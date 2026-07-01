#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill: 公司综合分析生成器
项目：invest-skill（与 invest-wiki 解耦，但方法论以 wiki 为依据）

输入：公司名称或股票代码
输出：存储在 invest-skill/reports/ 目录下的综合报告（Markdown）

数据源：Tushare 为主，AKShare 为备用（通过 shared/data_source.py 自动回退）
"""

import argparse
import os
import sys
import sqlite3
import json
import hashlib
import math
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import pandas as pd
import numpy as np

# 把项目根目录加入路径
SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT))

from shared.data_source import create_data_source, code_to_symbol

CONFIG_PATH = SKILL_ROOT / "config.yaml"
DATA_DIR = SKILL_ROOT / "data"
REPORTS_DIR = SKILL_ROOT / "reports"
DB_PATH = DATA_DIR / "invest_skill.db"
SCHEMA_PATH = SKILL_ROOT / "schema.sql"

# ---------------------------------------------------------------------------
# 0. 配置与工具
# ---------------------------------------------------------------------------

def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()
TODAY = datetime.strptime(CONFIG["project"]["analysis_date"], "%Y-%m-%d")


def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def ensure_schema():
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema 文件缺失: {SCHEMA_PATH}")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
    if cur.fetchone() is None:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        print(f"[DB] 已初始化数据库: {DB_PATH}")
    conn.close()


def parse_ts_code(raw: str) -> Optional[str]:
    raw = raw.strip()
    if "." in raw:
        return raw.upper()
    if len(raw) == 6 and raw.isdigit():
        first = raw[0]
        if first in ("6", "5", "9"):
            return f"{raw}.SH"
        else:
            return f"{raw}.SZ"
    return None


def fmt_date(d) -> str:
    if d is None:
        return ""
    if isinstance(d, pd.Timestamp):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)


def safe_div(a, b, default=0.0):
    try:
        if b == 0 or b is None or math.isnan(b):
            return default
        return a / b
    except Exception:
        return default


def cagr(start, end, years):
    if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1 / years) - 1


# ---------------------------------------------------------------------------
# 1. Wiki 联动校验
# ---------------------------------------------------------------------------

def validate_wiki_dependencies() -> List[Dict]:
    drifts = []
    wiki_root = (SKILL_ROOT / CONFIG["wiki_dependencies"]["repo_path"]).resolve()
    for dep in CONFIG["wiki_dependencies"]["methodology_pages"]:
        full_path = wiki_root / dep["path"]
        if not full_path.exists():
            drifts.append({
                "type": "missing",
                "path": dep["path"],
                "purpose": dep.get("purpose", ""),
                "message": f"Wiki 依赖页面不存在: {dep['path']}"
            })
            continue
        content = open(full_path, "rb").read()
        h = hashlib.sha256(content).hexdigest()[:16]
        drifts.append({
            "type": "ok",
            "path": dep["path"],
            "sha256_prefix": h,
            "purpose": dep.get("purpose", "")
        })
    return drifts


def save_drift_report(drifts: List[Dict]):
    report_path = SKILL_ROOT / CONFIG["coupling"]["drift_report"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": TODAY.strftime("%Y-%m-%d"),
            "drifts": drifts,
            "block_on_drift": CONFIG["coupling"]["block_on_drift"]
        }, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 2. 数据同步
# ---------------------------------------------------------------------------

def write_stock_basic(df: pd.DataFrame):
    if df.empty:
        return
    now = TODAY.strftime("%Y-%m-%d")
    conn = get_db()
    for _, row in df.iterrows():
        conn.execute(
            """INSERT INTO stocks(ts_code,symbol,name,fullname,exchange,list_date,industry,area,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ts_code) DO UPDATE SET
               symbol=excluded.symbol,name=excluded.name,fullname=excluded.fullname,
               exchange=excluded.exchange,list_date=excluded.list_date,
               industry=excluded.industry,area=excluded.area,updated_at=excluded.updated_at""",
            (row.get("ts_code"), row.get("symbol"), row.get("name"), row.get("fullname", ""),
             row.get("exchange", ""), row.get("list_date", ""), row.get("industry", ""),
             row.get("area", ""), now)
        )
    conn.commit()
    conn.close()


def write_daily_basic(df: pd.DataFrame, ts_code: str):
    if df.empty:
        return
    now = TODAY.strftime("%Y-%m-%d")
    conn = get_db()
    for _, row in df.iterrows():
        conn.execute(
            """INSERT INTO daily_basic(ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,
               pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,total_mv,circ_mv,total_share,float_share,free_share,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ts_code,trade_date) DO UPDATE SET
               close=excluded.close,turnover_rate=excluded.turnover_rate,turnover_rate_f=excluded.turnover_rate_f,
               volume_ratio=excluded.volume_ratio,pe=excluded.pe,pe_ttm=excluded.pe_ttm,pb=excluded.pb,
               ps=excluded.ps,ps_ttm=excluded.ps_ttm,dv_ratio=excluded.dv_ratio,total_mv=excluded.total_mv,
               circ_mv=excluded.circ_mv,total_share=excluded.total_share,float_share=excluded.float_share,
               free_share=excluded.free_share,updated_at=excluded.updated_at""",
            (ts_code, row.get("trade_date"), row.get("close"), row.get("turnover_rate"),
             row.get("turnover_rate_f"), row.get("volume_ratio"), row.get("pe"),
             row.get("pe_ttm"), row.get("pb"), row.get("ps"), row.get("ps_ttm"),
             row.get("dv_ratio"), row.get("total_mv"), row.get("circ_mv"),
             row.get("total_share"), row.get("float_share"), row.get("free_share"), now)
        )
    conn.commit()
    conn.close()


def write_daily_quotes(df: pd.DataFrame, ts_code: str):
    if df.empty:
        return
    now = TODAY.strftime("%Y-%m-%d")
    conn = get_db()
    for _, row in df.iterrows():
        conn.execute(
            """INSERT INTO daily_quotes(ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ts_code,trade_date) DO UPDATE SET
               open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
               pre_close=excluded.pre_close,change=excluded.change,pct_chg=excluded.pct_chg,
               vol=excluded.vol,amount=excluded.amount,updated_at=excluded.updated_at""",
            (ts_code, row.get("trade_date"), row.get("open"), row.get("high"), row.get("low"),
             row.get("close"), row.get("pre_close"), row.get("change"), row.get("pct_chg"),
             row.get("vol"), row.get("amount"), now)
        )
    conn.commit()
    conn.close()


def write_financial_df(df: pd.DataFrame, table: str, ts_code: str):
    if df.empty:
        return
    now = TODAY.strftime("%Y-%m-%d")
    conn = get_db()
    conn.execute(f"DELETE FROM {table} WHERE ts_code=?", (ts_code,))
    df = df.replace({np.nan: None})
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    available = [c for c in cols if c in df.columns]
    for _, row in df.iterrows():
        vals = [row.get(c) for c in available]
        placeholders = ",".join(["?"] * len(available))
        conn.execute(f"INSERT INTO {table}({','.join(available)},updated_at) VALUES({placeholders},?)",
                     vals + [now])
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 3. 数据新鲜度检查
# ---------------------------------------------------------------------------

def get_latest_trade_date(conn: sqlite3.Connection, ts_code: str) -> Optional[str]:
    row = conn.execute("SELECT MAX(trade_date) FROM daily_basic WHERE ts_code=?", (ts_code,)).fetchone()
    return row[0] if row and row[0] else None


def get_latest_financial_end_date(conn: sqlite3.Connection, ts_code: str) -> Optional[str]:
    row = conn.execute("SELECT MAX(end_date) FROM income WHERE ts_code=?", (ts_code,)).fetchone()
    return row[0] if row and row[0] else None


def is_stale(latest_date: Optional[str], max_days: int = 5) -> bool:
    if not latest_date:
        return True
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            d = datetime.strptime(latest_date, fmt)
            return (TODAY - d).days > max_days
        except ValueError:
            continue
    return True


# ---------------------------------------------------------------------------
# 4. 打分体系
# ---------------------------------------------------------------------------

class ScoreCard:
    def __init__(self):
        self.items: Dict[str, Tuple[float, str]] = {}

    def add(self, name: str, score: float, reason: str = ""):
        self.items[name] = (score, reason)

    def total(self) -> float:
        return sum(s for s, _ in self.items.values())

    def avg(self) -> float:
        return self.total() / len(self.items) if self.items else 0

    def to_markdown(self) -> str:
        lines = ["| 维度 | 得分 | 说明 |", "|------|------|------|"]
        for name, (score, reason) in self.items.items():
            lines.append(f"| {name} | {score:.1f} | {reason} |")
        return "\n".join(lines)


def score_financial_health(conn: sqlite3.Connection, ts_code: str) -> Tuple[float, str]:
    df_inc = pd.read_sql("SELECT * FROM income WHERE ts_code=? ORDER BY end_date DESC LIMIT 8", conn, params=(ts_code,))
    df_bal = pd.read_sql("SELECT * FROM balance WHERE ts_code=? ORDER BY end_date DESC LIMIT 8", conn, params=(ts_code,))
    df_cf = pd.read_sql("SELECT * FROM cashflow WHERE ts_code=? ORDER BY end_date DESC LIMIT 8", conn, params=(ts_code,))

    if df_inc.empty or df_bal.empty or df_cf.empty:
        return 0, "财务数据缺失，无法评估"

    score = 100
    reasons = []

    merged = pd.merge(df_inc[["end_date", "n_income_attr_p"]],
                      df_cf[["end_date", "n_cashflow_act"]], on="end_date")
    merged = merged.dropna()
    if len(merged) >= 2:
        low_ocf_years = (merged["n_cashflow_act"] / merged["n_income_attr_p"] < 0.8).sum()
        if low_ocf_years >= 2:
            score -= 40
            reasons.append(f"经营现金流/净利<0.8 持续 {low_ocf_years} 期")

    if len(df_inc) >= 2:
        df_inc = df_inc.sort_values("end_date")
        df_bal = df_bal.sort_values("end_date")
        rev_gr = safe_div(df_inc["total_revenue"].iloc[-1] - df_inc["total_revenue"].iloc[-2],
                          df_inc["total_revenue"].iloc[-2])
        ar_gr = safe_div(df_bal["accounts_receiv"].iloc[-1] - df_bal["accounts_receiv"].iloc[-2],
                         df_bal["accounts_receiv"].iloc[-2])
        if ar_gr > rev_gr + 0.3:
            score -= 25
            reasons.append("应收增速显著高于营收增速")

    latest_bal = df_bal.iloc[-1]
    interest_debt = (latest_bal.get("st_borr", 0) or 0) + (latest_bal.get("lt_borr", 0) or 0) + (latest_bal.get("bonds_payable", 0) or 0)
    money = latest_bal.get("money_cap", 0) or 0
    if interest_debt > money:
        score -= 20
        reasons.append("有息负债超过货币资金")

    equity = latest_bal.get("total_hldr_eqy_exc_min_int", 0) or 0
    goodwill = latest_bal.get("goodwill", 0) or 0
    if equity and goodwill / equity > 0.2:
        score -= 15
        reasons.append("商誉占净资产>20%")

    if df_cf["n_cashflow_act"].iloc[-1] < 0:
        score -= 20
        reasons.append("最近一期经营现金流为负")

    if score < 0:
        score = 0
    reason_text = "；".join(reasons) if reasons else "财务健康，无明显排雷信号"
    return score, reason_text


def score_graham(conn: sqlite3.Connection, ts_code: str) -> Tuple[float, str]:
    df_basic = pd.read_sql("SELECT * FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", conn, params=(ts_code,))
    df_inc = pd.read_sql("SELECT * FROM income WHERE ts_code=? AND end_date LIKE '%12-31' ORDER BY end_date DESC LIMIT 3", conn, params=(ts_code,))
    df_bal = pd.read_sql("SELECT * FROM balance WHERE ts_code=? AND end_date LIKE '%12-31' ORDER BY end_date DESC LIMIT 3", conn, params=(ts_code,))

    if df_basic.empty or df_inc.empty or df_bal.empty:
        return 0, "数据不足"

    close = df_basic["close"].iloc[0]
    eps_list = df_inc["n_income_attr_p"].dropna().tolist()
    avg_eps = sum(eps_list) / len(eps_list) if eps_list else 0
    shares = df_bal["total_share"].iloc[0] if "total_share" in df_bal and df_bal["total_share"].iloc[0] else 1e9
    latest_bps = df_bal["total_hldr_eqy_exc_min_int"].iloc[0] / shares

    graham_number = math.sqrt(22.5 * avg_eps * latest_bps) if avg_eps > 0 and latest_bps > 0 else 0
    pg = close / graham_number if graham_number > 0 else 99

    pe_ttm = df_basic["pe_ttm"].iloc[0]
    ey = 1 / pe_ttm if pe_ttm and pe_ttm > 0 else 0
    rf = CONFIG["scoring"]["risk_free_rate"]
    ey_spread = ey / rf if rf > 0 else 0

    score = 0
    reasons = []
    if pg <= 1.0:
        score += 50
        reasons.append(f"P/G={pg:.2f}，极具吸引力")
    elif pg <= 1.5:
        score += 35
        reasons.append(f"P/G={pg:.2f}，有吸引力")
    elif pg <= 2.0:
        score += 20
        reasons.append(f"P/G={pg:.2f}，偏贵")
    else:
        reasons.append(f"P/G={pg:.2f}，无安全边际")

    if ey_spread >= 2.5:
        score += 35
        reasons.append(f"EY/RF={ey_spread:.2f}x，极具吸引力")
    elif ey_spread >= 2.0:
        score += 25
        reasons.append(f"EY/RF={ey_spread:.2f}x，有吸引力")
    elif ey_spread >= 1.5:
        score += 15
        reasons.append(f"EY/RF={ey_spread:.2f}x，一般")

    if all(x > 0 for x in eps_list[-3:]):
        score += 15
        reasons.append("连续三年盈利")

    return min(score, 100), "；".join(reasons)


def score_fisher(conn: sqlite3.Connection, ts_code: str) -> Tuple[float, str]:
    df_inc = pd.read_sql("SELECT * FROM income WHERE ts_code=? AND end_date LIKE '%12-31' ORDER BY end_date DESC LIMIT 5", conn, params=(ts_code,))
    if len(df_inc) < 3:
        return 0, "年报数据不足 3 年"

    df_inc = df_inc.sort_values("end_date")
    rev = df_inc["total_revenue"].tolist()
    profit = df_inc["n_income_attr_p"].tolist()

    years = len(rev) - 1
    rev_cagr = cagr(rev[0], rev[-1], years)
    profit_cagr = cagr(profit[0], profit[-1], years)

    score = 0
    reasons = []
    if rev_cagr and rev_cagr >= 0.2:
        score += 35
        reasons.append(f"营收 CAGR {rev_cagr*100:.1f}%")
    elif rev_cagr and rev_cagr >= 0.1:
        score += 25
        reasons.append(f"营收 CAGR {rev_cagr*100:.1f}%")
    elif rev_cagr and rev_cagr >= 0.05:
        score += 15
        reasons.append(f"营收 CAGR {rev_cagr*100:.1f}%")

    if profit_cagr and profit_cagr >= 0.2:
        score += 35
        reasons.append(f"净利 CAGR {profit_cagr*100:.1f}%")
    elif profit_cagr and profit_cagr >= 0.1:
        score += 25
        reasons.append(f"净利 CAGR {profit_cagr*100:.1f}%")
    elif profit_cagr and profit_cagr >= 0.05:
        score += 15
        reasons.append(f"净利 CAGR {profit_cagr*100:.1f}%")

    if rev_cagr and profit_cagr and profit_cagr - rev_cagr < 0.2:
        score += 15
        reasons.append("增长质量较好")

    if rev[-1] > rev[-2]:
        score += 15
        reasons.append("最近年度营收正增长")

    return min(score, 100), "；".join(reasons)


def score_moat(conn: sqlite3.Connection, ts_code: str) -> Tuple[float, str]:
    df_fina = pd.read_sql("SELECT * FROM fina_indicators WHERE ts_code=? ORDER BY end_date DESC LIMIT 5", conn, params=(ts_code,))
    if df_fina.empty:
        return 0, "财务指标缺失"

    roe_list = df_fina["roe"].dropna().tolist()
    roic_list = df_fina["roic"].dropna().tolist()
    gm_list = df_fina["grossprofit_margin"].dropna().tolist()
    nm_list = df_fina["netprofit_margin"].dropna().tolist()

    score = 0
    reasons = []

    if roe_list:
        avg_roe = sum(roe_list) / len(roe_list)
        if avg_roe >= 15:
            score += 30
            reasons.append(f"3年均ROE {avg_roe:.1f}%")
        elif avg_roe >= 10:
            score += 20
            reasons.append(f"3年均ROE {avg_roe:.1f}%")
        elif avg_roe >= 5:
            score += 10

    if roic_list:
        avg_roic = sum(roic_list) / len(roic_list)
        if avg_roic >= 10:
            score += 25
            reasons.append(f"ROIC {avg_roic:.1f}% > WACC")
        elif avg_roic >= 6:
            score += 15

    if gm_list and sum(gm_list) / len(gm_list) >= 30:
        score += 20
        reasons.append("毛利率>30%")
    elif gm_list and sum(gm_list) / len(gm_list) >= 20:
        score += 10

    if nm_list and sum(nm_list) / len(nm_list) >= 10:
        score += 15
        reasons.append("净利率>10%")
    elif nm_list and sum(nm_list) / len(nm_list) >= 5:
        score += 8

    if len(roe_list) >= 3 and max(roe_list) - min(roe_list) < 10:
        score += 10
        reasons.append("ROE 波动小")

    return min(score, 100), "；".join(reasons)


def score_valuation(conn: sqlite3.Connection, ts_code: str) -> Tuple[float, str]:
    df_basic = pd.read_sql("SELECT * FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", conn, params=(ts_code,))
    if df_basic.empty:
        return 0, "估值数据缺失"

    row = df_basic.iloc[0]
    pe_ttm = row.get("pe_ttm")
    pb = row.get("pb")
    ps_ttm = row.get("ps_ttm")

    score = 0
    reasons = []

    if pe_ttm and pe_ttm > 0:
        if pe_ttm <= 15:
            score += 35
            reasons.append(f"PE(TTM)={pe_ttm:.1f}，低估")
        elif pe_ttm <= 25:
            score += 25
            reasons.append(f"PE(TTM)={pe_ttm:.1f}，合理")
        elif pe_ttm <= 40:
            score += 10
            reasons.append(f"PE(TTM)={pe_ttm:.1f}，偏贵")
        else:
            reasons.append(f"PE(TTM)={pe_ttm:.1f}，太贵")

    if pb and pb > 0:
        if pb <= 2:
            score += 25
            reasons.append(f"PB={pb:.1f}，低估")
        elif pb <= 4:
            score += 15
            reasons.append(f"PB={pb:.1f}，合理")
        elif pb <= 8:
            score += 5

    if ps_ttm and ps_ttm > 0:
        if ps_ttm <= 3:
            score += 20
            reasons.append(f"PS={ps_ttm:.1f}，合理")
        elif ps_ttm <= 6:
            score += 10

    df_cf = pd.read_sql("SELECT * FROM cashflow WHERE ts_code=? ORDER BY end_date DESC LIMIT 4", conn, params=(ts_code,))
    if not df_cf.empty:
        ocf = df_cf["n_cashflow_act"].sum()
        inv = abs(df_cf["n_cashflow_inv_act"].sum())
        fcf = ocf - inv
        if fcf > 0:
            score += 20
            reasons.append("TTM 自由现金流为正")

    return min(score, 100), "；".join(reasons)


def score_ten_bagger(conn: sqlite3.Connection, ts_code: str) -> Tuple[float, str]:
    df_basic = pd.read_sql("SELECT * FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", conn, params=(ts_code,))
    df_inc = pd.read_sql("SELECT * FROM income WHERE ts_code=? AND end_date LIKE '%12-31' ORDER BY end_date DESC LIMIT 5", conn, params=(ts_code,))
    df_fina = pd.read_sql("SELECT * FROM fina_indicators WHERE ts_code=? ORDER BY end_date DESC LIMIT 5", conn, params=(ts_code,))

    if df_basic.empty or df_inc.empty:
        return 0, "数据不足"

    score = 0
    reasons = []

    mv = (df_basic["total_mv"].iloc[0] or 0) / 10000
    if mv > 0 and mv < 100:
        score += 25
        reasons.append(f"市值 {mv:.1f} 亿，小而美")
    elif mv > 0 and mv < 300:
        score += 15
        reasons.append(f"市值 {mv:.1f} 亿，有空间")
    elif mv > 0:
        reasons.append(f"市值 {mv:.1f} 亿，偏大")

    df_inc = df_inc.sort_values("end_date")
    rev = df_inc["total_revenue"].tolist()
    profit = df_inc["n_income_attr_p"].tolist()
    years = len(rev) - 1
    rev_cagr = cagr(rev[0], rev[-1], years)
    profit_cagr = cagr(profit[0], profit[-1], years)

    if rev_cagr and rev_cagr >= 0.2:
        score += 20
        reasons.append(f"营收CAGR {rev_cagr*100:.1f}%")
    if profit_cagr and profit_cagr >= 0.2:
        score += 20
        reasons.append(f"净利CAGR {profit_cagr*100:.1f}%")

    if not df_fina.empty:
        roic_list = df_fina["roic"].dropna().tolist()
        if roic_list and sum(roic_list) / len(roic_list) >= 15:
            score += 20
            reasons.append("ROIC>15%")

    pe = df_basic["pe_ttm"].iloc[0]
    if pe and pe < 30:
        score += 15
        reasons.append(f"PE {pe:.1f}<30，估值合理")

    return min(score, 100), "；".join(reasons)


# ---------------------------------------------------------------------------
# 5. 报告生成
# ---------------------------------------------------------------------------

def build_report(ts_code: str, name: str, conn: sqlite3.Connection) -> str:
    today_str = TODAY.strftime("%Y-%m-%d")

    latest_trade = get_latest_trade_date(conn, ts_code)
    latest_fin = get_latest_financial_end_date(conn, ts_code)
    trade_stale = is_stale(latest_trade, max_days=5) if latest_trade else True
    fin_stale = is_stale(latest_fin, max_days=120) if latest_fin else True

    df_basic = pd.read_sql("SELECT * FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", conn, params=(ts_code,))
    basic_row = df_basic.iloc[0] if not df_basic.empty else {}
    close = basic_row.get("close", "N/A")
    pe_ttm = basic_row.get("pe_ttm", "N/A")
    pb = basic_row.get("pb", "N/A")
    total_mv = (basic_row.get("total_mv", 0) or 0) / 10000

    sc = ScoreCard()
    s1, r1 = score_financial_health(conn, ts_code)
    s2, r2 = score_graham(conn, ts_code)
    s3, r3 = score_fisher(conn, ts_code)
    s4, r4 = score_moat(conn, ts_code)
    s5, r5 = score_valuation(conn, ts_code)
    s6, r6 = score_ten_bagger(conn, ts_code)

    sc.add("财报排雷", s1, r1)
    sc.add("格雷厄姆价值", s2, r2)
    sc.add("费雪成长性", s3, r3)
    sc.add("护城河与盈利", s4, r4)
    sc.add("估值安全", s5, r5)
    sc.add("十倍股潜力", s6, r6)

    total_score = sc.total()
    avg_score = sc.avg()

    thresholds = CONFIG["scoring"]
    if s1 < thresholds["pass_financial_health"]:
        rating = "PASS"
        rating_reason = "财报排雷未通过，存在重大风险"
    elif avg_score >= thresholds["buy_avg_score"] and s1 >= thresholds["buy_min_health"]:
        rating = "BUY"
        rating_reason = "多维度评分优秀，具备安全边际与成长性"
    elif avg_score >= thresholds["observe_avg_score"]:
        rating = "OBSERVE"
        rating_reason = "部分维度达标，需进一步定性验证"
    else:
        rating = "TRACKING"
        rating_reason = "评分一般，长期跟踪等待更好价格或更明确基本面"

    wiki_refs = CONFIG["wiki_dependencies"]["methodology_pages"]
    wiki_ref_text = "\n".join([f"- {dep['purpose']}: `{dep['path']}`" for dep in wiki_refs])

    md = f"""# {name}（{ts_code}）综合报告

> **分析日期**：{today_str}  
> **数据新鲜度**：日线/估值最新 {latest_trade or 'N/A'} {"⚠️ 较旧" if trade_stale else "✅ 较新"}；财报最新 {latest_fin or 'N/A'} {"⚠️ 较旧" if fin_stale else "✅ 较新"}  
> **当前股价**：{close} 元 | **总市值**：{total_mv:.1f} 亿 | **PE(TTM)**：{pe_ttm} | **PB**：{pb}  
> **综合评分**：{total_score:.1f}/600（均值 {avg_score:.1f}/100）  
> **评级**：{rating} — {rating_reason}

---

## 0. 财报排雷

**得分**：{s1:.1f}/100

{r1}

## 1. 格雷厄姆过筛

**得分**：{s2:.1f}/100

{r2}

## 2. 费雪成长性

**得分**：{s3:.1f}/100

{r3}

## 3. 护城河评估

**得分**：{s4:.1f}/100

{r4}

## 4. 芒格防坑清单

- 财务数据是否可信：{'基本可信' if s1 >= 60 else '存疑，需人工复核'}
- 管理层资本配置：需结合历史分红/再融资/并购记录定性判断
- 行业是否被政策限制：需结合最新产业政策判断
- 是否存在单客户/大客户依赖：需阅读年报前五大客户
- 是否频繁跨界并购：需检查近年重大资产重组

## 5. 管理层定性

> 本部分需人工补充：管理层诚信记录、资本配置历史、股权结构、激励制度。

## 6. 估值综合

**得分**：{s5:.1f}/100

{r5}

## 7. 风险矩阵

| 风险类型 | 等级 | 说明 |
|----------|------|------|
| 财务造假/排雷 | {'高' if s1 < 60 else '中' if s1 < 80 else '低'} | {r1} |
| 估值过高 | {'高' if s5 < 40 else '中' if s5 < 60 else '低'} | {r5} |
| 成长性断裂 | {'高' if s3 < 40 else '中' if s3 < 60 else '低'} | {r3} |
| 护城河侵蚀 | {'高' if s4 < 40 else '中' if s4 < 60 else '低'} | {r4} |
| 数据陈旧 | {'高' if fin_stale else '低'} | 财报日期 {latest_fin or 'N/A'} |

## 8. 十倍成长股潜力

**得分**：{s6:.1f}/100

{r6}

> 十倍股是小概率事件，评分高只代表"具备部分条件"，不能作为买入依据。

## 9. 综合评分表

{sc.to_markdown()}

## 10. 行动建议

- **评级**：{rating}
- **建议**：{rating_reason}
- **后续跟踪**：关注下一季度财报、行业政策变化、估值变化
- **报告路径**：`reports/{today_str}/{name}_report_{today_str}.md`

## 11. 方法论依据

本报告基于 invest-wiki 的以下页面生成：

{wiki_ref_text}

> 若上述 wiki 页面发生结构性变更，本 skill 可能需要同步更新。详见 `config.yaml` 与 `Wiki-Skill 联动规范`。

---

*本报告由 invest-skill 公司分析 skill 自动生成，定量打分仅供参考，投资决策需结合定性研究与个人能力圈。*
"""
    return md


# ---------------------------------------------------------------------------
# 6. 主流程
# ---------------------------------------------------------------------------

def resolve_ts_code(ds, raw: str) -> Tuple[str, str]:
    ts_code = parse_ts_code(raw)
    if ts_code:
        conn = get_db()
        row = conn.execute("SELECT name FROM stocks WHERE ts_code=?", (ts_code,)).fetchone()
        conn.close()
        if row:
            return ts_code, row[0]
        df = ds.get_stock_basic(ts_code)
        write_stock_basic(df)
        if not df.empty:
            return ts_code, df.iloc[0]["name"]
        raise ValueError(f"无法找到代码: {raw}")

    conn = get_db()
    row = conn.execute("SELECT ts_code,name FROM stocks WHERE name=?", (raw,)).fetchone()
    conn.close()
    if row:
        return row[0], row[1]

    # 按名称远程查：AKShare 没有直接按名称查的接口，这里用 spot 全表过滤
    try:
        import akshare as ak
        spot = ak.stock_zh_a_spot_em()
        matched = spot[spot["名称"].str.contains(raw, na=False)]
        if not matched.empty:
            symbol = matched.iloc[0]["代码"]
            name = matched.iloc[0]["名称"]
            ts_code = f"{symbol}.SH" if symbol[0] in ("6", "5", "9") else f"{symbol}.SZ"
            df = ds.get_stock_basic(ts_code)
            write_stock_basic(df)
            return ts_code, name
    except Exception as e:
        print(f"[WARN] AKShare 名称匹配失败: {e}")

    raise ValueError(f"无法找到公司: {raw}")


def sync_company_data(ds, ts_code: str, force: bool = False):
    conn = get_db()
    today_str = TODAY.strftime("%Y%m%d")
    start_10y = (TODAY - timedelta(days=365 * 10)).strftime("%Y%m%d")

    latest_trade = get_latest_trade_date(conn, ts_code)
    if force or is_stale(latest_trade, max_days=5):
        start = start_10y if not latest_trade else latest_trade
        print(f"[SYNC] 更新日线/估值: {ts_code} 从 {start} 至 {today_str}")
        df_quote = ds.get_daily_quotes(ts_code, start, today_str)
        write_daily_quotes(df_quote, ts_code)
        df_basic = ds.get_daily_basic(ts_code, start, today_str)
        write_daily_basic(df_basic, ts_code)

    latest_fin = get_latest_financial_end_date(conn, ts_code)
    if force or is_stale(latest_fin, max_days=120):
        print(f"[SYNC] 更新财务报表: {ts_code}")
        df_inc = ds.get_income(ts_code, start_10y, today_str)
        write_financial_df(df_inc, "income", ts_code)
        df_bal = ds.get_balance(ts_code, start_10y, today_str)
        write_financial_df(df_bal, "balance", ts_code)
        df_cf = ds.get_cashflow(ts_code, start_10y, today_str)
        write_financial_df(df_cf, "cashflow", ts_code)
        df_fina = ds.get_fina_indicator(ts_code, start_10y, today_str)
        write_financial_df(df_fina, "fina_indicators", ts_code)
        df_audit = ds.get_fina_audit(ts_code, start_10y, today_str)
        write_financial_df(df_audit, "fina_audit", ts_code)

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="公司综合分析 skill")
    parser.add_argument("company", help="公司名称或代码，如 贵州茅台 或 600519.SH")
    parser.add_argument("--force-update", action="store_true", help="强制重新获取所有数据")
    parser.add_argument("--output-dir", type=str, default=str(REPORTS_DIR), help="报告输出目录")
    parser.add_argument("--skip-wiki-check", action="store_true", help="跳过 wiki 依赖校验")
    args = parser.parse_args()

    print(f"[INFO] 项目: {CONFIG['project']['name']} v{CONFIG['project']['version']}")
    print(f"[INFO] 分析日期: {TODAY.strftime('%Y-%m-%d')}")
    print(f"[INFO] 解析输入: {args.company}")

    ensure_schema()
    ds = create_data_source(CONFIG)
    print(f"[INFO] 数据源: {ds.name}")

    if not args.skip_wiki_check and CONFIG["coupling"]["validate_wiki_refs_before_run"]:
        drifts = validate_wiki_dependencies()
        save_drift_report(drifts)
        missing = [d for d in drifts if d["type"] == "missing"]
        if missing:
            print("[WARN] 检测到 wiki 依赖缺失：")
            for d in missing:
                print(f"  - {d['path']} ({d['purpose']})")
            if CONFIG["coupling"]["block_on_drift"]:
                print("[ERROR] 配置 block_on_drift=true，停止运行")
                sys.exit(1)
        else:
            print("[OK] wiki 依赖校验通过")

    ts_code, name = resolve_ts_code(ds, args.company)
    print(f"[INFO] 已定位: {name} ({ts_code})")

    sync_company_data(ds, ts_code, force=args.force_update)

    conn = get_db()
    md = build_report(ts_code, name, conn)
    conn.close()

    out_dir = Path(args.output_dir) / TODAY.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}_report_{TODAY.strftime('%Y-%m-%d')}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"[DONE] 报告已保存: {out_path}")


if __name__ == "__main__":
    main()
