# Codex 入口

完整协议见 [../../SKILL.md](../../SKILL.md)。

## 运行

先准备同批次数据，再由**当前 Codex 主 agent 的原生子代理能力**执行任务：

```bash
cd ~/invest-skill
python3 scripts/prepare_prompts.py 603605.SH --force-sync
python3 scripts/native_agent_tasks.py begin experts 603605.SH
```

主 agent 读取 `jobs[]`，使用宿主原生 delegate/subagent 并行委派，且不设置 provider/model
覆盖。子代理完成后逐项 `commit experts`，全部提交后执行 `advance experts`。质询和条件触发
的盲审同样使用 `begin challenges` / `begin cross-reviews`，不得调用其他产品 CLI。

## Codex 约束

- 子代理自然继承当前 Codex 主 agent 的 provider/model、认证和会话谱系；不要另启
  `codex exec`，也不要切换到 Claude/DSH。
- 子代理严格执行 `jobs[].instruction`；宿主不允许子代理写文件时，主 agent 把其完整
  返回写入 `staged_output_path`，再运行 commit。
- 宿主没有原生子代理能力时，在任何模型调用前停止，不做外部 fallback。
- 初次失败不自动重跑；每个认知阶段每批只允许一次 native `--retry`。
- 遇到互斥冲突先用 `runtime_guard.py status <code>` 查明所有者，不直接删除门禁。
- 三个 `run_*.sh` 仅为用户明确 opt-in 的外部 CLI 兼容层，不是标准入口。
