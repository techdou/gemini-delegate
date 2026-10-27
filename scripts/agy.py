#!/usr/bin/env python3
"""Antigravity CLI wrapper: mandatory proxy, workspace anchor and failure triage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from proxy_guard import ProxyError, prepare_proxy

DEFAULT_TIMEOUT = "25m"
ELIGIBILITY_MARKERS = (
    "eligibility check failed", "not currently available in your location",
    "not available in your location", "account is not eligible", "account ineligible",
)
ANCHOR_TEMPLATE = """[Workspace anchor / 工作区锚点]
All work for this task happens in this directory (it IS the target repository/workspace — do not search for, locate, or create any other project path):
{abs_path}
本任务的所有工作都在该目录内完成，不要搜索、定位或创建其他项目路径。所有命令在该目录下执行。不得递归调用 Gemini/agy 委派技能。

"""


def diagnose_eligibility(stdout_text: str, stderr_text: str) -> bool:
    blob = f"{stdout_text}\n{stderr_text}".lower()
    if not any(marker in blob for marker in ELIGIBILITY_MARKERS):
        return False
    print(
        "agy.py: [资格检查被拒] 本轮调用失败，不自动重试。\n"
        "  仅凭这条错误不能确认封号，也不能排除服务资格/账号限制。\n"
        "  核对 Google 账号关联地区、年龄、账号类型与官方支持范围；本轮代理出口见上方。\n"
        "  OAuth 成功仅证明登录认证通过，不证明 Antigravity 服务资格正常。\n"
        "  Cloudflare 出口不代表 Google 域名一定走同一节点；请检查代理的分流规则。\n"
        "  如保留 --log-file 日志，分享前须删除 token、邮箱及任务内容。",
        file=sys.stderr,
    )
    return True


def parse_duration_to_seconds(text: str) -> int:
    match = re.fullmatch(r"(\d+)(ms|s|m|h)", text.strip())
    if not match or int(match.group(1)) == 0:
        raise ValueError("--timeout must be positive (e.g. 25m / 900s)")
    scale = {"ms": .001, "s": 1, "m": 60, "h": 3600}
    return max(1, int(int(match.group(1)) * scale[match.group(2)]))


def build_task(args: argparse.Namespace, cwd: Path) -> str:
    if args.task_file:
        path = Path(args.task_file).expanduser()
        body = (path if path.is_absolute() else cwd / path).read_text(encoding="utf-8-sig")
    else:
        body = args.task or ""
    if not body.strip():
        raise ValueError("task must not be empty")
    return body if args.no_anchor else ANCHOR_TEMPLATE.format(abs_path=cwd) + body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=".", help="目标工作区；默认当前目录")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--task")
    mode.add_argument("--task-file")
    mode.add_argument("--interactive", action="store_true", help="经保护的交互聊天，继承终端输入输出")
    mode.add_argument("--doctor", action="store_true", help="检查代理/出口/CLI help，不调用模型或触发登录")
    mode.add_argument("--models", action="store_true", help="经代理查询 agy models；可能检查服务资格")
    parser.add_argument("--proxy", help="HTTP 代理；优先于环境变量，缺省使用 127.0.0.1:7890")
    parser.add_argument("--timeout", default=DEFAULT_TIMEOUT)
    parser.add_argument("--model")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--output", help="print stdout 追加到文件，相对 --cwd")
    parser.add_argument("--log-file", help="CLI 日志路径，相对 --cwd；可能含敏感内容，仅本地保存")
    parser.add_argument("--plan-mode", action="store_true", help="透传 --mode plan")
    parser.add_argument("--dangerously-skip-permissions", action="store_true", help="显式启用 CLI 自动批准；默认遵守 CLI 权限")
    parser.add_argument("--add-dir", action="append", default=[])
    parser.add_argument("--continue-session", "-c", action="store_true")
    parser.add_argument("--no-anchor", action="store_true")
    args = parser.parse_args()
    print_mode = args.task is not None or args.task_file is not None
    try:
        cwd = Path(args.cwd).expanduser().resolve()
        if not cwd.is_dir():
            raise ValueError(f"--cwd is not a directory: {cwd}")
        if not print_mode and (args.output or args.no_anchor):
            raise ValueError("--output/--no-anchor require print mode")
        task = build_task(args, cwd) if print_mode else None
        timeout_seconds = parse_duration_to_seconds(args.timeout)
        cli = shutil.which("agy")
        if not cli:
            print("agy.py: agy executable not found", file=sys.stderr)
            return 127
        child_env, egress = prepare_proxy(args.proxy)
    except (ProxyError, ValueError, OSError) as error:
        print(f"agy.py: {error}", file=sys.stderr)
        return 2

    if args.doctor:
        try:
            result = subprocess.run([cli, "--help"], cwd=str(cwd), env=child_env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"agy.py: local help check failed ({type(error).__name__})", file=sys.stderr)
            return 1
        help_text = result.stdout + result.stderr
        capabilities = {flag: flag in help_text for flag in ("--print", "--print-timeout", "--mode", "--log-file")}
        ok = result.returncode == 0 and all(capabilities.values())
        print(json.dumps({"ok": ok, "cli": cli, "egress": egress, "capabilities": capabilities, "eligibility": "not checked; no model call", "proxy_scope": "child env + explicit CONNECT preflight; proxy server rules still apply"}, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    cmd = [cli]
    if print_mode:
        # 附着参数值，避免任务以 -- 开头时被解析为选项。
        cmd += ["--print-timeout", args.timeout, "--print=" + task]
    elif args.models:
        cmd += ["models"]
    if not args.models:
        if args.model:
            cmd += ["--model", args.model]
        if args.effort:
            cmd += ["--effort", args.effort]
        if args.plan_mode:
            cmd += ["--mode", "plan"]
        if args.dangerously_skip_permissions:
            cmd += ["--dangerously-skip-permissions"]
        for extra in args.add_dir:
            path = Path(extra).expanduser()
            cmd += ["--add-dir", str((path if path.is_absolute() else cwd / path).resolve())]
        if args.continue_session:
            cmd += ["-c"]
    if args.log_file:
        path = Path(args.log_file).expanduser()
        path = (path if path.is_absolute() else cwd / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd += ["--log-file", str(path)]
    try:
        if args.interactive:
            return subprocess.run(cmd, cwd=str(cwd), env=child_env).returncode
        completed = subprocess.run(cmd, cwd=str(cwd), env=child_env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_seconds + 120 if print_mode else 30)
    except subprocess.TimeoutExpired as error:
        print("agy.py: hard timeout; partial output is not a completed result", file=sys.stderr)
        out = error.stdout or ""
        sys.stdout.write(out.decode("utf-8", "replace") if isinstance(out, bytes) else out)
        return 124
    except OSError as error:
        print(f"agy.py: failed to start CLI ({type(error).__name__})", file=sys.stderr)
        return 126
    except KeyboardInterrupt:
        return 130

    stdout, stderr = completed.stdout or "", completed.stderr or ""
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    code = completed.returncode
    if diagnose_eligibility(stdout, stderr):
        code = code or 4
    elif "print timeout" in (stdout + stderr).lower():
        print("agy.py: partial result; print timeout", file=sys.stderr)
        code = code or 124
    elif not stdout.strip():
        print("agy.py: no result returned", file=sys.stderr)
        code = code or 1
    elif "agy_error:" in (stdout + stderr).lower():
        code = code or 1
    if args.output:
        path = Path(args.output).expanduser()
        path = path if path.is_absolute() else cwd / path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(stdout + f"\n[agy-wrapper] exit={code}\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
