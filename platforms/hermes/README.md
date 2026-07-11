# Hermes 入口

这是 Hermes 的薄入口文件。完整 skill 说明见 [../SKILL.md](../SKILL.md)。

## Hermes 专有说明

Hermes 不直接执行 7 专家分析（那是 LLM agent 的工作）。Hermes 负责：
- 数据管道：`python3 shared/data_tools.py sync-all-stocks`（cron）
- 定时触发：cron 调度 `daily_analysis.py`
- Git push + 坚果云同步

Hermes 如需触发完整分析流程，应调用 Codex 或 Claude Code 执行 SKILL.md。
