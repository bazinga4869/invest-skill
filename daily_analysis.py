#!/usr/bin/env python3
"""
daily_analysis.py — 每日双管道股票分析调度器
============================================
每天自动选择2家公司，走双管道出报告：
  - 管道A: invest-tool（Tushare财务数据 + SKILL.md 7+1 专家团）
  - 管道B: sina_finance.py（新浪财经数据 + ai-berkshire框架）

用法:
  python3 daily_analysis.py                    # 查看队列
  python3 daily_analysis.py run                 # 跑一次（分析今天应分析的2家）
  python3 daily_analysis.py today               # 查看今天安排
  python3 daily_analysis.py status              # 进度统计
"""

import json, sys, os, subprocess
from datetime import datetime, date
from pathlib import Path

BASE = Path.home() / "invest-skill"
QUEUE_FILE = BASE / "data" / "stock_pool.json"
PROGRESS_FILE = BASE / "data" / "analysis_progress.json"
REPORTS_DIR = BASE / "reports"
AI_BERKSHIRE = Path.home() / "ai-berkshire"

# ── 初始状态 ──

def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"version": 2, "last_analysis_date": None, "completed_codes": [], "today_codes": []}

def save_progress(p):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)

def load_pool():
    with open(QUEUE_FILE) as f:
        return json.load(f)

def get_next_company(pool, progress):
    """按市值从大到小找下一个未分析的公司"""
    completed = set(progress["completed_codes"])
    for s in pool:
        if s["ts_code"] not in completed:
            return s
    return None

# ── 管道A: invest-tool 分析 ──

def run_pipe_a(code, today_str, report_path):
    """通过 Claude Code 执行 invest-tool 管道的完整分析"""
    name = code.replace(".SH","").replace(".SZ","")
    prompt = f"""请按照 invest-skill 的 SKILL.md 分析协议，分析股票 {code}。

步骤：
1. 确认日期 {today_str}，更新 config.yaml 的 analysis_date
2. 同步数据: python3 shared/data_tools.py sync {code}
3. 检查业绩预告: python3 shared/data_tools.py forecast {code}
4. 读取 CLAUDE.md 组建专家团（唐朝、格雷厄姆、费雪、多尔西、马克斯）
5. 获取全部数据: python3 shared/data_tools.py all {code}
6. 各专家独立评估并评分
7. 交叉验证
8. 报告保存到 {report_path}

工作目录: {BASE}
约束：使用 .venv 的 Python，TUSHARE_TOKEN 从 .env 读取"""
    
    cmd = f"""cd {BASE} && echo '{prompt}' | claude -p --permission-mode bypassPermissions --allowedTools "Read,Bash,Write,Edit" > /tmp/pipe_a_{code}.log 2>&1"""
    
    result = subprocess.run(cmd, shell=True, timeout=600, capture_output=True, text=True)
    return result.returncode == 0

# ── 管道B: sina_finance 分析 ──

def run_pipe_b(code, today_str, report_path):
    """通过 Claude Code 执行 sina_finance 管道的完整分析"""
    prompt = f"""请使用 ai-berkshire 的分析框架 + tools/sina_finance.py 独立分析 A 股股票 {code}。

**所有 A 股财务数据必须从 tools/sina_finance.py 获取，不得使用 invest-skill 的数据。**
这是完全独立的 Source B 管道，用于与 invest-tool 数据交叉验证。

步骤：
1. 读取 ai-berkshire/AGENTS.md 了解项目规范
2. 获取行情: python3 tools/sina_finance.py quote {code}
3. 获取利润表: python3 tools/sina_finance.py income {code}
4. 获取资产负债表: python3 tools/sina_finance.py balance {code}
5. 获取现金流量表: python3 tools/sina_finance.py cashflow {code}
6. 获取财务指标: python3 tools/sina_finance.py fin_ratio {code}
7. 基于以上独立数据，按 invest-tool 的专家框架（唐朝/格雷厄姆/费雪/多尔西/马克斯）完成完整分析
8. 报告保存到 {report_path}

工作目录: {AI_BERKSHIRE}"""
    
    cmd = f"""cd {AI_BERKSHIRE} && echo '{prompt}' | claude -p --permission-mode bypassPermissions --allowedTools "Read,Bash,Write,Edit" > /tmp/pipe_b_{code}.log 2>&1"""
    
    result = subprocess.run(cmd, shell=True, timeout=600, capture_output=True, text=True)
    return result.returncode == 0

# ── 主逻辑 ──

def run_analysis():
    """执行一次分析（~1家公司，双管道）"""
    pool = load_pool()
    progress = load_progress()
    
    company = get_next_company(pool, progress)
    if not company:
        print("队列已全部完成！")
        return
    
    code = company["ts_code"]
    name = company["name"]
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    report_dir = REPORTS_DIR / today_str
    report_dir.mkdir(parents=True, exist_ok=True)
    report_a = report_dir / f"{code}_invest_tool_{today_str}.md"
    report_b = report_dir / f"{code}_sina_finance_{today_str}.md"
    
    print(f"=== 分析 {name} ({code}) ===")
    print(f"行业: {company.get('industry','')} | 市值: {company.get('total_mv',0)/10000:.0f}亿")
    print(f"日期: {today_str}")
    print(f"管道A → {report_a}")
    print(f"管道B → {report_b}")
    print()
    
    # 管道A
    print("[1/2] 管道A: invest-tool 分析中...")
    ok_a = run_pipe_a(code, today_str, str(report_a))
    print(f"  管道A: {'✅ 完成' if ok_a else '❌ 失败'}")
    
    # 管道B
    print("[2/2] 管道B: sina_finance 分析中...")
    ok_b = run_pipe_b(code, today_str, str(report_b))
    print(f"  管道B: {'✅ 完成' if ok_b else '❌ 失败'}")
    
    # 记录进度
    progress["completed_codes"].append(code)
    progress["last_analysis_date"] = today_str
    save_progress(progress)
    
    print(f"\n🎯 完成: {name} ({code})")
    if ok_a: print(f"  报告A: {report_a}")
    if ok_b: print(f"  报告B: {report_b}")
    
    # 下一家预告
    next_co = get_next_company(pool, progress)
    if next_co:
        mv = next_co.get("total_mv", 0) / 10000
        print(f"\n下一家: {next_co['name']} ({next_co['ts_code']}) {mv:.0f}亿")
    
    return ok_a or ok_b

def show_status():
    pool = load_pool()
    progress = load_progress()
    completed = set(progress["completed_codes"])
    
    total = len(pool)
    done = len(completed)
    remaining = total - done
    
    print(f"股票池总计: {total} 家")
    print(f"已完成分析: {done} 家")
    print(f"待分析: {remaining} 家")
    print(f"进度: {done/total*100:.1f}%")
    print()
    
    if remaining > 0:
        print("接下来10家:")
        count = 0
        for s in pool:
            if s["ts_code"] not in completed:
                mv = s.get("total_mv", 0) / 10000
                print(f"  {s['ts_code']} {s['name']} ({s.get('industry','')}) {mv:.0f}亿")
                count += 1
                if count >= 10:
                    break

def main():
    if len(sys.argv) == 1:
        show_status()
        return
    
    cmd = sys.argv[1]
    if cmd in ("status", "st"):
        show_status()
    elif cmd == "run":
        run_analysis()
    elif cmd == "today":
        print(f"今日({datetime.now().strftime('%Y-%m-%d')})分析安排:")
        pool = load_pool()
        progress = load_progress()
        c = get_next_company(pool, progress)
        if c:
            mv = c.get("total_mv", 0) / 10000
            print(f"  1. {c['name']} ({c['ts_code']}) {c.get('industry','')} {mv:.0f}亿")
    else:
        print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()
