#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源抽象层：Tushare 为主，AKShare 为备用源。

设计原则：
1. 所有外部数据接口统一通过 DataSource 子类实现
2. FallbackDataSource 先尝试主源，失败或数据缺失时自动切换到备用源
3. 返回的 DataFrame 列名尽量与 Tushare 保持一致，便于下游统一处理
"""

import os, sys, json, subprocess
import time
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def code_to_symbol(ts_code: str) -> str:
    """600519.SH -> 600519"""
    return ts_code.split(".")[0]


def code_to_exchange(ts_code: str) -> str:
    """600519.SH -> SH"""
    return ts_code.split(".")[1]


def normalize_date(d) -> str:
    """把各种日期格式统一为 YYYYMMDD"""
    if d is None:
        return ""
    try:
        if pd.isna(d):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(d, pd.Timestamp):
        return d.strftime("%Y%m%d")
    if isinstance(d, datetime):
        return d.strftime("%Y%m%d")
    s = str(d).replace("-", "").replace("/", "")
    if len(s) == 8 and s.isdigit():
        return s
    return s


def normalize_date_hyphen(d) -> str:
    """把各种日期格式统一为 YYYY-MM-DD"""
    s = normalize_date(d)
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return str(d)


def yuan_to_wan(value) -> Optional[float]:
    """AKShare spot 市值（元）→ 内部 daily_basic 契约（万元）。"""
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed / 10000 if np.isfinite(parsed) else None


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class DataSource(ABC):
    """数据源抽象基类。"""

    name: str = "base"

    @abstractmethod
    def get_stock_basic(self, ts_code: str) -> pd.DataFrame:
        """返回基础信息 DataFrame，列至少包含 ts_code, symbol, name, exchange, list_date, industry, area"""
        pass

    @abstractmethod
    def get_all_stocks(self) -> pd.DataFrame:
        """返回全部 A 股基础信息，用于按名称搜索"""
        pass

    @abstractmethod
    def get_daily_quotes(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """返回日线 DataFrame，列：trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount"""
        pass

    @abstractmethod
    def get_daily_basic(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """返回估值 DataFrame，列：trade_date, close, turnover_rate, pe_ttm, pb, ps_ttm, total_mv, circ_mv, ..."""
        pass

    @abstractmethod
    def get_income(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_balance(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_cashflow(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_fina_indicator(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_fina_audit(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_forecast(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取业绩预告数据。返回字段：ts_code, ann_date, end_date, type, p_change_min,
        p_change_max, net_profit_min, net_profit_max, last_parent_net, summary, change_reason"""
        pass

    @abstractmethod
    def get_annual_report_text(self, ts_code: str, report_year: str) -> dict:
        """获取年报/半年报/季报文本。
        返回结构化 dict：
        {
            "ts_code": "002444.SZ",
            "report_year": "2024",
            "report_type": "annual",
            "ann_date": "20240427",
            "title": "2024年年度报告",
            "source_url": "...",
            "sections": {
                "经营情况讨论与分析": "...",
                "核心竞争力分析": "...",
                "公司未来发展的展望": "...",
                "可能面对的风险": "...",
                "募集资金使用": "..."
            },
            "full_text": "..."
        }
        """

    @abstractmethod
    def get_macro_data(self) -> dict:
        """获取宏观关键指标（GDP/PMI/CPI/PPI/M1-M2/利率），返回结构化 dict。
        每个指标独立容错——单个失败不阻塞其余。"""
        pass


# ---------------------------------------------------------------------------
# Tushare 数据源
# ---------------------------------------------------------------------------

class TushareDataSource(DataSource):
    name = "tushare"

    def __init__(self, token: Optional[str] = None):
        import tushare as ts
        if token is None:
            token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise RuntimeError(
                "Tushare token 未提供，且环境变量 TUSHARE_TOKEN 未设置。\n"
                "请执行以下操作之一：\n"
                "  1. 当前终端：export TUSHARE_TOKEN=你的token\n"
                "  2. 持久化：写入 ~/.bashrc 或 ~/.zshrc\n"
                "  3. 项目级：复制 .env.example 为 .env 并填写 token\n"
                "注意：不要把真实 token 提交到 git。"
            )
        self.pro = ts.pro_api(token)

    def _safe_call(self, func, *args, **kwargs) -> pd.DataFrame:
        """Tushare 有频率限制，失败时重试一次。"""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Tushare 调用失败，1 秒后重试: {e}")
            time.sleep(1)
            return func(*args, **kwargs)

    def get_stock_basic(self, ts_code: str) -> pd.DataFrame:
        df = self._safe_call(self.pro.stock_basic, ts_code=ts_code,
                             fields="ts_code,symbol,name,fullname,exchange,list_date,delist_date,industry,area")
        return df

    def get_all_stocks(self) -> pd.DataFrame:
        """获取全部 A 股列表。"""
        df = self._safe_call(self.pro.stock_basic, exchange='', list_status='L',
                             fields="ts_code,symbol,name,fullname,exchange,list_date,delist_date,industry,area")
        return df

    def get_daily_quotes(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._safe_call(self.pro.daily, ts_code=ts_code, start_date=start_date, end_date=end_date)
        if not df.empty:
            df = df.rename(columns={
                "trade_date": "trade_date",
                "open": "open", "high": "high", "low": "low", "close": "close",
                "pre_close": "pre_close", "change": "change", "pct_chg": "pct_chg",
                "vol": "vol", "amount": "amount"
            })
        return df

    def get_daily_basic(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._safe_call(self.pro.daily_basic, ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_income(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        fields = ("ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,total_revenue,revenue,total_cogs,"
                  "sell_exp,admin_exp,fin_exp,rd_exp,operate_profit,non_oper_income,total_profit,n_income,n_income_attr_p")
        return self._safe_call(self.pro.income, ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)

    def get_balance(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        fields = ("ts_code,ann_date,f_ann_date,end_date,report_type,total_assets,total_liab,"
                  "total_hldr_eqy_exc_min_int,total_hldr_eqy_inc_min_int,money_cap,trad_asset,notes_receiv,"
                  "accounts_receiv,inventories,goodwill,intan_assets,fix_assets,total_nca,st_borr,lt_borr,"
                  "bonds_payable,total_cur_liab,total_noncur_liab,total_share")
        return self._safe_call(self.pro.balancesheet, ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)

    def get_cashflow(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        fields = ("ts_code,ann_date,f_ann_date,end_date,report_type,c_cash_equ_end_period,n_cashflow_act,"
                  "n_cashflow_inv_act,n_cash_flows_fnc_act,c_pay_acq_const_fiolta,free_cashflow")
        df = self._safe_call(
            self.pro.cashflow,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            report_type="1",
            fields=fields,
        )
        # Tushare 的字段名是 free_cashflow；数据库历史字段沿用 free_cash_flow。
        return df.rename(columns={"free_cashflow": "free_cash_flow"})

    def get_fina_indicator(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        fields = ("ts_code,ann_date,end_date,roe,roe_waa,roe_dt,roic,grossprofit_margin,netprofit_margin,"
                  "op_yoy,netprofit_yoy,tr_yoy,or_yoy,assets_yoy,equity_yoy,debt_to_assets,current_ratio,"
                  "quick_ratio,cash_ratio,ocf_to_profit")
        return self._safe_call(self.pro.fina_indicator, ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)

    def get_fina_audit(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._safe_call(self.pro.fina_audit, ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_forecast(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._safe_call(self.pro.forecast, ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_macro_data(self) -> dict:
        """通过 Tushare 拉取宏观关键指标。

        拉取 5 类指标（各行独立容错）:
        1. GDP 增速（cn_gdp）
        2. PMI 制造业/非制造业（cn_pmi）
        3. CPI / PPI（cn_cpi / cn_ppi）
        4. M1/M2 增速及剪刀差（cn_m）
        5. SHIBOR 隔夜（shibor）

        返回 dict，缺失指标记录在 errors 列表中，不抛异常。
        """
        from datetime import datetime as _dt
        today = _dt.now()
        start_month = (today - timedelta(days=395)).strftime("%Y%m")
        end_month = today.strftime("%Y%m")
        start_quarter = f"{today.year - 3}Q1"
        end_quarter = f"{today.year}Q4"
        result = {
            "update_date": _dt.now().strftime("%Y-%m-%d"),
            "source": "tushare",
            "indicators": {},
            "errors": [],
        }

        def _safe(key, fn):
            try:
                val = fn()
                if val is not None:
                    result["indicators"][key] = val
            except Exception as e:
                result["errors"].append(f"{key}: {e}")

        # 1. GDP — 最近 3 个季度
        def _gdp():
            df = self._safe_call(self.pro.cn_gdp, start_q=start_quarter, end_q=end_quarter,
                                 fields="quarter,gdp,gdp_yoy")
            if df.empty:
                return None
            df = df.sort_values("quarter", ascending=False)
            series = []
            for _, r in df.iterrows():
                # cn_gdp 返回单位为亿元，/ 10000 转为万亿
                gdp_yi = float(r["gdp"]) / 10000 if r.get("gdp") else None
                gdp_yi = round(gdp_yi, 2) if gdp_yi is not None else None
                yoy = float(r["gdp_yoy"]) if r.get("gdp_yoy") else None
                series.append({"quarter": str(r["quarter"]), "gdp_yi": gdp_yi, "yoy_pct": yoy})
            return {"latest": series[0] if series else {}, "series": series}

        # 2. PMI — 最近 6 个月
        def _pmi():
            # cn_pmi 不支持 fields 过滤，返回全量列（数据量小，可接受）
            df = self._safe_call(self.pro.cn_pmi, start_m=start_month, end_m=end_month)
            if df.empty:
                return None
            df = df.sort_values("MONTH", ascending=False)
            mfg = {"latest": None, "trend": []}
            svc = {"latest": None, "trend": []}
            for _, r in df.iterrows():
                m = str(r.get("MONTH", r.get("month", "")))
                mv = float(r["PMI010000"]) if r.get("PMI010000") else None
                sv = float(r["PMI020100"]) if r.get("PMI020100") else None
                if mfg["latest"] is None:
                    mfg["latest"] = {"month": m, "value": mv}
                mfg["trend"].append({"month": m, "value": mv})
                if svc["latest"] is None:
                    svc["latest"] = {"month": m, "value": sv}
                svc["trend"].append({"month": m, "value": sv})
            return {"manufacturing": mfg, "non_manufacturing": svc}

        # 3. CPI & PPI — 最近 6 个月
        def _cpi_ppi():
            df_cpi = self._safe_call(self.pro.cn_cpi, start_m=start_month, end_m=end_month,
                                     fields="month,nt_yoy")
            df_ppi = self._safe_call(self.pro.cn_ppi, start_m=start_month, end_m=end_month,
                                     fields="month,ppi_yoy")
            output = {}
            for out_key, colname in [("cpi", "nt_yoy"), ("ppi", "ppi_yoy")]:
                df = df_cpi if out_key == "cpi" else df_ppi
                if df.empty:
                    continue
                df = df.sort_values("month", ascending=False)
                series, latest_val = [], None
                for _, r in df.iterrows():
                    v = float(r[colname]) if r.get(colname) else None
                    if latest_val is None:
                        latest_val = v
                    series.append({"month": str(r["month"]), "yoy_pct": v})
                latest_month = str(df.iloc[0]["month"]) if not df.empty else None
                output[out_key] = {"latest": {"month": latest_month, "yoy_pct": latest_val},
                                   "series": series}
            return output if output else None

        # 4. M1/M2 — 最近 6 个月
        def _money():
            df = self._safe_call(self.pro.cn_m, start_m=start_month, end_m=end_month,
                                 fields="month,m1_yoy,m2_yoy")
            if df.empty:
                return None
            df = df.sort_values("month", ascending=False)
            first = df.iloc[0]
            m1 = float(first["m1_yoy"]) if first.get("m1_yoy") else None
            m2 = float(first["m2_yoy"]) if first.get("m2_yoy") else None
            scissors = round(m1 - m2, 2) if m1 is not None and m2 is not None else None
            series = []
            for _, r in df.iterrows():
                v1 = float(r["m1_yoy"]) if r.get("m1_yoy") else None
                v2 = float(r["m2_yoy"]) if r.get("m2_yoy") else None
                s = round(v1 - v2, 2) if v1 is not None and v2 is not None else None
                series.append({"month": str(r["month"]), "m1_yoy_pct": v1,
                               "m2_yoy_pct": v2, "scissors_pct": s})
            return {"latest_scissors_pct": scissors, "series": series}

        # 5. SHIBOR 隔夜 — 最近一日
        def _shibor():
            df = self._safe_call(
                self.pro.shibor,
                start_date=(today - timedelta(days=10)).strftime("%Y%m%d"),
                end_date=today.strftime("%Y%m%d"),
            )
            if df.empty:
                return None
            df = df.sort_values("date", ascending=False)
            r = df.iloc[0]
            on_val = float(r["on"]) if r.get("on") else None
            w1_val = float(r["1w"]) if r.get("1w") else None
            return {"date": str(r.get("date", "")), "overnight_pct": on_val,
                    "week_pct": w1_val}

        for key, fn in [("gdp", _gdp), ("pmi", _pmi), ("inflation", _cpi_ppi),
                         ("money_supply", _money), ("shibor", _shibor)]:
            _safe(key, fn)

        return result

    def get_annual_report_text(self, ts_code: str, report_year: str) -> dict:
        """Tushare 暂不直接提供年报全文，抛出异常让 fallback 到 AKShare 处理。"""
        raise NotImplementedError("Tushare 数据源不支持年报全文抓取，请使用 AKShare 备用源")


# ---------------------------------------------------------------------------
# AKShare 数据源（备用）
# ---------------------------------------------------------------------------

class AKShareDataSource(DataSource):
    name = "akshare"

    def __init__(self):
        try:
            import akshare as ak
            self.ak = ak
        except ImportError as e:
            raise RuntimeError("AKShare 未安装，请执行 pip install akshare") from e

    def _symbol(self, ts_code: str) -> str:
        return code_to_symbol(ts_code)

    def get_stock_basic(self, ts_code: str) -> pd.DataFrame:
        """通过 spot 行情表获取基本信息。"""
        symbol = self._symbol(ts_code)
        try:
            df = self.ak.stock_individual_info_em(symbol=symbol)
        except Exception:
            # 备用：从全市场 spot 中过滤
            df = self.ak.stock_zh_a_spot_em()
            df = df[df["代码"] == symbol]
            if df.empty:
                return pd.DataFrame()
            row = df.iloc[0]
            return pd.DataFrame([{
                "ts_code": ts_code,
                "symbol": symbol,
                "name": row.get("名称", ""),
                "fullname": "",
                "exchange": code_to_exchange(ts_code),
                "list_date": "",
                "delist_date": "",
                "industry": row.get("所属行业", ""),
                "area": ""
            }])

        # stock_individual_info_em 返回 key-value 形式。
        info = dict(zip(df["item"].astype(str), df["value"]))
        return pd.DataFrame([{
            "ts_code": ts_code,
            "symbol": symbol,
            "name": info.get("股票简称", ""),
            "fullname": info.get("公司名称", ""),
            "exchange": code_to_exchange(ts_code),
            "list_date": normalize_date(info.get("上市时间", "")),
            "delist_date": "",
            "industry": info.get("行业", ""),
            "area": info.get("地域", "")
        }])

    def get_all_stocks(self) -> pd.DataFrame:
        """从全市场 spot 获取全部 A 股。"""
        try:
            df = self.ak.stock_zh_a_spot_em()
        except Exception as e:
            logger.warning(f"AKShare 全市场股票获取失败: {e}")
            return pd.DataFrame()
        if df.empty:
            return df
        result = []
        for _, row in df.iterrows():
            symbol = str(row.get("代码", ""))
            if not symbol or len(symbol) != 6:
                continue
            ts_code = f"{symbol}.SH" if symbol[0] in ("6", "5", "9") else f"{symbol}.SZ"
            result.append({
                "ts_code": ts_code,
                "symbol": symbol,
                "name": row.get("名称", ""),
                "fullname": "",
                "exchange": code_to_exchange(ts_code),
                "list_date": "",
                "delist_date": "",
                "industry": row.get("所属行业", ""),
                "area": ""
            })
        return pd.DataFrame(result)

    def get_daily_quotes(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = self._symbol(ts_code)
        try:
            df = self.ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                          start_date=start_date, end_date=end_date,
                                          adjust="qfq")
        except Exception as e:
            logger.warning(f"AKShare 日线获取失败: {e}")
            return pd.DataFrame()

        if df.empty:
            return df

        # AKShare 列名：日期，开盘，收盘，最高，最低，成交量，成交额，振幅，涨跌幅，涨跌额，换手率
        df = df.rename(columns={
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "vol",
            "成交额": "amount",
            "振幅": "amplitude",
            "涨跌幅": "pct_chg",
            "涨跌额": "change",
            "换手率": "turnover_rate"
        })
        df["trade_date"] = df["trade_date"].apply(normalize_date)
        df["pre_close"] = (df["close"].astype(float) - df["change"].astype(float)).round(2)
        # 补齐 Tushare 风格列
        for col in ["open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df[["trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]]

    def get_daily_basic(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从全市场 spot 获取最新估值；AKShare 不便于返回历史日线估值序列，因此只返回最新一天。"""
        symbol = self._symbol(ts_code)
        today = datetime.now()
        end_norm = normalize_date(end_date)
        if end_norm != today.strftime("%Y%m%d"):
            logger.warning("AKShare spot 不能提供历史时点估值，拒绝用当前值回填历史日期")
            return pd.DataFrame()
        if today.weekday() < 5 and today.hour < 16:
            logger.warning("AKShare spot 尚处交易时段，拒绝把盘中估值伪装成收盘数据")
            return pd.DataFrame()
        try:
            df = self.ak.stock_zh_a_spot_em()
        except Exception as e:
            logger.warning(f"AKShare spot 获取失败: {e}")
            return pd.DataFrame()

        df = df[df["代码"] == symbol]
        if df.empty:
            return pd.DataFrame()

        row = df.iloc[0]
        recent_start = (today - timedelta(days=14)).strftime("%Y%m%d")
        recent_quotes = self.get_daily_quotes(ts_code, recent_start, end_norm)
        if recent_quotes.empty:
            logger.warning("AKShare 无法确认最近实际交易日，拒绝生成 daily_basic")
            return pd.DataFrame()
        latest_quote = recent_quotes.sort_values("trade_date", ascending=False).iloc[0]
        actual_trade_date = str(latest_quote["trade_date"])

        # AKShare spot 列：代码，名称，最新价，涨跌幅，涨跌额，成交量，成交额，振幅，最高，最低，今开，昨收，量比，换手率，市盈率-动态，市净率，总市值，流通市值，涨速，5分钟涨跌，60日涨跌幅，年初至今涨跌幅
        def to_float(x, default=None):
            try:
                return float(str(x).replace(",", ""))
            except (ValueError, TypeError):
                return default

        result = pd.DataFrame([{
            "ts_code": ts_code,
            "trade_date": actual_trade_date,
            "close": to_float(latest_quote.get("close")),
            "turnover_rate": to_float(row.get("换手率")),
            "turnover_rate_f": None,
            "volume_ratio": to_float(row.get("量比")),
            "pe": to_float(row.get("市盈率-动态")),
            "pe_ttm": to_float(row.get("市盈率-动态")),
            "pb": to_float(row.get("市净率")),
            "ps": None,
            "ps_ttm": None,
            "dv_ratio": None,
            # AKShare spot 市值单位为元；内部/Tushare daily_basic 契约为万元。
            "total_mv": yuan_to_wan(row.get("总市值")),
            "circ_mv": yuan_to_wan(row.get("流通市值")),
            "total_share": None,
            "float_share": None,
            "free_share": None
        }])
        return result

    def _get_financial_report_sina(self, ts_code: str, report_type: str, start_date: str, end_date: str) -> pd.DataFrame:
        """通用财务报表获取（AKShare 备用）。report_type: 资产负债表/利润表/现金流量表"""
        symbol = self._symbol(ts_code)
        # AKShare 对于深交所股票需要 sz 前缀，上交所 sh 前缀
        if ts_code.endswith(".SZ"):
            ak_symbol = f"sz{symbol}"
        else:
            ak_symbol = f"sh{symbol}"
        try:
            df = self.ak.stock_financial_report_sina(stock=ak_symbol, symbol=report_type)
        except Exception as e:
            logger.warning(f"AKShare {report_type} 获取失败: {e}")
            return pd.DataFrame()

        if df.empty:
            return df

        # stock_financial_report_sina 返回的格式：第一列通常是日期列（"报告日"等），其余列为财务科目
        # 已经是标准行列格式，不需要 pivot
        # 查找日期列：优先匹配名称含"报告日/日期"的列，其次检查列值是否像日期
        date_col = None
        for col in df.columns:
            col_str = str(col)
            if "报告日" in col_str or "日期" in col_str or "报告期" in col_str:
                date_col = col
                break
        if date_col is None:
            # 回退：检查第一列的值是否匹配日期格式
            first_col = df.columns[0]
            sample = str(df[first_col].iloc[0]) if not df.empty else ""
            if len(sample.replace("-", "")) == 8 and sample.replace("-", "").isdigit():
                date_col = first_col
        if date_col is None:
            logger.warning(f"AKShare {report_type}: 无法识别日期列，列名={list(df.columns)[:5]}")
            return pd.DataFrame()
        df = df.rename(columns={date_col: "end_date"})
        df["end_date"] = df["end_date"].apply(normalize_date)

        # 过滤日期范围
        start_norm = normalize_date(start_date)
        end_norm = normalize_date(end_date)
        df = df[(df["end_date"] >= start_norm) & (df["end_date"] <= end_norm)]

        if df.empty:
            return df

        df["ts_code"] = ts_code
        df["ann_date"] = ""
        df["f_ann_date"] = ""
        df["report_type"] = ""
        return df

    def get_income(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._get_financial_report_sina(ts_code, "利润表", start_date, end_date)
        if df.empty:
            return df
        # 常见列名映射（AKShare 返回中文科目）
        col_map = {
            "营业总收入": "total_revenue",
            "营业收入": "revenue",
            "营业总成本": "total_cogs",
            "销售费用": "sell_exp",
            "管理费用": "admin_exp",
            "财务费用": "fin_exp",
            "研发费用": "rd_exp",
            "营业利润": "operate_profit",
            "利润总额": "total_profit",
            "净利润": "n_income",
            "归属于母公司股东的净利润": "n_income_attr_p",
            "营业外收入": "non_oper_income",
        }
        for cn, en in col_map.items():
            if cn in df.columns:
                df[en] = pd.to_numeric(df[cn].astype(str).str.replace(",", ""), errors="coerce")
        return df

    def get_balance(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._get_financial_report_sina(ts_code, "资产负债表", start_date, end_date)
        if df.empty:
            return df
        col_map = {
            "资产总计": "total_assets",
            "负债合计": "total_liab",
            "所有者权益(或股东权益)合计": "total_hldr_eqy_inc_min_int",
            "归属于母公司所有者权益合计": "total_hldr_eqy_exc_min_int",
            "货币资金": "money_cap",
            "交易性金融资产": "trad_asset",
            "应收票据": "notes_receiv",
            "应收账款": "accounts_receiv",
            "存货": "inventories",
            "商誉": "goodwill",
            "无形资产": "intan_assets",
            "固定资产": "fix_assets",
            "非流动资产合计": "total_nca",
            "短期借款": "st_borr",
            "长期借款": "lt_borr",
            "应付债券": "bonds_payable",
            "流动负债合计": "total_cur_liab",
            "非流动负债合计": "total_noncur_liab",
            "实收资本(或股本)": "total_share",
        }
        for cn, en in col_map.items():
            if cn in df.columns:
                df[en] = pd.to_numeric(df[cn].astype(str).str.replace(",", ""), errors="coerce")
        return df

    def get_cashflow(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._get_financial_report_sina(ts_code, "现金流量表", start_date, end_date)
        if df.empty:
            return df
        col_map = {
            "经营活动产生的现金流量净额": "n_cashflow_act",
            "投资活动产生的现金流量净额": "n_cashflow_inv_act",
            "筹资活动产生的现金流量净额": "n_cash_flows_fnc_act",
            "期末现金及现金等价物余额": "c_cash_equ_end_period",
            "购建固定资产、无形资产和其他长期资产支付的现金": "c_pay_acq_const_fiolta",
            "购建固定资产、无形资产及其他长期资产支付的现金": "c_pay_acq_const_fiolta",
        }
        for cn, en in col_map.items():
            if cn in df.columns:
                df[en] = pd.to_numeric(df[cn].astype(str).str.replace(",", ""), errors="coerce")
        return df

    def get_fina_indicator(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = self._symbol(ts_code)
        try:
            df = self.ak.stock_financial_abstract_ths(symbol=symbol, indicator="按报告期")
        except Exception as e:
            logger.warning(f"AKShare 财务指标获取失败: {e}")
            return pd.DataFrame()

        if df.empty:
            return df

        # 列名映射
        col_map = {
            "报告期": "end_date",
            "净资产收益率": "roe",
            "净资产收益率-摊薄": "roe_dt",
            "销售毛利率": "grossprofit_margin",
            "销售净利率": "netprofit_margin",
            "营业总收入同比增长率": "tr_yoy",
            "净利润同比增长率": "netprofit_yoy",
            "资产负债率": "debt_to_assets",
            "流动比率": "current_ratio",
            "速动比率": "quick_ratio",
            "每股经营现金流": "ocf_to_profit",
        }
        df = df.rename(columns=col_map)

        # 百分比字段转为数值（保持与 Tushare 一致的百分比格式，如 24.62 表示 24.62%）
        pct_fields = ["roe", "roe_dt", "grossprofit_margin", "netprofit_margin",
                       "tr_yoy", "netprofit_yoy", "debt_to_assets"]
        for field in pct_fields:
            if field in df.columns:
                df[field] = df[field].astype(str).str.replace(",", "").str.replace("%", "")
                df[field] = pd.to_numeric(df[field], errors="coerce")

        # 比率字段直接转数值
        ratio_fields = ["current_ratio", "quick_ratio", "ocf_to_profit"]
        for field in ratio_fields:
            if field in df.columns:
                df[field] = pd.to_numeric(df[field].astype(str).str.replace(",", ""), errors="coerce")

        # 标准化日期
        df["end_date"] = df["end_date"].apply(normalize_date)

        # 过滤日期范围
        start_norm = normalize_date(start_date)
        end_norm = normalize_date(end_date)
        df = df[(df["end_date"] >= start_norm) & (df["end_date"] <= end_norm)]

        if df.empty:
            return df

        df["ts_code"] = ts_code
        df["ann_date"] = ""
        return df

    def get_fina_audit(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        # AKShare 暂无标准审计意见接口，返回空
        return pd.DataFrame()

    def get_forecast(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        # AKShare 暂无业绩预告接口，返回空（依赖主源 Tushare）
        return pd.DataFrame()

    def get_macro_data(self) -> dict:
        """AKShare 宏观数据（备用源）。每个指标独立容错。"""
        from datetime import datetime as _dt
        result = {
            "update_date": _dt.now().strftime("%Y-%m-%d"),
            "source": "akshare",
            "indicators": {},
            "errors": [],
        }

        def _try(key, fn):
            try:
                val = fn()
                if val is not None:
                    result["indicators"][key] = val
            except Exception as e:
                result["errors"].append(f"{key}: {e}")

        # GDP
        def _gdp():
            df = self.ak.macro_china_gdp_yearly()
            if df.empty:
                return None
            series = []
            for _, r in df.iterrows():
                row = {str(k).lower(): v for k, v in r.items()}
                year = str(row.get("年份", r.iloc[0] if len(df.columns) > 0 else ""))
                gdp_raw = row.get("国内生产总值") or row.get("gdp") or row.get("总值")
                yoy_raw = row.get("同比增长") or row.get("gdp_yoy")
                try:
                    gdp_val = float(str(gdp_raw).replace(",", "")) if gdp_raw is not None else None
                    yoy_val = float(str(yoy_raw).replace(",", "")) if yoy_raw is not None else None
                except Exception:
                    gdp_val, yoy_val = None, None
                series.append({"quarter": year, "gdp_yi": round(gdp_val / 1e8, 2)
                               if gdp_val else None, "yoy_pct": yoy_val})
            return {"latest": series[-1] if series else {}, "series": series}

        # PMI
        def _pmi():
            df = self.ak.macro_china_pmi()
            if df.empty:
                return None
            df = df.tail(6)
            mfg_trend, svc_trend = [], []
            for _, r in df.iterrows():
                row = {str(k).lower(): v for k, v in r.items()}
                month = str(row.get("月份", row.get("month", row.get("日期", ""))))
                try:
                    mv = float(str(row.get("制造业", row.get("pmi010000", ""))).replace(",", ""))
                    sv = float(str(row.get("非制造业", row.get("pmi020000", ""))).replace(",", ""))
                except Exception:
                    mv, sv = None, None
                mfg_trend.insert(0, {"month": month, "value": mv})
                svc_trend.insert(0, {"month": month, "value": sv})
            return {
                "manufacturing": {"latest": mfg_trend[-1] if mfg_trend else None, "trend": mfg_trend},
                "non_manufacturing": {"latest": svc_trend[-1] if svc_trend else None, "trend": svc_trend},
            }

        # CPI/PPI
        def _cpi_ppi():
            output = {}
            for label, fn_name in [("cpi", "macro_china_cpi_monthly"), ("ppi", "macro_china_ppi_yearly")]:
                try:
                    df = getattr(self.ak, fn_name)()
                    if df.empty:
                        continue
                    series = []
                    for _, r in df.tail(6).iterrows():
                        row = {str(k).lower(): v for k, v in r.items()}
                        month = str(row.get("月份", row.get("month", row.get("日期", ""))))
                        v = row.get("居民消费价格指数") or row.get("cpi") or row.get("全国") or row.get("ppi")
                        try:
                            v = float(str(v).replace(",", "")) if v is not None else None
                        except Exception:
                            v = None
                        series.insert(0, {"month": month, "yoy_pct": v})
                    latest = series[-1] if series else {"month": None, "yoy_pct": None}
                    output[label] = {"latest": latest, "series": series}
                except Exception:
                    pass
            return output if output else None

        # M1/M2
        def _money():
            df = self.ak.macro_china_money_supply()
            if df.empty:
                return None
            df = df.tail(6)
            series = []
            for _, r in df.iterrows():
                row = {str(k).lower(): v for k, v in r.items()}
                month = str(row.get("月份", row.get("month", row.get("日期", ""))))
                try:
                    m1 = float(str(row.get("m1同比", row.get("m1_yoy", "0"))).replace(",", ""))
                    m2 = float(str(row.get("m2同比", row.get("m2_yoy", "0"))).replace(",", ""))
                except Exception:
                    m1, m2 = None, None
                s = round(m1 - m2, 2) if m1 is not None and m2 is not None else None
                series.insert(0, {"month": month, "m1_yoy_pct": m1,
                                  "m2_yoy_pct": m2, "scissors_pct": s})
            latest_s = series[-1]["scissors_pct"] if series else None
            return {"latest_scissors_pct": latest_s, "series": series}

        for key, fn in [("gdp", _gdp), ("pmi", _pmi), ("inflation", _cpi_ppi),
                         ("money_supply", _money)]:
            _try(key, fn)

        return result

    def get_annual_report_text(self, ts_code: str, report_year: str) -> dict:
        """
        通过巨潮资讯网 API 获取年报/半年报/三季报 PDF，解析为结构化文本。
        返回 dict，包含 sections 和 full_text。
        """
        symbol = self._symbol(ts_code)
        exchange = "sh" if ts_code.endswith(".SH") else "sz"
        column = "sse" if exchange == "sh" else "szse"

        # 分类映射：年报、半年报、三季报、一季报
        category_map = {
            "annual": "category_ndbg_szsh",
            "semi-annual": "category_bndbg_szsh",
            "q3": "category_sjdbg_szsh",
            "q1": "category_yjdbg_szsh",
        }

        import requests
        import io
        import pdfplumber
        from datetime import datetime

        # 获取 orgId
        # 巨潮 orgId 规则：gs + 交易所代码(sh/sz) + 股票代码补零到7位
        # 例：平安银行 gssz0000001(000001)、福耀玻璃 gssh0060060(600660)
        # 注意：sse_stock.json 接口已失效(404)，直接按规则构造，无需请求列表API
        padded_symbol = symbol.zfill(7)
        org_id = f"gs{exchange}{padded_symbol}"
        try:
            stock_json_url = f"http://www.cninfo.com.cn/new/data/{column}_stock.json"
            r = requests.get(stock_json_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                stock_list = r.json().get("stockList", [])
                for item in stock_list:
                    if item.get("code") == symbol:
                        org_id = item.get("orgId") or org_id
                        break
        except Exception as e:
            logger.warning(f"AKShare 获取 orgId 失败 {ts_code}: {e}，使用规则构造 {org_id}")

        stock_item = f"{symbol},{org_id}"
        start = f"{report_year}-01-01"
        end = f"{report_year}-12-31"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        }
        base_api = "http://www.cninfo.com.cn/new/hisAnnouncement/query"

        def fetch_pdf(category_key: str) -> dict:
            cat = category_map.get(category_key)
            if not cat:
                return {}
            payload = {
                "pageNum": "1",
                "pageSize": "30",
                "column": column,
                "tabName": "fulltext",
                "plate": "",
                "stock": stock_item,
                "searchkey": "",
                "secid": "",
                "category": cat,
                "trade": "",
                "seDate": f"{start}~{end}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            try:
                r = requests.post(base_api, data=payload, headers=headers, timeout=20)
                data = r.json()
                anns = data.get("announcements") or []
                if not anns:
                    return {}
                # 选择中文版：跳过标题含 "英文版" / "英文" / "English" 的公告
                selected_ann = None
                for ann in anns:
                    title = ann.get("announcementTitle", "")
                    if any(k in title for k in ["英文版", "英文", "English"]):
                        continue
                    selected_ann = ann
                    break
                # 如果全是英文版，则取第一条
                if selected_ann is None:
                    selected_ann = anns[0]
                ann = selected_ann
                adjunct = ann.get("adjunctUrl", "")
                if not adjunct:
                    return {}
                pdf_url = f"http://static.cninfo.com.cn/{adjunct}"
                pdf_resp = requests.get(pdf_url, headers={"User-Agent": headers["User-Agent"]}, timeout=30)
                if pdf_resp.status_code != 200:
                    return {}
                # 解析 PDF
                text_parts = []
                with pdfplumber.open(io.BytesIO(pdf_resp.content)) as pdf:
                    for page in pdf.pages:
                        txt = page.extract_text()
                        if txt:
                            text_parts.append(txt)
                full_text = "\n".join(text_parts)
                # 公告时间处理（毫秒时间戳）
                ann_time = ann.get("announcementTime", "")
                try:
                    ann_date = datetime.fromtimestamp(int(ann_time) / 1000).strftime("%Y%m%d")
                except Exception:
                    ann_date = str(ann_time)[:10].replace("-", "")
                return {
                    "ann_date": ann_date,
                    "title": ann.get("announcementTitle", ""),
                    "source_url": pdf_url,
                    "full_text": full_text,
                    "sections": self._split_report_sections(full_text),
                }
            except Exception as e:
                logger.warning(f"AKShare 年报抓取失败 {ts_code} {report_year} {category_key}: {e}")
                return {}

        # 优先获取年报，其次半年报、三季报、一季报
        result = {"ts_code": ts_code, "report_year": report_year, "reports": {}}
        for cat_key in ["annual", "semi-annual", "q3", "q1"]:
            data = fetch_pdf(cat_key)
            if data:
                result["reports"][cat_key] = data
        return result

    @staticmethod
    def _split_report_sections(text: str) -> dict:
        """
        按常见年报章节标题拆分文本。返回 {章节名: 内容}。
        支持 "第X节 章节名"、"X、章节名"、单独一行 "章节名" 等多种形式。
        """
        if not text:
            return {}

        # 关键章节关键词，按年报常见顺序
        key_sections = [
            ("重要提示、目录和释义", ["重要提示", "目录和释义"]),
            ("公司简介和主要财务指标", ["公司简介和主要财务指标", "公司基本情况", "主要会计数据和财务指标"]),
            ("管理层讨论与分析", ["管理层讨论与分析", "经营情况讨论与分析", "管理层讨论与分析"]),
            ("公司治理", ["公司治理", "股东大会情况"]),
            ("环境和社会责任", ["环境和社会责任", "社会责任", "环境保护"]),
            ("重要事项", ["重要事项", "重大事项"]),
            ("股份变动及股东情况", ["股份变动及股东情况", "股东和实际控制人情况"]),
            ("债券相关情况", ["债券相关情况", "公司债券"]),
            ("财务报告", ["财务报告", "审计报告", "合并资产负债表"]),
        ]

        # 构造正则：匹配 "第N节 章节名" 或 "N、章节名" 或单独 "章节名"（作为一行开头）
        patterns = []
        for sec_name, aliases in key_sections:
            alias_pattern = "|".join(re.escape(a) for a in aliases)
            # 形式1: 第[一二三四五六七八九十\d]+节\s*(章节名)
            # 形式2: [一二三四五六七八九十\d]+[、.．]\s*(章节名)
            # 形式3: 行首单独出现章节名
            pattern = (
                f"(?:"
                f"第[一二三四五六七八九十\\d]+[节章]\\s*({alias_pattern})"
                f"|[一二三四五六七八九十\\d]+[、.．\\s]+({alias_pattern})"
                f"|^[\\s]*({alias_pattern})[\\s]*$"
                f")"
            )
            patterns.append((sec_name, re.compile(pattern, re.MULTILINE)))

        # 找到每个章节的起始位置
        positions = []
        for sec_name, regex in patterns:
            for m in regex.finditer(text):
                positions.append((m.start(), sec_name))
                break  # 每个章节只取第一次出现

        if not positions:
            return {"全文": text}

        positions.sort()

        # 提取章节内容
        sections = {}
        for i, (start, sec_name) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            sections[sec_name] = text[start:end].strip()

        return sections


# ---------------------------------------------------------------------------
# 自动回退数据源
# ---------------------------------------------------------------------------


class CacheDataSource(DataSource):
    """
    本地缓存 + 浏览器下载的年报数据源（第三源）。
    1. 检查 ~/企业年报/{code6}/{year}_{code6}_annual_sections.json
    2. 有则直接返回
    3. 无则调用 cninfo-annual skill 的 fetch.py 下载
    """
    name = "cache"

    SKILL_DIR = os.path.expanduser("~/.codex/skills/cninfo-annual/scripts")
    ANNUAL_DIR = os.path.expanduser("~/企业年报")
    PLAYWRIGHT_PATH = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")

    def __init__(self):
        self.skill_script = os.path.join(self.SKILL_DIR, "fetch.py")

    @staticmethod
    def code6(ts_code: str) -> str:
        c = ts_code.upper().strip()
        if c.endswith(".SH") or c.endswith(".SZ") or c.endswith(".BJ"):
            return c[:6]
        if len(c) == 6 and c.isdigit():
            return c
        raise ValueError(f"无法识别的股票代码: {ts_code}")

    def get_annual_report_text(self, ts_code: str, report_year: str) -> dict:
        code6 = self.code6(ts_code)
        target = os.path.join(self.ANNUAL_DIR, code6)
        json_path = os.path.join(target, f"{report_year}_{code6}_annual_sections.json")
        pdf_path = os.path.join(target, f"{report_year}_{code6}_annual_report.pdf")

        if not os.path.exists(json_path):
            self._download(code6, report_year)
            if not os.path.exists(json_path):
                raise RuntimeError(f"年报下载后仍不可得: {ts_code} {report_year}")

        with open(json_path, "r", encoding="utf-8") as f:
            sec_data = json.load(f)

        full_text = ""
        if os.path.exists(pdf_path):
            try:
                import pdfplumber
                with pdfplumber.open(pdf_path) as pdf:
                    full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            except Exception:
                pass

        key_map = {
            "management_discussion": "经营情况讨论与分析",
            "core_competitiveness": "核心竞争力分析",
            "future_risks": "可能面对的风险",
            "corporate_governance": "公司治理",
            "shareholder_info": "股份变动及股东情况",
        }
        sections = {}
        for eng, chn in key_map.items():
            txt = sec_data.get(eng, "")
            if txt:
                sections[chn] = txt
        if not sections and len(full_text.strip()) >= 1000:
            sections["全文"] = full_text
        sections = {
            name: text for name, text in sections.items()
            if isinstance(text, str) and len(text.strip()) >= 200
        }
        if not sections:
            raise RuntimeError(f"缓存年报只有元数据或占位文本，正文不可用: {ts_code} {report_year}")

        return {
            "ts_code": ts_code,
            "report_year": report_year,
            "reports": {
                "annual": {
                    # 缓存文件没有可靠公告日时保持空值，禁止伪造日期。
                    "ann_date": "",
                    "title": f"{report_year}年年度报告",
                    "source_url": f"file://{pdf_path}" if os.path.exists(pdf_path) else "",
                    "full_text": full_text,
                    "sections": sections,
                }
            },
        }

    def _download(self, code6: str, report_year: str):
        if not os.path.exists(self.skill_script):
            logger.warning(f"cninfo-annual skill 脚本未找到: {self.skill_script}")
            return
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = self.PLAYWRIGHT_PATH
        try:
            r = subprocess.run(
                [sys.executable, self.skill_script, code6, "--years", report_year, "--force"],
                capture_output=True, text=True, timeout=120, env=env,
            )
            if r.returncode != 0:
                logger.warning(f"cninfo-annual 下载失败: {r.stderr[:500]}")
        except Exception as e:
            logger.warning(f"cninfo-annual 执行异常: {e}")

    def get_stock_basic(self, ts_code): raise NotImplementedError
    def get_all_stocks(self): raise NotImplementedError
    def get_daily_quotes(self, ts_code, start, end): raise NotImplementedError
    def get_daily_basic(self, ts_code, start, end): raise NotImplementedError
    def get_income(self, ts_code, start, end): raise NotImplementedError
    def get_balance(self, ts_code, start, end): raise NotImplementedError
    def get_cashflow(self, ts_code, start, end): raise NotImplementedError
    def get_fina_indicator(self, ts_code, start, end): raise NotImplementedError
    def get_fina_audit(self, ts_code, start, end): raise NotImplementedError
    def get_forecast(self, ts_code, start, end): raise NotImplementedError
    def get_macro_data(self): raise NotImplementedError


class FallbackDataSource(DataSource):
    """先尝试主源，失败或返回空时自动切换到备用源。"""

    name = "fallback"

    def __init__(self, primary: DataSource, fallback: Optional[DataSource] = None,
                 cache: Optional[DataSource] = None):
        self.primary = primary
        self.fallback = fallback
        self.cache = cache

    def _fetch(self, method: str, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            df = getattr(self.primary, method)(ts_code, start_date, end_date)
            if not df.empty:
                logger.info(f"[{method}] 主源 {self.primary.name} 成功，返回 {len(df)} 行")
                return df
            logger.warning(f"[{method}] 主源 {self.primary.name} 返回空，尝试备用源")
        except Exception as e:
            logger.warning(f"[{method}] 主源 {self.primary.name} 失败: {e}")

        if self.fallback is None:
            raise RuntimeError(f"[{method}] 主源失败且未配置备用源")

        try:
            df = getattr(self.fallback, method)(ts_code, start_date, end_date)
            if not df.empty:
                logger.info(f"[{method}] 备用源 {self.fallback.name} 成功，返回 {len(df)} 行")
                return df
            raise RuntimeError(f"[{method}] 备用源 {self.fallback.name} 也返回空")
        except Exception as e:
            raise RuntimeError(f"[{method}] 备用源 {self.fallback.name} 失败: {e}")

    def _fetch_no_dates(self, method: str, ts_code: str) -> pd.DataFrame:
        try:
            df = getattr(self.primary, method)(ts_code)
            if not df.empty:
                logger.info(f"[{method}] 主源 {self.primary.name} 成功，返回 {len(df)} 行")
                return df
            logger.warning(f"[{method}] 主源 {self.primary.name} 返回空，尝试备用源")
        except Exception as e:
            logger.warning(f"[{method}] 主源 {self.primary.name} 失败: {e}")

        if self.fallback is None:
            raise RuntimeError(f"[{method}] 主源失败且未配置备用源")

        try:
            df = getattr(self.fallback, method)(ts_code)
            if not df.empty:
                logger.info(f"[{method}] 备用源 {self.fallback.name} 成功，返回 {len(df)} 行")
                return df
            raise RuntimeError(f"[{method}] 备用源 {self.fallback.name} 也返回空")
        except Exception as e:
            raise RuntimeError(f"[{method}] 备用源 {self.fallback.name} 失败: {e}")

    def _fetch_no_args(self, method: str) -> pd.DataFrame:
        """用于不需要参数的方法，如 get_all_stocks。"""
        try:
            df = getattr(self.primary, method)()
            if not df.empty:
                logger.info(f"[{method}] 主源 {self.primary.name} 成功，返回 {len(df)} 行")
                return df
            logger.warning(f"[{method}] 主源 {self.primary.name} 返回空，尝试备用源")
        except Exception as e:
            logger.warning(f"[{method}] 主源 {self.primary.name} 失败: {e}")

        if self.fallback is None:
            raise RuntimeError(f"[{method}] 主源失败且未配置备用源")

        try:
            df = getattr(self.fallback, method)()
            if not df.empty:
                logger.info(f"[{method}] 备用源 {self.fallback.name} 成功，返回 {len(df)} 行")
                return df
            raise RuntimeError(f"[{method}] 备用源 {self.fallback.name} 也返回空")
        except Exception as e:
            raise RuntimeError(f"[{method}] 备用源 {self.fallback.name} 失败: {e}")

    def get_stock_basic(self, ts_code: str) -> pd.DataFrame:
        return self._fetch_no_dates("get_stock_basic", ts_code)

    def get_all_stocks(self) -> pd.DataFrame:
        return self._fetch_no_args("get_all_stocks")

    def get_daily_quotes(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._fetch("get_daily_quotes", ts_code, start_date, end_date)

    def get_daily_basic(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._fetch("get_daily_basic", ts_code, start_date, end_date)

    def get_income(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._fetch("get_income", ts_code, start_date, end_date)

    def get_balance(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._fetch("get_balance", ts_code, start_date, end_date)

    def get_cashflow(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._fetch("get_cashflow", ts_code, start_date, end_date)

    def get_fina_indicator(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._fetch("get_fina_indicator", ts_code, start_date, end_date)

    def get_fina_audit(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._fetch("get_fina_audit", ts_code, start_date, end_date)

    def get_forecast(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._fetch("get_forecast", ts_code, start_date, end_date)

    def get_macro_data(self) -> dict:
        """宏观数据：先主源后备用源。单源失败不抛异常。"""
        try:
            result = self.primary.get_macro_data()
            if result and result.get("indicators"):
                return result
        except Exception as e:
            logger.warning(f"[get_macro_data] 主源 {self.primary.name} 失败: {e}")

        if self.fallback is not None:
            try:
                result = self.fallback.get_macro_data()
                if result and result.get("indicators"):
                    logger.info(f"[get_macro_data] 备用源 {self.fallback.name} 成功")
                    return result
            except Exception as e:
                logger.warning(f"[get_macro_data] 备用源 {self.fallback.name} 失败: {e}")

        # 两个源都失败，返回空结果
        return {"update_date": "", "source": "none", "indicators": {}, "errors": ["所有数据源均失败"]}

    def get_annual_report_text(self, ts_code: str, report_year: str) -> dict:
        """年报全文抓取：主源→备用源→缓存源（三源依次回退）。"""
        try:
            result = self.primary.get_annual_report_text(ts_code, report_year)
            if result and result.get("reports"):
                logger.info(f"[get_annual_report_text] 主源 {self.primary.name} 成功")
                return result
        except Exception as e:
            logger.warning(f"[get_annual_report_text] 主源 {self.primary.name} 失败: {e}")

        if self.fallback is not None:
            try:
                result = self.fallback.get_annual_report_text(ts_code, report_year)
                if result and result.get("reports"):
                    logger.info(f"[get_annual_report_text] 备用源 {self.fallback.name} 成功")
                    return result
            except Exception as e:
                logger.warning(f"[get_annual_report_text] 备用源 {self.fallback.name} 失败: {e}")

        if self.cache is not None:
            try:
                result = self.cache.get_annual_report_text(ts_code, report_year)
                if result and result.get("reports"):
                    logger.info(f"[get_annual_report_text] 缓存源 {self.cache.name} 成功")
                    return result
            except Exception as e:
                logger.warning(f"[get_annual_report_text] 缓存源 {self.cache.name} 失败: {e}")

        raise RuntimeError(f"[get_annual_report_text] 所有数据源均失败: {ts_code} {report_year}")


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def create_data_source(config: dict) -> DataSource:
    """根据配置创建数据源。"""
    ds_config = config.get("data_sources", {})
    primary_name = "tushare"
    fallback_name = None

    # 找到主源
    for name, cfg in ds_config.items():
        if cfg.get("primary"):
            primary_name = name
        if cfg.get("fallback"):
            fallback_name = name

    def _build(name: Optional[str]) -> Optional[DataSource]:
        if not name:
            return None
        try:
            if name == "tushare":
                cfg = ds_config.get("tushare", {})
                token = os.environ.get(cfg.get("token_env", "TUSHARE_TOKEN"))
                return TushareDataSource(token=token)
            if name == "akshare":
                return AKShareDataSource()
            raise ValueError(f"未知数据源: {name}")
        except Exception as exc:
            logger.warning(f"[create_data_source] {name} 初始化失败: {exc}")
            return None

    primary = _build(primary_name)
    fallback = _build(fallback_name)
    if primary is None and fallback is not None:
        logger.warning(f"[create_data_source] 主源不可用，改用 {fallback.name} 作为唯一数据源")
        primary, fallback = fallback, None
    if primary is None:
        raise RuntimeError("没有可用数据源：主源与备用源均初始化失败")

    cache = None
    cache_script = os.path.expanduser("~/.codex/skills/cninfo-annual/scripts/fetch.py")
    if os.path.exists(cache_script):
        try:
            cache = CacheDataSource()
            logger.info("[create_data_source] CacheDataSource 初始化成功")
        except Exception as e:
            logger.warning(f"[create_data_source] CacheDataSource 初始化失败: {e}")
    if fallback or cache:
        return FallbackDataSource(primary=primary, fallback=fallback, cache=cache)
    return primary
