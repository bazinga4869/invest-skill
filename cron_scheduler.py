#!/usr/bin/env python3
"""
cron_scheduler.py — 每日双管道cron调度
每天2家公司，从 stock_pool.json 按市值从大到小顺序取。
上午10:00 跑第1家，下午15:00 跑第2家。

用法:
  python3 cron_scheduler.py                    # 看队列
  python3 cron_scheduler.py next               # 取下一家
  python3 cron_scheduler.py mark-completed     # 标记今日执行完成
"""

import json, sys, os, subprocess
from datetime import datetime
from pathlib import Path

BASE = Path.home() / "invest-skill"
POOL = BASE / "data" / "stock_pool.json"
PROGRESS = BASE / "data" / "analysis_progress.json"
SCRIPT = BASE / "run_daily_analysis.sh"


def load_progress():
    if PROGRESS.exists():
        with open(PROGRESS) as f:
            return json.load(f)
    return {"version": 2, "last_analysis_date": None, "completed_codes": [], "today_codes": []}


def save_progress(p):
    with open(PROGRESS, "w") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def load_pool():
    with open(POOL) as f:
        return json.load(f)


def get_next_code():
    pool = load_pool()
    progress = load_progress()
    completed = set(progress["completed_codes"])
    for s in pool:
        if s["ts_code"] not in completed:
            return s["ts_code"], s["name"], s.get("industry", ""), s.get("total_mv", 0)
    return None, None, None, 0


def run_next():
    code, name, industry, mv = get_next_code()
    if not code:
        print("队列已空！")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    mv_yi = mv / 10000
    print(f"分析: {name} ({code}) 行业:{industry} 市值:{mv_yi:.0f}亿")

    result = subprocess.run(
        ["bash", str(SCRIPT), code],
        capture_output=False, timeout=600
    )

    # 记录
    progress = load_progress()
    if code not in progress["completed_codes"]:
        progress["completed_codes"].append(code)

    today_codes = progress.get("today_codes", [])
    if code not in today_codes:
        today_codes.append(code)
    progress["today_codes"] = today_codes
    progress["last_analysis_date"] = today
    save_progress(progress)

    rc = result.returncode
    print(f"完成: {code} (exit={rc})")

    # 预告下一家
    next_code, next_name, _, next_mv = get_next_code()
    if next_code:
        print(f"下一家: {next_name} ({next_code}) {next_mv/10000:.0f}亿")

    return rc == 0


def show_status():
    pool = load_pool()
    progress = load_progress()
    completed = set(progress["completed_codes"])
    remaining = len(pool) - len(completed)

    print(f"全市场池: {len(pool)} 家")
    print(f"已完成: {len(completed)} 家")
    print(f"待分析: {remaining} 家")

    today = datetime.now().strftime("%Y-%m-%d")
    today_codes = progress.get("today_codes", [])
    done_today = len([c for c in today_codes if c in completed])

    print(f"今日已分析: {done_today} 家")
    print()

    if remaining > 0:
        print("接下来:")
        count = 0
        for s in pool:
            if s["ts_code"] not in completed:
                mv = s.get("total_mv", 0) / 10000
                print(f"  {s['ts_code']} {s['name']} ({s.get('industry','')}) {mv:.0f}亿")
                count += 1
                if count >= 5:
                    break


def main():
    if len(sys.argv) == 1:
        show_status()
    elif sys.argv[1] == "next":
        run_next()
    elif sys.argv[1] == "mark-completed":
        progress = load_progress()
        today = datetime.now().strftime("%Y-%m-%d")
        progress["today_codes"] = []
        progress["last_analysis_date"] = today
        save_progress(progress)
        print("今日标记完成")
    elif sys.argv[1] == "status":
        show_status()
    else:
        print(f"用法: {sys.argv[0]} [next|status|mark-completed]")


if __name__ == "__main__":
    main()
