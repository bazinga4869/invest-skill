# INV-DES-03 — 2026-10-18 22:49 巡检 / cleanup 自删租约静态复核

本轮只读复核群内新增的 cleanup caller/lease 旁证；未运行 assemble、cleanup、cron、测试或批次，也未访问 runtime/真实数据/Provider/凭证。

- **巡检基线：**系统采样 `2026-10-18T22:49:29+08:00`；本次 reminder occurrence `2026-10-18T14:49:29.700Z` 换算为 `22:49:29.700+08`，与采样同刻。`team_task_list` 为空，`list_agents` 仅 lead 运行；无成员 ACK/主矩阵交付。主矩阵 owner 仍 investPM；INV-DES-03 `IN_PROGRESS/BLOCKED`、非 `READY_FOR_CODE`；AC2/3/4/6/9未闭，候选 SHA 未冻结，无同 SHA QA，全量 ETA 未知。该当前 occurrence 不能解决历史 C145–C166 映射。

- **assemble 自删 run-state 的源码时序已逐点复核：**`scripts/assemble_report.py:1593-1613` 的 `main()` 调 `claim_run(ts_code, "finalize")` 后进入 `_main_locked()`；finalize 成功发布分支在 `:1507-1509` 原子替换正式报告后，若非 `INVEST_DEFER_CLEANUP=1`，于 `:1514` 调 `cleanup_intermediates(ts_code, reports_dir=REPORTS_DIR)`，之后才从 `main()` 的 `finally` 在 `:1614-1618` 调 `release_run(..., token=lease["token"])`。cleanup 的 `tmp_root` 默认 `RUNTIME_ROOT`（`scripts/cleanup_intermediates.py:18,79-83`），候选精确含 `invest_expert_run_<code>.json`（`:22-34`）；`runtime_guard.run_state_path()` 返回相同文件名且默认 root 同源（`scripts/runtime_guard.py:17-19,30-32`）。因此源码可确认：在同一进程的非-defer finalize 路径，cleanup 会把该 finalize 调用者自己的 run-state 纳入删除候选，并在 `release_run()` 前执行删除。这里不是仅假设外部清理与活动 lease 重叠。

- **精确后果与边界：**`release_run()` 先读 run-state；缺文件时 `:133-135` 直接返回，不抛错。因此在清理成功删除 run-state 的路径上，后续 release 会静默返回，文件系统互斥在进程退出前解除；另一个 claim 可能在旧进程仍运行时成功。若 cleanup 对该候选删除失败，或执行 defer 路径，则此特定自删结论不成立。源码静态可证明该顺序/候选/缺失时行为，但未动态观测实际清理、重叠运行或并发 claim，不称已发生事故。

- **caller 对照：**cron 的 defer 路径由 `INVEST_DEFER_CLEANUP=1` 让 assemble 在 `:1511-1513` 提前返回，外层 Step 9 再调用 cleanup；这避免了 assemble 在仍持有 finalize lease 时走自身 cleanup，但外层 cleanup 仍没有 lease 检查，不能因此推断其他同标的 writer 不存在。此前“活动 lease 与 cleanup 重叠”的一般条件性风险仍适用于独立 CLI/人工调用者以及 cron 外层并发情形。cron `cleanup_tmp()` 还会额外 unlink `cron_agent_prompt_${TIMESTAMP}.txt`，须计入独立路径/权限矩阵；外层 cleanup 退出码传播问题继续以既有 AC9 记录为准。

- **AC9 设计验收要求（静态复核建议，未实现）：**(1) cleanup 不得删除调用者正在持有的 run-state；非-defer assemble finalize 必须保留 lease 至 `release_run()` 完成，需采用有原子语义的 lease-aware exclusion/设计，不可仅“检查后再删”造成 TOCTOU；(2) 对其他 owner 的活动 lease 或非终态状态，cleanup fail-closed 且断言零删除；(3) 同 SHA 故障/并发用例证明另一 claim 在旧 writer 完结前仍被拒绝，并证明 release owner/token 校验实际执行；(4) cron 额外 shell unlink 列入逐点 root/purpose/mode/owner 矩阵；(5) 清理完成判据使用命令退出码和残留枚举，`.cleanup.json` 在检索的 `.py/.sh` 范围内无消费者，仅作旁证；外层错误必须传播且不得报成功。所有动态验收需另行授权并由独立工程 QA 对同一不可变候选 SHA 复核。

- **状态/下一步：**这是静态设计证据，不是工程QA或动态 PASS；不解除主任务 BLOCKED，不标 READY_FOR_CODE。下一责任人 @investPM（owner本人）将本附录纳入正式合同并收紧 AC9；之后由 @投研复核 针对更新后的不可变合同版本做只读合同复核（待群内正式派工/ACK），ETA 未知。未经授权不做实现、动态验证或发布。
