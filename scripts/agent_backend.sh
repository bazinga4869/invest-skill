#!/usr/bin/env bash
# 显式外部 CLI 兼容层；禁止自动选择，正常流程使用宿主原生子代理。

detect_host_agent() {
    case "${INVEST_HOST_AGENT:-}" in
        codex|claude) printf '%s\n' "$INVEST_HOST_AGENT"; return 0 ;;
        "") ;;
        *)
            echo "ERROR: INVEST_HOST_AGENT 只支持 codex / claude" >&2
            return 2
            ;;
    esac

    if [[ -n "${CODEX_THREAD_ID:-}" || -n "${CODEX_CI:-}" || -n "${CODEX_MANAGED_BY_NPM:-}" ]]; then
        printf 'codex\n'
        return 0
    fi
    if [[ -n "${CLAUDECODE:-}" || -n "${CLAUDE_CODE_ENTRYPOINT:-}" ]]; then
        printf 'claude\n'
        return 0
    fi

    local pid="$PPID" comm parent
    local depth=0
    while [[ "$pid" =~ ^[0-9]+$ ]] && (( pid > 1 && depth < 12 )); do
        comm=$(ps -o comm= -p "$pid" 2>/dev/null | tr -d '[:space:]')
        case "$comm" in
            codex|codex-*) printf 'codex\n'; return 0 ;;
            claude|claude-*) printf 'claude\n'; return 0 ;;
        esac
        parent=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d '[:space:]')
        [[ -n "$parent" ]] || break
        pid="$parent"
        depth=$((depth + 1))
    done

    printf 'unknown\n'
}

select_agent_backend() {
    local cli_override="${1:-}"
    local env_override="${EXPERT_CLI:-}"

    AGENT_HOST=$(detect_host_agent) || return $?
    if [[ -n "$cli_override" ]]; then
        AGENT_BACKEND="$cli_override"
        AGENT_BACKEND_SOURCE="--agent"
    elif [[ -n "$env_override" ]]; then
        AGENT_BACKEND="$env_override"
        AGENT_BACKEND_SOURCE="EXPERT_CLI"
    else
        echo "ERROR: shell 外部 CLI worker 已停用自动选择。" >&2
        echo "请由当前主 agent 使用原生子代理能力，并运行 native_agent_tasks.py；" >&2
        echo "不要从 DSH/Codex/Claude 主会话另启其他产品 CLI。" >&2
        return 2
    fi

    if [[ "${INVEST_ALLOW_EXTERNAL_AGENT:-0}" != "1" ]]; then
        echo "ERROR: 外部 $AGENT_BACKEND CLI 仅为显式兼容模式，默认禁用。" >&2
        echo "如确需外部进程，必须同时设置 INVEST_ALLOW_EXTERNAL_AGENT=1；" >&2
        echo "正常流程应使用主 agent 的原生子代理并继承其 provider/model。" >&2
        return 2
    fi

    case "$AGENT_BACKEND" in
        codex|claude) ;;
        *)
            echo "ERROR: agent 后端只支持 codex / claude，实际为: $AGENT_BACKEND" >&2
            return 2
            ;;
    esac

    if [[ "$AGENT_HOST" != "unknown" && "$AGENT_BACKEND" != "$AGENT_HOST" \
          && "${INVEST_ALLOW_CROSS_AGENT:-0}" != "1" ]]; then
        echo "ERROR: 检测到宿主 $AGENT_HOST，但请求启动 $AGENT_BACKEND。" >&2
        echo "默认必须使用同源 agent；仅当用户明确要求跨后端时设置 INVEST_ALLOW_CROSS_AGENT=1。" >&2
        return 2
    fi
}

# Codex has no supported global empty-tool-list override. Keep every known tool
# family disabled and turn off the code-mode host so any placeholder tool call
# fails closed. The orchestrator owns all file I/O; workers receive one prompt
# on stdin and return one document only.
build_codex_isolation_args() {
    INVEST_CODEX_CONFIG_ARGS=(
        -c 'mcp_servers={}'
        -c 'web_search="disabled"'
        --disable shell_tool
        --disable unified_exec
        --disable view_image
        --disable code_mode
        --disable code_mode_host
        --disable apps
        --disable browser_use
        --disable browser_use_external
        --disable browser_use_full_cdp_access
        --disable computer_use
        --disable image_generation
        --disable multi_agent
        --disable multi_agent_v2
        --disable goals
        --disable plugins
        --disable skill_search
        --disable skill_mcp_dependency_install
        --disable tool_suggest
        --disable tool_call_mcp_elicitation
        --disable auth_elicitation
        --disable default_mode_request_user_input
        --disable guardian_approval
    )
}

# Zero-model-call compatibility gate. Run this before claiming a retry. The
# deliberately invalid output schema makes `codex exec` stop after strict config
# and CLI validation, before any request is sent to the model provider.
validate_agent_backend() {
    local backend="$1" model="${2:-}"
    case "$backend" in
        codex)
            local help_text preflight_output
            local -a model_arg=()
            [[ -n "$model" ]] && model_arg=(-m "$model")
            if ! help_text=$(codex exec --help 2>&1); then
                echo "ERROR: 无法读取 codex exec 帮助，后端预检失败。" >&2
                return 2
            fi
            local required_flag
            for required_flag in --strict-config --sandbox --ephemeral --ignore-rules; do
                if [[ "$help_text" != *"$required_flag"* ]]; then
                    echo "ERROR: 当前 Codex CLI 不支持 $required_flag，后端预检失败。" >&2
                    return 2
                fi
            done
            build_codex_isolation_args
            if preflight_output=$(timeout 15 codex exec \
                --strict-config --sandbox read-only --ephemeral --ignore-rules \
                --skip-git-repo-check --output-schema /dev/null \
                "${INVEST_CODEX_CONFIG_ARGS[@]}" "${model_arg[@]}" \
                'invest-backend-preflight' </dev/null 2>&1); then
                echo "ERROR: Codex 后端预检未按预期在模型调用前停止。" >&2
                return 2
            fi
            if [[ "$preflight_output" != *"Output schema file /dev/null is not valid JSON"* ]]; then
                echo "ERROR: 当前 Codex CLI 不支持所需的无工具隔离参数；未启动模型，也未消耗重试。" >&2
                printf '%s\n' "$preflight_output" >&2
                return 2
            fi
            ;;
        claude)
            local claude_help
            if ! claude_help=$(claude --help 2>&1); then
                echo "ERROR: 无法读取 claude 帮助，后端预检失败。" >&2
                return 2
            fi
            [[ "$claude_help" == *"--tools"* && "$claude_help" == *"--no-session-persistence"* ]] || {
                echo "ERROR: 当前 Claude CLI 不支持所需的无工具隔离参数；未启动模型，也未消耗重试。" >&2
                return 2
            }
            ;;
        *)
            echo "ERROR: 不支持的 agent 后端: $backend" >&2
            return 2
            ;;
    esac
}

invoke_model_agent() {
    local backend="$1" output="$2" log="$3" timeout_seconds="$4" model="${5:-}"
    local -a model_arg=()
    local -a claude_model_arg=()
    [[ -n "$model" ]] && model_arg=(-m "$model")
    [[ -n "$model" ]] && claude_model_arg=(--model "$model")
    case "$backend" in
        codex)
            build_codex_isolation_args
            # --skip-git-repo-check 与预检一致：worker 目录（skill 仓库）不在
            # ~/.codex/config.toml 受信任列表，非交互 exec 会拒绝启动。
            timeout "$timeout_seconds" codex exec \
                -o "$output" --strict-config --sandbox read-only --ephemeral --ignore-rules \
                --skip-git-repo-check \
                "${INVEST_CODEX_CONFIG_ARGS[@]}" "${model_arg[@]}" - >"$log" 2>&1
            ;;
        claude)
            timeout "$timeout_seconds" claude --bare --no-session-persistence \
                --tools "" "${claude_model_arg[@]}" -p >"$output" 2>"$log"
            ;;
        *)
            echo "ERROR: 不支持的 agent 后端: $backend" >&2
            return 2
            ;;
    esac
}

record_agent_execution() {
    local script_dir="$1" code="$2" phase="$3" backend="$4" host="$5"
    local concurrency="$6" timeout_seconds="$7" repair_max_passes="${8:-}"
    local -a repair_arg=()
    [[ -n "$repair_max_passes" ]] && repair_arg=(--repair-max-passes "$repair_max_passes")
    python3 "$script_dir/execution_provenance.py" "$code" "$phase" \
        --backend "$backend" --host "$host" --model "${EXPERT_MODEL:-default}" \
        --concurrency "$concurrency" --timeout "$timeout_seconds" "${repair_arg[@]}"
}
