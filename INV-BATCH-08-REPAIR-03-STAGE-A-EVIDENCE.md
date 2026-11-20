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

**口径**：这里的「全绿」只指 `precommit_gate_summary` 七位专家的 `compile` + `precheck`。同一 `checks` 块里仍有 `data_quality: WARN`（3 条）、`report_wiki.summary_status: UNAVAILABLE`、`sage_wiki: DEGRADED`，与本轮无关也未修；对外只能说「**专家 precommit 门禁 7/7**」，不能说「批次门禁全绿」。

**修复后正文数值与修复前完全一致**：6 个 UNTRACED 数（0.7亿、8.2738、6.9478、25.77%、23.08%、16.62亿、12.0863、3.3897、225.67亿…）在渲染文本里仍是同一批值，[source]/[calc] 标签仍指向同一事实路径。全仓 `git diff` 级差异：financial-auditor 1 句、value-valuator 3 句、moat-analyst 1 句、cognitive-controller 1 句、macro-cyclist 1 句、growth-assessor 11 个 calc token，其余字节不变。

## 3. 逐条修复对照

门禁四类判定里，本批失败**全部**属于「左右文语义（`semantic_ok`）」与「calc 形态/量纲」，没有一条是数值与事实不符。

### 3.1 `semantic_ok` 触发的 5 位（改措辞，不动数字、不动来源）

`verify_number` 取数字左侧最后一段做 `SEMANTIC_PATH_RULES` 匹配：**匹配数 == 1 且该数字的 source 路径不含允许 token 时判 UNTRACED**；一句里塞多个语义类别（余额/营收/增长/现金）就会退化成单条匹配而失败。

| 专家 | 原文（判词指向的措辞） | 改为 | 依据 |
|---|---|---|---|
| financial-auditor L56 | `现有余额与收入锚点为{{F146}}{{F147}}{{F148}}{{F069}}{{F077}}{{F078}}` | `现有应收余额为{{F146}}{{F147}}{{F148}}；对应营收为{{F069}}{{F077}}{{F078}}` | 「余额」匹配账龄/坏账语境，直指 `accounts_receiv_yi`；拆句后营收独立成段 |
| value-valuator L35 | `得到 {{C:100/pe|F003}}%` | `得到 {{C:100*(1/market.pe_ttm)|F003}}` | 两处独立问题：①模板字面 `%` 与渲染补出的单位重复，成 `…]%`；②`100/pe` 形态不满足 `calculation_unit()` 的 `*100` 形状，推不出 `%`。**已更正**：旧稿把原因写成「`pe` 别名解析不到值」，与 `evaluate_calculation` 的语义别名绑定逻辑不符（见 §3.4） |
| value-valuator L35 | `粗略差额为 {{C:100/pe-shibor|F003,F149}} 个百分点` | `粗略差额为 {{C:100*(1/market.pe_ttm)-macro.indicators.shibor.week_pct|F003,F149}}` | 同上。**单位仍为「百分点」**（2026-11-19 第二轮已由 `calculation_unit()` 新增百分点档支持，见 §8）；旧稿「单位变为 `%`」的说法作废 |
| value-valuator L83 | `季度现金流样本为 {{F190}} 期` | `季度样本数为 {{F190}} 期` | 「现金流」语义与 `meta.report_history_years` 路径不匹配 |
| moat-analyst L80 | `证据：增长和现金创造可见 {{F010}}…` | `证据：利润复合增速 {{F010}}…` | 「增长/现金」双语义命中，而 F010 是 `profit_cagr_5y_pct` |
| cognitive-controller L72 | `证据：增长与现金流事实见{{F010}}、{{F011}}、{{F024}}、{{F025}}` | `证据：利润复合增速{{F010}}、营收复合增速{{F011}}、自由现金流{{F024}}、经营现金流{{F025}}` | 同上；逐项命名后每个数字的左侧语义唯一 |
| macro-cyclist L78 | `证据：个股估值与市值见 {{F001}}、{{F003}}、{{F004}}` | `证据：个股估值 PB {{F001}}、PE {{F003}}、总市值 {{F004}}` | 「估值/市值」歧义；PB/PE/总市值分别对应 `market.pb`/`market.pe_ttm`/`market.total_mv_yi` |

### 3.2 growth-assessor：`compile` 连挂两次，原因不同

1. **第一遍（原始失败）** `ExpertResultV3Error: calc 无法复算: selling_expense/revenue|F243,F202`。**根因（2026-11-19 复核更正）**：F243 = `annual.annual_data[10].sell_expense_yi` = 51.61 **亿**，F202 = `annual.annual_data[10].revenue_yuan` = 10778411781.2 **元**，两者量纲差 1e8 倍，比值 51.61/1.078e10 = **4.79e-9**。`evaluate_calculation` 的「输入是否真的参与运算」扰动校验用 `math.isclose(perturbed, value, rel_tol=1e-10, abs_tol=1e-10)`，对 5.16e-4 / 1.08e5 的扰动只产生 **4.79e-14** 的绝对变化，**被 abs_tol 吞掉** → `dependent_inputs=0` → 返回 `None` → 抛「无法复算」。所以报错文字说的是「算不出来」，真正原因是**量纲错配把一个合法公式压到 1e-9 量级**；旧稿「裸别名解析不到值」的解释**错误**，`selling_expense`/`revenue` 按顺序绑定 inputs 的语义别名机制是生效的（`scripts/verify_report.py:391-419`）。
2. **第二遍（改完别名后暴露）** `calc formula 非法`。`shared/expert_result_v3.py:258-260` 的合法性是 `re.fullmatch(r"[A-Za-z0-9_+\-*/(). ]+", …)`——**方括号不在字符集内**，`annual.annual_data[10].revenue_yi` 这类带下标路径被拒。
3. **终态**：带下标的路径一律改成按 inputs 顺序取值的 `current/previous`（语义即「分子/分母」，与原文一一对应）；不带下标的（`market.pe_ttm/annual.profit_cagr_5y_pct`）保留完整路径写法。
4. 4 个费用率 token 的**量纲错配**：分子 `*_yi`（亿）、分母 `revenue_yuan`（元），`units_compatible()` 严格相等故失败；即使强算也会得到 1e-8 级假比值。修复把分母换成同年度 `revenue_yi`（`F202`→`F077`=107.78、`F203`→`F078`=105.97），比值回到 0.4788 / 0.4963（销售费用收入比）、0.0195 / 0.0205（研发费用收入比）。
   **遗留**：`evaluate_calculation` 目前**不校验 calc 操作数量纲是否可比**，只靠「算不出来」兜底；量纲错配若恰好落在 1e-3~1e3 区间（例如 `亿/亿` 与 `元/元` 混用但同量级）仍可能被静默接受。已记为独立缺陷，未在本轮修。

复核过的其它比值：PEG = 12.0863 / 25.77 = 0.469（原文「看似不高」一致）、FCF/OCF = 0.8979、OCF/净利 = 0.8142、FCF/净利 = 0.7568、净利率 = 0.1414、营收/总资产 = 1.2486、总资产/权益 = 1.3820。

### 3.3 repair01 全部改动的分类表（label-only / formula / unit）

**声明：repair01 只作证据与门禁回归夹具，不得作为发布来源。** 它是编排方在 batch08 文本上的改写副本，不产出报告、不进 `assemble_report`、不参与任何交付物。
机器记录里真正承载这一 provenance 的是 `batch.json` 的 `repair.mode: "text-only"` 与 `repair.expert_invocation: "none (no expert subagent was called; …)"`，以及 2026-11-20 补写的 `repair.unit_model_repair.provenance`；`stop_reason` 只说明「本轮未 commit/advance」，**不是**常设禁止句（投研复核 2026-11-20 指出，已按此更正）。

| # | 位置 | 类型 | 改动 | 数值/来源是否变 |
|---|---|---|---|---|
| 1 | financial-auditor L56 | label-only | 一句拆两句（「余额与收入锚点」→「应收余额为…；对应营收为…」） | 否 |
| 2 | value-valuator L35（收益率） | formula | `100/pe` → `100*(1/market.pe_ttm)` | 否（8.2738 不变） |
| 3 | value-valuator L35（收益率） | unit | 删模板字面 `%`，改由渲染补 | 否 |
| 4 | value-valuator L35（利率） | unit | `{{F149}}%` → `{{F149}}`（去掉重复单位） | 否（1.326 不变） |
| 5 | value-valuator L35（差额） | formula | `100/pe-shibor` → `100*(1/market.pe_ttm)-macro.indicators.shibor.week_pct` | 否（6.9478 不变） |
| 6 | value-valuator L35（差额） | unit | 保留「个百分点」，但改由 `calculation_unit()` 补（原先靠模板字面） | 否 |
| 7 | value-valuator L72（checklist） | formula + unit | `100/pe`、`100/pe-shibor` 同步改成全路径形态；删除两侧字面 `%`/`个百分点` | 否 |
| 8 | value-valuator L83 | label-only | 「季度现金流样本为」→「季度样本数为」 | 否 |
| 9 | moat-analyst L80 | label-only | 「增长和现金创造可见」→「利润复合增速」 | 否 |
| 10 | cognitive-controller L72 | label-only | 四个数字逐项命名（利润复合增速/营收复合增速/自由现金流/经营现金流） | 否 |
| 11 | macro-cyclist L78 | label-only | 「个股估值与市值见」→「个股估值 PB/PE/总市值」 | 否 |
| 12 | growth-assessor 11 个 calc token | formula | 裸别名/带下标路径 → 按 inputs 顺序的 `current/previous` | 否 |
| 13 | growth-assessor 4 个费用率 | unit | 分母 `revenue_yuan`（元）→ `revenue_yi`（亿），消除 1e8 量纲错配 | **是**（比值从 4.79e-9 级回到 0.4788/0.4963 等真实比率） |
| 14 | management-auditor | 无改动 | — | — |

**审计结论**：13 类改动里只有 #13 改变了计算结果的含义（把假比值修成真比率，属必要修复），其余 12 类都是标签或单位表述；#2/#5/#7 的公式改写不改变数值，只改变「能否被 `calculation_unit()` 推出单位」。#6 在旧口径下曾被写成 `%`（错误），现已回到「百分点」——这是本轮返工的对象。

### 3.4 更正：`calc` 的裸字段别名**是可解析的**

`evaluate_calculation`（`scripts/verify_report.py:391-419`）在显式别名（`current/a/x1`、`previous/b/x2`…）绑定后，会把**剩余未绑定 inputs 按出现顺序分给未知名**，并记录为 `semantic_aliases` 参与扰动校验。因此 `fcf/ocf`、`selling_expense/revenue` 这类写法本身能算；真正让它们失败的是量纲错配（§3.2 第 1 条）和带下标路径的字符合法性（§3.2 第 2 条）。旧稿把两类原因都归为「别名解析不到」，不成立，已按本条更正。

## 4. 事实更正：`gate_precheck.py` 是存在的

`INV-BATCH-08-REPAIR-02.md` §1 记录「本机**不存在** `gate_precheck.py`、无 `INVEST_PANEL_TOOLS`」，据此把 AC 改成绑定 `build_expert_diagnostics`。**该结论已过期**：权威门禁实际位于
`/Volumes/MacData/workspace/invest/invest-kb/04_stock-analysis-expert/tools/gate_precheck.py`（108 行），
入场判据是 `<skill-root>/scripts/collect_results.py` 存在，脚本体内 `from scripts.collect_results import build_expert_diagnostics` ——**两者同源同版**，所以当时的替代判据在判词上并不错，错的只是「工具不存在」这一事实陈述。本轮基线复检与修复复检全部改用它本人跑，退出码 0/1/2。

`INVEST_PANEL_TOOLS` 环境变量仍未设置，调用时需显式给 `--skill-root` 与 `--runtime`。

## 5. 复现

```bash
R=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime
S=/Volumes/MacData/workspace/invest-skill            # skill 本体（有 scripts/collect_results.py）
K=/Volumes/MacData/workspace/invest/invest-kb        # 知识库/专家面板（有 04_stock-analysis-expert/tools）
PY=<python>=3.11 解释器

# 渲染（同 batch08 流程；失败时 stdout 为 {"status":"ERROR",...} 且 rc=2）
INVEST_RUNTIME_DIR=$R $PY $S/scripts/expert_result_v3.py compile 603605.SH <expert> \
    $R/batches/603605.SH-20261014-08-repair01/staging/<expert>.repair.v3.json \
    --sidecar /tmp/<expert>.v3.json --markdown /tmp/<expert>.md

# 权威门禁（--skill-root 必须是 $S，不是 $K；给错会 rc=2「✗ skill 根目录不对」）
$PY $K/04_stock-analysis-expert/tools/gate_precheck.py /tmp/<expert>.md \
    --expert <expert> --skill-root $S --runtime $R
```

> 勘误（2026-11-19，investQA 复核发现）：本节初版把 skill 根写成 `$S/invest-skill`（`S=/Volumes/MacData/workspace/invest`），
> 该路径不存在，照抄会 7/7 全 rc=2。skill 本体与 `invest-kb` 是**同级不同目录**，已按实际路径拆成 `$S` / `$K`。
> 门禁结论不受影响：换成真实根后 7/7 rc=0，负控仍逐条复现。

负控：把上面第二步的输入换成 batch08 既有 `checks/<expert>.md`，六位 rc=1（untraced 1/3/1/1/1 + management rc=0），与 `batch.json` 记录一致。

## 6. 未做与限制（必须随结果一起读）

1. **provenance 变更**：本次修复是我（编排方）在 batch08 既有 staging 文本上做的**等值改写**，不是专家子代理重新产出。门禁全绿证明「这些文本可以通过门禁」，**不证明**专家自己能写出这版措辞。进入正式链路前需要二选一：专家按同一判词重跑产出，或由 lead/用户明确接受「编排方修正文本」这一来源。
2. **单位口径（已返工）**：旧稿曾把「粗略差额 6.9478 个百分点」写成 `6.9478%`，并辩称「两个百分数之差写 % 不失真」——**该说法错误**，两个百分数之差是百分点。2026-11-19 第二轮已在门禁里补「百分点」档（见 §8），恢复为 `6.9478 个百分点`，数值 6.9478 不变。
3. **未验证项**：`commit`、`advance`、challenges、cross-review、裁决、`assemble_report`、report-wiki 物化、manifest 校验、复核签收、发布一律未跑；因此本次**不是**全链路 PASS、不是批次验收，也不代表 `execution_status` 可推进。
4. **既有瑕疵（已修）**：value-valuator 早期模板 `{{F149}}%` 会渲染成 `1.326% [source: …]%`（多余尾随 `%`）。第二轮已删掉模板里的字面单位，并把 `]%`/`] 个百分点` 这类「token 自带单位 + 模板又拼一个」纳入阻塞诊断（见 §8）。
5. **repair01 非自包含**：`artifacts.prompt_bundle_validation_log` / `injection_gate_log` 仍指向 batch08 目录（同一 `data_batch_id`，语义上成立），归档或迁移时必须连同 batch08 一起带走。
6. **`execution_status` 无校验器**：该字段在仓库代码里没有 schema 约束（batch08 的 `BLOCKED_PRECOMMIT_GATE` 同样如此），属描述性字段，不能当门禁状态机使用。

## 6.1 独立复核

- **investQA（独立工程 QA，2026-11-19）**：PASS。复跑 135 OK / 默认入口 rc=3 / 3.9 门槛 rc=2；确认 `4cfc351` 只改 3 个 hunk 且断言未动（legacy 分支 `ok/bad/check` 一条未改）；正向门禁 7/7 rc=0、负控逐条复现；把 7 份 staging 重新 compile 得与 `checks/*.md` **字节级相同**，证明 md 由 payload 生成而非手写；剥掉 `[source:]`/`[calc:]` 后正文数字多重集与 batch08 完全一致；batch08 全目录 mtime 未变。唯一必改项是本文件 §5 的复现路径（已勘误）。

## 6.2 provenance 决定（lead 书面裁定，2026-11-20）

**`repair01` 只作证据与门禁回归夹具，不得作为发布来源。** 任何对外报告必须由专家按同一判词重跑产出。

- 裁定来源：lead 于 2026-11-20 的书面决定（B3），适用范围**卡死在本批次证据**。
- 因此 `repair01` 的状态是「门禁证据 + 回归夹具」，不是「批次产出」：它不进 `assemble_report`、不做 report-wiki 物化、不参与 manifest 校验、不发起复核签收，也不构成任何交付物。
- 全链路是否跑、跑到哪一步，仍属用户授权范围，不由本条决定。
- 该前提同时写入群 goal 第 3 阶段（待用户批准全链路时作为前置条件之一）。

### 6.3 投研复核 会签（阶段A 证据链）

| 项 | 内容 |
|---|---|
| 签收人 | 投研复核（只读复核，非实现方） |
| 时间 | 2026-11-20 09:26 +08 |
| 快照 | `28190f1`（`origin/main`，`ahead=0`） |
| 结论 | **PASS**，阻塞 0，建议 4 条（已按 lead 归属分派，均不阻塞） |
| 背书范围 | **仅「证据链与门禁回归」**——不背书全链路、不背书批次验收、不背书 `execution_status` 可推进 |
| 复核方式 | 自己重渲、自己跑权威门禁、自己算哈希：receipt §2 改前 blob `07211fcb…`(17878B) 对上；§3 的 A–E 五条判词逐条实跑复现；§5 七个 SHA-256 全部命中 |
| 重申的边界 | `repair01` **不得作为发布来源**（同 §6.2） |

## 7. 产物

`batches/603605.SH-20261014-08-repair01/`：`batch.json`、`staging/*.repair.v3.json`（7）、`checks/*.md`、`checks/*.v3.json`、`checks/*.compile.log`、`checks/*.gate-precheck.log`、`failure-archive/growth-assessor/`（失败件存档，供负控重放，见 `INV-BATCH-08-REPAIR-04-UNIT-RECEIPT.md` §7）。

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

## 8. 第二轮（2026-11-19）：门禁补「百分点」档，把口径错误变成可判定

背景：lead 实证 `{{C:…}} 个百分点` 编译后渲染成 `6.9478% [calc: …] 个百分点`，权威门禁仍 **rc=0**；根因是 `scripts/verify_report.py:567` 把「百分点」无条件折成 `%`，门禁在构造上判不出单位对错。裁定：**补一档百分点单位**，不改字回避。

### 8.1 改动（4 个文件，均未提交）

| 文件 | 改动 |
|---|---|
| `scripts/verify_report.py` | `calculation_unit()` 新增百分点档（常量取「个百分点」，`normalize_report_unit()` 兼容「百分点/个百分点」两种写法）：顶层 `A-B` 且两个操作数单位都是 `%` → `百分点`（优先于 `*100` 比值规则）；`normalize_report_unit()` 不再把「百分点」折成 `%`；新增 `detect_unit_conflicts()`（两类：`%` 紧邻「百分点」= `percent_adjacent_percentage_point`；`]` 后紧跟 `%`/「个百分点」= `unit_duplicated_after_token`） |
| `scripts/collect_results.py` | `build_expert_diagnostics()` 把 `detect_unit_conflicts()` 结果并入既有 `invalid_calculations`（不新增类别键，权威门禁的 `FAIL_CATEGORIES` 立即生效） |
| `shared/expert_result_v3.py` | 新增 `_join_number_unit()`：推导出的计算单位若以非 ASCII 开头（如「百分点」「元」）与数字之间补一个空格，渲染为 `6.9478 个百分点 [calc: …]`；事实 token（`[source:]`）保持原字节 |
| `tests/test_report_gates.py` | 新增 2 条回归：`test_percentage_point_difference_is_traceable_in_percentage_points`（差值写法必须 DERIVED）、`test_percent_next_to_percentage_points_is_blocked`（`%`+百分点 与 `]%` 双单位必须阻塞）；并把既有 `test_percentage_points_list_indexes_and_assumption_ranges` 的期望单位由 `"%"` 改为 `百分点`（**有意改断言**，原断言正是错写法的通行证） |

### 8.2 验证（命令 + 输出）

```bash
PY=<python 3.11.17>; S=/Volumes/MacData/workspace/invest-skill
R=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime
G=/Volumes/MacData/workspace/invest/invest-kb/04_stock-analysis-expert/tools/gate_precheck.py

# ① 单测
$PY -m unittest discover -s tests -p "test_*.py"        # → Ran 137 tests, OK（原 135 + 新增 2）

# ② 从 staging 重渲 value-valuator（模板已删字面单位）
INVEST_RUNTIME_DIR=$R $PY $S/scripts/expert_result_v3.py compile 603605.SH value-valuator \
  $R/batches/603605.SH-20261014-08-repair01/staging/value-valuator.repair.v3.json \
  --sidecar /tmp/out/value-valuator.v3.json --markdown /tmp/out/value-valuator.md   # → COMPILED, rc=0
# 渲染结果：8.2738% [calc: 100*(1/market.pe_ttm); …]
#           6.9478 个百分点 [calc: 100*(1/market.pe_ttm)-macro.indicators.shibor.week_pct; …]

# ③ 权威门禁（正例）
$PY $G /tmp/out/value-valuator.md --expert value-valuator --skill-root $S --runtime $R
# → ✓ 全部诊断为空，可以 commit    rc=0

# ④ 权威门禁（反例：同一份把 % 与 个百分点 叠在一起）
#    L35 改成 "6.9478% [calc: …] 个百分点" 后
# → ✗ invalid_calculations：4 条（`]%` ×3、`] 个百分点` ×1）+ ✗ untraced_numbers：1 条   rc=1
```

七位重跑（同一 staging、同一解释器）：`financial-auditor / value-valuator / growth-assessor / moat-analyst / cognitive-controller / macro-cyclist / management-auditor` → **7/7 compile_rc=0, gate_rc=0**；与既有 `checks/*.md` 字节比对，6 位 `IDENTICAL`，只有 value-valuator `DIFF`（即本轮单位修复本身）。

负控（batch08 原始产物，用新门禁复跑）：`financial-auditor rc=1`、`value-valuator rc=1`、`moat-analyst rc=1`、`cognitive-controller rc=1`、`macro-cyclist rc=1`、`management-auditor rc=0`、`growth-assessor` 无 md（编译失败原状）——**5 FAIL / 1 PASS / 1 compile FAIL 的形状与 batch08 原判词一致**。
**差异（门禁变严，须披露）**：原批次 value-valuator 旧判词只有 `untraced_numbers 3 条`，新门禁**追加** `invalid_calculations 6 条`（L35 与 L72 的 `]%`/`] 个百分点` 重复单位）。这是新增诊断在原始产物上的真实命中，不是回归。

### 8.3 产物 SHA-256（第二轮）

| 文件 | SHA-256 |
|---|---|
| `scripts/verify_report.py` | `c66f23db3c0ab91f5ae3afd94eaaf42b6cac22a0ff23e52f7a373583f8a0af0c` |
| `scripts/collect_results.py` | `1f06be1fd2fbe99b4b7408d0bae41ce0131ba4131e1bdd6f3e92bd42cdc04086` |
| `shared/expert_result_v3.py` | `2379311649c5471aa71f01897a0c2cd1625aa54e2c2bcb0b3f40612b152b7d47` |
| `tests/test_report_gates.py` | `290ecd1deb331d8a172022fea3313da3634faccd784769b0b58486ef9eea1001` |
| `staging/value-valuator.repair.v3.json` | `caec201fde8178c86c4c2c0820050d8ed5339fe168dd07d553ca587042e25404` |
| `checks/value-valuator.md`（重渲后） | `922e6f1646832ff9e3aade47db248f49e6e0cb780ff2035236128fefec8a912a` |

修复前的 value-valuator 产物留存于 `/tmp/ipm-unit/value-valuator.md.before-unit-fix`（SHA `43ebd432217c89e666950ee694c77a20c00e12ba78732a71b11de985945e71c2`），仅作对照，不是交付物。

### 8.4 提交与回执

- 已提交并推送：`b33af26` `fix(gate): 百分点与 % 不再是同一个单位，重复单位写法必须阻塞`；推送后 `git rev-list --count origin/main..main` = 0。
- 该 commit 承载：`scripts/verify_report.py`、`scripts/collect_results.py`、`shared/expert_result_v3.py`、`tests/test_report_gates.py`、`README.md`（S4）。
- 用 `git archive b33af26` 重渲七位并与 runtime 产物逐字节比对：**7/7 IDENTICAL，compile=0 gate=0**（sha256 表见回执 §5）。
- 执行回执：`INV-BATCH-08-REPAIR-04-UNIT-RECEIPT.md`（谁改、改哪个产物、改前改后、门禁 rc 与判词原文、S1–S4）。
- 仍未做：`commit`/`advance`/challenges/cross-review/裁决/`assemble_report`/manifest/复核签收/发布一律未跑；`evaluate_calculation` 仍不校验 calc 操作数量纲（§3.2 遗留），属独立缺陷。
