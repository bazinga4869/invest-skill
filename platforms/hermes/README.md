# Hermes 入口

这是 Hermes 的薄入口文件。完整 skill 说明见 [../SKILL.md](../SKILL.md)。

## Hermes 专有说明

Hermes 不直接执行 7 专家分析（那是 LLM agent 的工作）。Hermes 负责：
- 数据管道：`python3 shared/data_tools.py sync-all-stocks`（cron）
- 定时触发：cron 调度 `scripts/cron_trigger.sh`
- Git push + 坚果云同步

Hermes 如需触发完整分析流程，应交给当前宿主 agent 执行 SKILL.md，并使用该宿主的原生子代理；不得硬编码或切换到 Codex/Claude CLI。宿主不提供原生子代理时应在模型调用前停止。
