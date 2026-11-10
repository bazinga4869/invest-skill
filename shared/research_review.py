"""Independent research acceptance: declared identities, NOT cryptographic authentication."""
from __future__ import annotations

import hashlib
import json
import re

import yaml

SCHEMA = "invest-skill.research-review.v1"


def adjudicator_identity(draft: str) -> str:
    match = re.search(r"^## 综合裁决 — 裁判长\s*$(.*?)(?=^## |\Z)", draft, re.M | re.S)
    block = re.search(r"```yaml\s*\n(.*?)```", match.group(1), re.S) if match else None
    if not block:
        return ""
    try:
        value = yaml.safe_load(block.group(1).strip().strip("-")) or {}
        return str(value.get("adjudicator", {}).get("identity") or "").strip()
    except (yaml.YAMLError, AttributeError):
        return ""


def identity(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def validate_review(receipt: dict, *, ts_code: str, batch_id: str,
                    draft: bytes, execution: dict) -> list[str]:
    errors = []
    if not isinstance(receipt, dict):
        return ["独立投研复核签收必须是对象"]
    if (receipt.get("schema_version") != SCHEMA
            or receipt.get("ts_code") != ts_code
            or receipt.get("batch_id") != batch_id
            or receipt.get("draft_sha256") != hashlib.sha256(draft).hexdigest()):
        errors.append("独立投研复核签收 schema/批次/草稿哈希不一致")
    if receipt.get("verdict") != "PASS":
        errors.append("独立投研复核必须明确 PASS")
    reviewer = identity(receipt.get("reviewer_identity"))
    orchestrator = identity(receipt.get("orchestrator_identity"))
    adjudicator = identity(receipt.get("adjudicator_identity"))
    invalid = {"", "unknown", "current-agent", "default", "orchestrator", "adjudicator"}
    if any(value.casefold() in invalid for value in (reviewer, orchestrator, adjudicator)):
        errors.append("复核/编排/裁判必须声明具体 identity")
    if reviewer.casefold() in {orchestrator.casefold(), adjudicator.casefold()}:
        errors.append("投研复核 identity 必须不同于编排及裁判")
    if adjudicator != adjudicator_identity(draft.decode("utf-8")):
        errors.append("复核签收裁判 identity 与草稿不一致")
    if not isinstance(execution, dict) or not isinstance(execution.get("events"), list):
        return errors + ["同批次执行台账结构非法"]
    hosts = {identity(event.get("host")) for event in execution["events"]
             if isinstance(event, dict) and event.get("backend") == "orchestrator"}
    host_keys = {host.casefold() for host in hosts}
    if (execution.get("batch_id") != batch_id or orchestrator not in hosts
            or reviewer.casefold() in host_keys):
        errors.append("复核签收 identity 与同批次编排执行台账不一致")
    if adjudicator.casefold() == orchestrator.casefold() or adjudicator.casefold() in host_keys:
        errors.append("裁判 identity 必须独立于编排者")
    worker_ids = set()
    for event in execution["events"]:
        if not isinstance(event, dict) or event.get("backend") != "host-native":
            continue
        detail = event.get("detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except (ValueError, TypeError):
                detail = {}
        if isinstance(detail, dict) and identity(detail.get("child_id")):
            worker_ids.add(identity(detail["child_id"]).casefold())
    if reviewer.casefold() in worker_ids or adjudicator.casefold() in worker_ids:
        errors.append("裁判及全报告复核不得复用专家/质询/盲审 child id")
    if not identity(receipt.get("reviewed_at")) or not identity(receipt.get("statement")):
        errors.append("复核签收缺少 reviewed_at/statement")
    return errors
