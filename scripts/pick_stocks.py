#!/usr/bin/env python3
"""
从全 A 股池中随机选取 N 只股票（排除科创/北交/ST）。
用法：python3 pick_stocks.py <N> [seed]
输出：每行 "ts_code 公司名"
"""
import sqlite3
import random
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = SKILL_ROOT / "data" / "invest_skill.db"

def pick(n: int, seed: str = "") -> list[tuple[str, str]]:
    db = sqlite3.connect(str(DB_PATH))
    cur = db.execute("""
        SELECT ts_code, name FROM stocks
        WHERE name IS NOT NULL AND name != ''
        AND ts_code NOT LIKE '688%'
        AND ts_code NOT LIKE '8%'
        AND name NOT LIKE '%ST%'
        AND ts_code NOT LIKE '%ST%'
        ORDER BY ts_code
    """)
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
