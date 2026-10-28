# INV-DES-03 — 2026-10-18 23:49 巡检 / stale lease 恢复语义复核

本轮只读核对群内新建议、正式合同、共享任务板与相关源码；未运行 CLI、脚本、清理、测试、SQLite、Provider 或批次，未访问 runtime/真实数据/凭证/知识库/工作区外路径。

- **巡检基线：**系统采样 `2026-10-18T23:49:29+08:00`；本次 reminder occurrence `2026-10-18T15:49:29.700Z` 换算为 `23:49:29.700+08`，与采样一致。`team_task_list`为空、`list_agents`仅lead运行；群内新增wiki_manager、投研流程、投研复核与chief关于 lease release/stale 语义的只读消息。本目录目前有 `INV-DES-03-23-19-ADDENDUM.md` 与 `INV-DES-03-23-47-ADDENDUM.md`，未见群内提及的23:45附录文件；故不把其内容或C168映射当作本轮已读正式证据。合同状态仍`IN_PROGRESS/BLOCKED`、非`READY_FOR_CODE`；AC2/3/4/6/9未闭，候选SHA未冻结，无同SHA QA，全量ETA未知。

- **已核 claim 与 stale 语义：**逐读 `scripts/runtime_guard.py:109-128`，`claim_run()`读取已有run-state，只要其为truthy即拒绝，不检查`created_at`年龄、PID是否存活、owner process启动身份或租约更新/续期；payload记录`created_at`和`os.getppid()`。`assert_idle()`也按state存在及owner比较阻止（`:145-153`）。据源码可说当前代码没有自动stale lease判定；不得从此推断任意被中断任务必然永久阻塞，因为仍有显式release或外部人工恢复可能。

- **PID身份约束：**`getppid()`记录的是claim进程的父进程，不足以单独证明真实持租约writer仍存活或已终止；反过来直接改`getpid()`也不充分，因为领取命令、短命CLI、父shell、host-native writer/session可能有不同生命周期。PID还受复用、namespace和跨主机环境影响。Chief的判断已采纳：先界定lease实际owner/协调者与writer生命周期、运行环境身份和启动标识，再定义原子 stale 判定与恢复；在证据不足时禁止自动回收。

- **release/recovery入口：**`release_run()`存在state时校验owner，若调用者提供token则再校验token后删除；state缺失则静默return（`runtime_guard.py:131-142`）。CLI暴露显式`release-run`与`status`（`:233-269`），这是调用方/人工可用接口，不是自动stale恢复，当前由谁授权/执行与审计流程仍未定义。`recover-retry`只迁移retry reservation（`:244-267`及`:185-230`），不恢复run-state lease。正常native流程有release：`begin()`无重试/异常分支与终态`_archive_and_release()`按token调用release（`native_agent_tasks.py:482-547,947-965,979-1010`）；但SIGKILL/断电等不保证执行常规release，异常覆盖完整性也未运行验证。

- **对cleanup AC9的平衡要求：**禁止cleanup删除调用者自持/其他有效活动lease，且零删除、无检查后删除竞态；同时不能把cleanup留下的lease无条件自动删掉当作已设计恢复。AC9需定义owner生命周期、host/process身份、启动标识、判stale所需证据、原子化回收/审计、人工`release-run`授权与恢复提示，以及测试覆盖旧writer仍活动、强杀遗留state、PID复用/namespace等正负例。此设计未完成前，在无法证明stale时fail-closed并输出可审计的人工处置提示，不自动回收。全部动态/故障测试须另行授权，在同一不可变候选SHA上由独立工程QA复核。

- **责任/进度：**本轮只完成 stale/recovery 语义的静态核验与正式记录补充，不是全量consumer/writer/deleter/mode矩阵完成，不是工程QA，也不授权实现。主任务维持BLOCKED、非READY_FOR_CODE；全量ETA未知。下一责任人@investPM（owner本人）继续剩余静态矩阵；需另由有权人确认lease owner模型及人工恢复授权后，才能定稿自动/人工恢复契约。未运行任何项目代码或测试。
