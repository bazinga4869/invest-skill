#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收集 7 位专家的结果，统一解析 frontmatter 并校验。

用法：
    python3 scripts/collect_results.py <code>            # JSON 摘要输出到 stdout
    python3 scripts/collect_results.py <code> --json     # 同时写入 /tmp/invest_results_<code>.json
    python3 scripts/collect_results.py <code> --check    # 逐专家校验并打印报告；全部通过 exit 0，否则 exit 1
    python3 scripts/collect_results.py <code> --failing  # 仅打印未通过校验的专家 ID（每行一个）；
                                                         # 全部通过时无输出；exit 0/1 语义同 --check

校验项（--check / --failing）：
    1. 结果文件存在且非空
    2. frontmatter 可解析，expert_id 与文件对应
    3. score 为 0-100 的整数
    4. verdict ∈ {PASS, WARN, VETO}；verdict=VETO 时 veto_triggers 非空
    5. data_date 与 /tmp/invest_data_<code>.json 的 market.trade_date 一致（防陈旧结果污染）
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

EXPERTS = [
    "financial-auditor",
    "value-valuator",
    "growth-assessor",
    "moat-analyst",
    "cognitive-controller",
    "macro-cyclist",
    "management-auditor",
]

VALID_VERDICTS = {"PASS", "WARN", "VETO"}


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

    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass

    clean = re.sub(r'```yaml\s*\n', '', text)
    clean = re.sub(r'\n```\s*\n', '\n', clean)
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', clean, re.DOTALL)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass

    return {}


def result_path(ts_code: str, expert_id: str) -> Path:
    return Path(f"/tmp/invest_result_{ts_code}_{expert_id}.md")


def expected_data_date(ts_code: str) -> str | None:
    """从数据文件读取数据基准日；文件缺失或字段缺失时返回 None。"""
    data_file = Path(f"/tmp/invest_data_{ts_code}.json")
    if not data_file.exists():
        return None
    try:
        d = json.loads(data_file.read_text(encoding="utf-8"))
        v = d.get("market", {}).get("trade_date")
        return str(v) if v else None
    except Exception:
        return None


def validate_expert(ts_code: str, expert_id: str, exp_date: str | None) -> list[str]:
    """返回问题列表；空列表表示校验通过。"""
    problems = []
    path = result_path(ts_code, expert_id)
    if not path.exists():
        return ["结果文件缺失"]
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return ["结果文件为空"]

    fm = parse_frontmatter(text)
    if not fm:
        return ["frontmatter 无法解析（需位于文件最开头，裸 YAML）"]

    if fm.get("expert_id") != expert_id:
        problems.append(f"expert_id 不匹配: {fm.get('expert_id')!r}")

    score = fm.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 100):
        problems.append(f"score 非法: {score!r}（需 0-100 整数）")

    verdict = fm.get("verdict")
    if verdict not in VALID_VERDICTS:
        problems.append(f"verdict 非法: {verdict!r}（需 PASS/WARN/VETO）")
    elif verdict == "VETO" and not fm.get("veto_triggers"):
        problems.append("verdict=VETO 但 veto_triggers 为空")

    if exp_date is None:
        problems.append("数据文件缺失或无 trade_date，无法校验 data_date")
    else:
        got = fm.get("data_date")
        if got is None:
            problems.append("缺少 data_date 字段")
        elif str(got) != exp_date:
            problems.append(f"data_date 陈旧/不一致: 结果={got} 数据={exp_date}")

    return problems


def collect_expert(ts_code: str) -> dict:
    result = {}
    for expert_id in EXPERTS:
        path = result_path(ts_code, expert_id)
        entry = {"file": str(path), "exists": False, "size": 0, "frontmatter": {}, "missing": True}
        if path.exists():
            text = path.read_text(encoding="utf-8")
            entry.update({
                "exists": True,
                "size": len(text),
                "frontmatter": parse_frontmatter(text),
                "missing": not text.strip(),
            })
        result[expert_id] = entry
    return result


def run_check(ts_code: str, quiet_pass: bool = False) -> list[str]:
    """逐专家校验，打印报告（quiet_pass 时只打印失败项），返回未通过的专家列表。"""
    exp_date = expected_data_date(ts_code)
    failing = []
    for expert_id in EXPERTS:
        problems = validate_expert(ts_code, expert_id, exp_date)
        if problems:
            failing.append(expert_id)
            if not quiet_pass:
                print(f"  ✗ {expert_id}")
                for p in problems:
                    print(f"      - {p}")
        elif not quiet_pass:
            print(f"  ✓ {expert_id}")
    return failing


def main() -> int:
    parser = argparse.ArgumentParser(description="收集/校验 invest-skill 专家结果")
    parser.add_argument("ts_code", help="股票代码，如 603605.SH")
    parser.add_argument("--json", action="store_true", help="输出 JSON 到 /tmp/invest_results_<code>.json")
    parser.add_argument("--check", action="store_true", help="校验全部专家结果，exit 0=全部通过")
    parser.add_argument("--failing", action="store_true", help="仅输出未通过校验的专家 ID")
    args = parser.parse_args()

    if args.check or args.failing:
        failing = run_check(args.ts_code, quiet_pass=args.failing)
        if args.failing:
            for expert_id in failing:
                print(expert_id)
        else:
            print(f"\n校验结果：{len(EXPERTS) - len(failing)}/{len(EXPERTS)} 通过")
        return 0 if not failing else 1

    experts = collect_expert(args.ts_code)
    output = {
        "ts_code": args.ts_code,
        "experts": experts,
        "missing_experts": [k for k, v in experts.items() if v["missing"]],
    }

    if args.json:
        out_file = Path(f"/tmp/invest_results_{args.ts_code}.json")
        out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {out_file}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
