#!/usr/bin/env bash
# platforms/codex/spawn.sh — Codex 子 Agent spawn 实现
# 用法: source 本文件后调用 spawn_expert 和 spawn_reviewer 函数
# Contract: 与 platforms/claude/spawn.sh 保持相同接口

spawn_expert() {
    local PROMPT_FILE="$1"
    local OUTPUT_FILE="$2"
    local EXPERT_ID="$3"

    # codex exec 从 stdin 读取 prompt，若需要从文件读可用 --image 或重定向
    codex exec < "$PROMPT_FILE" > "$OUTPUT_FILE" 2>/tmp/invest_stderr_${EXPERT_ID}.log

    echo "[DONE] ${EXPERT_ID}"
}

spawn_reviewer() {
    local REVIEWER_NUM="$1"
    local PROMPT_FILE="$2"
    local OUTPUT_FILE="$3"

    codex exec < "$PROMPT_FILE" > "$OUTPUT_FILE" 2>/tmp/invest_stderr_review_${REVIEWER_NUM}.log

    echo "[DONE] 评审员 #${REVIEWER_NUM}"
}

# Codex 不需要 --permission-mode bypassPermissions，权限由 ~/.codex/rules/ 管理
# 如需指定 model，可在调用前 export CODEX_MODEL="..."
# 如需指定 config: codex exec -c workdir=/path ...
