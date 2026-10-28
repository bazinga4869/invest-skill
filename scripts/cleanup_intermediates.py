#!/usr/bin/env python3
"""清理单只股票已归档或已终止批次的可再生中间文件。"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from shared.contracts import normalize_ts_code
from shared.project_config import configured_path
from shared.runtime import RUNTIME_ROOT
from shared.project_config import runtime_root


def runtime_paths(ts_code: str, tmp_root: Path = RUNTIME_ROOT) -> set[Path]:
    exact = [
        f"invest_data_{ts_code}.json",
        f"invest_annual_{ts_code}.txt",
        f"invest_report_bundle_{ts_code}.json",
        f"invest_annual_toc_{ts_code}.txt",
        f"invest_results_{ts_code}.json",
        f"invest_level3_{ts_code}.json",
        f"invest_cross_blind_{ts_code}.md",
        f"invest_expert_run_{ts_code}.json",
        f"invest_execution_{ts_code}.json",
        f"invest_adjudication_{ts_code}.json",
        f"invest_retry_evidence_{ts_code}.json",
    ]
    patterns = [
        f"invest_prompt_{ts_code}_*.txt",
        f"invest_native_prompt_{ts_code}_*.txt",
        f"invest_native_original_prompt_{ts_code}_*.txt",
        f"invest_native_decision_baseline_{ts_code}_*.json",
        f"invest_native_repair_{ts_code}_*.txt",
        f"invest_native_archive_{ts_code}_*",
        f"invest_rejected_result_{ts_code}_*",
        f"invest_native_compile_error_{ts_code}_*.json",
        f"invest_result_{ts_code}_*.v3.json",
        f"invest_result_{ts_code}_*.md*",
        f"invest_draft_{ts_code}_*.md",
        f"invest_fix_{ts_code}_*.txt",
        f"invest_fix_errors_{ts_code}*.json",
        f"invest_challenge_prompt_{ts_code}_*.txt",
        f"invest_challenge_result_{ts_code}_*.md*",
        f"invest_cross_prompt_{ts_code}_*.txt",
        f"invest_cross_result_{ts_code}_*.md*",
        f"invest_retry_{ts_code}_*.json",
        f"invest_failure_{ts_code}_*.json",
        f"invest_native_run_{ts_code}*.json",
        f"native-plan-{ts_code.split('.', 1)[0]}.json",
        f".invest_*{ts_code}*.next",
        f".invest_execution_{ts_code}.lock",
    ]
    paths = {tmp_root / name for name in exact}
    for pattern in patterns:
        paths.update(tmp_root.glob(pattern))
    return paths


def log_paths(ts_code: str, log_root: Path) -> set[Path]:
    paths: set[Path] = set()
    for subdir, pattern in (
        ("experts", f"{ts_code}_*.log"),
        ("challenges", f"{ts_code}_*.log"),
        ("cross_reviews", f"{ts_code}_*.log"),
        ("trace", f"{ts_code}_*.jsonl"),
    ):
        paths.update((log_root / subdir).glob(pattern))
    return paths


def cleanup_intermediates(
    ts_code: str,
    *,
    tmp_root: Path = RUNTIME_ROOT,
    log_root: Path | None = None,
    reports_dir: Path | None = None,
    remove_logs: bool = True,
    remove_draft: bool = True,
) -> dict:
    code = normalize_ts_code(ts_code)
    log_root = log_root or Path(os.environ.get("INVEST_LOG_DIR", runtime_root() / "logs"))
    reports_dir = reports_dir or Path(os.environ.get(
        "INVEST_REPORTS_DIR", configured_path("invest_tool_dir", "./reports/invest_tool")
    ))
    candidates = runtime_paths(code, tmp_root)
    if remove_logs:
        candidates.update(log_paths(code, log_root))
    if remove_draft:
        candidates.add(reports_dir / f"{code}.draft.md")

    removed: list[str] = []
    errors: list[str] = []
    for path in sorted(candidates, key=lambda item: str(item)):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
                removed.append(str(path))
            elif path.is_dir():
                shutil.rmtree(path)
                removed.append(str(path))
        except OSError as exc:
            errors.append(f"{path}: {exc}")

    remaining = [
        str(path) for path in sorted(runtime_paths(code, tmp_root), key=lambda item: str(item))
        if path.exists()
    ]
    if remove_logs:
        remaining.extend(
            str(path) for path in sorted(log_paths(code, log_root), key=lambda item: str(item))
            if path.exists()
        )
    if remove_draft and (reports_dir / f"{code}.draft.md").exists():
        remaining.append(str(reports_dir / f"{code}.draft.md"))
    result = {"ts_code": code, "removed": removed, "errors": errors, "remaining": remaining}
    if not errors and not remaining:
        published = sorted(
            path.parent
            for path in (reports_dir / "artifacts" / code).glob("*/.published.json")
            if path.is_file()
        )
        if published:
            receipt = published[-1] / ".cleanup.json"
            staged = receipt.with_name(f".{receipt.name}.{os.getpid()}.next")
            payload = {
                "schema_version": "invest-skill.cleanup-receipt.v1",
                "ts_code": code,
                "removed_count": len(removed),
                "remaining": [],
                "completed_at": datetime.now().astimezone().isoformat(),
            }
            try:
                with staged.open("x", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(staged, receipt)
                result["receipt"] = str(receipt)
            finally:
                staged.unlink(missing_ok=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 invest-skill 单批次中间文件")
    parser.add_argument("ts_code")
    parser.add_argument("--keep-logs", action="store_true")
    parser.add_argument("--keep-draft", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = cleanup_intermediates(
            args.ts_code,
            remove_logs=not args.keep_logs,
            remove_draft=not args.keep_draft,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["errors"] or result["remaining"]:
        print(
            f"✗ 中间文件清理不完整: errors={result['errors']}, "
            f"remaining={result['remaining']}", file=sys.stderr,
        )
    else:
        print(f"✓ 已清理 {len(result['removed'])} 个 {result['ts_code']} 中间文件")
    return 0 if not result["errors"] and not result["remaining"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
