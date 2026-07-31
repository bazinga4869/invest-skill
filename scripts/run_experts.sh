#!/usr/bin/env bash
# ============================================================
# run_experts.sh — 并行执行 7 位专家分析
#
# 用法：
#   bash scripts/run_experts.sh <ts_code> [--no-prepare] [--retry]
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
#         2 = 用法/环境错误（codex CLI 缺失、prompt 缺失等）
#
# 设计：
#   - 每位专家启动一个 codex exec 独立进程，通过 stdin 读 prompt、-o 落盘结果
#   - 非 --retry 运行前先删除旧结果文件，防止上次运行的陈旧结果被误当成本次产出
#   - 所有等待都收集逐专家退出码；任何失败都会反映到最终退出码（不静默）
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
TMP_DIR="${TMPDIR:-/tmp}"

# --- 参数解析 ---
TS_CODE=""
NO_PREPARE=0
RETRY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-prepare) NO_PREPARE=1; shift ;;
        --retry)      RETRY=1; shift ;;
        --agent)      EXPERT_CLI="$2"; shift 2 ;;
        --agent=*)    EXPERT_CLI="${1#*=}"; shift ;;
        -h|--help)    sed -n '2,17p' "$0"; exit 0 ;;
        -*)           echo "未知参数: $1" >&2; exit 2 ;;
        *)            TS_CODE="$1"; shift ;;
    esac
done
[[ -n "$TS_CODE" ]] || { echo "用法: $0 <ts_code> [--no-prepare] [--retry] [--agent codex|claude]" >&2; exit 2; }
if ! TS_CODE=$(cd "$SKILL_ROOT" && python3 -c \
    'import sys; from shared.contracts import normalize_ts_code; print(normalize_ts_code(sys.argv[1]))' \
    "$TS_CODE"); then
    echo "ERROR: 股票代码格式非法" >&2
    exit 2
fi

# 前置检查：所选 CLI 必须可用（--agent 参数 或 EXPERT_CLI 环境变量）
EXPERT_CLI="${EXPERT_CLI:-codex}"
command -v "$EXPERT_CLI" &>/dev/null || { echo "ERROR: 需要 $EXPERT_CLI CLI 来执行专家分析（可通过 --agent 参数或 EXPERT_CLI 环境变量指定）" >&2; exit 2; }

# 专家列表：从 data/experts.json 读取（唯一数据源）
EXPERTS_JSON="$SKILL_ROOT/data/experts.json"
EXPERTS=()
while IFS= read -r entry; do
    EXPERTS+=("$entry")
done < <(python3 -c "
import json
data = json.load(open('$EXPERTS_JSON'))
for e in data['experts']:
    print(f\"{e['id']}:{e['file']}\")
")

CONCURRENCY="${RUN_EXPERTS_CONCURRENCY:-3}"
EXPERT_TIMEOUT="${EXPERT_TIMEOUT:-1800}"
LOG_DIR="$SKILL_ROOT/logs/experts"
mkdir -p "$LOG_DIR"

# 中断时终止后台专家进程，避免孤儿 agent 占用 API 配额
trap 'echo "⚠ 收到中断信号，终止后台专家进程…" >&2; kill $(jobs -p) 2>/dev/null || true' INT TERM

prompt_file() { echo "$TMP_DIR/invest_prompt_${TS_CODE}_$1.txt"; }
result_file() { echo "$TMP_DIR/invest_result_${TS_CODE}_$1.md"; }
expert_log()  { echo "$LOG_DIR/${TS_CODE}_$1.log"; }

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

# --- 专家结果修复（带着校验失败清单让 agent 定向修复）---
fix_expert() {
    local expert_id="$1"
    local pf rf lf
    pf="$(prompt_file "$expert_id")"
    rf="$(result_file "$expert_id")"
    lf="$(expert_log "$expert_id")"
    local fix_prompt="/tmp/invest_fix_${TS_CODE}_${expert_id}.txt"

    # 收集该校验失败的专家具体问题
    python3 "$SKILL_ROOT/scripts/collect_results.py" "$TS_CODE" --failing --json > /tmp/invest_fix_errors_${TS_CODE}.json 2>/dev/null
    local problems
    problems=$(python3 -c "
import json, sys
data = json.load(open('/tmp/invest_fix_errors_${TS_CODE}.json'))
expert = data.get('${expert_id}', {})
print(chr(10).join(expert.get('problems', ['（校验错误详情不可得）'])))
" 2>/dev/null)

    # 构造修复 prompt：原始任务 + 上一轮的失败输出 + 具体问题
    {
        echo '⬛⬛⬛ 修复任务 — 只修正以下问题，不改动其余内容 ⬛⬛⬛'
        echo ''
        echo '你的上一轮分析因以下问题未通过校验：'
        echo "$problems"
        echo ''
        echo '请基于原始任务书重新输出完整分析，确保上述问题全部修正。'
        echo '输出格式：直接以 --- YAML frontmatter 开头。'
        echo ''
        echo '══════ 原始任务书 ══════'
        cat "$pf"
    } > "$fix_prompt"

    echo "  [fix] $expert_id — 带着校验失败清单定向修复…" >> "$lf"
    timeout "$EXPERT_TIMEOUT" codex exec -o "$rf" - < "$fix_prompt" >> "$lf" 2>&1
    rm -f "$fix_prompt" /tmp/invest_fix_errors_${TS_CODE}.json
}

# --- 执行单个专家（后台运行）---
run_expert() {
    local expert_id="$1"
    local pf rf lf
    pf="$(prompt_file "$expert_id")"
    rf="$(result_file "$expert_id")"
    lf="$(expert_log "$expert_id")"

    echo "  ▶ [$expert_id] 开始…"

    if [[ ! -s "$pf" ]]; then
        echo "prompt 文件缺失: $pf" > "$lf"
        return 2
    fi

    # 根据 EXPERT_CLI 选择后端
    case "$EXPERT_CLI" in
        codex)
            # 模拟交互式质量的 headless 执行：
            # - 给予完整文件系统访问权（读 prompt、写草稿、自检）
            # - 使用与交互模式一致的模型
            # - 两阶段：分析 → 自检修正 → 最终输出
            local model="${EXPERT_MODEL:-}"
            local model_arg=()
            [[ -n "$model" ]] && model_arg=(-m "$model")
            {
                echo '⬛⬛⬛ 你是 invest-skill 分析管线的自动化专家代理 ⬛⬛⬛'
                echo ''
                echo '你有文件读写和命令执行工具。请按以下两步执行：'
                echo ''
                echo '【阶段 1 — 分析】读入下方任务书，完成完整分析，写入草稿文件'
                echo "  /tmp/invest_draft_${TS_CODE}_${expert_id}.md"
                echo ''
                echo '【阶段 2 — 自检修正】读取你的草稿，逐项检查：'
                echo '  (a) 第一行是否是 "---"（YAML frontmatter 开头）？'
                echo '  (b) frontmatter 是否包含 expert_id, score, verdict, data_date, batch_id？'
                echo '  (c) 必检项表格每行是否都有 DONE/MISSING + 证据 + 结论？'
                echo '  (d) 所有数字是否紧跟 [source:] 或 [calc:]？'
                echo '  (e) 总字符数是否 ≥ 3000？'
                echo '  发现问题立即修正，修正后将完整最终版输出到 stdout。'
                echo '  不要输出任何 --- 之外的前导文字、空行或代码块标记。'
                echo ''
                echo '══════ 任务书 ══════'
                cat "$pf"
            } | timeout "$EXPERT_TIMEOUT" codex exec                 -o "$rf"                 --sandbox danger-full-access                 --add-dir /tmp                 "${model_arg[@]}"                 - > "$lf" 2>&1
            # 清理草稿
            rm -f "/tmp/invest_draft_${TS_CODE}_${expert_id}.md"
            ;;
        claude)
            # claude CLI: --bare 输出纯文本, -p 接受 stdin（避免 $(cat) 导致 "Argument list too long"）
            timeout "$EXPERT_TIMEOUT" claude --bare -p < "$pf" > "$rf" 2>"$lf"
            ;;
        *)
            echo "不支持的 EXPERT_CLI: $EXPERT_CLI（支持 codex / claude）" > "$lf"
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
    local -a pids=()
    local -A pid2expert=()
    local count=0
    local expert_id pid

    for expert_id in "$@"; do
        run_expert "$expert_id" &
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
    local max_fix_rounds=2
    local round=0
    while [[ $round -le $max_fix_rounds ]]; do
        if python3 scripts/collect_results.py "$TS_CODE" --check \
            && python3 scripts/checklist_audit.py --code "$TS_CODE"; then
            return 0
        fi
        [[ $round -ge $max_fix_rounds ]] && break
        round=$((round + 1))
        echo "[fix] 第 $round/$max_fix_rounds 轮修复 — 定向修正校验失败的专家…"
        local -a fix_pids=()
        while IFS= read -r expert_id; do
            fix_expert "$expert_id" &
            fix_pids+=($!)
        done < <(python3 scripts/collect_results.py "$TS_CODE" --failing 2>/dev/null)
        for pid in "${fix_pids[@]}"; do
            wait "$pid" || true
        done
    done
    return 1
}

# --- 主流程 ---
main() {
    # --retry 隐含 --no-prepare：结果必须与现有 prompt 同批次（data_date 一致性校验依赖这一点）
    if [[ $RETRY -eq 1 ]]; then
        NO_PREPARE=1
    fi

    echo "══════════════════════════════════════════"
    echo "  invest-skill 专家团独立分析"
    echo "  标的：$TS_CODE | 并发：$CONCURRENCY | 单专家超时：${EXPERT_TIMEOUT}s"
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

    run_batch "${targets[@]}"

    echo "[3/3] 校验结果…"
    if check_results; then
        echo ""
        echo "✓ 全部完成。下一步："
        echo "  bash scripts/run_challenges.sh $TS_CODE"
        exit 0
    fi

    echo ""
    echo "✗ 存在未通过校验的专家。修复策略（有界，禁止反复重跑）："
    echo "  1. 幂等重试一次： bash scripts/run_experts.sh $TS_CODE --retry"
    echo "  2. 重试仍失败 → 终止本次分析；禁止以缺失专家结果发布报告。"
    exit 1
}

main
