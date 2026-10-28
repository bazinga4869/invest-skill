#!/usr/bin/env bash
# ============================================================
# daily_analysis.sh — 每日自动分析 N 家上市公司
#
# 用法：
#   bash scripts/daily_analysis.sh              # 取 3 只，执行到待裁决草稿
#   bash scripts/daily_analysis.sh --count 5    # 取 5 只
#   bash scripts/daily_analysis.sh --sync-only  # 只同步数据 + 生成 prompt，不跑 expert
#   bash scripts/daily_analysis.sh --dry-run    # 只打印要分析的股票，不执行
# ============================================================
set -euo pipefail
umask 077

# --- 活动日志 ---

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
# cron 环境 PATH 极简（/usr/bin:/bin），补上 CLI 常见安装位置（sage-wiki 等）
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
# 本机部署配置（DEEPSEEK_API_KEY / INVEST_SKILL_HOME 等）；文件缺失时忽略
if [[ -f "$HOME/.config/invest-skill.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$HOME/.config/invest-skill.env"
    set +a
fi

# 运行时根：日志/报告/状态写入调用方 INVEST_SKILL_HOME，不回写 skill 仓库
RUNTIME_ROOT="${INVEST_SKILL_HOME:-$(cd "$SKILL_ROOT" && python3 -c 'from shared.project_config import runtime_root; print(runtime_root())')}"
export INVEST_SKILL_HOME="$RUNTIME_ROOT"
RUNTIME_DIR="${INVEST_RUNTIME_DIR:-$RUNTIME_ROOT}"
export INVEST_RUNTIME_DIR="$RUNTIME_DIR"
# 运行时根防护：禁止把运行时产物写回 skill 仓库（INVEST_ALLOW_SKILL_RUNTIME=1 显式逃逸）
if [[ "$RUNTIME_ROOT" == "$SKILL_ROOT" && "${INVEST_ALLOW_SKILL_RUNTIME:-0}" != "1" ]]; then
    echo "ERROR: 未设置 INVEST_SKILL_HOME，运行时产物将写回 skill 仓库（违反只读契约）。" >&2
    echo "       请 export INVEST_SKILL_HOME=<宿主运行时目录>（或 INVEST_ALLOW_SKILL_RUNTIME=1 显式允许）。" >&2
    exit 2
fi
export INVEST_SKILL_HOME="$RUNTIME_ROOT"
REPORTS_DIR="${INVEST_REPORTS_DIR:-$(cd "$SKILL_ROOT" && python3 -c 'from shared.project_config import configured_path; print(configured_path("invest_tool_dir", "./reports/invest_tool"))')}"
POOL_FILE="$RUNTIME_ROOT/config/stocks_pool.txt"
source "$SCRIPT_DIR/activity_log.sh"
STATE_FILE="$RUNTIME_ROOT/config/.daily_state"
LOG_DIR="${INVEST_LOG_DIR:-$RUNTIME_ROOT/logs}"
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
    local result_file="$REPORTS_DIR/${code}.draft.md"

    log "  ┌─ $code $name ─────────────────"

    # Step 1: 数据同步
    log "  │ [1/5] 同步数据…"
    if ! python3 "$SKILL_ROOT/shared/data_tools.py" sync "$code" >> "$LOG_FILE" 2>&1; then
        log "  │ ✗ 数据同步失败"
        log_activity "sync" "$code" "$name" "failure" "数据同步失败"
        return 1
    fi
    log_activity "sync" "$code" "$name" "success" "数据同步完成"

    # Step 1.5: report-wiki 语料就绪度门禁（只读、快）。
    # 未建库股票首次 materialize 需 1-4h（Sage 编译），会烧穿 prepare 的
    # 3600s 上限并拖垮整批；未就绪时跳过，由 prewarm_corpus.py 晚间预热。
    if ! python3 "$SKILL_ROOT/scripts/corpus_ready.py" "$code"; then
        log "  │ ✗ report-wiki 语料未就绪（跳过本只；晚间 prewarm 预热后次日可分析）"
        log_activity "prepare" "$code" "$name" "skipped" "report-wiki 语料未就绪（缺原件/证据）"
        return 1
    fi

    # Step 2: 生成 prompt
    log "  │ [2/5] 生成专家 prompt…"
    if ! python3 "$SKILL_ROOT/scripts/prepare_prompts.py" "$code" >> "$LOG_FILE" 2>&1; then
        log "  │ ✗ prompt 生成失败"
        log_activity "prompt" "$code" "$name" "failure" "prompt生成失败"
        return 1
    fi

    if [[ "$MODE" == "sync-only" ]]; then
        log "  │ [sync-only] 跳过 expert 执行"
        return 0
    fi

    # Shell cannot create a child of the *current* host agent.  Never guess a
    # product CLI here: doing so can silently switch provider/account and waste tokens.
    log "  │ [3/5] prompt 已就绪；等待当前主 agent 的原生子代理编排"
    log "  │ 执行入口: python3 scripts/native_agent_tasks.py begin experts $code"
    log "  └─ ⏸ shell 阶段停止；禁止自动 fallback 到 Codex/Claude/DSH CLI"
    log_activity "expert" "$code" "$name" "skipped" "等待主 agent 原生子代理编排"
    return 1
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
            ok=$((ok + 1))
        else
            fail=$((fail + 1))
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
        echo "报告路径: \`$REPORTS_DIR/\`"
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
    [[ $fail -eq 0 ]]
}

main
