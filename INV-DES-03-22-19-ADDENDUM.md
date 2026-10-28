# INV-DES-03 — 2026-10-18 22:19 巡检 / cleanup caller 分母补充

本轮只读盘点cleanup调用点，不运行cleanup或验证。

- **巡检：**系统采样`2026-10-18T22:19:29+08:00`；occurrence `2026-10-18T14:19:29.700Z`换算`22:19:29.700+08`，约差0.7秒，仅识别本轮提醒，不恢复C145–C165映射。task board空、roster仅lead运行，排程每1800秒；没有新矩阵ACK/交付。主任务保持`IN_PROGRESS/BLOCKED`、非`READY_FOR_CODE`，AC2/3/4/6/9未闭、候选SHA未冻结、无同SHA QA、全量ETA未知。
- **仓内生产调用者：**仅定位到`assemble_report.py:1514`函数内调用以及`cron_trigger.sh:278,411`外层CLI调用。assemble调用在finalize成功发布后、无defer时传`reports_dir=REPORTS_DIR`，tmp/log未传（详见19:19附录）。cron调用不传roots，且仅在前置headless报告/manifest验证成功及state更新后进入Step 9；失败路径不调用cleanup（详见20:19附录）。同一cron wrapper在cleanup函数内继续删除该次`cron_agent_prompt` (`cron_trigger.sh:279`)，这是python cleanup之外的单独shell deleter，不能与python返回码混作一件事。
- **shell compat范围：**`run_experts.sh:503,507`、`run_challenges.sh:151`、`run_cross_reviews.sh:147`只打印“用户确认后显式清理”的命令提示；本轮读取的对应片段里没有自动执行cleanup。提示文本不是调用证据。CLI `cleanup_intermediates.py:161-165`自调用函数，属于人工/直接入口；没有确认其外部操作者或实际运行。
- **测试范围：**本轮`*.py`检索只确认`tests/test_runtime_contracts.py:129-136,160-165`直接调用函数，给三个TemporaryDirectory roots做基本删除/保留断言；未发现测试通过CLI启动cleanup。未运行测试；不能据调用文字/测试源码宣称生产删除全覆盖。
- **静态调用者分母/限制：**当前仓内源码生产调用候选=assemble direct+cron wrapper CLI；另有脚本内人工命令提示和CLI入口。此口径只限可见仓内调用，不能排除人工/宿主直接触发、未来入口或工作区外调用。已知各root的实际runtime实值、外层host环境、上游lease/终态防护、CLI人工授权、cleanup失败部分删除后的实际状态均未验证。
- **AC9/交接要求：**@investPM（本人owner）继续核cleanup实际leaf callers及上游idle/终态门禁；将外层cron exit status传播、手工CLI是否需带run_id/lease检查、shell额外cron prompt unlink作为独立目标处理。交付是带行号/调用方式/roots/前置状态的调用者清单；完整ETA未知。未经授权不运行动态清理/测试；如获授权需独立QA对同一候选SHA验证lease活动零删除、失败零/部分删除语义、receipt与run绑定及cron success propagation。
