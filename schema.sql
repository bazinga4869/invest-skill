-- ============================================================
-- invest-wiki 本地投研数据库 Schema (SQLite)
-- 用途：支撑“未来产业每日筛选计划”的量化分析与回溯
-- 维护：Hermes / Claude Code
-- 更新策略：增量更新；重大 schema 变更需导出快照后重建
-- ============================================================

-- 1. 股票基础信息
CREATE TABLE IF NOT EXISTS stocks (
    ts_code TEXT PRIMARY KEY,            -- Tushare 代码，如 000001.SZ
    symbol TEXT NOT NULL,                -- 纯代码，如 000001
    name TEXT NOT NULL,                  -- 股票简称
    fullname TEXT,                       -- 全称
    exchange TEXT,                       -- SSE/SZSE/BSE
    list_date TEXT,                      -- 上市日期 YYYY-MM-DD
    delist_date TEXT,                    -- 退市日期
    industry_sw TEXT,                    -- 申万行业
    industry_citics TEXT,                -- 中信行业
    area TEXT,                           -- 地区
    company_type TEXT,                   -- 公司类型
    intro TEXT,                          -- 公司简介
    updated_at TEXT NOT NULL             -- 更新时间
);

CREATE INDEX IF NOT EXISTS idx_stocks_symbol ON stocks(symbol);
CREATE INDEX IF NOT EXISTS idx_stocks_industry ON stocks(industry_sw);

-- 2. 板块/概念定义
CREATE TABLE IF NOT EXISTS sectors (
    sector_code TEXT PRIMARY KEY,        -- 板块代码
    name TEXT NOT NULL,                  -- 板块名称
    category TEXT NOT NULL,              -- future / strategic / infrastructure
    sub_category TEXT,                   -- 如 量子科技、AI算力
    source TEXT NOT NULL,                -- tushare / akshare / manual
    description TEXT,
    policy_ref TEXT,                     -- 关联政策文件/ wiki 页面
    updated_at TEXT NOT NULL
);

-- 3. 股票-板块映射（多对多）
CREATE TABLE IF NOT EXISTS stock_sectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    weight REAL DEFAULT 1.0,             -- 相关度权重，1=核心，0.5=沾边
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code, sector_code),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code),
    FOREIGN KEY (sector_code) REFERENCES sectors(sector_code)
);

CREATE INDEX IF NOT EXISTS idx_stock_sectors_code ON stock_sectors(ts_code);
CREATE INDEX IF NOT EXISTS idx_stock_sectors_sector ON stock_sectors(sector_code);

-- 4. 日线行情（核心字段；完整 OHLCV 可另存 parquet）
CREATE TABLE IF NOT EXISTS daily_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    pre_close REAL,
    change REAL,
    pct_chg REAL,
    vol REAL,
    amount REAL,
    adj_factor REAL,                     -- 复权因子
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code, trade_date),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code)
);

CREATE INDEX IF NOT EXISTS idx_quotes_code_date ON daily_quotes(ts_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_quotes_date ON daily_quotes(trade_date);

-- 5. 每日估值指标
CREATE TABLE IF NOT EXISTS daily_basic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    close REAL,
    turnover_rate REAL,
    turnover_rate_f REAL,
    volume_ratio REAL,
    pe_ttm REAL,
    pe REAL,
    pb REAL,
    ps_ttm REAL,
    ps REAL,
    dv_ratio REAL,                       -- 股息率
    total_mv REAL,                       -- 总市值（万元）
    circ_mv REAL,                        -- 流通市值（万元）
    total_share REAL,
    float_share REAL,
    free_share REAL,
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code, trade_date),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code)
);

CREATE INDEX IF NOT EXISTS idx_basic_code_date ON daily_basic(ts_code, trade_date);

-- 6. 利润表（按报告期）
CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    ann_date TEXT,
    f_ann_date TEXT,
    end_date TEXT NOT NULL,              -- 报告期 YYYY-MM-DD
    report_type TEXT,                    -- 1=合并报表
    comp_type TEXT,
    total_revenue REAL,                  -- 营业总收入
    revenue REAL,                        -- 营业收入
    total_cogs REAL,
    sell_exp REAL,
    admin_exp REAL,
    fin_exp REAL,
    rd_exp REAL,
    operate_profit REAL,
    non_oper_income REAL,
    total_profit REAL,
    n_income REAL,                       -- 净利润
    n_income_attr_p REAL,                -- 归母净利润
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code, end_date, report_type),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code)
);

CREATE INDEX IF NOT EXISTS idx_income_code_date ON income(ts_code, end_date);

-- 7. 资产负债表
CREATE TABLE IF NOT EXISTS balance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    ann_date TEXT,
    f_ann_date TEXT,
    end_date TEXT NOT NULL,
    report_type TEXT,
    total_assets REAL,
    total_liab REAL,
    total_hldr_eqy_exc_min_int REAL,     -- 归母权益
    total_hldr_eqy_inc_min_int REAL,
    money_cap REAL,                      -- 货币资金
    trad_asset REAL,
    notes_receiv REAL,
    accounts_receiv REAL,                -- 应收账款
    inventories REAL,
    goodwill REAL,
    intan_assets REAL,
    fix_assets REAL,
    total_nca REAL,
    st_borr REAL,                        -- 短期借款
    lt_borr REAL,                        -- 长期借款
    bonds_payable REAL,                  -- 应付债券
    total_cur_liab REAL,
    total_noncur_liab REAL,
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code, end_date, report_type),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code)
);

CREATE INDEX IF NOT EXISTS idx_balance_code_date ON balance(ts_code, end_date);

-- 8. 现金流量表
CREATE TABLE IF NOT EXISTS cashflow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    ann_date TEXT,
    f_ann_date TEXT,
    end_date TEXT NOT NULL,
    report_type TEXT,
    c_cash_equ_end_period REAL,          -- 期末现金
    n_cashflow_act REAL,                 -- 经营活动现金流净额
    n_cashflow_inv_act REAL,             -- 投资活动现金流净额
    n_cash_flows_fnc_act REAL,           -- 筹资活动现金流净额
    free_cash_flow REAL,                 -- 自由现金流（可自定义计算）
    im_net_cashflow_oper_act REAL,
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code, end_date, report_type),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code)
);

CREATE INDEX IF NOT EXISTS idx_cashflow_code_date ON cashflow(ts_code, end_date);

-- 9. 财务指标（Tushare fina_indicator + 自定义）
CREATE TABLE IF NOT EXISTS fina_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    ann_date TEXT,
    end_date TEXT NOT NULL,
    roe REAL,
    roe_waa REAL,
    roe_dt REAL,
    roic REAL,
    grossprofit_margin REAL,
    netprofit_margin REAL,
    op_yoy REAL,                         -- 营业利润同比
    netprofit_yoy REAL,                  -- 净利润同比
    tr_yoy REAL,                         -- 营收同比
    or_yoy REAL,
    assets_yoy REAL,
    equity_yoy REAL,
    debt_to_assets REAL,
    current_ratio REAL,
    quick_ratio REAL,
    cash_ratio REAL,
    inv_turn REAL,
    ar_turn REAL,
    assets_turn REAL,
    ocf_to_profit REAL,                  -- 经营现金流/净利润
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code, end_date),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code)
);

CREATE INDEX IF NOT EXISTS idx_fina_code_date ON fina_indicators(ts_code, end_date);

-- 10. 审计意见
CREATE TABLE IF NOT EXISTS fina_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    ann_date TEXT,
    end_date TEXT NOT NULL,
    audit_agency TEXT,
    sign_agency TEXT,
    audit_sign REAL,
    opinion_type TEXT,                   -- 标准无保留/保留/否定/无法表示
    audit_costs REAL,
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code, end_date),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code)
);

-- 11. 每日筛选结果
CREATE TABLE IF NOT EXISTS screen_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    sector_code TEXT,
    tier TEXT,                           -- Tier1/Tier2/Tier3
    score_total REAL,                    -- 综合得分
    r1_ocf_profit INTEGER,               -- 0=通过, 1=不通过
    r2_ar_revenue INTEGER,
    r3_debt_cash INTEGER,
    r4_goodwill INTEGER,
    r5_audit INTEGER,
    r6_ocf_pos INTEGER,
    g1_graham REAL,                      -- P/G
    g2_ey_spread REAL,                   -- EY/国债收益率
    g3_profit_streak INTEGER,
    f1_rev_cagr REAL,
    f2_profit_cagr REAL,
    m1_roe_avg REAL,
    m2_roic REAL,
    m3_gm REAL,
    v1_pe_ttm REAL,
    v2_pb REAL,
    result TEXT NOT NULL,                -- PASS / WATCH / CANDIDATE
    reason TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code, trade_date),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code)
);

CREATE INDEX IF NOT EXISTS idx_screen_date ON screen_results(trade_date);
CREATE INDEX IF NOT EXISTS idx_screen_result ON screen_results(trade_date, result);

-- 12. 分析队列
CREATE TABLE IF NOT EXISTS analysis_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    scheduled_date TEXT,                 -- 计划分析日期
    analyzed_date TEXT,                  -- 实际分析日期
    status TEXT NOT NULL DEFAULT 'pending', -- pending / screened / analyzed / archived
    report_path TEXT,                    -- 生成报告路径
    notes TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code),
    FOREIGN KEY (sector_code) REFERENCES sectors(sector_code)
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON analysis_queue(status);

-- 13. 候选池跟踪
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    first_screen_date TEXT NOT NULL,
    latest_screen_date TEXT,
    rating TEXT,                         -- TRACKING / OBSERVE / BUY / PASS
    moat_score INTEGER,                  -- 0~5
    valuation_score INTEGER,
    risk_score INTEGER,
    report_path TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(ts_code),
    FOREIGN KEY (ts_code) REFERENCES stocks(ts_code)
);

-- 14. 宏无风险利率（用于 Graham Number）
CREATE TABLE IF NOT EXISTS macro_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    rate_type TEXT NOT NULL,             -- cn_10y_bond / us_10y_bond
    rate REAL NOT NULL,
    source TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(date, rate_type)
);
