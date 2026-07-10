#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收集 7 位专家 + 3 位评审员的结果，统一解析 frontmatter。

用法：
    python3 scripts/collect_results.py 603605.SH

输出：
    /tmp/invest_results_603605.SH.json
"""
import argparse
import json
import re
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


def parse_frontmatter(text: str) -> dict:
    """解析 frontmatter，兼容裸 YAML 和 ```yaml 包裹两种情况。"""
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


def collect_expert(ts_code: str) -> dict:
    result = {}
    for expert_id in EXPERTS:
        file_path = Path(f"/tmp/invest_result_{ts_code}_{expert_id}.md")
        entry = {"file": str(file_path), "exists": False, "size": 0, "frontmatter": {}, "missing": True}
        if file_path.exists():
            text = file_path.read_text(encoding="utf-8")
            entry.update({
                "exists": True,
                "size": len(text),
                "frontmatter": parse_frontmatter(text),
                "missing": not text.strip(),
            })
        result[expert_id] = entry
    return result


def collect_reviewers(ts_code: str) -> dict:
    result = {}
    for num in [1, 2, 3]:
        file_path = Path(f"/tmp/invest_review_{ts_code}_{num}.md")
        entry = {"file": str(file_path), "exists": False, "size": 0, "missing": True}
        if file_path.exists():
            text = file_path.read_text(encoding="utf-8")
            entry.update({
                "exists": True,
                "size": len(text),
                "missing": not text.strip(),
            })
        result[f"reviewer_{num}"] = entry
    return result


def missing_experts(ts_code: str) -> list:
    data = collect_expert(ts_code)
    return [k for k, v in data.items() if v["missing"]]


def missing_reviewers(ts_code: str) -> list:
    data = collect_reviewers(ts_code)
    return [k for k, v in data.items() if v["missing"]]


def main():
    parser = argparse.ArgumentParser(description="收集 invest-skill 专家/评审员结果")
    parser.add_argument("ts_code", help="股票代码，如 603605.SH")
    parser.add_argument("--json", action="store_true", help="输出 JSON 到文件")
    args = parser.parse_args()

    experts = collect_expert(args.ts_code)
    reviewers = collect_reviewers(args.ts_code)

    output = {
        "ts_code": args.ts_code,
        "experts": experts,
        "reviewers": reviewers,
        "missing_experts": [k for k, v in experts.items() if v["missing"]],
        "missing_reviewers": [k for k, v in reviewers.items() if v["missing"]],
    }

    if args.json:
        out_file = Path(f"/tmp/invest_results_{args.ts_code}.json")
        out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {out_file}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
