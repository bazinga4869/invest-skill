#!/usr/bin/env bash
# ============================================================
# run_experts.sh — 独立 Agent 并行执行 7 位专家分析
#
# 用法：
#   bash scripts/run_experts.sh <ts_code> [--agent auto|codex|claude|hermes]
#                                         [--no-prepare] [--retry]
#
#   --no-prepare  跳过 prompt 生成（调用方已运行 prepare_prompts.py，避免重复取数）
#   --retry       幂等重试：只重跑校验未通过的专家（collect_results.py --failing）
#
# 环境变量：
#   RUN_EXPERTS_CONCURRENCY  并发数，默认 3
#   EXPERT_TIMEOUT           单专家超时秒数，默认 1800
#
# 退出码：0 = 7 位专家全部通过校验
#         1 = 存在失败或校验未通过的专家（可用 --retry 幂等重试，最多 1 次）
#         2 = 用法/环境错误（agent CLI 缺失、prompt 缺失等）
#
# 设计要点：
#   - codex 后端用 `codex exec -o <result>` 落盘最后一条消息（CLI 写文件，
#     不受 codex exec 只读沙箱限制）；stdout/stderr 全部进 per-expert 日志，
#     保证结果文件只含专家正文，frontmatter 可解析。
#   - 非 --retry 运行前先删除旧结果文件，防止上次运行的陈旧结果被误当成本次产出。
#   - hermes 无 stdin 模式（-z 走 argv），prompt 超限直接判失败而非截断。
#   - 所有等待都收集逐专家退出码；任何失败都会反映到最终退出码（不静默）。
#   - hermes 后端未做端到端验证，仅作为实验性后备。
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
TMP_DIR="${TMPDIR:-/tmp}"

# --- 参数解析 ---
TS_CODE=""
AGENT="auto"
NO_PREPARE=0
RETRY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent)     AGENT="${2:?--agent 需要参数}"; shift 2 ;;
        --no-prepare) NO_PREPARE=1; shift ;;
        --retry)     RETRY=1; shift ;;
        -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
        -*)          echo "未知参数: $1" >&2; exit 2 ;;
        *)           TS_CODE="$1"; shift ;;
    esac
done
[[ -n "$TS_CODE" ]] || { echo "用法: $0 <ts_code> [--agent auto|codex|claude|hermes] [--no-prepare] [--retry]" >&2; exit 2; }

# 专家列表（与 SKILL.md 一致）
EXPERTS=(
    "financial-auditor:01-财务排雷官"
    "value-valuator:02-价值估值师"
    "growth-assessor:03-成长质量师"
    "moat-analyst:04-护城河分析师"
    "cognitive-controller:05-认知风控官"
    "macro-cyclist:06-宏观周期师"
    "management-auditor:07-管理层审计师"
)

CONCURRENCY="${RUN_EXPERTS_CONCURRENCY:-3}"
EXPERT_TIMEOUT="${EXPERT_TIMEOUT:-1800}"
LOG_DIR="$SKILL_ROOT/logs/experts"
mkdir -p "$LOG_DIR"

# 中断时终止后台专家进程，避免孤儿 agent 占用 API 配额
trap 'echo "⚠ 收到中断信号，终止后台专家进程…" >&2; kill $(jobs -p) 2>/dev/null || true' INT TERM

prompt_file() { echo "$TMP_DIR/invest_prompt_${TS_CODE}_$1.txt"; }
result_file() { echo "$TMP_DIR/invest_result_${TS_CODE}_$1.md"; }
expert_log()  { echo "$LOG_DIR/${TS_CODE}_$1.log"; }

# --- Agent 检测 ---
detect_agent() {
    if [[ "$AGENT" != "auto" ]]; then
        command -v "$AGENT" &>/dev/null || { echo "ERROR: 指定的 agent 不可用: $AGENT" >&2; return 2; }
        echo "$AGENT"
        return 0
    fi
    if command -v codex &>/dev/null; then
        echo "codex"
    elif command -v claude &>/dev/null; then
        echo "claude"
    elif command -v hermes &>/dev/null; then
        echo "hermes"
    else
        echo "ERROR: 未检测到 codex/claude/hermes CLI，缺少 agent 后端无法执行本分析" >&2
        return 2
    fi
}

# --- 生成 prompt 文件 ---
generate_prompts() {
    echo "[1/3] 生成 7 位专家 prompt…"
    cd "$SKILL_ROOT"
    python3 scripts/prepare_prompts.py "$TS_CODE"
}

# --- 校验 prompt 齐全（--no-prepare/--retry 路径） ---
require_prompts() {
    local missing=0
    for entry in "${EXPERTS[@]}"; do
        local expert_id="${entry%%:*}"
        if [[ ! -s "$(prompt_file "$expert_id")" ]]; then
            echo "  ✗ prompt 缺失: $(prompt_file "$expert_id")" >&2
            missing=$((missing + 1))
        fi
    done
    if [[ $missing -gt 0 ]]; then
        echo "ERROR: $missing 份 prompt 缺失，先运行 python3 scripts/prepare_prompts.py $TS_CODE" >&2
        return 2
    fi
}

# --- 执行单个专家（后台运行；退出码即 case 中命令的退出码） ---
run_expert() {
    local expert_id="$1"
    local backend="$2"
    local pf rf lf
    pf="$(prompt_file "$expert_id")"
    rf="$(result_file "$expert_id")"
    lf="$(expert_log "$expert_id")"

    echo "  ▶ [$expert_id] 开始…"

    if [[ ! -s "$pf" ]]; then
        echo "prompt 文件缺失: $pf" > "$lf"
        return 2
    fi

    case "$backend" in
        codex)
            # -o：CLI 落盘最后一条消息（不受只读沙箱限制）；stdout/stderr 进日志
            timeout "$EXPERT_TIMEOUT" codex exec -o "$rf" - < "$pf" > "$lf" 2>&1
            ;;
        claude)
            # --bare: 纯文本输出；stdin 传入避免 prompt 中 ** 被误解析
            timeout "$EXPERT_TIMEOUT" claude --bare -p < "$pf" > "$rf" 2> "$lf"
            ;;
        hermes)
            # hermes 无 stdin 模式，-z 走 argv；超限判失败而非截断半截 prompt
            local size
            size=$(wc -c < "$pf")
            if (( size > 300000 )); then
                echo "prompt ${size}B 超出 hermes argv 安全上限（300KB），请改用 codex/claude 后端" > "$lf"
                return 1
            fi
            timeout "$EXPERT_TIMEOUT" hermes -z "$(cat "$pf")" > "$rf" 2> "$lf"
            ;;
        *)
            echo "未知后端: $backend" > "$lf"
            return 2
            ;;
    esac
}

# --- 并行执行（批量并发控制 + 逐专家退出码收集） ---
declare -A RC_OF=()

wait_batch() {
    local -n _pids="$1"
    local -n _map="$2"
    local pid expert_id
    for pid in "${_pids[@]}"; do
        expert_id="${_map[$pid]}"
        if wait "$pid"; then
            RC_OF["$expert_id"]=0
            echo "  ✓ [$expert_id] 完成（$(wc -c < "$(result_file "$expert_id")" 2>/dev/null || echo 0) bytes）"
        else
            RC_OF["$expert_id"]=$?
            if [[ "${RC_OF[$expert_id]}" == "124" ]]; then
                echo "  ✗ [$expert_id] 超时（${EXPERT_TIMEOUT}s）"
            else
                echo "  ✗ [$expert_id] 失败（exit=${RC_OF[$expert_id]}，日志：$(expert_log "$expert_id")）"
            fi
        fi
    done
}

run_batch() {
    local backend="$1"; shift
    local -a pids=()
    local -A pid2expert=()
    local count=0
    local expert_id pid

    for expert_id in "$@"; do
        run_expert "$expert_id" "$backend" &
        pid=$!
        pids+=("$pid")
        pid2expert["$pid"]="$expert_id"
        count=$((count + 1))
        if (( count % CONCURRENCY == 0 )); then
            wait_batch pids pid2expert
            pids=()
        fi
    done

    if (( ${#pids[@]} > 0 )); then
        wait_batch pids pid2expert
    fi
}

# --- 校验结果 ---
check_results() {
    cd "$SKILL_ROOT"
    if python3 scripts/collect_results.py "$TS_CODE" --check; then
        return 0
    fi
    return 1
}

# --- 主流程 ---
main() {
    local backend
    backend=$(detect_agent) || exit 2

    # --retry 隐含 --no-prepare：结果必须与现有 prompt 同批次（data_date 一致性校验依赖这一点）
    if [[ $RETRY -eq 1 ]]; then
        NO_PREPARE=1
    fi

    echo "══════════════════════════════════════════"
    echo "  invest-skill 专家团独立分析"
    echo "  标的：$TS_CODE | Agent 后端：$backend | 并发：$CONCURRENCY | 单专家超时：${EXPERT_TIMEOUT}s"
    echo "══════════════════════════════════════════"

    if [[ $NO_PREPARE -eq 0 ]]; then
        generate_prompts
    else
        require_prompts || exit 2
    fi

    local -a targets=()
    if [[ $RETRY -eq 1 ]]; then
        local failing
        failing=$(python3 scripts/collect_results.py "$TS_CODE" --failing || true)
        if [[ -z "$failing" ]]; then
            echo "✓ 全部专家结果已通过校验，无需重试"
            exit 0
        fi
        mapfile -t targets <<< "$failing"
        echo "[2/3] 幂等重试 ${#targets[@]} 位专家：${targets[*]}"
    else
        # 预清理：删除上次运行的旧结果，防止陈旧结果被误当成本次产出
        local entry expert_id
        for entry in "${EXPERTS[@]}"; do
            expert_id="${entry%%:*}"
            rm -f "$(result_file "$expert_id")"
            targets+=("$expert_id")
        done
        echo "[2/3] 并行执行 ${#targets[@]} 位专家…"
    fi

    run_batch "$backend" "${targets[@]}"

    echo "[3/3] 校验结果…"
    if check_results; then
        echo ""
        echo "✓ 全部完成。下一步："
        echo "  python3 scripts/assemble_report.py $TS_CODE --name <公司名>"
        exit 0
    fi

    echo ""
    echo "✗ 存在未通过校验的专家。修复策略（有界，禁止反复重跑）："
    echo "  1. 幂等重试一次： bash scripts/run_experts.sh $TS_CODE --agent $backend --retry"
    echo "  2. 重试仍失败 → 以缺失状态继续：裁判长在报告中显式标注缺失专家并降低置信度，"
    echo "     或使用 fallback 路径（SKILL.md 第五步）。"
    exit 1
}

main
