#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组装 invest-skill 最终报告。

用法：
    python3 scripts/assemble_report.py 603605.SH --name 珀莱雅

工作流：
    1. 默认生成 reports/invest_tool/<code>.draft.md（嵌入专家原文 + 加权评分）
    2. 裁判长（主会话/裁决会话）完善草稿：裁决理由、一行总评、知识索引
    3. --finalize 校验草稿无占位符后更名为正式报告 <code>.md
       （不重新生成——重新生成会覆盖裁判长的裁决内容）

退出码：0 成功；2 草稿已生成但专家结果不完整（综合分 N/A）；1 错误。
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = SKILL_ROOT / "reports" / "invest_tool"
WIKI_ADJUDICATOR = (SKILL_ROOT.parent / "invest-wiki" / "04_stock-analysis-expert"
                    / "adjudicator" / "裁判长-多框架裁判规则.md")

EXPERTS = [
    "financial-auditor",
    "value-valuator",
    "growth-assessor",
    "moat-analyst",
    "cognitive-controller",
    "macro-cyclist",
    "management-auditor",
]

# 认知风控官不参与加权（wiki 规则），其 VETO/WARN 作为修正系数
EXPECTED_WEIGHT_KEYS = {
    "financial-auditor", "value-valuator", "moat-analyst",
    "growth-assessor", "management-auditor", "macro-cyclist",
}

# 定稿前必须被裁判长替换的占位符
FINALIZE_PLACEHOLDERS = ("待裁判长填写", "[HOLD / PASS / BUY / SELL / OBSERVE]")


def load_scoring_config() -> dict:
    """从 wiki 裁判规则文件解析机器可读 scoring 配置块。

    wiki 是评分规则的唯一来源，skill 不保存副本。
    硬失败：文件缺失、无 scoring 块、或配置非法时 SystemExit。
    """
    if not WIKI_ADJUDICATOR.exists():
        raise SystemExit(f"裁判规则文件不存在: {WIKI_ADJUDICATOR}")
    text = WIKI_ADJUDICATOR.read_text(encoding="utf-8")
    for block in re.findall(r'```yaml\s*\n(.*?)```', text, re.DOTALL):
        try:
            data = yaml.safe_load(block)
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("scoring"), dict):
            cfg = data["scoring"]
            weights = cfg.get("weights") or {}
            adj = cfg.get("cognitive_adjustment") or {}
            if set(weights) != EXPECTED_WEIGHT_KEYS:
                raise SystemExit(
                    f"scoring.weights 键集非法: {sorted(weights)}，"
                    f"应为 {sorted(EXPECTED_WEIGHT_KEYS)}（认知风控官不参与加权）"
                )
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < 1
                       for v in weights.values()):
                raise SystemExit("scoring.weights 存在非法权重值（需 0-1 之间的小数）")
            if not all(isinstance(adj.get(k), (int, float)) and 0 < adj.get(k) <= 1
                       for k in ("VETO", "WARN")):
                raise SystemExit("scoring.cognitive_adjustment 需含合法的 VETO/WARN 系数")
            return {
                "weights": {k: float(v) for k, v in weights.items()},
                "cognitive_adjustment": {"VETO": float(adj["VETO"]), "WARN": float(adj["WARN"])},
            }
    raise SystemExit(f"裁判规则文件中未找到 scoring 配置块（```yaml scoring: ... ```）: {WIKI_ADJUDICATOR}")


def load_results(ts_code: str) -> dict:
    results = {}
    for expert_id in EXPERTS:
        file_path = Path(f"/tmp/invest_result_{ts_code}_{expert_id}.md")
        if file_path.exists():
            results[expert_id] = file_path.read_text(encoding="utf-8")
        else:
            results[expert_id] = f"<!-- {expert_id} 结果缺失 -->\n"
    return results


def parse_frontmatter(text: str) -> dict:
    """解析 frontmatter，兼容裸 YAML、```yaml 包裹、以及 frontmatter 前有说明文字的情况。"""
    if not text:
        return {}

    # agent 有时会在 frontmatter 前输出说明性文字；允许 frontmatter 出现在前 10 行内
    lines = text.split("\n")
    if lines[0].strip() != "---":
        for i, line in enumerate(lines[:10]):
            if line.strip() == "---":
                text = "\n".join(lines[i:])
                break

    if not text:
        return {}

    # 先尝试裸 frontmatter
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass

    # 去掉 ```yaml / ``` 代码块标记后再尝试
    clean = re.sub(r'```yaml\s*\n', '', text)
    clean = re.sub(r'\n```\s*\n', '\n', clean)
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', clean, re.DOTALL)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass
    return {}


def compute_score(results: dict, scoring: dict) -> tuple:
    """返回 (raw, adjusted, scores, details, adjustment, complete)。

    权重与认知修正系数全部来自 wiki scoring 配置。
    任一专家结果缺失或 score 非法时 complete=False，raw/adjusted 为 None——
    综合分宁缺毋假。
    """
    scores = {}
    complete = True
    for expert_id in EXPERTS:
        text = results.get(expert_id, "")
        fm = parse_frontmatter(text)
        score = fm.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 100):
            score = None
        if score is None:
            complete = False
        scores[expert_id] = {
            "score": score,
            "verdict": fm.get("verdict", "UNKNOWN"),
            "veto_triggers": fm.get("veto_triggers", []),
        }

    if not complete:
        return None, None, scores, [], 1.0, False

    raw = 0.0
    details = []
    for expert_id, weight in scoring["weights"].items():
        s = scores[expert_id]["score"]
        contrib = s * weight
        raw += contrib
        details.append(f"{expert_id}: {s} × {weight} = {contrib:.2f}")

    cognitive_verdict = scores.get("cognitive-controller", {}).get("verdict", "PASS")
    adjustment = 1.0
    if cognitive_verdict == "VETO":
        adjustment = scoring["cognitive_adjustment"]["VETO"]
    elif cognitive_verdict == "WARN":
        adjustment = scoring["cognitive_adjustment"]["WARN"]

    adjusted = raw * adjustment
    return raw, adjusted, scores, details, adjustment, True


def load_data_summary(ts_code: str) -> dict:
    data_file = Path(f"/tmp/invest_data_{ts_code}.json")
    if not data_file.exists():
        return {}
    try:
        return json.loads(data_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_report(ts_code: str, name: str, results: dict, data: dict,
                 scoring: dict, degraded: bool = False) -> str:
    raw, adjusted, scores, details, adjustment, complete = compute_score(results, scoring)

    mode_desc = "降级模式：会话内顺序执行（隔离性受限）" if degraded else "独立进程隔离"
    mode_how = ("会话内顺序执行 7 域分析（fallback，隔离性受限）+ 裁判长综合裁决"
                if degraded else
                "独立 agent 进程并行执行 7 域分析 + 裁判长综合裁决（主会话）")

    market = data.get("market", {})
    stock_info = data.get("stock_info", {})
    annual = data.get("annual", {})
    balance = data.get("balance", {})
    indicators_list = data.get("indicators", {}).get("indicators", [])
    latest_indicator = indicators_list[0] if indicators_list else {}

    # 取最新年度数据
    annual_data = annual.get("annual_data", [])
    latest_annual = annual_data[-1] if annual_data else {}
    prev_annual = annual_data[-2] if len(annual_data) >= 2 else {}

    # 行业对比数据
    industry = data.get("industry", {})
    industry_stats = industry.get("industry_stats", {})
    target_industry = industry.get("target", {})

    # 核心速览
    overview = f"""# {name}（{ts_code}）深度投资分析报告

> **分析日期**：自动生成
> **分析模式**：深度分析（7+1 专家团，{mode_desc}）
> **数据基准日**：{market.get('trade_date', 'N/A')}（行情）| 最新财报：{latest_annual.get('year', 'N/A')}年报
> **行业**：{stock_info.get('industry', 'N/A')}
> **股票代码**：{ts_code}
> **生成方式**：{mode_how}

---

## 核心数据速览

| 指标 | 数值 | 评价 |
|------|------|------|
| 最新股价 | ¥{market.get('close', 'N/A')} | {market.get('trade_date', 'N/A')} 收盘 |
| 总市值 | ¥{market.get('total_mv_yi', 'N/A')}亿 | — |
| PE(TTM) | {market.get('pe_ttm', 'N/A')} | — |
| PB | {market.get('pb', 'N/A')} | — |
| {latest_annual.get('year', 'N/A')}营收 | ¥{latest_annual.get('revenue_yi', 'N/A')}亿 | YoY {((latest_annual.get('revenue_yi', 0) / prev_annual.get('revenue_yi', 1) - 1) * 100):.1f}% |
| {latest_annual.get('year', 'N/A')}净利 | ¥{latest_annual.get('net_profit_yi', 'N/A')}亿 | YoY {((latest_annual.get('net_profit_yi', 0) / prev_annual.get('net_profit_yi', 1) - 1) * 100):.1f}% |
| 5年营收CAGR | {annual.get('revenue_cagr_5y_pct', 'N/A')}% | — |
| 5年净利CAGR | {annual.get('profit_cagr_5y_pct', 'N/A')}% | — |
| 毛利率 | {latest_indicator.get('gross_margin_pct', 'N/A')}% | — |
| 净利率 | {latest_indicator.get('net_margin_pct', 'N/A')}% | — |
| ROE | {latest_indicator.get('roe_pct', 'N/A')}% | — |
| 资产负债率 | {latest_indicator.get('debt_ratio_pct', 'N/A')}% | — |
| 现金 | ¥{balance.get('cash_yi', 'N/A')}亿 | — |
| 有息负债 | ¥{balance.get('interest_debt_yi', 'N/A')}亿 | — |"""

    # 追加行业对比表
    if industry_stats:
        overview += """\n\n### 行业对比（公司值 vs 行业中位数）\n\n| 指标 | 公司值 | 行业中位 | 排名百分位 | 样本数 |\n|------|--------|----------|------------|--------|"""
        for metric, label, unit in [
            ("roe_pct", "ROE", "%"),
            ("gross_margin_pct", "毛利率", "%"),
            ("net_margin_pct", "净利率", "%"),
            ("sell_expense_rate_pct", "销售费用率", "%"),
            ("rd_expense_rate_pct", "研发费用率", "%"),
            ("debt_ratio_pct", "资产负债率", "%"),
            ("pe_ttm", "PE(TTM)", ""),
            ("pb", "PB", ""),
        ]:
            if metric in industry_stats and metric in target_industry:
                stats = industry_stats[metric]
                rank = target_industry.get(f"{metric}_rank_pct")
                rank_str = f"{rank}%" if rank is not None else "N/A"
                overview += (
                    f"\n| {label} | {target_industry.get(metric)}{unit} | "
                    f"{stats.get('median')}{unit} | {rank_str} | {stats.get('count')} |"
                )

    overview += """\n\n**一行总评**：待裁判长填写。\n\n---\n"""

    # 嵌入专家原文
    sections = []
    section_titles = {
        "financial-auditor": "财务排雷 — 财务排雷官评估",
        "value-valuator": "估值安全边际 — 价值估值师评估",
        "growth-assessor": "成长质量 — 成长质量师评估",
        "moat-analyst": "护城河评估 — 护城河分析师评估",
        "cognitive-controller": "认知风控 — 认知风控官评估",
        "macro-cyclist": "宏观周期 — 宏观周期师评估",
        "management-auditor": "管理层评估 — 管理层审计师评估",
    }
    for expert_id in EXPERTS:
        title = section_titles[expert_id]
        sections.append(f"## {title}\n\n{results.get(expert_id, '')}\n")

    def _sub_score(expert_id: str) -> str:
        s = scores[expert_id]
        score_str = s["score"] if s["score"] is not None else "null"
        return f"    {expert_id.replace('-', '_')}: {{ score: {score_str}, verdict: {s['verdict']} }}"

    sub_scores_yaml = "\n".join(_sub_score(e) for e in EXPERTS)
    composite_str = str(round(adjusted)) if complete else "null  # 专家结果不完整，综合分不可计算"
    raw_str = f"{raw:.2f}" if complete else "null"

    # 裁判长裁决模板
    adjudication = f"""---

## 综合裁决 — 裁判长

```yaml
---
adjudicator:
  verdict: [HOLD / PASS / BUY / SELL / OBSERVE]  # 裁判长填写
  composite_score: {composite_str}
  composite_score_raw: {raw_str}
  cognitive_adjustment: {adjustment}
  sub_scores:
{sub_scores_yaml}
  vetoes_triggered: []  # 裁判长填写
  conflicts: []  # 裁判长填写
  position_advice:
    max_allocation_pct: 0
    entry_strategy: 待裁判长填写
    stop_conditions: []
  watch_items: []
---
```

### 裁决理由

（裁判长在此撰写综合裁决：一票否决权检查、框架冲突裁决、评分计算说明、最终结论、主要分歧、观察指标。）

**加权评分计算过程**：

| 专家 | 评分 | 权重 | 贡献 |
|------|:----:|:----:|:----:|
"""
    for expert_id, weight in scoring["weights"].items():
        s = scores[expert_id]['score']
        s_str = s if s is not None else "N/A"
        contrib = f"{s * weight:.2f}" if s is not None else "N/A"
        adjudication += f"| {expert_id} | {s_str} | {weight} | {contrib} |\n"
    if complete:
        adjudication += f"| **原始加权分** | — | — | **{raw:.2f}** |\n"
        adjudication += f"| **认知修正** | {scores['cognitive-controller']['verdict']} | ×{adjustment} | **{adjusted:.2f}** |\n"
    else:
        adjudication += "| **综合分** | — | — | **N/A（专家结果不完整，裁判长须定性说明）** |\n"
    adjudication += """
（裁判长继续补充定性裁决……）

---

## 知识索引

（汇总本次分析引用的 wiki 页面清单。）

---

*报告版本：invest-skill v0.4.0 | 生成时间：自动生成*
"""

    return overview + "\n\n---\n\n".join(sections) + "\n\n" + adjudication


def main() -> int:
    parser = argparse.ArgumentParser(description="组装 invest-skill 最终报告")
    parser.add_argument("ts_code", help="股票代码，如 603605.SH")
    parser.add_argument("--name", help="公司中文名")
    parser.add_argument("--finalize", action="store_true",
                        help="定稿：校验草稿无占位符后更名为正式报告（不重新生成，保留裁判长裁决）")
    parser.add_argument("--allow-missing", action="store_true",
                        help="定稿时允许专家结果缺失（报告中须显式标注缺失专家）")
    parser.add_argument("--degraded", action="store_true",
                        help="标注降级模式（fallback 会话内顺序执行，隔离性受限）")
    args = parser.parse_args()

    ts_code = args.ts_code
    scoring = load_scoring_config()  # SystemExit on failure：wiki 是评分规则唯一来源
    data = load_data_summary(ts_code)
    name = args.name or data.get("stock_info", {}).get("name", ts_code)

    results = load_results(ts_code)
    missing = [k for k, v in results.items() if "结果缺失" in v]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    draft_file = REPORTS_DIR / f"{ts_code}.draft.md"
    final_file = REPORTS_DIR / f"{ts_code}.md"

    if args.finalize:
        # --finalize 不重新生成报告：裁判长完善的是草稿，重新生成会覆盖其裁决。
        # 只做校验 + 落盘，保证「裁判长看过的内容」与「正式报告」逐字一致。
        if not draft_file.exists():
            print("✗ 草稿不存在，无法定稿。先生成草稿并由裁判长完善：", file=sys.stderr)
            print(f"  python3 scripts/assemble_report.py {ts_code} --name <公司名>", file=sys.stderr)
            return 1
        draft = draft_file.read_text(encoding="utf-8")
        placeholders = [p for p in FINALIZE_PLACEHOLDERS if p in draft]
        if placeholders:
            print(f"✗ 草稿仍含占位符 {placeholders}，裁判长尚未完善，拒绝定稿。", file=sys.stderr)
            return 1
        if missing and not args.allow_missing:
            print(f"✗ 专家结果缺失: {missing}。如确认以缺失状态定稿，追加 --allow-missing，"
                  "并在报告中显式标注缺失专家、降低置信度。", file=sys.stderr)
            return 1
        final_file.write_text(draft, encoding="utf-8")
        print(f"✓ 正式报告已生成: {final_file}")
        return 0

    report = build_report(ts_code, name, results, data, scoring, degraded=args.degraded)
    draft_file.write_text(report, encoding="utf-8")
    print(f"报告草稿已生成: {draft_file}")
    if missing:
        print(f"警告：以下专家结果缺失: {missing}")
    raw, adjusted, _, _, _, complete = compute_score(results, scoring)
    if complete:
        print(f"原始加权分: {raw:.2f}")
        print(f"认知修正后: {adjusted:.2f}")
    else:
        print("综合分: N/A（专家结果不完整）")
    print("下一步：裁判长完善草稿（裁决理由、一行总评、知识索引）后定稿：")
    print(f"  python3 scripts/assemble_report.py {ts_code} --name {name} --finalize")
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(main())
