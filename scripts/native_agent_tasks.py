#!/usr/bin/env python3
"""Host-native subagent orchestration contract for cognitive pipeline stages.

This module never selects or starts a model provider.  It prepares bounded jobs
for the *current host agent* to delegate through its native child-agent tool, so
provider/model selection remains owned by that host and is inherited naturally.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from scripts.execution_provenance import record_execution
from scripts.runtime_guard import (
    GuardError,
    begin_retry,
    claim_retry,
    claim_run,
    current_batch_id,
    release_run,
)
from shared.batch_contract import prompt_contract_hash
from shared.contracts import batch_contract_paths, normalize_ts_code
from shared.runtime import RUNTIME_ROOT

PHASES = ("experts", "challenges", "cross-reviews")
PLAN_SCHEMA = "invest-skill.native-agent-plan.v1"
MAX_EXPERT_REPAIR_PASSES = 3
MAX_TASK_PROMPT_BYTES = 256 * 1024
MAX_ESTIMATED_PROMPT_TOKENS = 80_000
UNRESOLVED_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{[A-Za-z_][A-Za-z0-9_]*\}(?!\})")


class NativeTaskError(RuntimeError):
    pass


def _run(args: list[str], *, allow_one: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
    )
    allowed = {0, 1} if allow_one else {0}
    if result.returncode not in allowed:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise NativeTaskError(f"命令失败 exit={result.returncode}: {' '.join(args)}: {detail}")
    return result


def _atomic_json(path: Path, payload: dict) -> None:
    staged = path.with_name(f".{path.name}.{os.getpid()}.next")
    try:
        with staged.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _atomic_text(path: Path, content: str) -> None:
    staged = path.with_name(f".{path.name}.{os.getpid()}.next")
    try:
        with staged.open("x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _plan_path(code: str) -> Path:
    return RUNTIME_ROOT / f"invest_native_run_{code}.json"


def _load_plan(code: str) -> dict:
    path = _plan_path(code)
    if not path.is_file():
        raise NativeTaskError(f"没有活动的 host-native 计划: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeTaskError(f"host-native 计划损坏: {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != PLAN_SCHEMA:
        raise NativeTaskError(f"host-native 计划 schema 非法: {path}")
    return value


def _assert_contract_frozen(code: str) -> None:
    data_path = RUNTIME_ROOT / f"invest_data_{code}.json"
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeTaskError(f"无法读取批次快照，不能验证控制面冻结: {exc}") from exc
    declared = str(data.get("meta", {}).get("prompt_contract_hash") or "")
    current = prompt_contract_hash(batch_contract_paths(SKILL_ROOT))
    if not declared or declared != current:
        raise NativeTaskError(
            "活动批次控制面已变化，必须终止旧批次并重新 prepare: "
            f"snapshot={declared!r}, current={current!r}"
        )


def _expert_ids() -> list[str]:
    value = json.loads((SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8"))
    return [str(item["id"]) for item in value["experts"]]


def _reviewer_ids() -> list[str]:
    from scripts.collect_cross_reviews import CROSS_REVIEWERS
    return list(CROSS_REVIEWERS)


def _ids_for_phase(phase: str) -> list[str]:
    return _reviewer_ids() if phase == "cross-reviews" else _expert_ids()


def _prompt_path(code: str, phase: str, worker_id: str) -> Path:
    if phase == "experts":
        return RUNTIME_ROOT / f"invest_native_prompt_{code}_{worker_id}.txt"
    if phase == "challenges":
        return RUNTIME_ROOT / f"invest_challenge_prompt_{code}_{worker_id}.txt"
    return RUNTIME_ROOT / f"invest_cross_prompt_{code}_{worker_id}.txt"


def _original_prompt_path(code: str, phase: str, worker_id: str) -> Path:
    return RUNTIME_ROOT / f"invest_native_original_prompt_{code}_{phase}_{worker_id}.txt"


def _decision_baseline_path(code: str, expert_id: str) -> Path:
    return RUNTIME_ROOT / f"invest_native_decision_baseline_{code}_{expert_id}.json"


def _evidence_dir(plan: dict) -> Path:
    return RUNTIME_ROOT / (
        f"invest_native_archive_{plan['ts_code']}_{plan['phase']}_"
        f"{plan['batch_id']}_{plan['transaction_id']}"
    )


def _archive_evidence(plan: dict, label: str) -> None:
    """Snapshot orchestration evidence before it can be cleaned or overwritten."""
    root = _evidence_dir(plan)
    root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    plan_copy = root / f"plan_{label}_{stamp}.json"
    _atomic_json(plan_copy, plan)
    patterns = (
        f"invest_native_original_prompt_{plan['ts_code']}_*.txt",
        f"invest_native_decision_baseline_{plan['ts_code']}_*.json",
        f"invest_native_repair_{plan['ts_code']}_*.txt",
        f"invest_rejected_result_{plan['ts_code']}_*",
        f"invest_native_compile_error_{plan['ts_code']}_*.json",
        f"invest_failure_{plan['ts_code']}_*.json",
    )
    for pattern in patterns:
        for source in RUNTIME_ROOT.glob(pattern):
            if not source.is_file() or source.is_symlink():
                continue
            target = root / f"{stamp}_{source.name}"
            shutil.copy2(source, target)


def _result_path(code: str, phase: str, worker_id: str) -> Path:
    if phase == "experts":
        return RUNTIME_ROOT / f"invest_result_{code}_{worker_id}.md"
    if phase == "challenges":
        return RUNTIME_ROOT / f"invest_challenge_result_{code}_{worker_id}.md"
    return RUNTIME_ROOT / f"invest_cross_result_{code}_{worker_id}.md"


def _failing_ids(code: str, phase: str) -> list[str]:
    if phase == "experts":
        command = [sys.executable, "scripts/collect_results.py", code, "--failing"]
    elif phase == "challenges":
        command = [sys.executable, "scripts/collect_challenges.py", code, "--failing"]
    else:
        command = [sys.executable, "scripts/collect_cross_reviews.py", code, "--failing"]
    result = _run(command, allow_one=True)
    valid = set(_ids_for_phase(phase))
    return [line.strip() for line in result.stdout.splitlines() if line.strip() in valid]


def _validate_phase(code: str, phase: str) -> tuple[bool, str]:
    if phase == "experts":
        command = [sys.executable, "scripts/collect_results.py", code, "--check"]
    elif phase == "challenges":
        command = [sys.executable, "scripts/collect_challenges.py", code]
    else:
        command = [sys.executable, "scripts/collect_cross_reviews.py", code]
    result = subprocess.run(
        command, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()[-4000:]


def _prepare_phase(code: str, phase: str, retry: bool) -> list[str]:
    if phase == "experts":
        _run([sys.executable, "scripts/validate_prompt_bundle.py", code])
        for worker_id in _expert_ids():
            _run([
                sys.executable, "scripts/expert_result_v3.py", "prepare",
                code, worker_id,
            ])
    elif phase == "challenges":
        ok, detail = _validate_phase(code, "experts")
        if not ok:
            raise NativeTaskError(f"七专家结果未通过，禁止质询: {detail}")
        if not retry:
            _run([sys.executable, "scripts/prepare_challenges.py", code])
    else:
        if not retry:
            _run([sys.executable, "scripts/prepare_cross_reviews.py", code])

    ids = _failing_ids(code, phase) if retry else _ids_for_phase(phase)
    if retry and not ids:
        return []
    if not retry:
        existing = [_result_path(code, phase, item) for item in ids]
        collided = [str(path) for path in existing if path.exists()]
        if collided:
            raise NativeTaskError(
                "fresh 运行拒绝覆盖既有结果；请校验现有结果、使用 --retry 或重建批次: "
                + ", ".join(collided[:3])
            )
    for worker_id in ids:
        prompt = _prompt_path(code, phase, worker_id)
        if not prompt.is_file() or prompt.stat().st_size == 0:
            raise NativeTaskError(f"任务书缺失或为空: {prompt}")
    return ids


def _expert_diagnostics(code: str, expert_id: str) -> dict:
    result = subprocess.run(
        [sys.executable, "scripts/collect_results.py", code, "--expert", expert_id,
         "--failing", "--json"],
        cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        value = {}
    item = value.get(expert_id, {}) if isinstance(value, dict) else {}
    return item if isinstance(item, dict) else {}


def _repair_prompt(code: str, expert_id: str, pass_number: int) -> Path:
    original = _original_prompt_path(code, "experts", expert_id)
    base = (original if original.is_file() else _prompt_path(code, "experts", expert_id)).read_text(encoding="utf-8")
    result_path = RUNTIME_ROOT / f"invest_result_{code}_{expert_id}.v3.json"
    rejected_path = RUNTIME_ROOT / f"invest_rejected_result_{code}_{expert_id}.v3.json"
    if result_path.is_file():
        latest = result_path.read_text(encoding="utf-8")
    elif rejected_path.is_file():
        latest = rejected_path.read_text(encoding="utf-8")
    else:
        latest = "（没有可读取的上轮 v3 JSON）"
    diagnostics = _expert_diagnostics(code, expert_id)
    error_path = RUNTIME_ROOT / f"invest_native_compile_error_{code}_{expert_id}.json"
    if error_path.is_file():
        try:
            diagnostics["v3_compile"] = json.loads(error_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            diagnostics["v3_compile"] = {"error": "编译错误记录无法解析"}
    baseline_path = _freeze_decision_baseline(code, expert_id)
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_kind = baseline_payload.get("frozen_kind")
    baseline = baseline_payload.get("decision")
    if isinstance(baseline, dict):
        decision_rule = (
            "下方 immutable decision 必须逐字段原样复制，"
            "任何 score/verdict/direction/veto 变化都会硬失败。"
        )
        decision_block = (
            "## Immutable decision（机器冻结，不得改写）\n\n```json\n"
            + json.dumps(baseline, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n```"
        )
    else:
        decision_rule = (
            "首次独立产出没有可冻结的 decision（不可解析或结构不完整），本 pass 不设 immutable decision："
            "请按你所在专家页的方法论与检查清单**独立**给出完整 decision；该 decision 一经 commit 即成为本批次基线，"
            "不得为迎合门禁而降低证据标准、删减证据或改写结论方向。"
        )
        decision_block = (
            "## Immutable decision\n\n"
            f"（无：首次独立产出没有可冻结的 decision，frozen_kind={baseline_kind}。）"
        )
    path = RUNTIME_ROOT / f"invest_native_repair_{code}_{expert_id}_pass{pass_number}.txt"
    text = f"""⬛⬛⬛ Host-native 有界修复 {pass_number}/{MAX_EXPERT_REPAIR_PASSES} ⬛⬛⬛

你必须输出一份完整 ExpertResult v3 JSON，不得只解释错误或只返回局部 patch。
严格处理 diagnostics 中每一类别和条目；继续遵守原始 v3 任务书，只通过 F/C/M/A token
表达数字事实，不得手写 Markdown frontmatter、[source:] 或 [calc:]。
只修改 diagnostics 明确涉及的 prose/trace 字段；其余字段沿用“最新未通过结果”。不得删除、合并或缩短原有 analysis_sections、risks、narrative_checks、checklist_conclusions；完整输出仍须至少五个 analysis_sections、三条 risks 和全部 checklist 键。修复 C token 时，竖线左侧只保留纯算术表达式（如 `1/pe` 或 `a/b`），不得写 `name=表达式`，乘法只用 ASCII `*`。
下方 immutable decision 规则：{decision_rule}

{decision_block}

## 完整 diagnostics

```json
{json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True)}
```

## 最新未通过结果

{latest}

## 原始任务书

{base}
"""
    path.write_text(text, encoding="utf-8")
    return path


def _review_repair_prompt(code: str, phase: str, worker_id: str,
                          pass_number: int) -> Path:
    result_path = _result_path(code, phase, worker_id)
    rejected_path = RUNTIME_ROOT / f"invest_rejected_result_{code}_{phase}_{worker_id}.md"
    if result_path.is_file():
        latest = result_path.read_text(encoding="utf-8")
    elif rejected_path.is_file():
        latest = rejected_path.read_text(encoding="utf-8")
    else:
        latest = "（无上轮结果）"
    if phase == "challenges":
        from scripts.collect_challenges import validate_challenge
        diagnostics = validate_challenge(code, worker_id)
    elif phase == "cross-reviews":
        from scripts.collect_cross_reviews import validate_cross_review
        diagnostics = validate_cross_review(code, worker_id)
    else:
        raise NativeTaskError(f"不支持 review repair: {phase}")
    error_path = RUNTIME_ROOT / f"invest_native_compile_error_{code}_{phase}_{worker_id}.json"
    if error_path.is_file():
        try:
            compile_error = json.loads(error_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            compile_error = {"error": "规范化错误记录无法解析"}
        diagnostics = {"validation": diagnostics, "normalization": compile_error}
    original_path = _original_prompt_path(code, phase, worker_id)
    if not original_path.is_file():
        raise NativeTaskError(f"官方原始任务书缺失，拒绝生成 repair prompt: {original_path}")
    original = original_path.read_text(encoding="utf-8")
    path = RUNTIME_ROOT / (
        f"invest_native_repair_{code}_{phase}_{worker_id}_pass{pass_number}.txt"
    )
    text = f"""⬛⬛⬛ Host-native {phase} 定向修复 pass {pass_number} ⬛⬛⬛

你必须输出完整最终文档，不得只解释或返回局部 patch。逐条修复 diagnostics；
所有身份、输入哈希、prompt 哈希和既有有效内容必须保持与原任务书一致。

## 官方原始任务书

{original}

## 完整 diagnostics

```json
{json.dumps(diagnostics, ensure_ascii=False, indent=2)}
```

## 最新未通过结果

{latest}
"""
    path.write_text(text, encoding="utf-8")
    return path


def _worker_instruction(prompt: Path, staged: Path, phase: str) -> str:
    output_contract = (
        "输出必须是任务书规定的单一 ExpertResult v3 JSON object。"
        if phase == "experts" else "输出必须是任务书规定的完整最终文档。"
    )
    return (
        "你是当前主 agent 通过其原生委派能力创建的独立子代理；必须继承主 agent 的"
        "provider/model，不得选择或启动 codex、claude、dsh 或其他外部 CLI。\n"
        f"阶段：{phase}。唯一任务书：{prompt}。\n"
        "只读取该任务书；不要读取其他项目文件，不使用网络、shell 或外部知识。"
        + output_contract + "\n"
        f"将最终文档以 UTF-8 写入临时输出：{staged}。不要写最终结果路径。"
        "写入成功后，最终回复只报告 WRITTEN 和该临时路径；不要重复长文。"
        "若宿主不给子代理文件写入能力，则在最终回复返回完整文档，由主 agent 写入上述"
        " staging；不得因此启动任何外部 CLI。"
    )


def _build_jobs(code: str, phase: str, ids: list[str], token: str,
                *, retry: bool, pass_number: int) -> list[dict]:
    jobs: list[dict] = []
    for worker_id in ids:
        if phase == "experts" and retry:
            prompt = _repair_prompt(code, worker_id, pass_number)
        elif phase in {"challenges", "cross-reviews"} and retry:
            prompt = _review_repair_prompt(code, phase, worker_id, pass_number)
        else:
            prompt = _prompt_path(code, phase, worker_id)
        prompt_bytes = prompt.read_bytes()
        estimated_tokens = (len(prompt_bytes) + 2) // 3
        if len(prompt_bytes) > MAX_TASK_PROMPT_BYTES or estimated_tokens > MAX_ESTIMATED_PROMPT_TOKENS:
            raise NativeTaskError(
                f"任务书超出委派预算: {prompt} bytes={len(prompt_bytes)} "
                f"estimated_tokens={estimated_tokens}"
            )
        prompt_text = prompt_bytes.decode("utf-8")
        unresolved = sorted(set(UNRESOLVED_PLACEHOLDER_RE.findall(prompt_text)))
        if unresolved:
            raise NativeTaskError(f"任务书含未解析占位符: {prompt}: {unresolved[:5]}")
        staged = RUNTIME_ROOT / (
            f".invest_native_output_{code}_{phase}_{worker_id}.{token}.next"
        )
        staged.unlink(missing_ok=True)
        instruction = _worker_instruction(prompt, staged, phase)
        jobs.append({
            "id": worker_id,
            "description": f"{phase}:{worker_id}",
            "prompt_path": str(prompt),
            "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "prompt_bytes": len(prompt_bytes),
            "estimated_prompt_tokens": estimated_tokens,
            "staged_output_path": str(staged),
            "result_path": str(_result_path(code, phase, worker_id)),
            "instruction": instruction,
            "instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
            "committed": False,
        })
    return jobs


def _public_plan(plan: dict, *, status: str = "READY") -> dict:
    return {
        "status": status,
        "schema_version": plan["schema_version"],
        "mode": "host-native",
        "inherit_parent_provider": True,
        "inherit_parent_model": True,
        "provider_override": None,
        "model_override": None,
        "recommended_max_concurrency": min(2, len(plan["jobs"])),
        "ts_code": plan["ts_code"],
        "phase": plan["phase"],
        "batch_id": plan["batch_id"],
        "transaction_id": plan["transaction_id"],
        "retry": plan["retry"],
        "pass": plan["pass"],
        "jobs": plan["jobs"],
        "next": {
            "after_each_child": (
                f"python3 scripts/native_agent_tasks.py commit {plan['phase']} "
                f"{plan['ts_code']} <job-id> --child-id <host-child-id>"
            ),
            "after_all_children": (
                f"python3 scripts/native_agent_tasks.py advance {plan['phase']} "
                f"{plan['ts_code']}"
            ),
            "on_interruption": (
                f"python3 scripts/native_agent_tasks.py resume {plan['phase']} "
                f"{plan['ts_code']}"
            ),
        },
    }


def begin(code: str, phase: str, retry: bool) -> dict:
    _assert_contract_frozen(code)
    path = _plan_path(code)
    if path.exists():
        raise NativeTaskError(f"已有活动的 host-native 计划: {path}")
    token: str | None = None
    try:
        claim = claim_run(code, "native", RUNTIME_ROOT)
        token = str(claim["token"])
        ids = _prepare_phase(code, phase, retry)
        if retry and not ids:
            release_run(code, "native", RUNTIME_ROOT, token=token)
            return {
                "status": "PASS", "mode": "host-native", "phase": phase,
                "ts_code": code, "message": "当前阶段已全部通过，无需重试",
            }
        if retry:
            claim_retry(code, phase, RUNTIME_ROOT)
        batch_id = current_batch_id(code, RUNTIME_ROOT)
        transaction_id = secrets.token_hex(12)
        if not retry:
            for worker_id in ids:
                source = _prompt_path(code, phase, worker_id)
                _atomic_text(
                    _original_prompt_path(code, phase, worker_id),
                    source.read_text(encoding="utf-8"),
                )
        elif any(not _original_prompt_path(code, phase, worker_id).is_file() for worker_id in ids):
            raise NativeTaskError("retry 缺少官方原始任务书证据，拒绝继续")
        if retry and phase == "experts":
            for worker_id in ids:
                _freeze_decision_baseline(code, worker_id)
        jobs = _build_jobs(
            code, phase, ids, token, retry=retry, pass_number=1,
        )
        plan = {
            "schema_version": PLAN_SCHEMA,
            "ts_code": code,
            "phase": phase,
            "batch_id": batch_id,
            "transaction_id": transaction_id,
            "guard_token": token,
            "retry": retry,
            "retry_started": False,
            "pass": 1,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "jobs": jobs,
        }
        _atomic_json(path, plan)
        _archive_evidence(plan, "begin")
        record_execution(
            code, phase, backend="host-native", host="current-agent",
            model="inherit-parent", concurrency=min(2, len(jobs)), runtime_root=RUNTIME_ROOT,
            repair_max_passes=MAX_EXPERT_REPAIR_PASSES if phase == "experts" else 1,
            action="BEGIN_RETRY" if retry else "BEGIN",
            transaction_id=transaction_id,
        )
        return _public_plan(plan)
    except Exception:
        if token is not None:
            try:
                release_run(code, "native", RUNTIME_ROOT, token=token)
            except GuardError:
                pass
        path.unlink(missing_ok=True)
        raise


def _extract_decision(path: Path) -> dict | None:
    """Extract a complete decision object, even from later-truncated JSON."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(text)
        decision = payload.get("decision") if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        match = re.search(r'"decision"\s*:\s*', text)
        if not match:
            return None
        try:
            decision, _ = json.JSONDecoder().raw_decode(text, match.end())
        except json.JSONDecodeError:
            return None
    return decision if isinstance(decision, dict) else None


def _decision_signature(path: Path) -> tuple | None:
    """Return only decision fields for fail-closed trace-repair comparison."""
    decision = _extract_decision(path)
    if not decision:
        return None
    try:
        score = decision.get("score")
        verdict = decision.get("verdict")
        direction = decision.get("conclusion_direction")
        veto = decision.get("veto_triggers")
        if (isinstance(score, bool) or not isinstance(score, int)
                or not isinstance(verdict, str) or not isinstance(direction, str)
                or not isinstance(veto, list)
                or any(not isinstance(item, str) for item in veto)):
            return None
        return score, verdict, direction, tuple(veto)
    except TypeError:
        return None


def _expert_structure_signature(path: Path) -> dict | None:
    """Capture monotonic structural minima from a parseable expert result."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    fields = ("analysis_sections", "risks", "narrative_checks")
    values = {field: payload.get(field) for field in fields}
    if any(not isinstance(values[field], list) for field in fields):
        return None
    checklist = payload.get("checklist_conclusions")
    if not isinstance(checklist, dict) or any(not isinstance(key, str) for key in checklist):
        return None
    return {
        "analysis_sections_min": max(5, len(values["analysis_sections"])),
        "risks_min": max(3, len(values["risks"])),
        "narrative_checks_min": max(3, len(values["narrative_checks"])),
        "checklist_keys": sorted(checklist),
    }


def _freeze_decision_baseline(code: str, expert_id: str) -> Path:
    target = _decision_baseline_path(code, expert_id)
    if target.is_file():
        return target
    candidates = (
        RUNTIME_ROOT / f"invest_result_{code}_{expert_id}.v3.json",
        RUNTIME_ROOT / f"invest_rejected_result_{code}_{expert_id}.v3.json",
    )
    present = [path for path in candidates if path.is_file()]
    if not present:
        raise NativeTaskError(f"{expert_id} 缺少首次独立产出，拒绝 repair")
    source = next(
        (path for path in present if _decision_signature(path) is not None),
        present[0],
    )
    decision = _extract_decision(source)
    structure = _expert_structure_signature(source)
    if decision is None and structure is None:
        kind = "unparsable"
    elif decision is None:
        kind = "non_decision"
    else:
        kind = "decision"
    _atomic_json(target, {
        "schema_version": "invest-skill.decision-baseline.v1",
        "expert_id": expert_id,
        "source_path": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "decision": decision,
        "structure": structure,
        "frozen_kind": kind,
        "frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    return target


def _expert_structure_regression(baseline_path: Path, repaired_path: Path) -> str | None:
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "repair structure baseline unreadable"
    expected = baseline.get("structure") if isinstance(baseline, dict) else None
    if expected is None:
        return None
    if not isinstance(expected, dict):
        return "repair structure baseline invalid"
    actual = _expert_structure_signature(repaired_path)
    if actual is None:
        return "repaired expert structure unreadable"
    for field in ("analysis_sections_min", "risks_min", "narrative_checks_min"):
        required = expected.get(field)
        observed = actual.get(field)
        if not isinstance(required, int) or not isinstance(observed, int) or observed < required:
            return f"repair structure regression: {field} {observed!r} < {required!r}"
    expected_keys = expected.get("checklist_keys")
    actual_keys = actual.get("checklist_keys")
    if (not isinstance(expected_keys, list) or not isinstance(actual_keys, list)
            or not set(expected_keys) <= set(actual_keys)):
        return "repair structure regression: checklist keys removed"
    return None


def _review_signature(path: Path, phase: str) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return None
    try:
        import yaml
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except (yaml.YAMLError, TypeError):
        return None
    field = "challenge_verdict" if phase == "challenges" else "cross_verdict"
    value = frontmatter.get(field) if isinstance(frontmatter, dict) else None
    return str(value) if value else None


def _reject_review_semantic(code: str, phase: str, worker_id: str, plan: dict,
                            job: dict, raw_bytes: bytes, content_hash: str,
                            child_id: str, previous: str, repaired: str | None) -> None:
    reason = f"trace-only review repair semantic diff: verdict {previous!r} != {repaired!r}"
    rejected = RUNTIME_ROOT / f"invest_rejected_result_{code}_{phase}_{worker_id}.md"
    error_path = RUNTIME_ROOT / f"invest_native_compile_error_{code}_{phase}_{worker_id}.json"
    _atomic_text(rejected, raw_bytes.decode("utf-8"))
    _atomic_json(error_path, {
        "worker_id": worker_id, "content_sha256": content_hash, "error": reason,
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    job["commit_rejected"] = True
    job["commit_error"] = reason
    job["content_sha256"] = content_hash
    _atomic_json(_plan_path(code), plan)
    _archive_evidence(plan, f"semantic_rejected_{worker_id}")
    record_execution(
        code, phase, backend="host-native", host="current-agent",
        model="inherit-parent", action="COMMIT", status="REJECTED",
        transaction_id=str(plan["transaction_id"]), job_id=worker_id,
        content_hash=content_hash,
        detail=json.dumps({"child_id": child_id, "error": reason}, ensure_ascii=False),
        runtime_root=RUNTIME_ROOT,
    )
    raise NativeTaskError(reason)


def _consume_retry_after_valid_content(plan: dict) -> None:
    if not plan.get("retry") or plan.get("retry_started"):
        return
    begin_retry(str(plan["ts_code"]), str(plan["phase"]), RUNTIME_ROOT)
    plan["retry_started"] = True
    plan["retry_started_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _atomic_json(_plan_path(str(plan["ts_code"])), plan)


def _commit_unlocked(code: str, phase: str, worker_id: str, child_id: str) -> dict:
    _assert_contract_frozen(code)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", child_id):
        raise NativeTaskError("commit 必须提供合法的宿主 child-id 委派回执")
    plan = _load_plan(code)
    if plan.get("phase") != phase:
        raise NativeTaskError(f"活动阶段是 {plan.get('phase')}，不是 {phase}")
    matches = [item for item in plan["jobs"] if item.get("id") == worker_id]
    if len(matches) != 1:
        raise NativeTaskError(f"worker 不属于当前计划: {worker_id}")
    job = matches[0]
    job["child_id"] = child_id
    job["delegation_bound_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    staged = Path(job["staged_output_path"])
    if staged.is_symlink() or not staged.is_file() or staged.stat().st_size == 0:
        raise NativeTaskError(f"子代理临时输出缺失、为空或不是普通文件: {staged}")
    try:
        staged.resolve().relative_to(RUNTIME_ROOT.resolve())
    except ValueError as exc:
        raise NativeTaskError(f"staging 越出运行时根: {staged}") from exc
    if staged.stat().st_size > 512 * 1024:
        raise NativeTaskError(f"staging 体积异常: {staged.stat().st_size} bytes")
    raw_bytes = staged.read_bytes()
    if b"\x00" in raw_bytes:
        raise NativeTaskError("staging 含 NUL")
    try:
        raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NativeTaskError("staging 不是合法 UTF-8") from exc
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    result = Path(job["result_path"])
    previous_review = (
        _review_signature(result, phase)
        if plan.get("retry") and phase in {"challenges", "cross-reviews"}
        else None
    )
    if (plan.get("retry") and phase in {"challenges", "cross-reviews"}
            and result.is_file() and previous_review is None):
        raise NativeTaskError("上一份已发布 review 缺少合法 verdict，拒绝语义修复")
    if phase == "experts":
        sidecar_result = RUNTIME_ROOT / f"invest_result_{code}_{worker_id}.v3.json"
        baseline_path = _decision_baseline_path(code, worker_id)
        previous_decision = None
        if plan.get("retry"):
            if not baseline_path.is_file():
                raise NativeTaskError("repair 缺少首次独立产出 baseline，拒绝语义修复")
            try:
                baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise NativeTaskError("repair baseline 不可读，拒绝语义修复") from exc
            previous_decision = _decision_signature(baseline_path)
            if (isinstance(baseline_payload, dict)
                    and baseline_payload.get("frozen_kind") == "decision"
                    and previous_decision is None):
                raise NativeTaskError("repair baseline 声称有 decision 但不可复算，拒绝语义修复")
        compiled_sidecar = staged.with_suffix(staged.suffix + ".compiled.json")
        compiled_markdown = staged.with_suffix(staged.suffix + ".compiled.md")
        compiled_sidecar.unlink(missing_ok=True)
        compiled_markdown.unlink(missing_ok=True)
        try:
            _run([
                sys.executable, "scripts/expert_result_v3.py", "compile", code,
                worker_id, str(staged), "--sidecar", str(compiled_sidecar),
                "--markdown", str(compiled_markdown),
            ])
        except NativeTaskError as exc:
            rejected = RUNTIME_ROOT / f"invest_rejected_result_{code}_{worker_id}.v3.json"
            error_path = RUNTIME_ROOT / f"invest_native_compile_error_{code}_{worker_id}.json"
            _atomic_text(rejected, raw_bytes.decode("utf-8"))
            _atomic_json(error_path, {
                "expert_id": worker_id,
                "content_sha256": content_hash,
                "error": str(exc),
                "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            })
            job["commit_rejected"] = True
            job["commit_error"] = str(exc)[:4000]
            job["content_sha256"] = content_hash
            job["commit_attempted_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            _atomic_json(_plan_path(code), plan)
            _archive_evidence(plan, f"rejected_{worker_id}")
            record_execution(
                code, phase, backend="host-native", host="current-agent",
                model="inherit-parent", action="COMMIT", status="REJECTED",
                transaction_id=str(plan["transaction_id"]), job_id=worker_id,
                content_hash=content_hash,
                detail=json.dumps({"child_id": child_id, "error": str(exc)[:1000]}, ensure_ascii=False),
                runtime_root=RUNTIME_ROOT,
            )
            raise
        if plan.get("retry") and previous_decision is not None:
            repaired_decision = _decision_signature(compiled_sidecar)
            reason = None
            if repaired_decision is None or repaired_decision != previous_decision:
                reason = (
                    "trace-only repair semantic diff: decision.score/verdict/"
                    "conclusion_direction/veto_triggers changed or missing; "
                    "preserve the previously published decision"
                )
            if reason is None:
                reason = _expert_structure_regression(baseline_path, compiled_sidecar)
            if reason is not None:
                rejected = RUNTIME_ROOT / f"invest_rejected_result_{code}_{worker_id}.v3.json"
                _atomic_text(rejected, raw_bytes.decode("utf-8"))
                error_path = RUNTIME_ROOT / f"invest_native_compile_error_{code}_{worker_id}.json"
                _atomic_json(error_path, {"expert_id": worker_id, "content_sha256": content_hash, "error": reason})
                job["commit_rejected"] = True
                job["commit_error"] = reason
                job["content_sha256"] = content_hash
                _atomic_json(_plan_path(code), plan)
                _archive_evidence(plan, f"semantic_rejected_{worker_id}")
                record_execution(
                    code, phase, backend="host-native", host="current-agent",
                    model="inherit-parent", action="COMMIT", status="REJECTED",
                    transaction_id=str(plan["transaction_id"]), job_id=worker_id,
                    content_hash=content_hash,
                    detail=json.dumps({"child_id": child_id, "error": reason}, ensure_ascii=False),
                    runtime_root=RUNTIME_ROOT,
                )
                raise NativeTaskError(reason)
        _consume_retry_after_valid_content(plan)
        os.replace(compiled_sidecar, sidecar_result)
        os.replace(compiled_markdown, result)
        staged.unlink(missing_ok=True)
        job["sidecar_path"] = str(sidecar_result)
    elif phase == "challenges":
        normalized = staged.with_suffix(staged.suffix + ".normalized")
        normalized.unlink(missing_ok=True)
        try:
            _run([
                sys.executable, "scripts/normalize_challenge.py", code, worker_id,
                str(staged), str(normalized),
            ])
        except NativeTaskError as exc:
            rejected = RUNTIME_ROOT / f"invest_rejected_result_{code}_{phase}_{worker_id}.md"
            error_path = RUNTIME_ROOT / f"invest_native_compile_error_{code}_{phase}_{worker_id}.json"
            _atomic_text(rejected, raw_bytes.decode("utf-8"))
            _atomic_json(error_path, {
                "worker_id": worker_id,
                "content_sha256": content_hash,
                "error": str(exc),
                "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            })
            job["commit_rejected"] = True
            job["commit_error"] = str(exc)[:4000]
            job["content_sha256"] = content_hash
            job["commit_attempted_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            _atomic_json(_plan_path(code), plan)
            _archive_evidence(plan, f"rejected_{worker_id}")
            record_execution(
                code, phase, backend="host-native", host="current-agent",
                model="inherit-parent", action="COMMIT", status="REJECTED",
                transaction_id=str(plan["transaction_id"]), job_id=worker_id,
                content_hash=content_hash,
                detail=json.dumps({"child_id": child_id, "error": str(exc)[:1000]}, ensure_ascii=False),
                runtime_root=RUNTIME_ROOT,
            )
            raise
        if previous_review is not None:
            repaired_review = _review_signature(normalized, phase)
            if repaired_review != previous_review:
                _reject_review_semantic(
                    code, phase, worker_id, plan, job, raw_bytes, content_hash,
                    child_id, previous_review, repaired_review,
                )
        _consume_retry_after_valid_content(plan)
        os.replace(normalized, result)
        staged.unlink(missing_ok=True)
    else:
        if previous_review is not None:
            repaired_review = _review_signature(staged, phase)
            if repaired_review != previous_review:
                _reject_review_semantic(
                    code, phase, worker_id, plan, job, raw_bytes, content_hash,
                    child_id, previous_review, repaired_review,
                )
        _consume_retry_after_valid_content(plan)
        os.replace(staged, result)
    job["committed"] = True
    job["content_sha256"] = content_hash
    job["committed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _atomic_json(_plan_path(code), plan)
    _archive_evidence(plan, f"commit_{worker_id}")
    record_execution(
        code, phase, backend="host-native", host="current-agent",
        model="inherit-parent", action="COMMIT", status="PUBLISHED",
        transaction_id=str(plan["transaction_id"]), job_id=worker_id,
        content_hash=content_hash,
        detail=json.dumps({"child_id": child_id}, ensure_ascii=False),
        runtime_root=RUNTIME_ROOT,
    )
    return {
        "status": "COMMITTED", "ts_code": code, "phase": phase,
        "id": worker_id, "result_path": str(result),
    }


def commit(code: str, phase: str, worker_id: str, child_id: str) -> dict:
    lock_path = RUNTIME_ROOT / f".invest_native_plan_{code}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            return _commit_unlocked(code, phase, worker_id, child_id)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _preserve_failure(code: str, phase: str) -> str | None:
    result = subprocess.run(
        [sys.executable, "scripts/preserve_failure_evidence.py", code, phase],
        cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _archive_and_release(plan: dict, status: str) -> Path:
    code = str(plan["ts_code"])
    plan["terminal_status"] = status
    plan["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _archive_evidence(plan, f"terminal_{status.lower()}")
    archive = RUNTIME_ROOT / (
        f"invest_native_run_{code}_{plan['phase']}_{plan['batch_id']}_{status.lower()}.json"
    )
    _atomic_json(archive, plan)
    record_execution(
        code, str(plan["phase"]), backend="host-native", host="current-agent",
        model="inherit-parent", action="TERMINAL", status=status,
        transaction_id=str(plan["transaction_id"]), runtime_root=RUNTIME_ROOT,
    )
    release_run(
        code, "native", RUNTIME_ROOT, token=str(plan["guard_token"]),
    )
    _plan_path(code).unlink(missing_ok=True)
    return archive


def advance(code: str, phase: str) -> dict:
    _assert_contract_frozen(code)
    plan = _load_plan(code)
    if plan.get("phase") != phase:
        raise NativeTaskError(f"活动阶段是 {plan.get('phase')}，不是 {phase}")
    pending = [
        item["id"] for item in plan["jobs"]
        if not item.get("committed") and not item.get("commit_rejected")
    ]
    if pending:
        raise NativeTaskError("仍有子代理输出未 commit: " + ", ".join(pending))
    passed, detail = _validate_phase(code, phase)
    if passed:
        archive = _archive_and_release(plan, "PASS")
        return {
            "status": "PASS", "mode": "host-native", "phase": phase,
            "ts_code": code, "archive": str(archive), "validation": detail,
        }

    if (
        bool(plan.get("retry")) and phase == "experts"
        and int(plan.get("pass", 1)) < MAX_EXPERT_REPAIR_PASSES
    ):
        ids = _failing_ids(code, phase)
        if not ids:
            archive = _archive_and_release(plan, "PASS")
            return {
                "status": "PASS", "mode": "host-native", "phase": phase,
                "ts_code": code, "archive": str(archive), "validation": detail,
            }
        plan["pass"] = int(plan["pass"]) + 1
        plan["jobs"] = _build_jobs(
            code, phase, ids, str(plan["guard_token"]), retry=True,
            pass_number=int(plan["pass"]),
        )
        plan["last_validation"] = detail
        _atomic_json(_plan_path(code), plan)
        _archive_evidence(plan, f"pass_{plan['pass']}")
        return _public_plan(plan, status="CONTINUE")

    evidence = _preserve_failure(code, phase)
    archive = _archive_and_release(plan, "FAIL")
    return {
        "status": "FAIL", "mode": "host-native", "phase": phase,
        "ts_code": code, "archive": str(archive),
        "failure_evidence": evidence, "validation": detail,
        "next": (
            f"python3 scripts/native_agent_tasks.py begin {phase} {code} --retry"
            if not plan.get("retry") else "本批次唯一重试已结束；停止流程"
        ),
    }


def note_transport_failure(code: str, phase: str, worker_id: str,
                           detail: str) -> dict:
    _assert_contract_frozen(code)
    lock_path = RUNTIME_ROOT / f".invest_native_plan_{code}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            plan = _load_plan(code)
            if plan.get("phase") != phase:
                raise NativeTaskError(f"活动阶段是 {plan.get('phase')}，不是 {phase}")
            matches = [job for job in plan["jobs"] if job.get("id") == worker_id]
            if len(matches) != 1:
                raise NativeTaskError(f"worker 不属于当前计划: {worker_id}")
            job = matches[0]
            failures = list(job.get("transport_failures") or [])
            failures.append({
                "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "detail": detail[:1000],
            })
            job["transport_failures"] = failures
            _atomic_json(_plan_path(code), plan)
            _archive_evidence(plan, f"rejected_{worker_id}")
            record_execution(
                code, phase, backend="host-native", host="current-agent",
                model="inherit-parent", action="TRANSPORT_FAILURE",
                status="RETRYABLE", transaction_id=str(plan["transaction_id"]),
                job_id=worker_id, detail=detail[:1000], runtime_root=RUNTIME_ROOT,
            )
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return {
        "status": "RETRYABLE", "semantic_retry_consumed": False,
        "ts_code": code, "phase": phase, "id": worker_id,
    }


def resume(code: str, phase: str) -> dict:
    _assert_contract_frozen(code)
    plan = _load_plan(code)
    if plan.get("phase") != phase:
        raise NativeTaskError(f"活动阶段是 {plan.get('phase')}，不是 {phase}")
    claim = claim_run(code, "native", RUNTIME_ROOT)
    plan["guard_token"] = str(claim["token"])
    plan["resumed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _atomic_json(_plan_path(code), plan)
    record_execution(
        code, phase, backend="host-native", host="current-agent",
        model="inherit-parent", action="RESUME", status="ACTIVE",
        transaction_id=str(plan["transaction_id"]), runtime_root=RUNTIME_ROOT,
    )
    return _public_plan(plan, status="ACTIVE")


def abort(code: str, phase: str) -> dict:
    plan = _load_plan(code)
    if plan.get("phase") != phase:
        raise NativeTaskError(f"活动阶段是 {plan.get('phase')}，不是 {phase}")
    archive = _archive_and_release(plan, "ABORTED")
    return {
        "status": "ABORTED", "phase": phase, "ts_code": code,
        "archive": str(archive),
    }


def status(code: str) -> dict:
    path = _plan_path(code)
    if not path.exists():
        return {"status": "IDLE", "ts_code": code, "mode": "host-native"}
    return _public_plan(_load_plan(code), status="ACTIVE")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="由当前主 agent 的原生子代理执行任务；本脚本不选择或启动模型",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("begin")
    start.add_argument("phase", choices=PHASES)
    start.add_argument("ts_code")
    start.add_argument("--retry", action="store_true")
    for name in ("advance", "resume", "abort"):
        item = sub.add_parser(name)
        item.add_argument("phase", choices=PHASES)
        item.add_argument("ts_code")
    save = sub.add_parser("commit")
    save.add_argument("phase", choices=PHASES)
    save.add_argument("ts_code")
    save.add_argument("worker_id")
    save.add_argument("--child-id", required=True)
    failed = sub.add_parser("note-transport-failure")
    failed.add_argument("phase", choices=PHASES)
    failed.add_argument("ts_code")
    failed.add_argument("worker_id")
    failed.add_argument("detail")
    state = sub.add_parser("status")
    state.add_argument("ts_code")
    args = parser.parse_args()
    try:
        code = normalize_ts_code(args.ts_code)
        if args.command == "begin":
            payload = begin(code, args.phase, args.retry)
        elif args.command == "commit":
            payload = commit(code, args.phase, args.worker_id, args.child_id)
        elif args.command == "note-transport-failure":
            payload = note_transport_failure(
                code, args.phase, args.worker_id, args.detail,
            )
        elif args.command == "advance":
            payload = advance(code, args.phase)
        elif args.command == "resume":
            payload = resume(code, args.phase)
        elif args.command == "abort":
            payload = abort(code, args.phase)
        else:
            payload = status(code)
    except (OSError, ValueError, json.JSONDecodeError, GuardError, NativeTaskError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if payload.get("status") not in {"ERROR", "FAIL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
