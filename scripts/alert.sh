#!/usr/bin/env bash
# ============================================================
# alert.sh — invest-skill 失败/异常告警
#
# 用法：
#   bash scripts/alert.sh <phase> <code|-> <原因>
#   bash scripts/alert.sh sync 600000.SH "数据同步失败"
#   bash scripts/alert.sh watchdog - "今日无任何分析记录"
#
# 行为：
#   1. 写结构化告警事件到运行时根 logs/alert.jsonl（消费方：hermes 日报 / watchdog）
#   2. 通过 hermes send 推送到 telegram + discord（无 LLM、无 agent 循环；失败静默）
#
# 环境：INVEST_SKILL_HOME / INVEST_LOG_DIR 未设置时回退 skill 目录（向后兼容）
# ============================================================
set -u
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# cron 环境 PATH 极简（/usr/bin:/bin），补上 CLI 常见安装位置（hermes/sage-wiki 等）
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

# 本机部署配置（INVEST_SKILL_HOME 等）
if [[ -f "$HOME/.config/invest-skill.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$HOME/.config/invest-skill.env"
    set +a
fi

RUNTIME_ROOT="${INVEST_SKILL_HOME:-$(cd "$SKILL_DIR" && python3 -c 'from shared.project_config import runtime_root; print(runtime_root())')}"
LOG_DIR="${INVEST_LOG_DIR:-$RUNTIME_ROOT/logs}"
ALERT_FILE="$LOG_DIR/alert.jsonl"
mkdir -p "$LOG_DIR"

phase="${1:-unknown}"
code="${2:--}"
reason="${3:-未说明原因}"

# 结构化告警事件（JSON 转义交给 python）
python3 - "$phase" "$code" "$reason" "$ALERT_FILE" <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone

phase, code, reason, path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
record = {
    "ts": datetime.now(timezone.utc).isoformat(),
    "type": "alert",
    "phase": phase,
    "code": code,
    "reason": reason,
}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False) + "\n")
PYEOF

# 推送（hermes send 无 LLM；任一失败静默，不阻塞主流程）
if command -v hermes &>/dev/null; then
    msg="⚠️ invest-skill 告警 [$(date '+%m-%d %H:%M')] ${phase} ${code}: ${reason}"
    hermes send -t telegram "$msg" >/dev/null 2>&1 || true
    hermes send -t discord "$msg" >/dev/null 2>&1 || true
fi

echo "alert logged: $ALERT_FILE"
