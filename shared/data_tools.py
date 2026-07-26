#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取工具（瘦层）—— 仅负责取数和简单计算，不参与任何分析决策。

设计原则：
1. 所有分析决策由 LLM 根据 wiki 方法论做出
2. 本工具只提供原始数据 + 基础数学运算（CAGR、比率等）
3. 输出纯 JSON，便于 LLM 消费
4. 不包含评分、评级、报告生成等逻辑

用法：
  python3 shared/data_tools.py sync <ts_code>              # 同步数据
  python3 shared/data_tools.py sync-all-stocks             # 同步全部A股基础信息（用于行业对比）
  python3 shared/data_tools.py stock-info <ts_code>        # 公司信息
  python3 shared/data_tools.py market <ts_code>            # 行情估值
  python3 shared/data_tools.py annual <ts_code>            # 年度利润表
  python3 shared/data_tools.py quarterly <ts_code>         # 季度现金流
  python3 shared/data_tools.py balance <ts_code>           # 资产负债表
  python3 shared/data_tools.py indicators <ts_code>        # 财务指标
  python3 shared/data_tools.py industry <ts_code>          # 行业均值/中位数/分位
  python3 shared/data_tools.py forecast <ts_code>          # 业绩预告
  python3 shared/data_tools.py all <ts_code>               # 全部数据
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
import logging
logger = logging.getLogger(__name__)

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import sqlite3
import yaml

from shared.data_source import create_data_source

CONFIG_PATH = SKILL_ROOT / "config.yaml"
DB_PATH = SKILL_ROOT / "data" / "invest_skill.db"

try:
    from dotenv import load_dotenv
    env_path = SKILL_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()
# analysis_date 为可选的日期钉（历史回测用）；日常/cron 场景必须取系统当天，
# 否则 sync 的数据截止日期会永远停留在配置里那一天（实测 DB 行情因此停滞在 07-20）
_analysis_date = CONFIG["project"].get("analysis_date")
TODAY = datetime.strptime(_analysis_date, "%Y-%m-%d") if _analysis_date else datetime.now()


def get_db() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


# ── 数值安全处理 ──

def _f(v):
    if v is None: return None
    try: return float(v)
    except: return None

def _yi(v):
    """元 → 亿"""
    fv = _f(v)
    return None if fv is None else round(fv / 1e8, 2)

def _yi_w(v):
    """万元 → 亿"""
    fv = _f(v)
    return None if fv is None else round(fv / 10000, 2)

def _pct(a, b):
    fa, fb = _f(a), _f(b)
    return None if fa is None or fb is None or fb == 0 else round(fa / fb * 100, 2)

def _compute_cagr(start, end, years):
    if not start or not end or start <= 0 or end <= 0 or years <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 2)


# ── 子命令 ──

def cmd_sync(ts_code: str, force: bool = False) -> dict:
    ds = create_data_source(CONFIG)
    conn = get_db()
    today_str = TODAY.strftime("%Y%m%d")
    start_10y = (TODAY - timedelta(days=365 * 10)).strftime("%Y%m%d")

    row = conn.execute("SELECT MAX(trade_date) FROM daily_basic WHERE ts_code=?", (ts_code,)).fetchone()
    latest_trade = row[0] if row else None
    row = conn.execute("SELECT MAX(end_date) FROM income WHERE ts_code=?", (ts_code,)).fetchone()
    latest_fin = row[0] if row else None

    def stale(d, mx):
        if not d: return True
        try: return (TODAY - datetime.strptime(d, "%Y%m%d")).days > mx
        except: return True

    result = {"synced": [], "skipped": []}
    if force or stale(latest_trade, 5):
        start = start_10y if not latest_trade else latest_trade
        df_q = ds.get_daily_quotes(ts_code, start, today_str)
        df_b = ds.get_daily_basic(ts_code, start, today_str)
        # Write to DB
        _write_daily(conn, df_q, ts_code, "daily_quotes")
        _write_daily(conn, df_b, ts_code, "daily_basic")
        result["synced"].append("daily")
    else:
        result["skipped"].append("daily")

    if force or stale(latest_fin, 120):
        df_inc = ds.get_income(ts_code, start_10y, today_str)
        df_bal = ds.get_balance(ts_code, start_10y, today_str)
        df_cf = ds.get_cashflow(ts_code, start_10y, today_str)
        df_fina = ds.get_fina_indicator(ts_code, start_10y, today_str)
        _write_fin(conn, df_inc, "income", ts_code)
        _write_fin(conn, df_bal, "balance", ts_code)
        _write_fin(conn, df_cf, "cashflow", ts_code)
        _write_fin(conn, df_fina, "fina_indicators", ts_code)
        df_audit = ds.get_fina_audit(ts_code, start_10y, today_str)
        _write_fin(conn, df_audit, "fina_audit", ts_code)
        result["synced"].append("financials")
    else:
        result["skipped"].append("financials")

    # 业绩预告：每次都检查（可能比财报更新更频繁，且不随财报一起更新）
    # 注意：sync 中多次 API 调用可能触发频率限制，forecast 单独处理并加重试
    try:
        import time as _time
        _time.sleep(1.5)  # 避开 Tushare 频率限制
        # 预告公告日期可能晚于 analysis_date（盘后公告通常标次日日期），加 3 天缓冲
        fcst_end = (TODAY + timedelta(days=3)).strftime("%Y%m%d")
        df_fcst = ds.get_forecast(ts_code, (TODAY - timedelta(days=180)).strftime("%Y%m%d"), fcst_end)
        if not df_fcst.empty:
            _write_fin(conn, df_fcst, "forecast", ts_code)
            result["synced"].append("forecast")
        else:
            result["skipped"].append("forecast")
    except Exception as e:
        logger.warning(f"业绩预告同步失败（非致命）: {e}")
        result["skipped"].append("forecast")

    conn.close()
    return {"action": "sync", "ts_code": ts_code, **result}


def cmd_sync_all_stocks() -> dict:
    """同步全部 A 股基础信息到 stocks 表，用于行业对比。"""
    ds = create_data_source(CONFIG)
    conn = get_db()
    df = ds.get_all_stocks()
    if df.empty:
        conn.close()
        return {"action": "sync-all-stocks", "count": 0, "message": "未获取到股票列表"}

    df = df.rename(columns={
        "ts_code": "ts_code", "symbol": "symbol", "name": "name", "fullname": "fullname",
        "exchange": "exchange", "list_date": "list_date", "delist_date": "delist_date",
        "industry": "industry_sw", "area": "area"
    })
    for col in ["ts_code", "symbol", "name", "fullname", "exchange", "list_date", "delist_date", "industry_sw", "area"]:
        if col not in df.columns:
            df[col] = None
    df = df[[c for c in ["ts_code", "symbol", "name", "fullname", "exchange", "list_date", "delist_date", "industry_sw", "area"] if c in df.columns]]
    df = df.replace({np.nan: None})

    now = TODAY.strftime("%Y-%m-%d")
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(stocks)")
    cols = [r[1] for r in cur.fetchall()]
    conn.execute("DELETE FROM stocks")
    for _, row in df.iterrows():
        available = [c for c in cols if c in df.columns and c != "updated_at"]
        vals = [row.get(c) for c in available]
        ph = ",".join(["?"] * len(available))
        try:
            conn.execute(f"INSERT INTO stocks({','.join(available)},updated_at) VALUES({ph},?)", vals + [now])
        except Exception as e:
            logger.warning(f"写入 stocks 失败 {row.get('ts_code')}: {e}")
    conn.commit()
    conn.close()
    return {"action": "sync-all-stocks", "count": len(df), "message": "全部 A 股基础信息已同步"}


def _write_daily(conn, df, ts_code, table):
    if df.empty: return
    now = TODAY.strftime("%Y-%m-%d")
    df = df.replace({np.nan: None})
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    available = [c for c in cols if c in df.columns]
    for _, row in df.iterrows():
        vals = [row.get(c) for c in available]
        ph = ",".join(["?"] * len(available))
        try:
            conn.execute(f"INSERT OR REPLACE INTO {table}({','.join(available)},updated_at) VALUES({ph},?)", vals + [now])
        except Exception:
            pass
    conn.commit()


def _write_fin(conn, df, table, ts_code):
    if df.empty: return
    now = TODAY.strftime("%Y-%m-%d")
    conn.execute(f"DELETE FROM {table} WHERE ts_code=?", (ts_code,))
    df = df.replace({np.nan: None})
    if "end_date" in df.columns:
        dedup = ["end_date"]
        if "report_type" in df.columns: dedup.append("report_type")
        df = df.drop_duplicates(subset=dedup, keep="last")
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    available = [c for c in cols if c in df.columns]
    for _, row in df.iterrows():
        vals = [row.get(c) for c in available]
        ph = ",".join(["?"] * len(available))
        conn.execute(f"INSERT INTO {table}({','.join(available)},updated_at) VALUES({ph},?)", vals + [now])
    conn.commit()


def cmd_stock_info(ts_code: str) -> dict:
    conn = get_db()
    row = conn.execute("SELECT name, industry_sw, list_date, area FROM stocks WHERE ts_code=?", (ts_code,)).fetchone()
    conn.close()
    if not row: return {"error": f"未找到 {ts_code}"}
    return {"ts_code": ts_code, "name": row[0], "industry": row[1] or "N/A", "list_date": row[2] or "N/A", "area": row[3] or "N/A"}


def cmd_market(ts_code: str) -> dict:
    conn = get_db()
    df = pd.read_sql("SELECT close, pe_ttm, pb, ps_ttm, total_mv, total_share, turnover_rate, trade_date FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", conn, params=(ts_code,))
    conn.close()
    if df.empty: return {"error": "无行情数据"}
    r = df.iloc[0]
    return {
        "ts_code": ts_code, "trade_date": str(r["trade_date"]),
        "close": _f(r.get("close")), "pe_ttm": _f(r.get("pe_ttm")),
        "pb": _f(r.get("pb")), "ps_ttm": _f(r.get("ps_ttm")),
        "total_mv_yi": _yi_w(r.get("total_mv")),
        "total_shares_wan": _f(r.get("total_share")),
        "total_shares_yi": round(_f(r.get("total_share", 0)) / 10000, 2) if r.get("total_share") else None,
    }


def cmd_annual(ts_code: str) -> dict:
    conn = get_db()
    df = pd.read_sql("SELECT end_date, total_revenue, n_income_attr_p, total_cogs, rd_exp, sell_exp, operate_profit, non_oper_income FROM income WHERE ts_code=? AND end_date LIKE '%1231' ORDER BY end_date", conn, params=(ts_code,))
    conn.close()
    years_data = []
    for _, row in df.iterrows():
        yr = str(row["end_date"])[:4]
        rev = _f(row.get("total_revenue"))
        profit = _f(row.get("n_income_attr_p"))
        years_data.append({
            "year": yr,
            "revenue_yi": _yi(rev), "net_profit_yi": _yi(profit),
            "net_margin_pct": _pct(profit, rev),
            "rd_expense_yi": _yi(row.get("rd_exp")),
            "sell_expense_yi": _yi(row.get("sell_exp")),
            "operate_profit_yi": _yi(row.get("operate_profit")),
            "non_oper_income_yi": _yi(row.get("non_oper_income")),
            "non_recurring_pct": _pct(row.get("non_oper_income"), row.get("operate_profit")),
        })
    rev_vals = [d["revenue_yi"] for d in years_data if d["revenue_yi"]]
    profit_vals = [d["net_profit_yi"] for d in years_data if d["net_profit_yi"]]
    yrs = len(rev_vals) - 1
    return {
        "ts_code": ts_code, "annual_data": years_data, "count": len(years_data),
        "first_year": years_data[0]["year"] if years_data else None,
        "last_year": years_data[-1]["year"] if years_data else None,
        "revenue_cagr_full_pct": _compute_cagr(rev_vals[0], rev_vals[-1], yrs) if yrs > 0 and rev_vals[0] else None,
        "profit_cagr_full_pct": _compute_cagr(profit_vals[0], profit_vals[-1], yrs) if yrs > 0 and profit_vals[0] else None,
        "revenue_cagr_5y_pct": _compute_cagr(rev_vals[-6], rev_vals[-1], 5) if len(rev_vals) >= 6 and rev_vals[-6] else None,
        "profit_cagr_5y_pct": _compute_cagr(profit_vals[-6], profit_vals[-1], 5) if len(profit_vals) >= 6 and profit_vals[-6] else None,
    }


def cmd_quarterly(ts_code: str) -> dict:
    conn = get_db()
    df_inc = pd.read_sql("SELECT end_date, n_income_attr_p, total_revenue FROM income WHERE ts_code=? ORDER BY end_date DESC LIMIT 8", conn, params=(ts_code,))
    df_cf = pd.read_sql("SELECT end_date, n_cashflow_act, n_cashflow_inv_act FROM cashflow WHERE ts_code=? ORDER BY end_date DESC LIMIT 8", conn, params=(ts_code,))
    conn.close()
    merged = pd.merge(df_inc, df_cf, on="end_date", how="outer")
    periods = []
    for _, row in merged.iterrows():
        end_d = str(row["end_date"])
        p = _f(row.get("n_income_attr_p"))
        ocf = _f(row.get("n_cashflow_act"))
        inv = _f(row.get("n_cashflow_inv_act"))
        fcf = (ocf or 0) + (inv or 0)
        periods.append({
            "period": end_d, "is_q1": end_d.endswith("0331"), "is_annual": end_d.endswith("1231"),
            "revenue_yi": _yi(row.get("total_revenue")), "net_profit_yi": _yi(p),
            "ocf_yi": _yi(ocf), "fcf_yi": _yi(fcf), "ocf_ratio_pct": _pct(ocf, p),
        })
    ocf_ttm = sum(_f(r.get("n_cashflow_act", 0)) for _, r in df_cf.head(4).iterrows())
    inv_ttm = sum(abs(_f(r.get("n_cashflow_inv_act", 0))) for _, r in df_cf.head(4).iterrows())
    return {"ts_code": ts_code, "periods": periods, "fcf_ttm_yi": _yi(ocf_ttm - inv_ttm), "ocf_ttm_yi": _yi(ocf_ttm), "cap_ex_ttm_yi": _yi(inv_ttm)}


def cmd_balance(ts_code: str) -> dict:
    conn = get_db()
    df = pd.read_sql("SELECT end_date, total_assets, total_liab, total_hldr_eqy_exc_min_int, money_cap, st_borr, lt_borr, bonds_payable, goodwill, accounts_receiv, inventories FROM balance WHERE ts_code=? AND end_date LIKE '%1231' ORDER BY end_date DESC LIMIT 3", conn, params=(ts_code,))
    conn.close()
    if df.empty: return {"error": "无资产负债表数据"}
    history = []
    for _, row in df.iterrows():
        equity = _f(row.get("total_hldr_eqy_exc_min_int", 0))
        goodwill = _f(row.get("goodwill") or 0)
        money = _f(row.get("money_cap", 0))
        debt = (_f(row.get("st_borr", 0) or 0) + _f(row.get("lt_borr", 0) or 0) + _f(row.get("bonds_payable", 0) or 0))
        yr = str(row["end_date"])[:4]
        history.append({
            "year": yr,
            "total_assets_yi": _yi(row.get("total_assets")),
            "equity_yi": _yi(equity), "cash_yi": _yi(money),
            "interest_debt_yi": _yi(debt), "debt_gt_cash": (debt or 0) > (money or 0),
            "goodwill_yi": _yi(goodwill), "goodwill_ratio_pct": _pct(goodwill, equity),
            "accounts_receiv_yi": _yi(row.get("accounts_receiv")),
            "inventories_yi": _yi(row.get("inventories")),
            "asset_liability_ratio_pct": _pct(row.get("total_liab"), row.get("total_assets")),
        })
    # history 按 end_date DESC 排序，history[0] 为最新年报，展开为顶层字段（向后兼容）
    return {
        "ts_code": ts_code, "end_date": str(df.iloc[0]["end_date"]),
        **history[0],
        "balance_history": history,
    }


def cmd_indicators(ts_code: str) -> dict:
    conn = get_db()
    df = pd.read_sql("SELECT end_date, roe, grossprofit_margin, netprofit_margin, debt_to_assets, current_ratio FROM fina_indicators WHERE ts_code=? AND end_date LIKE '%1231' ORDER BY end_date DESC LIMIT 6", conn, params=(ts_code,))
    conn.close()
    indicators = []
    for _, row in df.iterrows():
        yr = str(row["end_date"])[:4]
        indicators.append({
            "year": yr,
            "roe_pct": _f(row.get("roe")), "gross_margin_pct": _f(row.get("grossprofit_margin")),
            "net_margin_pct": _f(row.get("netprofit_margin")), "debt_ratio_pct": _f(row.get("debt_to_assets")),
            "current_ratio": _f(row.get("current_ratio")),
        })
    return {"ts_code": ts_code, "indicators": indicators, "count": len(indicators)}


def cmd_fina_audit(ts_code: str) -> dict:
    """获取最新年报审计意见。"""
    conn = get_db()
    df = pd.read_sql(
        "SELECT ann_date, end_date, audit_result, audit_sign, audit_fees, audit_agency FROM fina_audit WHERE ts_code=? ORDER BY end_date DESC LIMIT 3",
        conn, params=(ts_code,))
    conn.close()
    if df.empty:
        return {"ts_code": ts_code, "has_audit": False, "message": "无审计意见数据"}
    audits = []
    for _, r in df.iterrows():
        audits.append({
            "ann_date": str(r["ann_date"]),
            "end_date": str(r["end_date"]),
            "audit_result": r.get("audit_result"),
            "audit_sign": r.get("audit_sign"),
            # audit_fees 单位为元（Tushare fina_audit），用元→亿换算
            "audit_fees_yi": _yi(r.get("audit_fees")),
            "audit_agency": r.get("audit_agency"),
        })
    return {"ts_code": ts_code, "has_audit": True, "latest": audits[0], "history": audits}


def cmd_forecast(ts_code: str) -> dict:
    """获取最近业绩预告（预增/预减/亏损等）"""
    conn = get_db()
    df = pd.read_sql("SELECT ann_date, end_date, type, net_profit_min, net_profit_max, last_parent_net, p_change_min, p_change_max, summary FROM forecast WHERE ts_code=? ORDER BY ann_date DESC LIMIT 3", conn, params=(ts_code,))
    conn.close()
    if df.empty:
        return {"ts_code": ts_code, "has_forecast": False, "message": "无业绩预告数据"}
    forecasts = []
    for _, r in df.iterrows():
        forecasts.append({
            "ann_date": str(r["ann_date"]) if r.get("ann_date") else None,
            "period_end": str(r["end_date"]) if r.get("end_date") else None,
            "type": r.get("type"),
            "net_profit_min_yi": _yi_w(r.get("net_profit_min")),
            "net_profit_max_yi": _yi_w(r.get("net_profit_max")),
            "last_period_profit_yi": _yi_w(r.get("last_parent_net")),
            "p_change_min_pct": _f(r.get("p_change_min")),
            "p_change_max_pct": _f(r.get("p_change_max")),
            "summary": r.get("summary", "")
        })
    return {"ts_code": ts_code, "has_forecast": True, "forecasts": forecasts}


def cmd_industry(ts_code: str) -> dict:
    """获取目标公司所在行业的横向对比数据（均值/中位数/分位）。"""
    conn = get_db()

    # 1. 目标公司行业
    row = conn.execute("SELECT name, industry_sw FROM stocks WHERE ts_code=?", (ts_code,)).fetchone()
    if not row:
        conn.close()
        return {"error": f"未找到 {ts_code}"}
    name, industry = row[0], row[1]
    if not industry:
        conn.close()
        return {"ts_code": ts_code, "name": name, "industry": "N/A", "message": "无行业分类数据"}

    # 2. 同行业所有公司（排除自身、ST、退市）
    peers = pd.read_sql(
        """SELECT ts_code, name FROM stocks
           WHERE industry_sw=? AND ts_code != ?
             AND (name NOT LIKE '%ST%' AND name NOT LIKE '%退%')
             AND (delist_date IS NULL OR delist_date = '')""",
        conn, params=(industry, ts_code)
    )
    peer_codes = peers["ts_code"].tolist()

    # 2.5 若本地缺失同行业公司财务数据，尝试自动同步（限制数量，避免 API 超限）
    synced_peers = []
    if peer_codes:
        ph = ",".join(["?"] * len(peer_codes))
        has_fina = pd.read_sql(
            f"SELECT DISTINCT ts_code FROM fina_indicators WHERE ts_code IN ({ph})",
            conn, params=peer_codes
        )["ts_code"].tolist()
        missing_peers = [c for c in peer_codes if c not in has_fina]
        if missing_peers:
            # 最多同步 30 家，避免触发频率/配额限制
            to_sync = missing_peers[:30]
            logger.info(f"行业对比：本地缺少 {len(missing_peers)} 家同行财务数据，将自动同步前 {len(to_sync)} 家")
            ds = create_data_source(CONFIG)
            today_str = TODAY.strftime("%Y%m%d")
            start_3y = (TODAY - timedelta(days=365 * 3)).strftime("%Y%m%d")
            for idx, peer_code in enumerate(to_sync):
                try:
                    df_inc = ds.get_income(peer_code, start_3y, today_str)
                    df_fina = ds.get_fina_indicator(peer_code, start_3y, today_str)
                    df_bal = ds.get_balance(peer_code, start_3y, today_str)
                    df_mk = ds.get_daily_basic(peer_code, start_3y, today_str)
                    _write_fin(conn, df_inc, "income", peer_code)
                    _write_fin(conn, df_fina, "fina_indicators", peer_code)
                    _write_fin(conn, df_bal, "balance", peer_code)
                    _write_daily(conn, df_mk, peer_code, "daily_basic")
                    synced_peers.append(peer_code)
                    if idx < len(to_sync) - 1:
                        time.sleep(0.6)  # 避开 Tushare 频率限制
                except Exception as e:
                    logger.warning(f"同步同行 {peer_code} 失败: {e}")

    if not peer_codes:
        conn.close()
        return {"ts_code": ts_code, "name": name, "industry": industry, "peer_count": 0, "message": "无同行业可比公司"}

    # 3. 最新年报财务指标（fina_indicators）
    ph = ",".join(["?"] * len(peer_codes))
    fina_sql = f"""SELECT ts_code, end_date, roe, grossprofit_margin, netprofit_margin, debt_to_assets
                   FROM fina_indicators
                   WHERE ts_code IN ({ph}) AND end_date LIKE '%1231'
                   ORDER BY ts_code, end_date DESC"""
    df_fina = pd.read_sql(fina_sql, conn, params=peer_codes)
    # 取每家公司最新一期
    df_fina = df_fina.drop_duplicates(subset=["ts_code"], keep="first")

    # 4. 最新年报利润表（计算销售费用率、研发费用率）
    inc_sql = f"""SELECT ts_code, end_date, total_revenue, sell_exp, rd_exp
                  FROM income
                  WHERE ts_code IN ({ph}) AND end_date LIKE '%1231'
                  ORDER BY ts_code, end_date DESC"""
    df_inc = pd.read_sql(inc_sql, conn, params=peer_codes)
    df_inc = df_inc.drop_duplicates(subset=["ts_code"], keep="first")

    # 5. 最新行情估值
    mk_sql = f"""SELECT ts_code, pe_ttm, pb, trade_date FROM daily_basic
                 WHERE ts_code IN ({ph})
                 ORDER BY ts_code, trade_date DESC"""
    df_mk = pd.read_sql(mk_sql, conn, params=peer_codes)
    df_mk = df_mk.drop_duplicates(subset=["ts_code"], keep="first")

    conn.close()

    # 6. 合并并计算衍生指标
    merged = df_fina.merge(df_inc, on="ts_code", how="outer").merge(df_mk, on="ts_code", how="outer")

    def _series_calc(df, col, fn):
        s = df[col].dropna().astype(float)
        s = s[s != 0] if col in ["pe_ttm"] else s
        return round(float(fn(s)), 4) if not s.empty else None

    def _percentile(s, target):
        s = s.dropna().astype(float)
        if s.empty or target is None:
            return None
        # 返回目标值在样本中的百分位（越低表示越小）
        return round((s <= target).mean() * 100, 2)

    metrics = {}
    # 财务指标
    for col, label in [
        ("roe", "roe_pct"),
        ("grossprofit_margin", "gross_margin_pct"),
        ("netprofit_margin", "net_margin_pct"),
        ("debt_to_assets", "debt_ratio_pct"),
    ]:
        s = merged[col].dropna().astype(float)
        if not s.empty:
            metrics[label] = {
                "count": int(len(s)),
                "mean": round(float(s.mean()), 2),
                "median": round(float(s.median()), 2),
                "p25": round(float(s.quantile(0.25)), 2),
                "p75": round(float(s.quantile(0.75)), 2),
            }

    # 销售费用率、研发费用率
    merged["sell_exp_rate"] = merged.apply(lambda r: _pct(r.get("sell_exp"), r.get("total_revenue")), axis=1)
    merged["rd_exp_rate"] = merged.apply(lambda r: _pct(r.get("rd_exp"), r.get("total_revenue")), axis=1)
    for col, label in [("sell_exp_rate", "sell_expense_rate_pct"), ("rd_exp_rate", "rd_expense_rate_pct")]:
        s = merged[col].dropna().astype(float)
        if not s.empty:
            metrics[label] = {
                "count": int(len(s)),
                "mean": round(float(s.mean()), 2),
                "median": round(float(s.median()), 2),
                "p25": round(float(s.quantile(0.25)), 2),
                "p75": round(float(s.quantile(0.75)), 2),
            }

    # 估值指标
    for col, label in [("pe_ttm", "pe_ttm"), ("pb", "pb")]:
        s = merged[col].dropna().astype(float)
        s = s[(s > 0) & (s < 500)]  # 剔除异常值
        if not s.empty:
            metrics[label] = {
                "count": int(len(s)),
                "mean": round(float(s.mean()), 2),
                "median": round(float(s.median()), 2),
                "p25": round(float(s.quantile(0.25)), 2),
                "p75": round(float(s.quantile(0.75)), 2),
            }

    # 7. 目标公司自身数据
    conn = get_db()
    target_fina = pd.read_sql(
        "SELECT roe, grossprofit_margin, netprofit_margin, debt_to_assets FROM fina_indicators WHERE ts_code=? AND end_date LIKE '%1231' ORDER BY end_date DESC LIMIT 1",
        conn, params=(ts_code,)
    )
    target_inc = pd.read_sql(
        "SELECT total_revenue, sell_exp, rd_exp FROM income WHERE ts_code=? AND end_date LIKE '%1231' ORDER BY end_date DESC LIMIT 1",
        conn, params=(ts_code,)
    )
    target_mk = pd.read_sql(
        "SELECT pe_ttm, pb FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
        conn, params=(ts_code,)
    )
    conn.close()

    target = {"ts_code": ts_code, "name": name, "industry": industry}
    if not target_fina.empty:
        r = target_fina.iloc[0]
        target.update({
            "roe_pct": _f(r.get("roe")),
            "gross_margin_pct": _f(r.get("grossprofit_margin")),
            "net_margin_pct": _f(r.get("netprofit_margin")),
            "debt_ratio_pct": _f(r.get("debt_to_assets")),
        })
    if not target_inc.empty:
        r = target_inc.iloc[0]
        target["sell_expense_rate_pct"] = _pct(r.get("sell_exp"), r.get("total_revenue"))
        target["rd_expense_rate_pct"] = _pct(r.get("rd_exp"), r.get("total_revenue"))
    if not target_mk.empty:
        r = target_mk.iloc[0]
        target["pe_ttm"] = _f(r.get("pe_ttm"))
        target["pb"] = _f(r.get("pb"))

    # 8. 计算目标公司在各指标上的行业百分位
    for metric_key, source_col in [
        ("roe_pct", "roe"),
        ("gross_margin_pct", "grossprofit_margin"),
        ("net_margin_pct", "netprofit_margin"),
        ("debt_ratio_pct", "debt_to_assets"),
        ("sell_expense_rate_pct", "sell_exp_rate"),
        ("rd_expense_rate_pct", "rd_exp_rate"),
        ("pe_ttm", "pe_ttm"),
        ("pb", "pb"),
    ]:
        if metric_key in target and metric_key in metrics:
            s = merged[source_col].dropna().astype(float)
            if metric_key in ["pe_ttm"]:
                s = s[(s > 0) & (s < 500)]
            target[f"{metric_key}_rank_pct"] = _percentile(s, target[metric_key])

    return {
        "ts_code": ts_code,
        "name": name,
        "industry": industry,
        "peer_count": len(peer_codes),
        "target": target,
        "industry_stats": metrics,
    }


def cmd_all(ts_code: str) -> dict:
    return {"stock_info": cmd_stock_info(ts_code), "market": cmd_market(ts_code),
            "annual": cmd_annual(ts_code), "quarterly": cmd_quarterly(ts_code),
            "balance": cmd_balance(ts_code), "indicators": cmd_indicators(ts_code),
            "audit": cmd_fina_audit(ts_code),
            "industry": cmd_industry(ts_code), "forecast": cmd_forecast(ts_code)}


def cmd_annual_report(ts_code: str, years: int = 5) -> dict:
    """
    抓取最近 N 年的年报/半年报/季报全文，解析后存入 annual_reports 表。
    返回结构化 dict，便于 LLM 消费。
    """
    ds = create_data_source(CONFIG)
    current_year = TODAY.year
    all_reports = {}
    stored_sections = 0
    conn = get_db()
    now = TODAY.strftime("%Y-%m-%d")

    for y in range(current_year - years + 1, current_year + 1):
        try:
            data = ds.get_annual_report_text(ts_code, str(y))
            if not data or not data.get("reports"):
                continue
            all_reports[str(y)] = data["reports"]
            # 写入数据库
            for report_type, report_data in data["reports"].items():
                # 删除旧数据
                conn.execute(
                    "DELETE FROM annual_reports WHERE ts_code=? AND report_year=? AND report_type=?",
                    (ts_code, str(y), report_type)
                )
                # 写入各章节
                for section_name, section_text in report_data.get("sections", {}).items():
                    conn.execute(
                        """INSERT INTO annual_reports
                           (ts_code, report_year, report_type, ann_date, title, section_name, section_text, source_url, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (ts_code, str(y), report_type,
                         report_data.get("ann_date", ""),
                         report_data.get("title", ""),
                         section_name,
                         section_text,
                         report_data.get("source_url", ""),
                         now)
                    )
                    stored_sections += 1
        except Exception as e:
            logger.warning(f"年报抓取失败 {ts_code} {y}: {e}")

    conn.commit()
    conn.close()

    # 返回摘要，避免全文过大
    summary = {}
    for year, reports in all_reports.items():
        summary[year] = {
            "report_types": list(reports.keys()),
            "section_names": {},
            "char_counts": {},
        }
        for rt, rd in reports.items():
            secs = list(rd.get("sections", {}).keys())
            summary[year]["section_names"][rt] = secs
            summary[year]["char_counts"][rt] = sum(len(v) for v in rd.get("sections", {}).values())

    return {
        "ts_code": ts_code,
        "years_requested": years,
        "years_fetched": list(all_reports.keys()),
        "stored_sections": stored_sections,
        "summary": summary,
    }


# ── 输出 ──

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        try:
            if pd.isna(obj): return None
        except: pass
        return super().default(obj)


def main():
    parser = argparse.ArgumentParser(description="数据获取工具（LLM 消费）")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ["sync", "stock-info", "market", "annual", "quarterly", "balance", "indicators", "industry", "forecast", "all", "annual-report"]:
        p = sub.add_parser(cmd)
        p.add_argument("ts_code", help="如 300408.SZ 或 603605.SH")
    # 不需要 ts_code 的子命令
    sub.add_parser("sync-all-stocks", help="同步全部 A 股基础信息到 stocks 表")

    args = parser.parse_args()

    if args.command == "sync-all-stocks":
        result = cmd_sync_all_stocks()
        print(json.dumps(result, ensure_ascii=False, indent=2, cls=NpEncoder))
        return

    ts_code = args.ts_code.upper()
    if "." not in ts_code and len(ts_code) == 6:
        ts_code = f"{ts_code}.SH" if ts_code[0] in "659" else f"{ts_code}.SZ"

    CMDS = {
        "sync": lambda: cmd_sync(ts_code), "stock-info": lambda: cmd_stock_info(ts_code),
        "market": lambda: cmd_market(ts_code), "annual": lambda: cmd_annual(ts_code),
        "quarterly": lambda: cmd_quarterly(ts_code), "balance": lambda: cmd_balance(ts_code),
        "indicators": lambda: cmd_indicators(ts_code), "industry": lambda: cmd_industry(ts_code),
        "forecast": lambda: cmd_forecast(ts_code), "all": lambda: cmd_all(ts_code),
        "annual-report": lambda: cmd_annual_report(ts_code, years=5),
    }
    result = CMDS[args.command]()
    print(json.dumps(result, ensure_ascii=False, indent=2, cls=NpEncoder))


if __name__ == "__main__":
    main()
