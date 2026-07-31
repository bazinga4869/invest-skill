#!/usr/bin/env bash
# 第三级触发后，并行执行三份独立交叉盲审。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
TMP_DIR="${TMPDIR:-/tmp}"
CODE="${1:-}"
MODE="${2:-}"
[[ -n "$CODE" ]] || { echo "用法: $0 <ts_code> [--retry]" >&2; exit 2; }
CODE=$(cd "$SKILL_ROOT" && python3 -c 'import sys; from shared.contracts import normalize_ts_code; print(normalize_ts_code(sys.argv[1]))' "$CODE")
command -v codex >/dev/null || { echo "ERROR: codex CLI 缺失" >&2; exit 2; }
mapfile -t REVIEWERS < <(cd "$SKILL_ROOT" && python3 -c 'from scripts.collect_cross_reviews import CROSS_REVIEWERS; print("\n".join(CROSS_REVIEWERS))')
if [[ "$MODE" == "--retry" ]]; then
    mapfile -t TARGETS < <(cd "$SKILL_ROOT" && python3 scripts/collect_cross_reviews.py "$CODE" --failing || true)
    (( ${#TARGETS[@]} > 0 )) || { echo "✓ 三方交叉盲审全部通过，无需重试"; exit 0; }
else
    cd "$SKILL_ROOT"
    python3 scripts/prepare_cross_reviews.py "$CODE"
    TARGETS=("${REVIEWERS[@]}")
fi
CONCURRENCY="${RUN_EXPERTS_CONCURRENCY:-3}"
TIMEOUT="${EXPERT_TIMEOUT:-1800}"
LOG_DIR="$SKILL_ROOT/logs/cross_reviews"
mkdir -p "$LOG_DIR"
run_one() {
    local reviewer="$1"
    timeout "$TIMEOUT" codex exec -o "$TMP_DIR/invest_cross_result_${CODE}_${reviewer}.md" - \
        < "$TMP_DIR/invest_cross_prompt_${CODE}_${reviewer}.txt" \
        > "$LOG_DIR/${CODE}_${reviewer}.log" 2>&1
}
declare -a PIDS=()
failed=0
for reviewer in "${TARGETS[@]}"; do
    echo "  ▶ [$reviewer] 交叉盲审开始…"
    run_one "$reviewer" & PIDS+=("$!")
    if (( ${#PIDS[@]} >= CONCURRENCY )); then
        for pid in "${PIDS[@]}"; do wait "$pid" || failed=$((failed + 1)); done
        PIDS=()
    fi
done
for pid in "${PIDS[@]}"; do wait "$pid" || failed=$((failed + 1)); done
(( failed == 0 )) || echo "⚠ $failed 个交叉盲审进程失败" >&2
cd "$SKILL_ROOT"
python3 scripts/collect_cross_reviews.py "$CODE"
