#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收集 7 位专家的结果，统一解析 frontmatter 并校验。

用法：
    python3 scripts/collect_results.py <code>            # JSON 摘要输出到 stdout
    python3 scripts/collect_results.py <code> --json     # 同时写入 /tmp/invest_results_<code>.json
    python3 scripts/collect_results.py <code> --check    # 逐专家校验并打印报告；全部通过 exit 0，否则 exit 1
    python3 scripts/collect_results.py <code> --failing  # 仅打印未通过校验的专家 ID（每行一个）；
                                                         # 全部通过时无输出；exit 0/1 语义同 --check
    python3 scripts/collect_results.py <code> --failing --json
                                                       # 向 stdout 输出纯 JSON：problems + 完整 diagnostics

校验项（--check / --failing）：
    1. 结果文件存在且非空
    2. frontmatter 可解析，expert_id 与文件对应
    3. score 为 0-100 的整数
    4. verdict ∈ {PASS, WARN, VETO}；verdict=VETO 时 veto_triggers 非空
    5. data_date 与 /tmp/invest_data_<code>.json 的 market.trade_date 一致（防陈旧结果污染）
"""
import argparse
from functools import lru_cache
import json
import re
import sys
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))
from shared.checklist_verify import check_expert_coverage, load_checklist
from shared.contracts import normalize_ts_code, snapshot_identity
from shared.project_config import legacy_wiki_repo, sage_wiki_repo, wiki_expert_root
from shared.runtime import RUNTIME_ROOT
from shared.expert_result_v3 import (
    SCHEMA_VERSION as EXPERT_RESULT_V3,
    ExpertResultV3Error,
    canonical_bytes as canonical_v3_bytes,
    knowledge_paths_from_prompt,
    parse_result as parse_v3_result,
    render_markdown as render_v3_markdown,
    validate_result as validate_v3_result,
)
from scripts.verify_report import (
    calculation_specs, evaluate_calculation, explicit_sources, extract_numbers,
    detect_qualitative_contradictions, detect_unsourced, flatten_json, flatten_paths,
    verify_number,
)
WIKI_ROOT = wiki_expert_root()
WIKI_REPO = sage_wiki_repo()
LEGACY_WIKI_REPO = legacy_wiki_repo()

EXPERTS = [
    item["id"] for item in
    json.loads((SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8"))["experts"]
]

VALID_VERDICTS = {"PASS", "WARN", "VETO"}

DIAGNOSTIC_CATEGORIES = (
    "invalid_sources",
    "invalid_calculations",
    "invalid_checklist_evidence",
    "out_of_domain_checklist_evidence",
    "qualitative_contradictions",
    "unsourced_claims",
    "untraced_numbers",
)

EXPERT_ALLOWED_PREFIXES = {
    "financial-auditor": ("annual.", "quarterly.", "balance.", "indicators.", "audit.", "forecast.", "industry."),
    "value-valuator": ("market.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "macro.", "forecast.", "data_quality.", "meta."),
    "growth-assessor": ("market.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "forecast.", "data_quality.", "meta."),
    "moat-analyst": ("market.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "forecast.", "data_quality.", "meta."),
    "cognitive-controller": ("market.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "forecast.", "data_quality.", "meta."),
    "macro-cyclist": ("macro.", "market.", "industry.", "annual.", "quarterly.", "forecast.", "data_quality.", "meta."),
    "management-auditor": ("stock_info.", "market.", "audit.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "forecast.", "data_quality.", "meta."),
}


def parse_frontmatter(text: str) -> dict:
    """解析 frontmatter，兼容裸 YAML、```yaml 包裹、以及 frontmatter 前有说明文字的情况。"""
    if not text:
        return {}

    # agent 有时会在 frontmatter 前输出说明性文字；允许 frontmatter 出现在前 10 行内
    lines = text.split("\n")
    if lines[0].strip() != "---":
        for i, line in enumerate(lines[:10]):
            if line.strip() == "---":
                text = "\n".join(lines[i:])
                break

    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass

    clean = re.sub(r'```yaml\s*\n', '', text)
    clean = re.sub(r'\n```\s*\n', '\n', clean)
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', clean, re.DOTALL)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass

    return {}


def result_path(ts_code: str, expert_id: str, base_dir: Path = RUNTIME_ROOT) -> Path:
    return base_dir / f"invest_result_{ts_code}_{expert_id}.md"


def expected_data_date(ts_code: str) -> str | None:
    """从数据文件读取数据基准日；文件缺失或字段缺失时返回 None。"""
    data_file = RUNTIME_ROOT / f"invest_data_{ts_code}.json"
    if not data_file.exists():
        return None
    try:
        d = json.loads(data_file.read_text(encoding="utf-8"))
        v = d.get("market", {}).get("trade_date")
        return str(v) if v else None
    except Exception:
        return None


def expected_batch_id(ts_code: str) -> str | None:
    data_file = RUNTIME_ROOT / f"invest_data_{ts_code}.json"
    if not data_file.exists():
        return None
    try:
        _, batch_id = snapshot_identity(json.loads(data_file.read_text(encoding="utf-8")))
        return batch_id
    except Exception:
        return None


def _meaningful_table_rows(text: str, heading: str) -> int:
    start = text.find(heading)
    if start < 0:
        return 0
    body = text[start + len(heading):]
    next_heading = re.search(r'^##\s+', body, re.MULTILINE)
    if next_heading:
        body = body[:next_heading.start()]
    placeholders = ("待填写", "页面路径", "管理层论述（年报章节+原文摘录）")
    rows = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or re.match(r'^\|[\s:|-]+\|$', stripped):
            continue
        if any(marker in stripped for marker in placeholders):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) >= 3 and cells[0] not in {"#", "必检项"}:
            rows.append(stripped)
    return len(rows)


@lru_cache(maxsize=512)
def _wiki_path_exists(raw: str) -> bool:
    value = raw.strip().strip('`').removeprefix('wiki:').strip()
    wikilink = re.fullmatch(r'\[\[([^]|]+)(?:\|[^]]+)?\]\]', value)
    if wikilink:
        value = wikilink.group(1).strip()
    markdown_link = re.fullmatch(r'\[[^]]+\]\(([^)]+)\)', value)
    if markdown_link:
        value = markdown_link.group(1).strip()
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    for root in (WIKI_REPO, WIKI_ROOT, LEGACY_WIKI_REPO):
        candidate = root / relative
        if candidate.is_file() or (
            not candidate.suffix and candidate.with_suffix(".md").is_file()
        ):
            return True
    # 兼容旧结果中的唯一 wikilink 标题；同名页面不唯一时拒绝猜测。
    if "/" not in value:
        page_name = relative.stem
        matches = sorted({
            *WIKI_REPO.rglob(f"{page_name}.md"),
            *LEGACY_WIKI_REPO.rglob(f"{page_name}.md"),
        })
        return len(matches) == 1
    return False


def _is_table_ordinal(value: str) -> bool:
    return bool(re.fullmatch(r'(?:\d+|[一二三四五六七八九十]+)', value.strip()))


def _annual_locator_exists(raw: str, annual_text: str) -> bool:
    return _annual_locator_section_text(raw, annual_text) is not None


def _annual_block_text(raw: str, annual_text: str) -> str | None:
    match = re.fullmatch(r'年报:(\d{4})/([^/\s；;、`]+)/([^|`；;\n]+)', raw.strip())
    if not match:
        return None
    year, report_type, _ = (part.strip() for part in match.groups())
    blocks = re.split(r'(?=^###\s+\d{4}年\s+)', annual_text, flags=re.MULTILINE)
    matched = [
        block for block in blocks
        if re.search(
            rf'^###\s+{re.escape(year)}年\s+{re.escape(report_type)}\b',
            block, re.MULTILINE,
        )
    ]
    return "\n".join(matched) if matched else None


def _annual_locator_section_text(raw: str, annual_text: str) -> str | None:
    match = re.fullmatch(r'年报:(\d{4})/([^/\s；;、`]+)/([^|`；;\n]+)', raw.strip())
    if not match:
        return None
    year, report_type, section = (part.strip() for part in match.groups())
    quoted_section = re.search(r'[“"]([^”"]+)[”"]', section)
    if quoted_section:
        section = quoted_section.group(1).strip()
    section = re.sub(r'^第[^\s“"]{0,12}节', '', section).strip('“”";;、 ')
    blocks = re.split(r'(?=^###\s+\d{4}年\s+)', annual_text, flags=re.MULTILINE)
    for block in blocks:
        if not re.search(
            rf'^###\s+{re.escape(year)}年\s+{re.escape(report_type)}\b',
            block, re.MULTILINE,
        ):
            continue
        section_match = re.search(
            rf'^####\s+[^\n]*{re.escape(section)}[^\n]*\n(.*?)(?=^####\s+|^###\s+|\Z)',
            block, re.MULTILINE | re.DOTALL,
        )
        if section_match:
            return section_match.group(1)
    return None


def _knowledge_log_existing_rows(text: str) -> int:
    start = text.find("## 知识检索日志")
    if start < 0:
        return 0
    heading_end = text.find('\n', start)
    body = text[heading_end + 1:] if heading_end >= 0 else ""
    next_heading = re.search(r'^##\s+', body, re.MULTILINE)
    if next_heading:
        body = body[:next_heading.start()]
    existing = set()
    for line in body.splitlines():
        if not line.strip().startswith('|'):
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) >= 2 and _is_table_ordinal(cells[0]) and _wiki_path_exists(cells[1]):
            existing.add(cells[1].strip().strip('`'))
    return len(existing)


def _verified_narrative_rows(text: str, annual_text: str, all_paths: set[str]) -> int:
    start = text.find("## 叙事–数据交叉验证")
    if start < 0:
        return 0
    heading_end = text.find('\n', start)
    body = text[heading_end + 1:] if heading_end >= 0 else ""
    later = re.search(r'^##\s+', body, re.MULTILINE)
    if later:
        body = body[:later.start()]
    signatures = set()
    for line in body.splitlines():
        if not re.match(r'^\|\s*(?:\d+|[一二三四五六七八九十]+)\s*\|', line.strip()):
            continue
        annual_locators = re.findall(r'年报:\d{4}/[^|`；;、\s]+/[^|`；;、\s）)]+', line)
        json_paths = [
            *explicit_sources(line),
            *(path for spec in calculation_specs(line) for path in spec.get("inputs", [])),
        ]
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        field_cell = cells[2] if len(cells) > 2 else ""
        quoted = re.findall(r'[“"]([^”"]+)[”"]', cells[1] if len(cells) > 1 else "")
        quote_chunks = [
            re.sub(r'[^\w\u4e00-\u9fff]', '', chunk)
            for quote in quoted for chunk in re.split(r'…+|\.{3,}', quote)
            if len(re.sub(r'[^\w\u4e00-\u9fff]', '', chunk)) >= 6
        ]
        annual_sections = [
            section for locator in annual_locators
            if (section := _annual_locator_section_text(locator, annual_text)) is not None
        ]
        annual_blocks = [
            block for locator in annual_locators
            if (block := _annual_block_text(locator, annual_text)) is not None
        ]
        quote_verified = any(
            chunk in re.sub(r'[^\w\u4e00-\u9fff]', '', section)
            for chunk in quote_chunks for section in annual_sections
        ) or any(
            chunk in re.sub(r'[^\w\u4e00-\u9fff]', '', block)
            for chunk in quote_chunks for block in annual_blocks
        )
        verified_paths = sorted(set(path for path in json_paths if path in all_paths))
        # “对应财务数据字段”必须明确写出证据路径，不能在另一列随意挂一个
        # 无关真路径来给叙事背书。
        field_bound = any(path in field_cell for path in verified_paths)
        if quote_verified and verified_paths and field_bound:
            signatures.add((
                tuple(sorted(set(annual_locators))),
                tuple(sorted(set(quote_chunks))),
                tuple(verified_paths),
            ))
    return len(signatures)


def trace_data_numbers(text: str, source_map: dict) -> list[dict]:
    """Return every data-number finding with its existing trace verdict."""
    return [
        verify_number(finding, source_map)
        for finding in extract_numbers(text)
        if finding.get("category") == "data"
    ]


def untraced_number_diagnostics(text: str, source_map: dict) -> list[dict]:
    """Return the complete, machine-readable list of untraced data numbers."""
    return [
        dict(item)
        for item in trace_data_numbers(text, source_map)
        if item.get("trace_status") == "UNTRACED"
    ]


def _empty_diagnostics() -> dict:
    return {category: [] for category in DIAGNOSTIC_CATEGORIES}


def _checklist_item_location(text: str, item_name: str) -> tuple[int | None, str]:
    pattern = re.compile(rf'^\|\s*{re.escape(item_name)}\s*\|', re.IGNORECASE)
    for line_no, line in enumerate(text.splitlines(), 1):
        if pattern.match(line.strip()):
            return line_no, line.strip()
    return None, ""


def build_expert_diagnostics(
    expert_id: str,
    text: str,
    data: dict,
    annual_text: str = "",
    *,
    checklist_result: dict | None = None,
    source_map: dict | None = None,
    all_paths: set[str] | None = None,
    checked_numbers: list[dict] | None = None,
) -> dict:
    """Build every enumerable expert-gate diagnostic without summary limits."""
    diagnostics = _empty_diagnostics()
    if checklist_result is None:
        checklist_result = check_expert_coverage(expert_id, text, load_checklist())
    if source_map is None:
        source_map = flatten_json(data)
    if all_paths is None:
        all_paths = flatten_paths(data)
    if checked_numbers is None:
        checked_numbers = trace_data_numbers(text, source_map)

    allowed_prefixes = EXPERT_ALLOWED_PREFIXES.get(expert_id, ())
    for item in checklist_result.get("items", []):
        if not item.get("found"):
            continue
        item_name = item["item"]
        evidence = item.get("evidence", "")
        line_no, context = _checklist_item_location(text, item_name)
        document_locators = re.findall(
            r'(?:年报|wiki):[^|`；;、\s]+(?:/[^|`；;、\s]+){0,2}',
            evidence, re.IGNORECASE,
        )
        invalid_document_locators = [
            locator for locator in document_locators
            if not (
                _wiki_path_exists(locator)
                if locator.lower().startswith("wiki:")
                else _annual_locator_exists(locator, annual_text)
            )
        ]
        if invalid_document_locators:
            diagnostics["invalid_checklist_evidence"].append({
                "item": item_name,
                "evidence": evidence,
                "line": line_no,
                "context": context,
                "invalid_document_locators": invalid_document_locators,
                "invalid_json_paths": [],
            })
        else:
            json_paths = re.findall(
                r'[A-Za-z_][\w-]*(?:\[\d+\])?(?:\.[A-Za-z_][\w-]*(?:\[\d+\])?)+',
                evidence,
            )
            invalid_json_paths = [path for path in json_paths if path not in all_paths]
            if invalid_json_paths:
                diagnostics["invalid_checklist_evidence"].append({
                    "item": item_name,
                    "evidence": evidence,
                    "line": line_no,
                    "context": context,
                    "invalid_document_locators": [],
                    "invalid_json_paths": invalid_json_paths,
                })

        evidence_paths = sorted(set(re.findall(
            r'[A-Za-z_][\w-]*(?:\[\d+\])?(?:\.[A-Za-z_][\w-]*(?:\[\d+\])?)+',
            evidence,
        )))
        out_of_domain_paths = [
            path for path in evidence_paths
            if allowed_prefixes and not path.startswith(allowed_prefixes)
        ]
        if evidence_paths and allowed_prefixes and out_of_domain_paths:
            diagnostics["out_of_domain_checklist_evidence"].append({
                "item": item_name,
                "evidence": evidence,
                "line": line_no,
                "context": context,
                "paths": evidence_paths,
                "out_of_domain_paths": out_of_domain_paths,
                "allowed_prefixes": list(allowed_prefixes),
            })

    for line_no, line in enumerate(text.splitlines(), 1):
        context = line.strip()
        for path in explicit_sources(line):
            if path not in all_paths:
                diagnostics["invalid_sources"].append({
                    "path": path,
                    "line": line_no,
                    "context": context,
                })
        for spec in calculation_specs(line):
            if evaluate_calculation(spec, source_map) is None:
                diagnostics["invalid_calculations"].append({
                    "formula": spec.get("formula", ""),
                    "inputs": list(spec.get("inputs", [])),
                    "line": line_no,
                    "context": context,
                })

    diagnostics["qualitative_contradictions"] = [
        dict(item) for item in detect_qualitative_contradictions(text, data)
    ]
    diagnostics["unsourced_claims"] = [
        dict(item) for item in detect_unsourced(text, source_map, annual_text)
    ]
    diagnostics["untraced_numbers"] = [
        dict(item) for item in checked_numbers
        if item.get("trace_status") == "UNTRACED"
    ]
    return diagnostics


def load_expert_diagnostics(ts_code: str, expert_id: str,
                            base_dir: Path = RUNTIME_ROOT) -> dict:
    """Load one expert's structured diagnostics without changing gate results."""
    path = result_path(ts_code, expert_id, base_dir)
    data_path = base_dir / f"invest_data_{ts_code}.json"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _empty_diagnostics()
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    annual_path = base_dir / f"invest_annual_{ts_code}.txt"
    annual_text = annual_path.read_text(encoding="utf-8") if annual_path.is_file() else ""
    return build_expert_diagnostics(expert_id, text, data, annual_text)


def validate_expert(ts_code: str, expert_id: str, exp_date: str | None,
                    exp_batch: str | None = None,
                    base_dir: Path = RUNTIME_ROOT) -> list[str]:
    """返回问题列表；空列表表示校验通过。"""
    problems = []
    path = result_path(ts_code, expert_id, base_dir)
    if not path.exists():
        return ["结果文件缺失"]
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return ["结果文件为空"]
    if len(text.strip()) < 1200:
        problems.append(f"正文过短: {len(text.strip())} 字符（至少 1200）")
    if not text.lstrip().startswith("---"):
        problems.append("frontmatter 前存在说明文字，文件必须直接以 --- 开头")
    if text.lstrip().startswith("```yaml"):
        problems.append("frontmatter 被代码块包裹")

    fm = parse_frontmatter(text)
    if not fm:
        return ["frontmatter 无法解析（需位于文件最开头，裸 YAML）"]

    if fm.get("expert_id") != expert_id:
        problems.append(f"expert_id 不匹配: {fm.get('expert_id')!r}")
    if fm.get("ts_code") != ts_code:
        problems.append(f"ts_code 不匹配: {fm.get('ts_code')!r} != {ts_code}")

    score = fm.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 100):
        problems.append(f"score 非法: {score!r}（需 0-100 整数）")

    verdict = fm.get("verdict")
    if verdict not in VALID_VERDICTS:
        problems.append(f"verdict 非法: {verdict!r}（需 PASS/WARN/VETO）")
    elif verdict == "VETO":
        triggers = fm.get("veto_triggers")
        if (not isinstance(triggers, list) or not triggers
                or not all(isinstance(item, str) and item.strip() for item in triggers)):
            problems.append("verdict=VETO 时 veto_triggers 必须是非空字符串列表")
    veto_lines = [
        line for line in text[text.find("---", 3) + 3:].splitlines()
        if re.search(r'⛔\s*VETO', line, re.IGNORECASE)
        and not re.search(r'未触发|没有触发|不触发', line)
    ]
    body_has_veto = bool(veto_lines)
    if body_has_veto and verdict != "VETO":
        problems.append("正文出现 VETO，但 frontmatter.verdict 不是 VETO")
    if verdict == "VETO" and not body_has_veto:
        problems.append("frontmatter.verdict=VETO，但正文未明确标注 VETO")
    if fm.get("conclusion_direction") not in {"POSITIVE", "NEUTRAL", "NEGATIVE"}:
        problems.append("conclusion_direction 非法（需 POSITIVE/NEUTRAL/NEGATIVE）")

    if exp_date is None:
        problems.append("数据文件缺失或无 trade_date，无法校验 data_date")
    else:
        got = fm.get("data_date")
        if got is None:
            problems.append("缺少 data_date 字段")
        elif str(got) != exp_date:
            problems.append(f"data_date 陈旧/不一致: 结果={got} 数据={exp_date}")

    if exp_batch is None:
        problems.append("数据文件缺失或无 batch_id，无法校验批次")
    else:
        got_batch = fm.get("batch_id")
        if got_batch is None:
            problems.append("缺少 batch_id 字段")
        elif str(got_batch) != exp_batch:
            problems.append(f"batch_id 陈旧/不一致: 结果={got_batch} 数据={exp_batch}")

    data_file = base_dir / f"invest_data_{ts_code}.json"
    data = {}
    try:
        data = json.loads(data_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    expected_analysis_date = data.get("meta", {}).get("analysis_date")
    if not expected_analysis_date or str(fm.get("analysis_date") or "") != str(expected_analysis_date):
        problems.append(
            f"analysis_date 缺失/不一致: 结果={fm.get('analysis_date')} 数据={expected_analysis_date}"
        )

    required_sections = (
        "## 总体判断", "## 详细分析", "## 叙事–数据交叉验证",
        "## 关键风险与不确定性", "## 必检项执行记录",
        "## 数据使用说明", "## 知识检索日志",
    )
    for heading in required_sections:
        if heading not in text:
            problems.append(f"缺少必需章节: {heading}")
    if _meaningful_table_rows(text, "## 叙事–数据交叉验证") < 3:
        problems.append("叙事–数据交叉验证少于 3 条有效记录")
    if _meaningful_table_rows(text, "## 知识检索日志") < 3:
        problems.append("知识检索日志少于 3 条有效记录")
    elif _knowledge_log_existing_rows(text) < 3:
        problems.append("知识检索日志少于 3 个真实存在的 wiki 页面")
    citation_count = len(re.findall(r'\[(?:source|calc):', text, re.IGNORECASE))
    if citation_count < 3:
        problems.append(f"精确数据引用不足: {citation_count}（至少 3 个 [source: ...]/[calc: ...]）")
    checklist_result = check_expert_coverage(expert_id, text, load_checklist())
    coverage = (checklist_result["covered"] / checklist_result["total"] * 100
                if checklist_result["total"] else 0)
    if coverage < 80:
        problems.append(f"必检项结构化覆盖率 {coverage:.1f}%（准出要求 >=80%）")
    done_count = sum(
        item.get("found") and item.get("status") == "DONE"
        for item in checklist_result.get("items", [])
    )
    if checklist_result.get("total") and done_count < 1:
        problems.append("必检项全部标为 MISSING，至少 1 项必须有实质 DONE 结论")
    source_map = flatten_json(data)
    all_paths = flatten_paths(data)
    annual_path = base_dir / f"invest_annual_{ts_code}.txt"
    annual_text = annual_path.read_text(encoding="utf-8") if annual_path.is_file() else ""
    if data.get("meta", {}).get("expert_result_contract_version") == EXPERT_RESULT_V3:
        sidecar = base_dir / f"invest_result_{ts_code}_{expert_id}.v3.json"
        original_prompt = base_dir / f"invest_prompt_{ts_code}_{expert_id}.txt"
        if not sidecar.is_file():
            problems.append("ExpertResult v3 sidecar 缺失")
        elif not original_prompt.is_file():
            problems.append("ExpertResult v3 原始 prompt 缺失，无法验证知识路径")
        else:
            try:
                raw_sidecar = sidecar.read_text(encoding="utf-8")
                structured = parse_v3_result(raw_sidecar)
                if raw_sidecar.encode("utf-8") != canonical_v3_bytes(structured):
                    raise ExpertResultV3Error("sidecar 不是 canonical JSON")
                knowledge_paths = knowledge_paths_from_prompt(
                    original_prompt.read_text(encoding="utf-8")
                )
                validate_v3_result(
                    structured, expert_id=expert_id, ts_code=ts_code, data=data,
                    annual_text=annual_text, knowledge_paths=knowledge_paths,
                )
                expected_markdown = render_v3_markdown(
                    structured, expert_id=expert_id, ts_code=ts_code, data=data,
                    annual_text=annual_text, knowledge_paths=knowledge_paths,
                )
                if expected_markdown != text:
                    raise ExpertResultV3Error("派生 Markdown 与确定性 renderer 输出不一致")
            except (OSError, ValueError, json.JSONDecodeError, ExpertResultV3Error) as exc:
                problems.append(f"ExpertResult v3 校验失败: {exc}")
    checked_numbers = trace_data_numbers(text, source_map)
    diagnostics = build_expert_diagnostics(
        expert_id, text, data, annual_text,
        checklist_result=checklist_result,
        source_map=source_map,
        all_paths=all_paths,
        checked_numbers=checked_numbers,
    )
    invalid_evidence = [
        item["item"] for item in diagnostics["invalid_checklist_evidence"]
    ]
    if invalid_evidence:
        problems.append(f"必检项证据路径不存在: {invalid_evidence[:5]}")
    if _verified_narrative_rows(text, annual_text, all_paths) < 3:
        problems.append("叙事–数据交叉验证少于 3 条同时具备真实年报定位和 JSON 证据的记录")

    evidence_signatures = []
    for item in checklist_result.get("items", []):
        if not item.get("found"):
            continue
        evidence = item.get("evidence", "")
        paths = sorted(set(re.findall(
            r'[A-Za-z_][\w-]*(?:\[\d+\])?(?:\.[A-Za-z_][\w-]*(?:\[\d+\])?)+',
            evidence,
        )))
        docs = sorted(set(re.findall(r'(?:年报|wiki):[^|`；、\s]+', evidence, re.IGNORECASE)))
        evidence_signatures.append(tuple(paths + docs))
    irrelevant_items = [
        item["item"] for item in diagnostics["out_of_domain_checklist_evidence"]
    ]
    if irrelevant_items:
        problems.append(f"必检项证据超出专家数据域: {irrelevant_items[:5]}")
    covered_count = sum(item.get("found") for item in checklist_result.get("items", []))
    minimum_unique = min(3, covered_count)
    if covered_count and len(set(evidence_signatures)) < minimum_unique:
        problems.append(
            f"必检项证据过度复用: 唯一证据组 {len(set(evidence_signatures))} < {minimum_unique}"
        )

    invalid_sources = sorted({
        item["path"] for item in diagnostics["invalid_sources"]
    })
    if invalid_sources:
        problems.append(f"[source] 路径不存在: {invalid_sources[:5]}")
    invalid_calcs = [
        {"formula": item["formula"], "inputs": item["inputs"]}
        for item in diagnostics["invalid_calculations"]
    ]
    if invalid_calcs:
        problems.append(f"[calc] 公式或 inputs 无法验证: {invalid_calcs[:3]}")
    traced_count = sum(item.get("trace_status") in {"DIRECT", "DERIVED"} for item in checked_numbers)
    if len(checked_numbers) < 5 or traced_count < 5:
        problems.append(
            f"实质数字事实不足: data={len(checked_numbers)}, traced={traced_count}（至少 5）"
        )
    traced_paths = set()
    for item in checked_numbers:
        if item.get("trace_status") == "DIRECT":
            traced_paths.update(source.get("path") for source in item.get("sources", []))
        elif item.get("trace_status") == "DERIVED":
            traced_paths.update(item.get("sources", []))
    traced_paths.discard(None)
    if len(traced_paths) < 3:
        problems.append(f"数字证据维度不足: 唯一 JSON 路径 {len(traced_paths)} < 3")
    qualitative = diagnostics["qualitative_contradictions"]
    unsupported = diagnostics["unsourced_claims"]
    if qualitative:
        examples = [f"L{item['line']}:{item['label']}" for item in qualitative[:5]]
        problems.append(
            f"存在与数据缺口矛盾的定性断言: {examples}"
        )
    if unsupported:
        examples = [f"L{item['line']}:{item['label']}" for item in unsupported[:5]]
        problems.append(
            f"存在未充分核对的行业/历史断言: {examples}"
        )
    untraced = diagnostics["untraced_numbers"]
    if untraced:
        examples = [f"L{item['line']}:{item['raw']}" for item in untraced[:8]]
        problems.append(f"存在 {len(untraced)} 个未精确溯源数字: {examples}")

    return problems


def collect_expert(ts_code: str) -> dict:
    result = {}
    for expert_id in EXPERTS:
        path = result_path(ts_code, expert_id)
        entry = {"file": str(path), "exists": False, "size": 0, "frontmatter": {}, "missing": True}
        if path.exists():
            text = path.read_text(encoding="utf-8")
            entry.update({
                "exists": True,
                "size": len(text),
                "frontmatter": parse_frontmatter(text),
                "missing": bool(validate_expert(
                    ts_code, expert_id, expected_data_date(ts_code), expected_batch_id(ts_code)
                )),
            })
        result[expert_id] = entry
    return result


def run_check(ts_code: str, quiet_pass: bool = False) -> list[str]:
    """逐专家校验，打印报告（quiet_pass 时只打印失败项），返回未通过的专家列表。"""
    exp_date = expected_data_date(ts_code)
    exp_batch = expected_batch_id(ts_code)
    failing = []
    for expert_id in EXPERTS:
        problems = validate_expert(ts_code, expert_id, exp_date, exp_batch)
        if problems:
            failing.append(expert_id)
            if not quiet_pass:
                print(f"  ✗ {expert_id}")
                for p in problems:
                    print(f"      - {p}")
        elif not quiet_pass:
            print(f"  ✓ {expert_id}")
    return failing


def main() -> int:
    parser = argparse.ArgumentParser(description="收集/校验 invest-skill 专家结果")
    parser.add_argument("ts_code", help="股票代码，如 603605.SH")
    parser.add_argument(
        "--json", action="store_true",
        help="默认模式写入结果文件；与 --failing 连用时向 stdout 输出纯 JSON 失败详情",
    )
    parser.add_argument("--check", action="store_true", help="校验全部专家结果，exit 0=全部通过")
    parser.add_argument(
        "--failing", action="store_true",
        help="输出失败专家；与 --json 连用时输出 problems 和完整 diagnostics 的纯 JSON",
    )
    parser.add_argument("--expert", choices=EXPERTS,
                        help="只校验指定专家（供有界修复事务逐轮验收）")
    args = parser.parse_args()

    try:
        ts_code = normalize_ts_code(args.ts_code)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    if args.check or args.failing:
        exp_date = expected_data_date(ts_code)
        exp_batch = expected_batch_id(ts_code)
        selected = [args.expert] if args.expert else EXPERTS
        details = {
            expert_id: validate_expert(ts_code, expert_id, exp_date, exp_batch)
            for expert_id in selected
        }
        failing = [expert_id for expert_id, problems in details.items() if problems]
        # --failing --json 是供修复器消费的机器契约，即使调用方误加
        # --check 也不能混入人类可读前缀。
        if args.check and not (args.failing and args.json):
            for expert_id in selected:
                problems = details[expert_id]
                if problems:
                    print(f"  ✗ {expert_id}")
                    for problem in problems:
                        print(f"      - {problem}")
                else:
                    print(f"  ✓ {expert_id}")
            print(f"\n校验结果：{len(selected) - len(failing)}/{len(selected)} 通过")
        if args.failing:
            if args.json:
                print(json.dumps(
                    {
                        expert_id: {
                            "problems": details[expert_id],
                            "diagnostics": load_expert_diagnostics(ts_code, expert_id),
                        }
                        for expert_id in failing
                    },
                    ensure_ascii=False, indent=2,
                ))
            else:
                for expert_id in failing:
                    print(expert_id)
        return 0 if not failing else 1

    experts = collect_expert(ts_code)
    output = {
        "ts_code": ts_code,
        "experts": experts,
        "missing_experts": [k for k, v in experts.items() if v["missing"]],
    }

    if args.json:
        out_file = RUNTIME_ROOT / f"invest_results_{ts_code}.json"
        out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {out_file}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
