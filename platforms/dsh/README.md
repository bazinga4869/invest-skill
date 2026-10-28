# DSH 入口

完整协议见 [../../SKILL.md](../../SKILL.md)。

准备完成后运行：

```bash
python3 scripts/native_agent_tasks.py begin experts <code>
```

当前 DSH 主会话对返回的每个 `jobs[]` 调用原生 `subagent`（大量扇出可使用宿主原生
workflow），调用时不传 provider/model 覆盖。DSH in-process 子代理会继承父会话模型；
不要执行嵌套 `dsh --profile ...`，也不要调用 Codex/Claude CLI。

子代理按 `jobs[].instruction` 写 staging；主会话逐项运行 `commit`，最后运行 `advance`。
若子代理没有文件写权限，则主会话将其完整最终输出写入 `staged_output_path` 后再 commit。
