#!/usr/bin/env bash
# 外部 CLI 兼容层：正常流程由 native_agent_tasks.py + 主 agent 原生子代理执行。
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
export INVEST_SKILL_ROOT="$SKILL_ROOT"
# prompts/results must share the caller's runtime root; explicit INVEST_RUNTIME_DIR still wins.
TMP_DIR="${INVEST_RUNTIME_DIR:-${INVEST_SKILL_HOME:-/tmp}}"
export INVEST_RUNTIME_DIR="$TMP_DIR"
CODE=""
RETRY=0
AGENT_OVERRIDE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --retry) RETRY=1; shift ;;
        --agent) [[ $# -ge 2 ]] || { echo "--agent 缺少参数" >&2; exit 2; }; AGENT_OVERRIDE="$2"; shift 2 ;;
        --agent=*) AGENT_OVERRIDE="${1#*=}"; shift ;;
        -*) echo "未知参数: $1" >&2; exit 2 ;;
        *) CODE="$1"; shift ;;
    esac
done
[[ -n "$CODE" ]] || { echo "用法: $0 <ts_code> [--retry] [--agent codex|claude]" >&2; exit 2; }
CODE=$(cd "$SKILL_ROOT" && python3 -c 'import sys; from shared.contracts import normalize_ts_code; print(normalize_ts_code(sys.argv[1]))' "$CODE")
source "$SCRIPT_DIR/agent_backend.sh"
select_agent_backend "$AGENT_OVERRIDE" || exit $?
EXPERT_CLI="$AGENT_BACKEND"
command -v "$EXPERT_CLI" >/dev/null || { echo "ERROR: $EXPERT_CLI CLI 缺失" >&2; exit 2; }
validate_agent_backend "$EXPERT_CLI" "${EXPERT_MODEL:-}" || exit $?
GUARD_CLAIMED=0
GUARD_TOKEN=""
release_guard() {
    if [[ "$GUARD_CLAIMED" -eq 1 ]]; then
        python3 "$SCRIPT_DIR/runtime_guard.py" release-run "$CODE" challenges \
            --token "$GUARD_TOKEN" >/dev/null 2>&1 || true
        GUARD_CLAIMED=0
    fi
}
on_signal() {
    local pids
    pids=$(jobs -pr)
    [[ -z "$pids" ]] || kill $pids 2>/dev/null || true
    release_guard
    exit 130
}
trap on_signal INT TERM
trap release_guard EXIT
guard_json=$(python3 "$SCRIPT_DIR/runtime_guard.py" claim-run "$CODE" challenges) || {
    echo "ERROR: 无法取得质询阶段互斥锁。" >&2
    exit 2
}
GUARD_TOKEN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$guard_json")
GUARD_CLAIMED=1
mapfile -t EXPERTS < <(cd "$SKILL_ROOT" && python3 -c 'import json; print("\n".join(x["id"] for x in json.load(open("data/experts.json"))["experts"]))')
if [[ "$RETRY" -eq 1 ]]; then
    failing_rc=0
    failing=$(cd "$SKILL_ROOT" && python3 scripts/collect_challenges.py "$CODE" --failing) || failing_rc=$?
    if [[ "$failing_rc" -ne 0 && "$failing_rc" -ne 1 ]]; then
        echo "ERROR: 无法读取失败质询列表（exit=$failing_rc）。" >&2
        exit 2
    fi
    mapfile -t TARGETS <<< "$failing"
    [[ -n "$failing" ]] || TARGETS=()
    (( ${#TARGETS[@]} > 0 )) || { echo "✓ 质询全部通过，无需重试"; exit 0; }
    python3 "$SCRIPT_DIR/runtime_guard.py" begin-retry "$CODE" challenges >/dev/null || {
        echo "ERROR: 本批质询重试额度已用完；禁止再次重跑。" >&2
        exit 2
    }
else
    if compgen -G "$TMP_DIR/invest_challenge_result_${CODE}_*.md" >/dev/null; then
        echo "ERROR: 已存在本批质询结果；请使用 --retry 或重建新批次，拒绝 fresh 覆盖。" >&2
        exit 2
    fi
    cd "$SKILL_ROOT"
    python3 scripts/prepare_challenges.py "$CODE"
    TARGETS=("${EXPERTS[@]}")
fi
CONCURRENCY="${RUN_EXPERTS_CONCURRENCY:-7}"
TIMEOUT="${EXPERT_TIMEOUT:-1800}"
# 运行时根：日志/结果写入调用方 INVEST_SKILL_HOME（与 run_experts 一致）
RUNTIME_ROOT="${INVEST_SKILL_HOME:-$(cd "$SKILL_ROOT" && python3 -c 'from shared.project_config import runtime_root; print(runtime_root())')}"
export INVEST_SKILL_HOME="$RUNTIME_ROOT"
# 运行时根防护：禁止把运行时产物写回 skill 仓库（INVEST_ALLOW_SKILL_RUNTIME=1 显式逃逸）
if [[ "$RUNTIME_ROOT" == "$SKILL_ROOT" && "${INVEST_ALLOW_SKILL_RUNTIME:-0}" != "1" ]]; then
    echo "ERROR: 未设置 INVEST_SKILL_HOME，运行时产物将写回 skill 仓库（违反只读契约）。" >&2
    echo "       请 export INVEST_SKILL_HOME=<宿主运行时目录>（或 INVEST_ALLOW_SKILL_RUNTIME=1 显式允许）。" >&2
    exit 2
fi
export INVEST_SKILL_HOME="$RUNTIME_ROOT"
TMP_DIR="$RUNTIME_ROOT"
export INVEST_RUNTIME_DIR="$RUNTIME_ROOT"
LOG_DIR="${INVEST_LOG_DIR:-$RUNTIME_ROOT/logs}/challenges"
mkdir -p "$LOG_DIR"
record_agent_execution "$SCRIPT_DIR" "$CODE" challenges "$EXPERT_CLI" \
    "$AGENT_HOST" "$CONCURRENCY" "$TIMEOUT" >/dev/null
echo "  质询后端：$EXPERT_CLI（宿主：$AGENT_HOST，来源：$AGENT_BACKEND_SOURCE）"
run_one() {
    local expert="$1"
    local prompt="$TMP_DIR/invest_challenge_prompt_${CODE}_${expert}.txt"
    local result="$TMP_DIR/invest_challenge_result_${CODE}_${expert}.md"
    local staged="$TMP_DIR/.invest_challenge_result_${CODE}_${expert}.${BASHPID}.next"
    local normalized="${staged}.normalized"
    local log="$LOG_DIR/${CODE}_${expert}.log"
    local rc=0
    rm -f "$staged" "$normalized"
    if invoke_model_agent "$EXPERT_CLI" "$staged" "$log" "$TIMEOUT" \
        "${EXPERT_MODEL:-}" < "$prompt"; then
        rc=0
    else
        rc=$?
    fi
    if [[ "$rc" -eq 0 && -s "$staged" ]] \
       && python3 "$SCRIPT_DIR/normalize_challenge.py" \
            "$CODE" "$expert" "$staged" "$normalized" >>"$log" 2>&1; then
        mv -f "$normalized" "$result"
    elif [[ "$rc" -eq 0 ]]; then
        rc=1
    fi
    rm -f "$staged" "$normalized"
    return "$rc"
}
declare -a PIDS=()
declare -A WHO=()
failed=0
for expert in "${TARGETS[@]}"; do
    echo "  ▶ [$expert] 质询开始…"
    run_one "$expert" & pid=$!; PIDS+=("$pid"); WHO["$pid"]="$expert"
    if (( ${#PIDS[@]} >= CONCURRENCY )); then
        for p in "${PIDS[@]}"; do wait "$p" || failed=$((failed + 1)); done
        PIDS=()
    fi
done
for p in "${PIDS[@]}"; do wait "$p" || failed=$((failed + 1)); done
(( failed == 0 )) || echo "⚠ $failed 个质询进程失败" >&2
cd "$SKILL_ROOT"
if python3 scripts/collect_challenges.py "$CODE"; then
    exit 0
fi
failure_evidence=""
if failure_evidence=$(python3 "$SCRIPT_DIR/preserve_failure_evidence.py" \
    "$CODE" challenges); then
    echo "失败证据已保留：$failure_evidence" >&2
else
    echo "⚠ 无法写入失败证据快照；现有 prompt/result/log 仍保留。" >&2
fi
if [[ "$RETRY" -eq 0 ]]; then
    echo "✗ 质询未通过；只允许一次：bash scripts/run_challenges.sh $CODE --retry" >&2
else
    echo "✗ 质询重试仍失败，本批次终止；失败现场默认保留。" >&2
    echo "  确认终止后显式清理：python3 scripts/cleanup_intermediates.py $CODE" >&2
fi
exit 1
