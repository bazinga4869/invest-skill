import math
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import numpy as np

from shared.data_source import normalize_date, yuan_to_wan
from shared.data_tools import (
    _f,
    _json_dumps,
    _migrate_schema,
    _series_cagr,
    _standalone_quarters,
    _sum_nullable,
    _ttm,
    _yi,
    cmd_annual_report,
    cmd_market,
    validate_snapshot,
)


class DataContractTests(unittest.TestCase):
    def test_ytd_is_deaccumulated_to_standalone_quarters(self):
        frame = pd.DataFrame([
            {"end_date": "20240331", "report_type": "1", "value": 10},
            {"end_date": "20240630", "report_type": "1", "value": 25},
            {"end_date": "20240930", "report_type": "1", "value": 45},
            {"end_date": "20241231", "report_type": "1", "value": 70},
        ])
        result = _standalone_quarters(frame, ["value"])
        self.assertEqual([result[key]["value"] for key in sorted(result)], [10, 15, 20, 25])
        self.assertEqual(result["20241231"]["value_ytd"], 70)

    def test_missing_predecessor_does_not_invent_quarter(self):
        frame = pd.DataFrame([
            {"end_date": "20240331", "report_type": "1", "value": 10},
            {"end_date": "20240930", "report_type": "1", "value": 45},
        ])
        result = _standalone_quarters(frame, ["value"])
        self.assertIsNone(result["20240930"]["value"])

    def test_report_type_two_is_already_single_quarter(self):
        frame = pd.DataFrame([
            {"end_date": "20240630", "report_type": "2", "value": 15},
        ])
        result = _standalone_quarters(frame, ["value"])
        self.assertEqual(result["20240630"]["value"], 15)
        self.assertIsNone(result["20240630"]["value_ytd"])

    def test_single_quarter_row_does_not_break_ytd_chain(self):
        frame = pd.DataFrame([
            {"end_date": "20240331", "report_type": "1", "value": 10},
            {"end_date": "20240630", "report_type": "1", "value": 25},
            {"end_date": "20240630", "report_type": "2", "value": 15},
            {"end_date": "20240930", "report_type": "1", "value": 45},
        ])
        result = _standalone_quarters(frame, ["value"])
        self.assertEqual(result["20240630"]["value"], 15)
        self.assertEqual(result["20240630"]["value_ytd"], 25)
        self.assertEqual(result["20240930"]["value"], 20)

    def test_unknown_report_type_is_not_guessed_as_ytd(self):
        frame = pd.DataFrame([
            {"end_date": "20240331", "report_type": "3", "value": 10},
            {"end_date": "20240630", "report_type": "3", "value": 15},
        ])
        result = _standalone_quarters(frame, ["value"])
        self.assertIsNone(result["20240331"]["value"])
        self.assertIsNone(result["20240630"]["value"])

    def test_ttm_requires_four_consecutive_non_null_quarters(self):
        periods = [
            {"period": "20241231", "quarter": 4, "ocf_yi": 4},
            {"period": "20240930", "quarter": 3, "ocf_yi": 3},
            {"period": "20240630", "quarter": 2, "ocf_yi": 2},
            {"period": "20240331", "quarter": 1, "ocf_yi": 1},
        ]
        self.assertEqual(_ttm(periods, "ocf_yi"), 10)
        periods[2]["ocf_yi"] = None
        self.assertIsNone(_ttm(periods, "ocf_yi"))

    def test_ttm_rounds_only_after_summing_raw_yuan(self):
        periods = [
            {"period": period, "quarter": quarter, "ocf": 150_400_000}
            for period, quarter in [
                ("20241231", 4), ("20240930", 3),
                ("20240630", 2), ("20240331", 1),
            ]
        ]
        self.assertEqual(_yi(_ttm(periods, "ocf")), 6.02)

    def test_cagr_uses_actual_year_distance_and_exact_horizon(self):
        points = [(2021, 100), (2023, 121)]
        self.assertEqual(_series_cagr(points), 10.0)
        self.assertIsNone(_series_cagr(points, 5))

    def test_missing_and_nonfinite_values_are_not_zero(self):
        self.assertIsNone(_f(float("nan")))
        self.assertIsNone(_f(float("inf")))
        self.assertIsNone(_sum_nullable([1, None, 2]))
        self.assertEqual(_sum_nullable([1, 0, 2]), 3)

    def test_adapter_units_and_dates(self):
        self.assertEqual(normalize_date("2026-07-30"), "20260730")
        self.assertEqual(yuan_to_wan("123,450,000"), 12345)
        self.assertIsNone(yuan_to_wan("--"))
        self.assertEqual(normalize_date(pd.NaT), "")
        self.assertEqual(normalize_date(pd.NA), "")
        self.assertIsNone(yuan_to_wan(float("nan")))
        self.assertIsNone(yuan_to_wan(float("inf")))

    def test_json_output_is_strict_and_nonfinite_becomes_null(self):
        text = _json_dumps({"a": float("nan"), "b": np.float64("inf")})
        self.assertEqual(json.loads(text), {"a": None, "b": None})
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)

    def test_forward_migration_adds_all_contract_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE cashflow (ts_code TEXT)")
        conn.execute("CREATE TABLE balance (ts_code TEXT)")
        conn.execute("CREATE TABLE fina_audit (opinion_type TEXT, audit_costs REAL)")
        conn.execute("INSERT INTO fina_audit VALUES ('标准无保留', 123)")
        _migrate_schema(conn)
        self.assertIn("c_pay_acq_const_fiolta", {
            row[1] for row in conn.execute("PRAGMA table_info(cashflow)")
        })
        self.assertIn("total_share", {
            row[1] for row in conn.execute("PRAGMA table_info(balance)")
        })
        audit_cols = {row[1] for row in conn.execute("PRAGMA table_info(fina_audit)")}
        self.assertTrue({"audit_result", "audit_fees", "audit_agency", "audit_sign"} <= audit_cols)
        self.assertEqual(
            conn.execute("SELECT audit_result, audit_fees FROM fina_audit").fetchone(),
            ("标准无保留", 123.0),
        )

    def test_snapshot_gate_warns_without_inventing_goodwill_and_capex(self):
        data = {
            "stock_info": {"ts_code": "000001.SZ", "name": "测试"},
            "market": {"ts_code": "000001.SZ", "trade_date": "20260730", "close": 10, "total_mv_yi": 100},
            "annual": {
                "ts_code": "000001.SZ", "count": 3,
                "annual_data": [
                    {"year": "2023", "revenue_yi": 1, "net_profit_yi": 1, "non_recurring_pct": 1},
                    {"year": "2024", "revenue_yi": 1.1, "net_profit_yi": 1.1, "non_recurring_pct": 1},
                    {"year": "2025", "revenue_yi": 1.21, "net_profit_yi": 1.21, "non_recurring_pct": 1},
                ],
                "revenue_cagr_full_pct": 10, "profit_cagr_full_pct": 10,
                "revenue_cagr_5y_pct": None, "profit_cagr_5y_pct": None,
            },
            "quarterly": {"periods": [
                {"period": period, "quarter": quarter, "revenue_yi": 1,
                 "net_profit_yi": 1, "ocf_yi": 1, "capex_yi": None, "fcf_yi": None}
                for period, quarter in [
                    ("20260331", 1), ("20251231", 4),
                    ("20250930", 3), ("20250630", 2),
                ]
            ], "ts_code": "000001.SZ", "ocf_ttm_complete": True,
               "ocf_ttm_yi": 4, "ttm_complete": False},
            "balance": {"ts_code": "000001.SZ", "end_date": "20251231",
                        "total_assets_yi": 10, "equity_yi": 6, "cash_yi": None,
                        "goodwill_yi": None, "interest_debt_yi": None},
            "indicators": {"ts_code": "000001.SZ", "count": 1, "indicators": [{
                "year": "2025", "roe_pct": 10, "gross_margin_pct": 20,
                "net_margin_pct": 8, "debt_ratio_pct": 30,
            }]},
            "audit": {"ts_code": "000001.SZ", "has_audit": True,
                      "latest": {"end_date": "20251231", "audit_result": "标准无保留"}},
            "industry": {"ts_code": "000001.SZ"},
            "forecast": {"ts_code": "000001.SZ"}, "macro": {},
        }
        quality = validate_snapshot(data)
        self.assertEqual(quality["status"], "WARN")
        self.assertTrue(any("goodwill" in message for message in quality["warnings"]))
        self.assertTrue(any("资本开支" in message for message in quality["warnings"]))
        self.assertTrue(any("cash_yi" in message for message in quality["warnings"]))

    def test_market_query_respects_historical_asof(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE daily_basic (ts_code TEXT, trade_date TEXT, close REAL, "
            "pe_ttm REAL, pb REAL, ps_ttm REAL, total_mv REAL, total_share REAL, "
            "turnover_rate REAL)"
        )
        conn.executemany(
            "INSERT INTO daily_basic VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("000001.SZ", "20200102", 10, 5, 1, 1, 10000, 1000, 1),
                ("000001.SZ", "20260730", 99, 9, 2, 2, 99000, 1000, 1),
            ],
        )
        with patch("shared.data_tools.get_db", return_value=conn), patch(
            "shared.data_tools.TODAY", datetime(2020, 1, 3)
        ):
            result = cmd_market("000001.SZ")
        self.assertEqual(result["trade_date"], "20200102")
        self.assertEqual(result["close"], 10)

    def test_annual_cache_never_skips_latest_expected_year(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "annual.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE annual_reports (ts_code TEXT, report_year TEXT, "
                "report_type TEXT, ann_date TEXT, title TEXT, section_name TEXT, "
                "section_text TEXT, source_url TEXT, updated_at TEXT)"
            )
            for year in (2022, 2023, 2024):
                conn.execute(
                    "INSERT INTO annual_reports VALUES (?,?,?,?,?,?,?,?,?)",
                    ("000001.SZ", str(year), "annual", f"{year + 1}0430", "年报",
                     "经营情况讨论与分析", "正文" * 600, "u", "now"),
                )
            conn.commit()
            conn.close()

            calls = []

            class FakeSource:
                cache = None

                def get_annual_report_text(self, ts_code, year):
                    calls.append(year)
                    return {"reports": {"annual": {
                        "ann_date": "20260430", "title": "2025年报", "source_url": "u",
                        "sections": {"经营情况讨论与分析": "最新正文" * 300},
                    }}} if year == "2025" else {"reports": {}}

            def fresh_conn():
                return sqlite3.connect(db_path)

            with patch("shared.data_tools.get_db", side_effect=fresh_conn), patch(
                "shared.data_tools.create_data_source", return_value=FakeSource()
            ), patch("shared.data_tools.TODAY", datetime(2026, 7, 31)):
                result = cmd_annual_report("000001.SZ", years=5, force=False)
            self.assertIn("2025", calls)
            self.assertIn("2025", result["years_fetched"])


if __name__ == "__main__":
    unittest.main()
