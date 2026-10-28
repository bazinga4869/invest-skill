#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$SKILL_ROOT/scripts/agent_backend.sh"

# 主 agent 无论是什么，都不得自动退化为另一个产品的外部 CLI。
for host in codex claude ""; do
    if INVEST_HOST_AGENT="$host" EXPERT_CLI= bash -c \
        'source "$1"; select_agent_backend ""' _ "$HELPER" >/dev/null 2>&1; then
        echo "host=$host 不应自动选择外部 worker" >&2
        exit 1
    fi
done

if INVEST_HOST_AGENT=codex INVEST_ALLOW_EXTERNAL_AGENT=0 EXPERT_CLI= bash -c \
    'source "$1"; select_agent_backend codex' _ "$HELPER" >/dev/null 2>&1; then
    echo "未显式许可时外部 CLI 应被拒绝" >&2
    exit 1
fi

actual=$(INVEST_HOST_AGENT=codex INVEST_ALLOW_EXTERNAL_AGENT=1 EXPERT_CLI= bash -c \
    'source "$1"; select_agent_backend codex; printf "%s" "$AGENT_BACKEND"' _ "$HELPER")
[[ "$actual" == "codex" ]] || { echo "显式外部兼容模式失败" >&2; exit 1; }

if INVEST_HOST_AGENT=codex INVEST_ALLOW_EXTERNAL_AGENT=1 EXPERT_CLI= bash -c \
    'source "$1"; select_agent_backend claude' _ "$HELPER" >/dev/null 2>&1; then
    echo "未授权跨 agent 应被拒绝" >&2
    exit 1
fi

actual=$(INVEST_HOST_AGENT=codex INVEST_ALLOW_EXTERNAL_AGENT=1 \
    INVEST_ALLOW_CROSS_AGENT=1 EXPERT_CLI= bash -c \
    'source "$1"; select_agent_backend claude; printf "%s" "$AGENT_BACKEND"' _ "$HELPER")
[[ "$actual" == "claude" ]] || { echo "显式跨 agent 兼容模式失败" >&2; exit 1; }

capture_log=$(mktemp)
trap 'rm -f -- "$capture_log"' EXIT
{
    source "$HELPER"
    timeout() { printf '%q ' "$@"; cat >/dev/null; }
    invoke_model_agent codex /tmp/out "$capture_log" 30 model-x <<<prompt
}
capture=$(<"$capture_log")
[[ "$capture" == *"--sandbox read-only"* \
   && "$capture" == *"mcp_servers="* \
   && "$capture" == *"web_search="* \
   && "$capture" == *"--disable code_mode_host"* \
   && "$capture" == *"--disable shell_tool"* \
   && "$capture" != *"danger-full-access"* ]] || {
    echo "Codex worker 未保持 fail-closed 无工具只读策略: $capture" >&2
    exit 1
}

preflight_capture=$(mktemp)
trap 'rm -f -- "$capture_log" "$preflight_capture"' EXIT
{
    source "$HELPER"
    timeout() { shift; "$@"; }
    codex() {
        printf '%q ' "$@" >>"$preflight_capture"
        if [[ "$1" == "exec" && "$2" == "--help" ]]; then
            printf '%s\n' '--strict-config --sandbox --ephemeral --ignore-rules'
        elif [[ "$1" == "exec" ]]; then
            printf '%s\n' 'Output schema file /dev/null is not valid JSON' >&2
            return 1
        fi
    }
    validate_agent_backend codex model-y
}
preflight=$(<"$preflight_capture")
[[ "$preflight" == *"--output-schema /dev/null"* \
   && "$preflight" == *"-m model-y"* \
   && "$preflight" == *"--disable code_mode_host"* ]] || {
    echo "Codex 后端兼容预检未覆盖实际隔离参数: $preflight" >&2
    exit 1
}

{
    source "$HELPER"
    timeout() { printf '%q ' "$@"; cat >/dev/null; }
    invoke_model_agent claude "$capture_log" /tmp/log 30 <<<prompt
}
capture=$(<"$capture_log")
[[ "$capture" == *"--tools ''"* && "$capture" == *"--no-session-persistence"* ]] || {
    echo "Claude worker 未保持无工具策略: $capture" >&2
    exit 1
}

echo "agent backend tests: PASS"
