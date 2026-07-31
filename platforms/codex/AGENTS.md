# Codex 入口

Codex 的薄入口文件。完整 skill 说明见 [../../SKILL.md](../../SKILL.md)。

## 分析流程（独立 Agent 模式）

### 前置依赖

1. **llm-wiki skill** — 已安装于 `~/.codex/skills/llm-wiki/`
2. **Tushare MCP** — 已配置 `codex mcp add tushareMcp`
3. **Python 3.10+** + `pip install -r requirements.txt`
4. **`config.yaml`** 中的 `analysis_date` 日常运行须为空；仅历史回测时显式钉住日期

### 执行分析

```bash
# Step 1-4: 数据准备（主 Agent 执行；prepare 会同步并校验数据）
cd ~/invest-skill
python3 scripts/prepare_prompts.py 603605.SH

# Step 5: 并行执行 7 位独立专家
# 首选：用 Codex 原生 subagent 机制，每个子代理读一份
#   /tmp/invest_prompt_603605.SH_<expert>.txt，结果写入对应的
#   /tmp/invest_result_603605.SH_<expert>.md（详见 ../../SKILL.md 第五步 spawn 模板）
# headless/cron 场景才使用 shell 脚本：
bash scripts/run_experts.sh 603605.SH

# Step 5.5: 二级魔鬼代言人质询（不可跳过）
python3 scripts/collect_results.py 603605.SH --json
bash scripts/run_challenges.sh 603605.SH

# Step 6-8: 裁判裁决 + 报告生成
python3 scripts/assemble_report.py 603605.SH --name <公司名>
# 主 Agent 撰写裁判长裁决（填写 assemble_report.py 生成的草稿占位符）
```

### Codex 专属注意事项

- `codex exec` 通过 stdin 接收 prompt：`cat prompt.txt | codex exec -`
- 并行执行时每个 `codex exec` 是独立进程，不会出现嵌套 spawn 问题
- 默认并发数 3，可在 `run_experts.sh` 中通过 `RUN_EXPERTS_CONCURRENCY` 环境变量调整
