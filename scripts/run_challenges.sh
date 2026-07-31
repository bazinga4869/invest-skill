#!/usr/bin/env bash
# 并行执行 7 位专家的第二级魔鬼代言人质询。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
TMP_DIR="${TMPDIR:-/tmp}"
CODE="${1:-}"
MODE="${2:-}"
[[ -n "$CODE" ]] || { echo "用法: $0 <ts_code> [--retry]" >&2; exit 2; }
CODE=$(cd "$SKILL_ROOT" && python3 -c 'import sys; from shared.contracts import normalize_ts_code; print(normalize_ts_code(sys.argv[1]))' "$CODE")
command -v codex >/dev/null || { echo "ERROR: codex CLI 缺失" >&2; exit 2; }
mapfile -t EXPERTS < <(cd "$SKILL_ROOT" && python3 -c 'import json; print("\n".join(x["id"] for x in json.load(open("data/experts.json"))["experts"]))')
if [[ "$MODE" == "--retry" ]]; then
    mapfile -t TARGETS < <(cd "$SKILL_ROOT" && python3 scripts/collect_challenges.py "$CODE" --failing || true)
    (( ${#TARGETS[@]} > 0 )) || { echo "✓ 质询全部通过，无需重试"; exit 0; }
else
    cd "$SKILL_ROOT"
    python3 scripts/prepare_challenges.py "$CODE"
    TARGETS=("${EXPERTS[@]}")
fi
CONCURRENCY="${RUN_EXPERTS_CONCURRENCY:-7}"
TIMEOUT="${EXPERT_TIMEOUT:-1800}"
LOG_DIR="$SKILL_ROOT/logs/challenges"
mkdir -p "$LOG_DIR"
run_one() {
    local expert="$1"
    timeout "$TIMEOUT" codex exec -o "$TMP_DIR/invest_challenge_result_${CODE}_${expert}.md" - \
        < "$TMP_DIR/invest_challenge_prompt_${CODE}_${expert}.txt" \
        > "$LOG_DIR/${CODE}_${expert}.log" 2>&1
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
python3 scripts/collect_challenges.py "$CODE"
