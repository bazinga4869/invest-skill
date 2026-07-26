#!/usr/bin/env bash
# ============================================================
# activity_log.sh — invest-skill 结构化活动日志
#
# 用法（source 后调用）：
#   source scripts/activity_log.sh
#   log_activity "sync" "600298.SH" "安琪酵母" "success" "数据同步完成"
#   log_activity "expert" "600298.SH" "安琪酵母" "success" "7/7 专家通过"
#   log_activity "report" "600298.SH" "安琪酵母" "success" "HOLD 54分"
#   log_activity "error" "600298.SH" "安琪酵母" "failure" "prompt生成失败: exit=1"
#
# 输出文件：$SKILL_ROOT/logs/activity.jsonl
# ============================================================

ACTIVITY_LOG="${ACTIVITY_LOG:-$HOME/invest-skill/logs/activity.jsonl}"

# 自动检测调用方 agent
detect_caller() {
    # CODEWX_INVOKED_BY 由调用方设置，否则自动检测
    if [[ -n "${INVEST_AGENT:-}" ]]; then
        echo "$INVEST_AGENT"
        return
    fi
    # 检测父进程链
    local ppid=$PPID
    while [[ $ppid -gt 1 ]]; do
        local pcmd
        pcmd=$(ps -o comm= -p $ppid 2>/dev/null || echo "")
        case "$pcmd" in
            codex|claude|hermes) echo "$pcmd"; return ;;
        esac
        ppid=$(ps -o ppid= -p $ppid 2>/dev/null || echo 1)
    done
    echo "manual"
}

log_activity() {
    local phase="$1"      # sync | prompt | expert | report | error
    local code="$2"       # ts_code
    local name="$3"       # 公司名
    local status="$4"     # success | failure | skipped
    local message="$5"    # 描述
    local agent
    agent=$(detect_caller)
    local ts
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    mkdir -p "$(dirname "$ACTIVITY_LOG")"
    printf '{"ts":"%s","agent":"%s","phase":"%s","code":"%s","name":"%s","status":"%s","msg":"%s"}\n' \
        "$ts" "$agent" "$phase" "$code" "$name" "$status" "$message" \
        >> "$ACTIVITY_LOG"
}
