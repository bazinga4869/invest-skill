#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组装 invest-skill 最终报告。

用法：
    python3 scripts/assemble_report.py 603605.SH --name 珀莱雅

输出：
    reports/invest_tool/603605.SH.md
"""
import argparse
import json
from pathlib import Path
import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = SKILL_ROOT / "reports" / "invest_tool"
EXPERTS = [
    "financial-auditor",
    "value-valuator",
    "growth-assessor",
    "moat-analyst",
    "cognitive-controller",
    "macro-cyclist",
    "management-auditor",
]

# wiki 定义的权重
WEIGHTS = {
    "financial-auditor": 0.25,
    "value-valuator": 0.25,
    "moat-analyst": 0.20,
    "growth-assessor": 0.10,
    "management-auditor": 0.10,
    "macro-cyclist": 0.05,
}


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
    import re
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


def compute_score(results: dict) -> tuple:
    """返回 (raw_score, adjusted_score, details)"""
    scores = {}
    for expert_id in EXPERTS:
        text = results.get(expert_id, "")
        fm = parse_frontmatter(text)
        scores[expert_id] = {
            "score": fm.get("score", 0),
            "verdict": fm.get("verdict", "UNKNOWN"),
            "veto_triggers": fm.get("veto_triggers", []),
        }

    raw = 0.0
    details = []
    for expert_id, weight in WEIGHTS.items():
        s = scores[expert_id]["score"]
        contrib = s * weight
        raw += contrib
        details.append(f"{expert_id}: {s} × {weight} = {contrib:.2f}")

    cognitive_verdict = scores.get("cognitive-controller", {}).get("verdict", "PASS")
    adjustment = 1.0
    if cognitive_verdict == "VETO":
        adjustment = 0.7
    elif cognitive_verdict == "WARN":
        adjustment = 0.85

    adjusted = raw * adjustment
    return raw, adjusted, scores, details, adjustment


def load_data_summary(ts_code: str) -> dict:
    data_file = Path(f"/tmp/invest_data_{ts_code}.json")
    if not data_file.exists():
        return {}
    try:
        return json.loads(data_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_report(ts_code: str, name: str, results: dict, data: dict) -> str:
    raw, adjusted, scores, details, adjustment = compute_score(results)

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

    def _industry_line(metric: str, label: str, unit: str = ""):
        if metric not in industry_stats or metric not in target_industry:
            return ""
        stats = industry_stats[metric]
        rank = target_industry.get(f"{metric}_rank_pct")
        return (
            f"| {label} | {target_industry.get(metric, 'N/A')}{unit} "
            f"(行业中位 {stats.get('median')}{unit}, 排名 {rank}%  if rank is not None else 'N/A') | — |\n"
        )

    # 核心速览
    overview = f"""# {name}（{ts_code}）深度投资分析报告

> **分析日期**：自动生成
> **分析模式**：深度分析（7+1 专家团，角色切换模式）
> **数据基准日**：{market.get('trade_date', 'N/A')}（行情）| 最新财报：{latest_annual.get('year', 'N/A')}年报
> **行业**：{stock_info.get('industry', 'N/A')}
> **股票代码**：{ts_code}
> **生成方式**：按 SKILL.md 协议角色切换执行 7 域分析 + 裁判长综合裁决

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

    # 裁判长裁决模板
    adjudication = f"""---

## 综合裁决 — 裁判长

```yaml
---
adjudicator:
  verdict: [HOLD / PASS / BUY / SELL / OBSERVE]  # 裁判长填写
  composite_score: {round(adjusted)}
  composite_score_raw: {raw:.2f}
  cognitive_adjustment: {adjustment}
  sub_scores:
    financial_auditor: {{ score: {scores['financial-auditor']['score']}, verdict: {scores['financial-auditor']['verdict']} }}
    value_valuator: {{ score: {scores['value-valuator']['score']}, verdict: {scores['value-valuator']['verdict']} }}
    growth_assessor: {{ score: {scores['growth-assessor']['score']}, verdict: {scores['growth-assessor']['verdict']} }}
    moat_analyst: {{ score: {scores['moat-analyst']['score']}, verdict: {scores['moat-analyst']['verdict']} }}
    cognitive_controller: {{ score: {scores['cognitive-controller']['score']}, verdict: {scores['cognitive-controller']['verdict']} }}
    macro_cyclist: {{ score: {scores['macro-cyclist']['score']}, verdict: {scores['macro-cyclist']['verdict']} }}
    management_auditor: {{ score: {scores['management-auditor']['score']}, verdict: {scores['management-auditor']['verdict']} }}
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
    for expert_id, weight in WEIGHTS.items():
        s = scores[expert_id]['score']
        adjudication += f"| {expert_id} | {s} | {weight} | {s * weight:.2f} |\n"
    adjudication += f"| **原始加权分** | — | — | **{raw:.2f}** |\n"
    adjudication += f"| **认知修正** | {scores['cognitive-controller']['verdict']} | ×{adjustment} | **{adjusted:.2f}** |\n"
    adjudication += """
（裁判长继续补充定性裁决……）

---

## 知识索引

（汇总本次分析引用的 wiki 页面清单。）

---

*报告版本：invest-skill v0.2.0 | 生成时间：自动生成*
"""

    return overview + "\n\n---\n\n".join(sections) + "\n\n" + adjudication


def main():
    parser = argparse.ArgumentParser(description="组装 invest-skill 最终报告")
    parser.add_argument("ts_code", help="股票代码，如 603605.SH")
    parser.add_argument("--name", help="公司中文名")
    parser.add_argument("--finalize", action="store_true", help="生成正式报告并覆盖 .md；否则生成 .draft.md")
    args = parser.parse_args()

    ts_code = args.ts_code
    data = load_data_summary(ts_code)
    name = args.name or data.get("stock_info", {}).get("name", ts_code)

    results = load_results(ts_code)
    missing = [k for k, v in results.items() if "结果缺失" in v]
    if missing:
        print(f"警告：以下专家结果缺失: {missing}")

    report = build_report(ts_code, name, results, data)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.finalize:
        report_file = REPORTS_DIR / f"{ts_code}.md"
    else:
        report_file = REPORTS_DIR / f"{ts_code}.draft.md"
    report_file.write_text(report, encoding="utf-8")
    print(f"报告草稿已生成: {report_file}")
    print(f"原始加权分: {compute_score(results)[0]:.2f}")
    print(f"认知修正后: {compute_score(results)[1]:.2f}")


if __name__ == "__main__":
    main()
