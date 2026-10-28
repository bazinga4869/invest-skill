#!/usr/bin/env python3
"""投资分析运行互斥与单次重试门禁。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from shared.contracts import normalize_ts_code, snapshot_identity
from shared.runtime import RUNTIME_ROOT

TMP_ROOT = RUNTIME_ROOT
VALID_OWNERS = {
    "prepare", "native", "shell", "challenges", "cross-reviews", "finalize",
}
VALID_PHASES = {"experts", "challenges", "cross-reviews"}


class GuardError(RuntimeError):
    pass


def run_state_path(ts_code: str, tmp_root: Path = TMP_ROOT) -> Path:
    return tmp_root / f"invest_expert_run_{ts_code}.json"


def retry_state_path(ts_code: str, phase: str, batch_id: str,
                     tmp_root: Path = TMP_ROOT) -> Path:
    return tmp_root / f"invest_retry_{ts_code}_{phase}_{batch_id}.json"


def retry_started_path(ts_code: str, phase: str, batch_id: str,
                       tmp_root: Path = TMP_ROOT) -> Path:
    return tmp_root / f"invest_retry_{ts_code}_{phase}_{batch_id}.started.json"


def current_batch_id(ts_code: str, tmp_root: Path = TMP_ROOT) -> str:
    data_path = tmp_root / f"invest_data_{ts_code}.json"
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
        _, batch_id = snapshot_identity(data)
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"无法读取同批次数据快照: {data_path}: {exc}") from exc
    if not batch_id:
        raise GuardError(f"数据快照缺少 batch_id: {data_path}")
    return batch_id


def read_run_state(ts_code: str, tmp_root: Path = TMP_ROOT) -> dict | None:
    path = run_state_path(ts_code, tmp_root)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"运行互斥文件损坏，拒绝猜测并发状态: {path}: {exc}") from exc
    return state


def _atomic_create(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise GuardError(f"门禁文件已存在: {path}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _read_json_state(path: Path, label: str) -> dict | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"{label}损坏，拒绝猜测状态: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardError(f"{label}不是 JSON 对象: {path}")
    return value


def _atomic_replace(path: Path, payload: dict) -> None:
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


def claim_run(ts_code: str, owner: str, tmp_root: Path = TMP_ROOT) -> dict:
    if owner not in VALID_OWNERS:
        raise GuardError(f"owner 只支持: {sorted(VALID_OWNERS)}")
    batch_id = "PENDING" if owner == "prepare" else current_batch_id(ts_code, tmp_root)
    existing = read_run_state(ts_code, tmp_root)
    if existing:
        raise GuardError(
            "分析管线已有运行占用，禁止启动第二个写入阶段: "
            f"owner={existing.get('owner')}, batch_id={existing.get('batch_id')}"
        )
    payload = {
        "ts_code": ts_code,
        "batch_id": batch_id,
        "owner": owner,
        "token": secrets.token_hex(16),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pid": os.getppid(),
    }
    _atomic_create(run_state_path(ts_code, tmp_root), payload)
    return payload


def release_run(ts_code: str, owner: str, tmp_root: Path = TMP_ROOT,
                token: str | None = None) -> None:
    state = read_run_state(ts_code, tmp_root)
    if state is None:
        return
    if state.get("owner") != owner:
        raise GuardError(
            f"运行占用属于 {state.get('owner')}，{owner} 无权释放"
        )
    if token is not None and state.get("token") != token:
        raise GuardError("运行占用 token 不匹配，无权释放")
    run_state_path(ts_code, tmp_root).unlink(missing_ok=True)


def assert_idle(ts_code: str, tmp_root: Path = TMP_ROOT,
                owner: str | None = None) -> None:
    state = read_run_state(ts_code, tmp_root)
    if state and state.get("owner") != owner:
        raise GuardError(
            "分析管线仍在运行，禁止重建 prompt 或切换执行阶段: "
            f"owner={state.get('owner')}, batch_id={state.get('batch_id')}。"
            "确认当前写入阶段的所有进程已结束后执行 release-run。"
        )


def claim_retry(ts_code: str, phase: str, tmp_root: Path = TMP_ROOT) -> dict:
    """幂等预留重试；不会消耗唯一一次实际执行机会。"""
    if phase not in VALID_PHASES:
        raise GuardError(f"phase 只支持: {sorted(VALID_PHASES)}")
    batch_id = current_batch_id(ts_code, tmp_root)
    path = retry_state_path(ts_code, phase, batch_id, tmp_root)
    started_path = retry_started_path(ts_code, phase, batch_id, tmp_root)
    if started_path.exists():
        raise GuardError(f"本批次 {phase} 已开始过唯一一次重试，禁止再次预留")
    existing = _read_json_state(path, "重试预留文件")
    if existing is not None:
        if existing.get("status") == "reserved":
            return existing
        if "status" not in existing and "used_at" in existing:
            raise GuardError(
                f"本批次 {phase} 使用旧版重试标记；先执行 recover-retry 完成一次性迁移"
            )
        raise GuardError(f"本批次 {phase} 重试状态非法: {existing.get('status')}")
    payload = {
        "ts_code": ts_code,
        "batch_id": batch_id,
        "phase": phase,
        "status": "reserved",
        "reserved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _atomic_create(path, payload)
    return payload


def begin_retry(ts_code: str, phase: str, tmp_root: Path = TMP_ROOT) -> dict:
    """原子消费一次重试预留；实际执行入口只能成功一次。"""
    reservation = claim_retry(ts_code, phase, tmp_root)
    batch_id = str(reservation["batch_id"])
    payload = {
        "ts_code": ts_code,
        "batch_id": batch_id,
        "phase": phase,
        "status": "started",
        "reserved_at": reservation.get("reserved_at"),
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pid": os.getppid(),
    }
    path = retry_started_path(ts_code, phase, batch_id, tmp_root)
    try:
        _atomic_create(path, payload)
    except GuardError as exc:
        raise GuardError(
            f"本批次 {phase} 已开始过唯一一次重试，禁止再次执行"
        ) from exc
    return payload


def recover_retry(ts_code: str, phase: str, tmp_root: Path = TMP_ROOT) -> dict:
    """把已确认未实际启动的旧版 used_at 标记迁移为预留状态。"""
    if phase not in VALID_PHASES:
        raise GuardError(f"phase 只支持: {sorted(VALID_PHASES)}")
    batch_id = current_batch_id(ts_code, tmp_root)
    path = retry_state_path(ts_code, phase, batch_id, tmp_root)
    started_path = retry_started_path(ts_code, phase, batch_id, tmp_root)
    if started_path.exists():
        raise GuardError(f"本批次 {phase} 已有实际重试启动标记，禁止恢复")
    existing = _read_json_state(path, "旧版重试文件")
    if existing is None or "used_at" not in existing or "status" in existing:
        raise GuardError("仅支持迁移尚无 status 且包含 used_at 的旧版重试标记")
    payload = {
        "ts_code": ts_code,
        "batch_id": batch_id,
        "phase": phase,
        "status": "reserved",
        "reserved_at": existing["used_at"],
        "recovered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "recovered_from": "legacy-used-at",
    }
    _atomic_replace(path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="invest-skill 运行互斥与重试门禁")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("claim-run", "release-run"):
        item = sub.add_parser(command)
        item.add_argument("ts_code")
        item.add_argument("owner", choices=sorted(VALID_OWNERS))
        if command == "release-run":
            item.add_argument("--token")
    idle = sub.add_parser("assert-idle")
    idle.add_argument("ts_code")
    for command in ("claim-retry", "begin-retry", "recover-retry"):
        retry = sub.add_parser(command)
        retry.add_argument("ts_code")
        retry.add_argument("phase", choices=sorted(VALID_PHASES))
    status = sub.add_parser("status")
    status.add_argument("ts_code")
    args = parser.parse_args()

    try:
        code = normalize_ts_code(args.ts_code)
        if args.command == "claim-run":
            result = claim_run(code, args.owner)
        elif args.command == "release-run":
            release_run(code, args.owner, token=args.token)
            result = {"released": True, "ts_code": code, "owner": args.owner}
        elif args.command == "assert-idle":
            assert_idle(code)
            result = {"idle": True, "ts_code": code}
        elif args.command == "claim-retry":
            result = claim_retry(code, args.phase)
        elif args.command == "begin-retry":
            result = begin_retry(code, args.phase)
        elif args.command == "recover-retry":
            result = recover_retry(code, args.phase)
        else:
            result = read_run_state(code) or {"idle": True, "ts_code": code}
    except (ValueError, GuardError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
