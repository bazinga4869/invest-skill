#!/usr/bin/env bash
# 列出所有 prompt 已生成但报告未完成的股票代码
SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$SKILL_ROOT/reports/invest_tool"

# 从 /tmp 中的 prompt 文件推断待处理的股票
ls /tmp/invest_prompt_*_financial-auditor.txt 2>/dev/null | while read f; do
    code=$(basename "$f" | sed 's/invest_prompt_\(.*\)_financial-auditor\.txt/\1/')
    if [[ ! -f "$REPORT_DIR/${code}.md" ]]; then
        name=$(grep -m1 'stock_name:' "$REPORT_DIR/${code}.md" 2>/dev/null | sed 's/.*"\(.*\)"/\1/' || echo "?")
        echo "$code"
    fi
done
