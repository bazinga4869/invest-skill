# 公司综合分析 Skill

## 用法

```bash
cd /home/bazinga/invest-skill

python3 company-analysis/analyze_company.py 贵州茅台
python3 company-analysis/analyze_company.py 600519.SH
python3 company-analysis/analyze_company.py 珀莱雅 --force-update
```

## 输出

报告保存到 `invest-skill/reports/YYYY-MM-DD/{公司名}_report_YYYY-MM-DD.md`。

## 数据来源

- 主：Tushare Pro
- 备：AKShare（待接入）
- 所有数据落入 `invest-skill/data/invest_skill.db`，与 invest-wiki 隔离

## 评分体系

见项目根目录 `README.md` 与 invest-wiki 的 [[公司综合分析 Skill]] 页面。

## 联动检查

运行前会校验 `config.yaml` 中声明的 wiki 方法论页面是否存在。缺失时：
- 输出告警
- 生成 `data/wiki_drift_report.json`
- 若 `block_on_drift: true` 则停止运行
