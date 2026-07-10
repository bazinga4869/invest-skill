---
name: invest-skill
version: 0.2.0
description: |
  A 股公司深度投资分析技能。基于 7+1 专家团（财务排雷官、价值估值师、成长质量师、
  护城河分析师、认知风控官、宏观周期师、管理层审计师 + 裁判长），
  通过独立子 Agent 会话物理隔离，每位专家在完全独立的
  会话中分析同一份原始数据，互不可见，杜绝上下文污染。
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

> 基于 invest-wiki 7+1 专家团，通过独立子 Agent 并行分析，输出标准化投资报告。

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
  spawn 7 个独立子 Agent（平台适配，物理隔离）
       ├── 财务排雷官   → /tmp/invest_result_…_financial-auditor.md
       ├── 价值估值师   → /tmp/invest_result_…_value-valuator.md
       ├── 成长质量师   → /tmp/invest_result_…_growth-assessor.md
       ├── 护城河分析师 → /tmp/invest_result_…_moat-analyst.md
       ├── 认知风控官   → /tmp/invest_result_…_cognitive-controller.md
       ├── 宏观周期师   → /tmp/invest_result_…_macro-cyclist.md
       └── 管理层审计师 → /tmp/invest_result_…_management-auditor.md
       ↓
  主会话收齐 7 份独立分析 → 裁判长综合裁决 → 撰写报告
```

**关键分工**：
- **LLM（大脑）**：加载 wiki 专家团 → spawn 7 个独立子 Agent → 裁判长综合裁决
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

> 💡 skill 只读取 wiki 中的**编排信息**（有哪些专家、什么顺序、裁判规则是什么）。每位专家的具体方法论内容由 spawn 出的独立会话自行从 wiki 加载。

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

### 第五步：并行 spawn 7 位独立专家

> 🚫 **严禁在同一会话中串行调用专家。** 同一会话内串行调用存在根本缺陷：LLM 会隐式记住前面专家的判断，导致后序专家产生锚定偏差。
> 
> 🚫 **严禁主会话在 spawn 专家前阅读任何已有分析报告。** 如果 `reports/invest_tool/<code>.md` 或 `/tmp/invest_result_<code>_*.md` 等历史文件已存在，主会话必须忽略它们。任何对历史报告的阅读都会污染裁判长的独立判断。所有裁决必须仅基于本次 spawn 产生的 7 份专家输出 + 原始数据 + wiki 规则。

**流程**：主会话通过平台适配层 spawn 7 个独立子 Agent，每位专家在完全隔离的会话中，阅读自己的 wiki 方法论文件，分析同一份原始数据。

#### 5a. 预取 wiki 知识（主会话，spawn 之前）

> 💡 主会话利用已有的 wiki 访问权限，为每位专家**预取其分析所需的全部 wiki 知识**——读方法论 → 提取 [[wikilink]] → 查找对应页面 → 读取内容 → 写入 prompt 文件。专家 spawn 后直接拿到完整的知识上下文，无需自己摸索 wiki 结构。

```bash
CODE="<ts_code>"    # 如 600519.SH
NAME="<公司名>"     # 如 贵州茅台
WIKI_ROOT="../invest-wiki/04_stock-analysis-expert"

# ── 预取阶段（顺序执行，纯文件 I/O，很快）──

prepare_expert_prompt() {
    local EXPERT_ID=$1      # 如 financial-auditor
    local FILE=$2           # 如 01-财务排雷官
    local PROMPT_FILE="/tmp/invest_prompt_${CODE}_${EXPERT_ID}.txt"

    # 1. 读取专家方法论
    local METHOD_FILE="${WIKI_ROOT}/experts/${FILE}.md"
    local METHOD=$(cat "$METHOD_FILE" 2>/dev/null || echo "专家文件缺失: $METHOD_FILE")

    # 2. 提取方法论中的 [[wikilink]] 引用
    local REFS=$(echo "$METHOD" | grep -oP '\[\[.+?\]\]' | sort -u)

    # 3. 在 wiki 中查找并读取每个引用页面
    local SUPP=""
    for ref in $REFS; do
        local pagename=$(echo "$ref" | sed 's/^\[\[//;s/\]\]$//')
        # 搜索匹配的 .md 文件（先精确匹配，再模糊匹配）
        local found=$(find "$WIKI_ROOT" -name "${pagename}.md" 2>/dev/null | head -1)
        if [ -z "$found" ]; then
            # 模糊匹配：搜索包含该关键词的 .md 文件
            found=$(grep -rl "title:.*${pagename}" "$WIKI_ROOT" 2>/dev/null | head -1)
        fi
        if [ -n "$found" ] && [ -s "$found" ]; then
            SUPP="${SUPP}\n\n---\n## ${pagename}\n\n$(cat "$found")"
        fi
    done

    # 4. 从 wiki YAML frontmatter 提取 title（用于报告章节命名）
    local TITLE=$(python3 -c "
import yaml, re
text = open('${METHOD_FILE}').read()
m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
if m:
    d = yaml.safe_load(m.group(1))
    print(d.get('title', '${EXPERT_ID}'))
" 2>/dev/null || echo "${EXPERT_ID}")

    # 5. 写入完整 prompt（方法论 + 预取知识 + 数据 + 指令）
    cat > "$PROMPT_FILE" << PROMPT_EOF
你是 invest-skill 专家团成员。

## 你的方法论（来自 invest-wiki）

以下是你完整的分析框架——身份、师承、使命、检查清单、判定标准、否决条件。请以它为大脑进行思考和分析。

${METHOD}

## 补充 wiki 知识（主会话已为你预取）

以下内容来自 invest-wiki 中你的方法论所引用的知识页面。这些是分析中涉及的关键概念、公式定义和案例参照的原文。请作为方法论的组成部分来阅读。

${SUPP}

> 💡 以上 wiki 知识已由主会话预取并附在 prompt 中。如果分析中遇到未覆盖的概念，你仍可使用 Read 工具自行查阅 wiki（三步法：index.md → [[wikilink]] → grep 兜底）。

## 目标公司原始数据

以下是 ${NAME}（${CODE}）的完整财务与行情数据。所有数据来自 Tushare Pro，已经过 Python 数据管道处理。

\`\`\`json
$(cat /tmp/invest_data_${CODE}.json)
\`\`\`

## 你的任务

以一位资深投资分析师的身份，基于你的方法论，对 ${NAME} 进行**定量与定性兼备**的深度评估。

**写作要求**：

1. **有人味，不要像机器**：用自然的中文撰写，就像你在给一位信任你的投资合伙人写分析备忘录。有数据，有逻辑，也有判断。

2. **定量分析**：列出关键数字，展示计算过程（公式 → 代入 → 结果），标注每个数字的数据来源。

3. **定性分析**：数字只是起点。解释数字背后的含义——它揭示了什么商业模式特征？什么竞争态势？什么风险信号？什么被市场忽略了？

4. **正反两面**：既写有利证据，也写不利证据。诚实是最好的分析。

5. **不确定性的诚实**：如果某些检查因数据缺失无法完成，坦率标注「数据不可得」并说明这对结论的影响。不要假装确定。

6. **如果触发 VETO，明确说出来**：在你的方法论中，某些条件是硬性的否决项。如果你发现这些条件被触发，在分析中明确标注 ⛔ VETO 并解释原因。

## 输出格式

你的输出将直接成为最终投资报告的一个章节。请在文件**最开头**放一段 YAML frontmatter，供裁判长提取关键信息，然后用 Markdown 撰写完整的分析正文。

> ⚠️ **frontmatter 格式要求**：直接以 `---` 开头、以 `---` 结束，**不要**用 `\`\`\`yaml` 代码块包裹，否则裁判长无法自动解析。

\`\`\`
---
expert_id: "${EXPERT_ID}"
score: <0-100 整数>
verdict: PASS | WARN | VETO
veto_triggers: []
---

# ${TITLE}评估 — ${NAME}（${CODE}）

## 总体判断

（2-4 句话的总结性判断。先说结论，再说依据。）

## 详细分析

（自由结构。用你的方法论框架组织分析，定量定性交织。可以包含表格、公式、推理链。）

## 关键风险与不确定性

（列出你的分析中最大的不确定性来源。）

## 数据使用说明

（简述你用了哪些数据，哪些数据缺失。）
\`\`\`

## 重要约束

- 🚫 只分析你的专业领域，不要越界做其他专家的判断
- 🚫 不要给出投资建议（BUY/SELL/HOLD），那是裁判长的工作
- 🚫 不要编造数据，所有数字必须来自上方提供的原始数据
- 🚫 **禁止无来源对比**：不得使用「行业平均」「市场普遍」「据统计」「历史中枢」等无法追溯到原始数据的断言；若需对比，必须标注「数据不可得」
- 🚫 **禁止未经核对的历史断言**：在写出「首次」「连续 N 年」「历史新高/最低」前，必须列出完整比较年份并逐项核对
- ✅ 你写的内容将直接成为最终报告的章节，请确保可以独立阅读
- ✅ 如果触发 VETO，在 frontmatter 的 `veto_triggers` 中明确列出，并在正文中标注 ⛔ VETO
PROMPT_EOF

    echo "[READY] ${EXPERT_ID}"
}

# 顺序预取所有专家的 wiki 知识（纯文件 I/O，约 1-3 秒完成）
prepare_expert_prompt "financial-auditor"   "01-财务排雷官"
prepare_expert_prompt "value-valuator"     "02-价值估值师"
prepare_expert_prompt "growth-assessor"    "03-成长质量师"
prepare_expert_prompt "moat-analyst"       "04-护城河分析师"
prepare_expert_prompt "cognitive-controller" "05-认知风控官"
prepare_expert_prompt "macro-cyclist"      "06-宏观周期师"
prepare_expert_prompt "management-auditor" "07-管理层审计师"

echo "=== 全部 7 位专家 prompt 准备完成 ==="
```

#### 5b. Spawn 阶段（并行，物理隔离）

> 🚫 **严禁在同一会话中串行调用专家。** 同一会话内串行调用存在根本缺陷：LLM 会隐式记住前面专家的判断，导致后序专家产生锚定偏差。
> 
> 每位专家的 prompt 文件已含方法论 + 预取 wiki 知识 + 原始数据。Spawn 时通过 **stdin 重定向**传入，不经过命令行参数，不受 ARG_MAX 限制。

```bash
CODE="<ts_code>"

# 加载当前平台的 spawn 实现（claude/codex/hermes 各自提供 spawn_expert 函数）
source "${SKILL_DIR:-/home/bazinga/invest-skill}/platforms/current/spawn.sh" 2>/dev/null || \
  source "${SKILL_DIR:-/home/bazinga/invest-skill}/platforms/claude/spawn.sh"

# ── 并行启动全部 7 位专家（平台无关 — 每个平台实现自己的 spawn_expert）──
for expert_id in financial-auditor value-valuator growth-assessor moat-analyst cognitive-controller macro-cyclist management-auditor; do
    spawn_expert \
        "/tmp/invest_prompt_${CODE}_${expert_id}.txt" \
        "/tmp/invest_result_${CODE}_${expert_id}.md" \
        "${expert_id}" &
done

wait
echo "=== 全部 7 位专家分析完成 ==="
```

#### 结果收集与验证

```bash
CODE="<ts_code>"

for EXPERT_ID in financial-auditor value-valuator growth-assessor moat-analyst cognitive-controller macro-cyclist management-auditor; do
    RESULT_FILE="/tmp/invest_result_${CODE}_${EXPERT_ID}.md"
    if [ -f "$RESULT_FILE" ] && [ -s "$RESULT_FILE" ]; then
        META=$(python3 -c "
import re, yaml
text = open('${RESULT_FILE}').read()
m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
if m:
    d = yaml.safe_load(m.group(1))
    print(f\"score={d.get('score','?')}, verdict={d.get('verdict','?')}\")
" 2>/dev/null || echo 'parse error')
        echo "✅ ${EXPERT_ID}: ${META}"
    else
        echo "❌ ${EXPERT_ID}: 结果缺失 → 重试一次，再失败则权重由其余专家均分"
    fi
done
```

**容错**：单个专家 spawn 失败 → 重试一次。两次失败 → 裁判长标注该专家缺失，权重由其余专家均分。

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

### 第八步：三人独立评审（2/3 准出，扣分制）

> ⚠️ 报告必须经过**三位独立评审员**的核查。评审员各自在独立子会话中并行工作，互不可见。**至少两位评审员给到 ≥ 80 分才准出。**

每位评审员拥有：
- **完整 invest-wiki 知识库**（`Read` 权限）——可查阅任何方法论页面验证报告声称
- **数据验证能力**（`Bash` 权限）——可调用 `data_tools.py` 重取数据、`curl` 查公开接口
- **相同评审材料**——最终报告 + 原始数据 + 7 份专家底稿 + 裁判长规则

#### spawn 三位评审员（并行）

> ⚠️ **短 prompt 方案**：评审材料（报告全文、原始数据、专家底稿、裁判规则）**不内联到 prompt 中**，而是通过**文件路径引用**。评审员在独立会话中用 `Read` 工具自行读取。这避免了 shell 的 `ARG_MAX` 限制（命令行参数长度上限）和 auto-classifier 对大型 heredoc 的拦截。

```bash
CODE="<ts_code>"
SKILL_ROOT="/home/bazinga/invest-skill"

spawn_reviewer() {
    local REVIEWER_NUM=$1

    # 将评审员 prompt 写入临时文件
    REVIEW_PROMPT_FILE="/tmp/invest_review_prompt_${CODE}_${REVIEWER_NUM}.txt"
    cat > "$REVIEW_PROMPT_FILE" << 'REVIEW_EOF'
你是 invest-skill 的**独立评审员 #${REVIEWER_NUM}**。你与其他评审员完全隔离，互不知晓对方的存在和判断。

## 你的角色

你不是重新分析公司。你是**质量核查员**——核查报告是否诚实、准确、逻辑自洽。

## 你的权限

- 📚 **Read**：读取 invest-wiki 任何方法论页面验证报告声称；读取所有评审材料文件
- 🔧 **Bash**：调用 \`python3 shared/data_tools.py <subcommand> ${CODE}\` 重取数据交叉验证

## 评审材料（用 Read 工具按需读取）

核心材料：
- **最终报告**：\`reports/invest_tool/${CODE}.md\`

事实基准：
- **原始数据**：\`/tmp/invest_data_${CODE}.json\`（所有报告数字必须可追溯到此文件）

专家底稿（验证报告是否忠实反映专家意见）：
- \`reports/invest_tool/${CODE%-*}/01-财务排雷官-珀莱雅.md\`（财务排雷官可能写到此路径）
- \`/tmp/invest_result_${CODE}_financial-auditor.md\`
- \`/tmp/invest_result_${CODE}_value-valuator.md\`
- \`/tmp/invest_result_${CODE}_growth-assessor.md\`
- \`/tmp/invest_result_${CODE}_moat-analyst.md\`
- \`/tmp/invest_result_${CODE}_cognitive-controller.md\`
- \`/tmp/invest_result_${CODE}_macro-cyclist.md\`
- \`/tmp/invest_result_${CODE}_management-auditor.md\`

裁判规则（验证裁判长是否按规则裁决）：
- \`../invest-wiki/04_stock-analysis-expert/adjudicator/裁判长-多框架裁判规则.md\`

方法论依据（按需查阅——只读与你正在核查的条款相关的专家文件）：
- \`../invest-wiki/04_stock-analysis-expert/experts/01-财务排雷官.md\`
- \`../invest-wiki/04_stock-analysis-expert/experts/02-价值估值师.md\`
- \`../invest-wiki/04_stock-analysis-expert/experts/03-成长质量师.md\`
- \`../invest-wiki/04_stock-analysis-expert/experts/04-护城河分析师.md\`
- \`../invest-wiki/04_stock-analysis-expert/experts/05-认知风控官.md\`
- \`../invest-wiki/04_stock-analysis-expert/experts/06-宏观周期师.md\`
- \`../invest-wiki/04_stock-analysis-expert/experts/07-管理层审计师.md\`

**工作目录**：\`${SKILL_ROOT}\`

## 评审流程

### 第一步：读取核心材料

首先读取最终报告。然后根据评审需要，选择性读取原始数据、专家底稿、裁判规则、方法论文件。不需要一次性全部读完，按需取用。

### 第二步：执行强制性验证清单

以下动作**不可跳过**，逐一完成并记录结果：

- [ ] **数据重取验证**：用 Bash 执行 \`python3 shared/data_tools.py market ${CODE}\` 和 \`python3 shared/data_tools.py indicators ${CODE}\`，将输出与报告中至少 5 个关键数字交叉比对
- [ ] **VETO 矩阵核查**：逐行对照裁判规则中的 VETO 条件表（5 项），检查裁判长裁决是否逐项覆盖、结论是否正确
- [ ] **加权评分重算**：从各专家 frontmatter 提取 score，按 wiki 权重独立重算综合分，与裁判长结果比对
- [ ] **冲突矩阵逐行对照**：将裁判长的冲突裁决与 wiki 冲突矩阵逐行比对，确认没有引用不存在的矩阵行
- [ ] **方法论抽查**：选择至少 3 位专家的 wiki 方法论文件，列出其必检项清单，逐项对照专家输出是否全部覆盖
- [ ] **交叉比对**：选择至少 5 对「不同专家对同一基础数据的描述」（如营收、毛利率、ROE），检查是否存在矛盾且裁判长未识别

### 第三步：重点关注区域

以下区域最容易出错，在常规检查之外给予额外注意：

1. **裁判长 VETO 检查表**——遗漏一项就是 -20 分。逐一验证 5 项 VETO 条件的触发状态。
2. **专家 frontmatter 与实际分析的一致性**——expert 写了 score=85 但正文有明显 VETO 触发信号？扣 2.3（-20）。
3. **「行业平均」「历史中枢」「市场普遍」「据统计」等无来源对比断言**——这类数字在原始数据中不可能找到来源。扣 1.4（-10/个）。
4. **加权评分的认知修正**——wiki 规定认知风控官 WARN 触发 8.5 折，VETO 触发 7 折。确认裁判长是否正确应用。
5. **Fisher 二季度触发器**（成长质量师）——此条款的 VETO/WARN 边界判断是历史高频出错点，逐季验算单季利润增速。

### 第四步：差异化深度核查

在你的基础评审之上，额外聚焦以下维度（三位评审员各有侧重，互不知晓）：

$(case ${REVIEWER_NUM} in
    1) echo "**你的深度领域：数据可追溯性 + 内部一致性**
- 至少验证 15 个报告中的数字在原始数据中可溯源
- 全文搜索关键指标（PE、ROE、毛利率、营收），确认前后章节数值一致
- 抽查 3 个派生计算（如 Graham Number、PEG、CAGR）用 Bash 独立重算" ;;
    2) echo "**你的深度领域：方法论忠实度 + 逻辑与表述**
- 至少查阅 4 位专家的 wiki 方法论原文，逐项核对必检项覆盖
- 识别报告中的循环论证、因果倒置、模糊措辞
- 检查每位专家的核心发现是否都在报告中有体现" ;;
    3) echo "**你的深度领域：裁判长诚实性 + 全文交叉验证**
- 逐行对照裁判规则冲突矩阵与裁判长裁决，确认没有引用不存在的矩阵行
- 逐位检查专家底稿中的关键否定意见是否被裁判长回应（而非忽略）
- 用 Bash 重取全部 7 个子命令的数据，做一轮完整的独立交叉验证" ;;
esac)

## 评审规则：扣分制

从 **100 分**起扣。同一问题跨多个类别，只扣最高的一项。

### 一、数据可追溯性（满分 25）

| # | 扣分项 | 扣分 | 检查方式 |
|---|--------|:----:|---------|
| 1.1 | 报告中的数字在原始数据中找不到来源 | -8/个 | 在 \`/tmp/invest_data_${CODE}.json\` 中搜索对应字段和数值 |
| 1.2 | 引用了不存在的字段名（如把 \`total_revenue\` 写成 \`revenue\`） | -5/个 | 对照原始数据 JSON 的 key |
| 1.3 | 单位换算错误（万元当成元、亿元当成万元等） | -10/个 | 核对数量级：总市值÷股价≈总股本 |
| 1.4 | 使用了「行业平均」「市场普遍」「据统计」「历史中枢」等无来源的对比数据 | -10/个 | 在原始数据和专家底稿中搜索来源 |
| 1.5 | 数字明显不合常理（如 ROE 500%、PE 0.01）但未被质疑 | -12/个 | 常识判断 + 可调 \`data_tools.py indicators\` 验证 |

### 二、方法论忠实度（满分 25）

| # | 扣分项 | 扣分 | 检查方式 |
|---|--------|:----:|---------|
| 2.1 | 专家的结论与其 wiki 方法论矛盾（如方法论说「OCF/NI<0.8 为危险」但专家给了 PASS） | -15/个 | 读专家的 wiki 文件，对照其结论 |
| 2.2 | 专家跳过了方法论中标记为「必检」的检查项 | -8/个 | 读 wiki 方法论，列出必检项，对照专家输出 |
| 2.3 | VETO 条件触发但专家未标注 ⛔ VETO | -20/个 | 对照裁判长规则中的 VETO 表 |
| 2.4 | 专家的分析引用了 wiki 中不存在的概念或捏造的引用 | -10/个 | 搜索 wiki 目录验证引用 |

### 三、裁判长诚实性（满分 25）

| # | 扣分项 | 扣分 | 检查方式 |
|---|--------|:----:|---------|
| 3.1 | 裁判长选择性忽略了某位专家的关键否定意见 | -15/个 | 逐位专家底稿 vs 裁判长裁决，找未被回应的重大否定 |
| 3.2 | 裁判长的 VETO 检查遗漏了某位专家触发的 VETO 条件 | -20/个 | 逐位专家 frontmatter 的 \`veto_triggers\` vs 裁判长裁决 |
| 3.3 | 加权评分计算错误（如果 wiki 规则要求加权） | -8/处 | 用 frontmatter 分数 × wiki 权重，重新计算验证 |

### 四、内部一致性（满分 15）

| # | 扣分项 | 扣分 | 检查方式 |
|---|--------|:----:|---------|
| 4.1 | 不同专家对同一数据源得出矛盾结论，且裁判长未识别（如 A 说「现金流健康」B 说「现金流紧张」——同一份 \`n_cashflow_act\`） | -10/对 | 交叉比对专家底稿中对同一字段的描述 |
| 4.2 | 报告前后矛盾（如估值章节说 PE=15、核心速览表说 PE=25） | -10/处 | 全文搜索关键指标，核对一致性 |

### 五、逻辑与表述（满分 10）

| # | 扣分项 | 扣分 | 检查方式 |
|---|--------|:----:|---------|
| 5.1 | 循环论证（「因为好所以值得买，因为值得买所以好」） | -5/处 | 通读裁决书，识别逻辑链条断裂 |
| 5.2 | 因果倒置（如「因为股价涨了所以 ROE 高」） | -5/处 | 检查因果方向 |
| 5.3 | 某位专家的核心发现完全没有出现在报告中（重大遗漏） | -10/位 | 逐位检查专家分析的核心结论是否在报告中有体现 |

> 💡 **扣分纪律**：必须给出具体证据——「报告中第 X 节说『……』，但原始数据中对应字段的值为 Y，两者不符。」不能凭感觉扣分。

## 输出格式

\`\`\`markdown
## 评审报告（评审员 #${REVIEWER_NUM}）

> 与其他评审员完全隔离，独立核查。以完整 invest-wiki 为知识库，使用数据接口进行事实核查。

### 评审过程

（简述做了哪些验证动作：读了多少材料、调了哪些数据接口、做了多少项独立重算。列出强制性清单的完成情况。）

### 深度核查（差异化领域）

（简述在你的深度领域中做了哪些额外检查，发现了什么。）

### 扣分明细

| 条款 | 问题描述 | 证据 | 扣分 |
|------|---------|------|:---:|
| ... | ... | ... | ... |

### 观察项（不扣分但值得记录）

（可选。记录边界情况——不算错误但有改进空间的地方。）

### 得分汇总

| 检查维度 | 满分 | 扣分 | 得分 |
|---------|:----:|:----:|:----:|
| 数据可追溯性 | 25 | -X | XX |
| 方法论忠实度 | 25 | -X | XX |
| 裁判长诚实性 | 25 | -X | XX |
| 内部一致性 | 15 | -X | XX |
| 逻辑与表述 | 10 | -X | XX |
| **总分** | **100** | **-X** | **XX** |

### 评审结论

**评审员 #${REVIEWER_NUM} 得分：XX / 100**

**判定：[ ] PASS（≥80 分，报告可信） [ ] FLAGGED（60-79 分，存在需要关注的问题） [ ] REJECT（<60 分，存在严重错误，不应发布）**

（必须勾选一个。判定基于得分，不是主观感受。）
\`\`\`
" --permission-mode bypassPermissions --allowedTools "Read,Bash"         > /tmp/invest_review_${CODE}_${REVIEWER_NUM}.md         2>/tmp/invest_stderr_review_${CODE}_${REVIEWER_NUM}.log

    echo "[DONE] 评审员 #${REVIEWER_NUM}"
}

# ── 并行启动三位评审员 ──
spawn_reviewer 1 &
spawn_reviewer 2 &
spawn_reviewer 3 &

wait
echo "=== 三位评审员全部完成 ==="
```

#### 评审失败处理

> ⚠️ 若并行 spawn 后，有评审员因 API 配额、超时、网络等原因**未成功返回结果**，主会话必须按以下流程处理，**不得默认继续生成报告**。

1. **识别失败评审员**：检查 `/tmp/invest_review_${CODE}_${N}.md` 是否存在且非空；若为空或不存在，视为失败。
2. **补充建立评审**：优先单独重试失败的评审员：
   ```bash
   # 仅重试失败的评审员，不要一次性全部重跑
   # 通过平台适配层重试失败的评审员
   spawn_reviewer \
       "${N}" \
       "/tmp/invest_review_prompt_${CODE}_${N}.txt" \
       "/tmp/invest_review_${CODE}_${N}.md"
   ```
3. **用户确认**：若重试仍失败，主会话必须向用户说明情况并询问：
   - "评审员 #N 因 API 配额限制无法完成，是否继续补充建立评审员评审？"
   - 若用户选择继续 → 等待配额恢复后重试；
   - 若用户选择跳过 → 按 `MISSING` 处理，生成 INCOMPLETE 标注。
4. **INCOMPLETE 阈值**：当缺失/失败评审员 ≥ 2 位时，报告准出状态为 **INCOMPLETE（评审无效）**，必须在报告末尾明确标注。

#### 评审结果汇总与准出判定

```bash
CODE="<ts_code>"
REPORT_FILE="reports/invest_tool/${CODE}.md"

# 统计三位评审员的得分和判定
PASS_COUNT=0
FLAGGED_COUNT=0
REJECT_COUNT=0
MISSING_COUNT=0
SCORES=""

for N in 1 2 3; do
    REVIEW_FILE="/tmp/invest_review_${CODE}_${N}.md"
    if [ -f "$REVIEW_FILE" ] && [ -s "$REVIEW_FILE" ]; then
        # 提取得分
        SCORE=$(grep -oP '得分：\K[0-9]+' "$REVIEW_FILE" 2>/dev/null | head -1 || echo "?")
        # 提取判定
        VERDICT=$(grep -oP '(?<=\[x\] |\[X\] )(PASS|FLAGGED|REJECT)' "$REVIEW_FILE" 2>/dev/null || echo "UNKNOWN")
        case "$VERDICT" in
            PASS)    PASS_COUNT=$((PASS_COUNT + 1)) ;;
            FLAGGED) FLAGGED_COUNT=$((FLAGGED_COUNT + 1)) ;;
            REJECT)  REJECT_COUNT=$((REJECT_COUNT + 1)) ;;
            *)       FLAGGED_COUNT=$((FLAGGED_COUNT + 1)) ;;
        esac
        SCORES="${SCORES}  评审员 #${N}: ${SCORE}/100 → ${VERDICT}\n"
    else
        MISSING_COUNT=$((MISSING_COUNT + 1))
        SCORES="${SCORES}  评审员 #${N}: 缺失\n"
    fi
done

# 准出判定
echo ""
if [ $PASS_COUNT -ge 2 ]; then
    EXIT_STATUS="✅ PASS"
    EXIT_DESC="至少 2 位评审员评分 ≥ 80，准出通过"
elif [ $MISSING_COUNT -ge 2 ]; then
    EXIT_STATUS="⚠️ INCOMPLETE"
    EXIT_DESC="超过半数评审员缺失，评审无效"
elif [ $REJECT_COUNT -ge 2 ]; then
    EXIT_STATUS="❌ REJECT"
    EXIT_DESC="至少 2 位评审员评分 < 60，建议重新生成报告"
else
    EXIT_STATUS="⚠️ FLAGGED"
    EXIT_DESC="评审意见分歧或多数评分在 60-79，需人工判断"
fi

# 追加评审汇总和全部评审意见到报告
cat >> "$REPORT_FILE" << REVIEW_SECTION

---

## 独立评审（三人制，扣分制，2/3 准出）

> **准出结果：${EXIT_STATUS}** | PASS=${PASS_COUNT}/3 | FLAGGED=${FLAGGED_COUNT}/3 | REJECT=${REJECT_COUNT}/3 | 缺失=${MISSING_COUNT}/3
>
> ${EXIT_DESC}
>
> 三位评审员在独立会话中并行工作，互不知晓彼此判断。每位评审员拥有完整 invest-wiki 知识库及数据接口验证能力。

### 评审得分

$(echo -e "${SCORES}")

---

REVIEW_SECTION

for N in 1 2 3; do
    REVIEW_FILE="/tmp/invest_review_${CODE}_${N}.md"
    if [ -f "$REVIEW_FILE" ] && [ -s "$REVIEW_FILE" ]; then
        cat "$REVIEW_FILE" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
    fi
done

echo "[DONE] 评审完成，准出：${EXIT_STATUS}"
```

**准出规则**：

| 评审结果 | 条件 | 行动 |
|---------|------|------|
| ✅ PASS | ≥ 2 位评审员 ≥ 80 分 | 报告准出，正常发布 |
| ❌ REJECT | ≥ 2 位评审员 < 60 分 | 建议重新生成报告 |
| ⚠️ FLAGGED | 其他所有情况 | 质量存疑，标注问题，用户自行判断 |
| ⚠️ INCOMPLETE | ≥ 2 位评审员缺失 | 评审无效，标注「未经独立评审」 |

> 💡 不阻塞：即使三人全部 spawn 失败，报告仍然生成并标注状态。三份评审意见全文追加到报告末尾，用户可以看到每一位评审员的扣分明细、验证动作和判定理由。

---

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

# 2. 并行 spawn 7 位专家（platforms/current/spawn.sh）
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
