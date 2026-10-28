# INV-DES-03 — 2026-10-18 23:47 巡检 / stale lease 恢复语义只读审查

本轮只读核对群内新建议与 `scripts/runtime_guard.py`、`scripts/native_agent_tasks.py` 的源码。未运行 CLI、脚本、清理、测试或批次，未访问 runtime/真实数据/Provider/凭证。

- **巡检/状态：**系统采样 `2026-10-18T23:47:30+08:00`，距上次可见 PM 回复约25分钟；该时刻没有新 schedule reminder payload，本附录不虚构 occurrence/C编号。任务板此前查询为空，roster此前仅 lead 运行；群内新增静态核验指出 native claim 后存在显式 release 路径，Chief 要求 stale owner/PID 判定先设计，证据不足禁止自动回收。项目仍 BLOCKED、非 READY_FOR_CODE；候选 SHA 未冻结、无同 SHA QA，全量 ETA 未知。

- **stale 判断：**`runtime_guard.claim_run()` 仅读取当前 run-state；只要 `existing` truthy 即拒绝新 claim（`:109-118`）。payload 写 `created_at` 与 `pid=os.getppid()`（`:119-127`），本函数该 claim 路径未据年龄、PID、进程存活或启动身份判定 stale。`assert_idle()` 也是按 state 是否存在及 owner 比较而拒绝（`:145-153`）。当前源码因此没有可见的自动 stale lease 回收策略；“永久阻塞”仅可表述为在没有人工/外部处理且此状态文件持续存在时后续 claim 会持续拒绝，不能断言所有故障均无恢复办法。

- **PID 身份边界：**代码记录的是 parent PID（`os.getppid()`），而非该 CLI/进程的自身 PID；但不能简单将其替换为 `getpid()` 来判断实际 writer 存活，因为 claim CLI 与持租约 writer 生命周期未必相同。任何 stale 判定至少需先定义 lease 实际 owner（进程、父/宿主、会话或协调器）、持有者生命周期、PID namespace/复用、进程启动时标/boot identity、跨主机/机器边界以及原子 claim/renew/release语义。缺少这些证据时不得自动回收或将 PID 不可见等同 stale。

- **可见恢复接口：**`runtime_guard.py:233-269` 提供显式 `release-run`（可选 token）和 `status` 子命令；`release_run()`若 state 存在会校验 owner 与传入 token（`:131-142`），但 state 缺失会静默返回（`:133-135`）。此接口是人工/调用方可用的显式恢复/释放机制，不是自动 stale 回收；是否受授权、由谁调用及生产操作程序未核。`recover-retry`（`:244-267`）针对 retry reservation 格式迁移，不能当作 run-state lease recovery。

- **native release 与 cleanup 关系：**native `begin()` 对无重试与异常分支尝试 release，终态 PASS/FAIL 经 `_archive_and_release()` 按 guard token release（既有23:19附录及源码）。因此cleanup并非 native 唯一正常 release 路径；但异常/被强杀时不保证finally执行，且无 stale 自动恢复的源码门禁。cleanup 删除 lease 可能绕过 owner/token 校验并在旧 writer 仍活动时开放并发；同样不能把“存在正常 release路径”推成所有异常都可恢复。

- **AC9 设计决策建议：**(1) 禁止cleanup无条件删除调用者自持/任何有效活动 lease；必须避免检查后删除TOCTOU；(2) 不把“owner非自己且看起来无PID”作为自动删除许可；先定义并验证租约owner生命周期、身份字段、失效判定、跨主机语义及原子恢复/审计；在该设计获批准前，无法安全证明 stale 时应 fail-closed并输出明确人工恢复说明；(3) 人工 `release-run` 需身份/owner/token与告警/审计流程，不要把无token宽松调用当默认自动恢复；(4) 构造有意中断/旧writer仍活动/失效owner/ PID复用与namespace等负例，冻结同一候选 SHA 后由独立 QA 验证，所有动态操作需另授权；(5) 将 stale recovery 定义列为 AC9未闭合项，不因正常路径 release 而删除 stale recovery需求，也不擅自新增自动回收实现。

- **下一责任人/动作：**@investPM（owner）将上述owner/stale恢复语义写入合同，保持 BLOCKED/非 READY_FOR_CODE；后续需 PM/授权方明确手动恢复策略与可用身份信息，再设计独立动态测试与QA任务。当前没有已批准的自动 lease回收或动态验证权限；全量ETA未知。
