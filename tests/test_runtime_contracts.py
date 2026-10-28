import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.cleanup_intermediates import cleanup_intermediates
from scripts.prepare_challenges import VALID_CHALLENGE_VERDICTS
from scripts.preserve_failure_evidence import preserve_failure_evidence
from scripts.normalize_challenge import normalize_raw
from scripts.collect_results import _is_table_ordinal, _wiki_path_exists
from scripts.prepare_prompts import (
    WIKI_ROOT, annual_locator_catalog, build_expert_prompt, checklist_template,
    narrative_quote_catalog, self_check_prompts,
)
from shared.expert_result_v3 import parse_result
from scripts.runtime_guard import (
    GuardError, assert_idle, begin_retry, claim_retry, claim_run, read_run_state,
    recover_retry, release_run, retry_state_path,
)


CODE = "000001.SZ"
BATCH = "a" * 24


class ExpertJsonTransportTests(unittest.TestCase):
    def test_repairs_unescaped_control_character_inside_string(self):
        parsed = parse_result('{"summary":"a\nb","narrative_checks":[]}')
        self.assertEqual(parsed["summary"], "a b")
        self.assertIn("escaped-control-character", parsed["transport_repairs"])

    def test_repairs_missing_object_closer_before_array_closer(self):
        parsed = parse_result('{"analysis_sections":[{"heading":"h"]}')
        self.assertEqual(parsed["analysis_sections"][0]["heading"], "h")
        self.assertIn("inserted-missing-container-closer", parsed["transport_repairs"])

    def test_does_not_repair_truncated_string(self):
        with self.assertRaises(Exception):
            parse_result('{"summary":"truncated')


def write_snapshot(root: Path) -> None:
    (root / f"invest_data_{CODE}.json").write_text(json.dumps({
        "market": {"trade_date": "20260731", "close": 10, "pe_ttm": 12},
        "meta": {"batch_id": BATCH, "analysis_date": "20260801"},
    }), encoding="utf-8")


class RuntimeGuardTests(unittest.TestCase):
    def test_pipeline_phases_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_snapshot(root)
            claim_run(CODE, "challenges", root)
            self.assertEqual(read_run_state(CODE, root)["owner"], "challenges")
            with self.assertRaises(GuardError):
                claim_run(CODE, "shell", root)
            with self.assertRaises(GuardError):
                release_run(CODE, "shell", root)
            release_run(CODE, "challenges", root)
            assert_idle(CODE, root)

    def test_prepare_can_lock_before_snapshot_and_token_is_required_when_given(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lease = claim_run(CODE, "prepare", root)
            self.assertEqual(lease["batch_id"], "PENDING")
            with self.assertRaises(GuardError):
                release_run(CODE, "prepare", root, token="wrong")
            assert_idle(CODE, root, owner="prepare")
            release_run(CODE, "prepare", root, token=lease["token"])

    def test_each_phase_has_exactly_one_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_snapshot(root)
            reserved = claim_retry(CODE, "experts", root)
            self.assertEqual(reserved["status"], "reserved")
            self.assertEqual(claim_retry(CODE, "experts", root), reserved)
            started = begin_retry(CODE, "experts", root)
            self.assertEqual(started["status"], "started")
            with self.assertRaises(GuardError):
                begin_retry(CODE, "experts", root)
            self.assertEqual(begin_retry(CODE, "challenges", root)["status"], "started")

    def test_legacy_retry_marker_requires_explicit_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_snapshot(root)
            path = retry_state_path(CODE, "experts", BATCH, root)
            path.write_text(json.dumps({
                "ts_code": CODE, "batch_id": BATCH,
                "phase": "experts", "used_at": "2026-08-02T00:00:00+00:00",
            }), encoding="utf-8")
            with self.assertRaises(GuardError):
                begin_retry(CODE, "experts", root)
            self.assertEqual(recover_retry(CODE, "experts", root)["status"], "reserved")
            self.assertEqual(begin_retry(CODE, "experts", root)["status"], "started")
            with self.assertRaises(GuardError):
                begin_retry(CODE, "experts", root)


class CleanupTests(unittest.TestCase):
    def test_cleanup_is_scoped_and_preserves_final_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tmp_root = root / "tmp"
            log_root = root / "logs"
            reports = root / "reports"
            (log_root / "experts").mkdir(parents=True)
            reports.mkdir()
            tmp_root.mkdir()
            target_files = [
                tmp_root / f"invest_data_{CODE}.json",
                tmp_root / f"invest_report_bundle_{CODE}.json",
                tmp_root / f"invest_prompt_{CODE}_financial-auditor.txt",
                tmp_root / f"invest_retry_{CODE}_experts_{BATCH}.json",
                log_root / "experts" / f"{CODE}_financial-auditor.log",
                reports / f"{CODE}.draft.md",
            ]
            for path in target_files:
                path.write_text("x", encoding="utf-8")
            final_report = reports / f"{CODE}.md"
            final_report.write_text("final", encoding="utf-8")
            other = tmp_root / "invest_data_000002.SZ.json"
            other.write_text("other", encoding="utf-8")

            result = cleanup_intermediates(
                CODE, tmp_root=tmp_root, log_root=log_root, reports_dir=reports,
            )
            self.assertFalse(result["errors"])
            self.assertFalse(result["remaining"])
            self.assertTrue(final_report.is_file())
            self.assertTrue(other.is_file())
            self.assertTrue(all(not path.exists() for path in target_files))

    def test_failure_evidence_is_written_and_explicit_cleanup_removes_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / f"invest_data_{CODE}.json"
            data.write_text(json.dumps({
                "market": {"trade_date": "20240102"},
                "meta": {"analysis_date": "20240103", "batch_id": BATCH},
            }), encoding="utf-8")
            with patch("scripts.preserve_failure_evidence._expert_failures", return_value={
                "macro-cyclist": {
                    "problems": ["历史断言无逐年核对"],
                    "diagnostics": {"unsourced_claims": [{"line": 96}]},
                },
            }):
                evidence = preserve_failure_evidence(
                    CODE, "experts", runtime_root=root, log_root=root / "logs",
                )
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload["batch_id"], BATCH)
            self.assertEqual(payload["failures"]["macro-cyclist"]["diagnostics"]
                             ["unsourced_claims"][0]["line"], 96)
            self.assertTrue(evidence.is_file())
            result = cleanup_intermediates(
                CODE, tmp_root=root, log_root=root / "logs",
                reports_dir=root / "reports",
            )
            self.assertFalse(evidence.exists())
            self.assertFalse(result["remaining"])


class ChallengeNormalizationTests(unittest.TestCase):
    def test_prompt_verdict_enum_is_explicit_and_closed(self):
        self.assertEqual(VALID_CHALLENGE_VERDICTS, ("UNCHANGED", "DOWNGRADED", "UPGRADED"))

    def test_wrapper_restores_trusted_questions_and_metadata(self):
        unhashed = '''标的：000001.SZ；专家：macro-cyclist；批次：batch。
原专家报告哈希：placeholder
challenge_prompt_hash: "__PROMPT_HASH__"
题库问题：问题甲？
动态问题：问题乙？
缺失项/薄弱假设追问：问题丙？
'''
        from shared.review_contracts import challenge_prompt_hash
        prompt = unhashed.replace(
            "__PROMPT_HASH__", challenge_prompt_hash(unhashed.encode("utf-8"))
        )
        response = (
            "不利压力情景会先使原报告的关键推理失效，因此结论应当维持但降低确信度。"
            "如果后续披露的数据与原证据链反向，评分就必须下调。下一个可证伪指标是"
            "同期现金流、利润与管理层承诺能否继续相互印证，任一证据缺失都保持风险判断。"
        )
        raw = f"challenge_verdict: DOWNGRADED\nresponse: |\n  {response}\n"
        result = normalize_raw(raw, prompt, "original", {
            "market": {"trade_date": "20260731"},
            "meta": {"analysis_date": "20260802", "batch_id": "batch"},
        }, CODE, "macro-cyclist")
        self.assertIn("challenge_verdict: DOWNGRADED", result)
        self.assertIn("1. 问题甲？\n2. 问题乙？\n3. 问题丙？", result)
        self.assertIn(response, result)


class PromptContractTests(unittest.TestCase):
    def setUp(self):
        self.annual = """
### 2025年 annual（公告日：20260401，标题：2025年报）
#### 经营情况讨论与分析
公司持续推进品牌建设并优化产品结构，主营业务保持稳健发展。
#### 重要事项
公司如实披露关联交易与资金占用核查情况，相关事项均经审议。
#### 公司治理
公司不断完善治理结构并强化内部控制制度建设。
"""
        self.data = {
            "stock_info": {"ts_code": CODE, "name": "测试"},
            "market": {"trade_date": "20260731", "close": 10, "pe_ttm": 12,
                       "pb": 2, "total_share": 10},
            "annual": {"annual_data": [
                {"year": "2025", "revenue_yi": 20, "net_profit_yi": 2,
                 "non_recurring_pct": 1}
            ]},
            "quarterly": {"periods": [
                {"period": "20260331", "ocf_yi": 1, "net_profit_yi": 0.8,
                 "fcf_yi": 0.7, "revenue_yi": 5}
            ]},
            "balance": {"equity_yi": 10, "interest_debt_yi": 1,
                        "goodwill_yi": 0.2, "receivables_yi": 1,
                        "inventory_yi": 2},
            "indicators": {"indicators": [
                {"gross_margin_pct": 60, "roe_pct": 20}
            ]},
            "audit": {"has_audit": True},
            "meta": {"analysis_date": "20260801", "batch_id": BATCH},
        }

    def test_annual_catalog_uses_exact_three_part_locator(self):
        locators = annual_locator_catalog(self.annual)
        self.assertIn("年报:2025/annual/经营情况讨论与分析", locators)
        self.assertTrue(all(locator.count("/") == 2 for locator in locators))

    def test_narrative_quote_catalog_returns_verbatim_short_sentences(self):
        rows = narrative_quote_catalog(self.annual)
        self.assertTrue(rows)
        locator, quote = rows[0]
        self.assertTrue(locator.startswith("年报:2025/annual/"))
        self.assertIn(quote, self.annual.replace("\n", "").replace(" ", ""))

    def test_checklist_contains_real_candidate_atoms(self):
        table = checklist_template("financial-auditor", self.data, self.annual)
        self.assertIn("quarterly.periods[0].ocf_yi", table)
        self.assertIn("net_profit_yi", table)
        self.assertIn("年报:2025/annual/重要事项", table)
        self.assertNotIn("用实际路径覆盖证据族", table)

    def test_prompt_prefills_exact_knowledge_paths_and_ascii_rule(self):
        prompt = build_expert_prompt(
            "financial-auditor", "01-财务排雷官", CODE, "测试",
            json.dumps(self.data, ensure_ascii=False), self.annual,
            "20260731", "20260801", BATCH, WIKI_ROOT,
        )
        self.assertIn(
            "04_stock-analysis-expert/experts/01-财务排雷官.md", prompt,
        )
        self.assertIn("首列必须严格使用 ASCII 数字", prompt)
        self.assertIn("禁止写 `[[页面标题]]`", prompt)
        knowledge_rows = [
            line for line in prompt.splitlines()
            if line.startswith("| ") and "任务书确定性注入" in line
        ]
        self.assertGreaterEqual(len(knowledge_rows), 3)

    def test_panel_contract_is_injected_even_when_sage_context_present(self):
        """F3：sage 有上下文时 `_panel.md`/`_schema.md` 仍必须确定性进入 prompt。"""
        sage = "（模拟：本批次 sage 检索有上下文）"
        prompt = build_expert_prompt(
            "financial-auditor", "01-财务排雷官", CODE, "测试",
            json.dumps(self.data, ensure_ascii=False), self.annual,
            "20260731", "20260801", BATCH, WIKI_ROOT,
            sage_context=sage,
        )
        self.assertIn(sage, prompt)
        self.assertIn("面板与方法论契约", prompt)
        self.assertIn("04_stock-analysis-expert/_schema.md", prompt)
        self.assertIn("04_stock-analysis-expert/experts/_panel.md", prompt)
        self.assertLess(prompt.index(sage), prompt.index("面板与方法论契约"))

    def test_panel_contract_block_present_without_sage_context(self):
        prompt = build_expert_prompt(
            "financial-auditor", "01-财务排雷官", CODE, "测试",
            json.dumps(self.data, ensure_ascii=False), self.annual,
            "20260731", "20260801", BATCH, WIKI_ROOT,
        )
        self.assertIn("面板与方法论契约", prompt)
        self.assertIn("04_stock-analysis-expert/_schema.md", prompt)

    def test_self_check_ignores_placeholders_from_injected_contract(self):
        """F3：契约页原文里的 `{{F001}}` 属数据，不得被当成未解析模板占位符。"""
        injected: list[str] = []
        prompt = build_expert_prompt(
            "financial-auditor", "01-财务排雷官", CODE, "测试",
            json.dumps(self.data, ensure_ascii=False), self.annual,
            "20260731", "20260801", BATCH, WIKI_ROOT,
            sage_context="（示例：staged JSON 正文用 {{F001}} 占位）",
            injected_out=injected,
        )
        name = f"invest_prompt_{CODE}_financial-auditor.txt"
        self.assertTrue(injected)
        without = self_check_prompts({name: prompt}, self.data)
        self.assertTrue(any("{{F001}}" in item for item in without[0]))
        with_ = self_check_prompts({name: prompt}, self.data, {name: injected})
        self.assertFalse(any("{{F001}}" in item for item in with_[0]))

    def test_validator_accepts_legacy_chinese_ordinals_and_unique_wikilink(self):
        self.assertTrue(_is_table_ordinal("三"))
        # 迁移说明：原夹具指向旧 invest-sage 页面；现知识层为投资知识库 AI-Wiki，
        # 改用面板内真实存在且唯一的页面，保持“唯一 wikilink 可解析”这一契约不变。
        self.assertTrue(_wiki_path_exists("[[裁判长-多框架裁判规则]]"))


if __name__ == "__main__":
    unittest.main()
