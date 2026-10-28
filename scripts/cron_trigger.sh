#!/bin/bash
# cron_trigger.sh — 每日自动分析执行器（被调用方；不持有定时配置）
# 触发: 宿主 invest-harness 的 crontab 经 ~/invest-harness/scripts/cron/cron_daily_analysis.sh
#       调用（02:00 / 04:30，DeepSeek API 低谷期 00:30-08:30 内执行，享 50% 折扣）
# 健壮性: 前置检查 + 脚本保证确定性步骤 + DSH headless 会话负责认知步骤 + 超时(TERM→KILL) + 重试 + 结构化日志
#
# 生产边界：外层 shell 只负责选股、数据同步、prompt 准备、状态更新和独立复核；
# 认知步骤全部在当前 host-native DSH headless 会话中执行。cron_prompt.txt 要求该主会话
# 通过 native_agent_tasks.py 委派当前主 agent 的原生子代理，完成专家、质询、裁判和定稿；
# 生产路径绝不探测、调用或 fallback 到 Codex/Claude/其他外部 worker。
# 成功判定要求 CRON_DONE、正式报告、事实核查 PASS 和 manifest 复核同时成立。
# 选股读 SQLite stocks 表（原 data/stock_pool.json 为无生产者的遗留文件），
# data/auto_state.json 缺失时自动重建默认状态。

set -u
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
# DSH headless 会话认证密钥 + 运行时根配置（cron 环境不含 ~/.bashrc；密钥文件 0600）
if [[ -f "$HOME/.config/invest-skill.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$HOME/.config/invest-skill.env"
    set +a
else
    echo "WARN: 未找到 $HOME/.config/invest-skill.env（DEEPSEEK_API_KEY），headless 会话可能认证失败" >&2
fi

# 运行时根：DB/日志/报告/状态文件写入调用方指定的 INVEST_SKILL_HOME，
# 不回写 skill 仓库（skill 只含资产）。未设置时回退 skill 目录（向后兼容）。
RUNTIME_ROOT="${INVEST_SKILL_HOME:-$(cd "$SKILL_DIR" && python3 -c 'from shared.project_config import runtime_root; print(runtime_root())')}"
export INVEST_SKILL_HOME="$RUNTIME_ROOT"
# Keep transient prompts/results beside the configured runtime artifacts.
RUNTIME_DIR="${INVEST_RUNTIME_DIR:-$RUNTIME_ROOT}"
export INVEST_RUNTIME_DIR="$RUNTIME_DIR"
# 运行时根防护：禁止把运行时产物写回 skill 仓库（INVEST_ALLOW_SKILL_RUNTIME=1 显式逃逸）
if [[ "$RUNTIME_ROOT" == "$SKILL_DIR" && "${INVEST_ALLOW_SKILL_RUNTIME:-0}" != "1" ]]; then
    echo "ERROR: 未设置 INVEST_SKILL_HOME，运行时产物将写回 skill 仓库（违反只读契约）。" >&2
    echo "       请 export INVEST_SKILL_HOME=<宿主运行时目录>（或 INVEST_ALLOW_SKILL_RUNTIME=1 显式允许）。" >&2
    exit 2
fi
LOG_DIR="${INVEST_LOG_DIR:-$RUNTIME_ROOT/logs}"
DB_PATH="${INVEST_DB_PATH:-$(cd "$SKILL_DIR" && python3 -c 'from shared.project_config import configured_path; print(configured_path("db_file", "./data/invest_skill.db"))')}"
export INVEST_DB_PATH="$DB_PATH"
AUTO_STATE_FILE="$RUNTIME_ROOT/data/auto_state.json"
export AUTO_STATE_FILE
REPORTS_DIR="${INVEST_REPORTS_DIR:-$(cd "$SKILL_DIR" && python3 -c 'from shared.project_config import configured_path; print(configured_path("invest_tool_dir", "./reports/invest_tool"))')}"
TIMESTAMP=$(date '+%Y%m%d_%H%M')
LOG_FILE="$LOG_DIR/cron_${TIMESTAMP}.log"
PROMPT_FILE="$SCRIPT_DIR/cron_prompt.txt"
MAX_RETRIES=1
# 真管线耗时：report-wiki 首次建库耗时不定 + 7 专家 30-45min + 裁判长/报告 ~10min
TIMEOUT_MINUTES=${TIMEOUT_MINUTES:-120}
TODAY_ISO=$(date +%Y-%m-%d)

# cron 环境 PATH 极简（/usr/bin:/bin），补上 CLI 常见安装位置
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

# 前置检查
command -v dsh &>/dev/null || { echo "ERROR: 需要 dsh CLI 来执行 host-native headless 会话" >&2; exit 2; }

mkdir -p "$LOG_DIR" "$RUNTIME_ROOT/data"
cd "$SKILL_DIR"
REPORT_WIKI_CLI="$(python3 -c 'from shared.project_config import report_wiki_cli; print(report_wiki_cli())')"
[[ -x "$REPORT_WIKI_CLI" ]] || {
    echo "ERROR: report-wiki CLI 未就绪: $REPORT_WIKI_CLI" >&2
    exit 2
}

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# 失败告警：写 alert.jsonl + hermes 推送（不阻塞主流程）
alert() { # phase code reason
    bash "$SCRIPT_DIR/alert.sh" "$1" "$2" "$3" >> "$LOG_FILE" 2>&1 || true
}

# 选股：从 SQLite stocks 表（排除科创/北交/ST），按 auto_state 轮转；状态文件缺失时自愈
# 路径来自环境变量（cron_trigger 顶部解析到运行时根），不回写 skill 仓库
select_stock() {
    python3 - <<'PYEOF'
import json, datetime, os, sqlite3, sys
db = sqlite3.connect(os.environ.get('INVEST_DB_PATH', 'data/invest_skill.db'))
rows = db.execute("""
    SELECT ts_code, name FROM stocks
    WHERE name IS NOT NULL AND name != ''
    AND ts_code NOT LIKE '688%'
    AND ts_code NOT LIKE '8%'
    AND name NOT LIKE '%ST%'
    AND ts_code NOT LIKE '%ST%'
    ORDER BY ts_code
""").fetchall()
db.close()
if not rows:
    print("NO_STOCK")
    sys.exit(1)
state_path = os.environ.get('AUTO_STATE_FILE', 'data/auto_state.json')
if os.path.exists(state_path):
    state = json.load(open(state_path, encoding='utf-8'))
else:
    state = {'next_index': 0, 'last_analyzed': {}, 'history': []}
    json.dump(state, open(state_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print("auto_state 缺失，已重建默认状态", file=sys.stderr)
idx = state.get('next_index', 0)
last = state.get('last_analyzed', {})
today = datetime.date.today()
n = len(rows)
for off in range(n):
    i = (idx + off) % n
    code, name = rows[i]
    d = last.get(code)
    if d is None or (today - datetime.date.fromisoformat(d)).days > 5:
        print(f"{code}\t{name}\t{i}")
        sys.exit(0)
print("NO_STOCK")
sys.exit(1)
PYEOF
}

# 检查是否已有完整专家结果（断点命中可跳到裁判长阶段）
has_complete_results() {
    local code="$1"
    local data_file="$RUNTIME_DIR/invest_data_${code}.json"
    if [[ ! -f "$data_file" ]]; then
        return 1
    fi
    python3 scripts/collect_results.py "$code" --check &>/dev/null
}

has_complete_challenges() {
    local code="$1"
    python3 scripts/collect_challenges.py "$code" &>/dev/null
}

# 验证数据新鲜度
verify_data_fresh() {
    local code="$1"
    local trade_date
    trade_date=$(python3 -c "import json; print(json.load(open('$RUNTIME_DIR/invest_data_${code}.json')).get('market',{}).get('trade_date',''))" 2>/dev/null || true)
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
    python3 scripts/prepare_prompts.py "$code" --force-sync --include-semiannual --semi-years 2 >> "$LOG_FILE" 2>&1
}

# 构造传给 agent 的 prompt：前置状态 + 原始 prompt，要求 agent 直接从 Step 3 开始
build_agent_prompt() {
    local code="$1"
    local name="$2"
    local resume_ready="${3:-0}"
    local agent_prompt="$RUNTIME_DIR/cron_agent_prompt_${TIMESTAMP}.txt"

    local data_file="$RUNTIME_DIR/invest_data_${code}.json"
    local prompts_ready="否"
    if ls "$RUNTIME_DIR/invest_prompt_${code}_"*.txt &>/dev/null; then
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
            echo "python3 scripts/native_agent_tasks.py begin challenges $code"
            echo "# 按 jobs[] 使用当前主 agent 原生子代理，逐项 commit 后 advance"
            echo "\`\`\`"
        else
            echo "直接从 **Step 3** 开始："
            echo ""
            echo "\`\`\`bash"
            echo "python3 scripts/native_agent_tasks.py begin experts $code"
            echo "# 按 jobs[] 使用当前主 agent 原生子代理，逐项 commit 后 advance"
            echo "\`\`\`"
        fi
        echo ""
        echo "然后按顺序执行 Step 4 校验 → Step 4.5 质询 → Step 5 裁判长裁决 → Step 6 草稿 → Step 7 自评审 → --finalize 门禁 → 输出 CRON_DONE。"
        echo "不要更新 auto_state，不要清理 $RUNTIME_DIR；cron_trigger.sh 会在独立复核报告通过后负责这两步。"
        echo ""
        echo "你可以通过 skill 工具加载 invest-skill（如可用）获取完整 7+1 协议与门禁要求；本 prompt 已包含全部执行步骤。"
        echo ""
        echo "---"
        echo ""
    } > "$agent_prompt"
    cat "$PROMPT_FILE" >> "$agent_prompt"
    echo "$agent_prompt"
}

# host-native DSH headless 会话：主 agent 原生子代理完成 experts/challenges/cross-reviews、裁判和 finalize。
# 外层只消费 CRON_DONE，并对正式报告执行独立 verify_report/verify_manifest 复核。
run_once() {
    local agent_prompt="$1"
    local secs=$((TIMEOUT_MINUTES * 60))
    timeout -k 30 "$secs" env INVEST_DEFER_CLEANUP=1 \
        dsh --profile headless "$(cat "$agent_prompt")" >> "$LOG_FILE" 2>&1
}

# 从日志解析 CRON_DONE（正则来自 shared/contracts.py，与评级词汇表单一来源）
check_cron_done() {
    local re
    re=$(cd "$SKILL_DIR" && python3 -c 'from shared.contracts import CRON_DONE_RE; print(CRON_DONE_RE)')
    grep -E "$re" "$LOG_FILE" | tail -n 1 || true
}

# 更新 auto_state.json
update_auto_state() {
    local code="$1"
    local name="$2"
    local rating="$3"
    local score="$4"
    python3 - <<PYEOF
import json, datetime, os, sqlite3
state_path = os.environ.get('AUTO_STATE_FILE', 'data/auto_state.json')
state = json.load(open(state_path))
state['last_analyzed']['$code'] = '$TODAY_ISO'
# 重新计算 valid pool size（读 SQLite stocks 表，避免依赖遗留 JSON）
db = sqlite3.connect(os.environ.get('INVEST_DB_PATH', 'data/invest_skill.db'))
valid_n = db.execute("""
    SELECT COUNT(*) FROM stocks
    WHERE name IS NOT NULL AND name != ''
    AND ts_code NOT LIKE '688%'
    AND ts_code NOT LIKE '8%'
    AND name NOT LIKE '%ST%'
    AND ts_code NOT LIKE '%ST%'
""").fetchone()[0]
db.close()
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
    python3 "$SCRIPT_DIR/cleanup_intermediates.py" "$code" >> "$LOG_FILE" 2>&1
    rm -f "$RUNTIME_DIR/cron_agent_prompt_${TIMESTAMP}.txt"
    log "  [清理] 已清理 $code 的中间文件与运行日志"
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
# 自动生产运行不复用旧认知结果：先权威刷新行情与公告水位，再建立新 batch。
# 这以少量重复计算换取“最新披露完整性”可证明，避免断点跨越报告更新。
RESUME_READY=0
log "  自动运行强制新批次；旧断点仅保留作失败审计，不直接续跑"

if [[ $RESUME_READY -eq 0 ]]; then
    # ─── Step 1-2：权威刷新并生成同批次快照/prompt ─────────
    # prepare_prompts --force-sync 是唯一刷新入口；禁止外层重复 sync。
    log "[Step 2] 生成专家 prompt $CODE ..."
    if ! run_prepare_prompts "$CODE"; then
        log "✗ prompt 生成失败"
        source scripts/activity_log.sh && log_activity prompt "$CODE" "$NAME" failure "prepare_prompts失败"
        echo "CRON_FAIL $CODE prepare_prompts失败" | tee -a "$LOG_FILE"
        alert prompt "$CODE" "prepare_prompts失败"
        exit 1
    fi
    if ! verify_data_fresh "$CODE"; then
        log "✗ 数据不可用，本次分析失败"
        source scripts/activity_log.sh && log_activity prompt "$CODE" "$NAME" failure "数据不可用或陈旧"
        echo "CRON_FAIL $CODE 数据不可用或陈旧" | tee -a "$LOG_FILE"
        alert data "$CODE" "数据不可用或陈旧"
        exit 1
    fi
    if ! ls "$RUNTIME_DIR/invest_prompt_${CODE}_"*.txt &>/dev/null; then
        log "✗ prompt 文件缺失"
        exit 1
    fi
    log "  ✓ 数据快照与 prompt 已生成"
fi

# ─── Step 3-10：交给 agent ───────────────────────────────
log "[Step 3-10] 启动 host-native DSH headless 会话（native experts/challenges → 裁判长 → 定稿）..."

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
        REPORT_FILE="$REPORTS_DIR/${DONE_CODE}.md"
        if [[ "$DONE_CODE" == "$CODE" ]] && [[ -s "$REPORT_FILE" ]] \
            && python3 scripts/verify_report.py "$REPORT_FILE" --data "$RUNTIME_DIR/invest_data_${CODE}.json" --strict >> "$LOG_FILE" 2>&1 \
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
    alert expert "$CODE" "agent阶段失败或静默终止"
    [[ $RC -eq 0 ]] && exit 1
    exit "$RC"
fi

# ─── Step 8：更新状态与日志 ──────────────────────────────
log "[Step 8] 更新状态与活动日志 ..."
if ! update_auto_state "$CODE" "$NAME" "$RATING" "$SCORE"; then
    log "✗ auto_state 更新失败；保留中间文件供恢复"
    source scripts/activity_log.sh && log_activity report "$CODE" "$NAME" failure "auto_state更新失败"
    echo "CRON_FAIL $CODE auto_state更新失败" | tee -a "$LOG_FILE"
    alert state "$CODE" "auto_state更新失败"
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
