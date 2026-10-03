#!/usr/bin/env python3
"""Antigravity CLI (`agy`) print-mode delegation wrapper.

Why this exists (measured 2026-09-16): `cd <workspace> && agy --print="…"`
is not enough for heavy tasks — the agy agent does not treat the process
cwd as the target repository and may spend most of its budget searching
for the "real" workspace (other drives, shell history, process args),
then time out. This wrapper closes that gap the same way the Codex
wrapper does: an explicit --cwd, a --task-file channel, and a workspace
anchor line injected at the top of every task so the agent never has to
guess where it is working.

Usage:
  python3 agy.py --cwd <workspace> (--task "<text>" | --task-file <path>)
                 [--timeout 25m] [--model <id>] [--effort low|medium|high]
                 [--output <path>] [--plan-mode] [--add-dir <path>...]
                 [--continue-session] [--no-anchor] [--allow-no-proxy]

代理硬校验：启动前要求 HTTPS_PROXY/HTTP_PROXY 已设置且端口可达，否则拒绝运行
（账号风控保护，见 enforce_proxy）。境外机器确无代理必要时用 --allow-no-proxy。

Exit codes: agy's exit code is passed through; 2 for wrapper misuse.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_TIMEOUT = "25m"  # 重任务经验值：5m 默认太短，15m 在带测试的审查上实测不够。

# 大陆网络裸连 Google 不只是"功能失败"（hang / fetch failed），还有账号风控风险——
# 反复以真实大陆 IP 触达 Google 服务可能触发账号安全审查。因此 wrapper 在启动 agy
# 前强制校验代理，宁可拒跑也不裸连（2026-10-01 豆哥确认此约束）。
PROXY_ENV_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


def extract_proxy_endpoint(raw: str) -> tuple[str, int] | None:
    """从代理环境变量值解析 host:port；支持 http://、socks5:// 与裸 host:port 形式。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    candidate = raw if "://" in raw else f"http://{raw}"
    parsed = urlparse(candidate)
    if not parsed.hostname or not parsed.port:
        return None
    return parsed.hostname, parsed.port


def enforce_proxy(allow_no_proxy: bool) -> None:
    """启动 agy 前的代理硬校验：未设置代理环境变量或代理端口不可达一律拒绝。"""
    if allow_no_proxy:
        return
    raw = next((os.environ[k] for k in PROXY_ENV_KEYS if os.environ.get(k, "").strip()), "")
    endpoint = extract_proxy_endpoint(raw)
    if endpoint is None:
        print(
            "agy.py: 拒绝启动——未检测到 HTTPS_PROXY/HTTP_PROXY 代理环境变量。\n"
            "  大陆网络裸连 Google 有账号风控风险，必须经由代理：\n"
            "  HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890 python agy.py ...\n"
            "  （仅在境外机器等确无代理必要的环境，可显式加 --allow-no-proxy）",
            file=sys.stderr,
        )
        sys.exit(2)
    host, port = endpoint
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except OSError:
        print(
            f"agy.py: 拒绝启动——代理 {host}:{port} 不可达（3s 探活失败）。\n"
            "  请先启动本地代理（如 Clash 7890 端口）再运行；跑代理前先探活可避免 agy 长时间挂起。\n"
            "  （确无代理必要的环境可显式加 --allow-no-proxy）",
            file=sys.stderr,
        )
        sys.exit(2)

ANCHOR_TEMPLATE = """[Workspace anchor / 工作区锚点]
All work for this task happens in this directory (it IS the target repository/workspace — do not search for, locate, or create any other project path):
{abs_path}
本任务的所有工作都在该目录内完成（它就是目标仓库/工作区，不要搜索、定位或创建其他项目路径）。所有命令都在该目录下执行。

"""


def parse_duration_to_seconds(text: str) -> int:
    """'25m' / '1500s' / '2h' → 秒。agy 接受 Go duration 字符串，这里只做校验与硬杀换算。"""
    m = re.fullmatch(r"(\d+)(ms|s|m|h)", text.strip())
    if not m:
        raise SystemExit(f"agy.py: invalid --timeout '{text}' (expected e.g. 25m / 900s)")
    scale = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    return max(1, int(float(m.group(1)) * scale[m.group(2)]))


def build_task(args: argparse.Namespace, cwd: Path) -> str:
    if bool(args.task) == bool(args.task_file):
        raise SystemExit("agy.py: provide exactly one of --task or --task-file")
    body = args.task or Path(args.task_file).read_text(encoding="utf-8")
    if args.no_anchor:
        return body
    return ANCHOR_TEMPLATE.format(abs_path=cwd) + body


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True, description="agy print-mode delegation wrapper")
    parser.add_argument("--cwd", required=True, help="目标工作区（绝对路径）；脚本将 cd 到这里并把路径注入任务锚点")
    parser.add_argument("--task", help="任务文本（与 --task-file 二选一）")
    parser.add_argument("--task-file", help="任务文件路径（长任务推荐，避免 shell 转义与长度问题）")
    parser.add_argument("--timeout", default=DEFAULT_TIMEOUT, help="print 超时（Go duration 格式，默认 25m）")
    parser.add_argument("--model", help="透传 agy --model")
    parser.add_argument("--effort", choices=["low", "medium", "high"], help="透传 agy --effort")
    parser.add_argument("--output", help="stdout 追加落盘到该文件（跨会话留存审查结果）")
    parser.add_argument("--plan-mode", action="store_true", help="透传 --mode plan（只读规划模式）")
    parser.add_argument("--add-dir", action="append", default=[], help="额外授权目录（可重复）")
    parser.add_argument("--continue-session", action="store_true", help="透传 -c 续接最近会话")
    parser.add_argument("--no-anchor", action="store_true", help="禁用工作区锚点注入（仅当你确知任务无需目录）")
    parser.add_argument("--allow-no-proxy", action="store_true", help="跳过代理硬校验（仅限境外机器等确无代理必要的环境）")
    args = parser.parse_args()

    enforce_proxy(args.allow_no_proxy)

    cwd = Path(args.cwd).resolve()
    if not cwd.is_dir():
        raise SystemExit(f"agy.py: --cwd is not a directory: {cwd}")

    task = build_task(args, cwd)
    timeout_seconds = parse_duration_to_seconds(args.timeout)

    cmd = ["agy", "--dangerously-skip-permissions", "--print-timeout", args.timeout, "--print", task]
    if args.model:
        cmd += ["--model", args.model]
    if args.effort:
        cmd += ["--effort", args.effort]
    if args.plan_mode:
        cmd += ["--mode", "plan"]
    for extra in args.add_dir:
        cmd += ["--add-dir", str(Path(extra).resolve())]
    if args.continue_session:
        cmd += ["-c"]

    # 硬杀保护：agy 自身有 --print-timeout（返回 partial 并退出），这里再加 120s
    # 缓冲兜底它彻底挂死的情况；两者取更晚的时刻。
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds + 120,
        )
    except subprocess.TimeoutExpired as error:
        print(f"agy.py: hard timeout after {timeout_seconds + 120}s (agy print-timeout did not fire)", file=sys.stderr)
        out = error.stdout or ""
        print(out)
        return 124

    sys.stdout.write(completed.stdout or "")
    sys.stderr.write(completed.stderr or "")
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(completed.stdout or "")
            handle.write(f"\n[agy-wrapper] exit={completed.returncode}\n")
    if "print timeout" in (completed.stdout or ""):
        print("agy.py: WARNING — agy hit its print timeout and returned partial output", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
