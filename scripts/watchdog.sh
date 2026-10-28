#!/usr/bin/env bash
# ============================================================
# watchdog.sh — 每日健康检查：分析没跑/没成功且无告警时推送
#
# 用法：bash scripts/watchdog.sh
# 触发：crontab 工作日 08:00（低谷期内；04:30 轮最晚 06:30 已结束）
#
# 逻辑（最近 30 小时窗口，覆盖前一日 02:00/04:30 两轮）：
#   1. activity.jsonl 有 phase=report status=success → 正常，静默
#   2. alert.jsonl 已有告警记录 → 失败已上报，不重复打扰
#   3. 两者皆无 → cron 可能没跑或脚本崩了 → 告警
# ============================================================
set -u
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# cron 环境 PATH 极简（/usr/bin:/bin），补上 CLI 常见安装位置（hermes/sage-wiki 等）
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -f "$HOME/.config/invest-skill.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$HOME/.config/invest-skill.env"
    set +a
fi

RUNTIME_ROOT="${INVEST_SKILL_HOME:-$(cd "$SKILL_DIR" && python3 -c 'from shared.project_config import runtime_root; print(runtime_root())')}"
LOG_DIR="${INVEST_LOG_DIR:-$RUNTIME_ROOT/logs}"

python3 - "$LOG_DIR" <<'PYEOF'
import json, os, sys
from datetime import datetime, timedelta, timezone

log_dir = sys.argv[1]
window = datetime.now(timezone.utc) - timedelta(hours=30)
# 告警抑制窗口 24h：连续失败时每天提醒一次，而不是一次告警后静默数天
alert_window = datetime.now(timezone.utc) - timedelta(hours=24)

def recent_events(path, since):
    if not os.path.exists(path):
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if ts >= since:
                events.append(rec)
    return events

activity = recent_events(os.path.join(log_dir, "activity.jsonl"), window)
alerts = recent_events(os.path.join(log_dir, "alert.jsonl"), alert_window)

if any(r.get("phase") == "report" and r.get("status") == "success" for r in activity):
    print("OK: 最近 30 小时有成功报告")
    sys.exit(0)
if alerts:
    print("INFO: 最近 24 小时已有告警记录，不重复推送")
    sys.exit(0)

summary = "最近 30 小时无任何成功报告，且无失败告警记录。"
sys.exit(2)
PYEOF
RC=$?
if [[ $RC -eq 2 ]]; then
    bash "$SCRIPT_DIR/alert.sh" watchdog - "健康检查：最近 30 小时无成功分析且无失败告警（cron 可能未运行或脚本崩溃）"
    exit 1
fi
exit 0
