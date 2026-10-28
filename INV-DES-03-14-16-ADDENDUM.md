# INV-DES-03 — 2026-10-18 14:16 巡检与 review 采纳

本补充为主合同 v3.95 的状态与证据记录。静态审查不代替设计验收、动态测试或工程 QA。

## 巡检状态
- 系统采样：`2026-10-18T14:16:52+08:00`。可读 reminder occurrence：`2026-10-18T06:15:51.179Z`，换算为 `14:15:51.179+08:00`，与采样约差61秒，不称同刻或据此作精确关联。
- `schedule_list` 显示巡检仍每1800秒；本会话实际 task board 查询为空、当前 roster 仅 lead 运行。没有其他主矩阵 ACK/交付；investPM仍是实际 owner。历史C145–C150映射尚无提醒服务原始投递关联，保持待核、不改历史。
- 任务继续 `IN_PROGRESS/BLOCKED`、非 `READY_FOR_CODE`；AC2/3/4/6/9未闭，候选SHA未冻结、无同SHA QA，全量矩阵ETA未知。无代码/测试/CLI/SQLite/Provider/批次执行，未访问runtime/真实数据/工作区外。

## 采纳复核并修正的静态结论
- 投研复核、Chief及wiki_manager的只读复核均指出：条件性 identity fallback 风险在 `collect_challenges.validate_challenge`，不是 `verify_manifest` 的 containment 绕过。现已在主合同与 `INV-DES-03-13-49-ADDENDUM.md` 明确收窄。
- `verify_manifest.py:480-482` 显式传 `base_dir=manifest_path.parent`。`collect_challenges.py:26-42` 对 prompt/result/original/data 主文件的读取使用传入目录。`verify_manifest.py` 对 manifest 路径还进行 reports-root containment 检查（行36-37、60-63，具体解析需在完整调用语境中按源码复核）；不再表述“任意异根 archive 被 verify_manifest 接受”。
- `collect_challenges.py:46-48` 在 archive data 缺 `market.trade_date` 或 `meta.batch_id` 时调用无 root 参数的 `expected_data_date/expected_batch_id`；定义于 `collect_results.py:119-140`，读模块级 `RUNTIME_ROOT/invest_data_<code>.json`。这使身份来源可能借用当前 runtime 活文件、降低 archive 校验自足性；是否触发、根是否不同均未知。
- 现有分支 `collect_challenges.py:43-59` 先基于 expected 值检查 frontmatter，随后检查 prompt identity line/hash。若 fallback 获取runtime值，会影响判词/identity校验；若取不到，空值比较也不必然意味着通过，仍有后续检查。未运行，故不声称“必然失败”“必然假PASS”或某个特定错误文本必然出现。需在授权的隔离测试设计中覆盖 archive 缺 `trade_date`、缺 `batch_id`、两者缺失、runtime有/无匹配文件，以及合法自足archive；断言不可从非archive root借值，并记录具体拒绝判词与零外部写入。这只是建议测试，不是执行证据。

## 调用点追核（有限范围）
- 已直接读取 `collect_challenges.py:110-129`：CLI `main()` 第120行调用 `validate_challenge(code, expert_id)` 不传 `base_dir`，因此按函数默认 `RUNTIME_ROOT`。CLI默认在runtime上验证，不属于archive显式调用。此点是本轮新增直接核验。
- `collect_results.py:119-140` 两个 identity helper 自身都固定读模块级 `RUNTIME_ROOT`，不接受 `base_dir`。跨目录调用者应以归档数据为权威，或显式拒绝缺字段；实现决策仍需设计批准，当前未修改代码。

## 四个额外调用点逐项复核（只读）
- `scripts/preserve_failure_evidence.py:41-46`：`_challenge_failures(code)` 作为失败证据收集器逐专家调用 `validate_challenge(code, expert)`，没有archive/base参数；函数在 `preserve_failure_evidence.py:57-63,83-90` 接受runtime_root、从该根读取data并列出同根现场，因此按当前诊断用途属于默认runtime读取，不是已证明错根。validator的字段fallback仍读模块snapshot；若传入runtime_root与import snapshot不同会有差异风险，实际根未验证。
- `scripts/prepare_cross_reviews.py:121-147`：CLI自身从模块 `RUNTIME_ROOT` 读取level3/data，用默认root的 `expected_batch_id/expected_data_date`，随后无base参数调用 `validate_expert` 与 `validate_challenge`，再向 `RUNTIME_ROOT` 写prompt。静态上是默认runtime流水线，不是archive调用；实际替代操作根/snapshot是否不同未验证。
- `scripts/native_agent_tasks.py:333-351`：`_review_repair_prompt` 在challenges phase调用validator不传base_dir；相邻逻辑从 `RUNTIME_ROOT`读result/rejected/error并向该运行根构造repair prompt，属native repair运行时诊断。其validator helper另用自身import snapshot；动态root同一性未核，未证明archive调用。
- `scripts/assemble_report.py:1346-1362`：`load_results/load_challenges` 和无base参数 `validate_challenge` 位于report `REPORTS_DIR.mkdir`之前；后续1362才建立REPORTS_DIR并构造draft/final路径。该点静态看是runtime报告输入校验，不是归档manifest validator。finalize是否另有归档期validator需完整追踪，本轮未据此推断。
- `scripts/collect_challenges.py:118-129`：CLI main逐专家调用 `validate_challenge(code, expert_id)` 不传base_dir，使用函数默认 `RUNTIME_ROOT`，属于runtime validator入口。
- **结论：**五处未传参调用均已按上下文分类；除CLI外四处分别为failure-runtime diagnostics、prepare default-runtime gate、native repair runtime diagnostics、assemble default-runtime input validation。静态源码没有证明这些调用收到不同root。后续应分别区分“helper固定snapshot”与“调用意图是否跨根”，不能按漏传个数直接认定错根。

## 验收状态与下一步
- 本轮切片仅支持 AC2（调用参数/root语义）与AC6（archive identity 自足/负例设计）局部静态证据，不关闭任何 AC。
- 未核：上述调用路径的动态root实值/环境组合、其余生产调用的完整分母；archive metadata缺失时的真实运行结果；逐写点mode/owner；用途allowlist/坏根前零写入；symlink/TOCTOU及故障恢复。候选 SHA 与同SHA QA仍缺。历史提醒映射仍需系统/Chief提供可审计原始关联。
- 下一责任人：@investPM（本人 owner）继续逐点只读矩阵核验，转向尚未分类生产调用/写点。全量 ETA 未知；不以检查点替代完成 ETA，不启动动态验证，除非相应有权人另行批准。
