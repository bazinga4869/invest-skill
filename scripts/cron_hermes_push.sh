#!/bin/bash
# ============================================================
# cron → hermes 每日报告推送
# cron: 0 21 * * 1-5
# ============================================================
SKILL_DIR="/home/bazinga/invest-skill"
LOG_DIR="$SKILL_DIR/logs"
TIMESTAMP=$(date '+%Y%m%d_%H%M')
LOG_FILE="$LOG_DIR/hermes_push_${TIMESTAMP}.log"
mkdir -p "$LOG_DIR"
cd "$SKILL_DIR"

# 检查是否有可用的 hermes CLI
if command -v hermes &>/dev/null; then
    hermes run "$(cat $SKILL_DIR/scripts/hermes_push_prompt.txt)" \
        >> "$LOG_FILE" 2>&1
    echo "[$(date)] exit=$?" >> "$LOG_FILE"
else
    echo "[$(date)] hermes CLI not found — 跳过推送" >> "$LOG_FILE"
fi
