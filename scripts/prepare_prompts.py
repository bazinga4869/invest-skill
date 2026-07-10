#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 7 位专家 + 3 位评审员的 prompt 文件。

用法：
    python3 scripts/prepare_prompts.py 603605.SH

输出：
    /tmp/invest_prompt_<code>_<expert_id>.txt      # 7 位专家
    /tmp/invest_review_prompt_<code>_<N>.txt       # 3 位评审员
    /tmp/invest_data_<code>.json                   # 原始数据
"""
import argparse
import re
import subprocess
from pathlib import Path
import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
WIKI_ROOT = SKILL_ROOT.parent / "invest-wiki" / "04_stock-analysis-expert"

EXPERTS = [
    ("financial-auditor", "01-财务排雷官"),
    ("value-valuator", "02-价值估值师"),
    ("growth-assessor", "03-成长质量师"),
    ("moat-analyst", "04-护城河分析师"),
    ("cognitive-controller", "05-认知风控官"),
    ("macro-cyclist", "06-宏观周期师"),
    ("management-auditor", "07-管理层审计师"),
]


def fetch_data(ts_code: str) -> str:
    """调用 data_tools.py all 获取全部财务与行情数据（不含年报文本，保持快速）。"""
    result = subprocess.run(
        ["python3", str(SKILL_ROOT / "shared" / "data_tools.py"), "all", ts_code],
        capture_output=True, text=True, timeout=120, cwd=str(SKILL_ROOT)
    )
    if result.returncode != 0:
        raise RuntimeError(f"数据获取失败: {result.stderr}")
    return result.stdout


def fetch_annual_reports(ts_code: str, years: int = 5) -> str:
    """
    调用 data_tools.py annual-report 抓取并解析最近 N 年年报全文，
    然后从数据库读取关键章节，整理为文本块。
    """
    subprocess.run(
        ["python3", str(SKILL_ROOT / "shared" / "data_tools.py"), "annual-report", ts_code],
        capture_output=True, text=True, timeout=600, cwd=str(SKILL_ROOT)
    )

    import sqlite3
    db_path = SKILL_ROOT / "data" / "invest_skill.db"
    if not db_path.exists():
        return ""

    conn = sqlite3.connect(str(db_path))
    cur_year = 2099  # 占位
    try:
        import datetime as dt
        cur_year = dt.datetime.now().year
    except Exception:
        pass
    start_year = cur_year - years + 1

    # 优先读取关键章节；管理层审计师需要公司治理等，因此把公司治理、股份变动也纳入
    priority_sections = [
        "管理层讨论与分析",
        "经营情况讨论与分析",
        "核心竞争力分析",
        "公司未来发展的展望",
        "可能面对的风险",
        "重要事项",
        "股份变动及股东情况",
        "公司治理",
        "募集资金使用",
        "全文",
    ]

    rows = conn.execute(
        """SELECT report_year, report_type, section_name, section_text, ann_date, title
           FROM annual_reports
           WHERE ts_code=? AND CAST(report_year AS INTEGER) >= ?
           ORDER BY report_year DESC, report_type, section_name""",
        (ts_code, start_year)
    ).fetchall()
    conn.close()

    if not rows:
        return ""

    # 按年度-报告类型-章节组织
    parts = ["\n## 公司年报文本（最近 3-5 年关键章节）\n"]
    current_year_rt = None
    for year, rt, sec, text, ann_date, title in rows:
        key = (year, rt)
        if key != current_year_rt:
            parts.append(f"\n### {year}年 {rt}（公告日：{ann_date}，标题：{title}）\n")
            current_year_rt = key
        parts.append(f"\n#### {sec}\n{text[:12000]}\n")  # 单章节上限，避免 prompt 过长

    return "\n".join(parts)


def read_wiki_pages(method_text: str, wiki_root: Path) -> str:
    """提取方法论中的 [[wikilink]]，读取对应 wiki 页面内容。"""
    refs = re.findall(r'\[\[(.+?)\]\]', method_text)
    pages = {}
    for ref in refs:
        pagename = ref.split('|')[0].strip()
        if pagename in pages or not pagename:
            continue
        found = None
        # 精确匹配
        candidates = list(wiki_root.rglob(f"{pagename}.md"))
        if candidates:
            found = candidates[0]
        else:
            # 按 title 模糊匹配
            for p in wiki_root.rglob("*.md"):
                try:
                    text = p.read_text(encoding="utf-8")
                    if re.search(rf'title:\s*.*{re.escape(pagename)}', text):
                        found = p
                        break
                except Exception:
                    continue
        if found and found.exists() and found.stat().st_size > 0:
            pages[pagename] = found.read_text(encoding="utf-8")

    parts = []
    for name, content in pages.items():
        parts.append(f"\n\n---\n## {name}\n\n{content}")
    return "".join(parts)


def get_title(method_file: Path) -> str:
    """从 wiki 专家文件的 YAML frontmatter 提取 title。"""
    text = method_file.read_text(encoding="utf-8")
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if m:
        try:
            d = yaml.safe_load(m.group(1))
            return d.get('title', method_file.stem)
        except Exception:
            pass
    return method_file.stem


def build_expert_prompt(expert_id: str, filename: str, ts_code: str, name: str, data_text: str, annual_text: str, wiki_root: Path) -> str:
    method_file = wiki_root / "experts" / f"{filename}.md"
    if not method_file.exists():
        raise FileNotFoundError(f"专家文件缺失: {method_file}")

    method_text = method_file.read_text(encoding="utf-8")
    title = get_title(method_file)
    supp = read_wiki_pages(method_text, wiki_root)

    # 认知风控官额外任务：管理层叙事审计
    cognitive_extra = ""
    if expert_id == "cognitive-controller":
        cognitive_extra = """
### 认知风控官专项任务：管理层叙事审计（必须完成）

你不仅要做常规认知偏误检查，还必须对年报文本进行**管理层叙事审计**：

1. **逐条列出管理层在年报中的关键主张**（战略方向、增长解释、风险判断、投资理由）。
2. **用财务数字验证每一条主张**：能验证的标注「可验证」并给出数据；无法验证的标注「愿景/叙事」。
3. **检查「这次不一样」陷阱**：管理层是否用新名词（如芯片、AI、出海、国产替代、第二曲线）包装老业务或掩盖问题？
4. **检查言行一致性**：对比最近 3-5 年年报，管理层是否反复变更战略方向？过去的承诺是否兑现？
5. **如果你是做空者**：你会如何反驳这份年报的管理层论述？列出最强 3 条反驳。
6. **在「关键风险与不确定性」中专门增加「叙事风险」小节**，明确说明哪些管理层论述可能误导投资者。
"""

    return f"""你是 invest-skill 专家团成员。

## 你的方法论（来自 invest-wiki）

以下是你完整的分析框架——身份、师承、使命、检查清单、判定标准、否决条件。请以它为大脑进行思考和分析。

{method_text}

## 补充 wiki 知识（主会话已为你预取）

以下内容来自 invest-wiki 中你的方法论所引用的知识页面。这些是分析中涉及的关键概念、公式定义和案例参照的原文。请作为方法论的组成部分来阅读。

{supp}

## 目标公司原始数据

以下是 {name}（{ts_code}）的完整财务与行情数据。所有数据来自 Tushare Pro，已经过 Python 数据管道处理。

原始数据 JSON 的 `industry` 字段包含目标公司所在行业的横向对比（均值、中位数、P25/P75 分位、目标公司在行业中的排名百分位）。**如果你的方法论需要做行业对比，请优先使用 `industry.industry_stats` 和 `industry.target` 中的实际数据，不要编造「行业平均」。**

```json
{data_text}
```

## 公司年报与管理层的自述（最近 3-5 年关键章节）

{annual_text if annual_text else "（本次未成功抓取到公司年报文本。请仅基于上方财务数据进行分析，并在「数据使用说明」中标注「年报文本不可得」。）"}

## 你的任务

以一位资深投资分析师的身份，基于你的方法论，对 {name} 进行**定量与定性兼备**的深度评估。

**反叙事要求（每位专家都必须执行）**：

你不只是要「读数字」或「读管理层说什么」。你必须做**财务数字 vs 管理层文字**的交叉验证：

- 当管理层解释业绩变化时，检查其解释是否与财务数据一致；
- 当管理层描述竞争优势或战略方向时，检查是否有过去 3-5 年的言行一致性证据；
- 当管理层使用宏大叙事（如「第二曲线」「战略转型」「把握历史性机遇」）时，检查其是否已经或正在产生可量化的财务结果；
- 如果你发现管理层的文字论述与财务数字矛盾、或无法被验证、或存在明显的修辞包装，必须在分析中明确标注并说明影响。

**写作要求**：

1. **有人味，不要像机器**：用自然的中文撰写，就像你在给一位信任你的投资合伙人写分析备忘录。有数据，有逻辑，也有判断。
2. **定量分析**：列出关键数字，展示计算过程（公式 → 代入 → 结果），标注每个数字的数据来源。
3. **定性分析**：数字只是起点。解释数字背后的含义——它揭示了什么商业模式特征？什么竞争态势？什么风险信号？什么被市场忽略了？
4. **正反两面**：既写有利证据，也写不利证据。诚实是最好的分析。
5. **不确定性的诚实**：如果某些检查因数据缺失无法完成，坦率标注「数据不可得」并说明这对结论的影响。不要假装确定。
6. **如果触发 VETO，明确说出来**：在你的方法论中，某些条件是硬性的否决项。如果你发现这些条件被触发，在分析中明确标注 ⛔ VETO 并解释原因。
{cognitive_extra}
**严格约束（违反将直接导致评审扣分）**：

- 🚫 **禁止无来源对比**：不得使用「行业平均」「市场普遍」「据统计」「历史中枢」「行业常见水平」等无法追溯到上方原始数据的断言。若必须做行业/历史对比，必须标注「数据不可得」。
- 🚫 **禁止未经核对的历史断言**：在写出「首次」「连续 N 年」「历史新高/最低」「上市以来首次」等表述前，必须列出完整比较年份的数据并逐项核对。若发现不符合，立即修正措辞。
- 🚫 **frontmatter 格式**：直接以 `---` 开头和结束，**不要**用 ```` ```yaml ```` 代码块包裹，否则裁判长无法自动解析。
- ✅ **VETO 必须进 frontmatter**：如果触发 VETO，`veto_triggers` 字段必须非空，正文中必须标注 ⛔ VETO。

## 输出格式

你的输出将直接成为最终投资报告的一个章节。请在文件**最开头**放一段 YAML frontmatter，供裁判长提取关键信息，然后用 Markdown 撰写完整的分析正文。

```
---
expert_id: "{expert_id}"
score: <0-100 整数>
verdict: PASS | WARN | VETO
veto_triggers: []
---

# {title}评估 — {name}（{ts_code}）

## 总体判断

（2-4 句话的总结性判断。先说结论，再说依据。）

## 详细分析

（自由结构。用你的方法论框架组织分析，定量定性交织。可以包含表格、公式、推理链。）

## 关键风险与不确定性

（列出你的分析中最大的不确定性来源。）

## 数据使用说明

（简述你用了哪些数据，哪些数据缺失。）
```

## 重要约束

- 🚫 只分析你的专业领域，不要越界做其他专家的判断
- 🚫 不要给出投资建议（BUY/SELL/HOLD），那是裁判长的工作
- 🚫 不要编造数据，所有数字必须来自上方提供的原始数据
- 🚫 不要编造年报中不存在的管理层言论；所有关于管理层说法的引用必须来自上方提供的年报文本
- ✅ 你写的内容将直接成为最终报告的章节，请确保可以独立阅读
"""


def build_reviewer_prompt(num: int, ts_code: str, skill_root: Path, wiki_root: Path) -> str:
    focus = {
        1: """**你的深度领域：数据可追溯性 + 内部一致性**
- 至少验证 15 个报告中的数字在原始数据中可溯源
- 全文搜索关键指标（PE、ROE、毛利率、营收），确认前后章节数值一致
- 抽查 3 个派生计算（如 Graham Number、PEG、CAGR）用 Bash 独立重算""",
        2: """**你的深度领域：方法论忠实度 + 逻辑与表述**
- 至少查阅 4 位专家的 wiki 方法论原文，逐项核对必检项覆盖
- 识别报告中的循环论证、因果倒置、模糊措辞
- 检查每位专家的核心发现是否都在报告中有体现""",
        3: """**你的深度领域：裁判长诚实性 + 全文交叉验证**
- 逐行对照裁判规则冲突矩阵与裁判长裁决，确认没有引用不存在的矩阵行
- 逐位检查专家底稿中的关键否定意见是否被裁判长回应（而非忽略）
- 用 Bash 重取全部 7 个子命令的数据，做一轮完整的独立交叉验证"""
    }[num]

    return f"""你是 invest-skill 的**独立评审员 #{num}**。你与其他评审员完全隔离，互不知晓对方的存在和判断。

## 你的角色

你不是重新分析公司。你是**质量核查员**——核查报告是否诚实、准确、逻辑自洽。

## 你的权限

- 📚 **Read**：读取 invest-wiki 任何方法论页面验证报告声称；读取所有评审材料文件
- 🔧 **Bash**：调用 `python3 shared/data_tools.py <subcommand> {ts_code}` 重取数据交叉验证

## 评审材料（用 Read 工具按需读取）

核心材料：
- **最终报告**：`{skill_root}/reports/invest_tool/{ts_code}.md`

事实基准：
- **原始数据**：`/tmp/invest_data_{ts_code}.json`（所有报告数字必须可追溯到此文件）

专家底稿：
- `/tmp/invest_result_{ts_code}_financial-auditor.md`
- `/tmp/invest_result_{ts_code}_value-valuator.md`
- `/tmp/invest_result_{ts_code}_growth-assessor.md`
- `/tmp/invest_result_{ts_code}_moat-analyst.md`
- `/tmp/invest_result_{ts_code}_cognitive-controller.md`
- `/tmp/invest_result_{ts_code}_macro-cyclist.md`
- `/tmp/invest_result_{ts_code}_management-auditor.md`

裁判规则：
- `{wiki_root}/adjudicator/裁判长-多框架裁判规则.md`

方法论依据（按需读取）：
- `{wiki_root}/experts/01-财务排雷官.md`
- `{wiki_root}/experts/02-价值估值师.md`
- `{wiki_root}/experts/03-成长质量师.md`
- `{wiki_root}/experts/04-护城河分析师.md`
- `{wiki_root}/experts/05-认知风控官.md`
- `{wiki_root}/experts/06-宏观周期师.md`
- `{wiki_root}/experts/07-管理层审计师.md`

**工作目录**：`{skill_root}`

## 评审流程

### 第一步：读取核心材料

首先读取最终报告。然后根据需要选择性读取原始数据、专家底稿、裁判规则、方法论文件。

### 第二步：执行强制性验证清单

- [ ] **数据重取验证**：用 Bash 执行 `python3 shared/data_tools.py market {ts_code}` 和 `python3 shared/data_tools.py indicators {ts_code}`，将输出与报告中至少 5 个关键数字交叉比对
- [ ] **VETO 矩阵核查**：逐行对照裁判规则中的 VETO 条件表，检查裁判长裁决是否逐项覆盖、结论是否正确
- [ ] **加权评分重算**：从各专家 frontmatter 提取 score，按 wiki 权重独立重算综合分，与裁判长结果比对
- [ ] **冲突矩阵逐行对照**：将裁判长的冲突裁决与 wiki 冲突矩阵逐行比对，确认没有引用不存在的矩阵行
- [ ] **方法论抽查**：选择至少 3 位专家的 wiki 方法论文件，列出其必检项清单，逐项对照专家输出是否全部覆盖
- [ ] **交叉比对**：选择至少 5 对「不同专家对同一基础数据的描述」，检查是否存在矛盾且裁判长未识别

### 第三步：重点关注区域

1. **裁判长 VETO 检查表**——遗漏一项就是 -20 分。
2. **专家 frontmatter 与实际分析的一致性**。
3. **「行业平均」「市场普遍」「据统计」「历史中枢」等无来源对比断言**——扣 1.4（-10/个）。
4. **加权评分的认知修正**——wiki 规定认知风控官 WARN 触发 8.5 折，VETO 触发 7 折。
5. **Fisher 二季度触发器**——逐季验算单季利润增速。

### 第四步：差异化深度核查

{focus}

## 评审规则：扣分制

从 **100 分**起扣。同一问题跨多个类别，只扣最高的一项。

### 一、数据可追溯性（满分 25）

| # | 扣分项 | 扣分 | 检查方式 |
|---|--------|:----:|---------|
| 1.1 | 报告中的数字在原始数据中找不到来源 | -8/个 | 在 `/tmp/invest_data_{ts_code}.json` 中搜索 |
| 1.2 | 引用了不存在的字段名 | -5/个 | 对照原始数据 JSON 的 key |
| 1.3 | 单位换算错误 | -10/个 | 核对数量级 |
| 1.4 | 使用了「行业平均」「市场普遍」「据统计」「历史中枢」等无来源对比数据 | -10/个 | 在原始数据中搜索来源 |
| 1.5 | 数字明显不合常理但未被质疑 | -12/个 | 常识判断 + data_tools 验证 |

### 二、方法论忠实度（满分 25）

| # | 扣分项 | 扣分 | 检查方式 |
|---|--------|:----:|---------|
| 2.1 | 专家的结论与其 wiki 方法论矛盾 | -15/个 | 读 wiki 对照 |
| 2.2 | 专家跳过了方法论中标记为「必检」的检查项 | -8/个 | 列出必检项对照 |
| 2.3 | VETO 条件触发但专家未标注 ⛔ VETO | -20/个 | 对照裁判长规则 |
| 2.4 | 专家的分析引用了 wiki 中不存在的概念 | -10/个 | 搜索 wiki 目录 |

### 三、裁判长诚实性（满分 25）

| # | 扣分项 | 扣分 | 检查方式 |
|---|--------|:----:|---------|
| 3.1 | 裁判长选择性忽略某位专家的关键否定意见 | -15/个 | 底稿 vs 裁决 |
| 3.2 | 裁判长的 VETO 检查遗漏了某位专家触发的 VETO 条件 | -20/个 | frontmatter `veto_triggers` vs 裁决 |
| 3.3 | 加权评分计算错误 | -8/处 | 独立重算 |

### 四、内部一致性（满分 15）

| # | 扣分项 | 扣分 | 检查方式 |
|---|--------|:----:|---------|
| 4.1 | 不同专家对同一数据源得出矛盾结论，裁判长未识别 | -10/对 | 交叉比对 |
| 4.2 | 报告前后矛盾 | -10/处 | 全文搜索关键指标 |

### 五、逻辑与表述（满分 10）

| # | 扣分项 | 扣分 |
|---|--------|:----:|
| 5.1 | 循环论证 | -5/处 |
| 5.2 | 因果倒置 | -5/处 |
| 5.3 | 某位专家的核心发现完全没有出现在报告中 | -10/位 |

> 扣分必须给出具体证据。

## 输出格式

```markdown
## 评审报告（评审员 #{num}）

### 评审过程
（简述验证动作和强制性清单完成情况。）

### 深度核查
（差异化领域发现。）

### 扣分明细
| 条款 | 问题描述 | 证据 | 扣分 |
|------|---------|------|:---:|
| ... | ... | ... | ... |

### 观察项（不扣分）

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
**评审员 #{num} 得分：XX / 100**

**判定：[ ] PASS（≥80 分） [ ] FLAGGED（60-79 分） [x] REJECT（<60 分）**
```
"""


def main():
    parser = argparse.ArgumentParser(description="生成 invest-skill 专家/评审员 prompt")
    parser.add_argument("ts_code", help="股票代码，如 603605.SH")
    parser.add_argument("--name", help="公司中文名（可选，自动从 stock-info 获取）")
    args = parser.parse_args()

    ts_code = args.ts_code
    data_text = fetch_data(ts_code)
    data_file = Path(f"/tmp/invest_data_{ts_code}.json")
    data_file.write_text(data_text, encoding="utf-8")
    print(f"[1/3] 数据已写入 {data_file}")

    # 获取公司名
    name = args.name
    if not name:
        try:
            import json
            d = json.loads(data_text)
            name = d.get("stock_info", {}).get("name", ts_code)
        except Exception:
            name = ts_code

    # 获取年报文本
    annual_text = fetch_annual_reports(ts_code, years=5)
    annual_file = Path(f"/tmp/invest_annual_{ts_code}.txt")
    annual_file.write_text(annual_text, encoding="utf-8")
    print(f"[1/3] 年报文本已写入 {annual_file}")

    # 生成专家 prompt
    for expert_id, filename in EXPERTS:
        prompt = build_expert_prompt(expert_id, filename, ts_code, name, data_text, annual_text, WIKI_ROOT)
        prompt_file = Path(f"/tmp/invest_prompt_{ts_code}_{expert_id}.txt")
        prompt_file.write_text(prompt, encoding="utf-8")
        print(f"[2/3] 专家 prompt: {prompt_file}")

    # 生成评审员 prompt
    for num in [1, 2, 3]:
        prompt = build_reviewer_prompt(num, ts_code, SKILL_ROOT, WIKI_ROOT)
        prompt_file = Path(f"/tmp/invest_review_prompt_{ts_code}_{num}.txt")
        prompt_file.write_text(prompt, encoding="utf-8")
        print(f"[3/3] 评审员 prompt: {prompt_file}")

    print("=== 全部 prompt 准备完成 ===")


if __name__ == "__main__":
    main()
