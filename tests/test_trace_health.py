import datetime as dt
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import trace_health


class TraceHealthFilterTests(unittest.TestCase):
    def test_recent_exception_examples_use_code_and_day_filters(self):
        now = dt.datetime.now(dt.timezone.utc)
        recent = {
            "ts": now.isoformat(), "phase": "expert", "status": "error",
            "code": "000001.SZ", "msg": "selected current failure",
        }
        unrelated = {
            "ts": now.isoformat(), "phase": "expert", "status": "error",
            "code": "000002.SZ", "msg": "other code failure",
        }
        old = {
            "ts": (now - dt.timedelta(days=30)).isoformat(),
            "phase": "expert", "status": "error",
            "code": "000001.SZ", "msg": "old failure",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "000001.SZ.jsonl").write_text(
                "\n".join(json.dumps(item) for item in (old, recent)),
                encoding="utf-8",
            )
            (root / "000002.SZ.jsonl").write_text(
                json.dumps(unrelated), encoding="utf-8",
            )
            with patch.object(trace_health, "TRACE_DIR", root):
                events = trace_health.load_traces(days=7, code="000001.SZ")
                output = io.StringIO()
                with redirect_stdout(output):
                    trace_health.print_health(
                        trace_health.analyze(events), events=events,
                    )

        text = output.getvalue()
        self.assertIn("selected current failure", text)
        self.assertNotIn("other code failure", text)
        self.assertNotIn("old failure", text)


if __name__ == "__main__":
    unittest.main()
