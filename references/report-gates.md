# 报告准出规则

仅在生成草稿、裁判或排查发布失败时读取。

## 信任边界

裁判可在 `## 裁判自检（非独立复核）` 声明已检查事实、冲突、风险和仓位语义，但不得给自己打 90 分并把它当独立准出保证。编排方只调度和转录，不得自行形成或改写投资结论。裁判须由与编排分离的独立原生子代理形成裁决，投研复核须由另一独立复核者对最终待发布草稿明确签收；不得复用裁判自评，也不得以条件触发的三级盲审替代全报告发布复核。发布可信度来自该签收、冻结控制面、机器 strict verification receipt、hash-bound adjudication receipt、publication receipt 与 manifest 复核；机器验证不能替代投研复核签字。

## 机器门禁

0. prepare 后 begin 前必须通过面板工具 `injection_gate.py`，核对七份 prompt 必须规则与同批身份；每份专家 staging 在 commit 前必须通过 v3 compile 和对渲染 Markdown 的 `gate_precheck.py`。工具不可用或失败不得跳过；保留诊断，按唯一修复流程处理。
0. `prepare_prompts.py` / `validate_prompt_bundle.py`：绑定最新交易/公告查询水位、最新年度/半年度期次、prompt bytes/token 和未解析占位符；冻结完整控制面与 report-wiki 源码树。后续任一阶段哈希变化都必须重建批次。
1. `collect_results.py --check`：七份结果均满足 frontmatter、`data_date`、`batch_id`、章节、精确引用和必检项；VETO 的 `veto_triggers` 必须是非空字符串列表。
2. `checklist_audit.py --code`：每位专家结构化必检项覆盖率至少 80%。项目名须原样保留，状态为 DONE，证据须同时通过该项语义规则和真实路径/文档定位验证；MISSING 不计覆盖。
3. `collect_challenges.py`：7 份二级质询必须绑定原专家报告 SHA-256 及结构化 claim/evidence/assumption/risk/checklist/decision 输入束；受信任包装器从 prompt 逐字写入 3 个问题，模型只生成定性回应。verdict 只能为 `UNCHANGED/DOWNGRADED/UPGRADED`；非中性意见自动触发第三级。最终回应须为 180-360 个中文字符，覆盖不利情景、结论变化和可证伪数据，且不得包含阿拉伯数字、百分号或新增数字引用。
4. `verify_report.py --strict`：每个事实数字以紧邻其后的 `[source: JSON.path]` 溯源；同一行的来源不能互换。推导值使用可执行的 `[calc: (current/previous-1)*100; inputs: JSON.path,JSON.path]`，验证器必须重算到报告显示精度且结果单位匹配。数组下标路径完整解析。历史极值断言必须明确指标、同行绑定 `[history-check: 标准化序列路径]`，并在同份报告中逐项引用全部可用期间；验证器跨段收集证据并重算最新值。管理层带年报定位的逐字引文不视为专家认可。无来源行业/历史断言为失败。
5. 裁判 YAML 必须声明具体 `adjudicator.identity`；`position_advice.scope` 必须明确 `general_research` 或 `personalized`。通用研究 `user_context=null`、`existing_position_action=NONE`、`new_allocation_pct=0`，总上限仅为研究情景；个性化必须绑定同批次完整且明确授权的用户上下文，缺失即拒绝。`BUY/PASS` 不再强制正新增仓位。
5. `research_review.py <code> --reviewer-identity <实际身份> --orchestrator-identity <实际身份> --verdict PASS --statement '<原始复核意见>'`：登记独立投研签收，绑定 batch_id、完整草稿 hash、裁判和编排身份。任何草稿变更须重新复核；声明身份只提供可审计约束，不是密码学身份认证。
5. `assemble_report.py --finalize`：强制检查独立投研签收及同批次执行台账；缺失、FAIL、身份不独立或草稿 hash 不匹配即禁止发布。重复上述检查，验证综合裁决 YAML、hash-bound knowledge refs、现有/新增/总仓位语义、七份专家原文和七份质询回应均唯一嵌入、三级触发判定与机器重算一致；如触发，3 个独立身份交叉盲审必须匿名化原作者/评分/verdict，绑定输入/prompt 哈希并逐字聚合。先验证注入 manifest 标记后的临时最终字节，再生成 adjudication/verification/publication receipts、记录 finalize `GATES PASS`，最后才原子发布。不存在 `--allow-missing` 绕过路径。
6. `verify_manifest.py <正式报告>`：验证报告引用的 manifest 存在、路径未越界，数据/report-wiki bundle 与引擎源码树/确定性年报视图/执行元数据/完整冻结控制面/7 专家 prompts/results/7 质询 prompts/results/三级判定/draft/final/各类 receipt 证据齐全；发生 retry 时还必须重算 retry ledger 内每份 plan、任务书、repair、diagnostics 和 rejected raw 的哈希。第三级触发时还必须包含 3 份交叉盲审 prompts/results 和聚合原文。每个文件大小/哈希必须正确，正式报告与归档副本必须一致。
