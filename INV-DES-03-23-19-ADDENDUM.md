# INV-DES-03 — 2026-10-18 23:19 巡检 / cron deleter 与 lease caller 静态切片

本轮只读核对群、正式状态、任务板和授权范围内的源码切片；未运行脚本、cleanup、assemble、测试、CLI、SQLite、Provider 或批次，未访问 runtime/真实数据/凭证/知识库/工作区外路径。

- **巡检基线：**系统采样 `2026-10-18T23:19:29+08:00`；schedule occurrence `2026-10-18T15:19:29.700Z` 换算 `23:19:29.700+08`，与采样一致。`team_task_list` 为空、`list_agents` 仅 lead 运行；群内无 v4.21 复核后的新矩阵 ACK/交付。已于本轮之前验收投研复核对 v4.21 / 22:49 附录的静态合同复核：lease 自删与 AC9 设计结论一致，不是实现/工程QA PASS。实际owner仍investPM；状态仍 `IN_PROGRESS/BLOCKED`、非 `READY_FOR_CODE`，AC2/3/4/6/9未闭，候选 SHA 未冻结、无同 SHA QA，全量 ETA 未知。当前 occurrence 不能裁定历史 C145–C167 映射。

- **cron wrapper 独立 shell deleter：**只读 `scripts/cron_trigger.sh:275-280` 确认 `cleanup_tmp()` 先调用 cleanup CLI（`:278`），接着无条件执行 `rm -f "$RUNTIME_DIR/cron_agent_prompt_${TIMESTAMP}.txt"`（`:279`），然后写 log（`:280`）。该 unlink 是 cleanup 函数外独立删除点；需记录其构造根、用途、有效权限及 Step 8 失败时保留文件的边界。先前群内只读复核确认 Step 9 位于成功验证/state 更新之后，但成功门禁不等同 run-state/无并发检查；该 wrapper 中 `grep` 未见 `claim_run`、`assert_idle`、`read_run_state` 或 `run_state_path` 静态引用。grep 只作为定位手段，本结论限于我逐段读取的脚本，不把负向命中扩大成运行时/仓外证明。

- **lease claimant 可见性再核：**针对当前已读 `scripts/*.py` 范围，静态定位到 `claim_run` 调用：`native_agent_tasks.py:489,1062`、`prepare_prompts.py:1369`、`assemble_report.py:1608`；runtime_guard自身CLI另有 `:255`。shell claim 点先前由合同记录为 `run_experts.sh:433`、`run_challenges.sh:49`、`run_cross_reviews.sh:49`。显式 `assert_idle` 调用在 `prepare_prompts.py:1614`，其余cleanup/cron wrapper未见 lease guard 调用。此为已查源码范围的调用点矩阵切片，不是全仓/动态运行时完整性证明。

- **与既有 v4.21 结论关系：**assemble non-defer finalize 的自删 run-state 调用序列已于 [22:49附录](INV-DES-03-22-49-ADDENDUM.md) 和 v4.21 记录，并经投研复核合同静态审查；本轮不重复计为新证据。cron `cleanup_tmp()` 的 Python cleanup 退出码仍可能被随后的 `rm`/`log` 命令覆盖，需 wrapper显式保存/检查状态且不得在失败后报告成功；`.cleanup.json` 没有已检代码消费方，仍仅作旁证。额外shell unlink也要纳入逐点root/purpose/mode/owner表。上述要求不说明任一删除已在生产发生。

- **native release 语义交叉核对（只读）：**补核 `native_agent_tasks.py:482-497,540-547,947-965,979-1010`。`begin()` claim 后，无需重试时显式 release，异常时也尝试 release；正常 PASS 与终态 FAIL 都经 `_archive_and_release()`，先写归档/provenance，再按保存的 `guard_token` 调 `release_run()`，随后删 plan。故 cleanup 自删 lease 不是 native 唯一恢复路径；但若状态被提前删除，`release_run()` 缺状态时静默返回，正常 owner/token 校验会被绕过，旧 writer 尚存活时可能重新打开 claim 窗口。该核对是源码静态流程，不验证所有异常中 release 的可靠性，也不改变 assemble 自删路径事实。详见 `native_agent_tasks.py` 对应行号及 `runtime_guard.py:131-142`。

- **范围缺口：**全量生产 reader/writer/deleter 去重分母、每个写删点 root 实参与真实环境继承、mode/owner、用途子树 allowlist、fail-closed零副作用、symlink/TOCTOU、部分删除/恢复、所有人工/宿主外部调用者与状态门禁仍未完成。动态验证需另行授权；如授权，冻结候选SHA并由独立工程QA在同SHA验证。

- **下一责任人/动作：**@investPM（本人 owner）继续下一未分类生产写删路径与逐点 root/mode/allowlist 核对；预计下次30分钟巡检回报实际新证据及剩余范围，但这是检查点而非全量完成 ETA。需明确下一具体切片尚未选定；全量 ETA未知。不得因合同静态review通过而解除 BLOCKED 或开始编码/动态验证。
