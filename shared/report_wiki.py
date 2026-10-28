"""Strict client and bundle contract for the external invest-report-wiki project."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath

from shared.contracts import normalize_ts_code
from shared.project_config import (
    configured_path, project_config, report_wiki_cli, report_wiki_repo,
)


BUNDLE_SCHEMA_VERSION_V1 = "report-wiki.bundle.v1"
BUNDLE_SCHEMA_VERSION_V2 = "report-wiki.bundle.v2"
BUNDLE_SCHEMA_VERSION = BUNDLE_SCHEMA_VERSION_V2
SUPPORTED_BUNDLE_SCHEMAS = {BUNDLE_SCHEMA_VERSION_V1, BUNDLE_SCHEMA_VERSION_V2}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MIN_ANNUAL_PAGES = 20
MIN_ANNUAL_VISIBLE_CHARS = 10_000
MIN_SECTION_CHARS = 200


class ReportWikiError(RuntimeError):
    pass


def report_wiki_engine_files() -> dict[str, str]:
    """Return a portable source snapshot when the external engine has no VCS id."""
    root = report_wiki_repo().resolve()
    candidates = []
    for pattern in ("report_wiki/**/*.py", "bin/report-wiki", "pyproject.toml"):
        candidates.extend(root.glob(pattern))
    files = {}
    for path in sorted(set(candidates)):
        if path.is_file() and not path.is_symlink():
            files[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
    if not files:
        raise ReportWikiError(f"report-wiki 引擎源码快照为空: {root}")
    return files


def report_wiki_engine_hash(files: dict[str, str] | None = None) -> str:
    snapshot = files if files is not None else report_wiki_engine_files()
    digest = hashlib.sha256()
    for name in sorted(snapshot):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(snapshot[name].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def bundle_hash(bundle: dict) -> str:
    normalized = json.loads(json.dumps(bundle, ensure_ascii=False, allow_nan=False))
    normalized.pop("bundle_hash", None)
    return hashlib.sha256(canonical_json(normalized)).hexdigest()


def expected_fiscal_years(as_of: datetime, years: int) -> list[str]:
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 20:
        raise ValueError("years 必须是 1-20 的整数")
    end_year = as_of.year - 1 if as_of.month >= 5 else as_of.year - 2
    return [str(year) for year in range(end_year - years + 1, end_year + 1)]


def listing_aware_years(ts_code: str, as_of: datetime, default_years: int = 5) -> int:
    """上市不足 default_years 年的公司只要求上市以来应有的年报年度数。

    依据 invest_skill.db 的 stocks.list_date（Tushare 基础信息）计算：
    应有年报年度 = [max(listing_year, end_year - default_years + 1), end_year]，
    其中 end_year 为 as_of 的最近完整财报年度。上市前的年度（如 2022-06 上市的
    公司没有 2021 年报，巨潮在该代码下无档）不要求提供。

    无 list_date 或查询失败时回退 default_years（保持旧行为）；至少 1 年。
    """
    if isinstance(default_years, bool) or not isinstance(default_years, int) \
            or not 1 <= default_years <= 20:
        raise ValueError("default_years 必须是 1-20 的整数")
    listing_year: int | None = None
    try:
        import sqlite3
        db_override = os.environ.get("INVEST_DB_PATH")
        db_path = (
            Path(db_override).expanduser() if db_override
            else configured_path("db_file", "./data/invest_skill.db")
        )
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT list_date FROM stocks WHERE ts_code = ?", (ts_code,),
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            text = str(row[0])[:4]
            if text.isdigit():
                listing_year = int(text)
    except Exception:  # noqa: BLE001 —— 查询失败回退默认行为
        listing_year = None
    if listing_year is None:
        return default_years
    end_year = as_of.year - 1 if as_of.month >= 5 else as_of.year - 2
    years = end_year - listing_year + 1
    if years >= default_years:
        return default_years
    return max(1, years)


def _visible_chars(text: str) -> int:
    return len(re.findall(r"[\w\u4e00-\u9fff]", text))


def _safe_relative_source_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def validate_report_bundle(
    bundle: object,
    *,
    ts_code: str,
    as_of: datetime,
    years: int,
    report_types: tuple[str, ...] = ("annual",),
    semi_years: int = 1,
) -> list[str]:
    problems: list[str] = []
    code = normalize_ts_code(ts_code)
    expected_years = expected_fiscal_years(as_of, years)
    expected_types = sorted(set(report_types))
    if not expected_types or not set(expected_types) <= {"annual", "semi"}:
        problems.append(f"report_types 非法: {expected_types!r}")
    if "semi" in expected_types and (
        isinstance(semi_years, bool) or not isinstance(semi_years, int)
        or semi_years < 1
    ):
        problems.append("semi_years 必须是正整数")
    if not isinstance(bundle, dict):
        return ["report-wiki bundle 不是 JSON 对象"]
    schema_version = bundle.get("schema_version")
    if schema_version not in SUPPORTED_BUNDLE_SCHEMAS:
        problems.append(f"schema_version 非法: {schema_version!r}")
    is_v2 = schema_version == BUNDLE_SCHEMA_VERSION_V2
    if bundle.get("status") != "PASS":
        problems.append(f"bundle status 未通过: {bundle.get('status')!r}")
    if bundle.get("ts_code") != code:
        problems.append(f"bundle ts_code 不匹配: {bundle.get('ts_code')!r} != {code}")
    as_of_text = as_of.strftime("%Y%m%d")
    if str(bundle.get("as_of") or "") != as_of_text:
        problems.append(f"bundle as_of 不匹配: {bundle.get('as_of')!r} != {as_of_text}")
    if bundle.get("requested_years") != expected_years:
        problems.append(
            f"requested_years 不完整/不一致: {bundle.get('requested_years')!r} "
            f"!= {expected_years!r}"
        )
    declared_types = bundle.get("report_types")
    if not isinstance(declared_types, list) or declared_types != expected_types:
        problems.append(f"report_types 不一致: {declared_types!r} != {expected_types!r}")
    declared_periods = bundle.get("requested_periods")
    if not isinstance(declared_periods, list):
        if "semi" in expected_types:
            problems.append("semi bundle 必须声明 requested_periods")
        declared_periods = [f"annual:{year}" for year in expected_years]
    annual_periods = [f"annual:{year}" for year in expected_years]
    if [item for item in declared_periods if str(item).startswith("annual:")] != annual_periods:
        problems.append("requested_periods 的年度报告集合不完整")
    semi_periods = [item for item in declared_periods if str(item).startswith("semi:")]
    if "semi" in expected_types:
        if not semi_periods or len(semi_periods) > semi_years:
            problems.append(
                f"requested_periods 半年度数量非法: {len(semi_periods)}（上限 {semi_years}）"
            )
        if any(not re.fullmatch(r"semi:\d{4}H1", str(item)) for item in semi_periods):
            problems.append(f"requested_periods 含非法半年度期次: {semi_periods!r}")
    elif semi_periods:
        problems.append("annual-only bundle 不得含半年度期次")
    declared_hash = bundle.get("bundle_hash")
    try:
        computed_hash = bundle_hash(bundle)
    except (TypeError, ValueError) as exc:
        problems.append(f"bundle 不是严格 JSON: {exc}")
        computed_hash = ""
    if not isinstance(declared_hash, str) or not SHA256_RE.fullmatch(declared_hash):
        problems.append("bundle_hash 缺失或非法")
    elif declared_hash != computed_hash:
        problems.append(f"bundle_hash 重算不一致: {declared_hash} != {computed_hash}")
    if not SHA256_RE.fullmatch(str(bundle.get("corpus_hash") or "")):
        problems.append("corpus_hash 缺失或非法")
    if bundle.get("missing") != []:
        problems.append(f"bundle 存在覆盖缺口: {bundle.get('missing')!r}")
    if not isinstance(bundle.get("warnings"), list):
        problems.append("warnings 必须是列表")

    sage = bundle.get("sage")
    if not isinstance(sage, dict):
        problems.append("sage 状态缺失")
    else:
        workspace = str(sage.get("workspace") or "")
        if not _safe_relative_source_path(workspace):
            problems.append(f"sage.workspace 非安全相对路径: {workspace!r}")
        if not str(sage.get("engine_version") or "").strip():
            problems.append("sage.engine_version 缺失")
        if not is_v2:
            expected_sage = {
                "status": "compiled",
                "coverage_status": "PASS",
                "provenance_status": "PASS",
            }
            for field, expected in expected_sage.items():
                if sage.get(field) != expected:
                    problems.append(f"sage.{field} 未通过: {sage.get(field)!r}")

    if is_v2:
        if bundle.get("evidence_status") != "PASS":
            problems.append(
                f"evidence_status 未通过: {bundle.get('evidence_status')!r}"
            )
        if bundle.get("summary_status") not in {"PASS", "UNAVAILABLE"}:
            problems.append(
                f"summary_status 非法: {bundle.get('summary_status')!r}"
            )
        search = bundle.get("search")
        if not isinstance(search, dict):
            problems.append("search 状态缺失")
        else:
            for field, expected in {
                "status": "PASS",
                "engine": "sqlite-fts5-bm25",
                "schema_version": "report-wiki.search.v2",
                "path": "evidence/search.sqlite3",
            }.items():
                if search.get(field) != expected:
                    problems.append(
                        f"search.{field} 未通过: {search.get(field)!r}"
                    )
            if not SHA256_RE.fullmatch(str(search.get("content_hash") or "")):
                problems.append("search.content_hash 缺失或非法")
            for field in ("document_count", "page_count"):
                value = search.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    problems.append(f"search.{field} 缺失或非法")

    reports = bundle.get("reports")
    if not isinstance(reports, list):
        problems.append("reports 必须是列表")
        reports = []
    expected_keys: list[tuple[str, str]] = []
    for period in declared_periods:
        text = str(period)
        if ":" not in text:
            problems.append(f"requested_periods 非法: {text!r}")
            continue
        report_type, fiscal_year = text.split(":", 1)
        expected_keys.append((fiscal_year, report_type))
    actual_keys: list[tuple[str, str]] = []
    seen_source_hashes: set[str] = set()
    for index, report in enumerate(reports):
        label = f"reports[{index}]"
        if not isinstance(report, dict):
            problems.append(f"{label} 不是对象")
            continue
        fiscal_year = str(report.get("fiscal_year") or "")
        report_type = str(report.get("report_type") or "")
        actual_keys.append((fiscal_year, report_type))
        announcement = str(report.get("announcement_date") or "")
        if not re.fullmatch(r"\d{8}", announcement):
            problems.append(f"{label}.announcement_date 非法: {announcement!r}")
        else:
            try:
                datetime.strptime(announcement, "%Y%m%d")
            except ValueError:
                problems.append(f"{label}.announcement_date 不是有效日期")
            if announcement > as_of_text:
                problems.append(f"{label}.announcement_date 晚于分析时点")
            period_end = (
                f"{fiscal_year[:4]}0630"
                if report_type == "semi" and len(fiscal_year) >= 4
                else (f"{fiscal_year}1231" if fiscal_year else "")
            )
            if period_end and announcement <= period_end:
                problems.append(f"{label}.announcement_date 早于报告期结束")
        title = str(report.get("title") or "").strip()
        year_text = fiscal_year[:4] if len(fiscal_year) >= 4 else fiscal_year
        if not title:
            problems.append(f"{label}.title 缺失")
        elif year_text and year_text not in title:
            problems.append(f"{label}.title 未包含财务年度 {year_text}")
        elif report_type == "semi" and "半年度报告" not in title:
            problems.append(f"{label}.title 不是完整半年度报告")
        elif report_type == "annual" and "年度报告" not in title:
            problems.append(f"{label}.title 不是完整年度报告")
        if not str(report.get("source_url") or "").startswith(("https://", "http://")):
            problems.append(f"{label}.source_url 非 HTTP(S)")
        source_path = report.get("source_path")
        if not _safe_relative_source_path(source_path):
            problems.append(f"{label}.source_path 非安全相对路径")
        elif not str(source_path).startswith(f"raw/{report_type}/{fiscal_year}/"):
            problems.append(f"{label}.source_path 不符合年度原件目录契约")
        source_hash = str(report.get("source_sha256") or "")
        if not SHA256_RE.fullmatch(source_hash):
            problems.append(f"{label}.source_sha256 非法")
        elif source_hash in seen_source_hashes:
            problems.append(f"{label}.source_sha256 与其他年度重复")
        seen_source_hashes.add(source_hash)
        source_bytes = report.get("source_bytes")
        if (isinstance(source_bytes, bool) or not isinstance(source_bytes, int)
                or source_bytes < 10_000):
            problems.append(f"{label}.source_bytes 低于 10000")
        page_count = report.get("page_count")
        if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < MIN_ANNUAL_PAGES:
            problems.append(f"{label}.page_count 低于 {MIN_ANNUAL_PAGES}")
            page_count = 0
        if report.get("provenance_level") != "page-exact":
            problems.append(f"{label}.provenance_level 不是 page-exact")
        if is_v2:
            for field in (
                "evidence_build_id", "document_sha256", "sections_sha256",
                "evidence_rules_hash",
            ):
                if not SHA256_RE.fullmatch(str(report.get(field) or "")):
                    problems.append(f"{label}.{field} 缺失或非法")
            for field, expected in (
                ("document_path", f"evidence/{report_type}/{fiscal_year}/document.json"),
                ("pages_path", f"evidence/{report_type}/{fiscal_year}/pages"),
            ):
                value = report.get(field)
                if value != expected or not _safe_relative_source_path(value):
                    problems.append(f"{label}.{field} 不符合本地证据路径契约")
            parser = report.get("parser")
            if not isinstance(parser, dict) or not str(parser.get("engine") or ""):
                problems.append(f"{label}.parser 缺失或非法")
            elif not isinstance(parser.get("versions"), dict):
                problems.append(f"{label}.parser.versions 缺失或非法")
            ocr = parser.get("ocr") if isinstance(parser, dict) else None
            if not isinstance(ocr, dict) or ocr.get("status") not in {
                "not-required", "applied",
            }:
                problems.append(f"{label}.parser.ocr 状态非法")
            if report.get("sage_source_status") not in {"generated", "compiled"}:
                problems.append(f"{label}.sage_source_status 非法")
            if not str(report.get("downloaded_at") or "").strip():
                problems.append(f"{label}.downloaded_at 缺失")
        elif report.get("sage_source_status") != "compiled":
            problems.append(f"{label}.sage_source_status 未编译")
        sections = report.get("sections")
        if not isinstance(sections, list) or not sections:
            problems.append(f"{label}.sections 为空")
            continue
        seen_sections: set[str] = set()
        full_text_parts: list[str] = []
        for section_index, section in enumerate(sections):
            section_label = f"{label}.sections[{section_index}]"
            if not isinstance(section, dict):
                problems.append(f"{section_label} 不是对象")
                continue
            name = str(section.get("name") or "").strip()
            text = str(section.get("text") or "")
            if not name:
                problems.append(f"{section_label}.name 缺失")
            elif name in seen_sections:
                problems.append(f"{label} 章节重复: {name}")
            seen_sections.add(name)
            if len(text.strip()) < MIN_SECTION_CHARS:
                problems.append(f"{section_label}.text 少于 {MIN_SECTION_CHARS} 字符")
            full_text_parts.append(text)
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if section.get("text_sha256") != text_hash:
                problems.append(f"{section_label}.text_sha256 重算不一致")
            page_start = section.get("page_start")
            page_end = section.get("page_end")
            valid_pages = all(
                not isinstance(value, bool) and isinstance(value, int)
                for value in (page_start, page_end)
            )
            if (not valid_pages or page_start < 1 or page_start > page_end
                    or (page_count and page_end > page_count)):
                problems.append(f"{section_label} 页码非法: {page_start!r}-{page_end!r}")
        if is_v2:
            sections_identity = {
                "sections": [
                    {
                        "name": item.get("name"),
                        "text_sha256": item.get("text_sha256"),
                        "page_start": item.get("page_start"),
                        "page_end": item.get("page_end"),
                    }
                    for item in sections if isinstance(item, dict)
                ]
            }
            expected_sections_hash = hashlib.sha256(
                canonical_json(sections_identity)
            ).hexdigest()
            if report.get("sections_sha256") != expected_sections_hash:
                problems.append(f"{label}.sections_sha256 重算不一致")
        if not any(
            marker in name
            for name in seen_sections
            for marker in ("管理层讨论与分析", "经营情况讨论与分析")
        ):
            problems.append(f"{label} 缺少管理层/经营情况讨论章节")
        if not any("风险" in name for name in seen_sections):
            problems.append(f"{label} 缺少风险章节")
        if _visible_chars("\n".join(full_text_parts)) < MIN_ANNUAL_VISIBLE_CHARS:
            problems.append(
                f"{label} 关键章节可见正文低于 {MIN_ANNUAL_VISIBLE_CHARS} 字符"
            )
    if actual_keys != expected_keys:
        problems.append(f"reports 年度/类型集合或排序不一致: {actual_keys!r} != {expected_keys!r}")
    if is_v2 and isinstance(reports, list):
        identity: dict[str, dict] = {}
        for report in reports:
            if not isinstance(report, dict):
                continue
            fiscal_year = str(report.get("fiscal_year") or "")
            report_type = str(report.get("report_type") or "annual")
            key = fiscal_year if report_type == "annual" else f"{report_type}:{fiscal_year}"
            identity[key] = {
                "source_sha256": report.get("source_sha256"),
                "document_sha256": report.get("document_sha256"),
                "sections_sha256": report.get("sections_sha256"),
                "build_id": report.get("evidence_build_id"),
                "report_type": report_type,
            }
        expected_corpus_hash = hashlib.sha256(canonical_json(identity)).hexdigest()
        if bundle.get("corpus_hash") != expected_corpus_hash:
            problems.append("corpus_hash 与 reports 证据身份重算不一致")
    return problems


def rows_from_bundle(bundle: dict) -> list[tuple[str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str]] = []
    # Bundle 固定按年度升序，消费视图按最新年度优先，避免 prompt 预算先耗在旧年。
    for report in reversed(bundle["reports"]):
        for section in report["sections"]:
            rows.append((
                str(report["fiscal_year"]), str(report["report_type"]),
                str(section["name"]), str(section["text"]),
                str(report["announcement_date"]), str(report["title"]),
            ))
    return rows


def render_annual_text(bundle: dict) -> str:
    parts = []
    for year, report_type, section, text, announcement, title in rows_from_bundle(bundle):
        display_year = year[:4] if report_type == "semi" else year
        parts.append(
            f"\n### {display_year}年 {report_type}（公告日：{announcement}，标题：{title}）\n"
            f"#### {section}\n{text}\n"
        )
    return "\n".join(parts)


def materialize_report_bundle(
    ts_code: str,
    *,
    as_of: datetime,
    years: int,
    output: Path,
    refresh: bool = False,
    report_types: tuple[str, ...] = ("annual",),
    semi_years: int = 1,
) -> dict:
    code = normalize_ts_code(ts_code)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fixture = os.environ.get("INVEST_REPORT_WIKI_FIXTURE")
    if fixture and os.environ.get("INVEST_TEST_MODE") == "1":
        source = Path(fixture).expanduser().resolve()
        try:
            bundle = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReportWikiError(f"report-wiki 测试 fixture 无法解析: {exc}") from exc
        problems = validate_report_bundle(
            bundle, ts_code=code, as_of=as_of, years=years,
            report_types=report_types, semi_years=semi_years,
        )
        if problems:
            raise ReportWikiError(
                "report-wiki 测试 fixture 门禁失败: " + "; ".join(problems[:20])
            )
        temp_output = output.with_name(f".{output.name}.{os.getpid()}.fixture")
        temp_output.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_output, output)
        return bundle

    cli = report_wiki_cli()
    project = report_wiki_repo()
    if not project.is_dir():
        raise ReportWikiError(
            f"report-wiki 项目未就绪: {project}；请先在该目录按 AGENTS.md 完成实现"
        )
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise ReportWikiError(f"report-wiki CLI 不存在或不可执行: {cli}")
    materialized = output.with_name(f".{output.name}.{os.getpid()}.materialize")
    materialized.unlink(missing_ok=True)
    command = [
        str(cli), "materialize", "--code", code,
        "--as-of", as_of.strftime("%Y%m%d"), "--years", str(years),
        "--report-types", ",".join(report_types),
        "--semi-years", str(semi_years), "--output", str(materialized),
        "--evidence-only",
    ]
    if refresh:
        command.append("--refresh")
    timeout = int(project_config().get("report_wiki", {}).get(
        "materialize_timeout_seconds", 1800
    ))
    try:
        try:
            result = subprocess.run(
                command, cwd=str(project), capture_output=True, text=True,
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReportWikiError(
                f"report-wiki materialize 超时（{exc.timeout} 秒）"
            ) from exc
        if result.returncode != 0:
            detail = result.stderr.strip()[-2000:] or result.stdout.strip()[-2000:]
            raise ReportWikiError(
                f"report-wiki materialize 失败(exit={result.returncode}): {detail}"
            )
        if not materialized.is_file():
            raise ReportWikiError(f"report-wiki 未生成 bundle: {materialized}")
        try:
            bundle = json.loads(materialized.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReportWikiError(f"report-wiki bundle 无法解析: {exc}") from exc
        problems = validate_report_bundle(
            bundle, ts_code=code, as_of=as_of, years=years,
            report_types=report_types, semi_years=semi_years,
        )
        if problems:
            raise ReportWikiError(
                "report-wiki bundle 门禁失败: " + "; ".join(problems[:20])
            )
        os.replace(materialized, output)
        return bundle
    finally:
        materialized.unlink(missing_ok=True)
