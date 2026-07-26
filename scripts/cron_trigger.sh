#!/bin/bash
# cron_trigger.sh — cron 定时触发每日自动分析（通用 agent 后端）
# 触发: 每天 10:00 / 14:30（见 crontab）
# 后端: --agent auto|codex|claude|hermes 或环境变量 AGENT，默认 auto（codex→claude→hermes）
# 健壮性: 前置检查 + stdin/argv 传 prompt + 超时(TERM→KILL) + 重试 + 结构化日志

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$SKILL_DIR/logs"
TIMESTAMP=$(date '+%Y%m%d_%H%M')
LOG_FILE="$LOG_DIR/cron_${TIMESTAMP}.log"
PROMPT_FILE="$SCRIPT_DIR/cron_prompt.txt"
MAX_RETRIES=1
# 真管线耗时：年报首次下载 ~5-10min + 7 专家 30-45min + 裁判长/报告 ~10min，
# 60 分钟会误杀正常运行的分析；默认放宽到 120 分钟
TIMEOUT_MINUTES=${TIMEOUT_MINUTES:-120}
AGENT="${AGENT:-auto}"

# cron 环境 PATH 极简（/usr/bin:/bin），补上 agent CLI 常见安装位置
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent) AGENT="${2:?--agent 需要参数}"; shift 2 ;;
        *) echo "用法: $0 [--agent auto|codex|claude|hermes]" >&2; exit 2 ;;
    esac
done

mkdir -p "$LOG_DIR"
cd "$SKILL_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# 与 run_experts.sh 同一检测顺序，保持 skill 内行为一致
detect_agent() {
    if [[ "$AGENT" != "auto" ]]; then
        command -v "$AGENT" &>/dev/null || { echo "ERROR: 指定的 agent 不可用: $AGENT" >&2; return 2; }
        echo "$AGENT"
        return 0
    fi
    local c
    for c in codex claude hermes; do
        command -v "$c" &>/dev/null && { echo "$c"; return 0; }
    done
    echo "ERROR: 未检测到 codex/claude/hermes CLI，缺少 agent 后端无法执行本分析" >&2
    return 2
}

# 外层会话要跑完整流水线（python 数据管道 + 拉起 7 个专家进程 + 写报告），
# 各后端「无人值守自主权」的 flag 不同，按后端分发。
# timeout 直接包住 agent 进程（-k 30：TERM 不理会时 30s 后补 KILL），
# 超时退出码 124，供下方重试逻辑识别。
run_once() {
    local backend="$1"
    local secs=$((TIMEOUT_MINUTES * 60))
    case "$backend" in
        codex)
            # exec 非交互；danger-full-access 允许数据管道联网与写盘
            timeout -k 30 "$secs" codex exec --sandbox danger-full-access - \
                < "$PROMPT_FILE" >> "$LOG_FILE" 2>&1
            ;;
        claude)
            # --bare 纯文本输出；stdin 传 prompt 避免内容被 CLI flag 误解析
            timeout -k 30 "$secs" claude --bare -p \
                --permission-mode bypassPermissions \
                --allowedTools "Read,Bash,Edit" \
                < "$PROMPT_FILE" >> "$LOG_FILE" 2>&1
            ;;
        hermes)
            # hermes 无 stdin 模式，-z 走 argv（cron prompt 仅 KB 级，远低于 300KB 上限）
            timeout -k 30 "$secs" hermes -z "$(cat "$PROMPT_FILE")" \
                >> "$LOG_FILE" 2>&1
            ;;
        *)
            echo "ERROR: 未知后端: $backend" >&2
            return 2
            ;;
    esac
}

log "═══ cron_trigger 开始 ═══"

# ─── 前置检查 ─────────────────────────────────────────────
if [[ ! -f "$PROMPT_FILE" ]]; then
    log "✗ prompt 文件不存在: $PROMPT_FILE"
    exit 1
fi
if [[ ! -s "$PROMPT_FILE" ]]; then
    log "✗ prompt 文件为空"
    exit 1
fi

backend=$(detect_agent) || exit 2
log "agent 后端: $backend (AGENT=$AGENT)"
log "prompt: $PROMPT_FILE ($(wc -l < "$PROMPT_FILE") 行)"

# ─── 执行（超时 + 重试） ──────────────────────────────────
attempt=0
while [[ $attempt -le $MAX_RETRIES ]]; do
    log "尝试 $((attempt + 1))/$((MAX_RETRIES + 1))…"

    run_once "$backend"
    RC=$?
    # exit 0 不算成功：外层会话可能中途静默终止（实测发生过）。
    # 只有日志里出现 CRON_DONE 完成标记才认定为成功。
    if [[ $RC -eq 0 ]] && grep -q 'CRON_DONE ' "$LOG_FILE"; then
        log "✓ 完成 (exit=$RC)"
        exit 0
    fi

    if [[ $RC -eq 0 ]]; then
        log "✗ 会话 exit 0 但无 CRON_DONE 标记（中途静默终止）"
    else
        log "✗ 失败 (exit=$RC, timeout=$([ $RC -eq 124 ] && echo yes || echo no))"
    fi
    attempt=$((attempt + 1))
done

log "═══ 所有重试已用尽，放弃 ═══"
exit "$RC"
