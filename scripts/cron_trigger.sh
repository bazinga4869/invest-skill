#!/bin/bash
# cron → claude 每日自动分析
SKILL_DIR="/home/bazinga/invest-skill"
LOG_DIR="$SKILL_DIR/logs"
TIMESTAMP=$(date '+%Y%m%d_%H%M')
LOG_FILE="$LOG_DIR/cron_${TIMESTAMP}.log"
mkdir -p "$LOG_DIR"
cd "$SKILL_DIR"
/home/bazinga/.npm-global/bin/claude -p \
    --permission-mode bypassPermissions \
    --allowedTools "Read,Bash,Edit" \
    "$(cat $SKILL_DIR/scripts/cron_prompt.txt)" \
    >> "$LOG_FILE" 2>&1
echo "[$(date)] exit=$?" >> "$LOG_FILE"
