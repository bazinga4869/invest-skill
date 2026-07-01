#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源抽象层：Tushare 为主，AKShare 为备用源。

设计原则：
1. 所有外部数据接口统一通过 DataSource 子类实现
2. FallbackDataSource 先尝试主源，失败或数据缺失时自动切换到备用源
3. 返回的 DataFrame 列名尽量与 Tushare 保持一致，便于下游统一处理
"""

import os
import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
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
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return ""
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
            raise RuntimeError("Tushare token 未提供，且环境变量 TUSHARE_TOKEN 未设置")
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
        return self._safe_call(self.pro.balance, ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)

    def get_cashflow(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        fields = ("ts_code,ann_date,f_ann_date,end_date,report_type,c_cash_equ_end_period,n_cashflow_act,"
                  "n_cashflow_inv_act,n_cash_flows_fnc_act,free_cash_flow")
        return self._safe_call(self.pro.cashflow, ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)

    def get_fina_indicator(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        fields = ("ts_code,ann_date,end_date,roe,roe_waa,roe_dt,roic,grossprofit_margin,netprofit_margin,"
                  "op_yoy,netprofit_yoy,tr_yoy,or_yoy,assets_yoy,equity_yoy,debt_to_assets,current_ratio,"
                  "quick_ratio,cash_ratio,ocf_to_profit")
        return self._safe_call(self.pro.fina_indicator, ts_code=ts_code, start_date=start_date, end_date=end_date, fields=fields)

    def get_fina_audit(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._safe_call(self.pro.fina_audit, ts_code=ts_code, start_date=start_date, end_date=end_date)


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

        # stock_individual_info_em 返回 key-value 形式
        info = dict(zip(df["item"].astype(str), df["value"]))
        return pd.DataFrame([{
            "ts_code": ts_code,
            "symbol": symbol,
            "name": info.get("股票简称", ""),
            "fullname": info.get("公司名称", ""),
            "exchange": code_to_exchange(ts_code),
            "list_date": info.get("上市时间", ""),
            "delist_date": "",
            "industry": info.get("行业", ""),
            "area": info.get("地域", "")
        }])

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
        try:
            df = self.ak.stock_zh_a_spot_em()
        except Exception as e:
            logger.warning(f"AKShare spot 获取失败: {e}")
            return pd.DataFrame()

        df = df[df["代码"] == symbol]
        if df.empty:
            return pd.DataFrame()

        row = df.iloc[0]
        today = datetime.now().strftime("%Y%m%d")

        # AKShare spot 列：代码，名称，最新价，涨跌幅，涨跌额，成交量，成交额，振幅，最高，最低，今开，昨收，量比，换手率，市盈率-动态，市净率，总市值，流通市值，涨速，5分钟涨跌，60日涨跌幅，年初至今涨跌幅
        def to_float(x, default=None):
            try:
                return float(str(x).replace(",", ""))
            except (ValueError, TypeError):
                return default

        result = pd.DataFrame([{
            "ts_code": ts_code,
            "trade_date": today,
            "close": to_float(row.get("最新价")),
            "turnover_rate": to_float(row.get("换手率")),
            "turnover_rate_f": None,
            "volume_ratio": to_float(row.get("量比")),
            "pe": to_float(row.get("市盈率-动态")),
            "pe_ttm": to_float(row.get("市盈率-动态")),
            "pb": to_float(row.get("市净率")),
            "ps": None,
            "ps_ttm": None,
            "dv_ratio": None,
            "total_mv": to_float(row.get("总市值")),
            "circ_mv": to_float(row.get("流通市值")),
            "total_share": None,
            "float_share": None,
            "free_share": None
        }])
        return result

    def _get_financial_report_sina(self, ts_code: str, report_type: str, start_date: str, end_date: str) -> pd.DataFrame:
        """通用财务报表获取（AKShare 备用）。report_type: 资产负债表/利润表/现金流量表"""
        symbol = self._symbol(ts_code)
        try:
            df = self.ak.stock_financial_report_sina(stock=symbol, symbol=report_type)
        except Exception as e:
            logger.warning(f"AKShare {report_type} 获取失败: {e}")
            return pd.DataFrame()

        if df.empty:
            return df

        # AKShare 返回列名可能包含日期（如 '2022-12-31'），第一列通常是项目/科目
        # 我们需要把列名转置：把日期列变成 end_date 行
        first_col = df.columns[0]
        id_vars = [first_col]
        date_cols = [c for c in df.columns[1:] if isinstance(c, str) and len(c.replace("-", "")) == 8]

        if not date_cols:
            return pd.DataFrame()

        melted = df.melt(id_vars=id_vars, value_vars=date_cols, var_name="end_date", value_name="value")
        melted["end_date"] = melted["end_date"].apply(normalize_date_hyphen)
        # 透视：每个科目一行日期，每个日期一行
        pivot = melted.pivot_table(index="end_date", columns=first_col, values="value", aggfunc="first").reset_index()
        pivot.columns.name = None
        pivot = pivot.rename_axis(None, axis=1)

        # 过滤日期范围
        pivot = pivot[(pivot["end_date"] >= normalize_date_hyphen(start_date)) &
                      (pivot["end_date"] <= normalize_date_hyphen(end_date))]
        pivot["ts_code"] = ts_code
        pivot["ann_date"] = ""
        pivot["f_ann_date"] = ""
        pivot["report_type"] = ""
        return pivot

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
            "五、现金及现金等价物净增加额": "free_cash_flow",
        }
        for cn, en in col_map.items():
            if cn in df.columns:
                df[en] = pd.to_numeric(df[cn].astype(str).str.replace(",", ""), errors="coerce")
        return df

    def get_fina_indicator(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = self._symbol(ts_code)
        try:
            df = self.ak.stock_financial_analysis_indicator(symbol=symbol)
        except Exception as e:
            logger.warning(f"AKShare 财务指标获取失败: {e}")
            return pd.DataFrame()

        if df.empty:
            return df

        # AKShare 返回列名通常是报告期，第一列是指标名称
        # 格式类似 Tushare fina_indicator，但列名可能是日期
        first_col = df.columns[0]
        date_cols = [c for c in df.columns[1:] if isinstance(c, str) and len(c.replace("-", "")) == 8]
        if not date_cols:
            return pd.DataFrame()

        melted = df.melt(id_vars=[first_col], value_vars=date_cols, var_name="end_date", value_name="value")
        melted["end_date"] = melted["end_date"].apply(normalize_date_hyphen)
        pivot = melted.pivot_table(index="end_date", columns=first_col, values="value", aggfunc="first").reset_index()
        pivot.columns.name = None
        pivot = pivot.rename_axis(None, axis=1)
        pivot = pivot[(pivot["end_date"] >= normalize_date_hyphen(start_date)) &
                      (pivot["end_date"] <= normalize_date_hyphen(end_date))]
        pivot["ts_code"] = ts_code
        pivot["ann_date"] = ""

        # 常见指标映射
        col_map = {
            "净资产收益率": "roe",
            "净资产收益率(扣除非经常性损益)": "roe_dt",
            "加权平均净资产收益率": "roe_waa",
            "投入资本回报率": "roic",
            "销售毛利率": "grossprofit_margin",
            "销售净利率": "netprofit_margin",
            "营业利润率": None,
            "营业收入同比增长率": "tr_yoy",
            "净利润同比增长率": "netprofit_yoy",
            "营业利润同比增长率": "op_yoy",
            "总资产同比增长率": "assets_yoy",
            "净资产同比增长率": "equity_yoy",
            "资产负债率": "debt_to_assets",
            "流动比率": "current_ratio",
            "速动比率": "quick_ratio",
            "现金比率": "cash_ratio",
            "每股经营现金流": "ocf_to_profit",
        }
        for cn, en in col_map.items():
            if en and cn in pivot.columns:
                pivot[en] = pd.to_numeric(pivot[cn].astype(str).str.replace(",", "").str.replace("%", ""), errors="coerce")
                # 百分比可能需要除以 100
                if en in ["roe", "roe_dt", "roe_waa", "roic", "grossprofit_margin", "netprofit_margin",
                          "tr_yoy", "netprofit_yoy", "op_yoy", "assets_yoy", "equity_yoy", "debt_to_assets"]:
                    pivot[en] = pivot[en] / 100.0
        return pivot

    def get_fina_audit(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        # AKShare 暂无标准审计意见接口，返回空
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# 自动回退数据源
# ---------------------------------------------------------------------------

class FallbackDataSource(DataSource):
    """先尝试主源，失败或返回空时自动切换到备用源。"""

    name = "fallback"

    def __init__(self, primary: DataSource, fallback: Optional[DataSource] = None):
        self.primary = primary
        self.fallback = fallback

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

    def get_stock_basic(self, ts_code: str) -> pd.DataFrame:
        return self._fetch_no_dates("get_stock_basic", ts_code)

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

    primary = None
    fallback = None

    if primary_name == "tushare":
        token = os.environ.get(ds_config["tushare"]["token_env"])
        primary = TushareDataSource(token=token)
    elif primary_name == "akshare":
        primary = AKShareDataSource()

    if fallback_name == "tushare":
        token = os.environ.get(ds_config["tushare"]["token_env"])
        fallback = TushareDataSource(token=token)
    elif fallback_name == "akshare":
        fallback = AKShareDataSource()

    if fallback:
        return FallbackDataSource(primary=primary, fallback=fallback)
    return primary
