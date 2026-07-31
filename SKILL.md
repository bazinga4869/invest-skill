---
name: invest-skill
description: >
  A股公司深度投资分析技能。基于7+1专家团（财务排雷官、价值估值师、成长质量师、
  护城河分析师、认知风控官、宏观周期师、管理层审计师+裁判长），
  由宿主Agent使用其原生子代理机制并行执行7位专家分析，每个子代理拥有完全隔离的上下文，
  确保各域视角独立、互不污染。不绑定任何特定agent软件。
  适用场景：用户要求分析某家A股公司、提到股票代码（如600519.SH/300408.SZ）、
  询问估值/财报/护城河/管理层质量、或明确要求做投资分析。
  也适用于cron定时批量分析、Hermes推送等自动化运维场景。
---

# invest-skill — A 股深度投资分析

> 基于 invest-wiki 7+1 专家团，通过独立 agent 进程并行执行 7 域独立分析，输出标准化投资报告。适用于 Codex / Claude Code / Hermes 等任意 Agent。

## 架构原则

```
用户说"分析 X公司"
       ↓
  确认日期 → 同步数据 → 检查业绩预告
       ↓
  python3 shared/data_tools.py all <ts_code>  →  共享数据 JSON
       ↓
  python3 shared/data_tools.py annual-report <ts_code>  →  年报全量文本
       ↓
  python3 scripts/prepare_prompts.py <ts_code>  →  7 份确定性 prompt（方法论快照 + 数据 + 年报）
       ↓
  宿主 Agent 用原生子代理机制 spawn 7 个子代理    ← 首选：上下文天然隔离，不绑定 agent 软件
  （Kimi Code Agent/AgentSwarm、Claude Code Task、Codex subagent …）
        或 bash scripts/run_experts.sh <ts_code>  ← 备选：headless/cron 环境
        ↓ 每位子代理使用同批次注入的 wiki 方法论快照 → 执行分析
        ├── 子代理 1 ← prompt_…_financial-auditor.txt  →  /tmp/invest_result_…_financial-auditor.md
        ├── 子代理 2 ← prompt_…_value-valuator.txt     →  /tmp/invest_result_…_value-valuator.md
        ├── …（共 7 个独立子代理）
        └── 全部完成
        ↓
  收齐 7 份分析 → 裁判长综合裁决 → 撰写报告 → 结构化自评审 → 环境清理
```

**关键分工**：
- **LLM（大脑）**：读取每位专家相互隔离的任务书，执行 7 域分析；主会话负责裁决、自评审和修正
- **Python（手）**：`shared/data_tools.py` 负责标准化取数与基础数学；`prepare_prompts.py` 把专家方法论、直接引用的 wiki 页面、同批次数据和年报正文确定性注入 prompt，不生成评分/评级/结论
- **wiki（知识）**：`~/invest-wiki` 是一个 **llm-wiki 格式的知识库**（含 `.wiki-schema.md` 别名词表、`index.md` 全局索引、`04_stock-analysis-expert/index.md` 考试大纲、frontmatter tags/related 等结构化元数据），子代理可利用这些结构高效检索。专家的角色定义、师承、分析清单由 wiki 中的专家文件定义，skill 不做硬编码

---

## 分析协议（九步）

### 第一步：确认日期与同步数据

1. 确认当前日期（`date` 命令）。日常/cron 必须保持 `config.yaml` 的 `analysis_date` 为空；仅历史回测时显式钉住日期，禁止每日改写配置
2. 同步数据：

```bash
# 首次分析或例行更新（会自动跳过新鲜数据，避免重复拉取）
python3 shared/data_tools.py sync <ts_code>

# 重复分析同一家公司 → 必须加 --force，强制重新拉取全部数据
python3 shared/data_tools.py sync <ts_code> --force
```

> ⚠️ **重复分析规则**：当用户要求重新分析一家已分析过的公司时，sync 必须使用 `--force`。不得因为「数据已是最新」而跳过数据同步步骤。每次分析都是独立的全流程，不依赖之前的分析结果。

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

> v0.5.1 起，主会话读取编排与裁判规则；`prepare_prompts.py` 将每位专家的完整方法论及其直接引用页面注入各自 prompt。这样七位专家使用同一批次的可归档知识快照，不受运行中 wiki 变化影响。

按顺序读取以下文件（只需一次）：

```
1. ../invest-wiki/04_stock-analysis-expert/experts/_panel.md       → 专家阵容 + 调用顺序 + 一票否决权
2. ../invest-wiki/04_stock-analysis-expert/process/深度分析流程.md   → 9 Phase SOP
3. ../invest-wiki/04_stock-analysis-expert/adjudicator/裁判长-多框架裁判规则.md → 综合裁决规则
```

> 上述编排/裁判文件由主 Agent 使用；各专家文件及其直接引用页面由 `prepare_prompts.py` 注入对应专家 prompt。

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

> 运行时专家 ID/文件映射唯一来源是 `data/experts.json`，角色方法论来自 wiki；上表仅为人类导航，不参与程序编排或评分。

### 第四步：获取数据

正常流程直接运行 `python3 scripts/prepare_prompts.py <ts_code>`：它会在同一次调用中生成数据快照、抓取年报、计算绑定数据/年报/wiki 的 `batch_id` 并制作 7 份 prompt。准备新批次会清除该代码旧的临时专家结果；七份新结果必须同时匹配 `data_date` 和 `batch_id`。`data_tools.py all/annual-report` 只用于单独诊断，正常流程不要预先重复调用。

#### 4.1 年报全文抓取

财报数字只是结果，管理层对结果的解释、战略承诺与历史言行一致性，必须从年报文本中验证。

```bash
python3 shared/data_tools.py annual-report <ts_code>
```

该命令会：
- 按已配置的数据源链抓取最近 5 年可得年报正文；
- 解析为结构化文本，按「管理层讨论与分析」「重要事项」「公司治理」等章节拆分；
- 存入 `annual_reports` 表；
- 全量文本写入 `/tmp/invest_annual_{code}.txt`；
- `prepare_prompts.py` 按专家域筛选章节并注入任务书，原始全文仍保留供裁判长复核。

**每位专家必须在分析中执行「反叙事」检查**：用财务数字交叉验证管理层在年报中的说法，识别承诺未兑现、宏大叙事掩盖问题、战略方向反复变更等风险信号。认知风控官需额外完成「管理层叙事审计」。



#### 4.2 数据完整性与口径门禁 ⛔

`data_tools.py all` 输出 `data_quality`；`prepare_prompts.py` 只接受 `PASS/WARN`，遇到 `FAIL` 立即终止。核心字段缺失不得在会话外口头补值后继续，补充数据必须写回同批次 JSON 并重新通过门禁。季度、FCF、单位、日期和缺失值规则见 [数据契约](references/data-contract.md)。

### 第五步：执行专家分析

**首选路径：宿主 Agent 原生子代理（agent 通用，不绑定具体软件）**

宿主 Agent 为 7 份 prompt 各 spawn 一个独立子代理。使用当前平台自带的子代理机制：

| 平台 | 子代理机制 |
|------|-----------|
| Kimi Code | `Agent` / `AgentSwarm` 工具 |
| Claude Code | `Task` 工具 |
| Codex | subagent 机制 |
| 其他 Agent | 其自带的子代理/任务委派能力 |

每个子代理只读自己的 prompt 文件，写自己的 result 文件。

prompt 包含该专家的 wiki 方法论快照、直接引用页面、原始 JSON 和相关年报章节。专家不得读取其他专家的 prompt/result；如额外检索 wiki，须在知识日志中记录精确路径。

spawn 模板：

```
读取 /tmp/invest_prompt_<code>_<expert_id>.txt —— 这是你的任务书，
包含你的身份定义、知识检索指引、原始数据和输出格式要求。

使用 prompt 中注入的方法论与数据完成分析；不得读取其他专家文件。

将完整分析结果（YAML frontmatter + Markdown 正文）直接输出到 stdout。
宿主的 -o 标志会自动捕获并存盘到 /tmp/invest_result_<code>_<expert_id>.md。
不要在输出前后添加任何说明文字（如"文件系统只读"等），
直接从 YAML frontmatter 的 `---` 开始输出。

禁止读取其他专家的 prompt 或 result 文件，禁止访问其他子代理。
完成后只需回复一行确认（不要把分析全文贴回来）。
```

子代理可并行 spawn也可顺序 spawn，隔离性等价——每个子代理都是全新会话上下文，只含自己的 prompt 文件内容。

```bash
# 第一步：若第四步尚未执行，则生成 7 位专家 prompt；已执行时不要重复运行
python3 scripts/prepare_prompts.py <code>

# 第二步：宿主 Agent 按上方模板 spawn 7 个子代理，每个处理一份 prompt

# 第三步：检查结果
python3 scripts/collect_results.py <code> --json
```

**备选路径：`run_experts.sh`（headless / cron 环境）**

当运行环境没有宿主 Agent 的子代理能力（如 cron 触发的裸 shell、CI 管线）时，在 shell 级别启动独立 agent 进程，达到同样的隔离效果：

```bash
bash scripts/run_experts.sh <code>                     # 并行执行 7 位专家分析
RUN_EXPERTS_CONCURRENCY=5 bash scripts/run_experts.sh <code>   # 并发数，默认 3
```

**何时选哪条路径**：

| 场景 | 用哪条 |
|------|--------|
| 交互式分析单只股票 | 首选路径（宿主原生子代理，7 个 Task） |
| 交互式分析多只股票 | **必须走备选路径**（`run_experts.sh`），否则会形成子 agent 嵌套 spawn（股票级 Task 里再 spawn 专家级 Task），层级失控 |
| cron / headless | 备选路径（`run_experts.sh`） |

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

### 第五点五步：魔鬼代言人三级质询（⛔ 不可跳过）

> 旧版「裁判长提 1 个反向问题」存在三个结构性漏洞：(1) 提问质量取决于裁判长个人判断力，盲点对裁判长和专家是共同的；(2) 单问题只能压测推理链的一环；(3) 同一裁判长可能对不同专家宽严不一，导致「PASS」不具可比性。
>
> v3 改为三级结构：第一级机械比对（客观）、第二级 Wiki 题库（半客观）、第三级三方交叉（争议案例升级）。

#### 第一级：必检项覆盖率审计（客观，自动化）

运行 `checklist_audit.py` 检查每位专家是否覆盖了 Wiki 方法论中标记的全部「必检项」：

```bash
python3 scripts/checklist_audit.py --code <code>
```

输出每位专家的必检项完成情况（✅/❌）和总覆盖率。缺失项直接成为魔鬼代言人的质询目标。

- **覆盖率 < 80%**：专家结果不准出，允许有界重试一次。
- **覆盖率 < 60%**：专家结果无效；重试仍失败则终止本次分析，禁止缺席发布。

#### 第二级：Wiki 题库质询（半客观，Wiki 维护）

每位专家的 Wiki 文件末尾有 `## 魔鬼代言人问题库` 段落，包含 4-5 个标准高压问题。

专家报告 7/7 通过后，执行不可跳过的独立质询进程：

```bash
bash scripts/run_challenges.sh <code>
# 失败时只允许有界重试一次：
bash scripts/run_challenges.sh <code> --retry
```

脚本对每位专家执行以下质询：

1. 从问题库中按 `batch_id + expert_id` **确定性抽取 1 个问题**（同批次可复现）
2. 加上 1 个**针对本次分析数据特化的动态问题**（如「你引用的 OCF/NI=0.71 阈值从何而来？如果将 WARN 线从 0.7 上调至 0.8，结论是否改变？」）
3. 如果第一级审计发现缺失项，额外追加 1 个**针对缺失项的问题**

每位专家用 150-300 个中文字回应。回应必须绑定原专家报告哈希，逐字保留三个问题，并由 `collect_challenges.py` 验证。裁判长将质询回复视为专家分析的补充材料。

**为什么用题库而非临场发挥**：题库保证了同一专家在不同股票上被问相同的问题，使 verdict 横向可比。题库由人维护，随分析经验积累迭代，逐步逼近「最该问的问题」。

#### 第三级：三方交叉盲审（争议案例升级，仅触发于以下情况）

触发条件（任一即触发）：
- 同一只股票 ≥ 3 位专家的 verdict 出现严重分歧（PASS vs VETO）
- 裁判长综合裁决的评分 < 40
- 连续 3 次分析同一行业时，某位专家的 conclusion 方向与同行相反

触发后，选择一位与该域最相关的其他专家，用被审专家自己的方法论清单重新审视其分析。例如：
- 让价值估值师用财务排雷官的 10 项必检项再过一遍财务排雷官的数字和结论
- 让护城河分析师用成长质量师的框架检查后者对「第二曲线」的判断

三方交叉输出：**「[方法论 X]视角下的遗漏/矛盾标注」**，不替代原文，而是标注额外的风险点。裁判长在综合裁决中引用交叉发现作为权重调整依据。

`assemble_report.py` 会机器重算触发条件。如果第三级被触发，首次组装会写入 `/tmp/invest_level3_<code>.json` 并拒绝继续；随后必须执行：

```bash
bash scripts/run_cross_reviews.sh <code>
# 失败时只允许有界重试一次：
bash scripts/run_cross_reviews.sh <code> --retry
python3 scripts/assemble_report.py <code> --name <公司名>
```

该脚本独立运行财务、估值、认知三个交叉盲审员，每份结果同时绑定专家/质询输入束哈希和自身 prompt 哈希。三份结果通过后才会生成可嵌入、可归档的聚合原文。

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

先生成 `reports/invest_tool/<code>.draft.md`；只有第八步的机器门禁与自评审均通过，`--finalize` 才原子发布为 `<code>.md`。

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

- 每个事实数字使用 `[source: 精确JSON路径]`；推导值使用 `[calc: 公式; inputs: 路径...]`
- **禁止编造对比数据**：行业均值/分位等必须来自 `python3 shared/data_tools.py industry <code>` 实际查询（已包含在 `all` 输出中），或明确标注"数据不可得"
- **禁止无来源的绝对化历史断言**：在做出「首次」「连续 N 年」「历史新高/最低」等断言前，必须列出完整比较年份并逐项核对原始数据
- 展示推导过程（公式 → 代入 → 结果）
- 自然语言叙事，不用模板套话
- 明确指出数据局限性

### 第八步：自评审与机器准出 ⛔

先按 [报告准出规则](references/report-gates.md) 完成 90 分扣分制自评审并写入草稿，然后执行：

```bash
python3 scripts/collect_results.py <code> --check
python3 scripts/checklist_audit.py --code <code>
python3 scripts/verify_report.py reports/invest_tool/<code>.draft.md --data /tmp/invest_data_<code>.json --strict
python3 scripts/assemble_report.py <code> --name <公司名> --finalize
```

`--finalize` 会再次执行契约、清单、批次身份、专家/质询原文、三级触发判定、综合裁决 YAML、事实溯源和自评审门禁。自评审须以独立行写明 72-90/90 且判定 PASS，机器事实核查也必须 PASS；FLAGGED/FAIL 均不得发布。成功后自动将 JSON、年报、7 专家 prompts/results、7 质询 prompts/results、三级判定（及触发时的盲审）、draft、final 和 SHA-256 manifest 归档。

### 第九步：环境清理

仅在 `--finalize` 成功且证据已归档后，清理本次分析产生的中间文件和残留输出。

清理内容：

1. 删除 `/tmp/` 下的中间文件：
   `/tmp/invest_data_{code}.json`、`/tmp/invest_prompt_{code}_*.txt`、`/tmp/invest_result_{code}_*.md`

2. 删除 `reports/invest_tool/` 中的残留：
   - 命名不规范的重复报告（如缺少交易所后缀的 `{code}.md`，正确格式是 `{ts_code}.md`）
   - 草稿文件 `{ts_code}.draft.md`（如已有对应的正式报告 `{ts_code}.md`）
   - 空子目录（如无有效文件的 `{code}/` 目录）

⚠️ **清理边界**：只清理本次分析产生的文件。已存在的历史分析报告（如其他股票的正式报告）不得删除。

## 交叉验证与计算规范

- 关键计算至少用两种独立口径验算（如 ROE 从 indicators 和净利/权益分别算）；备用源回退不等于双源交叉验证
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
| `python3 shared/data_tools.py quarterly <code>` | 近 8 个还原单季：营收、净利、OCF、资本开支、FCF；完整时给出 TTM |
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
| `scripts/collect_results.py` | 严格校验 7 份专家 frontmatter、批次日期、必需章节、数字引用与必检项 | `python3 scripts/collect_results.py 603605.SH --check` |
| `scripts/run_challenges.sh` | 独立执行并校验 7 份二级魔鬼代言人质询 | `bash scripts/run_challenges.sh 603605.SH` |
| `scripts/run_cross_reviews.sh` | 第三级触发时执行 3 份独立交叉盲审 | `bash scripts/run_cross_reviews.sh 603605.SH` |
| `scripts/assemble_report.py` | 生成裁判草稿；`--finalize` 执行发布门禁、原子发布并归档证据 | `python3 scripts/assemble_report.py 603605.SH --name 珀莱雅` |

**推荐工作流**：

```bash
# 1. 准备 prompt
python3 scripts/prepare_prompts.py 603605.SH

# 2. 执行专家分析：宿主 Agent 为 7 份 prompt 各 spawn 一个子代理（见第五步模板）
#    （headless/cron 环境改用：bash scripts/run_experts.sh 603605.SH）

# 3. 严格校验全部专家
python3 scripts/collect_results.py 603605.SH --check

# 4. 独立执行二级魔鬼代言人质询
bash scripts/run_challenges.sh 603605.SH

# 5. 生成报告草稿
python3 scripts/assemble_report.py 603605.SH --name 珀莱雅

# 6. 裁判长完善裁决与结构化自评审后，执行机器门禁并发布
python3 scripts/assemble_report.py 603605.SH --name 珀莱雅 --finalize
```

## 异常处理

| 异常 | 处理方式 |
|------|---------|
| 核心数据缺失（行情、利润、OCF、资产负债表、指标、审计意见） | ⛔ 数据门禁失败；补齐并重建同批次快照，禁止继续发布 |
| 商誉/借款分项/资本开支未披露 | 保持 `null` 并 WARN；禁止按 0、零商誉或确定 FCF/净现金表述，相关结论降级 |
| 行业特殊（如银行/保险） | 财务排雷官使用行业专用指标 |
| 上市不满 3 年 | 降低成长质量师评分权重，标注「历史数据不足」 |
| 跨市场（A+H 等） | 使用保守估值（两个市场取较低估值） |
| 数据源不可用（API / 数据库 / MCP） | ⛔ **硬失败。** 终止分析并输出错误，不生成正式报告。禁止自行编造数据或从非规范渠道补数。 |
| 年报文本不可得（Tushare + AKShare + 本地缓存全部失败） | 先调用 Claude 全局 skill `cninfo-annual` 从巨潮资讯网下载最近 5 年年报：<br>`python3 ~/.claude/skills/cninfo-annual/scripts/fetch.py <code6> --years <yyyy-yyyy>`<br>下载成功 → 继续完整分析；<br>下载仍失败 → ⛔ **硬失败。** 管理层审计师和反叙事验证无法完成，**禁止**跳过反叙事步骤继续分析。标注"年报文本缺失，分析不完整"。 |

## 自动化运维

交互式单股优先使用宿主子代理；cron/headless 使用 `run_experts.sh`。`daily_analysis.sh` 只能生成待裁决草稿，不能替代裁判长直接发布；`cron_trigger.sh` 在 agent 定稿后会用同批次 JSON 独立复核，复核 PASS 才更新状态和清理。完整职责、断点与成功判定见 [自动化运维](references/automation.md)。
