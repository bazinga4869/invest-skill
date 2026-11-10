import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.contracts import BATCH_CONTRACT_FILES
from shared.research_review import SCHEMA, adjudicator_identity, validate_review
from scripts import research_review
from scripts.cleanup_intermediates import runtime_paths


class ResearchReviewTests(unittest.TestCase):
    def setUp(self):
        self.draft = b'## \xe7\xbb\xbc\xe5\x90\x88\xe8\xa3\x81\xe5\x86\xb3 \xe2\x80\x94 \xe8\xa3\x81\xe5\x88\xa4\xe9\x95\xbf\n\n```yaml\n---\nadjudicator:\n  identity: judge-session\n---\n```\n'
        self.execution = {"batch_id": "batch", "events": [{"backend": "orchestrator", "host": "lead-session"}]}
        self.receipt = dict(schema_version=SCHEMA, ts_code="000001.SZ", batch_id="batch",
                            draft_sha256=hashlib.sha256(self.draft).hexdigest(),
                            reviewer_identity="review-session", orchestrator_identity="lead-session",
                            adjudicator_identity="judge-session", verdict="PASS",
                            reviewed_at="2026-11-03T00:00:00+00:00", statement="Independent research accepted")

    def check(self, receipt=None, draft=None):
        return validate_review(self.receipt if receipt is None else receipt,
                               ts_code="000001.SZ", batch_id="batch",
                               draft=self.draft if draft is None else draft, execution=self.execution)

    def test_independent_pass_and_boundaries(self):
        self.assertEqual(adjudicator_identity(self.draft.decode()), "judge-session")
        self.assertEqual(self.check(), [])
        for key, value in (("reviewer_identity", "lead-session"),
                           ("reviewer_identity", "judge-session"),
                           ("reviewer_identity", "LEAD-SESSION"),
                           ("reviewer_identity", "unknown"),
                           ("orchestrator_identity", "invented"),
                           ("adjudicator_identity", "invented"),
                           ("batch_id", "old-batch"), ("verdict", "FAIL"),
                           ("draft_sha256", "0" * 64), ("statement", "")):
            with self.subTest(key=key, value=value):
                self.assertTrue(self.check({**self.receipt, key: value}))
        self.assertTrue(self.check(draft=self.draft + b"changed"))
        self.assertTrue(self.check({}))

    def test_judge_cannot_be_orchestrator_or_existing_worker(self):
        same_draft = self.draft.replace(b"judge-session", b"lead-session")
        same = {**self.receipt, "adjudicator_identity": "lead-session",
                "draft_sha256": hashlib.sha256(same_draft).hexdigest()}
        self.assertTrue(self.check(same, same_draft))
        self.execution["events"].append({"backend": "host-native", "detail": json.dumps({"child_id": "expert-child-123"})})
        self.assertTrue(self.check({**self.receipt, "reviewer_identity": "EXPERT-CHILD-123"}))
        worker_draft = self.draft.replace(b"judge-session", b"expert-child-123")
        self.assertTrue(self.check({**self.receipt, "adjudicator_identity": "expert-child-123",
                                   "draft_sha256": hashlib.sha256(worker_draft).hexdigest()}, worker_draft))
        self.assertTrue(validate_review(self.receipt, ts_code="000001.SZ", batch_id="batch",
                                        draft=self.draft, execution=[]))

    def test_explicit_cli_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "000001.SZ.draft.md").write_bytes(self.draft)
            (root / "invest_data_000001.SZ.json").write_text(json.dumps({"meta": {"batch_id": "batch"}}))
            (root / "invest_execution_000001.SZ.json").write_text(json.dumps(self.execution))
            argv = ["research_review.py", "000001.SZ", "--reviewer-identity", "review-session",
                    "--orchestrator-identity", "lead-session", "--verdict", "PASS", "--statement", "accepted"]
            with patch.object(research_review, "RUNTIME_ROOT", root), patch.dict("os.environ", {"INVEST_REPORTS_DIR": str(root)}), patch("sys.argv", argv):
                self.assertEqual(research_review.main(), 0)
            receipt = json.loads((root / "invest_research_review_000001.SZ.json").read_text())
            self.assertEqual(self.check(receipt), [])
            self.assertIn("not-cryptographic", receipt["identity_assurance"])

    def test_finalize_refuses_missing_review_before_publication(self):
        import argparse
        from scripts import assemble_report as ar
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            code = "000001.SZ"
            for name in [f"invest_data_{code}.json", f"invest_annual_{code}.txt",
                         f"invest_report_bundle_{code}.json", f"invest_execution_{code}.json",
                         f"invest_level3_{code}.json", f"{code}.draft.md"]:
                (root / name).write_text("{}")
            for expert in ar.EXPERTS:
                for pattern in ("invest_prompt_{}.txt", "invest_native_prompt_{}.txt",
                                "invest_result_{}.v3.json", "invest_result_{}.md",
                                "invest_challenge_prompt_{}.txt", "invest_challenge_result_{}.md"):
                    (root / pattern.format(f"{code}_{expert}")).write_text("{}")
            with patch.object(ar, "RUNTIME_ROOT", root), patch.object(ar, "REPORTS_DIR", root), patch.object(ar, "record_execution"), patch.object(ar, "load_scoring_config") as scoring:
                result = ar._main_locked(argparse.Namespace(finalize=True), code)
                self.assertEqual(result, 2)
                scoring.assert_not_called()
            self.assertFalse((root / f"{code}.md").exists())

    def test_archive_requires_research_review(self):
        from scripts import assemble_report as ar
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(ar, "RUNTIME_ROOT", root), patch.object(ar, "build_retry_evidence", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "invest_research_review"):
                    ar.archive_run("000001.SZ", root / "000001.SZ.draft.md")

    def test_manifest_requires_archived_review(self):
        from scripts import verify_manifest as vm
        from shared.contracts import CONTRACT_VERSION
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "artifacts" / "000001.SZ" / "run"
            archive.mkdir(parents=True)
            report = archive / "000001.SZ.md"
            report.write_text("# Synthetic report\n<!-- artifact_manifest: artifacts/000001.SZ/run/manifest.json -->\n")
            (archive / "manifest.json").write_text(json.dumps({
                "ts_code": "000001.SZ", "run_id": "run", "contract_version": CONTRACT_VERSION,
                "files": [{"name": report.name, "sha256": hashlib.sha256(report.read_bytes()).hexdigest(), "bytes": report.stat().st_size}],
            }))
            with patch.object(vm, "REPORTS_DIR", root):
                result = vm.verify(str(report))
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("invest_research_review_000001.SZ.json" in error for error in result["errors"]))

    def test_control_plane_and_cleanup(self):
        self.assertIn("scripts/research_review.py", BATCH_CONTRACT_FILES)
        self.assertIn("shared/research_review.py", BATCH_CONTRACT_FILES)
        self.assertIn(Path("/tmp/invest_research_review_000001.SZ.json"), runtime_paths("000001.SZ", Path("/tmp")))


if __name__ == "__main__":
    unittest.main()
