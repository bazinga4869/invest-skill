# Claude 入口

Claude 的薄入口文件。完整 skill 说明见 [../SKILL.md](../SKILL.md)。

## 分析流程（独立 Agent 模式）

### 执行分析

```bash
# Step 1-4: 数据准备
cd ~/invest-skill
python3 shared/data_tools.py sync 603605.SH
python3 shared/data_tools.py all 603605.SH > /tmp/invest_data_603605.SH.json
python3 scripts/prepare_prompts.py 603605.SH

# Step 5: 并行执行 7 位独立专家
# 首选：用 Claude 原生 Task 子代理，每个子代理读一份
#   /tmp/invest_prompt_603605.SH_<expert>.txt，结果写入对应的
#   /tmp/invest_result_603605.SH_<expert>.md（详见 ../SKILL.md 第五步 spawn 模板）
# headless/cron 场景才使用 shell 脚本：
bash scripts/run_experts.sh 603605.SH --agent claude

# Step 6-8: 收齐结果
python3 scripts/collect_results.py 603605.SH --json
python3 scripts/assemble_report.py 603605.SH --name <公司名>
```

### Claude 专属注意事项

- Claude 使用 `claude --bare -p "$(cat prompt.txt)"` 模式
- `--bare` 确保非交互输出，适合脚本化执行
- 如果 Claude 支持并行调用，可以设置更高的`RUN_EXPERTS_CONCURRENCY`
