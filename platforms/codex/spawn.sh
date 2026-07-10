#!/usr/bin/env bash
# platforms/codex/spawn.sh — Codex 子 Agent spawn 实现
# 用法: source 本文件后调用 spawn_expert 和 spawn_reviewer 函数
# Contract: 与 platforms/claude/spawn.sh 保持相同接口

SKILL_ROOT="/home/bazinga/invest-skill"

spawn_expert() {
    local PROMPT_FILE="$1"
    local OUTPUT_FILE="$2"
    local EXPERT_ID="$3"

    codex exec -c workdir="${SKILL_ROOT}" \
        < "$PROMPT_FILE" \
        > "$OUTPUT_FILE" \
        2>/tmp/invest_stderr_${EXPERT_ID}.log

    echo "[DONE] ${EXPERT_ID}"
}

spawn_reviewer() {
    local REVIEWER_NUM="$1"
    local PROMPT_FILE="$2"
    local OUTPUT_FILE="$3"

    codex exec -c workdir="${SKILL_ROOT}" \
        < "$PROMPT_FILE" \
        > "$OUTPUT_FILE" \
        2>/tmp/invest_stderr_review_${REVIEWER_NUM}.log

    echo "[DONE] 评审员 #${REVIEWER_NUM}"
}
