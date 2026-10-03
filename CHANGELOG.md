# Changelog

## 1.5.1 - 2026-10-04

- rename: gemini → gemini-delegate（仓库与技能名，避免与 Google Gemini CLI 官方产品名混淆；旧链接 GitHub 自动重定向）
## Unreleased

- 新增 scripts/agy.py：agy print 模式委派包装器（--cwd 显式工作区 + 任务文件通道 + 双语工作区锚点注入 + 硬杀超时缓冲）。实测动因（2026-09-16）：重任务里 agy agent 不把进程 cwd 当目标仓库，全盘搜索定位耗尽 15m 预算零产出；agy 无原生 --cwd 参数，锚点必须写进任务文本。SKILL.md 的 Primary 节同步改为推荐包装器调用，裸调降级为 fallback 并补记实测坑。重任务二次实测（包装器+25m）：锚点生效不绕路（任务日志确认直接进入探索/测试），但 agy agent 循环在含测试执行的六面审查上 25m 仍未完成（Codex 同任务 ~15m 完成）——结论记入 SKILL.md：重交叉审查派 Codex，agy 留给中小任务或给足 40m+。

## 1.5.0 - 2026-09-10

- 首个公开发布：Gemini CLI 委派（模型探测、thinking 控制、会话延续、PDF/多模态评审）
- 认证管理器（多路径认证状态）
