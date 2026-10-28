# INV-DES-03 — 2026-10-18 20:19 巡检 / defer-cleanup 外层调用链

仅记录巡检及一段静态责任链，不代表cleanup调用者完整穷尽或动态验收。

- **巡检：**系统采样`2026-10-18T20:19:29+08:00`，schedule occurrence `2026-10-18T12:19:29.700Z`换算`20:19:29.700+08:00`，相差约0.7秒，仅识别本轮提醒，不裁定C145–C159历史事件。`schedule_list`仍每1800秒；task board为空，roster仅lead运行，无其他主矩阵ACK/交付；owner investPM。主任务仍IN_PROGRESS/BLOCKED、非READY_FOR_CODE；AC2/3/4/6/9未闭，候选SHA未冻结、无同SHA QA、完整矩阵ETA未知。
- **defer责任链静态复核：**`cron_trigger.sh:223-224`将`INVEST_DEFER_CLEANUP=1`仅注入单次DSH headless子进程环境；`assemble_report.py:1511-1514`在finalize发布成功后读取该flag，若为1则return不调用cleanup，外层wrapper收到成功标记后独立运行`verify_report --strict`与`verify_manifest`（`:367-370`），仅`PIPELINE_VERIFIED=1`后更新状态，最后进入Step 9调用`cleanup_tmp()`（`:399-412`；其函数`:275-280`运行cleanup_intermediates并删除cron prompt）。若agent失败或验证未通过，则`PIPELINE_VERIFIED`不为1并走失败退出（`:390-397`），不会走Step 9清理，保留中间文件。外层cleanup调用未显式传根参数：runtime候选用cleanup import-time `RUNTIME_ROOT` snapshot，logs按`INVEST_LOG_DIR`或`project_config.runtime_root()/logs`解析，reports使用cron的`REPORTS_DIR`。`cron_trigger` shell在`:32-36`导出persistent/operation变量，但headless/native之后是否保留尚未验证；即使wrapper导出也不能据此证明外层cleanup实值根同runtime/log/report根一致。静态确认的是resolver来源分立及不传参，实际路径是否相异、复核/清理是否成功、是否部分删除均未知。
- **边界更正/未知：**本轮在`cron_trigger.sh`确认defer设置与cleanup调用，没在`cron_prompt.txt`找到该env标记；因此源码上能确认的是shell确实注入，不推定headless Agent如何看见prompt里的流程文本。failure path刻意不调用外层cleanup，这是“保留现场”的行为，不代表cleanup入口全集已找到；兼容runner还提供用户提示的显式cleanup命令，另有CLI人工入口。除assemble直接调用、cron外层直接调用和CLI self-call外，完整可执行caller分母/人工入口仍待核。对未完成批次删除前需要确认idle/lease/终态授权，是AC9设计问题；本轮未运行。
- **已核/未核：**已核两个主要生产cleanup触发链的调用次序：assemble finalize成功后直接cleanup（`assemble_report.py:1514`）与cron通过defer后外层复核再cleanup（`cron_trigger.sh:223-224,367-412,275-280`），以及失败时保留中间文件的分支；确认cron cleanup不显式传tmp/log root。未核headless env过滤/转交、外层调用的运行时变量实值/根合法性、所有外部/人工调用、当前lease状态阻止清理、partial deletion rollback/receipt关联批次、实际mode/owner、TOCTOU、动态零写入/故障证据。
- **执行限制：**未运行cron/headless、assemble、cleanup、脚本/测试/CLI/SQLite/Provider/批次；未访问runtime、reports产物、HOME配置、真实数据、凭证或工作区外。
- **下一责任人/动作：**@investPM（本人owner）继续只读核剩余cleanup人工/兼容入口和lease/终态允许条件，将不可回滚删除负例纳入AC9；完整ETA未知。动态cleanup/故障验证须另外授权并由独立QA复核。

## 2026-10-19 13:23 +08 — Schedule巡检补记

- 时间依据用户提醒附带的系统采样`2026-10-19T13:23:04+08:00`；reminder payload未提供occurrence_at，因此不推算单独的投递ID或精确occurrence。
- 只读核对invest-skill群、唯一正式任务台账、共享任务板、agent roster及静态源码片段。未运行项目代码、测试、脚本、CLI、prepare/batch；未访问runtime、Provider或真实数据。
- `team_task_list`返回空；`list_agents`显示仅lead running，其他项目角色idle。不能把本地旧任务板条目或idle当作ACK/实际执行证明。
- 群内Chief最近裁定：TASK-3 review轮次A（限定阶段复核）已结束、FAIL整改已完成；轮次B（全范围）仍WAIT_ACK，直到剩余依赖交付并获得新ACK。投研复核已确认部分交付局部PASS、REM-02/04–09未覆盖；identity gate仍BLOCKED。
- 台账TASK-1为有界静态映射DONE；TASK-2仍IN_PROGRESS，完整REM映射与分母/ETA未知。现有REM-03矩阵记录了assemble finalize claim期间进入cleanup的静态调用顺序；已读`assemble_report.py:1378-1429,1507-1522,1608-1616`可佐证发布门禁、cleanup位于lease claim与finally release之间。该顺序仅是静态代码风险信号，不证明实际删除当前lease文件、并发写入或发生事故；无动态验证。
- 状态源保持：唯一仓内正式台账及群内裁定；共享任务板为空。下一责任为@investPM继续授权内静态REM核验；完整包完成后，群内真实@投研复核以获取新一轮ACK/拒绝及ETA。未为其他成员新派任务。
