#!/usr/bin/env python3
"""集成测试专用 agent：生成能通过生产契约的可验证专家/质询结果。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_report import flatten_paths


def parse_target(path: Path, kind: str) -> tuple[str, str]:
    match = re.fullmatch(
        rf"invest_{kind}_result_(\d{{6}}\.(?:SH|SZ|BJ))_(.+)\.md", path.name,
    )
    if not match:
        raise SystemExit(f"stub: 无法解析输出路径 {path}")
    return match.group(1), match.group(2)


def annual_evidence(code: str) -> tuple[list[str], list[tuple[str, str]]]:
    text = Path(f"/tmp/invest_annual_{code}.txt").read_text(encoding="utf-8")
    locators = []
    quotes = []
    block_pattern = re.compile(
        r"^###\s+(\d{4})年\s+([A-Za-z]+).*?$\n(.*?)(?=^###\s+\d{4}年\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for block in block_pattern.finditer(text):
        year, report_type, body = block.groups()
        for section in re.finditer(
            r"^####\s+(.+?)\s*$\n(.*?)(?=^####\s+|\Z)",
            body, re.MULTILINE | re.DOTALL,
        ):
            section_name, section_text = section.groups()
            locator = f"年报:{year}/{report_type}/{section_name.strip()}"
            locators.append(locator)
            if len(quotes) < 3:
                for snippet in re.findall(r"[\u4e00-\u9fff]{10,28}", section_text):
                    quotes.append((locator, snippet))
                    if len(quotes) >= 3:
                        break
    if len(quotes) < 3:
        raise SystemExit("stub: 年报中找不到 3 个可验证中文引文")
    return locators, quotes


def pick_atom(group: list[str], paths: list[str], locators: list[str]) -> str | None:
    for token in group:
        lower = token.lower()
        if lower == "年报:":
            return locators[0] if locators else None
        for locator in locators:
            if lower in locator.lower():
                return locator
        for path in paths:
            if lower in path.lower() and "." in path:
                return path
    return None


def expert_report(out: Path, code: str, expert: str) -> None:
    if os.environ.get("STUB_FAIL_EXPERT") == expert:
        raise SystemExit(1)
    data = json.loads(Path(f"/tmp/invest_data_{code}.json").read_text(encoding="utf-8"))
    checklist = json.loads((ROOT / "data/expert_checklist.json").read_text(encoding="utf-8"))
    rules = json.loads((ROOT / "data/checklist_evidence_rules.json").read_text(encoding="utf-8"))
    paths = sorted(flatten_paths(data))
    locators, quotes = annual_evidence(code)
    checklist_rows = []
    for item in checklist[expert]["items"]:
        atoms = []
        for group in rules[expert][item]:
            atom = pick_atom(group, paths, locators)
            if not atom:
                raise SystemExit(f"stub: {expert}/{item} 无可用证据组 {group}")
            if atom not in atoms:
                atoms.append(atom)
        evidence = "; ".join(f"`{atom}`" for atom in atoms)
        checklist_rows.append(f"| {item} | DONE | {evidence} | {item}已执行，结论保留数据边界 |")

    annual = data["annual"]["annual_data"]
    latest_index = len(annual) - 1
    latest = annual[latest_index]
    indicator = data["indicators"]["indicators"][0]
    facts = [
        ("股价", data["market"]["close"], "", "market.close"),
        ("总市值", data["market"]["total_mv_yi"], "亿", "market.total_mv_yi"),
        ("PE", data["market"]["pe_ttm"], "", "market.pe_ttm"),
        ("现金", data["balance"]["cash_yi"], "亿", "balance.cash_yi"),
        ("营收", latest["revenue_yi"], "亿", f"annual.annual_data[{latest_index}].revenue_yi"),
        ("净利润", latest["net_profit_yi"], "亿", f"annual.annual_data[{latest_index}].net_profit_yi"),
        ("毛利率", indicator["gross_margin_pct"], "%", "indicators.indicators[0].gross_margin_pct"),
    ]
    fact_rows = "\n".join(
        f"| {label} | {value}{unit} [source: {path}] | 同批次核对 |"
        for label, value, unit, path in facts
    )
    narrative_paths = [facts[4], facts[5], facts[3]]
    narrative_rows = "\n".join(
        f"| {index} | 年报原文“{quote}”（{locator}） | "
        f"{fact[1]}{fact[2]} [source: {fact[3]}] | 只确认原文存在且数据可复核 |"
        for index, ((locator, quote), fact) in enumerate(zip(quotes, narrative_paths), 1)
    )
    text = f"""---
expert_id: "{expert}"
ts_code: "{code}"
score: 80
verdict: PASS
conclusion_direction: NEUTRAL
veto_triggers: []
data_date: "{data['market']['trade_date']}"
analysis_date: "{data['meta']['analysis_date']}"
batch_id: "{data['meta']['batch_id']}"
---
# 集成契约专家评估 — {expert}

## 总体判断

本文只用于验证端到端契约，结论不代表真实投资意见。所有数字都绑定同批次 JSON 路径，定性内容只确认已执行检查，不将未知项目当作零或肯定事实。

## 详细分析

| 指标 | 数值 | 用途 |
|---|---:|---|
{fact_rows}

评估已核对行情、年度利润、现金与盈利能力。对于快照中的空值，只记录缺口及它对结论的限制；对于年报叙事，只做原文定位与相邻 JSON 事实的并列，不把相关性扩写成因果性。这段说明为契约长度和语义完整性提供必要上下文。

## 叙事–数据交叉验证

| # | 管理层论述（年报章节+原文摘录） | 对应财务数据 | 验证结果 |
|---|---|---|---|
{narrative_rows}

## 关键风险与不确定性

- 本文是管线契约测试，不对公司未来业绩做无来源预测。
- 任何快照未披露字段都应继续保持未知，不得从缺失推导出良性结论。

## 必检项执行记录

| 必检项 | 状态 | 证据/来源路径 | 结论 |
|---|---|---|---|
{chr(10).join(checklist_rows)}

## 数据使用说明

数据仅来自同批次快照和归档年报。本测试特意使用不同路径保持证据多样性，并保留不可得项的降级语义。

## 知识检索日志

| # | 页面路径 | 发现方式 | 使用深度 |
|---|---|---|---|
| 1 | 04_stock-analysis-expert/index.md | 索引 | 结构核对 |
| 2 | 04_stock-analysis-expert/experts/01-财务排雷官.md | 索引 | 方法核对 |
| 3 | 04_stock-analysis-expert/experts/02-价值估值师.md | 索引 | 方法核对 |
"""
    out.write_text(text, encoding="utf-8")


def challenge_report(out: Path, code: str, expert: str, prompt: str) -> None:
    original = Path(f"/tmp/invest_result_{code}_{expert}.md").read_text(encoding="utf-8")
    data = json.loads(Path(f"/tmp/invest_data_{code}.json").read_text(encoding="utf-8"))
    questions = re.findall(
        r"^(?:题库问题|动态问题|缺失项/薄弱假设追问)：(.+)$", prompt, re.MULTILINE,
    )
    if len(questions) != 3:
        raise SystemExit("stub: 质询 prompt 不是 3 题")
    prompt_hash_match = re.search(
        r'challenge_prompt_hash:\s*"([0-9a-f]{64})"', prompt,
    )
    if not prompt_hash_match:
        raise SystemExit("stub: 质询 prompt 缺少自身哈希")
    response = (
        "不利情景会先冲击报告中对定量证据的解释边界，因此原结论只能保持而不能加强。"
        "我会把被质询的路径、年报原文和清单缺口分开处理，不用一项证据替代另一项证据。"
        "如果后续可验证数据显示盈利质量、现金流或管理层承诺与原推理反向，就应下调评分并重新判定。"
        "下一个可证伪点是新批次快照与同期年报定位能否同时支持该链条；任一环缺失都保持降级。"
    )
    cjk = len(re.findall(r"[\u4e00-\u9fff]", response))
    if not 150 <= cjk <= 300:
        raise SystemExit(f"stub: 质询回应字数 {cjk}")
    text = f"""---
expert_id: "{expert}"
ts_code: "{code}"
data_date: "{data['market']['trade_date']}"
analysis_date: "{data['meta']['analysis_date']}"
batch_id: "{data['meta']['batch_id']}"
expert_result_hash: "{hashlib.sha256(original.encode('utf-8')).hexdigest()}"
challenge_prompt_hash: "{prompt_hash_match.group(1)}"
challenge_verdict: UNCHANGED
---

# {expert} 魔鬼代言人回应

## 质询问题

1. {questions[0]}
2. {questions[1]}
3. {questions[2]}

## 合并回应（150-300 个中文字符）

{response}
"""
    out.write_text(text, encoding="utf-8")


def cross_report(out: Path, code: str, reviewer: str, prompt: str) -> None:
    def field(pattern: str) -> str:
        match = re.search(pattern, prompt)
        if not match:
            raise SystemExit(f"stub: 交叉盲审 prompt 缺少字段 {pattern}")
        return match.group(1)

    data_date = field(r"data_date=([^;\s]+)")
    analysis_date = field(r"analysis_date=([^;\s]+)")
    batch_id = field(r"batch_id=([^;\s]+)")
    bundle_hash = field(r"input_bundle_hash=([0-9a-f]{64})")
    prompt_hash = field(r'cross_prompt_hash:\s*"([0-9a-f]{64})"')
    paragraph = (
        "盲审将专家结论、质询回应和原始证据分层对照，只标记能从同批次输入复核的遗漏与矛盾。"
        "对数据不可得的项目保持未知，对管理层叙事仅做原文与财务路径的并列，不把相关扩写为因果。"
        "若关键推理在不利情景下失效，应建议裁判长降低确信度，并把下一个可证伪数据写入观察条件。"
    )
    body = paragraph * 5
    text = f"""---
reviewer_id: "{reviewer}"
ts_code: "{code}"
data_date: "{data_date}"
analysis_date: "{analysis_date}"
batch_id: "{batch_id}"
input_bundle_hash: "{bundle_hash}"
cross_prompt_hash: "{prompt_hash}"
cross_verdict: CONFIRM
---
# {reviewer} 交叉盲审

## 遗漏与矛盾

{body}

## 反事实压力测试

{body}

## 对裁判长的影响

{body}
"""
    out.write_text(text, encoding="utf-8")


def main() -> None:
    out = Path(sys.argv[1])
    prompt = sys.stdin.read()
    kind = (
        "challenge" if out.name.startswith("invest_challenge_result_")
        else "cross" if out.name.startswith("invest_cross_result_") else ""
    )
    if kind == "challenge":
        code, expert = parse_target(out, "challenge")
        challenge_report(out, code, expert, prompt)
    elif kind == "cross":
        code, reviewer = parse_target(out, "cross")
        cross_report(out, code, reviewer, prompt)
    else:
        match = re.fullmatch(r"invest_result_(\d{6}\.(?:SH|SZ|BJ))_(.+)\.md", out.name)
        if not match:
            raise SystemExit(f"stub: 无法解析输出路径 {out}")
        expert_report(out, match.group(1), match.group(2))


if __name__ == "__main__":
    main()
