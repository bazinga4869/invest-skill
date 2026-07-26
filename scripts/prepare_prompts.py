#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 7 位专家的 prompt 文件。

用法：
    python3 scripts/prepare_prompts.py 603605.SH

输出：
    /tmp/invest_prompt_<code>_<expert_id>.txt      # 7 位专家
    /tmp/invest_data_<code>.json                   # 原始数据
    /tmp/invest_annual_<code>.txt                  # 年报全量章节（调试/裁判长查阅用）

硬失败策略（与 SKILL.md「异常处理」一致）：
    - 数据获取失败          → 退出码 2
    - 年报文本抓取/解析失败 → 退出码 2（反叙事验证是 7 位专家的共同责任，不可跳过继续）

退出码：0 成功；2 数据或年报不可用。
"""
import argparse
import datetime as dt
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
WIKI_ROOT = SKILL_ROOT.parent / "invest-wiki" / "04_stock-analysis-expert"
DB_PATH = SKILL_ROOT / "data" / "invest_skill.db"

EXPERTS = [
    ("financial-auditor", "01-财务排雷官"),
    ("value-valuator", "02-价值估值师"),
    ("growth-assessor", "03-成长质量师"),
    ("moat-analyst", "04-护城河分析师"),
    ("cognitive-controller", "05-认知风控官"),
    ("macro-cyclist", "06-宏观周期师"),
    ("management-auditor", "07-管理层审计师"),
]

# --- 年报章节按专家裁剪 -------------------------------------------------------
# 反叙事交叉验证是每位专家的共同责任，核心章节全员必给；
# 其余章节按专家关注域裁剪，控制 prompt 体积（匹配方式为子串包含）。
_CORE_SECTIONS = ["管理层讨论与分析", "经营情况讨论与分析", "公司未来发展的展望", "可能面对的风险"]

EXPERT_SECTIONS = {
    "financial-auditor": _CORE_SECTIONS + ["重要事项", "募集资金使用", "财务报告"],
    "value-valuator": _CORE_SECTIONS + ["重要事项"],
    "growth-assessor": _CORE_SECTIONS + ["核心竞争力分析"],
    "moat-analyst": _CORE_SECTIONS + ["核心竞争力分析"],
    "cognitive-controller": _CORE_SECTIONS + ["重要事项", "公司治理"],
    "macro-cyclist": ["管理层讨论与分析", "经营情况讨论与分析"],
    "management-auditor": _CORE_SECTIONS + ["公司治理", "股份变动及股东情况", "重要事项"],
}

SECTION_CHAR_CAP = 12000          # 单章节字符上限
ANNUAL_BUDGET_CHARS = 240_000     # 单专家年报文本总预算（超出时丢弃最早年份）


def fetch_data(ts_code: str) -> str:
    """调用 data_tools.py all 获取全部财务与行情数据。"""
    print(f"[prepare] 获取数据 {ts_code} ...", flush=True)
    result = subprocess.run(
        ["python3", str(SKILL_ROOT / "shared" / "data_tools.py"), "all", ts_code],
        capture_output=True, text=True, timeout=300, cwd=str(SKILL_ROOT)
    )
    if result.returncode != 0:
        raise RuntimeError(f"数据获取失败: {result.stderr[-500:]}")
    return result.stdout


def fetch_annual_rows(ts_code: str, years: int = 5) -> list:
    """抓取最近 N 年年报全文（写入 DB），返回结构化章节行。

    硬失败：子进程失败或 DB 无记录时抛 RuntimeError。
    """
    proc = subprocess.run(
        ["python3", str(SKILL_ROOT / "shared" / "data_tools.py"), "annual-report", ts_code],
        capture_output=True, text=True, timeout=600, cwd=str(SKILL_ROOT)
    )
    if proc.returncode != 0:
        raise RuntimeError(f"年报抓取失败(exit={proc.returncode}): {proc.stderr[-500:]}")

    if not DB_PATH.exists():
        raise RuntimeError(f"数据库不存在: {DB_PATH}")

    start_year = dt.datetime.now().year - years + 1
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        """SELECT report_year, report_type, section_name, section_text, ann_date, title
           FROM annual_reports
           WHERE ts_code=? AND CAST(report_year AS INTEGER) >= ?
           ORDER BY report_year DESC, report_type, section_name""",
        (ts_code, start_year)
    ).fetchall()
    conn.close()

    if not rows:
        raise RuntimeError(
            f"年报文本不可得（{ts_code} 最近 {years} 年无记录）。"
            "按 SKILL.md 异常处理：硬失败，禁止跳过反叙事步骤继续分析。"
        )
    return rows


def dump_annual_full(rows: list) -> str:
    """全量章节文本（落盘供调试/裁判长查阅），不受专家预算限制。"""
    parts = []
    for year, rt, sec, text, ann_date, title in rows:
        parts.append(f"\n### {year}年 {rt}（公告日：{ann_date}，标题：{title}）\n"
                     f"#### {sec}\n{(text or '')[:SECTION_CHAR_CAP]}\n")
    return "\n".join(parts)


def format_annual_text(rows: list, expert_id: str, budget: int = ANNUAL_BUDGET_CHARS) -> str:
    """按专家关注域筛选章节并格式化，总量受 budget 约束。

    rows 已按年份降序排列；预算耗尽时丢弃最早年份并显式标注。
    """
    wanted = EXPERT_SECTIONS.get(expert_id, _CORE_SECTIONS)
    selected = [r for r in rows if any(w in (r[2] or "") for w in wanted)]

    parts = ["\n## 公司年报文本（最近 3-5 年关键章节，按你的专业域筛选）\n"]
    total = 0
    truncated = False
    current_key = None
    for year, rt, sec, text, ann_date, title in selected:
        block = (text or "")[:SECTION_CHAR_CAP]
        if total + len(block) > budget:
            truncated = True
            break
        key = (year, rt)
        if key != current_key:
            parts.append(f"\n### {year}年 {rt}（公告日：{ann_date}，标题：{title}）\n")
            current_key = key
        parts.append(f"\n#### {sec}\n{block}\n")
        total += len(block)
    if truncated:
        parts.append("\n> 注：受篇幅预算限制，更早年份的章节未纳入；如需引用请在「数据使用说明」中标注。\n")
    if not selected:
        parts.append("\n（数据库中无与你专业域匹配的年报章节。）\n")
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
        candidates = list(wiki_root.rglob(f"{pagename}.md"))
        if candidates:
            found = candidates[0]
        else:
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


def build_expert_prompt(expert_id: str, filename: str, ts_code: str, name: str,
                        data_text: str, annual_text: str, data_date: str, wiki_root: Path) -> str:
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

以下是 {name}（{ts_code}）的完整财务与行情数据。所有数据来自 Tushare Pro，已经过 Python 数据管道处理。数据基准日：{data_date}。

原始数据 JSON 的 `industry` 字段包含目标公司所在行业的横向对比（均值、中位数、P25/P75 分位、目标公司在行业中的排名百分位）。**如果你的方法论需要做行业对比，请优先使用 `industry.industry_stats` 和 `industry.target` 中的实际数据，不要编造「行业平均」。**

```json
{data_text}
```

## 公司年报与管理层的自述（最近 3-5 年关键章节）

{annual_text}

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
- 🚫 **frontmatter 中 `data_date` 已预填为本次数据基准日，禁止修改或省略**——它用于校验你的分析是否与本次数据批次一致。
- ✅ **VETO 必须进 frontmatter**：如果触发 VETO，`veto_triggers` 字段必须非空，正文中必须标注 ⛔ VETO。

## 输出格式

你的输出将直接成为最终投资报告的一个章节。请在文件**最开头**放一段 YAML frontmatter，供裁判长提取关键信息，然后用 Markdown 撰写完整的分析正文。

```
---
expert_id: "{expert_id}"
data_date: "{data_date}"
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


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 invest-skill 专家 prompt")
    parser.add_argument("ts_code", help="股票代码，如 603605.SH")
    parser.add_argument("--name", help="公司中文名（可选，自动从数据中获取）")
    args = parser.parse_args()

    ts_code = args.ts_code
    try:
        data_text = fetch_data(ts_code)
    except RuntimeError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2

    data_file = Path(f"/tmp/invest_data_{ts_code}.json")
    data_file.write_text(data_text, encoding="utf-8")
    print(f"[1/2] 数据已写入 {data_file}")

    try:
        data_json = json.loads(data_text)
    except json.JSONDecodeError:
        data_json = {}
    name = args.name or data_json.get("stock_info", {}).get("name", ts_code)
    data_date = str(data_json.get("market", {}).get("trade_date") or "unknown")

    print("[prepare] 获取年报文本 ...", flush=True)
    try:
        rows = fetch_annual_rows(ts_code, years=5)
    except RuntimeError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2

    annual_file = Path(f"/tmp/invest_annual_{ts_code}.txt")
    annual_file.write_text(dump_annual_full(rows), encoding="utf-8")
    print(f"[1/2] 年报全量文本已写入 {annual_file}（{len(rows)} 个章节）")

    for expert_id, filename in EXPERTS:
        annual_text = format_annual_text(rows, expert_id)
        prompt = build_expert_prompt(
            expert_id, filename, ts_code, name, data_text, annual_text, data_date, WIKI_ROOT
        )
        prompt_file = Path(f"/tmp/invest_prompt_{ts_code}_{expert_id}.txt")
        prompt_file.write_text(prompt, encoding="utf-8")
        print(f"[2/2] 专家 prompt: {prompt_file}（{len(prompt)} 字符）")

    print("=== 全部 prompt 准备完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
