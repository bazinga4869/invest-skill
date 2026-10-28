#!/bin/bash
# ============================================================
# cron → hermes 每日报告推送
# cron: 0 21 * * 1-5
# ============================================================
SKILL_DIR="/home/bazinga/invest-skill"
# cron 环境 PATH 极简（/usr/bin:/bin），补上 CLI 常见安装位置（hermes/sage-wiki 等）
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

# 本机部署配置（INVEST_SKILL_HOME / INVEST_LOG_DIR 等；单一配置源）
if [[ -f "$HOME/.config/invest-skill.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$HOME/.config/invest-skill.env"
    set +a
fi
# 日志写入调用方 INVEST_LOG_DIR（运行时根），默认 skill 仓库（向后兼容）
LOG_DIR="${INVEST_LOG_DIR:-$SKILL_DIR/logs}"
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
