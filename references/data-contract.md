# 数据契约与质量门禁

仅在处理取数、口径或 `data_quality` 失败时读取。

## 内部标准

- 日期统一为 `YYYYMMDD`；报表 SQL 不接受带连字符日期。
- Tushare `daily_basic.total_mv/circ_mv` 的内部单位为万元；AKShare spot 的元值写库前除以 10,000。
- `null` 表示未知，绝不转换成 0。商誉、现金、借款分项任一缺失时，相应派生值保持 `null`。
- 数据源链是“主源失败后回退备用源”，不是双源交叉验证；除非两源同批次独立比对并记录差异，否则不得称“双源验证”。
- JSON 必须是严格标准 JSON：`NaN`/`Infinity` 在输出前转为 `null`，任何下游不得把非有限数当成有效事实。
- `meta.analysis_date` 是时点真值；历史分析只允许使用公告日不晚于该时点的年报，行情新鲜度也相对该时点而非现实系统时间计算。
- `prepare_prompts.py` 将数据、年报正文和 wiki 快照共同哈希成 `meta.batch_id`。七份专家结果必须同时匹配 `data_date` 与 `batch_id`；同日重跑也不能复用旧结果。

## 季度与自由现金流

Tushare 合并报表 `report_type=1` 是年内累计值。单季按 Q1=Q1、Q2=H1-Q1、Q3=Q3YTD-H1、Q4=FY-Q3YTD 还原；缺少前一期时该单季为 `null`。`report_type=2` 可直接视为单季；同一报告期同时存在两种口径时，展示值优先用 `report_type=2`，但 `report_type=1` 仍用于后续累计差分。`quarterly.periods[*].*_yi` 是单季，`*_ytd_yi` 是累计。

自由现金流只按 `n_cashflow_act - c_pay_acq_const_fiolta` 计算。`n_cashflow_inv_act` 是全部投资活动净现金流，不能当资本开支。TTM 仅在最近四个连续单季全部非空时计算，否则为 `null` 且 `ttm_complete=false`；先按原始元值求和，最后一次性换算/四舍五入为亿元。

年度 CAGR 使用首尾年度的真实年份差，不用“非空记录数”替代年数；5 年 CAGR 必须精确存在 `末年-5` 的起点，否则返回 `null`。

## 门禁

`data_tools.py all` 的 `data_quality.status=FAIL` 时必须停止。硬门禁包括行情、至少一份年报利润表、最近四个连续单季的营收/净利/OCF、最新资产负债表、财务指标和审计意见。资本开支、商誉或借款分项未知时为 WARN：值保持 `null`，分别禁止计算 FCF、断言“零商誉”或给出确定的净现金/偿债结论。行业或宏观样本不足同样为 WARN，且禁止构造行业比较。

任何外部补数都必须写入同批次 JSON、标明路径与来源并重新运行门禁；口头补充不能绕过快照和发布验证。

年报正文默认优先读取数据库中的有效缓存；已有至少 3 个完整年度时不因更早年份缺口自动触发慢速联网。需要强制刷新时显式运行 `annual-report <code> --force`。
