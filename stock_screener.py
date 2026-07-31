#!/usr/bin/env python3
"""
[DEPRECATED] stock_screener.py — 已废弃，请勿使用。

本文件是早期原型，存在以下问题：
  1. 跨项目引用 ~/ai-berkshire，违反 CLAUDE.md 定义的双管道独立约束
  2. 依赖 data/analysis_queue.json（已从 repo 删除）
  3. 无任何其他文件引用，功能已被 scripts/cron_trigger.sh + scripts/pick_stocks.py 替代

如需删除此文件，无任何影响。保留仅供历史参考。
"""

import json
import sys
import os
import subprocess
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent
QUEUE_PATH = SKILL_ROOT / "data" / "analysis_queue.json"
REPORTS_DIR = SKILL_ROOT / "reports"
AI_BERKSHIRE = Path.home() / "ai-berkshire"

# ── 初始股票池（按行业分散排列，市值从大到小）
DEFAULT_POOL = [
    # 银行金融
    "601398.SH",  # 工商银行
    "601939.SH",  # 建设银行
    "601288.SH",  # 农业银行
    "600036.SH",  # 招商银行
    "600519.SH",  # 贵州茅台（白酒）
    "000858.SZ",  # 五粮液
    "600809.SH",  # 山西汾酒
    
    # 消费
    "600887.SH",  # 伊利股份
    "002304.SZ",  # 洋河股份
    "000568.SZ",  # 泸州老窖
    "600690.SH",  # 海尔智家
    "000333.SZ",  # 美的集团
    "000651.SZ",  # 格力电器
    "002415.SZ",  # 海康威视
    "300760.SZ",  # 迈瑞医疗
    "600276.SH",  # 恒瑞医药
    "300015.SZ",  # 爱尔眼科
    
    # 科技
    "000725.SZ",  # 京东方A
    "002475.SZ",  # 立讯精密
    "300124.SZ",  # 汇川技术
    "002230.SZ",  # 科大讯飞
    
    # 新能源
    "300750.SZ",  # 宁德时代
    "601012.SH",  # 隆基绿能
    "300274.SZ",  # 阳光电源
    
    # 周期/制造
    "600585.SH",  # 海螺水泥
    "000002.SZ",  # 万科A
    "601899.SH",  # 紫金矿业
    "600031.SH",  # 三一重工
    "600309.SH",  # 万华化学
    
    # 已分析的（跳过）
    "300408.SZ",  # 已分析
    "603605.SH",  # 已分析
    "600436.SH",  # 已分析
    "002050.SZ",  # 已分析
    "301165.SZ",  # 已分析
    "300529.SZ",  # 已分析
]

# 已分析过的股票（跳过）
ALREADY_ANALYZED = {"300408.SZ", "603605.SH", "600436.SH", "002050.SZ", "301165.SZ", "300529.SZ"}
# ST 跳过
ST_STOCKS = set()


def load_queue():
    """加载队列"""
    if QUEUE_PATH.exists():
        with open(QUEUE_PATH) as f:
            return json.load(f)
    else:
        # 初始化队列
        pool = [s for s in DEFAULT_POOL if s not in ALREADY_ANALYZED and s not in ST_STOCKS]
        queue = {"version": 1, "created": datetime.now().isoformat(), "queue": pool, "completed": []}
        save_queue(queue)
        return queue


def save_queue(queue):
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_PATH, "w") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def list_queue():
    queue = load_queue()
    print(f"分析队列 (共{len(queue['queue'])}家)")
    print(f"已完成: {len(queue['completed'])}家")
    print()
    if queue["queue"]:
        print("待分析:")
        for i, code in enumerate(queue["queue"][:10]):
            print(f"  {i+1}. {code}")
        if len(queue["queue"]) > 10:
            print(f"  ... 还有 {len(queue['queue'])-10} 家")
    if queue["completed"]:
        print("\n最近完成的:")
        for c in queue["completed"][-3:]:
            print(f"  {c['code']} ({c.get('date','?')})")


def add_to_queue(code):
    queue = load_queue()
    if code in queue["queue"]:
        print(f"{code} 已在队列中")
        return
    if code in ALREADY_ANALYZED:
        print(f"{code} 已分析过，跳过")
        return
    queue["queue"].append(code)
    save_queue(queue)
    print(f"{code} 已加入队列")


def run_analysis():
    """启动一次分析"""
    queue = load_queue()
    if not queue["queue"]:
        print("队列已空，无处可分析")
        return
        
    # 取下一家
    code = queue["queue"][0]
    today = datetime.now().strftime("%Y-%m-%d")
    report_dir = REPORTS_DIR / today
    report_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"=== 分析 {code} ===")
    print(f"日期: {today}")
    print(f"管道A: invest-skill → {report_dir}/{code}_report_A_{today}.md")
    print(f"管道B: sina_finance → {report_dir}/{code}_report_B_{today}.md")
    print()
    
    # 记录到队列
    completed = {"code": code, "date": today, "status": "started"}
    queue["completed"].append(completed)
    queue["queue"].pop(0)
    save_queue(queue)
    
    # 打印下2家预告
    if queue["queue"]:
        print(f"下一家: {queue['queue'][0]}")
        if len(queue["queue"]) > 1:
            print(f"再下一家: {queue['queue'][1]}")
    
    return code, today, report_dir


def main():
    if len(sys.argv) == 1:
        # 默认查看状态
        list_queue()
        return
    
    cmd = sys.argv[1]
    if cmd == "list":
        list_queue()
    elif cmd == "run":
        run_analysis()
    elif cmd == "add" and len(sys.argv) >= 3:
        add_to_queue(sys.argv[2].upper())
    else:
        print(f"未知命令: {cmd}")
        print("用法: python3 stock_screener.py [list|run|add <code>]")
        sys.exit(1)


if __name__ == "__main__":
    main()
