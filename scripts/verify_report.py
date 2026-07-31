#!/usr/bin/env python3
"""报告数据溯源、断言、日期和方法论覆盖率门禁。"""
import argparse
import ast
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from shared.batch_contract import validate_batch_metadata
from shared.checklist_verify import print_checklist_report, verify_checklist
from shared.contracts import normalize_ts_code, quality_envelope_errors, snapshot_identity
from shared.data_tools import validate_snapshot

WIKI_ROOT = SKILL_ROOT.parent / "invest-wiki" / "04_stock-analysis-expert"
CHECKLIST_PATH = SKILL_ROOT / "data" / "expert_checklist.json"
EVIDENCE_RULES_PATH = SKILL_ROOT / "data" / "checklist_evidence_rules.json"
EXPERTS_PATH = SKILL_ROOT / "data" / "experts.json"
PROMPT_CONTRACT_PATH = SKILL_ROOT / "scripts" / "prepare_prompts.py"
EXPERT_IDS = [
    item["id"] for item in
    json.loads((SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8"))["experts"]
]

NUM_PATTERN = re.compile(
    r'(?:¥\s*)?(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s*(万亿|亿|万|元|%|个?百分点))?'
)
JSON_PATH_PATTERN = re.compile(r'[A-Za-z_][\w-]*(?:\[\d+\])?(?:\.[A-Za-z_][\w-]*(?:\[\d+\])?)+')

META_SECTIONS = {
    '结构化自评审', '必检项执行记录', '知识检索日志', '质询问题',
    '第三级触发评估',
}
META_LINE_PATTERN = re.compile(
    r'^\s*(?:score|data_date|analysis_date|batch_id|expert_id|ts_code|verdict|'
    r'veto_triggers|conclusion_direction|expert_result_hash|challenge_prompt_hash|challenge_verdict|reviewer_id|input_bundle_hash|'
    r'level3_hash|reviewer_ids|cross_prompt_hash|cross_verdict|composite_score|'
    r'composite_score_raw|cognitive_adjustment|max_allocation_pct)\s*:|'
    r'(?:总分|满分|评分|得分|权重|贡献分|扣分|覆盖率|专家分数|分析日期|数据基准日|'
    r'生成时间|股票代码|批次标识|报告版本|分析模式|生成方式)',
    re.IGNORECASE,
)
DATA_LINE_PATTERN = re.compile(
    r'(?:PE(?:\(TTM\))?|PB|PS(?:\(TTM\))?|PEG|ROE|ROIC|CAGR|股价|市值|营收|净利|'
    r'现金|负债|商誉|毛利率|净利率|资产负债率|流动比率)',
    re.IGNORECASE,
)

UNSOURCED_PATTERNS = [
    (re.compile(r'行业(?:平均|普遍|常见|一般|正常|通常)'), '行业对比无来源'),
    (re.compile(r'(?:历史|上市以来)(?:最高|最低|首次|新高|新低|中枢|最高水平)'), '历史断言无逐年核对'),
    (re.compile(r'市场(?:普遍|一般|常见|通常|公认)'), '市场共识无来源'),
    (re.compile(r'(?:据统计|据调研|据了解|据悉)'), '引用无具体出处'),
]

SEMANTIC_PATH_RULES = (
    (re.compile(r'总市值|市值'), ('total_mv', 'market_cap')),
    (re.compile(r'收盘价|股价|现价'), ('close',)),
    (re.compile(r'营收|收入'), ('revenue',)),
    (re.compile(r'净利润|利润'), ('profit', 'n_income')),
    (re.compile(r'有息负债'), ('interest_debt', 'st_borr', 'lt_borr', 'bonds_payable')),
    (re.compile(r'商誉'), ('goodwill',)),
    (re.compile(r'存货'), ('inventor',)),
    (re.compile(r'应收'), ('receiv',)),
    (re.compile(r'自由现金流|\bFCF\b'), ('fcf',)),
    (re.compile(r'经营现金流|\bOCF\b'), ('ocf', 'cashflow_act')),
    (re.compile(r'资本开支'), ('capex', 'cap_ex', 'c_pay_acq')),
    (re.compile(r'现金'), ('cash', 'money_cap')),
    (re.compile(r'总股本'), ('total_share',)),
    (re.compile(r'研发费用率'), ('rd_expense_rate',)),
    (re.compile(r'销售费用率'), ('sell_expense_rate',)),
    (re.compile(r'毛利率'), ('gross_margin', 'grossprofit_margin')),
    (re.compile(r'净利率'), ('net_margin', 'netprofit_margin')),
    (re.compile(r'资产负债率'), ('debt_ratio', 'debt_to_assets')),
    (re.compile(r'\bROE\b', re.IGNORECASE), ('roe',)),
    (re.compile(r'\bPE\b', re.IGNORECASE), ('pe',)),
    (re.compile(r'\bPB\b', re.IGNORECASE), ('pb',)),
)


def infer_unit(path: str) -> str:
    lower = path.lower()
    leaf = lower.rsplit('.', 1)[-1]
    if leaf in {'count', 'period_count', 'quarter'} or leaf.endswith('_count'):
        return ''
    if '_yi' in lower:
        return '亿'
    if '_wan' in lower:
        return '万'
    if any(key in lower for key in ('pct', 'margin', 'cagr', 'rate')):
        return '%'
    return ''


def flatten_json(obj, prefix='') -> dict:
    items = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f'{prefix}.{key}' if prefix else key
            items.update(flatten_json(value, path))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            items.update(flatten_json(value, f'{prefix}[{index}]'))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool) and math.isfinite(float(obj)):
        items[prefix] = (float(obj), infer_unit(prefix))
    return items


def flatten_paths(obj, prefix='') -> set[str]:
    paths = {prefix} if prefix else set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f'{prefix}.{key}' if prefix else key
            paths.update(flatten_paths(value, path))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            paths.update(flatten_paths(value, f'{prefix}[{index}]'))
    return paths


def units_compatible(report_unit: str, source_unit: str) -> bool:
    return report_unit == source_unit


def is_stock_code_occurrence(text: str, start: int, end: int) -> bool:
    """只在明确证券代码语境中豁免六位整数，避免吞掉经营事实。"""
    suffix = text[end:end + 3].upper()
    if suffix in {'.SH', '.SZ', '.BJ'}:
        return True
    prefix = text[max(0, start - 12):start]
    return bool(re.search(r'(?:股票|证券|标的)?代码\s*[:：]?\s*$', prefix))


def values_match(report_value: float, source_value: float, raw: str = '') -> bool:
    numeric = re.search(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?', raw)
    rounding_tolerance = 0.0
    if numeric:
        decimals = len(numeric.group(1) or '')
        rounding_tolerance = 0.5 * (10 ** -decimals) + 1e-12
    if abs(source_value) < 1e-12:
        return abs(report_value) <= max(1e-8, rounding_tolerance)
    return abs(report_value - source_value) <= max(rounding_tolerance, 1e-9)


def normalize_source_path(raw: str) -> str:
    return raw.strip().strip('`').replace('JSON.', '', 1) if raw.strip().startswith('JSON.') else raw.strip().strip('`')


def extract_tag_contents(line: str, label: str) -> list[tuple[int, int, str]]:
    """提取允许 JSON 数组下标的平衡方括号标签及其位置。"""
    results = []
    needle = f'[{label}:'.lower()
    lower = line.lower()
    cursor = 0
    while True:
        start = lower.find(needle, cursor)
        if start < 0:
            break
        depth = 1
        index = start + len(needle)
        while index < len(line) and depth:
            if line[index] == '[':
                depth += 1
            elif line[index] == ']':
                depth -= 1
            index += 1
        if depth == 0:
            results.append((start, index, line[start + len(needle):index - 1].strip()))
            cursor = index
        else:
            break
    return results


def _all_tags(line: str) -> list[tuple[int, int, str, str]]:
    tags = []
    for label in ('source', 'calc', 'assumption'):
        tags.extend((start, end, label, content)
                    for start, end, content in extract_tag_contents(line, label))
    return sorted(tags)


def explicit_sources(line: str, start: int = 0, end: int | None = None) -> list[str]:
    paths = []
    limit = len(line) if end is None else end
    for tag_start, tag_end, raw in extract_tag_contents(line, 'source'):
        if tag_start < start or tag_end > limit:
            continue
        for part in raw.split(','):
            path = normalize_source_path(part)
            if path:
                paths.append(path)
    return paths


def calculation_specs(line: str, start: int = 0, end: int | None = None) -> list[dict]:
    specs = []
    limit = len(line) if end is None else end
    for tag_start, tag_end, raw in extract_tag_contents(line, 'calc'):
        if tag_start < start or tag_end > limit:
            continue
        formula, _, inputs_text = raw.partition(';')
        paths = [normalize_source_path(path) for path in JSON_PATH_PATTERN.findall(inputs_text)]
        specs.append({'formula': formula.strip(), 'inputs': paths})
    return specs


def assumption_specs(line: str, start: int = 0, end: int | None = None) -> list[str]:
    limit = len(line) if end is None else end
    return [
        raw for tag_start, tag_end, raw in extract_tag_contents(line, 'assumption')
        if tag_start >= start and tag_end <= limit and len(raw.strip()) >= 8
    ]


def evaluate_calculation(spec: dict, source_map: dict) -> float | None:
    """只执行受限算术表达式，变量按 inputs 顺序映射为 current/previous/a/b。"""
    paths = spec.get('inputs', [])
    if not paths or any(path not in source_map for path in paths):
        return None
    values = [source_map[path][0] for path in paths]
    names = {}
    if len(values) >= 1:
        names.update({'current': values[0], 'a': values[0]})
    if len(values) >= 2:
        names.update({'previous': values[1], 'b': values[1]})
    for index, value in enumerate(values, 1):
        names[f'x{index}'] = value
        if index <= 26:
            names[chr(ord('a') + index - 1)] = value
    try:
        formula = spec.get('formula', '').replace('^', '**')
        tree = ast.parse(formula, mode='eval')
    except SyntaxError:
        return None
    allowed_nodes = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult,
        ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Constant, ast.Name, ast.Load, ast.Call,
    )
    if any(not isinstance(node, allowed_nodes) for node in ast.walk(tree)):
        return None
    safe_functions = {'sqrt': math.sqrt}
    if any(isinstance(node, ast.Call) and (
        not isinstance(node.func, ast.Name) or node.func.id not in safe_functions
    ) for node in ast.walk(tree)):
        return None
    if any(isinstance(node, ast.Name) and node.id not in names and node.id not in safe_functions
           for node in ast.walk(tree)):
        return None
    used_names = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id not in safe_functions
    }
    required_aliases = []
    for index in range(len(values)):
        aliases = {f'x{index + 1}'}
        if index == 0:
            aliases.update({'current', 'a'})
        elif index == 1:
            aliases.update({'previous', 'b'})
        if index < 26:
            aliases.add(chr(ord('a') + index))
        required_aliases.append(aliases)
    if not used_names or any(not (aliases & used_names) for aliases in required_aliases):
        return None
    compiled = compile(tree, '<report-calc>', 'eval')

    def run(mapping):
        return float(eval(compiled, {'__builtins__': {}, **safe_functions}, mapping))

    try:
        value = run(names)
        value = float(value)
        if not math.isfinite(value):
            return None
        if len(values) == 1 and math.isclose(
            value, values[0], rel_tol=1e-12, abs_tol=1e-12
        ):
            return None
        # “语法上引用”不等于真正依赖；拒绝 (a-a)+999、a/a 等
        # 用输入抵消后伪造派生数字的公式。
        for index, original in enumerate(values):
            aliases = {f'x{index + 1}', chr(ord('a') + index)}
            if index == 0:
                aliases.add('current')
            elif index == 1:
                aliases.add('previous')
            changed = dict(names)
            delta = max(abs(original) * 1e-5, 1e-5)
            for alias in aliases:
                if alias in changed:
                    changed[alias] = original + delta
            perturbed = run(changed)
            if not math.isfinite(perturbed) or math.isclose(
                perturbed, value, rel_tol=1e-10, abs_tol=1e-10
            ):
                return None
        return value
    except (ArithmeticError, TypeError, ValueError):
        return None


def calculation_unit(spec: dict, source_map: dict) -> str:
    formula = re.sub(r'\s+', '', spec.get('formula', ''))
    units = [source_map[path][1] for path in spec.get('inputs', []) if path in source_map]
    if '/' in formula and ('*100' in formula or '100*' in formula):
        return '%'
    if units and len(set(units)) == 1 and '/' not in formula:
        return units[0]
    return ''


def extract_numbers(text: str) -> list[dict]:
    findings = []
    current_section = '报告头部'
    table_headers: list[str] = []
    pending_table_headers: list[str] = []
    in_yaml_block = False
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```yaml"):
            in_yaml_block = True
        elif stripped == "```" and in_yaml_block:
            in_yaml_block = False
            continue
        if re.match(r'^#{1,6}\s+', stripped):
            current_section = stripped.strip('# ').strip()
        if stripped.startswith('|'):
            cells = [cell.strip() for cell in stripped.strip('|').split('|')]
            if re.fullmatch(r'\|?[\s:|-]+\|?', stripped):
                table_headers = pending_table_headers
            elif not table_headers:
                pending_table_headers = cells
        elif stripped:
            table_headers = []
            pending_table_headers = []
        tags = _all_tags(stripped)
        masked = list(stripped)
        for start, end, _, _ in tags:
            masked[start:end] = ' ' * (end - start)
        for code_match in re.finditer(r'(?<!`)`[^`\n]+`(?!`)', stripped):
            content = code_match.group(0)[1:-1].strip()
            # JSON 路径/公式的反引号不是事实；单独用反引号包住的
            # “999亿”仍是报告数字，不得藏过门禁。
            if not re.fullmatch(
                r'(?:¥\s*)?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*'
                r'(?:万亿|亿|万|元|%|个?百分点)?',
                content,
            ):
                masked[code_match.start():code_match.end()] = ' ' * (code_match.end() - code_match.start())
        visible = ''.join(masked)
        matches = list(NUM_PATTERN.finditer(visible))
        for match_index, match in enumerate(matches):
            raw_number = match.group(1).replace(',', '')
            raw_unit = match.group(2) or ''
            unit = '%' if raw_unit.endswith('百分点') else raw_unit
            try:
                value = float(raw_number)
            except ValueError:
                continue
            is_integer = value == int(value) and '.' not in raw_number
            if is_integer and 1900 <= value <= 2100 and not unit:
                continue
            if (is_integer and 100000 <= value <= 999999 and not unit
                    and is_stock_code_occurrence(visible, match.start(), match.end())):
                continue
            if is_integer and 19000101 <= value <= 21001231 and not unit:
                continue
            if (is_integer and not unit
                    and re.fullmatch(r'\s*(?:(?:#{1,6}|[-*])\s+)?', visible[:match.start()])
                    and re.match(r'[.)、]\s+', visible[match.end():])):
                continue
            if is_integer and not unit and re.fullmatch(r'\|\s*', visible[:match.start()]):
                continue
            if (is_integer and not unit and match.start() > 0
                    and re.match(r'[A-Za-z]', visible[match.start() - 1])):
                continue
            next_number = matches[match_index + 1].start() if match_index + 1 < len(matches) else len(stripped)
            sources = explicit_sources(stripped, match.end(), next_number)
            specs = calculation_specs(stripped, match.end(), next_number)
            assumptions = assumption_specs(stripped, match.end(), next_number)
            table_header = ''
            if table_headers and stripped.startswith('|'):
                cell_index = max(0, stripped[:match.start()].count('|') - 1)
                if cell_index < len(table_headers):
                    table_header = table_headers[cell_index]
            # A single assumption tag commonly qualifies a numeric range such as
            # ``10—15 个百分点 [assumption: ...]``.  Bind that tag to both
            # endpoints, but only when the characters between them are a pure
            # range delimiter; do not broaden source/calc associations.
            if not assumptions and match_index + 1 < len(matches):
                following = matches[match_index + 1]
                between = visible[match.end():following.start()]
                if re.fullmatch(r'\s*(?:[-–—~～]|至)\s*', between):
                    after_following = (
                        matches[match_index + 2].start()
                        if match_index + 2 < len(matches) else len(stripped)
                    )
                    assumptions = assumption_specs(
                        stripped, following.end(), after_following
                    )
            meta_context = (
                in_yaml_block
                or any(current_section.startswith(section) for section in META_SECTIONS)
                or bool(META_LINE_PATTERN.search(stripped))
                or bool(re.match(r'^#{1,6}\s+', stripped))
                or bool(table_headers and any(
                    re.search(r'评分|权重|贡献', header) for header in table_headers
                ))
            )
            if (is_integer and -10 <= value <= 10 and not unit and not sources and not specs
                    and not assumptions
                    and not DATA_LINE_PATTERN.search(stripped)):
                continue
            if (is_integer and not unit and not sources and not specs and not assumptions
                    and re.search(r'评分|序号|编号|^#$', table_header)):
                continue
            category = 'assumption' if assumptions else ('data' if (
                sources or specs
                or ((unit or abs(value) > 10 or DATA_LINE_PATTERN.search(stripped))
                    and not meta_context)
            ) else 'meta')
            findings.append({
                'value': value, 'unit': unit, 'raw': match.group(0).strip(),
                'context': stripped[:220], 'section': current_section, 'line': line_no,
                'category': category, 'declared_sources': sources, 'calculation_specs': specs,
                'assumptions': assumptions,
                'local_prefix': visible[
                    matches[match_index - 1].end() if match_index else 0:match.start()
                ][-80:],
            })
    return findings


def detect_unsourced(text: str, source_map: dict | None = None) -> list[dict]:
    findings = []
    for line_no, line in enumerate(text.splitlines(), 1):
        declared = explicit_sources(line)
        for spec in calculation_specs(line):
            declared.extend(spec.get('inputs', []))
        for pattern, label in UNSOURCED_PATTERNS:
            if pattern.search(line):
                allowed = False
                if label == '行业对比无来源':
                    industry_paths = [path for path in declared if path.startswith('industry.')]
                    allowed = bool(industry_paths)
                    if allowed and source_map is not None:
                        for path in industry_paths:
                            metric = re.match(
                                r'^industry\.industry_stats\.([^.]+)\.(?:mean|median|p25|p75)$',
                                path,
                            )
                            if metric:
                                count = source_map.get(
                                    f"industry.industry_stats.{metric.group(1)}.count"
                                )
                                if not count or count[0] < 5:
                                    allowed = False
                                    break
                elif label == '历史断言无逐年核对':
                    relevant = [
                        path for path in declared
                        if path.startswith(('annual.', 'quarterly.', 'balance.', 'indicators.'))
                    ]
                    groups = {}
                    for path in relevant:
                        normalized = re.sub(r'\[\d+\]', '[*]', path)
                        indexes = tuple(re.findall(r'\[(\d+)\]', path))
                        groups.setdefault(normalized, set()).add(indexes)
                    allowed = any(len(indexes) >= 2 for indexes in groups.values())
                    if allowed and source_map is not None:
                        allowed = any(
                            len(indexes) >= 2
                            and {
                                path for path in source_map
                                if re.sub(r'\[\d+\]', '[*]', path) == normalized
                            } <= set(relevant)
                            for normalized, indexes in groups.items()
                        )
                if not allowed:
                    findings.append({'line': line_no, 'label': label, 'context': line.strip()[:160]})
    return findings


def detect_qualitative_contradictions(text: str, data: dict) -> list[dict]:
    """防止用中文“零/无/强劲”绕开数字门禁并把未知值写成事实。"""
    conditions = []
    balance = data.get("balance", {})
    quarterly = data.get("quarterly", {})
    macro = data.get("macro", {})
    if balance.get("goodwill_yi") is None:
        conditions.append((re.compile(r'(?:零商誉|无商誉|商誉为零)'), "商誉未知却断言为零"))
    if balance.get("interest_debt_yi") is None:
        conditions.append((re.compile(r'(?:无有息负债|有息负债为零)'), "有息负债未知却断言为零"))
    if not quarterly.get("ttm_complete") or quarterly.get("fcf_ttm_yi") is None:
        conditions.append((re.compile(r'(?:自由现金流|FCF).{0,12}(?:稳定|充裕|强劲|改善)'), "FCF 不完整却做强结论"))
    if not macro.get("indicators"):
        conditions.append((re.compile(r'(?:强复苏|宏观.{0,8}强劲|已进入繁荣)'), "宏观数据缺失却做强周期结论"))
    if data.get("meta", {}).get("cross_validated") is not True:
        conditions.append((re.compile(r'(?:双源|交叉)验证(?:已)?通过'), "未完成双源交叉验证却宣称通过"))
    hedge = re.compile(r'不能|不会|无法|未知|不可得|未披露|未将|未视为|并非|不是|不代表|不等于|禁止')
    findings = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for clause in re.split(r'[。；;!?！？，,]', line):
            if hedge.search(clause):
                continue
            for pattern, label in conditions:
                if pattern.search(clause):
                    findings.append({"line": line_no, "label": label, "context": clause.strip()[:160]})
    return findings


def verify_number(finding: dict, source_map: dict) -> dict:
    local_prefix = re.split(r'[。；;|]', finding.get('local_prefix', ''))[-1]
    raw_semantic_matches = [
        (match.span(), allowed)
        for pattern, allowed in SEMANTIC_PATH_RULES
        if (match := pattern.search(local_prefix))
    ]
    semantic_matches = [
        allowed for (start, end), allowed in raw_semantic_matches
        if not any(
            other_start <= start and end <= other_end
            and (other_start, other_end) != (start, end)
            for (other_start, other_end), _ in raw_semantic_matches
        )
    ]

    def semantic_ok(path: str) -> bool:
        # 同一局部片段同时出现多个字段名时语义不唯一，不做猜测；
        # 单一明确标签则防止“营收引净利润路径”这类同值错配。
        if not semantic_matches:
            return True
        if len(semantic_matches) != 1:
            return False
        lower = path.lower()
        return any(token in lower for token in semantic_matches[0])

    def source_quality_ok(path: str) -> bool:
        match = re.match(
            r'^industry\.industry_stats\.([^.]+)\.(?:mean|median|p25|p75)$', path
        )
        if match:
            count = source_map.get(
                f"industry.industry_stats.{match.group(1)}.count"
            )
            return bool(count and count[0] >= 5)
        rank = re.match(r'^industry\.target\.([^.]+)_rank_pct$', path)
        if rank:
            count = source_map.get(
                f"industry.industry_stats.{rank.group(1)}.count"
            )
            return bool(count and count[0] >= 5)
        return True

    exact_matches = []
    for path in finding['declared_sources']:
        item = source_map.get(path)
        if (item and units_compatible(finding['unit'], item[1])
                and values_match(finding['value'], item[0], finding.get('raw', ''))
                and semantic_ok(path) and source_quality_ok(path)):
            exact_matches.append({'path': path, 'value': item[0], 'unit': item[1]})
    if exact_matches:
        return {**finding, 'trace_status': 'DIRECT', 'sources': exact_matches}

    for spec in finding['calculation_specs']:
        inputs = spec.get('inputs', [])
        if len(inputs) == 1 and not semantic_ok(inputs[0]):
            continue
        if not all(source_quality_ok(path) for path in inputs):
            continue
        calculated = evaluate_calculation(spec, source_map)
        if (calculated is not None
                and units_compatible(finding['unit'], calculation_unit(spec, source_map))
                and values_match(finding['value'], calculated, finding.get('raw', ''))):
            return {**finding, 'trace_status': 'DERIVED',
                    'sources': spec['inputs'], 'calculated_value': calculated}

    # 仅作诊断提示；同值不同语义不能通过发布门禁。
    candidates = []
    for path, (value, unit) in source_map.items():
        if (units_compatible(finding['unit'], unit)
                and values_match(finding['value'], value, finding.get('raw', ''))):
            candidates.append(path)
    return {**finding, 'trace_status': 'UNTRACED', 'value_only_candidates': candidates[:3]}


def checklist_summary(results: dict) -> dict:
    percentages = {}
    done_counts = {}
    for expert_id, result in results.items():
        total = result.get('total', 0)
        percentages[expert_id] = round(result.get('covered', 0) / total * 100, 1) if total else 0.0
        done_counts[expert_id] = sum(
            item.get('found') and item.get('status') == 'DONE'
            for item in result.get('items', [])
        )
    return {
        'by_expert': percentages,
        'done_by_expert': done_counts,
        'minimum_pct': min(percentages.values(), default=0.0),
        'minimum_done': min(done_counts.values(), default=0),
    }


def verify(report_path: str, data_path: str | None = None) -> dict:
    report = Path(report_path)
    if not report.exists():
        return {'error': f'报告文件不存在: {report}'}
    text = report.read_text(encoding='utf-8')
    code_match = re.search(r'(\d{6}\.(?:SH|SZ|BJ))', text)
    ts_code = code_match.group(1) if code_match else (report.stem if re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)', report.stem) else None)
    if data_path is None and ts_code:
        data_path = f'/tmp/invest_data_{ts_code}.json'
    if not data_path or not Path(data_path).exists():
        return {'error': f'同批次数据快照不存在: {data_path or "unknown"}'}
    try:
        data = json.loads(Path(data_path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return {'error': f'数据快照不可读: {exc}'}
    quality = data.get('data_quality', {})
    envelope_problems = quality_envelope_errors(data)
    if envelope_problems:
        return {'error': '数据快照质量状态非法/未通过: ' + '; '.join(envelope_problems),
                'data_quality': quality}
    try:
        reference_date = datetime.strptime(str(data.get('meta', {}).get('analysis_date') or ''), '%Y%m%d')
    except ValueError:
        return {'error': f"meta.analysis_date 非法: {data.get('meta', {}).get('analysis_date')!r}"}
    recomputed = validate_snapshot(data, reference_date=reference_date)
    if any(quality.get(key) != recomputed.get(key) for key in ('status', 'errors', 'warnings')):
        return {'error': 'data_quality 与重算结果不一致', 'declared': quality, 'recomputed': recomputed}

    identity_issues = []
    snapshot_codes = {
        str(data.get(section, {}).get('ts_code'))
        for section in ('stock_info', 'market') if data.get(section, {}).get('ts_code')
    }
    if not ts_code:
        identity_issues.append('报告正文缺少规范股票代码')
    else:
        try:
            ts_code = normalize_ts_code(ts_code)
        except ValueError as exc:
            identity_issues.append(str(exc))
    if len(snapshot_codes) != 1 or (ts_code and snapshot_codes != {ts_code}):
        identity_issues.append(f'报告/快照股票代码不一致: report={ts_code}, snapshot={sorted(snapshot_codes)}')
    _, batch_id = snapshot_identity(data)
    report_batches = set(re.findall(r'^\s*batch_id\s*:\s*["\']?([0-9a-f]{16,64})["\']?\s*$', text, re.MULTILINE | re.IGNORECASE))
    if not batch_id:
        identity_issues.append('数据快照缺少 batch_id')
    elif report_batches != {batch_id}:
        identity_issues.append(f'报告 batch_id 与快照不一致: report={sorted(report_batches)}, snapshot={batch_id}')
    data_file = Path(data_path)
    archived_annual = data_file.with_name(data_file.name.replace('invest_data_', 'invest_annual_')).with_suffix('.txt')
    annual_file = archived_annual if archived_annual.is_file() else Path(f'/tmp/invest_annual_{ts_code}.txt')
    if not annual_file.is_file():
        identity_issues.append(f'同批次年报快照不存在: {annual_file}')
    else:
        prompt_paths = {
            f"invest_prompt_{ts_code}_{expert_id}.txt": data_file.with_name(
                f"invest_prompt_{ts_code}_{expert_id}.txt"
            )
            for expert_id in EXPERT_IDS
        }
        missing_prompts = [name for name, path in prompt_paths.items() if not path.is_file()]
        if missing_prompts:
            identity_issues.append(f'同批次 prompt 缺失: {missing_prompts}')
        prompts = (
            {name: path.read_bytes() for name, path in prompt_paths.items()}
            if not missing_prompts else None
        )
        identity_issues.extend(validate_batch_metadata(
            data, annual_file.read_text(encoding='utf-8'), WIKI_ROOT,
            [PROMPT_CONTRACT_PATH, CHECKLIST_PATH, EVIDENCE_RULES_PATH, EXPERTS_PATH],
            prompts=prompts,
        ))

    source_map = flatten_json(data)
    numbers = extract_numbers(text)
    checked = [verify_number(item, source_map) for item in numbers]
    data_numbers = [item for item in checked if item['category'] == 'data']
    traced = [item for item in data_numbers if item['trace_status'] in ('DIRECT', 'DERIVED')]
    untraced = [item for item in data_numbers if item['trace_status'] == 'UNTRACED']
    unsourced = detect_unsourced(text, source_map)
    unsourced.extend(detect_qualitative_contradictions(text, data))

    date_issues = []
    trade_date = str(data.get('market', {}).get('trade_date') or '')
    if trade_date:
        try:
            parsed = datetime.strptime(trade_date.replace('-', ''), '%Y%m%d')
            analysis_date = reference_date.strftime('%Y%m%d')
            age = (reference_date - parsed).days
            if not 0 <= age <= 7:
                date_issues.append(f'数据基准日 {trade_date} 与分析时点 {analysis_date} 相差 {age} 天')
        except ValueError:
            date_issues.append(
                f'交易日期或分析时点格式非法: trade_date={trade_date}, '
                f"analysis_date={data.get('meta', {}).get('analysis_date')}"
            )

    checklist = verify_checklist(text)
    checklist_stats = checklist_summary(checklist)
    trace_pct = round(len(traced) / len(data_numbers) * 100, 1) if data_numbers else 0.0
    if (trace_pct >= 90 and not untraced and not unsourced and not date_issues
            and not identity_issues and checklist_stats['minimum_pct'] >= 80
            and checklist_stats['minimum_done'] >= 1):
        verdict = 'PASS'
    elif trace_pct >= 75 and checklist_stats['minimum_pct'] >= 60:
        verdict = 'FLAGGED'
    else:
        verdict = 'FAIL'
    return {
        'ts_code': ts_code, 'report_path': str(report), 'data_path': str(data_path),
        'verdict': verdict,
        'stats': {
            'data_numbers': len(data_numbers), 'traced': len(traced),
            'trace_coverage_pct': trace_pct, 'untraced': len(untraced),
            'unsourced_assertions': len(unsourced), 'date_issues': len(date_issues),
            'identity_issues': len(identity_issues),
            'checklist_minimum_pct': checklist_stats['minimum_pct'],
            'checklist_minimum_done': checklist_stats['minimum_done'],
        },
        'untraced': untraced, 'unsourced': unsourced, 'date_issues': date_issues,
        'identity_issues': identity_issues,
        'checklist': checklist, 'checklist_summary': checklist_stats,
    }


def print_report(result: dict) -> None:
    if 'error' in result:
        print(f"✗ {result['error']}")
        return
    stats = result['stats']
    print(f"\n报告事实核查 — {result['ts_code'] or '未知'}")
    print(f"数据断言溯源: {stats['traced']}/{stats['data_numbers']} ({stats['trace_coverage_pct']}%)")
    print(f"未溯源断言: {stats['untraced']}；无来源表述: {stats['unsourced_assertions']}；"
          f"日期问题: {stats['date_issues']}；身份问题: {stats['identity_issues']}")
    for item in result['untraced'][:20]:
        hint = ', '.join(item.get('value_only_candidates', [])) or '无同值候选'
        print(f"  ✗ L{item['line']} {item['raw']} — {item['context'][:100]}（仅同值候选: {hint}）")
    for item in result['unsourced'][:10]:
        print(f"  ⚠ L{item['line']} [{item['label']}] {item['context']}")
    for issue in result['date_issues']:
        print(f"  ⚠ {issue}")
    for issue in result.get('identity_issues', []):
        print(f"  ✗ {issue}")
    print_checklist_report(result['checklist'])
    print(f"\n综合判定: {result['verdict']}")


def main() -> int:
    parser = argparse.ArgumentParser(description='报告可溯源性验证')
    parser.add_argument('report_path')
    parser.add_argument('--data')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--strict', action='store_true', help='非 PASS 时返回非零退出码')
    args = parser.parse_args()
    result = verify(args.report_path, args.data)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)
    if not args.strict:
        return 0
    if 'error' in result or result.get('verdict') == 'FAIL':
        return 2
    return 0 if result.get('verdict') == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
