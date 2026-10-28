# INV-DES-03 — 2026-10-19 02:49 PM巡检与 release 能力闭环核验

> 03:19 增补：同日03:19对 `scripts/activity_log.sh:15-23,45-60` 的 writer 静态切片见本附录后续条目；不改变02:49采样记录。03:49 caller/root传递切片已加入正式合同及矩阵索引，不改变02:49附录原始巡检时点。

本轮执行只读巡检和设计记录更新；未运行代码、测试、CLI、cleanup、SQLite、Provider或批次，未访问runtime/真实数据/凭证/知识库/工作区外路径。

- **时序核对：**系统采样 `2026-10-19T02:49:29+08:00`；本轮提醒batch occurrence `2026-10-18T18:49:29.700Z` 换算为 `2026-10-19T02:49:29.700+08`，吻合。`schedule_list`中scheduledAt `2026-10-18T19:19:29.700Z`是之后的occurrence，而非本轮delivery时间。因用户batch occurrence才是本轮提醒的直接时间证据，现不混用schedule next tick/旧回复中的不同C编号。本记录不重建历史编号。

- **治理/执行核对：**task board查询为空；`list_agents`仅lead运行。无新成员ACK/全量矩阵交付。investPM仍为主矩阵owner；全量分母与ETA未知；INV-DES-03继续BLOCKED、非READY_FOR_CODE，candidate SHA未冻结、无同SHA工程QA。

- **release机制静态能力结论（新增已核事实）：**读`scripts/runtime_guard.py:131-142,233-258`，`release_run()`读取state；缺state静默返回；state存在时校验owner以及仅在token参数提供时才校验token，随后直接unlink。CLI `release-run`仅传ts_code/owner及可选token、直接调用该函数，代码中没有reason、操作者授权检查、先审计后释放或审计写入步骤。该程序行为与拟定AC9受控人工恢复SOP不相符，因此不只是“接口能力未知”：**当前实现不满足SOP且不得用于人工恢复放行**。这项静态事实不证明生产有遗留lease或有人实际绕过流程。

- **AC9决定与状态：**维持no-auto-reclaim；run-state存在即阻止新claim，cleanup不可代替lease recovery。人工`release-run`在新增受控接口/操作流程具备以下能力前一律禁用：验证授权维护者身份；要求owner与不可缺省token匹配；收集明确reason、旧writer已停止证据或授权风险签核；先将快照/hash与操作者、时间、证据写入受保护append-only审计并确认成功，之后才允许释放；任一身份/token/审计前置失败须保持state且非零退出。当前代码未实现这些控制，需作为后续工作区设计/实现任务提出；任何动态实现仍需单独授权、过READY门禁并由独立QA同SHA验证。本轮不修改代码，不授权人工删state，不使用cleanup、boot-id、心跳或force回收。

- **身份来源/RUN输入设计阻塞：**`checklist_audit --code`仍因可信batch identity/hash源未定义而执行A阶段fail-closed；暂停统计并不等于阶段B设计完成。下一步PM须给出manifest或显式调用输入候选，并逐项分析来源真实性/完整性、与冻结batch绑定、七expert唯一性/哈希、缺失/篡改/多个manifest/旧batch残留的拒绝规则，随后请投研复核评审；当前无已选可信源。

- **03:19矩阵切片—`activity_log.sh` writer：**逐读`scripts/activity_log.sh:15-23,45-60`，将已知生产writer落实到REM-02/AC2/AC4/AC6。`ACTIVITY_LOG`仅在调用方未预设时解析：依次取`INVEST_LOG_DIR/activity.jsonl`、`INVEST_SKILL_HOME/logs/activity.jsonl`、`$HOME/invest-skill/logs/activity.jsonl`；预设`ACTIVITY_LOG`可覆盖此优先级。每次`log_activity()`动态获取时间/agent后，`mkdir -p dirname`并用`>>`追加JSONL；未设置显式mode/owner/umask约束，无锁、原子替换或失败回滚机制。读静态代码未证明调用方、环境最终值、实际root/mode/并发效果；printf未校验/转义字段内双引号、反斜杠或换行，可能写入无效JSONL（条件性格式完整性风险，未动态验证）。本切片是已知模块写点语义补充，不增加模块分母；全仓writer/deleter分母仍未知。未运行脚本、未写日志或访问runtime。下一切片继续核一个此前未分类生产写删点并列出caller/实参/root/mode与故障边界；动态验证和权限stat仍未授权。

- **02:49时点下一责任人（03:19状态见主合同）：**@investPM（当前owner）提出batch identity可信来源候选与受控release API/SOP工作区设计，补齐REM-01..09一条新逐点矩阵切片后，再在群内真实@投研复核索取ACK/ETA和独立设计复核。完整矩阵ETA未知；检查点不等于完成ETA。
