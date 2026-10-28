import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.sage_wiki import (
    SageHit, SageWikiError, collect_expert_contexts,
)


EXPERT = "financial-auditor"
UTC = dt.timezone.utc


class SageWikiCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = {
            "enabled": True,
            "dir": "data/sage-cache",
            "fresh_days": 7,
            "max_stale_days": 90,
            "allow_builtin_without_cache": False,
        }
        self.patches = [
            patch("shared.sage_wiki.runtime_root", return_value=self.root),
            patch("shared.sage_wiki._cache_config", return_value=self.cfg),
            patch("shared.sage_wiki._model_name", return_value="test-model"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_live_query_writes_validated_per_expert_cache(self):
        now = dt.datetime(2026, 8, 20, tzinfo=UTC)
        hit = SageHit("query:test", "现金流与审计方法 [[cash-flow]]", 1.0)
        with patch("shared.sage_wiki.query", return_value=hit):
            contexts, status = collect_expert_contexts([EXPERT], now=now)
        self.assertEqual(status["status"], "OK")
        self.assertEqual(status["mode"], "live")
        self.assertIn("现金流与审计方法", contexts[EXPERT][0])
        cache = self.root / "data" / "sage-cache" / f"{EXPERT}.json"
        payload = json.loads(cache.read_text(encoding="utf-8"))
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["snapshot_date"], "2026-08-20")
        self.assertEqual(payload["expert_id"], EXPERT)
        self.assertEqual(len(payload["content_sha256"]), 64)
        self.assertTrue(payload["source_paths"])

    def test_fresh_cache_avoids_paid_query(self):
        now = dt.datetime(2026, 8, 20, tzinfo=UTC)
        hit = SageHit("query:test", "估值现金流方法", 1.0)
        with patch("shared.sage_wiki.query", return_value=hit):
            collect_expert_contexts([EXPERT], now=now)
        with patch("shared.sage_wiki.query") as live:
            contexts, status = collect_expert_contexts(
                [EXPERT], now=now + dt.timedelta(days=1),
            )
        live.assert_not_called()
        self.assertEqual(status["status"], "DEGRADED")
        self.assertEqual(status["mode"], "cache")
        self.assertIn("估值现金流方法", contexts[EXPERT][0])

    def test_402_uses_recent_validated_stale_cache(self):
        now = dt.datetime(2026, 8, 20, tzinfo=UTC)
        hit = SageHit("query:test", "历史方法论快照", 1.0)
        with patch("shared.sage_wiki.query", return_value=hit):
            collect_expert_contexts([EXPERT], now=now)
        failure = SageWikiError("Sage Wiki query exit=1: 402 Insufficient Balance")
        with patch("shared.sage_wiki.query", side_effect=failure):
            contexts, status = collect_expert_contexts(
                [EXPERT], now=now + dt.timedelta(days=8),
            )
        self.assertEqual(status["status"], "DEGRADED")
        self.assertEqual(status["mode"], "cache")
        self.assertIn("402 Insufficient Balance", status["error"])
        self.assertIn("历史方法论快照", contexts[EXPERT][0])

    def test_402_without_cache_fails_closed_with_clear_reason(self):
        failure = SageWikiError("Sage Wiki query exit=1: 402 Insufficient Balance")
        with patch("shared.sage_wiki.query", side_effect=failure):
            with self.assertRaises(SageWikiError) as raised:
                collect_expert_contexts(
                    [EXPERT], now=dt.datetime(2026, 8, 20, tzinfo=UTC),
                )
        self.assertIn("402 Insufficient Balance", str(raised.exception))
        self.assertIn("无通过校验的 cache", str(raised.exception))

    def test_tampered_cache_is_not_trusted(self):
        now = dt.datetime(2026, 8, 20, tzinfo=UTC)
        hit = SageHit("query:test", "可信缓存内容", 1.0)
        with patch("shared.sage_wiki.query", return_value=hit):
            collect_expert_contexts([EXPERT], now=now)
        cache = self.root / "data" / "sage-cache" / f"{EXPERT}.json"
        payload = json.loads(cache.read_text(encoding="utf-8"))
        payload["content"] += "篡改"
        cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with patch(
            "shared.sage_wiki.query",
            side_effect=SageWikiError("network timeout"),
        ):
            with self.assertRaises(SageWikiError) as raised:
                collect_expert_contexts(
                    [EXPERT], now=now + dt.timedelta(days=1),
                )
        self.assertIn("content_sha256 重算不一致", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
