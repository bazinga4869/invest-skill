#!/usr/bin/env bash
# run_daily_analysis.sh — 每日双管道股票分析调度
# 用法: /home/bazinga/invest-skill/run_daily_analysis.sh <ts_code>
# 输出: reports/YYYY-MM-DD/<ts_code>_invest_tool_<date>.md
#       reports/YYYY-MM-DD/<ts_code>_sina_finance_<date>.md

set -e

CODE=$1
if [ -z "$CODE" ]; then
    echo "用法: $0 <ts_code>"
    exit 1
fi

TODAY=$(date +%Y-%m-%d)
INVEST_DIR=/home/bazinga/invest-skill
AI_BERKSHIRE_DIR=/home/bazinga/ai-berkshire
REPORT_DIR=$INVEST_DIR/reports/$TODAY
mkdir -p "$REPORT_DIR"

REPORT_A="$REPORT_DIR/${CODE}_invest_tool_${TODAY}.md"
REPORT_B="$REPORT_DIR/${CODE}_sina_finance_${TODAY}.md"

# 同步数据
cd "$INVEST_DIR"
source .venv/bin/activate
export TUSHARE_TOKEN=$(grep -v '^#' .env | grep TUSHARE_TOKEN | cut -d= -f2)
python3 shared/data_tools.py sync "$CODE" 2>/dev/null || true

# 获取公司名称
COMPANY_INFO=$(python3 shared/data_tools.py stock-info "$CODE" 2>/dev/null | head -5)
COMPANY_NAME="${CODE}"

echo "=== 开始分析 $CODE ==="
echo "管道A: invest-tool (Tushare)"

# 管道A
cd "$INVEST_DIR"
claude --bare -p "
请使用 invest-skill 的 SKILL.md 分析协议，分析股票 $CODE。

步骤：
1. 先同步: source .venv/bin/activate && export TUSHARE_TOKEN=\$(grep -v '^#' .env | grep TUSHARE_TOKEN | cut -d= -f2) && python3 shared/data_tools.py sync $CODE
2. 获取全部数据: python3 shared/data_tools.py all $CODE
3. 检查业绩预告: python3 shared/data_tools.py forecast $CODE
4. 读取 CLAUDE.md 组建专家团评估
5. 各专家独立评分
6. 报告保存到 $REPORT_A

约束：使用 .venv 的 Python
" --permission-mode bypassPermissions --allowedTools "Read,Bash,Write,Edit" 2>/dev/null

echo "管道B: sina_finance (新浪)"

# 管道B
cd "$AI_BERKSHIRE_DIR"

# 转换代码格式 (601398.SH -> SH601398)
SHORT_CODE="${CODE%.*}"
EXCHANGE="${CODE##*.}"
if [ "$EXCHANGE" = "SH" ]; then
    SINA_CODE="SH${SHORT_CODE}"
elif [ "$EXCHANGE" = "SZ" ]; then
    SINA_CODE="SZ${SHORT_CODE}"
else
    SINA_CODE="${SHORT_CODE}"
fi

claude --bare -p "
请使用 tools/sina_finance.py（独立新浪数据管道）分析股票 $CODE（新浪代码: ${SINA_CODE}）。

所有数据必须从新浪财经获取，不得使用 Tushare 或 invest-skill。
这是完全独立的 Source B 管道。

步骤：
1. 获取行情: python3 tools/sina_finance.py quote ${SINA_CODE}
2. 获取利润表: python3 tools/sina_finance.py income ${SINA_CODE}
3. 获取资产负债表: python3 tools/sina_finance.py balance ${SINA_CODE}
4. 获取现金流量表: python3 tools/sina_finance.py cashflow ${SINA_CODE}
5. 获取财务指标: python3 tools/sina_finance.py fin_ratio ${SINA_CODE}
6. 基于以上数据，按五专家框架完成完整分析
7. 报告保存到 $REPORT_B
" --permission-mode bypassPermissions --allowedTools "Read,Bash,Write,Edit" 2>/dev/null

echo ""
echo "=== $CODE 分析完成 ==="
echo "报告A: $REPORT_A"
echo "报告B: $REPORT_B"
echo ""
echo "下一家公司请查看 queue:"
cd "$INVEST_DIR"
python3 -c "
import json
with open('data/analysis_progress.json') as f:
    p = json.load(f)
with open('data/stock_pool.json') as f:
    pool = json.load(f)
completed = set(p['completed_codes'])
for s in pool:
    if s['ts_code'] not in completed:
        mv = s.get('total_mv',0)/10000
        print(f'  {s[\"ts_code\"]} {s[\"name\"]} ({s.get(\"industry\",\"\")}) {mv:.0f}亿')
        break
" 2>/dev/null || true