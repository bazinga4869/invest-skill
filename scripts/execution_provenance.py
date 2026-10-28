#!/usr/bin/env python3
"""Record reproducible execution metadata for one analysis batch."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from shared.contracts import normalize_ts_code, snapshot_identity
from shared.runtime import RUNTIME_ROOT


def _version(command: str) -> str:
    if command == "host-native":
        return "inherited-from-host"
    try:
        result = subprocess.run(
            [command, "--version"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return (result.stdout or result.stderr).strip().splitlines()[0] if result.returncode == 0 else "unknown"


def record_execution(ts_code: str, phase: str, *, backend: str,
                     host: str = "unknown", model: str = "default",
                     concurrency: int | None = None,
                     timeout_seconds: int | None = None,
                     repair_max_passes: int | None = None,
                     action: str = "BEGIN", status: str = "RECORDED",
                     transaction_id: str | None = None,
                     job_id: str | None = None,
                     content_hash: str | None = None,
                     detail: str | None = None,
                     runtime_root: Path = RUNTIME_ROOT) -> Path:
    code = normalize_ts_code(ts_code)
    data_path = runtime_root / f"invest_data_{code}.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    data_date, batch_id = snapshot_identity(data)
    if not data_date or not batch_id:
        raise ValueError("数据快照身份不完整")
    path = runtime_root / f"invest_execution_{code}.json"
    lock_path = runtime_root / f".invest_execution_{code}.lock"
    meta = data.get("meta", {})
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    cli_version = _version(backend)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if existing and existing.get("batch_id") != batch_id:
            raise ValueError(
                f"执行元数据 batch 冲突: {existing.get('batch_id')} != {batch_id}"
            )
        events = list(existing.get("events") or [])
        event = {
            "seq": len(events) + 1,
            "phase": phase,
            "action": action,
            "status": status,
            "transaction_id": transaction_id,
            "job_id": job_id,
            "content_hash": content_hash,
            "detail": detail,
            "backend": backend,
            "host": host,
            "model": model,
            "recorded_at": now,
            "pid": os.getppid(),
        }
        events.append(event)
        payload = {
            "schema_version": "invest-skill.execution.v2",
            "ts_code": code,
            "data_date": data_date,
            "analysis_date": str(meta.get("analysis_date") or ""),
            "batch_id": batch_id,
            "worker_policy": (
                "host-native-inherit-provider-model-single-prompt-staged-output"
                if backend == "host-native"
                else existing.get("worker_policy")
                or "tools-disabled-fail-closed-stdin-stdout"
            ),
            "report_wiki": {
                "schema_version": meta.get("report_wiki_schema"),
                "evidence_status": meta.get("report_evidence_status"),
                "summary_status": meta.get("report_summary_status"),
                "bundle_hash": meta.get("report_bundle_hash"),
                "corpus_hash": meta.get("report_corpus_hash"),
                "search_content_hash": meta.get("report_search_content_hash"),
            },
            "sage_wiki": meta.get("sage_wiki"),
            "phases": dict(existing.get("phases") or {}),
            "events": events,
        }
        # Compatibility projection for manifest consumers; full history is events[].
        payload["phases"][phase] = {
            "backend": backend,
            "host": host,
            "model": model,
            "cli_version": cli_version,
            "concurrency": concurrency,
            "timeout_seconds": timeout_seconds,
            "repair_max_passes": repair_max_passes,
            "recorded_at": now,
            "pid": os.getppid(),
            "latest_action": action,
            "latest_status": status,
            "transaction_id": transaction_id,
        }
        staged = path.with_name(f".{path.name}.{os.getpid()}.next")
        try:
            with staged.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ts_code")
    parser.add_argument("phase")
    parser.add_argument("--backend", required=True)
    parser.add_argument("--host", default="unknown")
    parser.add_argument("--model", default="default")
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--repair-max-passes", type=int)
    args = parser.parse_args()
    try:
        path = record_execution(
            args.ts_code, args.phase, backend=args.backend, host=args.host,
            model=args.model, concurrency=args.concurrency,
            timeout_seconds=args.timeout, repair_max_passes=args.repair_max_passes,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: 执行元数据记录失败: {exc}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
