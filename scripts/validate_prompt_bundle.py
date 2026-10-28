#!/usr/bin/env python3
"""在启动专家前校验数据、年报与 7 份 prompt 的批次一致性。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from shared.batch_contract import validate_batch_metadata
from shared.contracts import batch_contract_paths, normalize_ts_code, snapshot_identity
from shared.report_wiki import (
    render_annual_text, report_wiki_engine_files, report_wiki_engine_hash,
    validate_report_bundle,
)
from shared.runtime import RUNTIME_ROOT
from shared.project_config import project_config, wiki_expert_root
from scripts.prepare_prompts import MAX_EXPERT_PROMPT_BYTES

WIKI_ROOT = wiki_expert_root()
CHECKLIST_PATH = SKILL_ROOT / "data" / "expert_checklist.json"
EVIDENCE_RULES_PATH = SKILL_ROOT / "data" / "checklist_evidence_rules.json"
EXPERTS_PATH = SKILL_ROOT / "data" / "experts.json"
PREPARE_PATH = SKILL_ROOT / "scripts" / "prepare_prompts.py"
REPORT_WIKI_CONTRACT_PATH = SKILL_ROOT / "shared" / "report_wiki.py"
SAGE_WIKI_CONTRACT_PATH = SKILL_ROOT / "shared" / "sage_wiki.py"
EXPERT_V3_CONTRACT_PATH = SKILL_ROOT / "shared" / "expert_result_v3.py"
EXPERT_V3_SCHEMA_PATH = SKILL_ROOT / "data" / "expert_result_v3.schema.json"


def validate_bundle(ts_code: str, tmp_root: Path = RUNTIME_ROOT) -> list[str]:
    data_path = tmp_root / f"invest_data_{ts_code}.json"
    annual_path = tmp_root / f"invest_annual_{ts_code}.txt"
    report_bundle_path = tmp_root / f"invest_report_bundle_{ts_code}.json"
    problems: list[str] = []
    if not data_path.is_file():
        return [f"数据快照缺失: {data_path}"]
    if not annual_path.is_file():
        return [f"年报快照缺失: {annual_path}"]
    if not report_bundle_path.is_file():
        return [f"report-wiki 证据包缺失: {report_bundle_path}"]
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"数据快照无法解析: {exc}"]
    annual = annual_path.read_text(encoding="utf-8")
    try:
        report_bundle = json.loads(report_bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"report-wiki 证据包无法解析: {exc}"]
    data_date, batch_id = snapshot_identity(data)
    meta = data.get("meta", {})
    analysis_date = str(meta.get("analysis_date") or "")
    if not data_date or not batch_id or not analysis_date:
        problems.append("数据快照缺少 data_date/batch_id/analysis_date")
    try:
        as_of = dt.datetime.strptime(analysis_date, "%Y%m%d")
        report_years = int(
            meta.get("report_history_years")
            or project_config().get("report_wiki", {}).get("history_years", 5)
        )
        report_types = tuple(meta.get("report_types") or ["annual"])
        semi_years = int(meta.get("report_semi_years") or 1)
    except (TypeError, ValueError):
        problems.append("analysis_date 或 report_wiki.history_years 非法")
    else:
        problems.extend(validate_report_bundle(
            report_bundle,
            ts_code=ts_code,
            as_of=as_of,
            years=report_years,
            report_types=report_types,
            semi_years=semi_years,
        ))
        if annual != render_annual_text(report_bundle):
            problems.append("年报全文快照与 report-wiki 证据包渲染结果不一致")
        for field, expected in (
            ("report_bundle_hash", report_bundle.get("bundle_hash")),
            ("report_corpus_hash", report_bundle.get("corpus_hash")),
            ("report_wiki_schema", report_bundle.get("schema_version")),
            ("report_evidence_status", report_bundle.get("evidence_status", "PASS")),
            ("report_summary_status", report_bundle.get("summary_status", "PASS")),
            ("report_search_content_hash", report_bundle.get("search", {}).get("content_hash")),
            ("report_history_years", report_years),
            ("report_types", list(report_types)),
        ):
            if meta.get(field) != expected:
                problems.append(
                    f"meta.{field} 与 report-wiki 证据包不一致: "
                    f"{meta.get(field)!r} != {expected!r}"
                )
        report_rows = [item for item in (report_bundle.get("reports") or []) if isinstance(item, dict)]
        if not report_rows:
            problems.append("report-wiki 未返回财报，最新披露完整性不可证明")
        else:
            latest = max(
                report_rows,
                key=lambda item: (
                    str(item.get("announcement_date") or ""),
                    str(item.get("fiscal_year") or ""),
                ),
            )
            disclosure_expected = {
                "disclosure_query_status": "PASS",
                "disclosure_query_as_of": report_bundle.get("as_of"),
                "latest_report_period": latest.get("fiscal_year"),
                "latest_report_type": latest.get("report_type"),
                "latest_report_announcement_date": latest.get("announcement_date"),
                "market_query_trade_date": data_date,
            }
            for field, expected in disclosure_expected.items():
                if meta.get(field) != expected:
                    problems.append(f"meta.{field} 最新披露/行情水位不一致")
        try:
            completed = dt.datetime.fromisoformat(str(meta.get("disclosure_query_completed_at") or ""))
            if completed.tzinfo is None or completed > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
                raise ValueError
        except (TypeError, ValueError):
            problems.append("meta.disclosure_query_completed_at 缺失或非法")
        try:
            engine_files = report_wiki_engine_files()
            if (meta.get("report_wiki_engine_hash") != report_wiki_engine_hash(engine_files)
                    or meta.get("report_wiki_engine_file_count") != len(engine_files)):
                problems.append("report-wiki 引擎在 prepare 后发生变化，必须重建批次")
        except (OSError, ValueError, RuntimeError) as exc:
            problems.append(f"report-wiki 引擎身份不可验证: {exc}")

    experts = [
        item["id"] for item in
        json.loads(EXPERTS_PATH.read_text(encoding="utf-8"))["experts"]
    ]
    prompts: dict[str, str] = {}
    identity_pattern = re.compile(
        r'(?mi)^batch_id\s*:\s*["\']?([0-9a-f]{16,64})["\']?\s*$'
    )
    for expert_id in experts:
        path = tmp_root / f"invest_prompt_{ts_code}_{expert_id}.txt"
        if not path.is_file() or not path.stat().st_size:
            problems.append(f"prompt 缺失/为空: {path}")
            continue
        text = path.read_text(encoding="utf-8")
        if path.stat().st_size > MAX_EXPERT_PROMPT_BYTES:
            problems.append(
                f"{path.name} 体积 {path.stat().st_size} > {MAX_EXPERT_PROMPT_BYTES} bytes"
            )
        prompts[path.name] = text
        identities = identity_pattern.findall(text)
        if identities != [batch_id]:
            problems.append(
                f"{path.name} batch_id 不唯一/不一致: {identities!r} != {[batch_id]!r}"
            )
        expected_lines = {
            "expert_id": expert_id,
            "ts_code": ts_code,
            "data_date": data_date,
            "analysis_date": analysis_date,
        }
        for field, expected in expected_lines.items():
            values = re.findall(
                rf'(?mi)^{re.escape(field)}\s*:\s*["\']?([^"\'\n]+)["\']?\s*$',
                text,
            )
            if values != [expected]:
                problems.append(
                    f"{path.name} {field} 不唯一/不一致: {values!r} != {[expected]!r}"
                )

    if len(prompts) == len(experts):
        problems.extend(validate_batch_metadata(
            data, annual, WIKI_ROOT,
            batch_contract_paths(SKILL_ROOT),
            prompts,
        ))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 invest-skill prompt bundle")
    parser.add_argument("ts_code")
    args = parser.parse_args()
    try:
        code = normalize_ts_code(args.ts_code)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    problems = validate_bundle(code)
    if problems:
        for problem in problems:
            print(f"✗ {problem}", file=sys.stderr)
        return 2
    print(f"✓ prompt bundle PASS: {code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
