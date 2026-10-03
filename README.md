# gemini-delegate (delegation skill)

一个 agent 技能（skill）：把有边界的任务委派给本地安装的 Google Gemini CLI——模型探测与选择、thinking 控制、会话延续、缓存感知的重复 PDF/多模态评审与写作。与 [codex](https://github.com/techdou/codex) 同构，主通道为 Antigravity CLI（agy），Gemini CLI 作为 fallback。

## 功能

- **模型探测**：探测可用模型与能力边界，按任务选型（`references/model-control.md`）
- **认证管理**：`scripts/auth_manager.py` 处理多路径认证状态（`references/authentication.md`）
- **会话延续**：跨多轮保持上下文，支持追问与迭代（`references/session-cache.md`）
- **健康自检**：`--doctor` 检查 CLI 安装/版本/登录态（`references/maintenance.md`）

## 安装

```bash
git clone https://github.com/techdou/gemini-delegate.git ~/.agents/skills/gemini-delegate
```

前置：本机已安装 Gemini CLI（或 Antigravity CLI）并完成认证。

## 用法

由 agent 按 `SKILL.md` 自动调度；手动体检：

```bash
python3 scripts/run.py --doctor
```

## 隐私注意

Gemini 免费层会收集交互数据用于改进。敏感内容（学术未发表工作等）请勿走免费层通道，细节见 `references/security.md`。

## 场景参考

| 认证、登录态与超时排错 | [authentication.md](references/authentication.md) |
| 模型选择与 thinking 档位 | [model-control.md](references/model-control.md) |
| 会话延续与缓存复用 | [session-cache.md](references/session-cache.md) |
| 沙箱与授权边界 | [security.md](references/security.md) |
| 健康检查、更新与回滚 | [maintenance.md](references/maintenance.md) |
| 与官方 Gemini CLI 的对应关系 | [official-cli.md](references/official-cli.md) |
| 典型委派工作流 | [workflows.md](references/workflows.md) |

非官方技能：由 TechDou 维护，与 Google 官方无关联。变更记录见 [CHANGELOG.md](CHANGELOG.md)。


## 目录

```
SKILL.md              技能入口（agent 读这里）
references/           分域参考：认证/模型控制/会话缓存/安全/维护
scripts/              run.py（入口）+ auth_manager.py + model_catalog.py
evals/                质量评估用例
```

## License

[MIT](LICENSE)
