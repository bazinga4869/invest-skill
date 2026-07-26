#!/usr/bin/env bash
# ============================================================
# reports_today.sh — 输出今日报告摘要，供 Hermes 定时读取并推送
#
# 用法：
#   bash scripts/reports_today.sh              # 今天的报告
#   bash scripts/reports_today.sh --date 2026-07-10  # 指定日期
#   bash scripts/reports_today.sh --json       # JSON 格式输出
#   bash scripts/reports_today.sh --activity   # 输出今日活动日志
#
# Hermes 集成：
#   hermes 在 cron 中调用此脚本，解析输出后推送到用户
# ============================================================
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$SKILL_ROOT/reports/invest_tool"
ACTIVITY_LOG="$SKILL_ROOT/logs/activity.jsonl"
DATE="${1:-today}"
OUTPUT_FORMAT="markdown"

# --- 参数解析 ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --date) DATE="$2"; shift 2 ;;
        --json) OUTPUT_FORMAT="json"; shift ;;
        --activity) OUTPUT_FORMAT="activity"; shift ;;
        --help|-h)
            echo "用法: $0 [--date YYYY-MM-DD] [--json|--activity]"
            exit 0
            ;;
        *) shift ;;
    esac
done

if [[ "$DATE" == "today" ]]; then
    DATE=$(date +%Y-%m-%d)
fi

# --- 活动日志模式 ---
if [[ "$OUTPUT_FORMAT" == "activity" ]]; then
    if [[ -f "$ACTIVITY_LOG" ]]; then
        grep "$DATE" "$ACTIVITY_LOG" 2>/dev/null || echo '{"msg":"今日无活动记录"}'
    else
        echo '{"msg":"活动日志不存在"}'
    fi
    exit 0
fi


# --- 检查今日异常 ---
check_failures() {
    local date="$1"
    local format="$2"  # markdown or json
    local activity_log="$SKILL_ROOT/logs/activity.jsonl"

    if [[ ! -f "$activity_log" ]]; then
        return
    fi

    local failures
    failures=$(grep "$date" "$activity_log" 2>/dev/null | grep '"failure"' || true)

    if [[ -z "$failures" ]]; then
        return
    fi

    local count
    count=$(echo "$failures" | wc -l)

    if [[ "$format" == "json" ]]; then
        echo "  \"failures\": ["
        local first=true
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            local code name phase msg
            code=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code','?'))" 2>/dev/null || echo "?")
            name=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','?'))" 2>/dev/null || echo "?")
            phase=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('phase','?'))" 2>/dev/null || echo "?")
            msg=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('msg',''))" 2>/dev/null || echo "")
            local comma=","
            [[ "$first" == "true" ]] && comma="" && first=false
            echo "    $comma{\"code\":\"$code\",\"name\":\"$name\",\"phase\":\"$phase\",\"msg\":\"$msg\"}"
        done <<< "$failures"
        echo "  ],"
        echo "  \"failure_count\": $count,"
    else
        echo ""
        echo "## ⚠️ 今日异常（$count 条）"
        echo ""
        echo "| 时间 | 股票 | 阶段 | 错误 |"
        echo "|------|------|------|------|"
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            local ts code name phase msg
            ts=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ts',''))" 2>/dev/null || echo "")
            code=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code','?'))" 2>/dev/null || echo "?")
            name=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','?'))" 2>/dev/null || echo "?")
            phase=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('phase','?'))" 2>/dev/null || echo "?")
            msg=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('msg',''))" 2>/dev/null || echo "")
            echo "| $ts | $name($code) | $phase | $msg |"
        done <<< "$failures"
        echo ""
    fi
}

# --- 收集今日报告 ---
REPORTS=()
while IFS= read -r -d '' f; do
    REPORTS+=("$f")
done < <(find "$REPORT_DIR" -name "*.md" -newermt "$DATE" -not -newermt "$DATE+1 day" -print0 2>/dev/null || true)

# --- JSON 输出 ---
if [[ "$OUTPUT_FORMAT" == "json" ]]; then
    echo '{'
    echo "  \"date\": \"$DATE\","
    check_failures "$DATE" "json"
    echo "  \"report_count\": ${#REPORTS[@]},"
    echo '  "reports": ['
    for i in "${!REPORTS[@]}"; do
        f="${REPORTS[$i]}"
        code=$(basename "$f" .md)
        code=$(basename "$f" .md)
        name=$(grep -m1 'stock_name:' "$f" 2>/dev/null | sed 's/.*: "\(.*\)"/\1/' || echo "?")
        score=$(grep -m1 'composite_score:' "$f" 2>/dev/null | sed 's/.*: //' || echo "?")
        rating=$(grep -m1 'rating:' "$f" 2>/dev/null | sed 's/.*: "\(.*\)"/\1/' || echo "?")
        comma=","
        [[ $i -eq $((${#REPORTS[@]} - 1)) ]] && comma=""
        echo "    {\"code\":\"$code\",\"name\":\"$name\",\"score\":$score,\"rating\":\"$rating\"}$comma"
    done
    echo '  ]'
    echo '}'
    exit 0
fi

# --- Markdown 输出（默认，适合 Hermes 阅读） ---
echo "# invest-skill 每日报告 · $DATE"
echo ""

if [[ ${#REPORTS[@]} -eq 0 ]]; then
    echo "本日无新报告。"
    echo ""
    echo "---"
    echo ""
    echo "## 今日活动日志"
    if [[ -f "$ACTIVITY_LOG" ]]; then
        grep "$DATE" "$ACTIVITY_LOG" 2>/dev/null | while IFS= read -r line; do
            phase msg
            phase=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('phase','?'))" 2>/dev/null || echo "?")
            msg=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null || echo "")
            echo "- \`$phase\` $msg"
        done
    else
        echo "（无活动日志）"
    fi
    exit 0
fi

echo "共 **${#REPORTS[@]}** 份报告："
echo ""

for f in "${REPORTS[@]}"; do
    code=$(basename "$f" .md)
    name=$(grep -m1 'stock_name:' "$f" 2>/dev/null | sed 's/.*: "\(.*\)"/\1/' || echo "?")
    score=$(grep -m1 'composite_score:' "$f" 2>/dev/null | sed 's/.*: //' || echo "?")
    rating=$(grep -m1 'rating:' "$f" 2>/dev/null | sed 's/.*: "\(.*\)"/\1/' || echo "?")

    # 评级 emoji
    emoji=""
    case "$rating" in
        BUY) emoji="🟢" ;;
        HOLD) emoji="🟡" ;;
        SELL|PASS) emoji="🔴" ;;
        *) emoji="⚪" ;;
    esac

    echo "### $emoji $name（$code）"
    echo ""
    echo "| 指标 | 值 |"
    echo "|------|----|"
    echo "| 综合评分 | $score / 90 |"
    echo "| 评级 | **$rating** |"
    echo "| 报告路径 | \`$f\` |"
    echo ""

    # 提取一行总评
    oneline=$(grep -A1 '一行总评' "$f" 2>/dev/null | tail -1 | sed 's/^> //' || echo "")
    if [[ -n "$oneline" ]]; then
        echo "> $oneline"
    fi
    echo ""
done

check_failures "$DATE" "markdown"
echo "---"
echo "*生成时间：$(date '+%Y-%m-%d %H:%M:%S')*"
