#!/usr/bin/env python3
"""
从全 A 股池中随机选取 N 只股票（排除科创/北交/ST/尚无年报可用的新上市股）。
用法：python3 pick_stocks.py <N> [seed]
输出：每行 "ts_code 公司名"
"""
import datetime
import os
import sqlite3
import random
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))
from shared.project_config import configured_path
_db_override = os.environ.get("INVEST_DB_PATH")
DB_PATH = (Path(_db_override).expanduser() if _db_override
           else configured_path("db_file", "./data/invest_skill.db"))


def _annual_report_cutoff(as_of: datetime.date | None = None) -> str:
    """最近应有年报（end_year）的合理披露截止（次年 6/30）。

    晚于该日期上市的公司，其最近年报在上市前披露，巨潮在该代码下无档，
    materialize 必然缺年失败；这类股票从每日选股池排除。
    """
    today = as_of or datetime.date.today()
    end_year = today.year - 1 if today.month >= 5 else today.year - 2
    return f"{end_year + 1}-06-30"


def pick(n: int, seed: str = "") -> list[tuple[str, str]]:
    db = sqlite3.connect(str(DB_PATH))
    cutoff = _annual_report_cutoff()
    cur = db.execute("""
        SELECT ts_code, name FROM stocks
        WHERE name IS NOT NULL AND name != ''
        AND ts_code NOT LIKE '688%'
        AND ts_code NOT LIKE '8%'
        AND name NOT LIKE '%ST%'
        AND ts_code NOT LIKE '%ST%'
        AND (list_date IS NULL OR list_date <= ?)
        ORDER BY ts_code
    """, (cutoff,))
    all_stocks = [(row[0], row[1]) for row in cur]
    db.close()

    if seed:
        random.seed(seed)
    picked = random.sample(all_stocks, min(n, len(all_stocks)))
    return picked

if __name__ == "__main__":
    n = int(sys.argv[1])
    seed = sys.argv[2] if len(sys.argv) > 2 else ""
    for code, name in pick(n, seed):
        print(f"{code} {name}")
