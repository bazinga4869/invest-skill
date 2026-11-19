# INV-BATCH-08-REPAIR-03 · 阶段A：batch08 precommit gate 全绿（文本修复，止于 advance 之前）

- **TASK-ID：** `INV-BATCH-08-REPAIR-03`（阶段A，lead 2026-11-19 书面批准；见 `INV-BATCH-08-REPAIR-01/02` 的方案谱系）
- **状态：** `STAGE_A_DONE / PRECOMMIT_GATE_PASS`；**未** commit 任何专家结果、**未** advance。
- **批次：** `603605.SH-20261014-08`（`data_batch_id d4450143cd0858a8260f0bd4`，transaction `2e3c97d7805891517d1515eb`）
- **修复副本：** `batches/603605.SH-20261014-08-repair01/`（`supersedes: 603605.SH-20261014-08`；原批次目录只读、未改一个字节）
- **owner / 复核：** investPM（执行与证据）｜独立工程/文档复核：投研复核

## 1. 授权与边界

lead 批准的范围：把 batch 08 的 5 个 `gate_precheck` FAIL + 1 个 `expert_result_v3 compile` FAIL 逐个修到 `precommit_gate` 全绿，**停在 advance 之前**。

- 允许：读取批次控制面与我方 staging 输出、改文本、重跑 `compile` 与 `gate_precheck`、写 repair01 副本。
- 禁止（本轮全未做）：调用任何专家子代理、`commit`、`advance`、challenges、cross-review、裁决、`assemble_report`、report-wiki 物化、manifest 校验、复核签收、发布；不改 `config.yaml`、不改门禁代码、不改 `../invest-kb` 面板。

## 2. 结论（同一门禁、同一数据包、同一 prompt）

基线用权威门禁复检 batch08 既有的 `checks/<expert>.md`，结论与 batch08 `batch.json` 的 `precommit_gate_summary` **逐条一致**（负控成立：门禁没变，判词可复现）：

| 专家 | 基线 compile/precheck（复检 rc） | repair01 compile/precheck（rc） | 判词 |
|---|---|---|---|
| financial-auditor | PASS / FAIL（rc=1，untraced 1） | PASS / PASS（rc=0） | L56 |
| value-valuator | PASS / FAIL（rc=1，untraced 3） | PASS / PASS（rc=0） | L35×2、L83 |
| moat-analyst | PASS / FAIL（rc=1，untraced 1） | PASS / PASS（rc=0） | L80 |
| cognitive-controller | PASS / FAIL（rc=1，untraced 1） | PASS / PASS（rc=0） | L72 |
| macro-cyclist | PASS / FAIL（rc=1，untraced 1） | PASS / PASS（rc=0） | L78 |
| growth-assessor | FAIL / NOT_RUN | PASS / PASS（rc=0） | `calc 无法复算` → `calc formula 非法` → 通过 |
| management-auditor | PASS / PASS（rc=0） | PASS / PASS（rc=0） | 未改动 |

`repair01/batch.json` 的 `precommit_gate_summary` 即上表右列，`execution_status: PRECOMMIT_GATE_PASS`，`stop_reason` 明确写出「未 commit、未 advance」。

**修复后正文数值与修复前完全一致**：6 个 UNTRACED 数（0.7亿、8.2738、6.9478、25.77%、23.08%、16.62亿、12.0863、3.3897、225.67亿…）在渲染文本里仍是同一批值，[source]/[calc] 标签仍指向同一事实路径。全仓 `git diff` 级差异：financial-auditor 1 句、value-valuator 3 句、moat-analyst 1 句、cognitive-controller 1 句、macro-cyclist 1 句、growth-assessor 11 个 calc token，其余字节不变。

## 3. 逐条修复对照

门禁四类判定里，本批失败**全部**属于「左右文语义（`semantic_ok`）」与「calc 形态/量纲」，没有一条是数值与事实不符。

### 3.1 `semantic_ok` 触发的 5 位（改措辞，不动数字、不动来源）

`verify_number` 取数字左侧最后一段做 `SEMANTIC_PATH_RULES` 匹配：**匹配数 == 1 且该数字的 source 路径不含允许 token 时判 UNTRACED**；一句里塞多个语义类别（余额/营收/增长/现金）就会退化成单条匹配而失败。

| 专家 | 原文（判词指向的措辞） | 改为 | 依据 |
|---|---|---|---|
| financial-auditor L56 | `现有余额与收入锚点为{{F146}}{{F147}}{{F148}}{{F069}}{{F077}}{{F078}}` | `现有应收余额为{{F146}}{{F147}}{{F148}}；对应营收为{{F069}}{{F077}}{{F078}}` | 「余额」匹配账龄/坏账语境，直指 `accounts_receiv_yi`；拆句后营收独立成段 |
| value-valuator L35 | `得到 {{C:100/pe|F003}}%` | `得到 {{C:100*(1/market.pe_ttm)|F003}}` | 单位 `%` 由 `calculation_unit()` 自动拼接，模板里再写 `%` 就成 `…]%`（形态 B 失败）；同时 `100/pe` 的 `pe` 是别名，`evaluate_calculation` 只认 `current/previous` 或 inputs 的完整 JSON 路径 |
| value-valuator L35 | `粗略差额为 {{C:100/pe-shibor|F003,F149}} 个百分点` | `粗略差额为 {{C:100*(1/market.pe_ttm)-macro.indicators.shibor.week_pct|F003,F149}}` | 同上；**单位由「个百分点」变为 `%`**（`calculation_unit()` 只有 `%` 一档），见 §6 限制说明 |
| value-valuator L83 | `季度现金流样本为 {{F190}} 期` | `季度样本数为 {{F190}} 期` | 「现金流」语义与 `meta.report_history_years` 路径不匹配 |
| moat-analyst L80 | `证据：增长和现金创造可见 {{F010}}…` | `证据：利润复合增速 {{F010}}…` | 「增长/现金」双语义命中，而 F010 是 `profit_cagr_5y_pct` |
| cognitive-controller L72 | `证据：增长与现金流事实见{{F010}}、{{F011}}、{{F024}}、{{F025}}` | `证据：利润复合增速{{F010}}、营收复合增速{{F011}}、自由现金流{{F024}}、经营现金流{{F025}}` | 同上；逐项命名后每个数字的左侧语义唯一 |
| macro-cyclist L78 | `证据：个股估值与市值见 {{F001}}、{{F003}}、{{F004}}` | `证据：个股估值 PB {{F001}}、PE {{F003}}、总市值 {{F004}}` | 「估值/市值」歧义；PB/PE/总市值分别对应 `market.pb`/`market.pe_ttm`/`market.total_mv_yi` |

### 3.2 growth-assessor：`compile` 连挂两次，原因不同

1. **第一遍（原始失败）** `ExpertResultV3Error: calc 无法复算: selling_expense/revenue|F243,F202`。`evaluate_calculation` 的变量只能是 `current/previous/a/b/xN` 或 inputs 里**完整 JSON 路径**（确定性替换成 `xN`），`fcf`/`ocf`/`revenue`/`growth` 这类裸字段别名解析不到值 → `None` → 抛错。11 个 calc token 全是这种写法。
2. **第二遍（改完别名后暴露）** `calc formula 非法`。`shared/expert_result_v3.py:260-263` 的合法性是 `re.fullmatch(r"[A-Za-z0-9_+\-*/(). ]+", …)`——**方括号不在字符集内**，`annual.annual_data[10].revenue_yi` 这类带下标路径被拒。
3. **终态**：带下标的路径一律改成按 inputs 顺序取值的 `current/previous`（语义即「分子/分母」，与原文一一对应）；不带下标的（`market.pe_ttm/annual.profit_cagr_5y_pct`）保留完整路径写法。

其中 4 个费用率 token 还有**量纲错配**：分子 `*_yi`（亿）、分母 `revenue_yuan`（元），`units_compatible()` 严格相等故失败；即使强算也会得到 1e-8 级假比值。修复把分母换成同年度 `revenue_yi`（`F202`→`F077`=107.78、`F203`→`F078`=105.97），比值回到 0.4788 / 0.4963（销售费用收入比）、0.0195 / 0.0205（研发费用收入比）。

复核过的其它比值：PEG = 12.0863 / 25.77 = 0.469（原文「看似不高」一致）、FCF/OCF = 0.8979、OCF/净利 = 0.8142、FCF/净利 = 0.7568、净利率 = 0.1414、营收/总资产 = 1.2486、总资产/权益 = 1.3820。

## 4. 事实更正：`gate_precheck.py` 是存在的

`INV-BATCH-08-REPAIR-02.md` §1 记录「本机**不存在** `gate_precheck.py`、无 `INVEST_PANEL_TOOLS`」，据此把 AC 改成绑定 `build_expert_diagnostics`。**该结论已过期**：权威门禁实际位于
`/Volumes/MacData/workspace/invest/invest-kb/04_stock-analysis-expert/tools/gate_precheck.py`（108 行），
入场判据是 `<skill-root>/scripts/collect_results.py` 存在，脚本体内 `from scripts.collect_results import build_expert_diagnostics` ——**两者同源同版**，所以当时的替代判据在判词上并不错，错的只是「工具不存在」这一事实陈述。本轮基线复检与修复复检全部改用它本人跑，退出码 0/1/2。

`INVEST_PANEL_TOOLS` 环境变量仍未设置，调用时需显式给 `--skill-root` 与 `--runtime`。

## 5. 复现

```bash
R=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime
S=/Volumes/MacData/workspace/invest
PY=<python>=3.11 解释器

# 渲染（同 batch08 流程；失败时 stdout 为 {"status":"ERROR",...} 且 rc=2）
INVEST_RUNTIME_DIR=$R $PY $S/invest-skill/scripts/expert_result_v3.py compile 603605.SH <expert> \
    $R/batches/603605.SH-20261014-08-repair01/staging/<expert>.repair.v3.json \
    --sidecar /tmp/<expert>.v3.json --markdown /tmp/<expert>.md

# 权威门禁
$PY $S/invest-kb/04_stock-analysis-expert/tools/gate_precheck.py /tmp/<expert>.md \
    --expert <expert> --skill-root $S/invest-skill --runtime $R
```

负控：把上面第二步的输入换成 batch08 既有 `checks/<expert>.md`，六位 rc=1（untraced 1/3/1/1/1 + management rc=0），与 `batch.json` 记录一致。

## 6. 未做与限制（必须随结果一起读）

1. **provenance 变更**：本次修复是我（编排方）在 batch08 既有 staging 文本上做的**等值改写**，不是专家子代理重新产出。门禁全绿证明「这些文本可以通过门禁」，**不证明**专家自己能写出这版措辞。进入正式链路前需要二选一：专家按同一判词重跑产出，或由 lead/用户明确接受「编排方修正文本」这一来源。
2. **单位口径变化**：value-valuator 的「粗略差额」由「个百分点」改为 `%`（`calculation_unit()` 只有 `%` 一档，无一档可表达百分点）。数值 6.9478 不变，语义上「PE 倒数 − SHIBOR」本就是两个百分数的差，写 `%` 不失真，但与原文表述不同，属**已披露的措辞变更**。
3. **未验证项**：`commit`、`advance`、challenges、cross-review、裁决、`assemble_report`、report-wiki 物化、manifest 校验、复核签收、发布一律未跑；因此本次**不是**全链路 PASS、不是批次验收，也不代表 `execution_status` 可推进。
4. **既有瑕疵未修**：value-valuator 原文 `{{F149}}%` 渲染成 `1.326% [source: …]%`（多余的尾随 `%`），属原始模板问题，不在本轮判词范围内，未擅自改。

## 7. 产物

`batches/603605.SH-20261014-08-repair01/`：`batch.json`、`staging/*.repair.v3.json`（7）、`checks/*.md`、`checks/*.v3.json`、`checks/*.compile.log`、`checks/*.gate-precheck.log`。

| 文件 | SHA-256 |
|---|---|
| `batch.json` | `a06d225a124b8bb90f96c989c46ae2894b3627808a2d270a809f34a808a875f5` |
| `staging/financial-auditor.repair.v3.json` | `f7d25f965f69a20ce23e6ed17f4f4996b3fc543b6756b789ac3c02a46c3f3bf9` |
| `staging/value-valuator.repair.v3.json` | `b3facab73ee235908740d9a638c3b1695805547acd8d3a4ec6b96ac9e07201a2` |
| `staging/moat-analyst.repair.v3.json` | `611a96db11b581a2a1e32212bfa512f8f3785d27bd80093fb875ca354e6e0f04` |
| `staging/cognitive-controller.repair.v3.json` | `0ac376aa5be6a7c30e4be903005fe8944cc11c833e0d853c3781a010f219a885` |
| `staging/macro-cyclist.repair.v3.json` | `701ff513369293ecc4b736d11953050a484490084263217450b62c9742fc9d75` |
| `staging/growth-assessor.repair.v3.json` | `79e51352ba1bacc3a9f252f714d01994bad6dea992a51411d7aee3db4c5b67db` |
| `staging/management-auditor.repair.v3.json` | `a0c0e3b3563b0a685b59bed3dfb4888d7dfce98377c5a09fa9628811c34df91b` |

原批次 `603605.SH-20261014-08/` 全程只读；原始 7 份 staging 仍在
`evidence/native-experts-20261025/staging-next/`，未删除、未覆盖。
