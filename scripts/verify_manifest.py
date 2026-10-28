#!/usr/bin/env python3
"""验证正式报告引用的归档 manifest 及全部文件哈希。"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))
from shared.batch_contract import (
    batch_id_from_components, canonical_data_hash, contract_snapshot_hash,
    pre_report_wiki_batch_id_from_components, prompt_bundle_hash,
    wiki_snapshot_hash,
)
from scripts.collect_results import validate_expert
from scripts.collect_challenges import validate_challenge
from scripts.collect_cross_reviews import (
    CROSS_REVIEWERS, validate_cross_aggregate,
)
from shared.contracts import (
    CONTRACT_VERSION, LEGACY_CONTRACT_VERSION, PREVIOUS_CONTRACT_VERSION,
    PRE_REPORT_WIKI_CONTRACT_VERSION, REQUIRED_REPLAY_FILES, required_replay_files,
)
from shared.project_config import configured_path
from shared.report_wiki import (
    render_annual_text, report_wiki_engine_hash, validate_report_bundle,
)
_reports_override = os.environ.get("INVEST_REPORTS_DIR")
REPORTS_DIR = (Path(_reports_override).expanduser() if _reports_override
               else configured_path("invest_tool_dir", "./reports/invest_tool"))
EXPERTS = [
    item["id"] for item in
    json.loads((SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8"))["experts"]
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(report_path: str) -> dict:
    report = Path(report_path).resolve()
    if not report.is_file():
        return {"status": "FAIL", "errors": [f"正式报告不存在: {report}"]}
    text = report.read_text(encoding="utf-8")
    match = re.search(r'<!--\s*artifact_manifest:\s*([^>]+?)\s*-->', text)
    if not match:
        return {"status": "FAIL", "errors": ["报告缺少 artifact_manifest 标记"]}
    reports_root = REPORTS_DIR.resolve()
    manifest_path = (reports_root / match.group(1).strip()).resolve()
    if reports_root not in manifest_path.parents:
        return {"status": "FAIL", "errors": ["manifest 路径越界"]}
    if not manifest_path.is_file():
        return {"status": "FAIL", "errors": [f"manifest 不存在: {manifest_path}"]}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "errors": [f"manifest 不可读: {exc}"]}
    code_match = re.search(r'(\d{6}\.(?:SH|SZ|BJ))', report.name)
    expected_code = code_match.group(1) if code_match else None
    errors = []
    if manifest.get("ts_code") != expected_code:
        errors.append(f"manifest ts_code 不匹配: {manifest.get('ts_code')} != {expected_code}")
    if manifest.get("run_id") != manifest_path.parent.name:
        errors.append(f"manifest run_id 与目录不一致: {manifest.get('run_id')} != {manifest_path.parent.name}")
    contract_version = str(manifest.get("contract_version") or "")
    if contract_version not in {
        LEGACY_CONTRACT_VERSION, PRE_REPORT_WIKI_CONTRACT_VERSION,
        PREVIOUS_CONTRACT_VERSION, CONTRACT_VERSION,
    }:
        errors.append(f"manifest contract_version 非法: {contract_version!r}")
    is_legacy = contract_version == LEGACY_CONTRACT_VERSION
    requires_report_wiki = contract_version in {PREVIOUS_CONTRACT_VERSION, CONTRACT_VERSION}
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        errors.append("manifest files 为空")
        entries = []
    seen_report = False
    entry_names = set()
    for entry in entries:
        name = entry.get("name", "") if isinstance(entry, dict) else ""
        if not isinstance(entry, dict):
            errors.append("manifest file entry 不是对象")
            continue
        if not re.fullmatch(r'[0-9a-f]{64}', str(entry.get("sha256", ""))):
            errors.append(f"manifest sha256 非法: {name}")
        if (isinstance(entry.get("bytes"), bool)
                or not isinstance(entry.get("bytes"), int) or entry.get("bytes") < 0):
            errors.append(f"manifest bytes 非法: {name}")
        entry_names.add(name)
        path = (manifest_path.parent / name).resolve()
        if manifest_path.parent.resolve() not in path.parents:
            errors.append(f"归档文件路径越界: {name}")
            continue
        if not path.is_file():
            errors.append(f"归档文件缺失: {name}")
            continue
        if path.stat().st_size != entry.get("bytes"):
            errors.append(f"归档文件大小不匹配: {name}")
        if sha256(path) != entry.get("sha256"):
            errors.append(f"归档文件哈希不匹配: {name}")
        if name == report.name:
            seen_report = True
            if sha256(path) != sha256(report):
                errors.append("正式报告与归档副本不一致")
    if not seen_report:
        errors.append("manifest 未包含正式报告副本")
    if contract_version == CONTRACT_VERSION:
        publish_marker = manifest_path.parent / ".published.json"
        try:
            publication = json.loads(publish_marker.read_text(encoding="utf-8"))
            archived_report_path = manifest_path.parent / report.name
            if publication.get("schema_version") != "invest-skill.publication-receipt.v1":
                errors.append("publication receipt schema 非法")
            if publication.get("manifest_sha256") != sha256(manifest_path):
                errors.append("publication receipt manifest 哈希不一致")
            if publication.get("report_sha256") != sha256(archived_report_path):
                errors.append("publication receipt 报告哈希不一致")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            errors.append(f"publication receipt 不可复核: {exc}")
    if expected_code:
        expected_names = {
            f"invest_data_{expected_code}.json",
            f"invest_annual_{expected_code}.txt",
            f"{expected_code}.draft.md",
            f"{expected_code}.md",
            *{f"invest_prompt_{expected_code}_{expert_id}.txt" for expert_id in EXPERTS},
            *{f"invest_result_{expected_code}_{expert_id}.md" for expert_id in EXPERTS},
            *{f"invest_challenge_prompt_{expected_code}_{expert_id}.txt" for expert_id in EXPERTS},
            *{f"invest_challenge_result_{expected_code}_{expert_id}.md" for expert_id in EXPERTS},
            f"invest_level3_{expected_code}.json",
            "wiki_snapshot.json",
            "contract_bundle.json",
        }
        archived_data_path = manifest_path.parent / f"invest_data_{expected_code}.json"
        try:
            archived_contract = json.loads(
                archived_data_path.read_text(encoding="utf-8")
            ).get("meta", {}).get("expert_result_contract_version")
        except (OSError, json.JSONDecodeError):
            archived_contract = None
        if archived_contract == "expert-result/v3":
            expected_names.update({
                *{f"invest_native_prompt_{expected_code}_{expert_id}.txt" for expert_id in EXPERTS},
                *{f"invest_result_{expected_code}_{expert_id}.v3.json" for expert_id in EXPERTS},
            })
        if not is_legacy:
            expected_names.add(f"invest_execution_{expected_code}.json")
        archived_execution = {}
        if contract_version == CONTRACT_VERSION:
            expected_names.update({
                f"invest_verification_{expected_code}.json",
                f"invest_adjudication_{expected_code}.json",
            })
            execution_path = manifest_path.parent / f"invest_execution_{expected_code}.json"
            try:
                archived_execution = json.loads(execution_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                archived_execution = {}
            if any(
                event.get("action") == "BEGIN_RETRY"
                for event in (archived_execution.get("events") or [])
                if isinstance(event, dict)
            ):
                expected_names.add(f"invest_retry_evidence_{expected_code}.json")
        if requires_report_wiki:
            expected_names.add(f"invest_report_bundle_{expected_code}.json")
        level3_path = manifest_path.parent / f"invest_level3_{expected_code}.json"
        try:
            archived_level3 = json.loads(level3_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            archived_level3 = {}
            errors.append(f"归档三级触发判定不可读: {exc}")
        if archived_level3.get("triggered"):
            expected_names.update({
                f"invest_cross_blind_{expected_code}.md",
                *{f"invest_cross_prompt_{expected_code}_{reviewer}.txt"
                  for reviewer in CROSS_REVIEWERS},
                *{f"invest_cross_result_{expected_code}_{reviewer}.md"
                  for reviewer in CROSS_REVIEWERS},
            })
            cross_problems = validate_cross_aggregate(
                expected_code, base_dir=manifest_path.parent,
            )
            if cross_problems:
                errors.append(f"归档三方交叉盲审未通过契约: {cross_problems[:3]}")
        if len(entry_names) != len(entries):
            errors.append("manifest 存在重复文件名")
        missing = sorted(expected_names - entry_names)
        unexpected = sorted(entry_names - expected_names)
        if missing:
            errors.append(f"manifest 缺少证据: {missing}")
        if unexpected:
            errors.append(f"manifest 含非预期证据: {unexpected}")
        data_file = manifest_path.parent / f"invest_data_{expected_code}.json"
        if data_file.is_file():
            try:
                archived_data = json.loads(data_file.read_text(encoding="utf-8"))
                meta = archived_data.get("meta", {})
                data_batch = meta.get("batch_id")
                if not data_batch or manifest.get("batch_id") != data_batch:
                    errors.append(
                        f"manifest batch_id 不匹配: {manifest.get('batch_id')} != {data_batch}"
                    )
                if meta.get("data_hash") != canonical_data_hash(archived_data):
                    errors.append("归档数据快照 data_hash 重算不一致")
                recomputed_batch_id = (
                    batch_id_from_components(meta)
                    if requires_report_wiki
                    else pre_report_wiki_batch_id_from_components(meta)
                )
                if data_batch != recomputed_batch_id:
                    errors.append("归档数据快照 batch_id 组件重算不一致")
                wiki_snapshot_path = manifest_path.parent / "wiki_snapshot.json"
                try:
                    wiki_snapshot = json.loads(wiki_snapshot_path.read_text(encoding="utf-8"))
                    if wiki_snapshot_hash(wiki_snapshot.get("files") or {}) != meta.get("wiki_hash"):
                        errors.append("归档 wiki_snapshot 与批次 wiki_hash 不一致")
                except (OSError, json.JSONDecodeError, AttributeError) as exc:
                    errors.append(f"归档 wiki_snapshot 不可重算: {exc}")
                contract_path = manifest_path.parent / "contract_bundle.json"
                try:
                    contract = json.loads(contract_path.read_text(encoding="utf-8"))
                    if contract_snapshot_hash(
                        contract.get("prompt_contract_files") or []
                    ) != meta.get("prompt_contract_hash"):
                        errors.append("归档 contract_bundle 与批次 prompt_contract_hash 不一致")
                    replay_files = contract.get("replay_files")
                    if not is_legacy:
                        if not isinstance(replay_files, dict):
                            errors.append("归档 contract_bundle.replay_files 非法")
                        else:
                            prompt_paths = {
                                str(item.get("path") or "")
                                for item in (contract.get("prompt_contract_files") or [])
                                if isinstance(item, dict)
                            }
                            required = set(required_replay_files(contract_version))
                            if contract_version == PRE_REPORT_WIKI_CONTRACT_VERSION:
                                required.discard("shared/report_wiki.py")
                            missing_replay = sorted(
                                required - (set(replay_files) | prompt_paths)
                            )
                            if missing_replay:
                                errors.append(
                                    f"归档 replay bundle 缺少运行契约: {missing_replay}"
                                )
                    if contract_version == CONTRACT_VERSION:
                        engine = (contract.get("external_engines") or {}).get("report-wiki") or {}
                        engine_files = engine.get("files")
                        if not isinstance(engine_files, dict) or not engine_files:
                            errors.append("归档缺少 report-wiki 引擎源码快照")
                        else:
                            engine_hash = report_wiki_engine_hash(engine_files)
                            if (engine.get("tree_hash") != engine_hash
                                    or meta.get("report_wiki_engine_hash") != engine_hash
                                    or meta.get("report_wiki_engine_file_count") != len(engine_files)):
                                errors.append("归档 report-wiki 引擎身份不一致")
                except (OSError, json.JSONDecodeError, AttributeError) as exc:
                    contract = {}
                    errors.append(f"归档 contract_bundle 不可重算: {exc}")
                if contract_version == CONTRACT_VERSION:
                    receipt_path = manifest_path.parent / f"invest_verification_{expected_code}.json"
                    execution_path = manifest_path.parent / f"invest_execution_{expected_code}.json"
                    try:
                        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                        contract_texts = {
                            str(item.get("path") or ""): str(item.get("text") or "")
                            for item in (contract.get("prompt_contract_files") or [])
                            if isinstance(item, dict)
                        }
                        contract_texts.update(contract.get("replay_files") or {})
                        verifier_text = contract_texts.get("scripts/verify_report.py")
                        expected_verifier_hash = (
                            hashlib.sha256(verifier_text.encode("utf-8")).hexdigest()
                            if isinstance(verifier_text, str) else None
                        )
                        archived_report = manifest_path.parent / f"{expected_code}.md"
                        if receipt.get("schema_version") != "invest-skill.verification-receipt.v1":
                            errors.append("归档 verification receipt schema 非法")
                        if receipt.get("ts_code") != expected_code or receipt.get("batch_id") != data_batch:
                            errors.append("归档 verification receipt 身份不一致")
                        if receipt.get("verdict") != "PASS":
                            errors.append("归档 verification receipt 未通过")
                        if receipt.get("report_sha256") != sha256(archived_report):
                            errors.append("归档 verification receipt 报告哈希不一致")
                        if receipt.get("data_sha256") != sha256(data_file):
                            errors.append("归档 verification receipt 数据哈希不一致")
                        if not expected_verifier_hash or receipt.get("verifier_sha256") != expected_verifier_hash:
                            errors.append("归档 verification receipt 验证器哈希不一致")
                    except (OSError, json.JSONDecodeError, AttributeError) as exc:
                        errors.append(f"归档 verification receipt 不可复核: {exc}")
                    adjudication_path = manifest_path.parent / f"invest_adjudication_{expected_code}.json"
                    try:
                        adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
                        draft_path = manifest_path.parent / f"{expected_code}.draft.md"
                        draft_text = draft_path.read_text(encoding="utf-8")
                        adjudication_match = re.search(
                            r"^## 综合裁决 — 裁判长\s*$.*?(?=^## 裁判自检|\Z)",
                            draft_text, re.MULTILINE | re.DOTALL,
                        )
                        adjudication_hash = (
                            hashlib.sha256(adjudication_match.group(0).encode("utf-8")).hexdigest()
                            if adjudication_match else None
                        )
                        expected_experts = {
                            expert_id: sha256(manifest_path.parent / f"invest_result_{expected_code}_{expert_id}.md")
                            for expert_id in EXPERTS
                        }
                        expected_challenges = {
                            expert_id: sha256(manifest_path.parent / f"invest_challenge_result_{expected_code}_{expert_id}.md")
                            for expert_id in EXPERTS
                        }
                        if (adjudication.get("schema_version") != "invest-skill.adjudication-receipt.v1"
                                or adjudication.get("ts_code") != expected_code
                                or adjudication.get("batch_id") != data_batch
                                or adjudication.get("draft_sha256") != sha256(draft_path)
                                or adjudication.get("adjudication_sha256") != adjudication_hash
                                or adjudication.get("expert_result_sha256") != expected_experts
                                or adjudication.get("challenge_result_sha256") != expected_challenges
                                or adjudication.get("level3_sha256")
                                != sha256(manifest_path.parent / f"invest_level3_{expected_code}.json")):
                            errors.append("归档 adjudication receipt 身份或证据哈希不一致")
                    except (OSError, json.JSONDecodeError, AttributeError) as exc:
                        errors.append(f"归档 adjudication receipt 不可复核: {exc}")
                    try:
                        execution = json.loads(execution_path.read_text(encoding="utf-8"))
                        gates_pass = any(
                            event.get("phase") == "finalize"
                            and event.get("action") == "GATES"
                            and event.get("status") == "PASS"
                            for event in (execution.get("events") or [])
                            if isinstance(event, dict)
                        )
                        if not gates_pass:
                            errors.append("归档执行元数据缺少 finalize GATES PASS")
                    except (OSError, json.JSONDecodeError, AttributeError) as exc:
                        errors.append(f"归档 finalize 终态不可复核: {exc}")
                    retry_name = f"invest_retry_evidence_{expected_code}.json"
                    if retry_name in expected_names:
                        retry_path = manifest_path.parent / retry_name
                        try:
                            retry = json.loads(retry_path.read_text(encoding="utf-8"))
                            records = retry.get("files")
                            if (retry.get("schema_version") != "invest-skill.retry-evidence.v1"
                                    or retry.get("ts_code") != expected_code
                                    or retry.get("batch_id") != data_batch
                                    or not isinstance(records, list) or not records):
                                errors.append("归档 retry evidence ledger 身份/schema/内容非法")
                            else:
                                for record in records:
                                    raw = base64.b64decode(
                                        str(record.get("content_base64") or ""), validate=True,
                                    )
                                    if (record.get("bytes") != len(raw)
                                            or record.get("sha256")
                                            != hashlib.sha256(raw).hexdigest()):
                                        errors.append("归档 retry evidence 内部哈希不一致")
                                        break
                        except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
                            errors.append(f"归档 retry evidence 不可复核: {exc}")
                annual_path = manifest_path.parent / f"invest_annual_{expected_code}.txt"
                if annual_path.is_file():
                    annual_hash = hashlib.sha256(annual_path.read_bytes()).hexdigest()
                    if meta.get("annual_hash") != annual_hash:
                        errors.append("归档年报 annual_hash 重算不一致")
                if requires_report_wiki:
                    bundle_path = (
                        manifest_path.parent
                        / f"invest_report_bundle_{expected_code}.json"
                    )
                    try:
                        report_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                        report_years = int(meta.get("report_history_years"))
                        report_types = tuple(meta.get("report_types") or [])
                        semi_years = int(meta.get("report_semi_years") or 1)
                        as_of = datetime.strptime(
                            str(meta.get("analysis_date") or ""), "%Y%m%d"
                        )
                        bundle_problems = validate_report_bundle(
                            report_bundle,
                            ts_code=expected_code,
                            as_of=as_of,
                            years=report_years,
                            report_types=report_types,
                            semi_years=semi_years,
                        )
                        if bundle_problems:
                            errors.append(
                                "归档 report-wiki 证据包未通过契约: "
                                f"{bundle_problems[:5]}"
                            )
                        if (annual_path.is_file()
                                and annual_path.read_text(encoding="utf-8")
                                != render_annual_text(report_bundle)):
                            errors.append("归档年报与 report-wiki 证据包渲染结果不一致")
                        report_rows = [
                            item for item in (report_bundle.get("reports") or [])
                            if isinstance(item, dict)
                        ]
                        latest_report = max(
                            report_rows,
                            key=lambda item: (
                                str(item.get("announcement_date") or ""),
                                str(item.get("fiscal_year") or ""),
                            ),
                        ) if report_rows else {}
                        expected_meta = {
                            "report_bundle_hash": report_bundle.get("bundle_hash"),
                            "report_corpus_hash": report_bundle.get("corpus_hash"),
                            "report_wiki_schema": report_bundle.get("schema_version"),
                            "disclosure_query_status": "PASS",
                            "disclosure_query_as_of": report_bundle.get("as_of"),
                            "latest_report_period": latest_report.get("fiscal_year"),
                            "latest_report_type": latest_report.get("report_type"),
                            "latest_report_announcement_date": latest_report.get("announcement_date"),
                            "market_query_trade_date": archived_data.get("market", {}).get("trade_date"),
                        }
                        if report_bundle.get("schema_version") == "report-wiki.bundle.v2":
                            expected_meta.update({
                                "report_evidence_status": report_bundle.get("evidence_status"),
                                "report_summary_status": report_bundle.get("summary_status"),
                                "report_search_content_hash": (
                                    report_bundle.get("search", {}).get("content_hash")
                                ),
                            })
                        for field, value in expected_meta.items():
                            if meta.get(field) != value:
                                errors.append(
                                    f"归档数据快照 meta.{field} 与 report-wiki 不一致"
                                )
                    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                        errors.append(f"归档 report-wiki 证据包不可重算: {exc}")
                expected_date = str(archived_data.get("market", {}).get("trade_date") or "")
                expected_analysis = str(meta.get("analysis_date") or "")
                for expert_id in EXPERTS:
                    result_path = manifest_path.parent / f"invest_result_{expected_code}_{expert_id}.md"
                    prompt_path = manifest_path.parent / f"invest_prompt_{expected_code}_{expert_id}.txt"
                    if result_path.is_file():
                        result_text = result_path.read_text(encoding="utf-8")
                        fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', result_text, re.DOTALL)
                        try:
                            fm = yaml.safe_load(fm_match.group(1)) if fm_match else {}
                        except yaml.YAMLError:
                            fm = {}
                        expected_fm = {
                            "expert_id": expert_id, "ts_code": expected_code,
                            "data_date": expected_date, "analysis_date": expected_analysis,
                            "batch_id": data_batch,
                        }
                        for field, expected_value in expected_fm.items():
                            if str((fm or {}).get(field) or "") != expected_value:
                                errors.append(f"归档专家结果身份不匹配: {expert_id}.{field}")
                        if not is_legacy:
                            expert_problems = validate_expert(
                                expected_code, expert_id, expected_date, data_batch,
                                base_dir=manifest_path.parent,
                            )
                            if expert_problems:
                                errors.append(
                                    f"归档专家结果未通过契约: {expert_id}: "
                                    f"{expert_problems[:3]}"
                                )
                    if prompt_path.is_file():
                        prompt_text = prompt_path.read_text(encoding="utf-8")
                        if expected_code not in prompt_text or expert_id not in prompt_text or data_batch not in prompt_text:
                            errors.append(f"归档专家 prompt 身份不匹配: {expert_id}")
                    if not is_legacy:
                        challenge_problems = validate_challenge(
                            expected_code, expert_id, base_dir=manifest_path.parent,
                        )
                        if challenge_problems:
                            errors.append(
                                f"归档质询结果未通过契约: {expert_id}: "
                                f"{challenge_problems[:3]}"
                            )
                prompt_paths = {
                    f"invest_prompt_{expected_code}_{expert_id}.txt":
                    manifest_path.parent / f"invest_prompt_{expected_code}_{expert_id}.txt"
                    for expert_id in EXPERTS
                }
                if all(path.is_file() for path in prompt_paths.values()):
                    actual_prompt_hash = prompt_bundle_hash(
                        {name: path.read_bytes() for name, path in prompt_paths.items()},
                        str(data_batch or ""),
                    )
                    if meta.get("prompt_bundle_hash") != actual_prompt_hash:
                        errors.append("归档 prompt_bundle_hash 与实际 prompt 字节不一致")
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"归档数据快照不可读: {exc}")
        draft_path = manifest_path.parent / f"{expected_code}.draft.md"
        final_archive = manifest_path.parent / f"{expected_code}.md"
        if draft_path.is_file() and final_archive.is_file():
            draft_text = draft_path.read_text(encoding="utf-8")
            visible_draft = re.sub(r'<!--.*?-->', '', draft_text, flags=re.DOTALL)
            for expert_id in EXPERTS:
                result_path = manifest_path.parent / f"invest_result_{expected_code}_{expert_id}.md"
                if result_path.is_file():
                    result_text = result_path.read_text(encoding="utf-8")
                    if visible_draft.count(result_text) != 1:
                        errors.append(f"归档 draft 未唯一嵌入专家原文: {expert_id}")
                challenge_path = (
                    manifest_path.parent
                    / f"invest_challenge_result_{expected_code}_{expert_id}.md"
                )
                if challenge_path.is_file():
                    challenge_text = challenge_path.read_text(encoding="utf-8")
                    if visible_draft.count(challenge_text) != 1:
                        errors.append(f"归档 draft 未唯一嵌入质询原文: {expert_id}")
            declared_level3_match = re.search(
                r'^### 第三级触发评估\s*$\n+```yaml\s*\n(.*?)\n```',
                draft_text, re.MULTILINE | re.DOTALL,
            )
            try:
                declared_level3 = (
                    yaml.safe_load(declared_level3_match.group(1))
                    if declared_level3_match else None
                )
            except yaml.YAMLError:
                declared_level3 = None
            if declared_level3 != {"level3": archived_level3}:
                errors.append("归档 draft 三级触发评估与判定文件不一致")
            if archived_level3.get("triggered"):
                cross_path = manifest_path.parent / f"invest_cross_blind_{expected_code}.md"
                if cross_path.is_file():
                    cross_text = cross_path.read_text(encoding="utf-8")
                    if visible_draft.count(cross_text) != 1:
                        errors.append("归档 draft 未唯一嵌入有效的三方交叉盲审原文")
            marker = re.search(r'\n*<!--\s*artifact_manifest:[^>]+-->\s*$',
                               final_archive.read_text(encoding="utf-8"))
            final_without_marker = (
                final_archive.read_text(encoding="utf-8")[:marker.start()].rstrip()
                if marker else None
            )
            if final_without_marker != draft_path.read_text(encoding="utf-8").rstrip():
                errors.append("归档 final 去除 manifest 标记后与 draft 不一致")
    return {
        "status": "FAIL" if errors else "PASS",
        "report": str(report), "manifest": str(manifest_path), "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 invest-skill 归档 manifest")
    parser.add_argument("report_path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(args.report_path)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["status"] == "PASS":
        print(f"✓ manifest 验证通过: {result['manifest']}")
    else:
        for error in result["errors"]:
            print(f"✗ {error}", file=sys.stderr)
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
