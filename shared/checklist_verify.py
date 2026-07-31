"""方法论清单验证 — 独立模块，供 verify_report.py 导入。"""
import json
import re
from pathlib import Path
# L4: 方法论清单覆盖率（v2 — 魔鬼代言人第一级）
# ═══════════════════════════════════════════════════════════════

def load_checklist():
    """加载专家必检项清单。"""
    cp = Path(__file__).resolve().parents[1] / "data" / "expert_checklist.json"
    if cp.exists():
        data = json.loads(cp.read_text(encoding="utf-8"))
        for expert_id, info in data.items():
            declared = info.get("total")
            actual = len(info.get("items", []))
            if declared != actual:
                raise ValueError(f"{expert_id} checklist total={declared}，实际 items={actual}")
        return data
    return {}


def load_evidence_rules():
    path = Path(__file__).resolve().parents[1] / "data" / "checklist_evidence_rules.json"
    if not path.is_file():
        raise ValueError(f"必检项证据规则缺失: {path}")
    rules = json.loads(path.read_text(encoding="utf-8"))
    checklist = load_checklist()
    for expert_id, info in checklist.items():
        expected = set(info.get("items", []))
        actual = set(rules.get(expert_id, {}))
        if actual != expected:
            raise ValueError(
                f"{expert_id} 证据规则与 checklist 不一致: "
                f"missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
            )
    return rules

def check_expert_coverage(expert_id: str, expert_text: str, checklist: dict) -> dict:
    """检查单个专家的必检项覆盖率。返回 {item, found, keywords} 列表。"""
    if expert_id not in checklist:
        return {"expert_id": expert_id, "items": [], "covered": 0, "total": 0}
    
    info = checklist[expert_id]
    evidence_rules = load_evidence_rules().get(expert_id, {})
    items = info["items"]
    total = len(items)
    
    results = []
    covered = 0
    for item in items:
        # 新版 prompt 要求稳定表格行；只有原样项目名 + DONE + 非占位证据才算覆盖。
        row = re.search(
            rf'^\|\s*{re.escape(item)}\s*\|\s*(DONE|MISSING)\s*\|\s*([^|]+)\|\s*([^|]+)\|',
            expert_text,
            re.MULTILINE | re.IGNORECASE,
        )
        evidence = row.group(2).strip() if row else ""
        conclusion = row.group(3).strip() if row else ""
        status = row.group(1).upper() if row else ""
        placeholders = ("JSON.path", "年报:年份", "一句话结论", "待填写", "…", "...")
        json_locator = re.search(
            r'[A-Za-z_][\w-]*(?:\[\d+\])?(?:\.[A-Za-z_][\w-]*(?:\[\d+\])?)+',
            evidence,
        )
        document_locator = re.search(r'(?:年报|wiki):[^|`\s]+', evidence, re.IGNORECASE)
        substantive_conclusion = len(re.sub(r'[`*_\s]', '', conclusion)) >= 4
        semantic_text = (evidence + " " + conclusion).lower()
        latin_terms = [term.lower() for term in re.findall(r'[A-Za-z]{2,}', item)]
        chinese_chunks = re.findall(r'[\u4e00-\u9fff]{2,}', item)
        generic_bigrams = {
            "检查", "分析", "评估", "记录", "趋势", "判断", "专项",
            "框架", "视角", "检验", "速览", "合理", "深度", "最终",
        }
        chinese_terms = {
            chunk[index:index + 2]
            for chunk in chinese_chunks for index in range(len(chunk) - 1)
            if chunk[index:index + 2] not in generic_bigrams
        }
        semantic_match = any(term in semantic_text for term in latin_terms) or any(
            term in semantic_text for term in chinese_terms
        )
        # 证据语义规则只检查可验证的 JSON/文档定位原子，
        # 不允许在定位后随手追加关键词骗过项目约束。
        evidence_atoms = re.findall(
            r'[A-Za-z_][\w-]*(?:\[\d+\])?(?:\.[A-Za-z_][\w-]*(?:\[\d+\])?)+'
            r'|(?:年报|wiki):[^|`\s]+',
            evidence, re.IGNORECASE,
        )
        evidence_lower = " ".join(evidence_atoms).lower()
        rule_groups = evidence_rules.get(item, [])
        evidence_rule_match = bool(rule_groups) and all(
            any(str(token).lower() in evidence_lower for token in group)
            for group in rule_groups
        )
        valid_record = bool(
            row and evidence and conclusion and (json_locator or document_locator)
            and substantive_conclusion
            and semantic_match
            and evidence_rule_match
            and not any(marker in evidence or marker in conclusion for marker in placeholders)
        )
        # 准出覆盖率衡量“已执行”，不是“已诚实声明没做”。
        # 数据不可得时，如果专家已检查可用证据并说明降级影响，
        # 应标 DONE；MISSING 始终保留为未完成项，不计入 80% 门禁。
        found = valid_record and status == "DONE"
        if found:
            covered += 1
        results.append({"item": item, "found": found, "status": status,
                        "evidence": evidence, "conclusion": conclusion})
    
    return {"expert_id": expert_id, "items": results, "covered": covered, "total": total}

def _extract_keywords(item_name: str) -> list:
    """从必检项名称提取搜索关键词。"""
    # 英文缩写直接保留
    abbrs = re.findall(r'[A-Z]{2,}(?:/[A-Z]{2,})*', item_name)
    # 中文关键词：分割括号、数字、标点后的核心词组
    clean = re.sub(r'[（(].*?[)）]', '', item_name)  # 去掉括号内容
    clean = re.sub(r'\d+[\.\、\s]', '', clean)  # 去掉序号
    parts = re.split(r'[/\s·]+', clean)
    keywords = [p.strip() for p in parts if len(p.strip()) >= 2]
    return abbrs + keywords

def verify_checklist(report_text: str) -> dict:
    """对报告中每位专家做必检项覆盖率检查。"""
    checklist = load_checklist()
    if not checklist:
        return {"error": "checklist 数据不可用，请运行 python3 scripts/generate_checklist.py"}

    # 分割报告为各专家段落
    expert_sections = {}
    current_expert = None
    current_text = []
    
    # Expert IDs in order
    expert_map = {
        "financial-auditor": "财务排雷官",
        "value-valuator": "价值估值师",
        "growth-assessor": "成长质量师",
        "moat-analyst": "护城河分析师",
        "cognitive-controller": "认知风控官",
        "macro-cyclist": "宏观周期师",
        "management-auditor": "管理层审计师",
    }
    
    for line in report_text.split('\n'):
        # Detect expert section by matching expert_id in frontmatter
        for eid, cname in expert_map.items():
            if re.search(rf'^\s*expert_id\s*:\s*["\']?{re.escape(eid)}["\']?\s*$', line):
                if current_expert and current_text:
                    previous = expert_sections.get(current_expert, "")
                    expert_sections[current_expert] = previous + "\n" + '\n'.join(current_text)
                current_expert = eid
                current_text = []
                break
        if current_expert:
            current_text.append(line)
    
    if current_expert and current_text:
        previous = expert_sections.get(current_expert, "")
        expert_sections[current_expert] = previous + "\n" + '\n'.join(current_text)
    
    # Check each expert
    results = {}
    for eid in expert_map:
        text = expert_sections.get(eid, "")
        results[eid] = check_expert_coverage(eid, text, checklist)
    
    return results

def print_checklist_report(checklist_results: dict):
    """打印必检项覆盖率报告。"""
    if "error" in checklist_results:
        print(f"\n[L4] 方法检查单: {checklist_results['error']}")
        return
    
    print(f"\n[L4] 方法论必检项覆盖率：")
    print(f"{'专家':<25s} {'覆盖':>5s}  {'缺失项':>6s}")
    print("-" * 60)
    
    all_missing = []
    for eid, r in checklist_results.items():
        covered = r["covered"]
        total = r["total"]
        missing = [i["item"] for i in r["items"] if not i["found"]]
        pct = f"{covered}/{total}"
        print(f"{eid:<25s} {pct:>5s}  {str(len(missing)):>6s} 项")
        for m in missing:
            print(f"  ✗ {m}")
            all_missing.append((eid, m))
    
    total_coverage = sum(r["covered"] for r in checklist_results.values())
    total_items = sum(r["total"] for r in checklist_results.values())
    print(f"\n  总覆盖率: {total_coverage}/{total_items} ({round(total_coverage/total_items*100,1)}%)")
    print(f"  缺失项总数: {len(all_missing)}")
