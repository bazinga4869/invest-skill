import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from shared.report_wiki import (
    BUNDLE_SCHEMA_VERSION,
    ReportWikiError,
    bundle_hash,
    expected_fiscal_years,
    materialize_report_bundle,
    render_annual_text,
    validate_report_bundle,
)


CODE = "000001.SZ"
AS_OF = datetime(2026, 8, 1)


def valid_bundle(*, years: int = 1) -> dict:
    reports = []
    for year in expected_fiscal_years(AS_OF, years):
        sections = []
        for page, name in enumerate((
            "管理层讨论与分析", "经营情况讨论与分析",
            "公司未来发展的展望", "可能面对的风险",
        ), start=10):
            sentence = f"{name}只陈述正式披露事实并保留风险边界，年度{year}。"
            text = "\n".join(f"{sentence}核对序号{i}。" for i in range(120))
            sections.append({
                "name": name,
                "text": text,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "page_start": page,
                "page_end": page + 1,
            })
        source = f"{CODE}-{year}".encode()
        sections_identity = {"sections": [
            {
                "name": item["name"], "text_sha256": item["text_sha256"],
                "page_start": item["page_start"], "page_end": item["page_end"],
            }
            for item in sections
        ]}
        sections_hash = hashlib.sha256(
            json.dumps(
                sections_identity, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        source_hash = hashlib.sha256(source).hexdigest()
        document_hash = hashlib.sha256(f"document-{year}".encode()).hexdigest()
        build_id = hashlib.sha256(f"build-{year}".encode()).hexdigest()
        rules_hash = hashlib.sha256(b"rules").hexdigest()
        reports.append({
            "fiscal_year": year,
            "report_type": "annual",
            "announcement_date": f"{int(year) + 1}0430",
            "title": f"{year}年年度报告",
            "source_url": f"https://example.invalid/{CODE}/{year}.pdf",
            "source_path": f"raw/annual/{year}/report.pdf",
            "source_sha256": source_hash,
            "source_bytes": 20_000,
            "downloaded_at": f"{int(year) + 1}-04-30T00:00:00+00:00",
            "page_count": 100,
            "provenance_level": "page-exact",
            "evidence_build_id": build_id,
            "document_sha256": document_hash,
            "sections_sha256": sections_hash,
            "evidence_rules_hash": rules_hash,
            "document_path": f"evidence/annual/{year}/document.json",
            "pages_path": f"evidence/annual/{year}/pages",
            "parser": {
                "engine": "pypdfium2", "versions": {"pypdfium2": "test"},
                "ocr": {"status": "not-required"},
            },
            "sage_source_status": "generated",
            "sections": sections,
        })
    corpus_identity = {
        report["fiscal_year"]: {
            "source_sha256": report["source_sha256"],
            "document_sha256": report["document_sha256"],
            "sections_sha256": report["sections_sha256"],
            "build_id": report["evidence_build_id"],
            "report_type": report["report_type"],
        }
        for report in reports
    }
    corpus_hash = hashlib.sha256(json.dumps(
        corpus_identity, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    bundle = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "status": "PASS",
        "evidence_status": "PASS",
        "summary_status": "UNAVAILABLE",
        "ts_code": CODE,
        "as_of": AS_OF.strftime("%Y%m%d"),
        "requested_years": expected_fiscal_years(AS_OF, years),
        "report_types": ["annual"],
        "corpus_hash": corpus_hash,
        "search": {
            "status": "PASS", "engine": "sqlite-fts5-bm25",
            "schema_version": "report-wiki.search.v2",
            "path": "evidence/search.sqlite3",
            "content_hash": hashlib.sha256(b"search").hexdigest(),
            "document_count": len(reports), "page_count": 100 * len(reports),
        },
        "sage": {
            "workspace": f"companies/{CODE}/sage",
            "engine_version": "unavailable",
            "status": "unavailable",
            "coverage_status": "UNAVAILABLE",
            "provenance_status": "UNAVAILABLE",
        },
        "reports": reports,
        "missing": [],
        "warnings": [],
    }
    bundle["bundle_hash"] = bundle_hash(bundle)
    return bundle


class ReportWikiContractTests(unittest.TestCase):
    def test_valid_bundle_passes_and_renders_deterministically(self):
        bundle = valid_bundle()
        self.assertEqual(validate_report_bundle(
            bundle, ts_code=CODE, as_of=AS_OF, years=1,
        ), [])
        rendered = render_annual_text(bundle)
        self.assertIn("### 2025年 annual", rendered)
        self.assertIn("#### 经营情况讨论与分析", rendered)

    def test_consumer_view_prioritizes_latest_year(self):
        bundle = valid_bundle(years=2)
        rendered = render_annual_text(bundle)
        self.assertLess(rendered.index("### 2025年"), rendered.index("### 2024年"))

    def test_semiannual_bundle_is_validated_and_rendered(self):
        bundle = valid_bundle()
        semi = copy.deepcopy(bundle["reports"][0])
        semi.update({
            "fiscal_year": "2025H1",
            "report_type": "semi",
            "announcement_date": "20250826",
            "title": "2025年半年度报告",
            "source_path": "raw/semi/2025H1/report.pdf",
            "source_sha256": hashlib.sha256(b"semi-source").hexdigest(),
            "evidence_build_id": hashlib.sha256(b"semi-build").hexdigest(),
            "document_sha256": hashlib.sha256(b"semi-document").hexdigest(),
            "document_path": "evidence/semi/2025H1/document.json",
            "pages_path": "evidence/semi/2025H1/pages",
        })
        bundle["reports"].append(semi)
        bundle["report_types"] = ["annual", "semi"]
        bundle["requested_periods"] = ["annual:2025", "semi:2025H1"]
        bundle["search"]["document_count"] = 2
        bundle["search"]["page_count"] = 200
        corpus_identity = {
            (
                report["fiscal_year"] if report["report_type"] == "annual"
                else f'{report["report_type"]}:{report["fiscal_year"]}'
            ): {
                "source_sha256": report["source_sha256"],
                "document_sha256": report["document_sha256"],
                "sections_sha256": report["sections_sha256"],
                "build_id": report["evidence_build_id"],
                "report_type": report["report_type"],
            }
            for report in bundle["reports"]
        }
        bundle["corpus_hash"] = hashlib.sha256(json.dumps(
            corpus_identity, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        bundle["bundle_hash"] = bundle_hash(bundle)
        self.assertEqual(validate_report_bundle(
            bundle, ts_code=CODE, as_of=AS_OF, years=1,
            report_types=("annual", "semi"), semi_years=1,
        ), [])
        rendered = render_annual_text(bundle)
        self.assertIn("### 2025年 semi", rendered)
        self.assertNotIn("2025H1年", rendered)

    def test_missing_year_and_future_announcement_are_rejected(self):
        bundle = valid_bundle(years=2)
        bundle["reports"].pop(0)
        bundle["reports"][0]["announcement_date"] = "20270101"
        bundle["bundle_hash"] = bundle_hash(bundle)
        problems = validate_report_bundle(
            bundle, ts_code=CODE, as_of=AS_OF, years=2,
        )
        self.assertTrue(any("年度/类型集合" in item for item in problems))
        self.assertTrue(any("晚于分析时点" in item for item in problems))

    def test_text_tampering_breaks_section_and_bundle_hashes(self):
        bundle = valid_bundle()
        bundle["reports"][0]["sections"][0]["text"] += "篡改"
        problems = validate_report_bundle(
            bundle, ts_code=CODE, as_of=AS_OF, years=1,
        )
        self.assertTrue(any("bundle_hash 重算不一致" in item for item in problems))
        self.assertTrue(any("text_sha256 重算不一致" in item for item in problems))

    def test_fixture_bypass_requires_explicit_test_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "bundle.json"
            output = root / "output.json"
            fixture.write_text(json.dumps(valid_bundle()), encoding="utf-8")
            with patch.dict(os.environ, {
                "INVEST_TEST_MODE": "1",
                "INVEST_REPORT_WIKI_FIXTURE": str(fixture),
            }, clear=False):
                result = materialize_report_bundle(
                    CODE, as_of=AS_OF, years=1, output=output,
                )
            self.assertEqual(result["bundle_hash"], valid_bundle()["bundle_hash"])
            self.assertTrue(output.is_file())

            with patch.dict(os.environ, {
                "INVEST_TEST_MODE": "0",
                "INVEST_REPORT_WIKI_FIXTURE": str(fixture),
                "INVEST_REPORT_WIKI_CLI": str(root / "missing-cli"),
            }, clear=False):
                with self.assertRaises(ReportWikiError):
                    materialize_report_bundle(
                        CODE, as_of=AS_OF, years=1, output=output,
                    )


if __name__ == "__main__":
    unittest.main()
