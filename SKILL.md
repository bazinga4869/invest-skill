---
name: invest-skill
version: 0.4.0
description: |
  A 股公司深度投资分析技能。基于 7+1 专家团（财务排雷官、价值估值师、成长质量师、
  护城河分析师、认知风控官、宏观周期师、管理层审计师 + 裁判长），
  由宿主 Agent 使用其原生子代理机制并行执行 7 位专家分析，每个子代理拥有完全隔离的上下文，
  确保各域视角独立、互不污染。不绑定任何特定 agent 软件。
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

> 基于 invest-wiki 7+1 专家团，通过独立 agent 进程并行执行 7 域独立分析，输出标准化投资报告。适用于 Codex / Claude Code / Hermes 等任意 Agent。

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
  python3 scripts/prepare_prompts.py <ts_code>  →  7 份独立 prompt 文件
       ↓
  宿主 Agent 用原生子代理机制 spawn 7 个子代理    ← 首选：上下文天然隔离，不绑定 agent 软件
  （Kimi Code Agent/AgentSwarm、Claude Code Task、Codex subagent …）
          或 bash scripts/run_experts.sh <ts_code>  ← 备选：headless/cron 环境（无宿主子代理时）
          ↓ 7 位专家独立分析（每子代理只读自己的 prompt 文件）
          ├── 子代理 1 ← prompt_…_financial-auditor.txt  →  /tmp/invest_result_…_financial-auditor.md
          ├── 子代理 2 ← prompt_…_value-valuator.txt     →  /tmp/invest_result_…_value-valuator.md
          ├── …（共 7 个独立子代理）
          └── 全部完成
          ↓
      收齐 7 份分析 → 裁判长综合裁决 → 撰写报告 → 结构化自评审 → 环境清理
```

**关键分工**：
- **LLM（大脑）**：加载 wiki 专家团 → spawn 7 个独立子代理并行执行 7 域分析 → 裁判长综合裁决 → 结构化自评审 → 环境清理
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

> 💡 skill 只读取 wiki 中的**编排信息**（有哪些专家、什么顺序、裁判规则是什么）。每位专家的具体方法论内容由 `prepare_prompts.py` 在生成 prompt 时从 wiki 自动注入。

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



### 第四步（续）：数据完整性检查（Tushare MCP 补充）⛔ 强制检查点

> ⛔ **在进入第五步之前，必须完成本节检查。不可跳过。**

执行完 `data_tools.py all` 后，读入 `/tmp/invest_data_{code}.json`，按以下流程逐项检查并补充：

**Step 1：逐项检查（非可选）**

对以下 4 个字段执行显式检查，每一项都必须输出检查结果：

| # | 检查字段 | JSON 路径 | 缺失判定 | 缺失时动作 |
|----|---------|----------|---------|----------|
| 1 | 商誉 | `balance.goodwill_yi` | 为 `null`/`None` | 调用 `mcp__tushareMcp__balancesheet` 查询最新年报 |
| 2 | 季度现金流 | `quarterly.periods` | 数组长度 < 4 | 调用 `mcp__tushareMcp__cashflow` 查询近 8 季 |
| 3 | 审计意见 | 字段缺失 | 任何情况下都缺失（`data_tools.py all` 不含此字段） | 调用 `mcp__tushareMcp__fina_audit` 查询最新年报 |
| 4 | 扣非净利润 | `annual.annual_data[*].non_recurring_pct` | 每股 `non_recurring_pct` 为 `null`/`None` | 用 `non_oper_income / operate_profit` 估算（`data_tools.py` 已输出）；若仍不足，调用 `mcp__tushareMcp__income` |

**Step 2：执行 MCP 补充（对缺失项）**

对每个标记为「缺失」的字段，调用一次对应的 MCP 工具。在分析日志中记录：

```
[MCP补充] 商誉 — balancesheet → goodwill=XXX亿
[MCP补充] 审计意见 — fina_audit → 标准无保留意见
[MCP补充] <字段> — <数据可用/确认缺失>
```

**Step 3：注入分析流程**

MCP 补充的数据不修改 `/tmp/invest_data_{code}.json`。在第五步中，当前专家在分析中如遇对应字段为 None，主 Agent 应直接引用 MCP Step 2 中已获取的数据。

**MCP 工具速查**：

| 数据需求 | MCP 工具名 | 示例调用 |
|---------|-----------|---------|
| 资产负债表科目 | `mcp__tushareMcp__balancesheet` | `ts_code='603605.SH', end_date='20251231'` |
| 季度现金流 | `mcp__tushareMcp__cashflow` | `ts_code='603605.SH', start_date='20240101', end_date='20260331'` |
| 利润表科目 | `mcp__tushareMcp__income` | `ts_code='603605.SH', end_date='20251231'` |
| 审计意见 | `mcp__tushareMcp__fina_audit` | `ts_code='603605.SH', end_date='20251231'` |

> ⚠️ **不得跳过**：即使所有字段看起来都有值，也必须逐项检查并输出检查日志。这是分析质量的门槛守卫。

### 第五步：执行专家分析

**首选路径：宿主 Agent 原生子代理（agent 通用，不绑定具体软件）**

宿主 Agent 为 7 份 prompt 各 spawn 一个独立子代理。使用当前平台自带的子代理机制：

| 平台 | 子代理机制 |
|------|-----------|
| Kimi Code | `Agent` / `AgentSwarm` 工具 |
| Claude Code | `Task` 工具 |
| Codex | subagent 机制 |
| 其他 Agent | 其自带的子代理/任务委派能力 |

每个子代理只读自己的 prompt 文件，写自己的 result 文件。spawn 模板：

```
读取 /tmp/invest_prompt_<code>_<expert_id>.txt —— 这是你的完整任务书，
包含你的专家角色方法论、原始数据和输出格式要求。
严格按其中指示完成分析，将最终结果（含 YAML frontmatter）写入
/tmp/invest_result_<code>_<expert_id>.md。
禁止读取其他专家的 prompt 或 result 文件，禁止访问其他子代理。
完成后只需回复一行确认（不要把分析全文贴回来）。
```

子代理可并行 spawn（如 Kimi Code 的 AgentSwarm）也可顺序 spawn，隔离性等价——每个子代理都是全新会话上下文，只含自己的 prompt 文件内容。

```bash
# 第一步：生成 7 位专家的独立 prompt（自动注入 wiki 方法论 + 原始数据）
python3 scripts/prepare_prompts.py <code>

# 第二步：宿主 Agent 按上方模板 spawn 7 个子代理，每个处理一份 prompt

# 第三步：检查结果
python3 scripts/collect_results.py <code> --json
```

**备选路径：`run_experts.sh`（headless / cron 环境）**

当运行环境没有宿主 Agent 的子代理能力（如 cron 触发的裸 shell、CI 管线）时，在 shell 级别启动独立 agent 进程，达到同样的隔离效果：

```bash
bash scripts/run_experts.sh <code>                     # 按 codex → claude → hermes 自动检测 CLI
bash scripts/run_experts.sh <code> --agent claude      # 或显式指定后端
RUN_EXPERTS_CONCURRENCY=5 bash scripts/run_experts.sh <code>   # 并发数，默认 3
```

两条路径的文件契约完全相同（prompt/result 文件路径一致），下游 `collect_results.py`、`assemble_report.py` 无感。

**为什么必须是独立子代理/进程**：同一会话内顺序扮演 7 位专家，前序上下文必然泄漏到后续分析。独立子代理（或独立进程）实现了真正的认知隔离——每位专家的上下文只包含该专家的方法论和原始数据，不包含其他专家的任何分析和结论。

**输出格式**（每位专家统一，由 prompt 中的模板定义）：

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

> ⚠️ 不 spawn 独立评审员。主 Agent 完成报告后，以审查模式重新审视自己的输出。分四个维度执行核查，各维度从满分起扣（25/25/25/15，总分 90）。

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
| **总分** | **90** | **-X** | **XX** |

### 扣分明细

| 维度 | 问题描述 | 证据 | 扣分 |
|------|---------|------|:---:|
| ... | ... | ... | ... |

### 评审结论

**总分：XX / 90**
**判定：[ ] PASS（≥72分） [ ] FLAGGED（60-71分） [ ] REJECT（<60分）**

（必须勾选一个）
```

#### 准出规则

- ≥ 72 分（总分 90 的 80%）→ 报告准出，附加评审结论到报告末尾
- 60-71 分 → 报告标注 FLAGGED，列出需修正的问题
- < 60 分 → 报告标注 REJECT，建议重新生成

### 第九步：环境清理

分析流程完成后，清理本次分析产生的中间文件和残留输出。

清理内容：

1. 删除 `/tmp/` 下的中间文件：
   `/tmp/invest_data_{code}.json`、`/tmp/invest_prompt_{code}_*.txt`、`/tmp/invest_result_{code}_*.md`

2. 删除 `reports/invest_tool/` 中的残留：
   - 命名不规范的重复报告（如缺少交易所后缀的 `{code}.md`，正确格式是 `{ts_code}.md`）
   - 草稿文件 `{ts_code}.draft.md`（如已有对应的正式报告 `{ts_code}.md`）
   - 空子目录（如无有效文件的 `{code}/` 目录）

⚠️ **清理边界**：只清理本次分析产生的文件。已存在的历史分析报告（如其他股票的正式报告）不得删除。

## 交叉验证与计算规范

- 所有计算至少用两种方法验算（如 ROE 从 indicators 和 净利/权益 分别算）
- OCF/净利 中识别 Q1 季节性（Q1 OCF 偏低是正常现象）
- 应收/营收增速用同比（YoY）而非环比
- data_tools 数据与手动计算不一致时，优先手动重算

## 数据工具（两种路径）

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

### 路径 B：Tushare MCP（Codex 原生支持）

Codex 可通过 MCP 协议直接调用 Tushare API，无需经过 Python 脚本。适合实时查询和增量数据获取。

需要预先添加 MCP server：

```bash
codex mcp add tushareMcp --url "https://api.tushare.pro/mcp/?token=<YOUR_TOKEN>"
```

**使用场景**：
- 财报公告日当天立即获取数据（Python db 可能有延迟）
- 补充查询 Python 数据工具未覆盖的字段（如分析师评级、龙虎榜、基金持仓）
- 跨市场数据扩展

> ⚠️ MCP 路径和 Python 工具互为补充，核心分析流程仍以 `data_tools.py all` 为主（格式一致、缓存稳定），MCP 用于补充和验证。

## 自动化脚本

项目提供以下辅助脚本，减少手动拼接 prompt 和报告的工作量：

| 脚本 | 作用 | 示例 |
|------|------|------|
| `scripts/prepare_prompts.py` | 生成 7 位专家的 prompt 文件，并拉取全部原始数据 | `python3 scripts/prepare_prompts.py 603605.SH` |
| `scripts/collect_results.py` | 收集并解析 7 位专家的结果，输出 JSON 摘要；兼容裸 YAML 和 `\`\`\`yaml` 包裹的 frontmatter | `python3 scripts/collect_results.py 603605.SH --json` |
| `scripts/assemble_report.py` | 自动嵌入专家原文、计算加权评分、生成裁判长裁决草稿；默认输出 `.draft.md`，需裁判长填充定性判断后 `--finalize` | `python3 scripts/assemble_report.py 603605.SH --name 珀莱雅` |

**推荐工作流**：

```bash
# 1. 准备 prompt
python3 scripts/prepare_prompts.py 603605.SH

# 2. 执行专家分析：宿主 Agent 为 7 份 prompt 各 spawn 一个子代理（见第五步模板）
#    （headless/cron 环境改用：bash scripts/run_experts.sh 603605.SH）

# 3. 检查哪些专家缺失
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
| 数据源不可用（API / 数据库 / MCP） | ⛔ **硬失败。** 终止分析，输出错误报告。**禁止**自行编造数据、**禁止**从非规范渠道（搜索引擎、LLM 记忆知识、第三方网站爬虫）补充数据继续分析流程。数据是分析的基石——数据缺失时，"不确定性过高"比"编造结论"诚实。 |
| 年报文本不可得（Tushare + AKShare + 本地缓存全部失败） | 先调用 Claude 全局 skill `cninfo-annual` 从巨潮资讯网下载最近 5 年年报：<br>`python3 ~/.claude/skills/cninfo-annual/scripts/fetch.py <code6> --years <yyyy-yyyy>`<br>下载成功 → 继续完整分析；<br>下载仍失败 → ⛔ **硬失败。** 管理层审计师和反叙事验证无法完成，**禁止**跳过反叙事步骤继续分析。标注"年报文本缺失，分析不完整"。 |

## 自动化运维（v0.3.0 新增；v0.4.0 起交互式分析改用宿主子代理，本节脚本服务于 cron/headless 场景）

### 定时分析流水线

Cron 调度（工作日）：

```
20:00  daily_analysis.sh --sync-only  → 数据同步 + prompt 生成 → activity.jsonl
21:00  cron_hermes_push.sh             → Hermes 读取 reports_today.sh → 推送用户
每月1日 sync-all-stocks                 → 刷新全 A 股基础信息
```

### 运维脚本速查

| 脚本 | 作用 |
|------|------|
| `scripts/cron_trigger.sh` | 每日分析的 cron 触发器（10:00 / 14:30）。通用 agent 后端：`--agent auto|codex|claude|hermes` 或环境变量 `AGENT`，默认 auto 按 codex→claude→hermes 检测（与 `run_experts.sh` 同序）。含超时（`TIMEOUT_MINUTES`，默认 60 分钟，超时退出码 124）、重试与结构化日志 |
| `scripts/daily_analysis.sh` | 每日分析主脚本。从全 A 股动态随机选 N 只（`pick_stocks.py`），逐只执行数据同步→prompt 生成→可选 expert 分析→报告组装。支持 `--sync-only`（cron 用）、`--dry-run`、`--count N` |
| `scripts/pick_stocks.py` | 从本地 DB 的 `stocks` 表中随机选取股票，排除科创/北交/ST。用法：`python3 pick_stocks.py <N> [seed]`，seed 默认取当日日期保证同一天幂等 |
| `scripts/activity_log.sh` | 结构化活动日志库（source 后使用）。函数 `log_activity <phase> <code> <name> <status> <msg>`，输出 `logs/activity.jsonl`。自动检测调用方 agent（codex/claude/hermes/cron） |
| `scripts/reports_today.sh` | 每日报告摘要输出。支持 `--date`、`--json`（Hermes 程序化消费）、`--activity`（活动日志）。输出含 `report_count` + `failure_count` + `failures` 数组 |
| `scripts/hermes_push_prompt.txt` | 发给 Hermes 的推送指令 prompt，定义如何解析 `reports_today.sh --json`、格式化消息、推送报告和异常告警 |
| `scripts/cron_hermes_push.sh` | Hermes 推送的 cron 触发器，调用 `hermes run` 执行 `hermes_push_prompt.txt` |

### 活动日志格式

`logs/activity.jsonl`，每行一条 JSON：

```json
{"ts":"2026-07-11T15:35:13Z","agent":"codex","phase":"report","code":"600298.SH","name":"安琪酵母","status":"success","msg":"HOLD 54分"}
```

字段：`ts`(UTC时间)、`agent`(调用方)、`phase`(sync/prompt/expert/report/session)、`code`、`name`、`status`(success/failure/skipped)、`msg`

### Hermes 推送的消息类型

| 条件 | 推送内容 |
|------|---------|
| `report_count > 0` 且 `failure_count == 0` | 📊 每日报告摘要（评分 + 评级 + 一行总评） |
| `report_count > 0` 且 `failure_count > 0` | 📊 报告摘要 + ⚠️ 异常提醒 |
| `report_count == 0` 且 `failure_count > 0` | ⚠️ 异常告警（全部失败） |
| `report_count == 0` 且 `failure_count == 0` | 不推送 |
