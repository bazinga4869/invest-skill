#!/usr/bin/env python3
"""严格审计 7 位专家的结构化必检项记录。"""
import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from shared.checklist_verify import print_checklist_report, verify_checklist
from shared.contracts import normalize_ts_code


def read_target(report_path: str | None, ts_code: str | None) -> str:
    if report_path:
        path = Path(report_path)
        if not path.exists():
            raise FileNotFoundError(f"报告不存在: {path}")
        return path.read_text(encoding="utf-8")
    if not ts_code:
        raise ValueError("必须提供 report_path 或 --code")
    chunks = []
    for path in sorted(Path("/tmp").glob(f"invest_result_{ts_code}_*.md")):
        chunks.append(path.read_text(encoding="utf-8"))
    if not chunks:
        raise FileNotFoundError(f"没有找到 /tmp/invest_result_{ts_code}_*.md")
    return "\n\n".join(chunks)


def summary(results: dict) -> dict:
    experts = {}
    for expert_id, result in results.items():
        total = result["total"]
        covered = result["covered"]
        pct = round(covered / total * 100, 1) if total else 0.0
        done = sum(
            item.get("found") and item.get("status") == "DONE"
            for item in result.get("items", [])
        )
        valid = pct >= 80 and done >= 1
        experts[expert_id] = {
            "covered": covered,
            "total": total,
            "done": done,
            "coverage_pct": pct,
            "status": "VALID" if valid else ("INCOMPLETE" if pct >= 60 else "INVALID"),
            "missing": [item["item"] for item in result["items"] if not item["found"]],
        }
    minimum = min((item["coverage_pct"] for item in experts.values()), default=0.0)
    all_have_done = all(item["done"] >= 1 for item in experts.values()) if experts else False
    return {
        "experts": experts,
        "minimum_coverage_pct": minimum,
        "status": "PASS" if minimum >= 80 and all_have_done else (
            "INCOMPLETE" if minimum >= 60 else "FAIL"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="严格必检项覆盖率审计")
    parser.add_argument("report_path", nargs="?")
    parser.add_argument("--code", help="审计 /tmp 中该代码的 7 份专家结果")
    parser.add_argument("--expert", help="只显示某位专家（判定仍基于所选专家）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if bool(args.report_path) == bool(args.code):
        parser.error("report_path 与 --code 必须且只能提供一个")
    if args.code:
        try:
            args.code = normalize_ts_code(args.code)
        except ValueError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 2
    try:
        results = verify_checklist(read_target(args.report_path, args.code))
    except (OSError, ValueError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    if args.expert:
        results = {args.expert: results.get(args.expert, {
            "expert_id": args.expert, "items": [], "covered": 0, "total": 0
        })}
    output = summary(results)
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_checklist_report(results)
        print(f"\n门禁判定: {output['status']}（最低覆盖率 {output['minimum_coverage_pct']}%）")
    if output["status"] == "FAIL":
        return 2
    if output["status"] == "INCOMPLETE":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
