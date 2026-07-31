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
  python3 shared/data_tools.py macro                       # 宏观指标（GDP/PMI/CPI/PPI/M1-M2/SHIBOR）
  python3 shared/data_tools.py all <ts_code>               # 全部数据（含宏观）
"""

import argparse
import json
import math
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
from shared.contracts import normalize_ts_code

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


def _migrate_schema(conn: sqlite3.Connection) -> None:
    # 轻量向前迁移，兼容旧版 schema；复制可映射的历史审计字段。
    def ensure_column(table, column, declaration, copy_from=None):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            if copy_from and copy_from in cols:
                conn.execute(f"UPDATE {table} SET {column}={copy_from} WHERE {column} IS NULL")

    ensure_column("cashflow", "c_pay_acq_const_fiolta", "REAL")
    ensure_column("balance", "total_share", "REAL")
    ensure_column("fina_audit", "audit_result", "TEXT", "opinion_type")
    ensure_column("fina_audit", "audit_fees", "REAL", "audit_costs")
    ensure_column("fina_audit", "audit_agency", "TEXT")
    ensure_column("fina_audit", "audit_sign", "TEXT")
    conn.commit()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    _migrate_schema(conn)
    return conn


# ── 数值安全处理 ──

def _f(v):
    if v is None:
        return None
    try:
        value = float(v)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _sum_nullable(values):
    """只有全部分项可得时才求和，避免把未知错误表示为 0。"""
    parsed = [_f(v) for v in values]
    return None if any(v is None for v in parsed) else sum(parsed)


def _normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    """内部日期契约统一为 YYYYMMDD。"""
    df = df.copy()
    for col in ("trade_date", "ann_date", "f_ann_date", "end_date", "list_date", "delist_date"):
        if col in df.columns:
            df[col] = df[col].map(
                lambda value: "" if value is None or pd.isna(value)
                else str(value).replace("-", "").replace("/", "")[:8]
            )
    return df

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


def _series_cagr(points: list[tuple[int, Optional[float]]], horizon: Optional[int] = None):
    valid = [(year, _f(value)) for year, value in points if _f(value) is not None and _f(value) > 0]
    valid.sort(key=lambda item: item[0])
    if len(valid) < 2:
        return None
    end_year, end_value = valid[-1]
    if horizon is None:
        start_year, start_value = valid[0]
    else:
        target_year = end_year - horizon
        match = [(year, value) for year, value in valid if year == target_year]
        if not match:
            return None
        start_year, start_value = match[0]
    return _compute_cagr(start_value, end_value, end_year - start_year)


def _quarter_no(end_date: str) -> Optional[int]:
    suffix = str(end_date).replace("-", "")[-4:]
    return {"0331": 1, "0630": 2, "0930": 3, "1231": 4}.get(suffix)


def _standalone_quarters(df: pd.DataFrame, value_cols: list[str]) -> dict[str, dict]:
    """把累计报表还原成单季值；report_type=2 时直接使用单季口径。"""
    if df.empty:
        return {}
    work = _normalize_dates(df)
    work = work[work["end_date"].map(_quarter_no).notna()].copy()
    if work.empty:
        return {}
    if "report_type" not in work.columns:
        work["report_type"] = ""
    result = {}
    for year, yearly in work.groupby(work["end_date"].str[:4]):
        previous_ytd = {col: None for col in value_cols}
        previous_quarter = 0
        for end_date, same_period in yearly.sort_values("end_date").groupby("end_date", sort=True):
            end_date = str(end_date)
            quarter = _quarter_no(end_date)
            direct_rows = same_period[same_period.get("report_type", "").astype(str) == "2"]
            ytd_rows = same_period[same_period.get("report_type", "").astype(str) == "1"]
            if ytd_rows.empty and set(same_period["report_type"].astype(str)) <= {"", "None", "nan"}:
                ytd_rows = same_period
            direct_row = direct_rows.iloc[0] if not direct_rows.empty else None
            ytd_row = ytd_rows.iloc[0] if not ytd_rows.empty else None
            # 确定数据口径；无法确定时显式标记为 inferred，防止静默使用错误口径
            if direct_row is not None:
                stmt_kind = "single_quarter"
            elif ytd_row is not None and str(ytd_row.get("report_type", "")).strip() not in {"", "None", "nan"}:
                stmt_kind = "ytd"
            elif ytd_row is not None:
                stmt_kind = "inferred_ytd"
            else:
                stmt_kind = "unknown"
            entry = {
                "end_date": end_date,
                "quarter": quarter,
                "report_type": "2" if direct_row is not None else (
                    str(ytd_row.get("report_type", "")) if ytd_row is not None else ""),
                "source_statement_kind": stmt_kind,
            }
            for col in value_cols:
                direct_value = _f(direct_row.get(col)) if direct_row is not None else None
                ytd_value = _f(ytd_row.get(col)) if ytd_row is not None else None
                entry[f"{col}_ytd"] = ytd_value
                if direct_value is not None:
                    standalone = direct_value
                elif quarter == 1:
                    standalone = ytd_value
                elif previous_quarter == quarter - 1 and ytd_value is not None and previous_ytd[col] is not None:
                    standalone = ytd_value - previous_ytd[col]
                else:
                    standalone = None
                entry[col] = standalone
                if ytd_row is not None:
                    previous_ytd[col] = ytd_value
            if ytd_row is not None:
                previous_quarter = quarter
            result[end_date] = entry
    return result


def _ttm(periods: list[dict], field: str) -> Optional[float]:
    latest = periods[:4]
    if len(latest) < 4:
        return None
    quarter_ids = [int(p["period"][:4]) * 4 + int(p["quarter"]) for p in latest]
    if any(quarter_ids[i] - quarter_ids[i + 1] != 1 for i in range(3)):
        return None
    values = [_f(p.get(field)) for p in latest]
    return None if any(value is None for value in values) else sum(values)


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

    result = {"synced": [], "skipped": [], "rows_written": {}, "data_source": ds.name}
    try:
        # 超过 1 个自然日就重新查询到今天；周末/节假日源会返回同一最近交易日，
        # 工作日则不会继续沿用上周行情。
        if force or stale(latest_trade, 1):
            start = start_10y if force or not latest_trade else latest_trade
            df_q = ds.get_daily_quotes(ts_code, start, today_str)
            df_b = ds.get_daily_basic(ts_code, start, today_str)
            conn.execute("BEGIN")
            try:
                result["rows_written"]["daily_quotes"] = _write_daily(
                    conn, df_q, ts_code, "daily_quotes", manage_transaction=False)
                result["rows_written"]["daily_basic"] = _write_daily(
                    conn, df_b, ts_code, "daily_basic", manage_transaction=False)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            result["synced"].append("daily")
        else:
            result["skipped"].append("daily")

        if force or stale(latest_fin, 120):
            failures = {}
            fetched = {}
            for table, fetch_fn in [
                ("income", ds.get_income),
                ("balance", ds.get_balance),
                ("cashflow", ds.get_cashflow),
                ("fina_indicators", ds.get_fina_indicator),
                ("fina_audit", ds.get_fina_audit),
            ]:
                try:
                    df = fetch_fn(ts_code, start_10y, today_str)
                    if df is None or df.empty:
                        raise RuntimeError("数据源返回空表")
                    fetched[table] = df
                except Exception as exc:
                    failures[table] = str(exc)
            if failures:
                detail = "; ".join(f"{table}: {reason}" for table, reason in failures.items())
                raise RuntimeError(f"关键财务表同步不完整，拒绝继续: {detail}")
            conn.execute("BEGIN")
            try:
                for table, df in fetched.items():
                    result["rows_written"][table] = _write_fin(
                        conn, df, table, ts_code, manage_transaction=False)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            result["synced"].append("financials")
        else:
            result["skipped"].append("financials")

        # 业绩预告属于可选事件数据：失败需显式记录，但不冒充已同步。
        try:
            time.sleep(1.5)
            fcst_end = (TODAY + timedelta(days=3)).strftime("%Y%m%d")
            df_fcst = ds.get_forecast(ts_code, (TODAY - timedelta(days=180)).strftime("%Y%m%d"), fcst_end)
            if df_fcst is not None and not df_fcst.empty:
                result["rows_written"]["forecast"] = _write_fin(conn, df_fcst, "forecast", ts_code)
                result["synced"].append("forecast")
            else:
                result["skipped"].append("forecast:no-records")
        except Exception as exc:
            result.setdefault("warnings", []).append(f"业绩预告同步失败: {exc}")
            result["skipped"].append("forecast:error")
    finally:
        conn.close()
    output = {"action": "sync", "ts_code": ts_code, **result}
    if force:
        output["force"] = True
    return output


def cmd_sync_all_stocks() -> dict:
    """同步全部 A 股基础信息到 stocks 表，用于行业对比。"""
    ds = create_data_source(CONFIG)
    conn = get_db()
    df = ds.get_all_stocks()
    if df is None or df.empty:
        conn.close()
        raise RuntimeError("未获取到股票列表，保留原 stocks 表并终止")

    df = df.rename(columns={
        "ts_code": "ts_code", "symbol": "symbol", "name": "name", "fullname": "fullname",
        "exchange": "exchange", "list_date": "list_date", "delist_date": "delist_date",
        "industry": "industry_sw", "area": "area"
    })
    for col in ["ts_code", "symbol", "name", "fullname", "exchange", "list_date", "delist_date", "industry_sw", "area"]:
        if col not in df.columns:
            df[col] = None
    df = df[[c for c in ["ts_code", "symbol", "name", "fullname", "exchange", "list_date", "delist_date", "industry_sw", "area"] if c in df.columns]]
    df = _normalize_dates(df.replace({np.nan: None})).drop_duplicates(subset=["ts_code"], keep="last")

    now = TODAY.strftime("%Y-%m-%d")
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(stocks)")
    cols = [r[1] for r in cur.fetchall()]
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM stocks")
        available = [c for c in cols if c in df.columns and c != "updated_at"]
        inserted = 0
        for _, row in df.iterrows():
            vals = [row.get(c) for c in available]
            ph = ",".join(["?"] * len(available))
            conn.execute(f"INSERT INTO stocks({','.join(available)},updated_at) VALUES({ph},?)", vals + [now])
            inserted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"action": "sync-all-stocks", "count": inserted, "message": "全部 A 股基础信息已原子同步"}


def _write_daily(conn, df, ts_code, table, manage_transaction=True):
    if df is None or df.empty:
        raise RuntimeError(f"{table} 返回空数据")
    now = TODAY.strftime("%Y-%m-%d")
    df = _normalize_dates(df.replace({np.nan: None}))
    if "ts_code" not in df.columns:
        df["ts_code"] = ts_code
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    available = [c for c in cols if c in df.columns]
    if manage_transaction:
        conn.execute("BEGIN")
    try:
        inserted = 0
        for _, row in df.iterrows():
            vals = [row.get(c) for c in available]
            ph = ",".join(["?"] * len(available))
            conn.execute(f"INSERT OR REPLACE INTO {table}({','.join(available)},updated_at) VALUES({ph},?)", vals + [now])
            inserted += 1
        if manage_transaction:
            conn.commit()
    except Exception:
        if manage_transaction:
            conn.rollback()
        raise
    return inserted


def _write_fin(conn, df, table, ts_code, manage_transaction=True):
    if df is None or df.empty:
        raise RuntimeError(f"{table} 返回空数据")
    now = TODAY.strftime("%Y-%m-%d")
    df = _normalize_dates(df.replace({np.nan: None}))
    if "ts_code" not in df.columns:
        df["ts_code"] = ts_code
    if "end_date" in df.columns:
        dedup = ["end_date"]
        if "report_type" in df.columns: dedup.append("report_type")
        df = df.drop_duplicates(subset=dedup, keep="last")
    if manage_transaction:
        conn.execute("BEGIN")
    try:
        conn.execute(f"DELETE FROM {table} WHERE ts_code=?", (ts_code,))
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        available = [c for c in cols if c in df.columns]
        inserted = 0
        for _, row in df.iterrows():
            vals = [row.get(c) for c in available]
            ph = ",".join(["?"] * len(available))
            conn.execute(f"INSERT INTO {table}({','.join(available)},updated_at) VALUES({ph},?)", vals + [now])
            inserted += 1
        if manage_transaction:
            conn.commit()
    except Exception:
        if manage_transaction:
            conn.rollback()
        raise
    return inserted


def cmd_stock_info(ts_code: str) -> dict:
    conn = get_db()
    row = conn.execute("SELECT name, industry_sw, list_date, area FROM stocks WHERE ts_code=?", (ts_code,)).fetchone()
    conn.close()
    if not row: return {"error": f"未找到 {ts_code}"}
    return {"ts_code": ts_code, "name": row[0], "industry": row[1] or "N/A", "list_date": row[2] or "N/A", "area": row[3] or "N/A"}


def cmd_market(ts_code: str) -> dict:
    conn = get_db()
    as_of = TODAY.strftime("%Y%m%d")
    df = pd.read_sql(
        "SELECT close, pe_ttm, pb, ps_ttm, total_mv, total_share, turnover_rate, trade_date "
        "FROM daily_basic WHERE ts_code=? AND REPLACE(trade_date, '-', '')<=? "
        "ORDER BY trade_date DESC LIMIT 1",
        conn, params=(ts_code, as_of),
    )
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
    as_of = TODAY.strftime("%Y%m%d")
    df = pd.read_sql("""SELECT end_date, total_revenue, n_income_attr_p, total_cogs, rd_exp,
                             sell_exp, operate_profit, non_oper_income
                      FROM income
                      WHERE ts_code=? AND end_date LIKE '%1231'
                        AND (report_type='1' OR report_type='' OR report_type IS NULL)
                        AND REPLACE(COALESCE(NULLIF(ann_date,''), NULLIF(f_ann_date,'')), '-', '')<=?
                      ORDER BY end_date""", conn, params=(ts_code, as_of))
    conn.close()
    years_data = []
    revenue_points = []
    profit_points = []
    for _, row in df.iterrows():
        yr = str(row["end_date"])[:4]
        rev = _f(row.get("total_revenue"))
        profit = _f(row.get("n_income_attr_p"))
        revenue_points.append((int(yr), rev))
        profit_points.append((int(yr), profit))
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
    return {
        "ts_code": ts_code, "annual_data": years_data, "count": len(years_data),
        "first_year": years_data[0]["year"] if years_data else None,
        "last_year": years_data[-1]["year"] if years_data else None,
        "revenue_cagr_full_pct": _series_cagr(revenue_points),
        "profit_cagr_full_pct": _series_cagr(profit_points),
        "revenue_cagr_5y_pct": _series_cagr(revenue_points, 5),
        "profit_cagr_5y_pct": _series_cagr(profit_points, 5),
    }


def cmd_quarterly(ts_code: str) -> dict:
    conn = get_db()
    as_of = TODAY.strftime("%Y%m%d")
    df_inc = pd.read_sql(
        """SELECT end_date, report_type, n_income_attr_p, total_revenue
           FROM income WHERE ts_code=?
             AND REPLACE(COALESCE(NULLIF(ann_date,''), NULLIF(f_ann_date,'')), '-', '')<=?
           ORDER BY end_date DESC LIMIT 24""",
        conn, params=(ts_code, as_of))
    df_cf = pd.read_sql(
        """SELECT end_date, report_type, n_cashflow_act, n_cashflow_inv_act,
                  c_pay_acq_const_fiolta
           FROM cashflow WHERE ts_code=?
             AND REPLACE(COALESCE(NULLIF(ann_date,''), NULLIF(f_ann_date,'')), '-', '')<=?
           ORDER BY end_date DESC LIMIT 24""",
        conn, params=(ts_code, as_of))
    conn.close()

    income = _standalone_quarters(df_inc, ["total_revenue", "n_income_attr_p"])
    cashflow = _standalone_quarters(
        df_cf, ["n_cashflow_act", "n_cashflow_inv_act", "c_pay_acq_const_fiolta"])
    periods = []
    raw_periods = []
    for end_d in sorted(set(income) | set(cashflow), reverse=True)[:8]:
        inc = income.get(end_d, {})
        cf = cashflow.get(end_d, {})
        profit = _f(inc.get("n_income_attr_p"))
        ocf = _f(cf.get("n_cashflow_act"))
        capex = _f(cf.get("c_pay_acq_const_fiolta"))
        fcf = None if ocf is None or capex is None else ocf - capex
        ocf_ytd = _f(cf.get("n_cashflow_act_ytd"))
        capex_ytd = _f(cf.get("c_pay_acq_const_fiolta_ytd"))
        fcf_ytd = None if ocf_ytd is None or capex_ytd is None else ocf_ytd - capex_ytd
        raw_periods.append({
            "period": end_d, "quarter": _quarter_no(end_d),
            "ocf": ocf, "capex": capex, "fcf": fcf,
        })
        periods.append({
            "period": end_d,
            "quarter": _quarter_no(end_d),
            "period_kind": "standalone_quarter",
            "source_statement_kind": {
                "income": inc.get("source_statement_kind"),
                "cashflow": cf.get("source_statement_kind"),
            },
            "is_q1": end_d.endswith("0331"),
            "is_annual": end_d.endswith("1231"),
            "revenue_ytd_yi": _yi(inc.get("total_revenue_ytd")),
            "net_profit_ytd_yi": _yi(inc.get("n_income_attr_p_ytd")),
            "ocf_ytd_yi": _yi(ocf_ytd),
            "capex_ytd_yi": _yi(capex_ytd),
            "fcf_ytd_yi": _yi(fcf_ytd),
            # 向后兼容字段现在明确为单季值。
            "revenue_yi": _yi(inc.get("total_revenue")),
            "net_profit_yi": _yi(profit),
            "ocf_yi": _yi(ocf),
            "investing_cashflow_yi": _yi(cf.get("n_cashflow_inv_act")),
            "capex_yi": _yi(capex),
            "fcf_yi": _yi(fcf),
            "ocf_ratio_pct": _pct(ocf, profit),
        })
    has_inferred = any(
        p.get("source_statement_kind", {}).get("income") == "inferred_ytd"
        or p.get("source_statement_kind", {}).get("cashflow") == "inferred_ytd"
        for p in periods
    )
    ocf_ttm = _ttm(raw_periods, "ocf") if not has_inferred else None
    capex_ttm = _ttm(raw_periods, "capex") if not has_inferred else None
    fcf_ttm = _ttm(raw_periods, "fcf") if not has_inferred else None
    return {
        "ts_code": ts_code,
        "periods": periods,
        "period_count": len(periods),
        "ocf_ttm_complete": ocf_ttm is not None,
        "ttm_complete": (
            not has_inferred
            and all(value is not None for value in (ocf_ttm, capex_ttm, fcf_ttm))
        ),
        "fcf_formula": "经营活动现金流净额 - 购建固定资产、无形资产和其他长期资产支付的现金",
        "fcf_ttm_yi": _yi(fcf_ttm),
        "ocf_ttm_yi": _yi(ocf_ttm),
        "cap_ex_ttm_yi": _yi(capex_ttm),
    }


def cmd_balance(ts_code: str) -> dict:
    conn = get_db()
    as_of = TODAY.strftime("%Y%m%d")
    df = pd.read_sql("SELECT end_date, total_assets, total_liab, total_hldr_eqy_exc_min_int, money_cap, st_borr, lt_borr, bonds_payable, goodwill, accounts_receiv, inventories FROM balance WHERE ts_code=? AND end_date LIKE '%1231' AND REPLACE(COALESCE(NULLIF(ann_date,''), NULLIF(f_ann_date,'')), '-', '')<=? ORDER BY end_date DESC LIMIT 3", conn, params=(ts_code, as_of))
    conn.close()
    if df.empty: return {"error": "无资产负债表数据"}
    history = []
    for _, row in df.iterrows():
        equity = _f(row.get("total_hldr_eqy_exc_min_int"))
        goodwill = _f(row.get("goodwill"))
        money = _f(row.get("money_cap"))
        debt = _sum_nullable([row.get("st_borr"), row.get("lt_borr"), row.get("bonds_payable")])
        yr = str(row["end_date"])[:4]
        history.append({
            "year": yr,
            "total_assets_yi": _yi(row.get("total_assets")),
            "equity_yi": _yi(equity), "cash_yi": _yi(money),
            "interest_debt_yi": _yi(debt),
            "debt_gt_cash": None if debt is None or money is None else debt > money,
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
    as_of = TODAY.strftime("%Y%m%d")
    df = pd.read_sql("SELECT end_date, roe, grossprofit_margin, netprofit_margin, debt_to_assets, current_ratio FROM fina_indicators WHERE ts_code=? AND end_date LIKE '%1231' AND REPLACE(NULLIF(ann_date,''), '-', '')<=? ORDER BY end_date DESC LIMIT 6", conn, params=(ts_code, as_of))
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
    as_of = TODAY.strftime("%Y%m%d")
    df = pd.read_sql(
        "SELECT ann_date, end_date, audit_result, audit_sign, audit_fees, audit_agency "
        "FROM fina_audit WHERE ts_code=? "
        "AND REPLACE(NULLIF(ann_date,''), '-', '')<=? "
        "ORDER BY end_date DESC LIMIT 3",
        conn, params=(ts_code, as_of))
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
    as_of = TODAY.strftime("%Y%m%d")
    df = pd.read_sql("SELECT ann_date, end_date, type, net_profit_min, net_profit_max, last_parent_net, p_change_min, p_change_max, summary FROM forecast WHERE ts_code=? AND REPLACE(ann_date, '-', '')<=? ORDER BY ann_date DESC LIMIT 3", conn, params=(ts_code, as_of))
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
    as_of = TODAY.strftime("%Y%m%d")
    fiscal_year = TODAY.year - 1 if TODAY.month >= 5 else TODAY.year - 2
    fiscal_end = f"{fiscal_year}1231"

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

    # 查询命令必须保持只读。同行缺数据时返回较小样本并显式标注，禁止在 all/industry
    # 中隐式联网写库导致同一批次结果漂移；需要扩充样本时先显式 sync 对应公司。

    if not peer_codes:
        conn.close()
        return {"ts_code": ts_code, "name": name, "industry": industry, "peer_count": 0, "message": "无同行业可比公司"}

    # 3. 同一预期财年财务指标。禁止把不同公司的“各自最新一期”混在一起。
    ph = ",".join(["?"] * len(peer_codes))
    fina_sql = f"""SELECT ts_code, end_date, roe, grossprofit_margin, netprofit_margin, debt_to_assets
                   FROM fina_indicators
                   WHERE ts_code IN ({ph}) AND REPLACE(end_date, '-', '')=?
                     AND REPLACE(NULLIF(ann_date,''), '-', '')<=?
                   ORDER BY ts_code, end_date DESC"""
    df_fina = pd.read_sql(fina_sql, conn, params=[*peer_codes, fiscal_end, as_of])
    # 取每家公司最新一期
    df_fina = df_fina.drop_duplicates(subset=["ts_code"], keep="first")

    # 4. 最新年报利润表（计算销售费用率、研发费用率）
    inc_sql = f"""SELECT ts_code, end_date, total_revenue, sell_exp, rd_exp
                  FROM income
                  WHERE ts_code IN ({ph}) AND REPLACE(end_date, '-', '')=?
                    AND REPLACE(COALESCE(NULLIF(ann_date,''), NULLIF(f_ann_date,'')), '-', '')<=?
                  ORDER BY ts_code, end_date DESC"""
    df_inc = pd.read_sql(inc_sql, conn, params=[*peer_codes, fiscal_end, as_of])
    df_inc = df_inc.drop_duplicates(subset=["ts_code"], keep="first")

    # 5. 行情估值必须与目标公司同一交易日；停牌或缓存陈旧的同行自动剔除。
    target_market_row = conn.execute(
        "SELECT trade_date FROM daily_basic WHERE ts_code=? "
        "AND REPLACE(trade_date, '-', '')<=? ORDER BY trade_date DESC LIMIT 1",
        (ts_code, as_of),
    ).fetchone()
    target_market_date = str(target_market_row[0]).replace("-", "") if target_market_row else ""
    mk_sql = f"""SELECT ts_code, pe_ttm, pb, trade_date FROM daily_basic
                 WHERE ts_code IN ({ph}) AND REPLACE(trade_date, '-', '')=?
                 ORDER BY ts_code, trade_date DESC"""
    df_mk = pd.read_sql(mk_sql, conn, params=[*peer_codes, target_market_date])
    df_mk = df_mk.drop_duplicates(subset=["ts_code"], keep="first")

    conn.close()

    # 6. 合并并计算衍生指标
    merged = df_fina.merge(df_inc, on="ts_code", how="outer").merge(df_mk, on="ts_code", how="outer")

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
        "SELECT roe, grossprofit_margin, netprofit_margin, debt_to_assets FROM fina_indicators WHERE ts_code=? AND REPLACE(end_date, '-', '')=? AND REPLACE(NULLIF(ann_date,''), '-', '')<=? ORDER BY end_date DESC LIMIT 1",
        conn, params=(ts_code, fiscal_end, as_of)
    )
    target_inc = pd.read_sql(
        "SELECT total_revenue, sell_exp, rd_exp FROM income WHERE ts_code=? AND REPLACE(end_date, '-', '')=? AND REPLACE(COALESCE(NULLIF(ann_date,''), NULLIF(f_ann_date,'')), '-', '')<=? ORDER BY end_date DESC LIMIT 1",
        conn, params=(ts_code, fiscal_end, as_of)
    )
    target_mk = pd.read_sql(
        "SELECT pe_ttm, pb FROM daily_basic WHERE ts_code=? AND REPLACE(trade_date, '-', '')=? LIMIT 1",
        conn, params=(ts_code, target_market_date)
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
        "comparison_fiscal_year": fiscal_year,
        "comparison_trade_date": target_market_date or None,
        "financial_peer_rows": int(merged[["roe", "grossprofit_margin", "netprofit_margin", "debt_to_assets"]].notna().any(axis=1).sum()),
        "market_peer_rows": int(merged[["pe_ttm", "pb"]].notna().any(axis=1).sum()),
        "target": target,
        "industry_stats": metrics,
    }


def cmd_macro() -> dict:
    """获取当前宏观关键指标，供宏观周期师使用。
    返回 GDP/PMI/CPI/PPI/M1-M2/SHIBOR 数据，每个指标独立容错。"""
    if _analysis_date:
        return {
            "source": "unavailable_for_historical_asof",
            "update_date": TODAY.strftime("%Y%m%d"),
            "indicators": {},
            "errors": ["历史日期钉下禁止注入当前宏观数据；本地无可审计的历史宏观快照"],
        }
    ds = create_data_source(CONFIG)
    return ds.get_macro_data()


def validate_snapshot(data: dict, reference_date: Optional[datetime] = None) -> dict:
    """对供专家使用的数据快照执行结构与口径门禁。"""
    errors = []
    warnings = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    as_of = reference_date or TODAY
    stock = data.get("stock_info", {})
    market = data.get("market", {})
    annual = data.get("annual", {})
    quarterly = data.get("quarterly", {})
    balance = data.get("balance", {})
    indicators = data.get("indicators", {})
    audit = data.get("audit", {})

    require(not stock.get("error") and stock.get("name"), "stock_info 缺少公司名称")
    expected_code = stock.get("ts_code")
    try:
        expected_code = normalize_ts_code(expected_code)
    except (TypeError, ValueError):
        errors.append(f"stock_info.ts_code 非法: {expected_code!r}")
        expected_code = None
    for section in ("market", "annual", "quarterly", "balance", "indicators", "audit", "industry", "forecast"):
        section_code = data.get(section, {}).get("ts_code")
        require(
            expected_code is not None and section_code == expected_code,
            f"{section}.ts_code 与 stock_info 不一致: {section_code!r} != {expected_code!r}",
        )
    require(not market.get("error") and market.get("trade_date"), "market 缺少交易日期")
    require(_f(market.get("close")) is not None, "market.close 缺失")
    require(_f(market.get("total_mv_yi")) is not None, "market.total_mv_yi 缺失或单位未统一")
    if market.get("trade_date"):
        try:
            trade_day = datetime.strptime(str(market["trade_date"]).replace("-", ""), "%Y%m%d")
            age = (as_of.date() - trade_day.date()).days
            require(0 <= age <= 7, f"market.trade_date 陈旧或位于未来（相差 {age} 天）")
        except ValueError:
            errors.append(f"market.trade_date 格式非法: {market.get('trade_date')}")
    require(annual.get("count", 0) >= 1, "annual 无年度利润表")
    annual_rows = annual.get("annual_data", [])
    require(annual.get("count") == len(annual_rows), "annual.count 与 annual_data 长度不一致")
    annual_years = [str(item.get("year") or "") for item in annual_rows]
    require(len(annual_years) == len(set(annual_years)), "annual_data 年份重复")
    require(annual_years == sorted(annual_years), "annual_data 年份未按升序排列")
    expected_fiscal_year = as_of.year - 1 if as_of.month >= 5 else as_of.year - 2
    if annual_years:
        require(annual.get("last_year") in (None, annual_years[-1]),
                "annual.last_year 与 annual_data 不一致")
        require(
            annual_years[-1] == str(expected_fiscal_year),
            f"annual 最新年度陈旧: {annual_years[-1]} != {expected_fiscal_year}",
        )
        latest_annual = annual_rows[-1]
        require(_f(latest_annual.get("revenue_yi")) is not None,
                "annual 最新年度营收缺失")
        require(_f(latest_annual.get("net_profit_yi")) is not None,
                "annual 最新年度净利润缺失")
    if len(annual_rows) >= 2 and all(year.isdigit() for year in annual_years):
        for prefix, field in (("revenue", "revenue_yi"), ("profit", "net_profit_yi")):
            points = [(int(item["year"]), item.get(field)) for item in annual_rows]
            for output_field, horizon in (
                (f"{prefix}_cagr_full_pct", None), (f"{prefix}_cagr_5y_pct", 5)
            ):
                expected = _series_cagr(points, horizon)
                declared = _f(annual.get(output_field))
                require(
                    (expected is None and declared is None)
                    or (expected is not None and declared is not None and abs(expected - declared) <= 0.15),
                    f"annual.{output_field} 与年度序列重算不一致",
                )
    if 0 < annual.get("count", 0) < 3:
        warnings.append("annual 少于 3 个年度，成长趋势置信度应降级")

    periods = quarterly.get("periods", [])
    require(len(periods) >= 4, "quarterly 少于 4 个单季")
    if len(periods) >= 4:
        quarter_ids = []
        for period in periods[:4]:
            period_text = str(period.get("period") or "")
            quarter = period.get("quarter")
            try:
                quarter_ids.append(int(period_text[:4]) * 4 + int(quarter))
                require(_quarter_no(period_text) == int(quarter),
                        f"quarterly {period_text} quarter 编号与日期不一致")
            except (TypeError, ValueError):
                quarter_ids.append(None)
        contiguous = (
            len(set(quarter_ids)) == 4 and None not in quarter_ids
            and all(quarter_ids[index] - quarter_ids[index + 1] == 1 for index in range(3))
        )
        require(contiguous, "quarterly 最近四季存在重复、乱序或断裂")
        try:
            latest_quarter_end = datetime.strptime(str(periods[0].get("period")), "%Y%m%d")
            quarter_age = (as_of.date() - latest_quarter_end.date()).days
            require(0 <= quarter_age <= 200,
                    f"quarterly 最新报告期陈旧或位于未来（相差 {quarter_age} 天）")
        except ValueError:
            errors.append(f"quarterly 最新 period 格式非法: {periods[0].get('period')!r}")
        for field in ("revenue_yi", "net_profit_yi", "ocf_yi"):
            require(all(_f(period.get(field)) is not None for period in periods[:4]),
                    f"quarterly 最近四季 {field} 不完整")
        expected_ocf_complete = contiguous and all(
            _f(period.get("ocf_yi")) is not None for period in periods[:4]
        )
        require(
            quarterly.get("ocf_ttm_complete") is expected_ocf_complete,
            "quarterly.ocf_ttm_complete 与最近四季明细不一致",
        )
        require(expected_ocf_complete, "quarterly 最近四季不连续或 OCF TTM 不完整")
        if expected_ocf_complete:
            expected_ocf_ttm = round(sum(_f(period.get("ocf_yi")) for period in periods[:4]), 2)
            require(
                _f(quarterly.get("ocf_ttm_yi")) is not None
                and abs(_f(quarterly.get("ocf_ttm_yi")) - expected_ocf_ttm) <= 0.05,
                "quarterly.ocf_ttm_yi 与最近四个单季不一致",
            )
        for period in periods[:4]:
            ocf, capex, fcf = (_f(period.get(key)) for key in ("ocf_yi", "capex_yi", "fcf_yi"))
            if ocf is not None and capex is not None:
                require(
                    fcf is not None and abs((ocf - capex) - fcf) <= 0.03,
                    f"quarterly {period.get('period')} FCF 不等于 OCF-资本开支",
                )
        if all(_f(period.get("capex_yi")) is not None for period in periods[:4]):
            expected_capex_ttm = round(sum(_f(period.get("capex_yi")) for period in periods[:4]), 2)
            expected_fcf_ttm = round(sum(_f(period.get("fcf_yi")) for period in periods[:4]), 2)
            require(
                _f(quarterly.get("cap_ex_ttm_yi")) is not None
                and abs(_f(quarterly.get("cap_ex_ttm_yi")) - expected_capex_ttm) <= 0.05,
                "quarterly.cap_ex_ttm_yi 与最近四个单季不一致",
            )
            require(
                _f(quarterly.get("fcf_ttm_yi")) is not None
                and abs(_f(quarterly.get("fcf_ttm_yi")) - expected_fcf_ttm) <= 0.05,
                "quarterly.fcf_ttm_yi 与最近四个单季不一致",
            )
        if not all(_f(period.get("capex_yi")) is not None for period in periods[:4]):
            warnings.append("quarterly 最近四季资本开支缺失，FCF/FCF TTM 必须标注不可得")
        elif not quarterly.get("ttm_complete"):
            warnings.append("quarterly FCF TTM 不完整，禁止使用 TTM FCF")
    inferred_periods = [
        p.get("period") for p in periods
        if p.get("source_statement_kind", {}).get("income") == "inferred_ytd"
        or p.get("source_statement_kind", {}).get("cashflow") == "inferred_ytd"
    ]
    if inferred_periods:
        warnings.append(
            f"quarterly 以下报告期数据口径未确认（inferred_ytd）: {inferred_periods}；"
            "单季值基于'视为累计'的不可靠假设还原，TTM 和 FCF 一律禁用"
        )

    require(not balance.get("error") and balance.get("end_date"), "balance 缺少最新年报")
    balance_year = str(balance.get("end_date") or "")[:4]
    if balance.get("end_date"):
        require(balance_year == str(expected_fiscal_year),
                f"balance 最新年度陈旧: {balance_year} != {expected_fiscal_year}")
    require(_f(balance.get("total_assets_yi")) is not None, "balance.total_assets_yi 缺失")
    require(_f(balance.get("equity_yi")) is not None, "balance.equity_yi 缺失")
    if balance.get("cash_yi") is None:
        warnings.append("balance.cash_yi 未披露，流动性/净现金结论必须降级")
    if balance.get("goodwill_yi") is None:
        warnings.append("balance.goodwill_yi 未披露，必须表述为未知，不得按 0 处理")
    if balance.get("interest_debt_yi") is None:
        warnings.append("balance 有息负债分项不完整，净现金/偿债结论必须降级")
    require(indicators.get("count", 0) >= 1, "indicators 无年度财务指标")
    indicator_rows = indicators.get("indicators", [])
    require(indicators.get("count") == len(indicator_rows),
            "indicators.count 与 indicators 长度不一致")
    if indicator_rows:
        require(str(indicator_rows[0].get("year") or "") == str(expected_fiscal_year),
                f"indicators 最新年度陈旧: {indicator_rows[0].get('year')} != {expected_fiscal_year}")
        for field in ("roe_pct", "gross_margin_pct", "net_margin_pct", "debt_ratio_pct"):
            require(_f(indicator_rows[0].get(field)) is not None,
                    f"indicators 最新年度 {field} 缺失")
    require(audit.get("has_audit") is True and audit.get("latest", {}).get("audit_result"),
            "audit 缺少最新年报审计意见")
    audit_end = str(audit.get("latest", {}).get("end_date") or "")
    require(audit_end[:4] == str(expected_fiscal_year),
            f"audit 最新年度陈旧或缺失: {audit_end[:4]!r} != {expected_fiscal_year}")
    market_cap = _f(market.get("total_mv_yi"))
    close = _f(market.get("close"))
    shares = _f(market.get("total_shares_yi"))
    if market_cap is not None and close is not None and shares is not None and shares > 0:
        implied = close * shares
        require(
            abs(market_cap - implied) / max(abs(implied), 1e-9) <= 0.05,
            "market.total_mv_yi 与股价×总股本不一致，疑似单位错误",
        )

    industry = data.get("industry", {})
    if not industry.get("industry_stats"):
        warnings.append("industry 无有效同行样本，禁止报告行业均值/分位")
    else:
        require(
            industry.get("comparison_fiscal_year") == expected_fiscal_year,
            "industry 财务样本不是同一预期财年",
        )
        require(
            str(industry.get("comparison_trade_date") or "").replace("-", "")
            == str(market.get("trade_date") or "").replace("-", ""),
            "industry 估值样本与目标公司不是同一交易日",
        )
        metric_counts = [
            int(metric.get("count")) for metric in industry.get("industry_stats", {}).values()
            if isinstance(metric, dict) and isinstance(metric.get("count"), int)
        ]
        if not metric_counts or min(metric_counts) < 5:
            warnings.append("industry 有效同行样本少于 5，行业均值/分位结论必须降级")
    macro = data.get("macro", {})
    if not macro.get("indicators"):
        warnings.append("macro 实时指标不可得，宏观判断必须标注数据局限")
    missing_non_recurring = [
        item.get("year") for item in annual.get("annual_data", [])
        if item.get("non_recurring_pct") is None
    ]
    if missing_non_recurring:
        warnings.append(f"annual 扣非代理口径缺失年份: {missing_non_recurring}")

    return {
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
        "errors": errors,
        "warnings": warnings,
        "contract_version": "0.5.1",
    }


def cmd_all(ts_code: str) -> dict:
    data = {"stock_info": cmd_stock_info(ts_code), "market": cmd_market(ts_code),
            "annual": cmd_annual(ts_code), "quarterly": cmd_quarterly(ts_code),
            "balance": cmd_balance(ts_code), "indicators": cmd_indicators(ts_code),
            "audit": cmd_fina_audit(ts_code),
            "industry": cmd_industry(ts_code), "forecast": cmd_forecast(ts_code),
            "macro": cmd_macro()}
    data["meta"] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "analysis_date": TODAY.strftime("%Y%m%d"),
        "cross_validated": False,
        "source_note": "主源失败时按表回退备用源；这不是双源交叉验证",
    }
    data["data_quality"] = validate_snapshot(data)
    return data


def cmd_annual_report(ts_code: str, years: int = 5, force: bool = False) -> dict:
    """
    抓取最近 N 年的年报/半年报/季报全文，解析后存入 annual_reports 表。
    返回结构化 dict，便于 LLM 消费。
    """
    ds = create_data_source(CONFIG)
    # 年报对应已结束财政年度；1-4 月上一年度年报尚未到法定披露截止日。
    end_year = TODAY.year - 1 if TODAY.month >= 5 else TODAY.year - 2
    all_reports = {}
    stored_sections = 0
    conn = get_db()
    now = TODAY.strftime("%Y-%m-%d")
    target_years = list(range(end_year - years + 1, end_year + 1))

    if not force:
        # 先一次性装载全部可用数据库正文，避免按升序遇到最老缺口就触发慢速联网。
        for y in target_years:
            cached_rows = conn.execute(
                """SELECT report_type, ann_date, title, section_name, section_text, source_url
                   FROM annual_reports
                   WHERE ts_code=? AND report_year=?
                     AND LENGTH(TRIM(COALESCE(section_text, ''))) >= 200
                   ORDER BY report_type, section_name""",
                (ts_code, str(y)),
            ).fetchall()
            if not cached_rows or sum(len(row[4] or "") for row in cached_rows) < 1000:
                continue
            reports = {}
            for report_type, ann_date, title, section_name, section_text, source_url in cached_rows:
                report = reports.setdefault(report_type, {
                    "ann_date": ann_date or "", "title": title or "",
                    "source_url": source_url or "", "sections": {},
                })
                report["sections"][section_name] = section_text
            all_reports[str(y)] = reports
            stored_sections += len(cached_rows)

    for y in reversed(target_years):
        if str(y) in all_reports:
            continue
        # 最新应有年度必须先尝试补齐；3 年窗口只能跳过更早缺口。
        if not force and len(all_reports) >= 3 and y != end_year:
            break
        try:
            # 年报正文优先使用本地可审计缓存，缓存不可用时再走远端源。
            cache_source = getattr(ds, "cache", None)
            if cache_source is not None:
                try:
                    data = cache_source.get_annual_report_text(ts_code, str(y))
                except Exception:
                    data = ds.get_annual_report_text(ts_code, str(y))
            else:
                data = ds.get_annual_report_text(ts_code, str(y))
            if not data or not data.get("reports"):
                continue
            all_reports[str(y)] = data["reports"]
            # 写入数据库：按年份包裹事务，单年失败不影响其他年份
            conn.execute("BEGIN")
            try:
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
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        except Exception as e:
            logger.warning(f"年报抓取失败 {ts_code} {y}: {e}")

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

    output = {
        "ts_code": ts_code,
        "years_requested": years,
        "years_fetched": list(all_reports.keys()),
        "stored_sections": stored_sections,
        "summary": summary,
    }
    if stored_sections == 0:
        raise RuntimeError(f"年报正文不可得或解析后无有效章节: {ts_code}")
    return output


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


def _json_safe(obj):
    """递归清除 NaN/Infinity；标准 JSON 不允许这些字面量。"""
    if isinstance(obj, dict):
        return {str(key): _json_safe(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [_json_safe(value) for value in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        return value if math.isfinite(value) else None
    try:
        return None if pd.isna(obj) else obj
    except (TypeError, ValueError):
        return obj


def _json_dumps(obj, *, indent=None) -> str:
    return json.dumps(
        _json_safe(obj), ensure_ascii=False, indent=indent,
        cls=NpEncoder, allow_nan=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="数据获取工具（LLM 消费）")
    sub = parser.add_subparsers(dest="command", required=True)

    # sync 需要 --force 标志
    p_sync = sub.add_parser("sync", help="同步数据到本地 DB")
    p_sync.add_argument("ts_code", help="如 300408.SZ 或 603605.SH")
    p_sync.add_argument("--force", action="store_true", help="强制重新同步，忽略新鲜度检查（重复分析同一家公司时使用）")

    for cmd in ["stock-info", "market", "annual", "quarterly", "balance", "indicators", "industry", "forecast", "all"]:
        p = sub.add_parser(cmd)
        p.add_argument("ts_code", help="如 300408.SZ 或 603605.SH")
    p_annual_report = sub.add_parser("annual-report")
    p_annual_report.add_argument("ts_code", help="如 300408.SZ 或 603605.SH")
    p_annual_report.add_argument("--force", action="store_true", help="忽略数据库正文缓存并重新抓取")
    # 不需要 ts_code 的子命令
    sub.add_parser("macro", help="获取当前宏观关键指标（GDP/PMI/CPI/PPI/M1-M2/利率）")
    sub.add_parser("sync-all-stocks", help="同步全部 A 股基础信息到 stocks 表")

    args = parser.parse_args()

    if args.command == "sync-all-stocks":
        try:
            result = cmd_sync_all_stocks()
            print(_json_dumps(result, indent=2))
            return 0
        except Exception as exc:
            print(_json_dumps({"error": str(exc), "command": args.command}), file=sys.stderr)
            return 2

    if args.command == "macro":
        try:
            result = cmd_macro()
            print(_json_dumps(result, indent=2))
            return 0
        except Exception as exc:
            print(_json_dumps({"error": str(exc), "command": args.command}), file=sys.stderr)
            return 2

    try:
        ts_code = normalize_ts_code(args.ts_code)
    except ValueError as exc:
        print(_json_dumps({"error": str(exc), "command": args.command}), file=sys.stderr)
        return 2

    force_sync = getattr(args, "force", False)

    CMDS = {
        "sync": lambda: cmd_sync(ts_code, force=force_sync), "stock-info": lambda: cmd_stock_info(ts_code),
        "market": lambda: cmd_market(ts_code), "annual": lambda: cmd_annual(ts_code),
        "quarterly": lambda: cmd_quarterly(ts_code), "balance": lambda: cmd_balance(ts_code),
        "indicators": lambda: cmd_indicators(ts_code), "industry": lambda: cmd_industry(ts_code),
        "forecast": lambda: cmd_forecast(ts_code), "all": lambda: cmd_all(ts_code),
        "annual-report": lambda: cmd_annual_report(ts_code, years=5, force=force_sync),
    }
    try:
        result = CMDS[args.command]()
        print(_json_dumps(result, indent=2))
        if args.command == "all" and result.get("data_quality", {}).get("status") == "FAIL":
            for message in result["data_quality"]["errors"]:
                print(f"[data-quality] {message}", file=sys.stderr)
            return 2
        return 0
    except Exception as exc:
        print(_json_dumps({"error": str(exc), "command": args.command,
                           "ts_code": ts_code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
