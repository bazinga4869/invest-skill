# Claude 入口

Claude 的薄入口文件。完整 skill 说明见 [../SKILL.md](../SKILL.md)。

## 分析流程（独立 Agent 模式）

### 执行分析

```bash
# Step 1-4: 数据准备（prepare 会同步并验证数据）
cd ~/invest-skill
python3 scripts/prepare_prompts.py 603605.SH

# Step 5: 并行执行 7 位独立专家
# 首选：用 Claude 原生 Task 子代理，每个子代理读一份
#   /tmp/invest_prompt_603605.SH_<expert>.txt，结果写入对应的
#   /tmp/invest_result_603605.SH_<expert>.md（详见 ../SKILL.md 第五步 spawn 模板）
# headless/cron 场景才使用 shell 脚本：
bash scripts/run_experts.sh 603605.SH

# Step 5.5: 收齐结果并独立执行二级质询
python3 scripts/collect_results.py 603605.SH --json
bash scripts/run_challenges.sh 603605.SH

# Step 6-8: 裁决与报告
python3 scripts/assemble_report.py 603605.SH --name <公司名>
```

### Claude 专属注意事项

- **宿主环境**：在 Claude Code 对话中直接使用 `Task` 工具 spawn 7 位专家子代理（SKILL.md 首选路径），不通过 CLI spawn。
- **headless/cron 场景**：改用 Codex CLI（`codex exec`）作为独立 agent 后端，不再使用 `claude --bare -p`。
- 如果 Claude 支持并行 Task，可以设置更高的`RUN_EXPERTS_CONCURRENCY`。
