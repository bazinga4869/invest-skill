# INV-DES-03 — 2026-10-19 00:49 checklist_audit 准出门禁输入完整性静态复核

本轮只读核对 `scripts/checklist_audit.py`、`shared/checklist_verify.py` 及 `references/report-gates.md`；未运行脚本、CLI、测试、未读取runtime结果文件。

- **巡检基线：**系统采样`2026-10-19T00:49:29+08`；schedule occurrence `2026-10-18T16:49:29.700Z`换算为`2026-10-19T00:49:29.700+08`，相符。群内投研复核已完成v4.34此前复核并指出checklist新风险，Chief请优先纳入；task board最近视图为空，roster此前仅lead运行。当前合同v4.36，任务仍`IN_PROGRESS/BLOCKED`、非`READY_FOR_CODE`，全量矩阵ETA未知。

- **既有入口reader事实（不新增模块分母）：**`checklist_audit.py:16-29`中`report_path`分支按用户参数直接读取；`--code`分支对`RUNTIME_ROOT.glob(f"invest_result_{ts_code}_*.md")`所得全部路径排序、逐份`read_text`后拼接。`main()`只保证二选一参数存在（`:69-70`），`--code`规范化代码（`:71-76`）；结果只经print/JSON stdout（`:86-96`），该脚本未见文件写点。此前对reader/stdout-only分类已有覆盖，本轮不重复记为新consumer模块。

- **新增准出门禁输入风险（静态控制流）：**`read_target()`未校验glob匹配文件数量、每份专家身份、batch_id/哈希关系、重复/缺失专家或是否来自同一批次；只要至少命中一个文件就将全文并接（`:24-29`）。`data/experts.json:1-10`静态列出7个预期expert id，`shared.checklist_verify.verify_checklist()`使用固定expert_map分段并对七人逐个算覆盖（`:114-153`），但未验证输入集合恰好对应同一批次七份原始结果。汇总门禁可因此接受部分文件集合（缺失专家会形成空段，按0覆盖处理），也可能把残留/跨批次文档拼在一起影响覆盖统计；是否最终变PASS取决于拼接内容，静态源码不能断言必然虚高。准出契约`references/report-gates.md:11-13`将`checklist_audit.py --code`定位为七份结果之后的机器门禁、要求每位专家≥80%，所以输入身份/完整性属于该门禁输入可信度问题，不只是一般reader边界。

- **文案契约：**`checklist_audit.py:65` help称“审计 /tmp 中该代码的 7 份专家结果”，但实际读`RUNTIME_ROOT` glob，且目前未严格证明七份集合；需AC7同步文案与代码契约。属于新门禁相关发现，不增加模块去重分母。

- **AC6/AC7唯一fail-closed前置（PM v4.38决策，待独立复核/未实现）：**当前`--code`读取器和`verify_checklist`没有可信batch_id/hash来源，因此不得猜字段、把其他门禁身份字段当成当前七份文件绑定，或默默按文件名/顺序认定同批。**在可信身份来源及其与唯一冻结batch的绑定设计经独立复核前，任何`--code` glob命中集合均不得拼接计算覆盖率，必须明确报`checklist inputs not batch-verifiable`并返回非零；零命中另报missing input。**恢复正常计算前，设计必须指定受保护manifest或等价权威输入，证明与冻结batch绑定、包含七个唯一预期`expert_id`及每份哈希；缺失/重复/跨批次/哈希不符/身份不明一律FAIL，不静默丢弃任何glob命中文件。显式`report_path`也须满足权威身份与路径allowlist，不因用户提供而默认可信；help须反映实际RUNTIME_ROOT及身份要求。此为设计门禁，不代表当前实现已遵守。

- **最低正/负边界（后续获批动态验证才运行）：**正例：临时隔离root内同一冻结batch恰有七份唯一expert结果，审计按各自身份读取；负例：少于7份、重复expert、混合batch、遗留同代码旧结果、缺身份/hash mismatch、`report_path`越用途allowlist、glob结果包含符号链接越界，均应在读取/汇总前失败且零越界访问；同时断言stdout/退出码和门禁不会因拼接旧结果达标。不得用真实数据/runtime。当前无动态授权、未执行。

- **静态复核补充与范围限定：**投研复核本轮v4.36后续复核已给出此项FAIL；关键源码缺口得到印证：`read_target`没有身份输入/过滤，`verify_checklist`只从拼接文本按expert_id分段，二者均无batch_id/hash验证。当前提案要“按batch过滤”，但真实可信身份来源及如何绑定当前冻结batch尚未由读取器提供，不能直接视为可执行设计标准。需先设计唯一受信输入来源（例如由受保护manifest/调用方显式传入并与当前batch绑定），然后规定恰好7个唯一expert_id、每份哈希/身份一致；无来源、重复、缺件、跨批次均fail-closed。不得把此方案写成已实现，且需独立复核。help `/tmp`更正为代码文档AC。

- **状态/下一责任人：**这是一条已逐点核过的新AC语义，不增加consumer模块分母，但需要补到AC6/7矩阵和REM-01/AC6/7检查点。下一责任人@investPM整理并更新正式合同/索引；随后@投研复核按v4.36更新版本逐项复审（本轮请群内ACK/ETA，未ACK前WAIT_ACK）。全仓去重分母、逐写点mode/root/allowlist、no-auto-reclaim人工审计机制可实现性、候选SHA和同SHA QA仍未闭合。未运行代码、测试、CLI或访问runtime数据。
