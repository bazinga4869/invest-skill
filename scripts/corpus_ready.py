#!/usr/bin/env python3
"""corpus_ready.py — report-wiki 语料就绪度快速门禁（只读，不下载不编译）。

daily_analysis.sh 在 prepare 前调用，避免对未建库/未预热的股票空烧
materialize_timeout_seconds（3600s）后整体失败：

退出码：
- 0 = 就绪或仅剩 Sage 编译（原件/证据完整，可增量续跑）→ 允许 prepare
- 1 = 语料未就绪（缺原件/证据/Sage 未初始化）→ 跳过该股票，由 prewarm 晚间预热

语料就绪判定与 prepare 完全同口径：as_of 取分析日期，years 走
listing_aware_years（上市年份感知），状态由 report-wiki status 只读给出。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from shared.project_config import configured_path, report_wiki_cli, report_wiki_repo  # noqa: E402
from shared.report_wiki import listing_aware_years  # noqa: E402

# 允许继续 prepare 的逐年状态（原件/证据已就绪，Sage 编译可增量续跑）
_PROCEED_YEAR_STATUSES = {"raw-ok", "evidence", "evidence-ok"}


def corpus_ready(ts_code: str, as_of: datetime.date, years: int) -> tuple[bool, dict]:
    """调用 report-wiki status，返回 (可继续?, status 摘要)。"""
    cli = report_wiki_cli()
    project = report_wiki_repo()
    if not cli.is_file() or not os.access(cli, os.X_OK):
        return False, {"error": f"report-wiki CLI 不可用: {cli}"}
    command = [
        str(cli), "status", "--code", ts_code,
        "--as-of", as_of.strftime("%Y%m%d"),
        "--years", str(years), "--format", "json",
    ]
    try:
        result = subprocess.run(
            command, cwd=str(project), capture_output=True, text=True,
            timeout=90, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return False, {"error": f"report-wiki status 超时: {exc.timeout}s"}
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        return False, {"error": f"report-wiki status 输出无法解析: {exc}"}
    if result.returncode == 0:
        return True, payload
    per_year = payload.get("per_year", [])
    if not per_year:
        return False, payload
    all_proceed = all(
        item.get("status") in _PROCEED_YEAR_STATUSES for item in per_year
    )
    return all_proceed, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", help="ts_code，如 000001.SZ")
    parser.add_argument("--as-of", default="", help="YYYYMMDD，缺省今天")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    as_of = (
        datetime.datetime.strptime(args.as_of, "%Y%m%d").date()
        if args.as_of else datetime.date.today()
    )
    try:
        years = listing_aware_years(args.code, as_of)
    except Exception as exc:  # noqa: BLE001 —— 查询失败回退 5 年
        years = 5
    ok, payload = corpus_ready(args.code, as_of, years)
    if args.verbose:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
