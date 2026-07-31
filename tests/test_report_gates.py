import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.assemble_report import (
    evaluate_level3, validate_adjudication, validate_devil_challenge,
    validate_self_review,
)
from scripts.collect_challenges import validate_challenge
from scripts.collect_cross_reviews import (
    CROSS_REVIEWERS, build_aggregate, input_bundle_hash,
    validate_cross_aggregate,
)
from scripts.collect_results import (
    _annual_locator_section_text, _meaningful_table_rows, _verified_narrative_rows,
)
from scripts.prepare_cross_reviews import expected_cross_prompt
from scripts.verify_report import (
    calculation_specs, detect_unsourced, explicit_sources, extract_numbers, flatten_json,
    verify, verify_number,
)
from scripts.verify_manifest import verify as verify_manifest
from scripts.verify_manifest import EXPERTS as MANIFEST_EXPERTS
from shared.batch_contract import (
    batch_id_from_components, canonical_data_hash, compute_batch_metadata,
    contract_snapshot_hash, prompt_bundle_hash, validate_batch_metadata,
    wiki_snapshot_hash,
)
from shared.checklist_verify import check_expert_coverage, load_checklist
from shared.review_contracts import challenge_prompt_hash, cross_prompt_hash


class ReportGateTests(unittest.TestCase):
    def test_six_digit_business_fact_is_not_hidden_as_stock_code(self):
        facts = extract_numbers("营收为123456元，用户数123456")
        self.assertEqual([(item["value"], item["category"]) for item in facts], [
            (123456.0, "data"), (123456.0, "data"),
        ])
        self.assertEqual(extract_numbers("股票代码：603605；标的 603605.SH"), [])

    def test_challenge_prompt_hash_binds_prompt_bytes(self):
        raw = b'challenge_prompt_hash: "__PROMPT_HASH__"\nquestion=A'
        digest = challenge_prompt_hash(raw)
        bound = raw.replace(b"__PROMPT_HASH__", digest.encode())
        self.assertEqual(challenge_prompt_hash(bound), digest)
        self.assertNotEqual(
            challenge_prompt_hash(bound.replace(b"question=A", b"question=B")),
            digest,
        )

    def test_prompt_bundle_hash_normalizes_batch_id_after_embedded_yaml(self):
        sentinel = "__BATCH_ID_PLACEHOLDER__"
        batch_id = "abcdef0123456789abcdef01"
        prompt = (
            "## 方法论\n\n---\ntitle: method\n---\n\n"
            "```yaml\n---\n"
            f'batch_id: "{sentinel}"\n'
            "---\n```\n"
        )
        first = prompt_bundle_hash({"p": prompt}, sentinel)
        second = prompt_bundle_hash(
            {"p": prompt.replace(sentinel, batch_id)}, batch_id
        )
        self.assertEqual(first, second)

    def test_checklist_declared_totals_match_items(self):
        checklist = load_checklist()
        for info in checklist.values():
            self.assertEqual(info["total"], len(info["items"]))

    def test_keyword_mention_does_not_satisfy_checklist(self):
        checklist = load_checklist()
        expert_id = "financial-auditor"
        item = checklist[expert_id]["items"][0]
        result = check_expert_coverage(expert_id, f"正文顺带提到 {item}", checklist)
        self.assertEqual(result["covered"], 0)

    def test_exact_done_row_requires_real_evidence(self):
        checklist = load_checklist()
        expert_id = "financial-auditor"
        item = checklist[expert_id]["items"][0]
        valid = (
            f"| {item} | DONE | `quarterly.ocf_ttm_yi`; "
            "`annual.annual_data[0].net_profit_yi` | OCF/NI 已核对 |"
        )
        invalid = f"| {item} | DONE | `JSON.path` | 一句话结论 |"
        self.assertEqual(check_expert_coverage(expert_id, valid, checklist)["covered"], 1)
        self.assertEqual(check_expert_coverage(expert_id, invalid, checklist)["covered"], 0)

    def test_honest_missing_row_never_counts_as_executed(self):
        checklist = load_checklist()
        expert_id = "management-auditor"
        item = checklist[expert_id]["items"][0]
        valid = (
            f"| {item} | MISSING | `audit.history[0].audit_result` | "
            "处罚资料不全，不能形成完整结论 |"
        )
        invalid = f"| {item} | MISSING | 无 | 资料不全 |"
        self.assertEqual(check_expert_coverage(expert_id, valid, checklist)["covered"], 0)
        self.assertEqual(check_expert_coverage(expert_id, invalid, checklist)["covered"], 0)

    def test_real_parentheses_in_narrative_rows_are_not_placeholders(self):
        text = """## 叙事–数据交叉验证

| # | 论述 | 证据 |
|---|---|---|
| 1 | 毛利改善（年报:2025/annual/经营情况讨论与分析） | `annual.annual_data[0].revenue_yi` |
| 2 | 库存下降（年报:2025/annual/经营情况讨论与分析） | `balance.inventories_yi` |
| 3 | 现金充裕（年报:2025/annual/经营情况讨论与分析） | `balance.cash_yi` |
"""
        self.assertEqual(_meaningful_table_rows(text, "## 叙事–数据交叉验证"), 3)

    def test_annual_locator_returns_section_body_not_empty_tail(self):
        annual = """### 2025年 annual（公告日：20260430）
#### 公司治理
管理层承诺与治理正文
#### 重要事项
其他正文
"""
        section = _annual_locator_section_text("年报:2025/annual/公司治理", annual)
        self.assertIn("管理层承诺与治理正文", section)
        self.assertNotIn("其他正文", section)

    def test_duplicate_narrative_evidence_counts_once(self):
        annual = """### 2025年 annual（公告日：20260430）
#### 经营情况讨论与分析
公司坚持长期主义推动品牌建设并持续优化产品结构。
"""
        row = (
            "| 1 | “公司坚持长期主义推动品牌建设”（年报:2025/annual/经营情况讨论与分析） | "
            "`annual.annual_data[0].revenue_yi` | ✅ | "
            "10亿 [source: annual.annual_data[0].revenue_yi] |"
        )
        text = "## 叙事–数据交叉验证\n\n" + "\n".join([row, row, row])
        self.assertEqual(_verified_narrative_rows(
            text, annual, {"annual.annual_data[0].revenue_yi"}
        ), 1)

    def test_same_value_wrong_unit_or_path_cannot_pass(self):
        source_map = flatten_json({"market": {"total_mv_yi": 100, "pe_ttm": 100}})
        finding = {
            "value": 100.0, "unit": "亿", "declared_sources": ["market.pe_ttm"],
            "calculation_specs": [], "category": "data", "raw": "100亿",
            "context": "", "section": "", "line": 1,
        }
        result = verify_number(finding, source_map)
        self.assertEqual(result["trace_status"], "UNTRACED")
        self.assertIn("market.total_mv_yi", result["value_only_candidates"])

    def test_exact_path_and_unit_pass(self):
        source_map = flatten_json({"market": {"total_mv_yi": 100}})
        finding = {
            "value": 100.0, "unit": "亿", "declared_sources": ["market.total_mv_yi"],
            "calculation_specs": [], "category": "data", "raw": "100亿",
            "context": "", "section": "", "line": 1,
        }
        self.assertEqual(verify_number(finding, source_map)["trace_status"], "DIRECT")

    def test_calculation_must_reproduce_reported_value(self):
        source_map = flatten_json({"annual": {"current_yi": 120, "previous_yi": 100}})
        base = {
            "unit": "%", "declared_sources": [], "category": "data", "raw": "20%",
            "context": "", "section": "", "line": 1,
            "calculation_specs": [{
                "formula": "(current/previous-1)*100",
                "inputs": ["annual.current_yi", "annual.previous_yi"],
            }],
        }
        self.assertEqual(verify_number({**base, "value": 20}, source_map)["trace_status"], "DERIVED")
        self.assertEqual(verify_number({**base, "value": 99}, source_map)["trace_status"], "UNTRACED")

    def test_array_paths_are_not_truncated(self):
        line = (
            "收入 100亿 [source: annual.annual_data[0].revenue_yi]；"
            "增速 20% [calc: (current/previous-1)*100; inputs: "
            "annual.annual_data[1].revenue_yi,annual.annual_data[0].revenue_yi]"
        )
        self.assertEqual(explicit_sources(line), ["annual.annual_data[0].revenue_yi"])
        self.assertEqual(calculation_specs(line)[0]["inputs"], [
            "annual.annual_data[1].revenue_yi", "annual.annual_data[0].revenue_yi",
        ])

    def test_large_unformatted_number_is_one_data_assertion(self):
        findings = extract_numbers("市值 1234.56亿 [source: market.total_mv_yi]")
        data = [item for item in findings if item["category"] == "data"]
        self.assertEqual([(item["value"], item["unit"]) for item in data], [(1234.56, "亿")])

    def test_large_integer_without_unit_is_data(self):
        findings = extract_numbers("PE 999")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["category"], "data")

    def test_each_number_only_uses_its_following_locator(self):
        findings = extract_numbers(
            "收入 100亿 [source: annual.profit_yi]；利润 5亿 [source: annual.revenue_yi]"
        )
        source_map = flatten_json({"annual": {"revenue_yi": 100, "profit_yi": 5}})
        checked = [verify_number(item, source_map) for item in findings]
        self.assertEqual([item["trace_status"] for item in checked], ["UNTRACED", "UNTRACED"])

    def test_calculation_result_unit_must_match(self):
        source_map = flatten_json({"annual": {"current_yi": 120, "previous_yi": 100}})
        finding = {
            "value": 20, "unit": "亿", "declared_sources": [], "category": "data",
            "raw": "20亿", "context": "", "section": "", "line": 1,
            "calculation_specs": [{
                "formula": "(current/previous-1)*100",
                "inputs": ["annual.current_yi", "annual.previous_yi"],
            }],
        }
        self.assertEqual(verify_number(finding, source_map)["trace_status"], "UNTRACED")

    def test_constant_formula_cannot_pretend_to_use_inputs(self):
        source_map = flatten_json({"annual": {"revenue_yi": 100}})
        finding = {
            "value": 999, "unit": "亿", "declared_sources": [], "category": "data",
            "raw": "999亿", "context": "", "section": "", "line": 1,
            "calculation_specs": [{"formula": "999", "inputs": ["annual.revenue_yi"]}],
        }
        self.assertEqual(verify_number(finding, source_map)["trace_status"], "UNTRACED")

    def test_near_values_cannot_swap_sources_outside_display_rounding(self):
        source_map = flatten_json({"annual": {"revenue_yi": 100.0, "profit_yi": 100.9}})
        findings = extract_numbers(
            "收入 100亿 [source: annual.profit_yi]；利润 101亿 [source: annual.revenue_yi]"
        )
        self.assertEqual(
            [verify_number(item, source_map)["trace_status"] for item in findings],
            ["UNTRACED", "UNTRACED"],
        )

    def test_unitless_financial_ratios_are_data(self):
        findings = extract_numbers("PE 8.5，PB 2.0，流动比率 1.2")
        self.assertEqual([item["category"] for item in findings], ["data", "data", "data"])

    def test_percentage_points_list_indexes_and_assumption_ranges(self):
        findings = extract_numbers(
            "1. GDP变化 -0.40 个百分点 [calc: current-previous; inputs: "
            "macro.current_pct,macro.previous_pct]\n"
            "2. 低 PE 不是安全边际\n"
            "仓位低配约 10—15 个百分点 [assumption: 相邻周期仓位差的压力估计]"
        )
        self.assertFalse(any(item["line"] == 2 for item in findings))
        first_line = [item for item in findings if item["line"] == 1]
        self.assertEqual([(item["value"], item["unit"]) for item in first_line], [(-0.4, "%")])
        range_items = [item for item in findings if item["line"] == 3]
        self.assertEqual([item["category"] for item in range_items], ["assumption", "assumption"])

    def test_challenge_question_numbers_are_metadata_not_company_facts(self):
        findings = extract_numbers(
            "## 质询问题\n\n1. 如果行业基准调严 20%，结论是否变化？"
        )
        self.assertFalse(any(item["category"] == "data" for item in findings))

    def test_adjudication_reason_financial_number_is_not_hidden_as_metadata(self):
        findings = extract_numbers(
            "## 综合裁决 — 裁判长\n\n### 裁决理由\n\n"
            "公司营收为 999亿，但没有给出数据定位。"
        )
        data = [item for item in findings if item["category"] == "data"]
        self.assertEqual([(item["value"], item["unit"]) for item in data], [(999.0, "亿")])

    def test_adjudication_yaml_subscores_remain_metadata(self):
        findings = extract_numbers(
            "## 综合裁决 — 裁判长\n\n```yaml\n"
            "financial_auditor: { score: 80, verdict: PASS }\n```\n"
        )
        self.assertTrue(findings)
        self.assertTrue(all(item["category"] == "meta" for item in findings))

    def test_adjudication_weight_table_remains_metadata(self):
        findings = extract_numbers(
            "| 专家 | 评分 | 权重 | 贡献 |\n"
            "|---|---:|---:|---:|\n"
            "| financial-auditor | 80 | 0.25 | 20.00 |"
        )
        self.assertFalse(any(item["category"] == "data" for item in findings))

    def test_irrelevant_source_does_not_suppress_industry_claim(self):
        self.assertTrue(detect_unsourced("行业平均明显更低 [source: market.close]"))
        self.assertEqual(
            detect_unsourced("行业平均为 10% [source: industry.industry_stats.roe_pct.mean]"),
            [],
        )

    def test_verify_rejects_unknown_quality_and_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "000001.SZ.md"
            report.write_text("# 测试（000001.SZ）\nbatch_id: deadbeefdeadbeef\n", encoding="utf-8")
            data = root / "data.json"
            data.write_text(json.dumps({
                "stock_info": {"ts_code": "000001.SZ"},
                "market": {"ts_code": "000001.SZ", "trade_date": "20200102"},
                "meta": {"analysis_date": "20200103", "batch_id": "deadbeefdeadbeef"},
                "data_quality": {"status": "BOGUS"},
            }), encoding="utf-8")
            self.assertIn("error", verify(str(report), str(data)))

    def test_batch_hash_detects_data_annual_wiki_and_prompt_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wiki = root / "wiki"
            wiki.mkdir()
            (wiki / "method.md").write_text("方法 A", encoding="utf-8")
            contract = root / "prompt.py"
            checklist = root / "checklist.json"
            contract.write_text("prompt-v1", encoding="utf-8")
            checklist.write_text("{}", encoding="utf-8")
            data = {"market": {"close": 10}, "meta": {}}
            data["meta"].update(compute_batch_metadata(
                data, "annual-v1", wiki, [contract, checklist]
            ))
            self.assertEqual(validate_batch_metadata(
                data, "annual-v1", wiki, [contract, checklist]
            ), [])
            data["market"]["close"] = 11
            self.assertTrue(validate_batch_metadata(
                data, "annual-v1", wiki, [contract, checklist]
            ))

    def test_historical_freshness_uses_snapshot_analysis_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "000001.SZ.md"
            report.write_text("# 测试（000001.SZ）\nbatch_id: deadbeefdeadbeef\n", encoding="utf-8")
            data = root / "data.json"
            data.write_text(json.dumps({
                "stock_info": {"ts_code": "000001.SZ"},
                "market": {"ts_code": "000001.SZ", "trade_date": "20200102"},
                "meta": {"analysis_date": "20200103", "batch_id": "deadbeefdeadbeef"},
                "data_quality": {"status": "PASS", "errors": [], "warnings": []},
            }), encoding="utf-8")
            with patch("scripts.verify_report.validate_snapshot", return_value={
                "status": "PASS", "errors": [], "warnings": [],
            }):
                result = verify(str(report), str(data))
            self.assertEqual(result["date_issues"], [])

    def test_self_review_requires_exact_section_and_pass_line(self):
        valid = """## 综合裁决 — 裁判长

裁决正文。

## 结构化自评审

| 维度 | 得分 |
|---|---:|
| 数据可追溯性 | 20 / 25 |
| 方法论忠实度 | 20 / 25 |
| 裁判诚实性与一致性 | 20 / 25 |
| 逻辑与表述 | 12 / 15 |

### 扣分明细
- 数据缺口扣分。

**总分：72 / 90**

**判定：PASS**
"""
        self.assertEqual(validate_self_review(valid), [])
        self.assertTrue(validate_self_review("**总分：72 / 90**\nBYPASS"))
        self.assertTrue(validate_self_review(
            "## 结构化自评审\n\n**总分：91 / 90**\n\n**判定：PASS**"
        ))

    def test_adjudication_yaml_is_structurally_validated(self):
        valid = """## 综合裁决 — 裁判长

```yaml
---
adjudicator:
  verdict: BUY
  composite_score: 80
  conflicts: []
  vetoes_triggered: []
  review_resolutions: []
  position_advice:
    max_allocation_pct: 10
    entry_strategy: 分批建仓
    stop_conditions: [基本面恶化]
  watch_items: [收入增速]
  knowledge_refs: [index.md, experts/01-财务排雷官.md, experts/02-价值估值师.md]
---
```

### 裁决理由

七位专家的分析已完成数据、方法和风险交叉复核，没有发现需要触发一票否决的事项。裁决保留所有数据缺口，不把未知项目视为零，并明确说明各框架之间的分歧、评分计算过程及后续观察条件。估值、成长、现金流、治理和宏观判断均回到同一批次证据，结论可复核且不超出证据边界。

**加权评分计算过程**
"""
        self.assertEqual(validate_adjudication(valid), [])
        self.assertTrue(validate_adjudication(valid.replace("verdict: BUY", "verdict: MAYBE")))

    def test_manifest_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "artifacts" / "000001.SZ" / "run"
            archive.mkdir(parents=True)
            report = root / "000001.SZ.md"
            report.write_text(
                "# 报告\n<!-- artifact_manifest: artifacts/000001.SZ/run/manifest.json -->\n",
                encoding="utf-8",
            )
            annual_text = "可审计年报正文"
            wiki_snapshot = {"files": {"index.md": "测试 wiki"}}
            prompt_contract_files = [
                {"name": "prepare_prompts.py", "text": "prompt"},
                {"name": "expert_checklist.json", "text": "{}"},
                {"name": "checklist_evidence_rules.json", "text": "{}"},
                {"name": "experts.json", "text": "{}"},
            ]
            contract_bundle = {
                "prompt_contract_files": prompt_contract_files,
                "replay_files": {},
            }
            archived_data = {
                "market": {"trade_date": "20200102"},
                "meta": {
                    "analysis_date": "20200103",
                    "annual_hash": hashlib.sha256(annual_text.encode()).hexdigest(),
                    "wiki_hash": wiki_snapshot_hash(wiki_snapshot["files"]),
                    "prompt_contract_hash": contract_snapshot_hash(prompt_contract_files),
                },
            }
            archived_data["meta"]["data_hash"] = canonical_data_hash(archived_data)
            provisional_batch = batch_id_from_components(archived_data["meta"])
            provisional_prompts = {
                f"invest_prompt_000001.SZ_{expert}.txt":
                f"000001.SZ {expert} {provisional_batch}".encode()
                for expert in MANIFEST_EXPERTS
            }
            archived_data["meta"]["prompt_bundle_hash"] = prompt_bundle_hash(
                provisional_prompts, provisional_batch,
            )
            archived_data["meta"]["batch_id"] = batch_id_from_components(archived_data["meta"])
            batch_id = archived_data["meta"]["batch_id"]
            expert_texts = {
                expert: (
                    f"---\nexpert_id: {expert}\nts_code: 000001.SZ\n"
                    f"data_date: '20200102'\nanalysis_date: '20200103'\n"
                    f"batch_id: {batch_id}\n---\nresult {expert}"
                ) for expert in MANIFEST_EXPERTS
            }
            challenge_texts = {
                expert: f"challenge {expert}" for expert in MANIFEST_EXPERTS
            }
            level3 = {"triggered": False}
            level3_yaml = "level3:\n  triggered: false"
            draft_text = (
                "# 报告\n" + "\n".join(expert_texts.values()) + "\n"
                + "\n".join(challenge_texts.values())
                + f"\n### 第三级触发评估\n```yaml\n{level3_yaml}\n```\n"
            )
            report_text = (
                draft_text.rstrip()
                + "\n\n<!-- artifact_manifest: artifacts/000001.SZ/run/manifest.json -->\n"
            )
            report.write_text(report_text, encoding="utf-8")
            evidence_names = [
                "000001.SZ.md", "000001.SZ.draft.md",
                "invest_data_000001.SZ.json", "invest_annual_000001.SZ.txt",
                *[f"invest_prompt_000001.SZ_{expert}.txt" for expert in MANIFEST_EXPERTS],
                *[f"invest_result_000001.SZ_{expert}.md" for expert in MANIFEST_EXPERTS],
                *[f"invest_challenge_prompt_000001.SZ_{expert}.txt" for expert in MANIFEST_EXPERTS],
                *[f"invest_challenge_result_000001.SZ_{expert}.md" for expert in MANIFEST_EXPERTS],
                "invest_level3_000001.SZ.json",
                "wiki_snapshot.json", "contract_bundle.json",
            ]
            for name in evidence_names:
                content = report.read_bytes()
                if name == "invest_data_000001.SZ.json":
                    content = json.dumps(archived_data).encode()
                elif name == "invest_annual_000001.SZ.txt":
                    content = annual_text.encode()
                elif name == "000001.SZ.draft.md":
                    content = draft_text.encode()
                elif name == "000001.SZ.md":
                    content = report.read_bytes()
                elif name.startswith("invest_prompt_"):
                    expert = name.removeprefix("invest_prompt_000001.SZ_").removesuffix(".txt")
                    content = f"000001.SZ {expert} {batch_id}".encode()
                elif name.startswith("invest_result_"):
                    expert = name.removeprefix("invest_result_000001.SZ_").removesuffix(".md")
                    content = expert_texts[expert].encode()
                elif name.startswith("invest_challenge_prompt_"):
                    content = b"challenge prompt"
                elif name.startswith("invest_challenge_result_"):
                    expert = name.removeprefix(
                        "invest_challenge_result_000001.SZ_"
                    ).removesuffix(".md")
                    content = challenge_texts[expert].encode()
                elif name == "invest_level3_000001.SZ.json":
                    content = json.dumps(level3).encode()
                elif name == "wiki_snapshot.json":
                    content = json.dumps(wiki_snapshot).encode()
                elif name == "contract_bundle.json":
                    content = json.dumps(contract_bundle).encode()
                (archive / name).write_bytes(content)
            archived = archive / report.name
            manifest = {
                "ts_code": "000001.SZ",
                "run_id": "run",
                "contract_version": "0.5.1",
                "batch_id": batch_id,
                "files": [
                    {
                        "name": name,
                        "sha256": hashlib.sha256((archive / name).read_bytes()).hexdigest(),
                        "bytes": (archive / name).stat().st_size,
                    }
                    for name in evidence_names
                ],
            }
            (archive / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch("scripts.verify_manifest.REPORTS_DIR", root), patch(
                "scripts.verify_manifest.validate_expert", return_value=[]
            ), patch("scripts.verify_manifest.validate_challenge", return_value=[]):
                self.assertEqual(verify_manifest(str(report))["status"], "PASS")
                archived.write_text("tampered", encoding="utf-8")
                self.assertEqual(verify_manifest(str(report))["status"], "FAIL")

    def test_cancelled_or_identity_calculations_cannot_launder_numbers(self):
        source_map = flatten_json({"annual": {"profit": 20, "revenue": 100}})
        common = {
            "value": 20, "unit": "", "declared_sources": [], "category": "data",
            "raw": "20", "context": "", "section": "", "line": 1,
        }
        cancelled = {**common, "calculation_specs": [{
            "formula": "profit+revenue-revenue",
            "inputs": ["annual.profit", "annual.revenue"],
        }]}
        identity = {**common, "calculation_specs": [{
            "formula": "profit", "inputs": ["annual.profit"],
        }]}
        self.assertEqual(verify_number(cancelled, source_map)["trace_status"], "UNTRACED")
        self.assertEqual(verify_number(identity, source_map)["trace_status"], "UNTRACED")

    def test_legitimate_multi_input_ratio_remains_valid(self):
        source_map = flatten_json({"annual": {"profit": 20, "revenue": 100}})
        finding = {
            "value": 20, "unit": "%", "declared_sources": [], "category": "data",
            "raw": "20%", "context": "", "section": "", "line": 1,
            "calculation_specs": [{
                "formula": "current/previous*100",
                "inputs": ["annual.profit", "annual.revenue"],
            }],
        }
        self.assertEqual(verify_number(finding, source_map)["trace_status"], "DERIVED")

    def test_industry_qualitative_claim_requires_sample_of_five(self):
        line = "行业平均毛利率可参考中位数 [source: industry.industry_stats.gross_margin_pct.median]"
        small = flatten_json({"industry": {"industry_stats": {
            "gross_margin_pct": {"median": 50, "count": 4},
        }}})
        enough = flatten_json({"industry": {"industry_stats": {
            "gross_margin_pct": {"median": 50, "count": 5},
        }}})
        self.assertTrue(detect_unsourced(line, small))
        self.assertEqual(detect_unsourced(line, enough), [])

    def test_level3_machine_trigger_and_exact_embedding(self):
        scoring = {
            "weights": {
                "financial-auditor": .2, "value-valuator": .2,
                "growth-assessor": .15, "moat-analyst": .15,
                "management-auditor": .15, "macro-cyclist": .15,
            },
            "cognitive_adjustment": {"VETO": .5, "WARN": .8},
        }
        results = {}
        for index, expert in enumerate(MANIFEST_EXPERTS):
            verdict = "PASS" if index < 2 else ("VETO" if index == 2 else "WARN")
            results[expert] = f"---\nscore: 50\nverdict: {verdict}\n---\n"
        level3 = evaluate_level3(results, scoring)
        self.assertTrue(level3["triggered"])
        self.assertFalse(level3["industry_three_run_opposition"])
        self.assertEqual(
            level3["industry_history_status"],
            "MISSING_CURRENT_INDUSTRY_OR_DIRECTION",
        )

    def test_level3_three_verified_industry_oppositions_trigger(self):
        scoring = {
            "weights": {
                "financial-auditor": .2, "value-valuator": .2,
                "growth-assessor": .15, "moat-analyst": .15,
                "management-auditor": .15, "macro-cyclist": .15,
            },
            "cognitive_adjustment": {"VETO": .5, "WARN": .8},
        }
        directions = {expert: "POSITIVE" for expert in MANIFEST_EXPERTS}
        directions["value-valuator"] = "NEGATIVE"
        results = {
            expert: (
                "---\nscore: 70\nverdict: PASS\n"
                f"conclusion_direction: {direction}\n---\n"
            )
            for expert, direction in directions.items()
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(2):
                run = root / "artifacts" / f"code{index}" / f"run{index}"
                run.mkdir(parents=True)
                name = f"invest_level3_code{index}.json"
                payload = {"industry": "化妆品", "expert_directions": directions}
                (run / name).write_text(json.dumps(payload), encoding="utf-8")
                digest = hashlib.sha256((run / name).read_bytes()).hexdigest()
                manifest = {
                    "run_id": f"run{index}", "created_at": f"2026-01-0{index + 1}",
                    "files": [{"name": name, "sha256": digest}],
                }
                (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            level3 = evaluate_level3(results, scoring, "化妆品", root)
        self.assertTrue(level3["industry_three_run_opposition"])
        self.assertEqual(level3["industry_opposition_experts"], ["value-valuator"])
        self.assertTrue(level3["triggered"])

    def test_cross_review_aggregate_is_bound_to_three_independent_results(self):
        code = "000001.SZ"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = {
                "market": {"trade_date": "20200102"},
                "meta": {"analysis_date": "20200103", "batch_id": "a" * 24},
            }
            (root / f"invest_data_{code}.json").write_text(json.dumps(data), encoding="utf-8")
            (root / f"invest_level3_{code}.json").write_text(
                json.dumps({"triggered": True}), encoding="utf-8",
            )
            for expert in MANIFEST_EXPERTS:
                (root / f"invest_result_{code}_{expert}.md").write_text(
                    f"expert {expert}", encoding="utf-8",
                )
                (root / f"invest_challenge_result_{code}_{expert}.md").write_text(
                    f"challenge {expert}", encoding="utf-8",
                )
            bundle_hash = input_bundle_hash(code, root)
            body = "交叉检查保留证据边界。" * 100
            for reviewer in CROSS_REVIEWERS:
                prompt = expected_cross_prompt(code, reviewer, root).encode()
                prompt_hash = cross_prompt_hash(prompt)
                (root / f"invest_cross_prompt_{code}_{reviewer}.txt").write_bytes(prompt)
                result = f"""---
reviewer_id: {reviewer}
ts_code: {code}
data_date: '20200102'
analysis_date: '20200103'
batch_id: {'a' * 24}
input_bundle_hash: {bundle_hash}
cross_prompt_hash: {prompt_hash}
cross_verdict: CONFIRM
---
# 盲审
## 遗漏与矛盾
{body}
## 反事实压力测试
{body}
## 对裁判长的影响
{body}
"""
                (root / f"invest_cross_result_{code}_{reviewer}.md").write_text(
                    result, encoding="utf-8",
                )
            aggregate = root / f"invest_cross_blind_{code}.md"
            aggregate.write_text(build_aggregate(code, root), encoding="utf-8")
            self.assertEqual(validate_cross_aggregate(code, root), [])
            prompt_path = root / f"invest_cross_prompt_{code}_{CROSS_REVIEWERS[0]}.txt"
            result_path = root / f"invest_cross_result_{code}_{CROSS_REVIEWERS[0]}.md"
            mutated = prompt_path.read_bytes().replace("你是".encode(), "你不是".encode(), 1)
            mutated_hash = cross_prompt_hash(mutated)
            old_hash = cross_prompt_hash(prompt_path.read_bytes())
            mutated = mutated.replace(old_hash.encode(), mutated_hash.encode())
            prompt_path.write_bytes(mutated)
            result_path.write_text(
                result_path.read_text(encoding="utf-8").replace(old_hash, mutated_hash),
                encoding="utf-8",
            )
            self.assertTrue(validate_cross_aggregate(code, root))
            prompt_path.write_text(expected_cross_prompt(code, CROSS_REVIEWERS[0], root), encoding="utf-8")
            result_path.write_text(
                result_path.read_text(encoding="utf-8").replace(mutated_hash, old_hash),
                encoding="utf-8",
            )
            self.assertEqual(validate_cross_aggregate(code, root), [])
            victim = root / f"invest_cross_result_{code}_{CROSS_REVIEWERS[0]}.md"
            victim.write_text(victim.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
            self.assertTrue(validate_cross_aggregate(code, root))


if __name__ == "__main__":
    unittest.main()
