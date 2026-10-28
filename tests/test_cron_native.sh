#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRIGGER="$SKILL_ROOT/scripts/cron_trigger.sh"
PROMPT="$SKILL_ROOT/scripts/cron_prompt.txt"

bash -n "$TRIGGER"

# Production cron entrypoint may require only DSH; it must never probe or invoke
# the legacy external worker path. Compatibility scripts remain separate.
if grep -Eq 'command -v (codex|claude)|(^|[[:space:]])codex exec|run_experts\.sh|run_challenges\.sh' "$TRIGGER"; then
    echo "cron_trigger.sh still contains a legacy external-worker path" >&2
    exit 1
fi

grep -Fq 'command -v dsh' "$TRIGGER"
grep -Fq 'native_agent_tasks.py begin experts' "$TRIGGER"
grep -Fq 'native_agent_tasks.py begin challenges' "$TRIGGER"
grep -Fq 'verify_report.py' "$TRIGGER"
grep -Fq 'verify_manifest.py' "$TRIGGER"

grep -Fq 'native_agent_tasks.py begin experts' "$PROMPT"
grep -Fq 'native_agent_tasks.py begin challenges' "$PROMPT"
grep -Fq '禁止自动调用 `run_experts.sh`' "$PROMPT"
grep -Fq '仅保留给用户明确启用的兼容路径' "$PROMPT"

# Explicit compatibility entrypoints remain present and retain their own guard.
for script in run_experts.sh run_challenges.sh run_cross_reviews.sh; do
    test -f "$SKILL_ROOT/scripts/$script"
done
for script in run_experts.sh run_challenges.sh run_cross_reviews.sh; do
    grep -Fq 'source "$SCRIPT_DIR/agent_backend.sh"' "$SKILL_ROOT/scripts/$script"
    grep -Fq 'select_agent_backend' "$SKILL_ROOT/scripts/$script"
done

echo "cron host-native static checks: PASS"
