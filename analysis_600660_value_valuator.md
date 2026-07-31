---
expert_id: "value-valuator"
ts_code: "600660.SH"
data_date: "20260731"
analysis_date: "20260801"
batch_id: "0fb7f7a6f85748304a0cd5fb"
score: 48
verdict: WARN
conclusion_direction: NEUTRAL
veto_triggers: []
---

# 02-价值估值师评估 — 福耀玻璃（600660.SH）

## 总体判断

福耀玻璃是一家质地优秀的公司——连续 10 年盈利、ROE 从 12% 爬升至 25%、毛利率从周期底部回升、盈利收益率远超无风险利率。但从格雷厄姆框架看，当前 59.70 元的股价已大幅透支其账面价值所能支撑的安全边际：Graham Number 仅 33.99 元，比率 0.569 落入「高估」区间。FCF-DCF 基准情景内在价值 31.73 元，当前价格与之相比几乎翻倍。即便用更宽松的盈利 DCF，价格也仅处于悲观与基准情景之间。**结论：好公司，但价格不够便宜。** 没有触发 VETO 否决条件，但安全边际不足，需依赖其他专家（护城河、成长质量）提供更强的溢价理由。

## 详细分析

### 一、Graham Number：核心锚点，亮黄灯

Graham Number 是格雷厄姆防御型投资者的核心底线指标。计算过程：

- EPS（2025 全年）= 归母净利润 / 总股本 = 93.12 亿 / 26.0974 亿股 = 3.568 元/股 [calc: 93.12/26.0974; inputs: annual.annual_data[9].net_profit_yi, market.total_shares_yi]
- BVPS（2025 年末）= 归母权益 / 总股本 = 375.56 亿 / 26.0974 亿股 = 14.391 元/股 [calc: 375.56/26.0974; inputs: balance.equity_yi, market.total_shares_yi]
- Graham Number = √(22.5 × 3.568 × 14.391) = 33.99 元 [calc: sqrt(22.5*3.568*14.391); inputs: annual.annual_data[9].net_profit_yi, balance.equity_yi, market.total_shares_yi]
- Graham 比率 = 33.99 / 59.70 = 0.569 [calc: 33.99/59.70; inputs: annual.annual_data[9].net_profit_yi, balance.equity_yi, market.total_shares_yi, market.close]

| 区间 | 判定 | 当前状态 |
|------|------|---------|
| ≥ 1.5 | 极度低估 | — |
| 1.0 ~ 1.5 | 低估 | — |
| 0.67 ~ 1.0 | 合理偏贵 | — |
| **0.5 ~ 0.67** | **高估** | **◀ 0.569 在此** |
| < 0.5 | ⛔ 极度高估 VETO | — |

0.569 距离 0.5 的 VETO 线只有 13.8% 的空间。这意味着如果 EPS 或 BVPS 略微收缩（例如行业周期下行、原材料涨价侵蚀利润），Graham 比率就可能跌入否决区。这不是一个可以安睡的估值水平。

关于 Graham Number 常数 22.5 的 A 股修正：22.5 = 15（PE 上限）× 1.5（PB 上限），隐含无风险利率约 6.67%。当前中国 10 年期国债收益率约 1.7% [assumption: 基于 Shibor 1 周 1.453% 加合理期限利差估算，数据未直接提供]，若按同等逻辑上调 PE 上限至 1/0.017 ≈ 58.8 倍（盈利收益率 = 2× 无风险利率 → 1/0.034 = 29.4），修正后的 Graham 乘数将远超 22.5。但这个方法论上的修正会使 Graham Number 大幅膨胀，暂时保留标准公式以保持保守性。若后续查阅 [[框架A股适用性修正]] 页面，可按修正后常数重新计算。

### 二、盈利收益率 vs 无风险利率：最强绿灯

- 盈利收益率 = 1 / PE_TTM = 1 / 17.3226 = 5.773% [calc: 1/17.3226*100; inputs: market.pe_ttm]
- 无风险利率（Shibor 1 周）= 1.453% [source: macro.indicators.shibor.week_pct]
- 比率 = 5.773% / 1.453% = 3.97× [calc: (1/17.3226*100)/1.453; inputs: market.pe_ttm, macro.indicators.shibor.week_pct]

即使以更合理的 10 年期国债约 1.7% [assumption: Shibor 是隔夜/短期利率，中国 10 年期国债约 1.7% 为分析师估计，非数据源提供] 计算，比率仍达 3.40×，远超 2× 的 PASS 门槛。股票提供的盈利回报是国债的近 4 倍，从大类资产配置角度，福耀玻璃的盈利产出明显优于固定收益。

这是本次评估中最强的正面信号，也是 Graham 框架下不会被否决的根本原因。

### 三、PE 历史分位：数据不可得

原始数据仅提供当前 PE_TTM = 17.32 [source: market.pe_ttm]，未提供历史 PE 序列或分位数据。无法判断当前 PE 处于近 5 年的什么位置。从绝对水平看，17.3× PE 对于一家 ROE 25%、5 年利润 CAGR 29% 的公司而言，在 A 股市场不算昂贵，但没有历史分位佐证意味着「均值回归」方向的判断缺乏锚点。此条检查标记为数据缺口，结论降级。

### 四、清算价值底线：无资产保护

净流动资产价值（NCAV）的精确计算需要流动资产与流动负债的分项数据。当前数据仅提供：

- 流动资产部分子项：货币资金 192.74 亿 [source: balance.cash_yi] + 应收账款 84.78 亿 [source: balance.accounts_receiv_yi] + 存货 67.99 亿 [source: balance.inventories_yi] = 345.51 亿
- 流动比率 = 1.539 [source: indicators.indicators[0].current_ratio]
- 总负债 = 总资产 × 资产负债率 = 700.62 × 46.40% = 325.10 亿 [calc: 700.62*0.464018; inputs: balance.total_assets_yi, indicators.indicators[0].debt_ratio_pct]

保守估计：若流动资产 ≈ 总资产的 50% = 350 亿，则 NCAV = 350 − 325 = 25 亿，每股 NCAV ≈ 0.96 元。乐观估计（流动资产 = 流动负债 × 1.539 且流动负债 = 总负债的 70%）约 6-7 元/股。无论哪种情形，NCAV 均远低于股价 59.70 元 [source: market.close]。

结论：股价完全没有资产清算底线的保护。福耀不是烟蒂股，也不是廉价证券。投资者押注的是持续经营价值（going concern），而非资产兜底。

### 五、PB 合理性：偏高但 ROE 提供支撑

- PB = 3.98 [source: market.pb]
- ROE = 25.43% [source: indicators.indicators[0].roe_pct]

PB 3.98 处于方法论定义的「1~3 正常范围」之上。但福耀的 ROE 达到 25.43%，且过去 6 年 ROE 趋势持续改善：12.11% → 13.14% → 17.20% → 18.63% → 22.34% → 25.43% [source: indicators.indicators[5].roe_pct, indicators.indicators[4].roe_pct, indicators.indicators[3].roe_pct, indicators.indicators[2].roe_pct, indicators.indicators[1].roe_pct, indicators.indicators[0].roe_pct]，说明公司运用净资产创造利润的效率在持续提升。

简单校验：若 PB ≈ ROE / COE（可持续增长模型），隐含权益成本 COE = 25.43% / 3.98 ≈ 6.4% [calc: 25.43/3.98; inputs: indicators.indicators[0].roe_pct, market.pb]。在 1.45% 无风险利率环境下，6.4% 的要求回报率意味着风险溢价约 5%，对于一家全球龙头汽车玻璃公司而言并非不合理。

但 PB 已接近 4×，对 ROE 的任何下滑都非常敏感——若 ROE 回到 2021 年的 13% 水平，同样的 PB 将隐含 COE 仅 3.3%，届时估值将显得昂贵。PB 的脆弱性是一个值得警惕的信号。

### 六、连续盈利记录：干净通过

2016–2025 年各年归母净利润（亿）：31.44 → 31.49 → 41.20 → 28.98 → 26.01 → 31.46 → 47.56 → 56.29 → 74.98 → 93.12 [source: annual.annual_data[0].net_profit_yi, annual.annual_data[1].net_profit_yi, annual.annual_data[2].net_profit_yi, annual.annual_data[3].net_profit_yi, annual.annual_data[4].net_profit_yi, annual.annual_data[5].net_profit_yi, annual.annual_data[6].net_profit_yi, annual.annual_data[7].net_profit_yi, annual.annual_data[8].net_profit_yi, annual.annual_data[9].net_profit_yi]

10 年全部盈利，从未亏损。近 3 年（2023–2025）净利润 56.29 → 74.98 → 93.12 亿，稳健增长。完全符合格雷厄姆防御型标准，不触发 VETO。

### 七、DCF 多情景估值：FCF 基准下缺乏安全边际

**关键参数**：FCF_TTM = 经营活动现金流净额 − 资本开支 = 104.04 − 60.70 = 43.34 亿 [calc: 104.04-60.70; inputs: quarterly.ocf_ttm_yi, quarterly.cap_ex_ttm_yi]。总股本 26.10 亿股 [source: market.total_shares_yi]。

| 情景 | FCF 5 年增速 | 永续增长率 | WACC | 每股内在价值 | vs 股价 59.70 |
|------|------------|-----------|------|------------|--------------|
| 悲观 | 2% [assumption: 汽车行业增速放缓至 GDP 水平，福耀份额增长基本结束] | 1% [assumption: 长期通胀接近央行目标] | 10% [assumption: 中国制造业权益资本成本 10% 为合理中枢] | 19.43 | −67.5% |
| 基准 | 7% [assumption: 福耀历史 5 年利润 CAGR 29%，保守取 7% 考虑基数增大与行业成熟化] | 2.5% [assumption: 略高于 CPI 的永续增长，反映全球替换市场] | 9% [assumption: 龙头企业融资成本可略低于行业中枢] | 31.73 | −46.9% |
| 乐观 | 12% [assumption: 高附加值产品渗透加速 + 全球份额持续提升] | 4% [assumption: 智能玻璃 ASP 持续上升驱动长期增长] | 8% [assumption: 龙头确定性溢价压低折现率] | 61.06 | +2.3% |

**DCF 敏感性分析（基准情景单参数 ±10%）**：

| 参数 | −10% 变动后每股价值 | +10% 变动后每股价值 |
|------|-------------------|-------------------|
| 初始 FCF（43.34 亿） | 28.56 | 34.90 |
| 5 年增速（7%） | 27.89 | 36.30 |
| 永续增长率（2.5%） | 28.57 | 36.22 |
| WACC（9%） | 37.34 | 27.39 |

终值对 WACC 和永续增长率高度敏感——终值占基准情景 EV 约 75%，这意味着 DCF 估值结论的稳健性有限。

**当前股价 59.70 元处于什么位置？** 它高于基准 DCF（31.73），接近乐观 DCF（61.06）。按 FCF 口径，市场已经在定价接近乐观情景——即福耀必须实现 12% 的 FCF 增速 + 4% 永续增长 + 8% WACC 的组合，估值才算公允。这个要求不低。

### DCF 的补充视角：盈利 vs 现金流的巨大鸿沟

FCF（43.34 亿）仅为净利润（93.12 亿）的 46.5% [calc: 43.34/93.12*100; inputs: quarterly.fcf_ttm_yi, annual.annual_data[9].net_profit_yi]。差额来自 60.70 亿的资本开支。如果改用净利润做 DCF（近似于假设资本开支全部是增长性投资、维持性资本开支可忽略——一个乐观但未必成立的假设）：

| 情景 | 每股内在价值（盈利 DCF） | vs 股价 59.70 |
|------|----------------------|--------------|
| 悲观 | 41.76 | −30.1% |
| 基准 | 68.17 | +14.2% |
| 乐观 | 131.20 | +119.8% |

盈利 DCF 下，基准情景 68.17 元略高于当前股价，悲观情景 41.76 元低于股价。当前价格大致位于悲观与基准之间偏上的位置。这意味着：如果你相信福耀的资本开支是用于有回报的增长而非维持，那么当前价格有合理的安全边际；如果你对资本开支的效率持怀疑态度，那么 FCF 基准给出的 31.73 元才是更诚实的内在价值。

### 八、多模型交叉验证：模型间分歧显著

| 估值模型 | 核心指标 | 内在价值/参考价 | vs 股价 59.70 | 方向 |
|---------|---------|---------------|-------------|------|
| Graham Number | 33.99 | 33.99 | −43.1% | ⬇ 高估 |
| FCF-DCF（基准） | FCF_TTM 43.34 | 31.73 | −46.9% | ⬇ 高估 |
| 盈利-DCF（基准） | NP 93.12 | 68.17 | +14.2% | ⬆ 低估 |
| PE 盈利收益率 | PE 17.32 | — | 5.77% vs 1.45% | ⬆ 低估 |
| PB-ROE | PB 3.98, ROE 25.4% | — | 中性偏贵 | ➡ 合理偏贵 |

模型间分歧超过 50%：Graham Number（33.99）与盈利-DCF（68.17）相差 100%。FCF-DCF（31.73）与盈利-DCF（68.17）相差 115%。根据方法论，≥ 3 个模型显示高估则 VETO 信号增强——Graham Number、FCF-DCF 两个模型显示高估，PB-ROE 中性偏贵，共 2~3 个模型偏负面。PE 盈利收益率和盈利-DCF 显示正面，共 2 个模型偏正面。模型间严重分歧，标记为模型不确定。

分歧的解释：高资本开支是核心变量。福耀过去一年资本开支占 OCF 的 58% [calc: 60.70/104.04*100; inputs: quarterly.cap_ex_ttm_yi, quarterly.ocf_ttm_yi]，远超典型的制造业维持性水平（通常 20-30%），说明公司处于大规模扩张期。如果这些投资成功转化为未来收入和利润，当前 FCF 低估了真实盈利能力；如果扩张不及预期，FCF 才是真实的现金回报。这个判断超出了本专家的范畴，需要成长质量师和护城河分析师做更深入的判断。

### 九、捡漏 vs 价值陷阱：未触发捡漏框架，但不构成价值陷阱

触发条件检查：前 8 项中需要 ≥ 2 项显示「低估」才启动捡漏深度验证。实际结果：仅盈利收益率（PASS）和盈利-DCF（基准低估）可算作正面信号，但 Graham Number、FCF-DCF 均显示高估，PB 中性偏贵。不满足 ≥ 2 项「低估」的触发门槛，捡漏框架不启动。

尽管如此，福耀明显不是价值陷阱。快速排除：

- ☐ 利润虚胖：OCF_TTM / NP_TTM = 1.12× [calc: 104.04/93.12; inputs: quarterly.ocf_ttm_yi, annual.annual_data[9].net_profit_yi]，现金流覆盖利润 ✓
- ☐ 债务安全：资产负债率 46.40% [source: indicators.indicators[0].debt_ratio_pct]，货币资金 192.74 亿 [source: balance.cash_yi]，有息负债分项数据缺失无法精确计算净现金，但现金充裕
- ☐ 业务存活：汽车玻璃是结构性增长品种（单车玻璃面积和 ASP 持续提升），非技术淘汰行业 ✓
- ☐ 管理层可靠：标准无保留意见 × 3 年 [source: audit.history[0].audit_result, audit.history[1].audit_result, audit.history[2].audit_result]，但大股东质押率数据缺失
- ☐ 有催化剂：高附加值产品占比提升 [年报:2025/annual/管理层讨论与分析]，但需更明确的量化验证

不构成价值陷阱，但当前价格也不构成「捡漏」机会。

### 加分项检查

| 加分项 | 状态 | 说明 |
|--------|------|------|
| 廉价证券筛查 | ❌ 不触发 | 股价 59.70 远超 NCAV 每股不足 7 元 |
| 连续 10 年以上分红 | ❓ 数据缺失 | 股利数据未提供 |
| 邓普顿极度悲观点 | ❌ 不触发 | 福耀 PE 17×、PB 3.98×，远非「第 99 个人放弃」的绝望定价 |
| 降维三变量检查 | ✅ 有价值 | 福耀的企业价值（全球龙头、ROE 25%）和产业趋势（智能玻璃 ASP 提升）是清晰的正面变量。但当前分析确实在「价格是否便宜」的第三变量上纠结——这本质上属于系统性风险水平判断，不应过度关注琐碎的价格波动 |
| 极端斯坦校准 | ⚠️ 需关注 | 汽车行业面临 EV 转型、地缘政治（全球生产基地分布在美/俄/欧/中）、贸易摩擦三重极端斯坦风险。DCF 假设的平滑增长路径可能在任一维度被黑天鹅打断。当前安全边际不足以覆盖极端斯坦事件 |

## 叙事–数据交叉验证

| # | 管理层论述（年报章节+原文摘录） | 对应财务数据字段 | 验证结果 | 证据 |
|---|------------------------------|-----------------|---------|------|
| 1 | 「实现营业收入人民币 3,925,165.73 万元，比上年同期增长 18.37%」（年报:2025/annual/管理层讨论与分析） | annual.annual_data[8].revenue_yi, annual.annual_data[7].revenue_yi | ✅ 可验证 | 392.52 亿 vs 331.61 亿，增长 18.37% [calc: (392.52/331.61-1)*100; inputs: annual.annual_data[8].revenue_yi, annual.annual_data[7].revenue_yi] |
| 2 | 「高附加值产品占比持续提升，占比较上年同期上升 5.02 个百分点」（年报:2025/annual/管理层讨论与分析） | indicators.indicators[1].gross_margin_pct, indicators.indicators[0].gross_margin_pct | ⚠️ 部分可验证 | 毛利率从 36.23% → 37.27% [source: indicators.indicators[1].gross_margin_pct, indicators.indicators[0].gross_margin_pct]，提升 1.04pp。产品结构改善被证实，但 5.02pp 的占比提升仅转化为 1.04pp 的毛利率提升，暗示标准品毛利率可能承压或成本端有抵消 |
| 3 | 「持续加大研发投入」（年报:2024/annual/管理层讨论与分析） | annual.annual_data[6].rd_expense_yi, annual.annual_data[7].rd_expense_yi, annual.annual_data[8].rd_expense_yi, annual.annual_data[9].rd_expense_yi | ✅ 可验证 | 研发费用 12.49 → 14.03 → 16.78 → 19.13 亿，连续 4 年增长 [source: annual.annual_data[6].rd_expense_yi, annual.annual_data[7].rd_expense_yi, annual.annual_data[8].rd_expense_yi, annual.annual_data[9].rd_expense_yi]，但研发费用率稳定在 4.2~4.4% [calc: 19.13/457.87*100; inputs: annual.annual_data[9].rd_expense_yi, annual.annual_data[9].revenue_yi]，与收入同步增长，非超比例投入 |
| 4 | 「毛利率…同比减少 1.87 个百分点，主要为能源和纯碱的价格上涨影响」（年报:2023/annual/管理层讨论与分析） | indicators.indicators[4].gross_margin_pct, indicators.indicators[5].gross_margin_pct | ✅ 可验证 | 2022 年毛利率 34.03% vs 2021 年 35.90% [source: indicators.indicators[4].gross_margin_pct, indicators.indicators[5].gross_margin_pct]，下降 1.87pp，与管理层归因（能源+纯碱）方向一致，属于外部成本冲击而非竞争力下滑 |

> ❓ = 不可验证（愿景/叙事，无法用数据证伪）。❌ = 矛盾。⚠️ = 部分可验证。✅ = 可验证。

**交叉验证发现**：管理层对营收增长的论述与财务数据高度吻合；对产品结构升级的论述方向正确但量化效果被放大——5.02pp 的高附加值占比提升仅转化了 1.04pp 毛利率改善，剩余约 4pp 的提升空间被成本端或其他因素吞噬。管理层坦诚承认了原材料成本的影响（2022 年的纯碱和能源），这在 A 股年报中是比较难得的诚实。整体而言，管理层的文字论述与财务数据的匹配度较高，未发现系统性美化或矛盾。

## 关键风险与不确定性

1. **FCF vs 盈利的巨大鸿沟是本次分析最大的不确定性**。60.70 亿的 TTM 资本开支中，有多少是维持性的、多少是增长性的？如果维持性 capex 占 50%，则「真实 FCF」仅约 13 亿，所有 DCF 估值需下调 60% 以上。数据不支持这个拆分，结论降级。

2. **PE 历史分位数据缺失**。无法判断当前 17.3× PE 在福耀自身历史中处于什么位置。如果历史上福耀常年在 10-15× PE 交易，那么 17× 偏贵；如果历史中枢在 20×，则 17× 合理。缺了这个锚，PE 判断缺乏历史纵深感。

3. **10 年期国债收益率非直接数据**。盈利收益率 vs 无风险利率的比较使用了 Shibor 1 周（1.453%）作为下界代理，并假设 10 年期国债约 1.7%。若实际 10 年期国债显著高于或低于此值，结论的精确度会下降，但方向不变（盈利收益率仍远超 2×）。

4. **Graham Number 常数未做 A 股适应性修正**。标准 22.5 隐含 6.67% 的无风险利率，在 1.7% 的低利率环境中大幅低估了合理 PE。若按 [[框架A股适用性修正]] 调整常数，Graham 比率可能从 0.569 上升至更合理的区间，但该页面内容未经本次注入。

5. **全球运营的地缘政治极端斯坦风险**。福耀在美国、俄罗斯、欧洲均有生产基地，任何一地的贸易政策突变（关税、制裁、供应链脱钩）都可能使 FCF 出现断崖式下跌。DCF 的平滑增长假设在这种环境下不够稳健。

## 必检项执行记录

| 必检项 | 状态 | 证据/来源路径 | 结论 |
|--------|------|---------------|------|
| Graham Number 计算 | DONE | annual.annual_data[9].net_profit_yi + balance.equity_yi + market.total_shares_yi + market.close | Graham Number 33.99，比率 0.569，落入高估区间（0.5-0.67），未触发 VETO |
| 盈利收益率 vs 无风险利率 | DONE | market.pe_ttm + macro.indicators.shibor.week_pct | 盈利收益率 5.77%，无风险利率 1.45%，比率 3.97×，PASS |
| PE 历史分位 | DONE | market.pe_ttm（仅当前值） | 数据不可得——历史 PE 序列缺失，无法计算分位，结论降级 |
| 清算价值底线 | DONE | balance.cash_yi + balance.accounts_receiv_yi + balance.inventories_yi + balance.total_assets_yi + indicators.indicators[0].debt_ratio_pct | NCAV 每股不足 7 元，股价 59.70 元无资产底线保护 |
| PB 合理性 | DONE | market.pb + indicators.indicators[0].roe_pct | PB 3.98 偏高，ROE 25.43% 提供支撑，但 PB 对 ROE 下滑敏感 |
| 连续盈利记录 | DONE | annual.annual_data[0:10].net_profit_yi | 2016-2025 连续 10 年盈利，PASS |
| DCF 多情景估值 | DONE | quarterly.fcf_ttm_yi + quarterly.ocf_ttm_yi + quarterly.cap_ex_ttm_yi + market.total_shares_yi | FCF-DCF：悲观 19.43 / 基准 31.73 / 乐观 61.06；盈利-DCF：悲观 41.76 / 基准 68.17 / 乐观 131.20。股价 59.70 在 FCF 口径下接近乐观情景，在盈利口径下处于悲观-基准之间 |
| 多模型交叉验证 | DONE | market.pe_ttm + market.pb + indicators.indicators[0].roe_pct + quarterly.fcf_ttm_yi + annual.annual_data[9].net_profit_yi | Graham Number（高估）+ FCF-DCF（高估）+ PB-ROE（中性偏贵）+ 盈利收益率（低估）+ 盈利-DCF（低估）。模型分歧 > 50%，标记模型不确定 |
| 捡漏 vs 价值陷阱（综合判断） | DONE | market.close + quarterly.fcf_ttm_yi + annual.annual_data[0:10].net_profit_yi + balance.cash_yi | 捡漏框架未触发（不足 2 项「低估」信号）。非价值陷阱：OCF 覆盖利润、负债可控、业务有结构性增长 |

## 数据使用说明

已使用数据：全年财务数据（2016-2025 年营收、利润、利润率）、资产负债表（2023-2025 年）、财务指标（2020-2025 年 ROE/毛利率/净利率/负债率/流动比率）、季度现金流（OCF/CAPEX/FCF TTM）、市场行情（股价/PE/PB/总市值/总股本）、审计历史、宏观利率（Shibor）、年报文本（2022-2025 年管理层讨论与分析）。

数据缺失：PE 历史序列（无法计算分位）、10 年期国债收益率（以 Shibor 替代）、有息负债分项（偿债能力结论降级）、行业可比公司数据（无法做行业横向估值对比）、股利历史（无法验证连续分红加分项）、流动资产/流动负债分项（NCAV 为近似估计）、折旧与摊销（无法构建 EBITDA 估值模型）。

## 知识检索日志

| # | 页面路径 | 发现方式 | 使用深度 |
|---|---------|---------|---------|
| 1 | [[格雷厄姆计算工具]] | 考试大纲 2.2 | 全文精读 — 用于 Graham Number 公式、判定区间与 VETO 阈值 |
| 2 | [[安全边际]] / [[普通股的安全边际]] | 考试大纲 2.3 / 2.4 | 关键段落 — 用于安全边际概念定义、Graham 比率判定标准 |
| 3 | [[多情景DCF分析]] | 考试大纲 2.8 | 全文精读 — 用于三情景参数设定、敏感性分析框架 |
| 4 | [[多模型加权估值法]] | 考试大纲 2.7 | 关键段落 — 用于模型分歧判定（≥ 3 模型高估 → VETO 增强） |
| 5 | [[清算价值]] | 考试大纲 2.11 | 关键段落 — 用于 NCAV 计算与烟蒂股判定 |
| 6 | [[捡漏框架]] | 考试大纲 2.16 | 关键段落 — 用于捡漏触发条件与价值陷阱排除清单 |
| 7 | [[估值方法对比]] | 考试大纲 2.6 | 全文精读 — 用于 PE/PB/ROE 交叉校验逻辑 |
| 8 | [[极度悲观点原则]] | 别名展开（方法论加分项引用） | 关键段落 — 用于判断当前是否处于极度悲观点（结论：否） |
| 9 | [[基本面投资降维三变量]] | 别名展开（方法论加分项引用） | 关键段落 — 用于检查是否过度关注琐碎价格变量 |
| 10 | [[平均斯坦与极端斯坦]] | 别名展开（方法论加分项引用） | 关键段落 — 用于极端斯坦安全边际校准 |
