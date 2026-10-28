"""Structured expert-result v3 contract and deterministic Markdown renderer.

The model supplies judgments and references stable fact/quote IDs.  Identity,
values, paths, calculations, checklist structure, annual quotes and Markdown
syntax are controlled by trusted code.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.checklist_verify import load_checklist
from shared.contracts import normalize_ts_code, snapshot_identity
from shared.project_config import wiki_expert_root
from scripts.prepare_prompts import checklist_template, narrative_quote_catalog
from scripts.verify_report import (
    calculation_unit, evaluate_calculation, flatten_json,
    normalize_calculation_formula,
)

SCHEMA_VERSION = "expert-result/v3"
VALID_VERDICTS = {"PASS", "WARN", "VETO"}
VALID_DIRECTIONS = {"POSITIVE", "NEUTRAL", "NEGATIVE"}
RESULT_MAX_BYTES = 96 * 1024

EXPERT_ALLOWED_PREFIXES = {
    "financial-auditor": ("semiannual.", "annual.", "quarterly.", "balance.", "indicators.", "audit.", "forecast.", "industry."),
    "value-valuator": ("market.", "semiannual.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "macro.", "forecast.", "data_quality.", "meta."),
    "growth-assessor": ("market.", "semiannual.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "forecast.", "data_quality.", "meta."),
    "moat-analyst": ("market.", "semiannual.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "forecast.", "data_quality.", "meta."),
    "cognitive-controller": ("market.", "semiannual.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "forecast.", "data_quality.", "meta."),
    "macro-cyclist": ("macro.", "market.", "industry.", "semiannual.", "annual.", "quarterly.", "forecast.", "data_quality.", "meta."),
    "management-auditor": ("stock_info.", "market.", "audit.", "semiannual.", "annual.", "quarterly.", "balance.", "indicators.", "industry.", "forecast.", "data_quality.", "meta."),
}

TOKEN_RE = re.compile(
    r"\{\{(?:(?P<fact>F\d{3})|(?P<kind>C|M|A):(?P<body>[^{}]+))\}\}"
)
FACT_ID_RE = re.compile(r"F\d{3}")
ASCII_DIGIT_RE = re.compile(r"\d")


class ExpertResultV3Error(ValueError):
    pass


@dataclass(frozen=True)
class Fact:
    fact_id: str
    path: str
    value: float
    unit: str


def _format_number(value: float, precision: int = 4) -> str:
    if not math.isfinite(value):
        raise ExpertResultV3Error("数值不是有限数")
    rounded = round(value, precision)
    if abs(rounded - int(rounded)) < 10 ** (-precision):
        return str(int(rounded))
    return f"{rounded:.{precision}f}".rstrip("0").rstrip(".")


def build_fact_catalog(data: dict, expert_id: str) -> list[Fact]:
    prefixes = EXPERT_ALLOWED_PREFIXES.get(expert_id)
    if not prefixes:
        raise ExpertResultV3Error(f"未知专家: {expert_id}")
    source_map = flatten_json(data)
    ranked: list[tuple[tuple[Any, ...], str, float, str]] = []
    priority_tokens = (
        "revenue_yi", "net_profit_yi", "ocf", "fcf", "gross_margin", "net_margin",
        "roe", "pe_", ".pb", "close", "total_mv", "equity", "assets", "debt",
        "goodwill", "receiv", "inventor", "cagr", "audit", "pmi", "gdp", "shibor",
    )
    for path, item in source_map.items():
        if not path.startswith(prefixes):
            continue
        value, unit = item
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not math.isfinite(float(value)):
            continue
        lower = path.lower()
        rank = (
            not any(token in lower for token in priority_tokens),
            path.count("."), len(path), path,
        )
        ranked.append((rank, path, float(value), str(unit or "")))
    ranked.sort()
    # Stable IDs follow path order after relevance ranking.  The prompt and
    # renderer always rebuild from the same batch snapshot.
    return [
        Fact(f"F{index:03d}", path, value, unit)
        for index, (_, path, value, unit) in enumerate(ranked[:600], 1)
    ]


def fact_maps(data: dict, expert_id: str) -> tuple[dict[str, Fact], dict[str, Fact]]:
    facts = build_fact_catalog(data, expert_id)
    return ({fact.fact_id: fact for fact in facts}, {fact.path: fact for fact in facts})


def build_qualitative_catalog(data: dict, expert_id: str) -> list[tuple[str, Any]]:
    prefixes = EXPERT_ALLOWED_PREFIXES[expert_id]
    leaves: list[tuple[str, Any]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                walk(value[key], f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif path.startswith(prefixes) and (value is None or isinstance(value, (str, bool))):
            if not any(token in path.lower() for token in ("hash", "prompt", "query", "content")):
                text = str(value)
                if len(text) <= 240:
                    leaves.append((path, value))

    walk(data, "")
    priority = ("audit.", "data_quality.", "forecast.", "stock_info.", "industry.", "meta.")
    leaves.sort(key=lambda item: (
        next((i for i, prefix in enumerate(priority) if item[0].startswith(prefix)), len(priority)),
        item[0],
    ))
    return leaves[:220]


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        stripped = stripped[len("```json"): -3].strip()
    elif stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3].strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start:end + 1]
    return stripped


def _repair_json_transport(text: str) -> tuple[str, list[str]]:
    """Repair only unambiguous JSON transport damage; never invent prose."""
    output: list[str] = []
    stack: list[str] = []
    actions: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                output.append(char)
                escaped = False
            elif char == "\\":
                output.append(char)
                escaped = True
            elif char == '"':
                output.append(char)
                in_string = False
            elif ord(char) < 0x20:
                output.append(" ")
                actions.append("escaped-control-character")
            else:
                output.append(char)
            continue
        if char == '"':
            in_string = True
            output.append(char)
            continue
        if char in "{[":
            stack.append(char)
            output.append(char)
            continue
        if char in "}]":
            expected = "{" if char == "}" else "["
            while stack and stack[-1] != expected:
                opener = stack.pop()
                output.append("}" if opener == "{" else "]")
                actions.append("inserted-missing-container-closer")
            if stack and stack[-1] == expected:
                stack.pop()
            output.append(char)
            continue
        output.append(char)
    # Do not repair truncated strings or tail containers: that could turn
    # incomplete prose into apparently valid evidence.
    if in_string or stack:
        return text, []
    return "".join(output), list(dict.fromkeys(actions))


def parse_result(text: str) -> dict:
    if len(text.encode("utf-8")) > RESULT_MAX_BYTES:
        raise ExpertResultV3Error(f"v3 JSON 过大: > {RESULT_MAX_BYTES} bytes")
    if "\x00" in text:
        raise ExpertResultV3Error("v3 JSON 含 NUL")
    raw = _strip_json_fence(text)
    repairs: list[str] = []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as original_exc:
        repaired, repairs = _repair_json_transport(raw)
        if not repairs:
            raise ExpertResultV3Error(f"v3 JSON 无法解析: {original_exc}") from original_exc
        try:
            value = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise ExpertResultV3Error(f"v3 JSON 无法解析: {exc}") from exc
    if not isinstance(value, dict):
        raise ExpertResultV3Error("v3 顶层必须是 object")
    if repairs:
        value["transport_repairs"] = repairs
    # Small deterministic enum normalization is a mechanical transport repair,
    # not a semantic rewrite.
    for item in value.get("narrative_checks", []) if isinstance(value.get("narrative_checks"), list) else []:
        if isinstance(item, dict) and item.get("assessment") == "SUPPORTED":
            item["assessment"] = "CONFIRMED"
    return value


def canonical_bytes(result: dict) -> bytes:
    return (json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ) + "\n").encode("utf-8")


def canonical_hash(result: dict) -> str:
    return hashlib.sha256(canonical_bytes(result)).hexdigest()


def _mask_tokens_and_validate(text: str, valid_facts: set[str], field: str) -> None:
    if not isinstance(text, str) or len(text.strip()) < 4:
        raise ExpertResultV3Error(f"{field} 缺失或过短")
    if any(marker in text for marker in ("[source:", "[calc:", "```", "<script")):
        raise ExpertResultV3Error(f"{field} 不得手写最终引用或代码块")
    masked = list(text)
    for match in TOKEN_RE.finditer(text):
        kind = "F" if match.group("fact") else match.group("kind")
        body = match.group("fact") or match.group("body")
        if kind == "F":
            if body not in valid_facts:
                raise ExpertResultV3Error(f"{field} 使用未知事实 ID: {body}")
        elif kind == "C":
            try:
                formula, raw_ids = body.split("|", 1)
            except ValueError as exc:
                raise ExpertResultV3Error(f"{field} calc token 格式错误") from exc
            ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
            if not ids or any(item not in valid_facts for item in ids):
                raise ExpertResultV3Error(f"{field} calc token facts 非法: {ids}")
            normalized_formula = normalize_calculation_formula(formula)
            if not normalized_formula or not re.fullmatch(
                r"[A-Za-z0-9_+\-*/(). ]+", normalized_formula
            ):
                raise ExpertResultV3Error(f"{field} calc formula 非法: {formula}")
        elif kind in {"M", "A"}:
            try:
                value, rationale = body.split("|", 1)
            except ValueError as exc:
                raise ExpertResultV3Error(f"{field} method/assumption token 格式错误") from exc
            if not re.search(r"\d", value) or len(rationale.strip()) < 8:
                raise ExpertResultV3Error(f"{field} method/assumption 缺值或理由过短")
        masked[match.start():match.end()] = " " * (match.end() - match.start())
    remaining = "".join(masked)
    if ASCII_DIGIT_RE.search(remaining):
        raise ExpertResultV3Error(
            f"{field} 含裸阿拉伯数字；事实用 F/C token，规则或假设用 M/A token"
        )


def _checklist_evidence_map(expert_id: str, data: dict, annual_text: str) -> dict[str, str]:
    rendered = checklist_template(expert_id, data, annual_text)
    mapping: dict[str, str] = {}
    for line in rendered.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 4 and cells[1] == "DONE / MISSING":
            mapping[cells[0]] = cells[2]
    return mapping


def quote_catalog(annual_text: str, limit: int = 12) -> list[dict]:
    preferred = ("管理层讨论与分析", "公司治理", "重要事项", "财务报告")
    candidates = [
        (locator, quote) for locator, quote in narrative_quote_catalog(annual_text, 160)
        if not ASCII_DIGIT_RE.search(quote) and any(section in locator for section in preferred)
    ]
    if len(candidates) < limit:
        candidates.extend(
            (locator, quote) for locator, quote in narrative_quote_catalog(annual_text, 200)
            if not ASCII_DIGIT_RE.search(quote) and (locator, quote) not in candidates
        )
    return [
        {"quote_id": f"Q{index:02d}", "locator": locator, "quote": quote}
        for index, (locator, quote) in enumerate(candidates[:limit], 1)
    ]


def knowledge_paths_from_prompt(prompt_text: str) -> list[str]:
    head = prompt_text.split("年报证据只能", 1)[0]
    values = re.findall(r'^- `([^`]+\.md)`\s*$', head, re.MULTILINE)
    return list(dict.fromkeys(values))[:3]


def validate_result(result: dict, *, expert_id: str, ts_code: str, data: dict,
                    annual_text: str, knowledge_paths: list[str]) -> None:
    code = normalize_ts_code(ts_code)
    data_date, batch_id = snapshot_identity(data)
    analysis_date = str(data.get("meta", {}).get("analysis_date") or "")
    if result.get("schema_version") != SCHEMA_VERSION:
        raise ExpertResultV3Error(f"schema_version 必须是 {SCHEMA_VERSION}")
    identity = result.get("identity")
    if not isinstance(identity, dict):
        raise ExpertResultV3Error("identity 缺失")
    expected_identity = {
        "expert_id": expert_id, "ts_code": code, "data_date": data_date,
        "analysis_date": analysis_date, "batch_id": batch_id,
    }
    if identity != expected_identity:
        raise ExpertResultV3Error(f"identity 不匹配: {identity!r} != {expected_identity!r}")

    decision = result.get("decision")
    if not isinstance(decision, dict):
        raise ExpertResultV3Error("decision 缺失")
    score = decision.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise ExpertResultV3Error("decision.score 必须是零到一百的整数")
    verdict = decision.get("verdict")
    if verdict not in VALID_VERDICTS:
        raise ExpertResultV3Error("decision.verdict 非法")
    if decision.get("conclusion_direction") not in VALID_DIRECTIONS:
        raise ExpertResultV3Error("decision.conclusion_direction 非法")
    veto = decision.get("veto_triggers")
    if not isinstance(veto, list) or any(not isinstance(item, str) for item in veto):
        raise ExpertResultV3Error("decision.veto_triggers 必须是字符串数组")
    if verdict == "VETO" and not veto:
        raise ExpertResultV3Error("VETO 必须提供 veto_triggers")
    if verdict != "VETO" and veto:
        raise ExpertResultV3Error("非 VETO 不得提供 veto_triggers")

    facts_by_id, _ = fact_maps(data, expert_id)
    valid_fact_ids = set(facts_by_id)
    text_errors: list[str] = []

    def check_text(value: object, field: str) -> None:
        try:
            _mask_tokens_and_validate(value, valid_fact_ids, field)  # type: ignore[arg-type]
        except ExpertResultV3Error as exc:
            text_errors.append(str(exc))

    check_text(result.get("summary"), "summary")
    analyses = result.get("analysis_sections")
    if not isinstance(analyses, list) or len(analyses) < 5:
        raise ExpertResultV3Error("analysis_sections 至少五节")
    for index, item in enumerate(analyses):
        if not isinstance(item, dict):
            raise ExpertResultV3Error(f"analysis_sections[{index}] 非 object")
        check_text(item.get("heading"), f"analysis[{index}].heading")
        check_text(item.get("body"), f"analysis[{index}].body")
    risks = result.get("risks")
    if not isinstance(risks, list) or len(risks) < 3:
        raise ExpertResultV3Error("risks 至少三条")
    for index, value in enumerate(risks):
        check_text(value, f"risks[{index}]")
    check_text(result.get("data_usage"), "data_usage")
    for index, value in enumerate(veto):
        check_text(value, f"veto_triggers[{index}]")

    expected_items = load_checklist()[expert_id]["items"]
    conclusions = result.get("checklist_conclusions")
    if not isinstance(conclusions, dict) or set(conclusions) != set(expected_items):
        missing = sorted(set(expected_items) - set(conclusions or {}))
        extra = sorted(set(conclusions or {}) - set(expected_items))
        raise ExpertResultV3Error(f"checklist_conclusions 键不一致: missing={missing}, extra={extra}")
    for item in expected_items:
        check_text(conclusions[item], f"checklist.{item}")
    evidence = _checklist_evidence_map(expert_id, data, annual_text)
    if set(evidence) != set(expected_items):
        raise ExpertResultV3Error("可信 checklist evidence 骨架不完整")

    quotes = {item["quote_id"]: item for item in quote_catalog(annual_text)}
    narratives = result.get("narrative_checks")
    if not isinstance(narratives, list) or len(narratives) < 3:
        raise ExpertResultV3Error("narrative_checks 至少三条")
    used_quotes: set[str] = set()
    narrative_fact_ids: set[str] = set()
    narrative_fact_count = 0
    for index, item in enumerate(narratives):
        if not isinstance(item, dict) or item.get("quote_id") not in quotes:
            raise ExpertResultV3Error(f"narrative[{index}] quote_id 非法")
        quote_id = item["quote_id"]
        if quote_id in used_quotes:
            raise ExpertResultV3Error("narrative quote_id 不得重复")
        used_quotes.add(quote_id)
        if item.get("assessment") not in {"CONFIRMED", "PARTIAL", "CONTRADICTED", "UNKNOWN"}:
            raise ExpertResultV3Error(f"narrative[{index}] assessment 非法")
        ids = item.get("fact_ids")
        if not isinstance(ids, list) or not ids or any(value not in valid_fact_ids for value in ids):
            raise ExpertResultV3Error(f"narrative[{index}] fact_ids 非法")
        narrative_fact_ids.update(ids)
        narrative_fact_count += len(ids)
        check_text(item.get("analysis"), f"narrative[{index}].analysis")
    if text_errors:
        raise ExpertResultV3Error(
            "prose token 合同错误（一次性列出）: " + " | ".join(text_errors[:30])
        )
    if narrative_fact_count < 5 or len(narrative_fact_ids) < 3:
        raise ExpertResultV3Error("叙事核验至少绑定五个事实、三个不同路径")

    if len(knowledge_paths) < 3:
        raise ExpertResultV3Error("可信知识路径不足三条")
    prose = [result["summary"], result["data_usage"], *risks]
    prose.extend(item["body"] for item in analyses)
    token_count = sum(len(TOKEN_RE.findall(text)) for text in prose)
    if token_count < 12:
        raise ExpertResultV3Error(f"实质证据 token 不足: {token_count} < 12")
    if sum(len(text) for text in prose) < 1200:
        raise ExpertResultV3Error("分析正文过短，至少一千二百字符")


def _render_token(match: re.Match[str], facts: dict[str, Fact], source_map: dict) -> str:
    kind = "F" if match.group("fact") else match.group("kind")
    body = match.group("fact") or match.group("body")
    if kind == "F":
        fact = facts[body]
        return f"{_format_number(fact.value)}{fact.unit} [source: {fact.path}]"
    if kind == "C":
        formula, raw_ids = body.split("|", 1)
        ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
        paths = [facts[item].path for item in ids]
        normalized_formula = normalize_calculation_formula(formula)
        spec = {"formula": normalized_formula, "inputs": paths}
        value = evaluate_calculation(spec, source_map)
        if value is None:
            raise ExpertResultV3Error(f"calc 无法复算: {body}")
        unit = calculation_unit(spec, source_map)
        return (
            f"{_format_number(float(value))}{unit} "
            f"[calc: {normalized_formula}; inputs: {','.join(paths)}]"
        )
    value, rationale = body.split("|", 1)
    label = "method" if kind == "M" else "assumption"
    return f"{value.strip()} [{label}: {rationale.strip()}]"


def _expand(text: str, facts: dict[str, Fact], source_map: dict) -> str:
    value = TOKEN_RE.sub(lambda match: _render_token(match, facts, source_map), text)
    if "{{" in value or "}}" in value:
        raise ExpertResultV3Error("存在无法识别的模板 token")
    return unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")


def build_native_prompt(*, expert_id: str, ts_code: str, data: dict,
                        annual_text: str, original_prompt: str) -> str:
    code = normalize_ts_code(ts_code)
    data_date, batch_id = snapshot_identity(data)
    identity = {
        "expert_id": expert_id,
        "ts_code": code,
        "data_date": data_date,
        "analysis_date": str(data.get("meta", {}).get("analysis_date") or ""),
        "batch_id": batch_id,
    }
    experts = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "experts.json").read_text(encoding="utf-8")
    )["experts"]
    filename = next(item["file"] for item in experts if item["id"] == expert_id)
    method_path = wiki_expert_root() / "experts" / f"{filename}.md"
    method_text = method_path.read_text(encoding="utf-8")
    # Sage content is already batch-bound in the original prompt.  Keep only
    # this compact methodology supplement; do not repeat raw JSON or annual text.
    sage = ""
    marker = "## Sage Wiki 检索知识"
    if marker in original_prompt:
        sage = original_prompt.split(marker, 1)[1].split("## 目标公司原始数据", 1)[0]
        sage = sage[:8000]
    facts = build_fact_catalog(data, expert_id)
    fact_lines = [
        f"- {fact.fact_id} | {fact.path} | {_format_number(fact.value)}{fact.unit}"
        for fact in facts
    ]
    qualitative_lines = [
        f"- {path} = {json.dumps(value, ensure_ascii=False)}"
        for path, value in build_qualitative_catalog(data, expert_id)
    ]
    quotes = quote_catalog(annual_text)
    checklist_items = load_checklist()[expert_id]["items"]
    knowledge = knowledge_paths_from_prompt(original_prompt)
    skeleton = {
        "schema_version": SCHEMA_VERSION,
        "identity": identity,
        "decision": {
            "score": 50,
            "verdict": "WARN",
            "conclusion_direction": "NEUTRAL",
            "veto_triggers": [],
        },
        "summary": "至少一段完整判断，并使用 {{F001}} 这类事实 token。",
        "analysis_sections": [
            {"heading": "分析主题（不要阿拉伯数字）", "body": "完整分析与证据 token"}
        ],
        "narrative_checks": [
            {
                "quote_id": "Q01", "assessment": "PARTIAL",
                "fact_ids": ["F001", "F002"],
                "analysis": "对管理层原话的核验结论",
            }
        ],
        "risks": ["风险及其证伪条件"],
        "checklist_conclusions": {item: "逐项实质结论、缺口及影响" for item in checklist_items},
        "data_usage": "数据范围、缺失项和结论降级说明",
    }
    return f"""⬛⬛⬛ ExpertResult v3 唯一输出契约 ⬛⬛⬛
你是当前主 agent 创建的独立 {expert_id} 子代理。只输出一个 JSON object；不要 Markdown
代码围栏、前言或结尾确认。不要启动任何外部 CLI，不使用网络或其他项目文件。

你的职责是做深入投资判断；机器负责数值、路径、公式、frontmatter、表格和最终 Markdown。
所有 prose 字段（summary、heading、body、analysis、risks、checklist conclusion、data_usage、
veto_triggers）禁止直接输入阿拉伯数字，也禁止手写 [source:] / [calc:]。

事实写法：`{{{{F001}}}}`，renderer 自动变成“真实值+单位+[source:path]”。
计算写法：`{{{{C:a/b|F001,F002}}}}`；竖线左侧只能写纯算术表达式，可用 a/b、x1/x2 或 fcf/revenue 等语义变量，机器按变量首次出现顺序绑定右侧事实；不要写 `result=a/b` 这类赋值式，只用 ASCII `*` 表示乘法；**绝不能在公式左侧写 F001/F002**，竖线右侧才按顺序列事实 ID。
方法阈值：`{{{{M:0.7|至少八个汉字的方法论规则来源}}}}`；竖线左侧必须含阿拉伯数字，右侧至少八个字符。
分析假设：`{{{{A:8%|至少八个汉字的具体假设理由}}}}`；竖线左侧必须含阿拉伯数字，右侧至少八个字符。
不要在 token 外重复其数值。年份、期间也尽量通过事实 token 表达；普通序数使用中文。输出前逐个扫描所有 C/M/A token，任何缺少竖线、公式含 F 编号、M/A 左侧无数字或右侧过短都先自行修正。

硬要求：
- analysis_sections 至少五节；summary+分析+risks+data_usage 合计至少一千二百字符；
- 上述文本合计至少十二个 F/C/M/A token；
- risks 至少三条；
- narrative_checks 至少三条且 quote_id 不重复，assessment 只能是 CONFIRMED、PARTIAL、
  CONTRADICTED 或 UNKNOWN；合计至少五个 fact_ids、三个不同事实；
- checklist_conclusions 必须包含下方全部项目且键名逐字一致；
- VETO 时 veto_triggers 非空并明确原因；非 VETO 时必须为空；
- 结论必须诚实处理数据缺失，不得编造同行、行业或外部事实；没有合格行业样本时避免
  “行业平均/普遍/通常”等措辞；不要写“历史最高/最低”或“连续若干年”等历史断言，
  改为逐期事实 token 的客观比较。

## 固定身份（必须逐字段原样复制）
{json.dumps(identity, ensure_ascii=False, indent=2)}

## JSON 形状示例（仅形状；必须扩充到硬要求）
{json.dumps(skeleton, ensure_ascii=False, indent=2)}

## 必检项键（全部必须输出）
{json.dumps(checklist_items, ensure_ascii=False, indent=2)}

## 可选逐字年报引文（只能按 quote_id 选择，机器插入原文与定位）
{json.dumps(quotes, ensure_ascii=False, indent=2)}

## 可用知识页（机器会固定渲染日志）
{json.dumps(knowledge, ensure_ascii=False, indent=2)}

## 数值事实目录（只引用 F 编号，值由机器重新读取）
{chr(10).join(fact_lines)}

## 定性与缺失状态目录（用于判断；不要把路径手写成数值引用）
{chr(10).join(qualitative_lines) or '- 无'}

## 专家方法论
{method_text[:18000]}

## 本批 Sage 方法论补充
{sage or '无额外补充；仅按上述专家方法论执行。'}
"""


def render_markdown(result: dict, *, expert_id: str, ts_code: str, data: dict,
                    annual_text: str, knowledge_paths: list[str]) -> str:
    validate_result(
        result, expert_id=expert_id, ts_code=ts_code, data=data,
        annual_text=annual_text, knowledge_paths=knowledge_paths,
    )
    facts, _ = fact_maps(data, expert_id)
    source_map = flatten_json(data)
    identity = result["identity"]
    decision = result["decision"]
    veto_json = json.dumps(decision["veto_triggers"], ensure_ascii=False)
    lines = [
        "---",
        f'expert_id: "{expert_id}"',
        f'ts_code: "{identity["ts_code"]}"',
        f'data_date: "{identity["data_date"]}"',
        f'analysis_date: "{identity["analysis_date"]}"',
        f'batch_id: "{identity["batch_id"]}"',
        f'score: {decision["score"]}',
        f'verdict: {decision["verdict"]}',
        f'conclusion_direction: {decision["conclusion_direction"]}',
        f'veto_triggers: {veto_json}',
        f'result_contract: "{SCHEMA_VERSION}"',
        f'result_payload_hash: "{canonical_hash(result)}"',
        "---",
        "",
        f"# {expert_id} 专家评估",
        "",
        "## 总体判断",
        "",
        f"**裁决：{'⛔ VETO' if decision['verdict'] == 'VETO' else decision['verdict']}。**",
        "",
        _expand(result["summary"], facts, source_map),
        "",
        "## 详细分析",
        "",
    ]
    for item in result["analysis_sections"]:
        lines.extend([
            f"### {_expand(item['heading'], facts, source_map)}", "",
            _expand(item["body"], facts, source_map), "",
        ])

    quote_map = {item["quote_id"]: item for item in quote_catalog(annual_text)}
    assessment = {"CONFIRMED": "✅", "PARTIAL": "⚠️", "CONTRADICTED": "❌", "UNKNOWN": "❓"}
    lines.extend([
        "## 叙事–数据交叉验证", "",
        "| # | 管理层论述（年报章节+原文摘录） | 对应财务数据字段 | 验证结果 | 证据 |",
        "|---|---|---|---|---|",
    ])
    for index, item in enumerate(result["narrative_checks"], 1):
        quote = quote_map[item["quote_id"]]
        paths = [facts[fact_id].path for fact_id in item["fact_ids"]]
        path_cell = "; ".join(f"`{path}`" for path in paths)
        appended = "；核对数据：" + "；".join(
            _expand("{{" + fact_id + "}}", facts, source_map)
            for fact_id in item["fact_ids"]
        )
        analysis = _expand(item["analysis"], facts, source_map) + appended
        for char in "|\n":
            analysis = analysis.replace(char, "；" if char == "|" else " ")
        lines.append(
            f"| {index} | “{quote['quote']}”（{quote['locator']}） | {path_cell} | "
            f"{assessment[item['assessment']]} | {analysis} |"
        )

    lines.extend(["", "## 关键风险与不确定性", ""])
    for index, risk in enumerate(result["risks"], 1):
        lines.append(f"{index}. {_expand(risk, facts, source_map)}")

    evidence_map = _checklist_evidence_map(expert_id, data, annual_text)
    lines.extend([
        "", "## 必检项执行记录", "",
        "| 必检项 | 状态 | 证据/来源路径 | 结论 |",
        "|---|---|---|---|",
    ])
    for item in load_checklist()[expert_id]["items"]:
        conclusion = _expand(result["checklist_conclusions"][item], facts, source_map)
        conclusion = conclusion.replace("|", "；").replace("\n", " ")
        lines.append(f"| {item} | DONE | {evidence_map[item]} | {conclusion} |")

    lines.extend([
        "", "## 数据使用说明", "", _expand(result["data_usage"], facts, source_map),
        "", "## 知识检索日志", "",
        "| # | 页面路径 | 发现方式 | 使用深度 |",
        "|---|---|---|---|",
    ])
    for index, path in enumerate(knowledge_paths[:3], 1):
        lines.append(f"| {index} | {path} | 任务书确定性注入 | 已用于本专家方法论判断 |")
    return "\n".join(lines).rstrip() + "\n"
