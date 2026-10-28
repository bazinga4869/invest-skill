# INV-DES-03 — 2026-10-19 00:46 巡检 / calibrate_scores 新增调用与日志根缺陷

- **PM更正记录时间：**本附录系统采样为00:46:11+08；合同v4.34状态头采用00:45:51+08的提醒巡检采样。两者相邻但不相同，不混作一个发生时刻。

本轮只读核对群内补充与源码，未运行`calibrate_scores.py`、测试或shell；未读取runtime/activity数据或访问工作区外路径。

- **采样/基线：**系统采样`2026-10-19T00:46:11+08:00`；当前可见schedule提醒occurrence尚未随本轮交付提供，故不据此造新C编号。最新正式合同此前为v4.30、主任务`IN_PROGRESS/BLOCKED`、非`READY_FOR_CODE`；task board最近核为空，roster仅lead运行。全量consumer/writer/deleter及root/mode/allowlist矩阵未闭，候选SHA未冻结、无同SHA QA，完整ETA未知。

- **此前覆盖的切片及计数规则：**`calibrate_scores.py`双reader同次main调用是10:49已有切片；本轮再次核实同一调用事实，不计为新覆盖。此前合同的10:49记录也曾核其assemble调用时点；本轮不把旧调用关系重复登记为新增分母。本轮新增内容仅限下列能形成独立 AC/负例的语义。

- **旧覆盖补证（不计新增分母）：同次双reader调用关系：**`scripts/calibrate_scores.py:89-97` 的`main()`无条件先调用`get_current_scores()`再调用`get_historical_baselines()`；前者在`:39-50`从模块导入时固定的`RUNTIME_ROOT`读专家评分，后者在`:53-62`函数内调用`project_config.runtime_root()`并读`logs/activity.jsonl`。因此一次校准调用确实同时使用两来源；若两resolver实值不同，则会跨根读取。代码行序已由PM只读复核，投研流程/投研复核亦交叉核对；根实值、是否读到不同批次和生产发生情况未动态验证。

- **新增发现（独立AC语义；现实现的条件性失效，不是规范验收规则）：writer/reader未遵从`INVEST_LOG_DIR`的日志根契约缺口：**`scripts/activity_log.sh:15-23` 在未预设`ACTIVITY_LOG`时，优先从`INVEST_LOG_DIR`选`$INVEST_LOG_DIR/activity.jsonl`，其次`INVEST_SKILL_HOME/logs/activity.jsonl`，再退到`$HOME/invest-skill/logs/activity.jsonl`。`scripts/calibrate_scores.py`的历史reader在`:53-62`直接以`runtime_root()/logs/activity.jsonl`构造，不检查`INVEST_LOG_DIR`。当前实现的静默退化仅在调用环境设置`INVEST_LOG_DIR`、writer最终路径与reader路径不一致，且历史只存在于writer覆盖路径（reader根不存在或无相应记录）时成立：reader会将每专家基线按`n=0`返回（`:58-60`），输出“样本不足”而不诊断root mismatch（CLI表格见`:123-140`）。这只是条件性现实现路径，不是AC6规范：规范要求writer/reader解析根`realpath`不同即诊断`activity log root mismatch`并fail-closed；根相同但无匹配历史可按数据语义报告样本不足；根身份无法比较也fail-closed。实际生产根值、触发及是否导致错误建议均未验证。wiki_manager提供的`tests/integration_test.sh`行号仅为静态提示，本轮未逐行核该变量用法，也未运行测试。

- **新增C：文档/代码一致性：**模块docstring `:8`只写`logs/activity.jsonl`，未说明配置resolver或`INVEST_LOG_DIR`；`get_current_scores` docstring `:40`硬编码`/tmp/invest_result_*.md`，与实现使用`RUNTIME_ROOT`可能不一致。纳入AC7文档契约一致性检查；不是运行时错误已发生证据。

- **AC/设计建议（未实现、待复核）：**AC2/3要求current scores与activity writer/reader来源单一且同一调用显式可追溯；AC6的唯一失配条件是writer与reader解析的日志根`realpath`不同：不论reader目标是否存在/有记录，都必须显式诊断`activity log root mismatch`并fail-closed（非零退出），不得静默掩盖失配或自动按另一resolver回退。若realpath相同，则按该根的实际读取结果处理；同根但无匹配历史数据可按数据语义报告“样本不足”，不得误判为根失配。writer/reader根比较不可得或无法解析时按身份不可证处理，fail-closed。另：专家结果`--code`按glob拼接且无批次过滤/恰好七份校验，是wiki_manager新提的静态候选；尚未由PM逐行核验，不作为本附录已核事实或计数，待另行纳入矩阵核验。AC7同步docstring，删掉硬编码/tmp契约。实现方向可选共用`configured_path`/统一resolver或显式把日志文件root传入，但须先设计评估，不在此直接挑选或改代码。测试须使用隔离临时根与合成日志，不读取真实数据；动态测试另立获批叶并由独立QA在同一候选SHA复核。

- **归档/责任/剩余范围：**本附录为新增的calibration日志根语义切片，不缩减全仓矩阵去重分母；未补足消费者/读写删全量清单、所有逐写点mode/owner、SQLite sidecar、allowlist、坏根拒绝零写入及故障恢复证据。下一责任人@investPM继续按集中矩阵索引逐项核一个此前未分类生产写删路径；下个检查点只交一组准确行号/调用实参与剩余未核表，不宣称整体ETA。随后由@投研复核对更新合同中的此切片及之前no-auto-reclaim设计提案作独立只读审查；ACK前WAIT_ACK。主任务仍BLOCKED/非READY_FOR_CODE。未运行项目代码、测试、CLI或Provider。
