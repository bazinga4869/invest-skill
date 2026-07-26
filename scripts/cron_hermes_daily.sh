#!/usr/bin/env bash
# ============================================================
# cron_hermes_daily.sh — Hermes 定时读取 invest-skill 报告并推送
#
# cron: 0 21 * * 1-5  (工作日 21:00，在 data sync 20:00 之后)
# ============================================================
SKILL_DIR="/home/bazinga/invest-skill"
LOG_DIR="$SKILL_DIR/logs"
TIMESTAMP=$(date '+%Y%m%d_%H%M')
LOG_FILE="$LOG_DIR/hermes_push_${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

# 1. 生成今日摘要
SUMMARY=$("$SKILL_DIR/scripts/reports_today.sh" 2>/dev/null)

# 2. 如果有新报告，推送给用户
HAS_REPORTS=$(echo "$SUMMARY" | grep -c '综合评分' || echo 0)

if [[ "$HAS_REPORTS" -gt 0 ]]; then
    {
        echo "[$(date)] 检测到 $HAS_REPORTS 份新报告"
        echo ""
        echo "$SUMMARY"
    } > "$LOG_FILE"
else
    {
        echo "[$(date)] 今日无新报告"
    } > "$LOG_FILE"
fi

# Hermes 读取 $LOG_FILE 来决定是否推送
# 或者 Hermes 直接调用 reports_today.sh
