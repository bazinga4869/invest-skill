# 报告准出规则

仅在生成草稿、裁判或排查发布失败时读取。

## 信任边界

裁判可在 `## 裁判自检（非独立复核）` 声明已检查事实、冲突、风险和仓位语义，但不得给自己打 90 分并把它当独立准出保证。发布可信度来自冻结控制面、机器 strict verification receipt、hash-bound adjudication receipt、publication receipt 与独立 manifest 复核；如需额外人工质量审阅，应另开独立 native draft reviewer，而不是复用裁判自评。

## 机器门禁

0. `prepare_prompts.py` / `validate_prompt_bundle.py`：绑定最新交易/公告查询水位、最新年度/半年度期次、prompt bytes/token 和未解析占位符；冻结完整控制面与 report-wiki 源码树。后续任一阶段哈希变化都必须重建批次。
1. `collect_results.py --check`：七份结果均满足 frontmatter、`data_date`、`batch_id`、章节、精确引用和必检项；VETO 的 `veto_triggers` 必须是非空字符串列表。
2. `checklist_audit.py --code`：每位专家结构化必检项覆盖率至少 80%。项目名须原样保留，状态为 DONE，证据须同时通过该项语义规则和真实路径/文档定位验证；MISSING 不计覆盖。
3. `collect_challenges.py`：7 份二级质询必须绑定原专家报告 SHA-256 及结构化 claim/evidence/assumption/risk/checklist/decision 输入束；受信任包装器从 prompt 逐字写入 3 个问题，模型只生成定性回应。verdict 只能为 `UNCHANGED/DOWNGRADED/UPGRADED`；非中性意见自动触发第三级。最终回应须为 180-360 个中文字符，覆盖不利情景、结论变化和可证伪数据，且不得包含阿拉伯数字、百分号或新增数字引用。
4. `verify_report.py --strict`：每个事实数字以紧邻其后的 `[source: JSON.path]` 溯源；同一行的来源不能互换。推导值使用可执行的 `[calc: (current/previous-1)*100; inputs: JSON.path,JSON.path]`，验证器必须重算到报告显示精度且结果单位匹配。数组下标路径完整解析。历史极值断言必须明确指标、同行绑定 `[history-check: 标准化序列路径]`，并在同份报告中逐项引用全部可用期间；验证器跨段收集证据并重算最新值。管理层带年报定位的逐字引文不视为专家认可。无来源行业/历史断言为失败。
5. `assemble_report.py --finalize`：重复上述检查，验证综合裁决 YAML、hash-bound knowledge refs、现有/新增/总仓位语义、七份专家原文和七份质询回应均唯一嵌入、三级触发判定与机器重算一致；如触发，3 个独立身份交叉盲审必须匿名化原作者/评分/verdict，绑定输入/prompt 哈希并逐字聚合。先验证注入 manifest 标记后的临时最终字节，再生成 adjudication/verification/publication receipts、记录 finalize `GATES PASS`，最后才原子发布。不存在 `--allow-missing` 绕过路径。
6. `verify_manifest.py <正式报告>`：验证报告引用的 manifest 存在、路径未越界，数据/report-wiki bundle 与引擎源码树/确定性年报视图/执行元数据/完整冻结控制面/7 专家 prompts/results/7 质询 prompts/results/三级判定/draft/final/各类 receipt 证据齐全；发生 retry 时还必须重算 retry ledger 内每份 plan、任务书、repair、diagnostics 和 rejected raw 的哈希。第三级触发时还必须包含 3 份交叉盲审 prompts/results 和聚合原文。每个文件大小/哈希必须正确，正式报告与归档副本必须一致。
