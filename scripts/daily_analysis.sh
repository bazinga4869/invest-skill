#!/usr/bin/env bash
# ============================================================
# daily_analysis.sh — 每日自动分析 N 家上市公司
#
# 用法：
#   bash scripts/daily_analysis.sh              # 正常执行：取 3 只，全流程
#   bash scripts/daily_analysis.sh --count 5    # 取 5 只
#   bash scripts/daily_analysis.sh --sync-only  # 只同步数据 + 生成 prompt，不跑 expert
#   bash scripts/daily_analysis.sh --dry-run    # 只打印要分析的股票，不执行
# ============================================================
set -euo pipefail

# --- 活动日志 ---

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
POOL_FILE="$SKILL_ROOT/config/stocks_pool.txt"
source "$SCRIPT_DIR/activity_log.sh"
STATE_FILE="$SKILL_ROOT/config/.daily_state"
LOG_DIR="$SKILL_ROOT/logs"
TIMESTAMP=$(date +%Y-%m-%d_%H%M)
LOG_FILE="$LOG_DIR/daily_${TIMESTAMP}.log"
SUMMARY_FILE="$LOG_DIR/daily_summary.md"

COUNT=3
MODE="full"

# --- 参数解析 ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --count) COUNT="$2"; shift 2 ;;
                --sync-only) MODE="sync-only"; shift ;;
        --dry-run) MODE="dry-run"; shift ;;
        --help|-h)
            echo "用法: $0 [--count N] [--resume|--sync-only|--dry-run]"
            exit 0
            ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG_FILE"; }

# --- 从股票池取 N 只（轮转） ---
pick_stocks() {
    local n="$1"
    # 从数据库动态选取：全 A 股，排除科创/北交/ST
    # 每天按固定种子随机，保证同一天多次运行选到同一批
    local seed
    seed=$(date +%Y%m%d)
    python3 "$SKILL_ROOT/scripts/pick_stocks.py" "$n" "$seed"
}

# --- 单只股票全流程 ---
analyze_one() {
    local code="$1"
    local name="$2"
    local result_file="$SKILL_ROOT/reports/invest_tool/${code}.md"

    log "  ┌─ $code $name ─────────────────"

    # Step 1: 数据同步
    log "  │ [1/4] 同步数据…"
    if ! python3 "$SKILL_ROOT/shared/data_tools.py" sync "$code" >> "$LOG_FILE" 2>&1; then
        log "  │ ✗ 数据同步失败"
    log_activity "sync" "$code" "$name" "failure" "数据同步失败"
        return 1
    log_activity "sync" "$code" "$name" "success" "数据同步完成"
    fi

    # Step 2: 生成 prompt
    log "  │ [2/4] 生成专家 prompt…"
    if ! python3 "$SKILL_ROOT/scripts/prepare_prompts.py" "$code" >> "$LOG_FILE" 2>&1; then
        log "  │ ✗ prompt 生成失败"
    log_activity "prompt" "$code" "$name" "failure" "prompt生成失败"
        return 1
    fi

    if [[ "$MODE" == "sync-only" ]]; then
        log "  │ [sync-only] 跳过 expert 执行"
        return 0
    fi

    # Step 3: 执行专家分析（timeout 60 分钟）
    log "  │ [3/4] 执行 7 位专家…"
    if timeout 3600 bash "$SKILL_ROOT/scripts/run_experts.sh" "$code" >> "$LOG_FILE" 2>&1; then
        log "  │ ✓ 专家分析完成"
        log_activity "expert" "$code" "$name" "success" "7专家分析完成"
    else
        local ec=$?
        if [[ $ec -eq 124 ]]; then
            log "  │ ⚠ 专家分析超时（60min）"
        else
            log "  │ ✗ 专家分析失败 (exit=$ec)"
        fi
        return 1
    fi

    # Step 4: 组装报告
    log "  │ [4/4] 组装报告…"
    if python3 "$SKILL_ROOT/scripts/assemble_report.py" "$code" --name "$name" --finalize >> "$LOG_FILE" 2>&1; then
        log "  └─ ✓ $code $name — 报告已生成: $result_file"
        log_activity "report" "$code" "$name" "success" "报告已生成"
        return 0
    else
        log "  └─ ⚠ $code $name — 报告组装失败（专家结果可能不完整）"
        return 1
    fi
}

# --- 主流程 ---
main() {
    log "══════════════════════════════════════════"
        local caller; caller=$(detect_caller)
    log_activity "session" "-" "每日分析" "start" "agent=$caller mode=$MODE count=$COUNT"
    log "  invest-skill 每日分析"
    log "  日期：$(date +%Y-%m-%d) | 模式：$MODE | 数量：$COUNT"
    log "══════════════════════════════════════════"

    local stocks
    stocks=$(pick_stocks "$COUNT")

    if [[ "$MODE" == "dry-run" ]]; then
        echo "今日将分析："
        echo "$stocks"
        exit 0
    fi

    local ok=0 fail=0
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        local code="${line%% *}"
        local name="${line#* }"
        if analyze_one "$code" "$name"; then
            ((ok++))
        else
            ((fail++))
        fi
        echo ""
    done <<< "$stocks"

    # 摘要
    {
        echo "# 每日分析摘要 — $(date +%Y-%m-%d)"
        echo ""
        echo "| 结果 | 数量 |"
        echo "|------|:---:|"
        echo "| ✓ 完成 | $ok |"
        echo "| ✗ 失败 | $fail |"
        echo ""
        echo "## 今日标的"
        echo '```'
        echo "$stocks"
        echo '```'
        echo ""
        echo "报告路径: \`reports/invest_tool/\`"
        echo "日志: \`$LOG_FILE\`"
    } > "$SUMMARY_FILE"

    # Log session result
    local session_status="success"
    [[ $fail -gt 0 ]] && session_status="failure"
    log_activity "session" "-" "每日分析" "$session_status" "完成=$ok 失败=$fail 模式=$MODE"

    log "══════════════════════════════════════════"
    log "  完成：$ok | 失败：$fail"
    log "  摘要：$SUMMARY_FILE"
    log "══════════════════════════════════════════"
}

main
