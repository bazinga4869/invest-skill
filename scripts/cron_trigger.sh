#!/bin/bash
# cron_trigger.sh — cron 定时触发每日自动分析
# 触发: 每天 10:00 / 14:30（见 crontab）
# 健壮性: 前置检查 + 脚本保证确定性步骤 + codex exec 负责认知步骤 + 超时(TERM→KILL) + 重试 + 结构化日志
#
# 设计变更 2026-07-27:
#   原来把完整 pipeline 交给一个 agent 会话执行，agent 经常在数据同步/验证后只输出文字就停止，
#   导致误报成功。现在改为"混合驱动"：
#     - cron_trigger.sh 自己完成选股、数据同步、prepare_prompts 等确定性步骤
#     - codex exec 负责 run_experts → run_challenges → 裁判长裁决 → finalize
#     - 成功判定要求 CRON_DONE、正式报告、事实核查 PASS 和审计清单归档同时成立

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$SKILL_DIR/logs"
TIMESTAMP=$(date '+%Y%m%d_%H%M')
LOG_FILE="$LOG_DIR/cron_${TIMESTAMP}.log"
PROMPT_FILE="$SCRIPT_DIR/cron_prompt.txt"
MAX_RETRIES=1
# 真管线耗时：年报首次下载 ~5-10min + 7 专家 30-45min + 裁判长/报告 ~10min
TIMEOUT_MINUTES=${TIMEOUT_MINUTES:-120}
TODAY_ISO=$(date +%Y-%m-%d)

# cron 环境 PATH 极简（/usr/bin:/bin），补上 CLI 常见安装位置
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

# 前置检查
command -v codex &>/dev/null || { echo "ERROR: 需要 codex CLI 来执行分析" >&2; exit 2; }

mkdir -p "$LOG_DIR"
cd "$SKILL_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# 选股：排除科创/北交/ST，按 auto_state 轮转
select_stock() {
    python3 - <<'PYEOF'
import json, datetime, sys
pool = json.load(open('data/stock_pool.json'))
valid = [s for s in pool
         if not s['ts_code'].startswith('688')
         and not s['ts_code'].startswith('8')
         and 'ST' not in s.get('name', '')]
state = json.load(open('data/auto_state.json'))
idx = state.get('next_index', 0)
last = state.get('last_analyzed', {})
today = datetime.date.today()
n = len(valid)
for off in range(n):
    i = (idx + off) % n
    s = valid[i]
    d = last.get(s['ts_code'])
    if d is None or (today - datetime.date.fromisoformat(d)).days > 5:
        print(f"{s['ts_code']}\t{s.get('name', '')}\t{i}")
        sys.exit(0)
print("NO_STOCK")
sys.exit(1)
PYEOF
}

# 检查是否已有完整专家结果（断点命中可跳到裁判长阶段）
has_complete_results() {
    local code="$1"
    local data_file="/tmp/invest_data_${code}.json"
    if [[ ! -f "$data_file" ]]; then
        return 1
    fi
    python3 scripts/collect_results.py "$code" --check &>/dev/null
}

has_complete_challenges() {
    local code="$1"
    python3 scripts/collect_challenges.py "$code" &>/dev/null
}

# 数据同步
run_sync() {
    local code="$1"
    log "  [前置] 数据同步 $code ..."
    python3 shared/data_tools.py sync "$code" >> "$LOG_FILE" 2>&1
}

# 验证数据新鲜度
verify_data_fresh() {
    local code="$1"
    local trade_date
    trade_date=$(python3 -c "import json; print(json.load(open('/tmp/invest_data_${code}.json')).get('market',{}).get('trade_date',''))" 2>/dev/null || true)
    if [[ -z "$trade_date" ]]; then
        log "✗ 无法读取 market.trade_date"
        return 1
    fi
    log "  [前置] 数据基准日: $trade_date"
    # sync 已在前置步骤执行；这里只容纳周末/长假，不把该窗口当作免同步缓存期。
    local td_epoch today_epoch
    td_epoch=$(date -d "${trade_date:0:4}-${trade_date:4:2}-${trade_date:6:2}" +%s 2>/dev/null || echo 0)
    today_epoch=$(date +%s)
    local days_diff=$(( (today_epoch - td_epoch) / 86400 ))
    if [[ $days_diff -gt 7 ]]; then
        log "✗ 数据陈旧（$days_diff 天前），超过 7 天节假日容忍窗口"
        return 1
    fi
    return 0
}

# 生成 prompt
run_prepare_prompts() {
    local code="$1"
    log "  [前置] 生成专家 prompt $code ..."
    python3 scripts/prepare_prompts.py "$code" >> "$LOG_FILE" 2>&1
}

# 构造传给 agent 的 prompt：前置状态 + 原始 prompt，要求 agent 直接从 Step 3 开始
build_agent_prompt() {
    local code="$1"
    local name="$2"
    local resume_ready="${3:-0}"
    local agent_prompt="/tmp/cron_agent_prompt_${TIMESTAMP}.txt"

    local data_file="/tmp/invest_data_${code}.json"
    local prompts_ready="否"
    if ls "/tmp/invest_prompt_${code}_"*.txt &>/dev/null; then
        prompts_ready="是"
    fi

    {
        echo "## 前置状态（由 cron_trigger.sh 预先完成，你不需要重做）"
        echo ""
        echo "- 已选中标的：$code $name"
        echo "- 已执行数据同步：$data_file"
        echo "- 专家 prompt 已生成：$prompts_ready"
        echo "- 当前日期：$TODAY_ISO"
        echo ""
        echo "## 你的起始点"
        echo ""
        echo "你**不需要**执行 Step 0 选股、Step 1 数据同步、Step 2 prepare_prompts。"
        if [[ "$resume_ready" == "2" ]]; then
            echo "7 份专家结果已通过校验。直接从 **Step 5 裁判长综合裁决**开始，不得重跑或删除专家结果。"
        elif [[ "$resume_ready" == "1" ]]; then
            echo "7 份专家结果已通过，但二级质询未齐。直接从 **Step 4.5** 开始："
            echo ""
            echo "\`\`\`bash"
            echo "bash scripts/run_challenges.sh $code"
            echo "\`\`\`"
        else
            echo "直接从 **Step 3** 开始："
            echo ""
            echo "\`\`\`bash"
            echo "bash scripts/run_experts.sh $code --no-prepare"
            echo "\`\`\`"
        fi
        echo ""
        echo "然后按顺序执行 Step 4 校验 → Step 4.5 质询 → Step 5 裁判长裁决 → Step 6 草稿 → Step 7 自评审 → --finalize 门禁 → 输出 CRON_DONE。"
        echo "不要更新 auto_state，不要清理 /tmp；cron_trigger.sh 会在独立复核报告通过后负责这两步。"
        echo ""
        echo "---"
        echo ""
    } > "$agent_prompt"
    cat "$PROMPT_FILE" >> "$agent_prompt"
    echo "$agent_prompt"
}

# codex exec 会话：跑 run_experts → run_challenges → 裁判长 → finalize
run_once() {
    local agent_prompt="$1"
    local secs=$((TIMEOUT_MINUTES * 60))
    timeout -k 30 "$secs" codex exec --sandbox danger-full-access - \
        < "$agent_prompt" >> "$LOG_FILE" 2>&1
}

# 从日志解析 CRON_DONE
check_cron_done() {
    grep -E '^CRON_DONE [0-9]{6}\.(SH|SZ|BJ) (BUY|SELL|HOLD|PASS|OBSERVE) ([0-9]|[1-9][0-9]|100)$' "$LOG_FILE" | tail -n 1 || true
}

# 更新 auto_state.json
update_auto_state() {
    local code="$1"
    local name="$2"
    local rating="$3"
    local score="$4"
    python3 - <<PYEOF
import json, datetime
state_path = 'data/auto_state.json'
state = json.load(open(state_path))
state['last_analyzed']['$code'] = '$TODAY_ISO'
# 重新计算 valid pool size，避免硬编码
pool = json.load(open('data/stock_pool.json'))
valid_n = len([s for s in pool
               if not s['ts_code'].startswith('688')
               and not s['ts_code'].startswith('8')
               and 'ST' not in s.get('name', '')])
state['next_index'] = (${SELECTED_INDEX} + 1) % valid_n
entry = {
    'ts_code': '$code',
    'name': '$name',
    'date': '$TODAY_ISO',
    'rating': '$rating',
    'score': $score,
    'next_index': state['next_index'],
    'source': 'invest_tool'
}
if 'history' not in state:
    state['history'] = []
state['history'].append(entry)
with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
print('auto_state updated')
PYEOF
}

# 清理中间文件
cleanup_tmp() {
    local code="$1"
    rm -f /tmp/invest_prompt_${code}_*.txt
    rm -f /tmp/invest_result_${code}_*.md
    rm -f /tmp/invest_challenge_prompt_${code}_*.txt
    rm -f /tmp/invest_challenge_result_${code}_*.md
    rm -f /tmp/invest_cross_prompt_${code}_*.txt
    rm -f /tmp/invest_cross_result_${code}_*.md
    rm -f "/tmp/invest_level3_${code}.json"
    rm -f "/tmp/invest_cross_blind_${code}.md"
    rm -f /tmp/invest_annual_${code}.txt
    rm -f /tmp/invest_data_${code}.json
    rm -f "reports/invest_tool/${code}.draft.md"
    rm -f "/tmp/cron_agent_prompt_${TIMESTAMP}.txt"
    log "  [清理] 已清理 /tmp/invest_*${code}* 中间文件"
}

# ═══════════════════════════════════════════════════════
log "═══ cron_trigger 开始 ═══"

# ─── 前置检查 ─────────────────────────────────────────────
if [[ ! -f "$PROMPT_FILE" ]]; then
    log "✗ prompt 文件不存在: $PROMPT_FILE"
    exit 1
fi
if [[ ! -s "$PROMPT_FILE" ]]; then
    log "✗ prompt 文件为空"
    exit 1
fi

log "prompt: $PROMPT_FILE ($(wc -l < "$PROMPT_FILE") 行)"

# ─── Step 0：选股 ────────────────────────────────────────
log "[Step 0] 选股 ..."
SELECTED=$(select_stock)
if [[ "$SELECTED" == "NO_STOCK" ]] || [[ -z "$SELECTED" ]]; then
    log "✗ 未找到可分析标的"
    exit 1
fi
CODE=$(echo "$SELECTED" | awk -F'\t' '{print $1}')
NAME=$(echo "$SELECTED" | awk -F'\t' '{print $2}')
SELECTED_INDEX=$(echo "$SELECTED" | awk -F'\t' '{print $3}')
log "  选中: $CODE $NAME (index=$SELECTED_INDEX)"

# ─── Step 0.5：断点检查 ──────────────────────────────────
log "[Step 0.5] 断点检查 ..."
RESUME_READY=0
if has_complete_results "$CODE" && verify_data_fresh "$CODE"; then
    if has_complete_challenges "$CODE"; then
        log "  断点命中：数据、专家结果与质询 7/7 已就绪，进入裁判长阶段"
        RESUME_READY=2
    else
        log "  部分断点：专家结果 7/7 已就绪，从二级质询继续"
        RESUME_READY=1
    fi
else
    log "  无断点，按正常管线执行"
fi

if [[ $RESUME_READY -eq 0 ]]; then
    # ─── Step 1：数据同步 ────────────────────────────────────
    log "[Step 1] 数据同步 $CODE ..."
    if ! run_sync "$CODE"; then
        log "✗ 数据同步失败"
        echo "CRON_FAIL $CODE 数据同步失败" | tee -a "$LOG_FILE"
        exit 1
    fi

    # ─── Step 2：生成并验证同批次快照/prompt ───────────────
    log "[Step 2] 生成专家 prompt $CODE ..."
    if ! run_prepare_prompts "$CODE"; then
        log "✗ prompt 生成失败"
        source scripts/activity_log.sh && log_activity prompt "$CODE" "$NAME" failure "prepare_prompts失败"
        echo "CRON_FAIL $CODE prepare_prompts失败" | tee -a "$LOG_FILE"
        exit 1
    fi
    if ! verify_data_fresh "$CODE"; then
        log "✗ 数据不可用，本次分析失败"
        source scripts/activity_log.sh && log_activity prompt "$CODE" "$NAME" failure "数据不可用或陈旧"
        echo "CRON_FAIL $CODE 数据不可用或陈旧" | tee -a "$LOG_FILE"
        exit 1
    fi
    if ! ls "/tmp/invest_prompt_${CODE}_"*.txt &>/dev/null; then
        log "✗ prompt 文件缺失"
        exit 1
    fi
    log "  ✓ 数据快照与 prompt 已生成"
fi

# ─── Step 3-10：交给 agent ───────────────────────────────
log "[Step 3-10] 启动 codex 会话（run_experts → run_challenges → 裁判长 → 定稿）..."

attempt=0
RC=1
PIPELINE_VERIFIED=0
while [[ $attempt -le $MAX_RETRIES ]]; do
    log "  尝试 $((attempt + 1))/$((MAX_RETRIES + 1)) ..."

    if has_complete_results "$CODE" && verify_data_fresh "$CODE"; then
        if has_complete_challenges "$CODE"; then RESUME_READY=2; else RESUME_READY=1; fi
    else
        RESUME_READY=0
    fi
    AGENT_PROMPT=$(build_agent_prompt "$CODE" "$NAME" "$RESUME_READY")

    run_once "$AGENT_PROMPT"
    RC=$?

    DONE_LINE=$(check_cron_done)
    if [[ $RC -eq 0 ]] && [[ -n "$DONE_LINE" ]]; then
        DONE_CODE=$(echo "$DONE_LINE" | awk '{print $2}')
        RATING=$(echo "$DONE_LINE" | awk '{print $3}')
        SCORE=$(echo "$DONE_LINE" | awk '{print $4}')
        REPORT_FILE="$SKILL_DIR/reports/invest_tool/${DONE_CODE}.md"
        if [[ "$DONE_CODE" == "$CODE" ]] && [[ -s "$REPORT_FILE" ]] \
            && python3 scripts/verify_report.py "$REPORT_FILE" --data "/tmp/invest_data_${CODE}.json" --strict >> "$LOG_FILE" 2>&1 \
            && python3 scripts/verify_manifest.py "$REPORT_FILE" >> "$LOG_FILE" 2>&1; then
            log "✓ agent 阶段完成 (exit=$RC, code=$DONE_CODE, rating=$RATING, score=$SCORE)"
            PIPELINE_VERIFIED=1
            break
        else
            log "✗ agent 声称完成但报告异常: $DONE_LINE"
        fi
    elif [[ $RC -eq 0 ]]; then
        log "✗ agent exit 0 但无有效 CRON_DONE（中途静默终止）"
    else
        log "✗ agent 失败 (exit=$RC, timeout=$([ $RC -eq 124 ] && echo yes || echo no))"
    fi
    attempt=$((attempt + 1))
    # 专家层已经在单会话内有界重试；外层只允许在 7/7 结果已就绪时重试裁决/发布。
    if [[ $attempt -le $MAX_RETRIES ]] && ! has_complete_results "$CODE"; then
        log "✗ 专家结果仍不完整，不再启动第二轮整会话重跑"
        break
    fi
done

if [[ $PIPELINE_VERIFIED -ne 1 ]]; then
    log "═══ agent 阶段失败，放弃 ═══"
    source scripts/activity_log.sh && log_activity report "$CODE" "$NAME" failure "agent阶段失败或静默终止"
    echo "CRON_FAIL $CODE agent阶段失败" | tee -a "$LOG_FILE"
    [[ $RC -eq 0 ]] && exit 1
    exit "$RC"
fi

# ─── Step 8：更新状态与日志 ──────────────────────────────
log "[Step 8] 更新状态与活动日志 ..."
if ! update_auto_state "$CODE" "$NAME" "$RATING" "$SCORE"; then
    log "✗ auto_state 更新失败；保留中间文件供恢复"
    source scripts/activity_log.sh && log_activity report "$CODE" "$NAME" failure "auto_state更新失败"
    echo "CRON_FAIL $CODE auto_state更新失败" | tee -a "$LOG_FILE"
    exit 1
fi
source scripts/activity_log.sh && log_activity report "$CODE" "$NAME" success "$RATING ${SCORE}分"

# ─── Step 9：清理 ────────────────────────────────────────
cleanup_tmp "$CODE"

# ─── Step 10：完成标记（再次确认已输出）────────────────────
if ! check_cron_done | grep -q "$CODE"; then
    echo "CRON_DONE $CODE $RATING $SCORE" | tee -a "$LOG_FILE"
fi

log "✓ 全部完成 (code=$CODE, rating=$RATING, score=$SCORE)"
exit 0
