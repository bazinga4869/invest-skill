#!/usr/bin/env python3
"""Explicit independent research sign-off (declared identity, not authentication)."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.contracts import normalize_ts_code
from shared.project_config import configured_path
from shared.runtime import RUNTIME_ROOT
from shared.research_review import SCHEMA, adjudicator_identity, validate_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ts_code")
    parser.add_argument("--reviewer-identity", required=True)
    parser.add_argument("--orchestrator-identity", required=True)
    parser.add_argument("--verdict", required=True, choices=["PASS"])
    parser.add_argument("--statement", required=True, help="Independent research review findings/acceptance")
    args = parser.parse_args()
    try:
        code = normalize_ts_code(args.ts_code)
        reports = Path(os.environ["INVEST_REPORTS_DIR"]) if os.environ.get("INVEST_REPORTS_DIR") else configured_path("invest_tool_dir", "./reports/invest_tool")
        draft = (reports / f"{code}.draft.md").read_bytes()
        data = json.loads((RUNTIME_ROOT / f"invest_data_{code}.json").read_text())
        execution = json.loads((RUNTIME_ROOT / f"invest_execution_{code}.json").read_text())
        batch = data["meta"]["batch_id"]
        receipt = {
            "schema_version": SCHEMA, "ts_code": code, "batch_id": batch,
            "draft_sha256": hashlib.sha256(draft).hexdigest(),
            "reviewer_identity": args.reviewer_identity,
            "orchestrator_identity": args.orchestrator_identity,
            "adjudicator_identity": adjudicator_identity(draft.decode("utf-8")),
            "verdict": args.verdict, "statement": args.statement,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "identity_assurance": "declared-identities-not-cryptographic-authentication",
        }
        errors = validate_review(receipt, ts_code=code, batch_id=batch, draft=draft, execution=execution)
        if errors:
            raise ValueError("; ".join(errors))
        target = RUNTIME_ROOT / f"invest_research_review_{code}.json"
        staged = target.with_name(f".{target.name}.{os.getpid()}.next")
        with staged.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, target)
        print(target)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"独立投研复核签收失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
