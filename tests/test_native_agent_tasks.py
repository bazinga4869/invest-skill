import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import native_agent_tasks as native
from shared.batch_contract import prompt_contract_hash
from shared.contracts import batch_contract_paths


CODE = "002727.SZ"


class NativeAgentTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.expert = "financial-auditor"
        for name in (
            f"invest_prompt_{CODE}_{self.expert}.txt",
            f"invest_native_prompt_{CODE}_{self.expert}.txt",
            f"invest_native_original_prompt_{CODE}_experts_{self.expert}.txt",
        ):
            (self.root / name).write_text("唯一专家任务书", encoding="utf-8")
        (self.root / f"invest_data_{CODE}.json").write_text(json.dumps({
            "meta": {
                "prompt_contract_hash": prompt_contract_hash(
                    batch_contract_paths(native.SKILL_ROOT)
                )
            }
        }), encoding="utf-8")
        def fake_run(args, **_kwargs):
            if "scripts/expert_result_v3.py" in args and "compile" in args:
                sidecar = Path(args[args.index("--sidecar") + 1])
                markdown = Path(args[args.index("--markdown") + 1])
                sidecar.write_text(json.dumps({
                    "schema_version": "expert-result/v3",
                    "decision": {"score": 62, "verdict": "WARN",
                                 "conclusion_direction": "NEUTRAL",
                                 "veto_triggers": []},
                }) + "\n", encoding="utf-8")
                markdown.write_text("---\nexpert_id: financial-auditor\n---\n正文", encoding="utf-8")
            return None

        self.patches = [
            patch.object(native, "RUNTIME_ROOT", self.root),
            patch.object(native, "_run", side_effect=fake_run),
            patch.object(native, "claim_run", return_value={"token": "token1"}),
            patch.object(native, "_prepare_phase", return_value=[self.expert]),
            patch.object(native, "current_batch_id", return_value="batch1"),
            patch.object(native, "record_execution"),
            patch.object(native, "release_run"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_plan_inherits_parent_without_provider_selection(self):
        plan = native.begin(CODE, "experts", False)
        self.assertEqual(plan["mode"], "host-native")
        self.assertTrue(plan["inherit_parent_provider"])
        self.assertTrue(plan["inherit_parent_model"])
        self.assertIsNone(plan["provider_override"])
        self.assertIsNone(plan["model_override"])
        self.assertNotIn("codex exec", plan["jobs"][0]["instruction"])
        self.assertIn("不得选择或启动 codex、claude、dsh", plan["jobs"][0]["instruction"])
        self.assertEqual(plan["jobs"][0]["prompt_bytes"], len("唯一专家任务书".encode()))
        self.assertEqual(len(plan["jobs"][0]["prompt_sha256"]), 64)
        self.assertEqual(len(plan["jobs"][0]["instruction_sha256"]), 64)

    def test_control_plane_change_aborts_batch(self):
        data_path = self.root / f"invest_data_{CODE}.json"
        data_path.write_text(json.dumps({
            "meta": {"prompt_contract_hash": "0" * 64}
        }), encoding="utf-8")
        with self.assertRaises(native.NativeTaskError) as ctx:
            native.begin(CODE, "experts", False)
        self.assertIn("控制面已变化", str(ctx.exception))

    def test_unresolved_placeholder_fails_before_delegation(self):
        (self.root / f"invest_native_prompt_{CODE}_{self.expert}.txt").write_text(
            "bad {growth_extra}", encoding="utf-8",
        )
        with self.assertRaises(native.NativeTaskError) as ctx:
            native.begin(CODE, "experts", False)
        self.assertIn("未解析占位符", str(ctx.exception))

    def test_commit_requires_host_child_receipt(self):
        plan = native.begin(CODE, "experts", False)
        Path(plan["jobs"][0]["staged_output_path"]).write_text(
            '{"schema_version":"expert-result/v3"}', encoding="utf-8",
        )
        with self.assertRaises(native.NativeTaskError):
            native.commit(CODE, "experts", self.expert, "short")

    def test_retry_is_reserved_until_valid_content_is_committed(self):
        (self.root / f"invest_native_prompt_{CODE}_{self.expert}.txt").write_text(
            "紧凑任务书", encoding="utf-8",
        )
        (self.root / f"invest_result_{CODE}_{self.expert}.v3.json").write_text(
            json.dumps({"decision": {"score": 62, "verdict": "WARN",
                                      "conclusion_direction": "NEUTRAL",
                                      "veto_triggers": []}}), encoding="utf-8",
        )
        (self.root / f"invest_native_original_prompt_{CODE}_experts_{self.expert}.txt").write_text(
            "唯一官方专家任务书", encoding="utf-8",
        )
        with (
            patch.object(native, "claim_retry") as reserve,
            patch.object(native, "begin_retry") as started,
        ):
            plan = native.begin(CODE, "experts", True)
            reserve.assert_called_once()
            started.assert_not_called()
            Path(plan["jobs"][0]["staged_output_path"]).write_text(
                '{"schema_version":"expert-result/v3"}', encoding="utf-8",
            )
            native.commit(CODE, "experts", self.expert, "child-test-0001")
            started.assert_called_once()

    def test_rejected_v3_commit_remains_retryable_and_does_not_block_advance(self):
        plan = native.begin(CODE, "experts", False)
        staged = Path(plan["jobs"][0]["staged_output_path"])
        staged.write_text('{"schema_version":"expert-result/v3"}', encoding="utf-8")
        with patch.object(native, "_run", side_effect=native.NativeTaskError("token 非法")):
            with self.assertRaises(native.NativeTaskError):
                native.commit(CODE, "experts", self.expert, "child-test-0001")
        saved = native._load_plan(CODE)
        self.assertTrue(saved["jobs"][0]["commit_rejected"])
        self.assertTrue((self.root / f"invest_rejected_result_{CODE}_{self.expert}.v3.json").is_file())
        with (
            patch.object(native, "_validate_phase", return_value=(False, "missing result")),
            patch.object(native, "_preserve_failure", return_value=None),
        ):
            failed = native.advance(CODE, "experts")
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("--retry", failed["next"])

    def test_review_repair_contains_official_prompt_and_diagnostics(self):
        original = self.root / f"invest_native_original_prompt_{CODE}_challenges_{self.expert}.txt"
        original.write_text("OFFICIAL CHALLENGE TASK", encoding="utf-8")
        (self.root / f"invest_rejected_result_{CODE}_challenges_{self.expert}.md").write_text(
            "challenge_verdict: BAD", encoding="utf-8",
        )
        with patch.object(native, "_result_path", return_value=self.root / "missing.md"):
            with patch("scripts.collect_challenges.validate_challenge", return_value={"error": "bad enum"}):
                prompt = native._review_repair_prompt(CODE, "challenges", self.expert, 1)
        text = prompt.read_text(encoding="utf-8")
        self.assertIn("## 官方原始任务书", text)
        self.assertIn("OFFICIAL CHALLENGE TASK", text)
        self.assertIn("bad enum", text)
        self.assertIn("challenge_verdict: BAD", text)

    def test_truncated_json_still_freezes_complete_decision_prefix(self):
        rejected = self.root / f"invest_rejected_result_{CODE}_{self.expert}.v3.json"
        rejected.write_text(
            '{"decision":{"score":58,"verdict":"WARN",'
            '"conclusion_direction":"NEUTRAL","veto_triggers":[]},'
            '"summary":"unterminated',
            encoding="utf-8",
        )
        baseline = native._freeze_decision_baseline(CODE, self.expert)
        frozen = json.loads(baseline.read_text(encoding="utf-8"))
        self.assertEqual(frozen["decision"]["score"], 58)

    def test_retry_freezes_first_rejected_decision_and_embeds_it(self):
        rejected = self.root / f"invest_rejected_result_{CODE}_{self.expert}.v3.json"
        rejected.write_text(json.dumps({"decision": {
            "score": 64, "verdict": "WARN",
            "conclusion_direction": "NEUTRAL", "veto_triggers": [],
        }}), encoding="utf-8")
        baseline = native._freeze_decision_baseline(CODE, self.expert)
        frozen = json.loads(baseline.read_text(encoding="utf-8"))
        self.assertEqual(frozen["decision"]["score"], 64)
        with patch.object(native, "_expert_diagnostics", return_value={}):
            prompt = native._repair_prompt(CODE, self.expert, 1)
        text = prompt.read_text(encoding="utf-8")
        self.assertIn("Immutable decision", text)
        self.assertIn('"score": 64', text)
        self.assertIn("不得删除、合并或缩短", text)
        self.assertIn("不得写 `name=表达式`", text)

    def test_repair_structure_cannot_shrink_valid_arrays(self):
        baseline = self.root / "baseline.json"
        baseline.write_text(json.dumps({"structure": {
            "analysis_sections_min": 7,
            "risks_min": 4,
            "narrative_checks_min": 3,
            "checklist_keys": ["a", "b"],
        }}), encoding="utf-8")
        repaired = self.root / "repaired.json"
        repaired.write_text(json.dumps({
            "analysis_sections": [{"heading": "h", "body": "b"}] * 5,
            "risks": ["r"] * 4,
            "narrative_checks": [{"quote_id": "q"}] * 3,
            "checklist_conclusions": {"a": "x", "b": "y"},
        }), encoding="utf-8")
        self.assertIn(
            "analysis_sections_min",
            native._expert_structure_regression(baseline, repaired),
        )
        repaired.write_text(json.dumps({
            "analysis_sections": [{"heading": "h", "body": "b"}] * 7,
            "risks": ["r"] * 4,
            "narrative_checks": [{"quote_id": "q"}] * 3,
            "checklist_conclusions": {"a": "x", "b": "y", "c": "z"},
        }), encoding="utf-8")
        self.assertIsNone(native._expert_structure_regression(baseline, repaired))

    def test_decision_signature_covers_trace_only_fields(self):
        path = self.root / "decision.json"
        path.write_text(json.dumps({"decision": {
            "score": 62, "verdict": "WARN",
            "conclusion_direction": "NEUTRAL", "veto_triggers": []
        }}), encoding="utf-8")
        self.assertEqual(native._decision_signature(path), (62, "WARN", "NEUTRAL", ()))
        path.write_text(json.dumps({"decision": {
            "score": 61, "verdict": "WARN",
            "conclusion_direction": "NEUTRAL", "veto_triggers": []
        }}), encoding="utf-8")
        self.assertNotEqual(native._decision_signature(path), (62, "WARN", "NEUTRAL", ()))

    def test_retry_rejects_decision_semantic_diff(self):
        sidecar = self.root / f"invest_result_{CODE}_{self.expert}.v3.json"
        sidecar.write_text(json.dumps({"decision": {
            "score": 62, "verdict": "WARN", "conclusion_direction": "NEUTRAL",
            "veto_triggers": []
        }}), encoding="utf-8")
        def changed_run(args, **_kwargs):
            if "scripts/expert_result_v3.py" in args and "compile" in args:
                out = Path(args[args.index("--sidecar") + 1])
                md = Path(args[args.index("--markdown") + 1])
                out.write_text(json.dumps({"decision": {
                    "score": 61, "verdict": "WARN", "conclusion_direction": "NEUTRAL",
                    "veto_triggers": []
                }}), encoding="utf-8")
                md.write_text("---\\nexpert_id: financial-auditor\\n---\\n正文", encoding="utf-8")
            return None
        with patch.object(native, "_run", side_effect=changed_run), \
             patch.object(native, "claim_retry"), patch.object(native, "begin_retry"):
            plan = native.begin(CODE, "experts", True)
            Path(plan["jobs"][0]["staged_output_path"]).write_text(
                '{"schema_version":"expert-result/v3"}', encoding="utf-8"
            )
            with self.assertRaises(native.NativeTaskError) as ctx:
                native.commit(CODE, "experts", self.expert, "child-test-0001")
        self.assertIn("semantic diff", str(ctx.exception))
        self.assertTrue((self.root / f"invest_native_compile_error_{CODE}_{self.expert}.json").is_file())

    def test_repair_requires_first_output_evidence(self):
        """F4：没有首次独立产出时仍 fail-closed。"""
        with self.assertRaises(native.NativeTaskError) as ctx:
            native._freeze_decision_baseline(CODE, self.expert)
        self.assertIn("缺少首次独立产出", str(ctx.exception))

    def test_repair_available_when_first_output_has_no_decision(self):
        """F4：首产出不可解析（`{}`）时仍可冻结无决策基线并生成 repair 任务书。"""
        rejected = self.root / f"invest_rejected_result_{CODE}_{self.expert}.v3.json"
        rejected.write_text("{}", encoding="utf-8")
        baseline = native._freeze_decision_baseline(CODE, self.expert)
        frozen = json.loads(baseline.read_text(encoding="utf-8"))
        self.assertIsNone(frozen["decision"])
        self.assertEqual(frozen["frozen_kind"], "unparsable")
        with patch.object(native, "_expert_diagnostics", return_value={}):
            prompt = native._repair_prompt(CODE, self.expert, 1)
        text = prompt.read_text(encoding="utf-8")
        self.assertIn("没有可冻结的 decision", text)
        self.assertNotIn("Immutable decision（机器冻结，不得改写）", text)
        self.assertIn("不得删除、合并或缩短", text)

    def test_retry_commits_when_first_output_had_no_decision(self):
        """F4 端到端：首产出 `{}` 的专家仍能走完 retry → commit。"""
        rejected = self.root / f"invest_rejected_result_{CODE}_{self.expert}.v3.json"
        rejected.write_text("{}", encoding="utf-8")
        with patch.object(native, "claim_retry"), patch.object(native, "begin_retry"):
            plan = native.begin(CODE, "experts", True)
            Path(plan["jobs"][0]["staged_output_path"]).write_text(
                '{"schema_version":"expert-result/v3"}', encoding="utf-8",
            )
            committed = native.commit(CODE, "experts", self.expert, "child-test-0001")
        frozen = json.loads(
            (self.root / f"invest_native_decision_baseline_{CODE}_{self.expert}.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(frozen["frozen_kind"], "unparsable")
        self.assertTrue(Path(committed["result_path"]).is_file())

    def test_repair_rejects_baseline_claiming_unrecomputable_decision(self):
        """F4 反向：基线声称有 decision 却复算不出时必须拒绝。"""
        baseline = self.root / f"invest_native_decision_baseline_{CODE}_{self.expert}.json"
        baseline.write_text(json.dumps({
            "frozen_kind": "decision",
            "decision": {"score": "not-an-int"},
        }), encoding="utf-8")
        (self.root / f"invest_native_original_prompt_{CODE}_experts_{self.expert}.txt").write_text(
            "唯一官方专家任务书", encoding="utf-8",
        )
        with patch.object(native, "claim_retry"), patch.object(native, "begin_retry"):
            plan = native.begin(CODE, "experts", True)
            Path(plan["jobs"][0]["staged_output_path"]).write_text(
                '{"schema_version":"expert-result/v3"}', encoding="utf-8",
            )
            with self.assertRaises(native.NativeTaskError) as ctx:
                native.commit(CODE, "experts", self.expert, "child-test-0001")
        self.assertIn("不可复算", str(ctx.exception))

    def test_commit_and_advance_publish_native_child_output(self):
        plan = native.begin(CODE, "experts", False)
        staged = Path(plan["jobs"][0]["staged_output_path"])
        staged.write_text("---\nexpert_id: financial-auditor\n---\n正文", encoding="utf-8")
        committed = native.commit(CODE, "experts", self.expert, "child-test-0001")
        result = Path(committed["result_path"])
        self.assertTrue(result.is_file())
        self.assertFalse(staged.exists())
        with patch.object(native, "_validate_phase", return_value=(True, "7/7 PASS")):
            done = native.advance(CODE, "experts")
        self.assertEqual(done["status"], "PASS")
        self.assertFalse((self.root / f"invest_native_run_{CODE}.json").exists())
        archives = list(self.root.glob(f"invest_native_archive_{CODE}_experts_batch1_*"))
        self.assertTrue(archives)
        self.assertTrue(any(p.name.startswith("plan_") for p in archives[0].iterdir()))


if __name__ == "__main__":
    unittest.main()
