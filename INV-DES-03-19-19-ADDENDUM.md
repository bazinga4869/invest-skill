# INV-DES-03 — 2026-10-18 19:19 巡检与 cleanup caller 复核

只记录当前巡检与一个生产调用点的静态证据；不代表设计完成、运行通过或可启动清理。

- **巡检状态：**系统采样`2026-10-18T19:19:29+08:00`；本次occurrence `2026-10-18T11:19:29.700Z`换算为`19:19:29.700+08:00`，约差0.7秒，仅识别本轮提醒，不恢复历史C145–C158 occurrence映射。`schedule_list`每1800秒；task board为空、roster仅lead运行，无其他主矩阵ACK/交付；owner investPM。INV-DES-03仍IN_PROGRESS/BLOCKED、非READY_FOR_CODE；AC2/3/4/6/9未闭，候选SHA未冻结、无同SHA QA、全量ETA未知。
- **cleanup调用点静态复核：**仓内生产调用搜索只显示`assemble_report.py:1514`处调用 `cleanup_intermediates(ts_code, reports_dir=REPORTS_DIR)`；该默认调用未显式传`tmp_root`或`log_root`，所以cleanup保留import snapshot的runtime候选根并在调用时解析/环境覆盖日志根，同时报告根显式使用assemble的`REPORTS_DIR`。前置`assemble_report.main()`在`:1608`先`claim_run(finalize)`，进入`_main_locked`；报告先经门禁/归档/发布，在`:1508-1510`替换正式报告后，若无`INVEST_DEFER_CLEANUP=1`，才在`:1514`调用cleanup。由源码可确认该调用用途为finalize后本批清理；**不能**据此认为cleanup的全部候选都用统一或同一realpath根，也未见该caller在传参前逐项校验tmp/log/reports根与清单。删除实际根、调用进程环境和上游平台授权未验证。
- **上游风险边界：**`assemble_report`自己的顶层报告根为 `INVEST_REPORTS_DIR`或`configured_path(...)`（`:59-62`），而RUNTIME_ROOT来自`shared.runtime`；guard的lock也是runtime_guard。claim-run保证并发租约，不等价于cleanup目标路径allowlist。报告已发布后才cleanup；若cleanup root异常，源码能定位到非原子删除/错误结果可能性，但未测试、没有发生证据。若外层设置`INVEST_DEFER_CLEANUP=1`，本处不清理，调用者/后续cleanup责任方不在本次核验范围。
- **已核/未核及AC：**已核唯一可见Python生产调用点、显式reports_dir实参、runtime/log默认解析语义、finalize claim及cleanup相对发布的顺序。对应AC2（deleter调用与参数）、AC3（snapshot vs call-time根来源）、AC6/9（删除allowlist与坏根首副作用前拒绝）局部证据。未核shell/external/手动调用分母、外层defer cleanup后的责任链、有效path realpath及每个候选所有权、实际权限/owner、symlink/TOCTOU、删除中断恢复、越界零写入。
- **执行边界：**未运行cleanup、assemble、脚本、测试、CLI、SQLite、Provider或批次；未读runtime/报告产物/外部配置/真实数据/凭证/工作区外。
- **下一责任人/动作：**@investPM（本人owner）继续核`INVEST_DEFER_CLEANUP`外层cleanup调用路径及其他入口，更新deleter清单；全量ETA未知。动态删除与故障验证须另获授权并由独立QA复核。
