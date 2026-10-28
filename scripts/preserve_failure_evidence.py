#!/usr/bin/env python3
"""原子保存认知阶段失败诊断与现场清单，供终止批次复盘。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from scripts.cleanup_intermediates import log_paths, runtime_paths
from scripts.collect_challenges import EXPERTS as CHALLENGE_EXPERTS, validate_challenge
from scripts.collect_cross_reviews import CROSS_REVIEWERS, validate_cross_review
from scripts.collect_results import (
    EXPERTS, expected_batch_id, expected_data_date, load_expert_diagnostics,
    validate_expert,
)
from shared.contracts import normalize_ts_code
from shared.runtime import RUNTIME_ROOT
from shared.project_config import runtime_root as configured_runtime_root


def _expert_failures(code: str) -> dict:
    data_date = expected_data_date(code)
    batch_id = expected_batch_id(code)
    failures = {}
    for expert in EXPERTS:
        problems = validate_expert(code, expert, data_date, batch_id)
        if problems:
            failures[expert] = {
                "problems": problems,
                "diagnostics": load_expert_diagnostics(code, expert),
            }
    return failures


def _challenge_failures(code: str) -> dict:
    return {
        expert: {"problems": problems}
        for expert in CHALLENGE_EXPERTS
        if (problems := validate_challenge(code, expert))
    }


def _cross_failures(code: str) -> dict:
    return {
        reviewer: {"problems": problems}
        for reviewer in CROSS_REVIEWERS
        if (problems := validate_cross_review(code, reviewer))
    }


def preserve_failure_evidence(code: str, phase: str, *,
                              runtime_root: Path = RUNTIME_ROOT,
                              log_root: Path | None = None) -> Path:
    code = normalize_ts_code(code)
    log_root = log_root or Path(
        os.environ.get("INVEST_LOG_DIR", configured_runtime_root() / "logs")
    )
    failure_loaders = {
        "experts": _expert_failures,
        "challenges": _challenge_failures,
        "cross-reviews": _cross_failures,
    }
    data_path = runtime_root / f"invest_data_{code}.json"
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    payload = {
        "ts_code": code,
        "phase": phase,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_date": str(data.get("market", {}).get("trade_date") or ""),
        "analysis_date": str(data.get("meta", {}).get("analysis_date") or ""),
        "batch_id": str(data.get("meta", {}).get("batch_id") or ""),
        "failures": failure_loaders[phase](code),
    }
    destination = runtime_root / f"invest_failure_{code}_{phase}.json"
    # 先写诊断，再列现场；清单包含刚生成的证据文件本身。
    payload["artifacts"] = {
        "runtime": sorted({
            str(destination),
            *(str(path) for path in runtime_paths(code, runtime_root) if path.exists()),
        }),
        "logs": sorted(str(path) for path in log_paths(code, log_root) if path.exists()),
    }
    temp = destination.with_name(f".{destination.name}.{os.getpid()}.next")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="保存 invest-skill 失败现场")
    parser.add_argument("ts_code")
    parser.add_argument("phase", choices=("experts", "challenges", "cross-reviews"))
    args = parser.parse_args()
    try:
        path = preserve_failure_evidence(args.ts_code, args.phase)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: 失败现场保存失败: {exc}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
