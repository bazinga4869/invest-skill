---
name: invest-skill
version: 0.2.0
description: |
  A 股公司深度投资分析技能。基于 7+1 专家团（财务排雷官、价值估值师、成长质量师、
  护城河分析师、认知风控官、宏观周期师、管理层审计师 + 裁判长），
  主 Agent 按顺序角色切换，依次以 7 位专家的身份独立分析同一份原始数据。
  每次切换重读该专家的 wiki 方法论，确保各域视角独立。
  触发条件：用户要求"分析"某家 A 股公司、提到股票代码、或明确要求做投资分析。
metadata:
  trigger_keywords:
    - 分析
    - 股票
    - 公司分析
    - 投资分析
    - 估值
    - 财报
    - A股
    - 上市公司
---

# invest-skill — A 股深度投资分析

> 基于 invest-wiki 7+1 专家团，通过角色切换顺序执行 7 域独立分析，输出标准化投资报告。适用于 Codex / Claude Code / Hermes 等任意 Agent。

## 架构原则

```
用户说"分析 X公司"
       ↓
  确认日期 → 同步数据 → 检查业绩预告
       ↓
  读取专家团配置（invest-wiki/04_stock-analysis-expert/）
       ↓
  python3 shared/data_tools.py all <ts_code>  →  共享数据 JSON
       ↓
  角色切换：依次以 7 位专家身份独立分析（同一会话，方法论隔离）
       ├── ① 财务排雷官   → /tmp/invest_result_…_financial-auditor.md
       ├── ② 价值估值师   → /tmp/invest_result_…_value-valuator.md
       ├── ③ 成长质量师   → /tmp/invest_result_…_growth-assessor.md
       ├── ④ 护城河分析师 → /tmp/invest_result_…_moat-analyst.md
       ├── ⑤ 认知风控官   → /tmp/invest_result_…_cognitive-controller.md
       ├── ⑥ 宏观周期师   → /tmp/invest_result_…_macro-cyclist.md
       └── ⑦ 管理层审计师 → /tmp/invest_result_…_management-auditor.md
       ↓
  收齐 7 份分析 → 裁判长综合裁决 → 撰写报告 → 结构化自评审
```

**关键分工**：
- **LLM（大脑）**：加载 wiki 专家团 → 角色切换执行 7 域分析 → 裁判长综合裁决 → 结构化自评审
- **Python（手）**：`shared/data_tools.py` 只负责取数 + 基础数学（CAGR、比率），不包含任何评分/评级/结论
- **wiki（知识）**：`../invest-wiki/04_stock-analysis-expert/` 是专家团的**唯一结构来源**，专家的角色定义、师承、核心使命、检查清单全部由 wiki 定义，skill 不做硬编码

---

## 分析协议（七步）

### 第一步：确认日期与同步数据

1. 确认当前日期（`date` 命令），与 `config.yaml` 中的 `analysis_date` 对比，若不匹配则更新
2. 同步数据：

```bash
python3 shared/data_tools.py sync <ts_code>
```

### 第二步：检查重大公告

财报数据有滞后性。最新财报可能是 3 个月前，期间可能有业绩预告、重大合同等。

```bash
python3 shared/data_tools.py forecast <ts_code>
```

检查要点：
- 业绩预告报告期晚于最新财报期 → 优先使用预告数据计算 forward PE
- 预告与财报存在显著偏差 → 估值部分须同时展示两种口径
- ⚠️ 禁止忽略业绩预告

### 第三步：加载专家团配置

> 💡 skill 只读取 wiki 中的**编排信息**（有哪些专家、什么顺序、裁判规则是什么）。每位专家的具体方法论内容由主 Agent 在角色切换时从 wiki 加载。

按顺序读取以下文件（只需一次）：

```
1. ../invest-wiki/04_stock-analysis-expert/experts/_panel.md       → 专家阵容 + 调用顺序 + 一票否决权
2. ../invest-wiki/04_stock-analysis-expert/process/深度分析流程.md   → 9 Phase SOP
3. ../invest-wiki/04_stock-analysis-expert/adjudicator/裁判长-多框架裁判规则.md → 综合裁决规则
```

#### 专家团阵容

wiki 的 `_panel.md` 和专家文件 frontmatter（`expert_role`、`expert_priority`、`framework_source`）定义了以下阵容：

| 文件名 | 角色 ID | wiki 定义的师承 |
|--------|---------|----------------|
| `01-财务排雷官.md` | `financial-auditor` | Accounting, Graham |
| `02-价值估值师.md` | `value-valuator` | Graham, Templeton, Taleb, QiuGuolu |
| `03-成长质量师.md` | `growth-assessor` | Fisher, Lynch, QiuGuolu, FengLiu |
| `04-护城河分析师.md` | `moat-analyst` | Buffett, Dorsey, QiuGuolu, ZhangLei |
| `05-认知风控官.md` | `cognitive-controller` | Munger, Marks, Taleb, Templeton, Dorsey, QiuGuolu |
| `06-宏观周期师.md` | `macro-cyclist` | Macro |
| `07-管理层审计师.md` | `management-auditor` | Graham, Buffett, Munger, ZhangLei |
| — | `adjudicator` | 综合裁决 |

> ⚠️ **skill 不硬编码专家的中文名、师承描述、核心问题。** 这些全部来自 wiki 文件本身（YAML frontmatter + 正文）。如果 wiki 中专家文件的内容发生变化，skill 自动跟随，无需修改。

### 第四步：获取数据

```bash
python3 shared/data_tools.py all <ts_code> > /tmp/invest_data_<ts_code>.json
```

### 第四步（续）：抓取最近 3-5 年年报全文

财报数字只是结果，管理层对结果的解释、战略承诺与历史言行一致性，必须从年报文本中验证。

```bash
python3 shared/data_tools.py annual-report <ts_code>
```

该命令会：
- 从巨潮资讯网下载最近 5 年的年报/半年报/季报 PDF；
- 解析为结构化文本，按「管理层讨论与分析」「重要事项」「公司治理」等章节拆分；
- 存入 `annual_reports` 表；
- 在 `prepare_prompts.py` 阶段自动注入 7 位专家的 prompt。

**每位专家必须在分析中执行「反叙事」检查**：用财务数字交叉验证管理层在年报中的说法，识别承诺未兑现、宏大叙事掩盖问题、战略方向反复变更等风险信号。认知风控官需额外完成「管理层叙事审计」。

### 第五步：角色切换执行 7 位专家分析

> ⚠️ **方法论隔离原则**：每次切换到下一位专家前，必须重新读取该专家的 wiki 方法论页面。不要依赖前一位专家的分析——每位专家有独立的知识域和检查清单。
> 
> ⚠️ **数据只读原则**：所有专家的分析必须基于同一份原始数据（`/tmp/invest_data_{code}.json`），不得基于其他专家的输出做判断。

**流程**：主 Agent 按顺序扮演 7 位专家角色。每轮：读取该专家的 wiki 方法论 → 读取原始数据 → 用该专家的框架分析 → 写输出到 `/tmp/invest_result_{code}_{expert}.md` → 切换下一位。

#### 5a. 角色切换协议

> 💡 不 spawn 子进程。主 Agent 按顺序在单会话内扮演 7 位专家。通过**每次切换重读该专家 wiki 方法论**来实现认知隔离。

**切换流程**（每轮执行一次）：

```
1. 读方法论：Read ../invest-wiki/04_stock-analysis-expert/experts/{专家文件}.md
2. 读原始数据：Read /tmp/invest_data_{code}.json
3. 用该专家的框架分析（仅关注该专家域的内容，不越界）
4. 写输出：/tmp/invest_result_{code}_{expert_id}.md
5. 在 log 中记录关键发现（一句话），供裁判长综合时参考
6. 切换下一位专家：回到步骤 1
```

**方法论隔离检查**（每轮结束时自查）：
- 我的分析是否仅基于本专家的框架？
- 我是否引用了其他专家的结论？（如果是，删除）
- 所有数字是否来自原始数据而非其他专家输出？（如果不是，纠正）

**输出格式**（每位专家统一）：

```yaml
---
expert_id: "financial-auditor"
score: <0-100 整数>
verdict: PASS | WARN | VETO
veto_triggers: []
---
# {专家中文名}评估 — {公司名}（{代码}）

## 总体判断
（2-4 句话总结性判断）

## 详细分析
（用该专家的框架组织，定量定性交织）

## 关键风险与不确定性
（该域最大的不确定性来源）

## 数据使用说明
（用了哪些数据，哪些缺失）
```

#### 5b. 角色切换执行清单

按优先顺序依次执行（禁止并行，确保方法论隔离）：

| 顺序 | 专家 ID | 方法论文件 | 核心关注域 |
|:----:|---------|-----------|-----------|
| ① | financial-auditor | `01-财务排雷官.md` | ROE趋势、利润质量、资产负债结构、RED FLAG |
| ② | value-valuator | `02-价值估值师.md` | PE/PB分位、安全边际、DCF合理性、跨市场比较 |
| ③ | growth-assessor | `03-成长质量师.md` | 营收CAGR、利润率趋势、Fisher二季度触发器 |
| ④ | moat-analyst | `04-护城河分析师.md` | 品牌/转换成本/网络效应/成本优势、护城河趋势 |
| ⑤ | cognitive-controller | `05-认知风控官.md` | 锚定效应、叙事谬误、确认偏误、管理层叙事审计 |
| ⑥ | macro-cyclist | `06-宏观周期师.md` | 行业周期定位、宏观关联、政策影响 |
| ⑦ | management-auditor | `07-管理层审计师.md` | 管理层质量、战略一致性、资本配置能力 |

**执行注意事项**：
- 每位专家分析基于相同的原始数据 JSON + 该专家的 wiki 方法论
- 禁止引用前序专家的分析结论（方法论隔离原则）
- 如果某项检查因数据缺失无法完成，标注「数据不可得」而非跳过
- 输出格式统一为 YAML frontmatter + Markdown 正文

**容错**：某位专家分析不完整 → 标注不确定性来源 → 继续下一位。所有 7 位完成后裁判长统一评估缺失影响。

### 第六步：裁判长综合裁决

> ⚠️ **VETO 条件、冲突裁决规则、评分权重、评级映射全部由 wiki 定义。skill 不复制这些规则。**
>
> wiki 文件：`../invest-wiki/04_stock-analysis-expert/adjudicator/裁判长-多框架裁判规则.md`

裁判长在**主会话**中执行。已收齐 `/tmp/invest_result_<ts_code>_*.md` 全部 7 份专家分析。

**工作流程**：

1. **读取裁判长规则与知识结构**：
   - **知识索引**：先读 `../invest-wiki/04_stock-analysis-expert/index.md`（考试大纲），了解七位专家的知识域全局结构。这帮助裁判长理解每位专家覆盖了哪些领域、各自的分析框架从何而来。
   - **裁判规则**：加载 `裁判长-多框架裁判规则.md`。这份文件包含了完整的裁决框架——VETO 触发条件、框架冲突裁决优先级、评分权重、评级映射。**以这份文件为裁决的"法律依据"，skill 不做二次定义。**
   - **案例库（如存在）**：读 `案例库-裁判先例.md`，参照历史上类似公司的裁决结果。如果案例库不存在或为空，跳过此步，但标注「无先例可参照」

2. **通读 7 份专家分析**：不是只提取 frontmatter 里的分数，而是理解每位专家的论证逻辑、核心担忧、不确定性来源。裁判长是一个有判断力的"法官"，不是一个加权计算器。

3. **按 wiki 规则裁决**：先查一票否决 → 再处理框架冲突 → 最后给出综合判断。如果 wiki 规则之间有模糊地带，裁判长用自己的判断力做出裁决，并说明理由。

4. **撰写裁决书**：输出评级 + 仓位建议 + 核心理由 + 主要分歧 + 观察指标。裁决书应是一段有判断力的文字，不是填表。

### 第七步：撰写最终报告

保存到 `reports/invest_tool/<code>.md`。

**报告结构**：

1. **核心数据速览** — 一行总评 + 关键指标表
2. **财务排雷** — 财务排雷官分析全文 + RED FLAG（如有）
3. **估值安全边际** — 价值估值师分析全文
4. **成长质量** — 成长质量师分析全文
5. **护城河评估** — 护城河分析师分析全文
6. **认知风控** — 认知风控官分析全文
7. **宏观周期** — 宏观周期师分析全文
8. **管理层评估** — 管理层审计师分析全文
9. **综合裁决** — 裁判长裁决书：评级 + 仓位 + 核心理由 + 主要分歧 + 观察指标
10. **知识索引** — 本次分析引用的 wiki 页面清单

> 💡 第 2-8 章直接嵌入各专家的 Markdown 分析原文。第 9 章由裁判长在主会话中撰写。第 10 章汇总所有被引用的 wiki 页面。

**质量标准**：

- 每个数字都有来源（来自 Python 工具的哪个字段）
- **禁止编造对比数据**：行业均值/分位等必须来自 `python3 shared/data_tools.py industry <code>` 实际查询（已包含在 `all` 输出中），或明确标注"数据不可得"
- **禁止无来源的绝对化历史断言**：在做出「首次」「连续 N 年」「历史新高/最低」等断言前，必须列出完整比较年份并逐项核对原始数据
- 展示推导过程（公式 → 代入 → 结果）
- 自然语言叙事，不用模板套话
- 明确指出数据局限性

### 第八步：结构化自评审（扣分制）

> ⚠️ 不 spawn 独立评审员。主 Agent 完成报告后，以审查模式重新审视自己的输出。分三个独立维度执行核查，每个维度从 100 分起扣。

#### 评审流程

**准备**：已完成最终报告 `reports/invest_tool/{code}.md`。现在切换到审查身份。

#### 维度一：数据可追溯性（满分 25）

逐项检查（至少验证 10 个数字）：

| # | 扣分项 | 扣分 |
|---|--------|:----:|
| 1.1 | 报告中的数字在 `/tmp/invest_data_{code}.json` 中找不到来源 | -8/个 |
| 1.2 | 单位换算错误（万元/元/亿元混淆） | -10/个 |
| 1.3 | 使用了「行业平均」「市场普遍」「历史中枢」等无来源对比 | -10/个 |

#### 维度二：方法论忠实度（满分 25）

| # | 扣分项 | 扣分 |
|---|--------|:----:|
| 2.1 | 专家的结论与其 wiki 方法论矛盾 | -15/个 |
| 2.2 | 专家跳过了方法论中标记为「必检」的检查项 | -8/个 |
| 2.3 | VETO 条件触发但未标注 ⛔ VETO | -20/个 |

#### 维度三：裁判长诚实性与内部一致性（满分 25）

| # | 扣分项 | 扣分 |
|---|--------|:----:|
| 3.1 | 裁判长选择性忽略了某位专家的关键否定意见 | -15/个 |
| 3.2 | 不同专家对同一数据得出矛盾结论，裁判长未识别 | -10/对 |
| 3.3 | 报告前后数据不一致 | -10/处 |

#### 维度四：逻辑与表述（满分 15）

| # | 扣分项 | 扣分 |
|---|--------|:----:|
| 4.1 | 循环论证 | -5/处 |
| 4.2 | 因果倒置 | -5/处 |
| 4.3 | 某位专家的核心发现未出现在报告中 | -10/位 |

#### 维度五：隔离性自检（满分 10）—— 角色切换模式专有

| # | 扣分项 | 扣分 |
|---|--------|:----:|
| 5.1 | 发现某位专家引用了其他专家的分析结论（而非原始数据） | -10/处 |
| 5.2 | 发现相邻专家的分析存在明显的措辞/逻辑继承 | -5/处 |

#### 评审输出格式

```markdown
## 结构化自评审

### 得分汇总

| 评审维度 | 满分 | 扣分 | 得分 |
|---------|:----:|:----:|:----:|
| 数据可追溯性 | 25 | -X | XX |
| 方法论忠实度 | 25 | -X | XX |
| 裁判长诚实性 | 25 | -X | XX |
| 逻辑与表述 | 15 | -X | XX |
| 隔离性自检 | 10 | -X | XX |
| **总分** | **100** | **-X** | **XX** |

### 扣分明细

| 维度 | 问题描述 | 证据 | 扣分 |
|------|---------|------|:---:|
| ... | ... | ... | ... |

### 评审结论

**总分：XX / 100**
**判定：[ ] PASS（≥80分） [ ] FLAGGED（60-79分） [ ] REJECT（<60分）**

（必须勾选一个）
```

#### 准出规则

- ≥ 80 分 → 报告准出，附加评审结论到报告末尾
- 60-79 分 → 报告标注 FLAGGED，列出需修正的问题
- < 60 分 → 报告标注 REJECT，建议重新生成

## 交叉验证与计算规范

- 所有计算至少用两种方法验算（如 ROE 从 indicators 和 净利/权益 分别算）
- OCF/净利 中识别 Q1 季节性（Q1 OCF 偏低是正常现象）
- 应收/营收增速用同比（YoY）而非环比
- data_tools 数据与手动计算不一致时，优先手动重算

## 数据工具

| 命令 | 输出 |
|------|------|
| `python3 shared/data_tools.py sync <code>` | 同步最新数据到本地 DB |
| `python3 shared/data_tools.py sync-all-stocks` | 同步全部 A 股基础信息到 stocks 表 |
| `python3 shared/data_tools.py stock-info <code>` | 公司名、行业、上市日期 |
| `python3 shared/data_tools.py market <code>` | 股价、PE、PB、PS、市值、总股本 |
| `python3 shared/data_tools.py annual <code>` | 历年营收、净利、净利率、CAGR |
| `python3 shared/data_tools.py quarterly <code>` | 近 8 季：营收、净利、OCF、FCF |
| `python3 shared/data_tools.py balance <code>` | 资产、负债、现金、商誉、应收 |
| `python3 shared/data_tools.py indicators <code>` | ROE、毛利率、净利率（年报） |
| `python3 shared/data_tools.py industry <code>` | 行业均值/中位数/分位 + 目标公司行业排名 |
| `python3 shared/data_tools.py forecast <code>` | 业绩预告 |
| `python3 shared/data_tools.py annual-report <code>` | 最近 3-5 年年报/半年报/季报全文（注入专家 prompt 做定性交叉验证） |
| `python3 shared/data_tools.py all <code>` | 以上全部（含 industry，不含 annual-report） |

代码格式：`300408.SZ` 或 `603605.SH`。也可用 6 位数字自动推断交易所。

## 自动化脚本

项目提供以下辅助脚本，减少手动拼接 prompt 和报告的工作量：

| 脚本 | 作用 | 示例 |
|------|------|------|
| `scripts/prepare_prompts.py` | 生成 7 位专家 + 3 位评审员的 prompt 文件，并拉取全部原始数据 | `python3 scripts/prepare_prompts.py 603605.SH` |
| `scripts/collect_results.py` | 收集并解析 7 位专家 + 3 位评审员的结果，输出 JSON 摘要；兼容裸 YAML 和 `\`\`\`yaml` 包裹的 frontmatter | `python3 scripts/collect_results.py 603605.SH --json` |
| `scripts/assemble_report.py` | 自动嵌入专家原文、计算加权评分、生成裁判长裁决草稿；默认输出 `.draft.md`，需裁判长填充定性判断后 `--finalize` | `python3 scripts/assemble_report.py 603605.SH --name 珀莱雅` |

**推荐工作流**：

```bash
# 1. 准备 prompt
python3 scripts/prepare_prompts.py 603605.SH

# 2. 角色切换执行 7 位专家分析（见第五步）
# ...

# 3. 检查哪些专家/评审员缺失
python3 scripts/collect_results.py 603605.SH --json

# 4. 生成报告草稿
python3 scripts/assemble_report.py 603605.SH --name 珀莱雅

# 5. 裁判长人工完善草稿后，生成正式报告
python3 scripts/assemble_report.py 603605.SH --name 珀莱雅 --finalize
```

## 异常处理

| 异常 | 处理方式 |
|------|---------|
| 数据缺失（如现金流量表） | 标记缺失，对应专家跳过但标注不确定性 |
| 行业特殊（如银行/保险） | 财务排雷官使用行业专用指标 |
| 上市不满 3 年 | 降低成长质量师评分权重，标注「历史数据不足」 |
| 跨市场（A+H 等） | 使用保守估值（两个市场取较低估值） |
