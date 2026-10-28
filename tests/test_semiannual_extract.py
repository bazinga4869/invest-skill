import unittest

from scripts.prepare_prompts import extract_latest_semiannual_metrics


class SemiannualExtractTests(unittest.TestCase):
    def test_extracts_separated_numbers_without_digit_boundary_drift(self):
        profile = """
主要会计数据
营业收入 5,374,800,725.36 5,361,890,476.66 0.24
利润总额 1,339,569,138.47 998,497,421.08 34.16
归属于上市公司股东的净利润 1,167,896,499.41 798,511,332.07 46.26
归属于上市公司股东的扣除非经常
性损益的净利润 664,234,371.34 770,601,133.28 -13.80
经营活动产生的现金流量净额 950,841,180.71 1,293,329,341.66 -26.48
归属于上市公司股东的净资产 6,708,330,495.49 6,141,055,103.57 9.24
总资产 10,866,569,404.94 8,487,416,240.25 28.03
基本每股收益（元／股） 2.96 2.02 46.53
稀释每股收益（元／股） 2.94 2.02 45.54
扣除非经常性损益后的基本每股收
益（元／股） 1.68 1.95 -13.85
加权平均净资产收益率（%） 17.61 14.35 增加3.26个百分点
扣除非经常性损益后的加权平均净
资产收益率（%） 10.02 13.85 减少3.83个百分点
九、 非经常性损益项目和金额
合计 503,662,128.07
"""
        mda = """
财务报表相关科目变动分析表
营业成本 1,380,206,847.09 1,427,500,235.41 -3.31
销售费用 2,855,752,719.23 2,658,870,093.11 7.40
管理费用 236,648,534.10 177,479,237.25 33.34
研发费用 99,429,488.73 95,025,833.06 4.63
投资活动产生的现金流量净额 -697,822,418.10 -174,138,931.67 不适用
筹资活动产生的现金流量净额 -138,126,730.33 -477,161,516.14 不适用
购买日前持有的股权按购买日公允价值重新计量产生投资收益 445,360,152.15 元
"""
        bundle = {"reports": [{
            "fiscal_year": "2026H1",
            "report_type": "semi",
            "announcement_date": "20260824",
            "title": "2026年半年度报告",
            "source_sha256": "a" * 64,
            "evidence_build_id": "b" * 64,
            "sections": [
                {"name": "公司简介和主要财务指标", "text": profile},
                {"name": "管理层讨论与分析", "text": mda},
            ],
        }]}
        metrics = extract_latest_semiannual_metrics(bundle)["metrics"]
        self.assertEqual(metrics["parent_net_profit_prior_yi"], 7.985113)
        self.assertEqual(metrics["parent_net_profit_yoy_pct"], 46.26)
        self.assertEqual(metrics["total_assets_change_pct"], 28.03)
        self.assertEqual(metrics["weighted_roe_prior_pct"], 14.35)
        self.assertEqual(metrics["management_expense_yoy_pct"], 33.34)
        self.assertEqual(metrics["acquisition_remeasurement_gain_yi"], 4.453602)


if __name__ == "__main__":
    unittest.main()
