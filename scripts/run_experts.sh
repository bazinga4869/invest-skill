#!/usr/bin/env bash
# ============================================================
# run_experts.sh — 显式外部 CLI 兼容层（正常流程使用 native_agent_tasks.py）
#
# 用法：
#   bash scripts/run_experts.sh <ts_code> [--prepare] [--force-sync] [--retry] [--agent codex|claude]
#
#   --prepare     显式生成新 prompt 批次；默认复用调用方已准备的当前批次
#   --force-sync  与 --prepare 同用，强制刷新远端数据
#   --no-prepare  兼容旧调用方式，与默认行为相同
#   --retry       唯一一次定向修复：只修正校验未通过的专家
#
# 环境变量：
#   INVEST_HOST_AGENT        宿主 agent（codex / claude）；通常自动识别
#   INVEST_ALLOW_EXTERNAL_AGENT 用户明确要求外部 CLI 兼容模式时设为 1
#   INVEST_ALLOW_CROSS_AGENT    用户明确要求跨产品时设为 1（不推荐）
#   EXPERT_CLI                  显式后端覆盖；正常 host-native 流程不要设置
#   RUN_EXPERTS_CONCURRENCY  并发数，默认 7
#   EXPERT_TIMEOUT           单专家超时秒数，默认 1800
#   EXPERT_REPAIR_MAX_PASSES 重试事务内单专家最多修复轮数，默认 3，范围 1-5
#   INVEST_LOG_DIR           日志根目录，默认 <skill>/logs
#
# 退出码：0 = 7 位专家全部通过校验
#         1 = 存在失败或校验未通过的专家
#         2 = 用法/环境错误（codex CLI 缺失、prompt 缺失等）
#
# 设计：
#   - 每位专家启动一个同源 agent CLI 独立进程，通过 stdin 读 prompt 并落盘结果
#   - fresh 运行拒绝覆盖已有结果；新批次由 prepare_prompts.py 负责清理
#   - 初次执行不暗中重跑；--retry 事务只允许一次，事务内最多 3 轮“修复→单专家校验”
#   - 所有等待都收集逐专家退出码；任何失败都会反映到最终退出码（不静默）
# ============================================================

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
export INVEST_SKILL_ROOT="$SKILL_ROOT"
# prompts/results must share the caller's runtime root; explicit INVEST_RUNTIME_DIR still wins.
TMP_DIR="${INVEST_RUNTIME_DIR:-${INVEST_SKILL_HOME:-/tmp}}"
export INVEST_RUNTIME_DIR="$TMP_DIR"

# --- 参数解析 ---
TS_CODE=""
NO_PREPARE=1
RETRY=0
FORCE_SYNC=0
AGENT_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prepare)    NO_PREPARE=0; shift ;;
        --no-prepare) NO_PREPARE=1; shift ;;
        --retry)      RETRY=1; shift ;;
        --force-sync) FORCE_SYNC=1; shift ;;
        --agent)      [[ $# -ge 2 ]] || { echo "--agent 缺少参数" >&2; exit 2; }; AGENT_OVERRIDE="$2"; shift 2 ;;
        --agent=*)    AGENT_OVERRIDE="${1#*=}"; shift ;;
        -h|--help)    sed -n '2,17p' "$0"; exit 0 ;;
        -*)           echo "未知参数: $1" >&2; exit 2 ;;
        *)            TS_CODE="$1"; shift ;;
    esac
done
[[ -n "$TS_CODE" ]] || { echo "用法: $0 <ts_code> [--prepare] [--retry] [--agent codex|claude]" >&2; exit 2; }
if [[ "$FORCE_SYNC" -eq 1 && "$NO_PREPARE" -eq 1 ]]; then
    echo "ERROR: --force-sync 必须与 --prepare 同用" >&2
    exit 2
fi
if ! TS_CODE=$(cd "$SKILL_ROOT" && python3 -c \
    'import sys; from shared.contracts import normalize_ts_code; print(normalize_ts_code(sys.argv[1]))' \
    "$TS_CODE"); then
    echo "ERROR: 股票代码格式非法" >&2
    exit 2
fi

# 前置检查：默认跟随宿主；跨 agent 必须由用户显式许可。
source "$SCRIPT_DIR/agent_backend.sh"
select_agent_backend "$AGENT_OVERRIDE" || exit $?
EXPERT_CLI="$AGENT_BACKEND"
command -v "$EXPERT_CLI" &>/dev/null || { echo "ERROR: 需要 $EXPERT_CLI CLI 来执行专家分析（可通过 --agent 参数或 EXPERT_CLI 环境变量指定）" >&2; exit 2; }

# 专家列表：从 data/experts.json 读取（唯一数据源）
EXPERTS_JSON="$SKILL_ROOT/data/experts.json"
EXPERTS=()
while IFS= read -r entry; do
    EXPERTS+=("$entry")
done < <(python3 -c "
import json
data = json.load(open('$EXPERTS_JSON'))
for e in data['experts']:
    print(f\"{e['id']}:{e['file']}\")
")

CONCURRENCY="${RUN_EXPERTS_CONCURRENCY:-7}"
EXPERT_TIMEOUT="${EXPERT_TIMEOUT:-1800}"
REPAIR_MAX_PASSES="${EXPERT_REPAIR_MAX_PASSES:-3}"
if [[ ! "$REPAIR_MAX_PASSES" =~ ^[1-5]$ ]]; then
    echo "ERROR: EXPERT_REPAIR_MAX_PASSES 必须是 1-5 的整数" >&2
    exit 2
fi
# 运行时根：日志/结果写入调用方 INVEST_SKILL_HOME（与 cron_trigger/daily 一致）
RUNTIME_ROOT="${INVEST_SKILL_HOME:-$(cd "$SKILL_ROOT" && python3 -c 'from shared.project_config import runtime_root; print(runtime_root())')}"
export INVEST_SKILL_HOME="$RUNTIME_ROOT"
# 运行时根防护：禁止把运行时产物写回 skill 仓库（INVEST_ALLOW_SKILL_RUNTIME=1 显式逃逸）
if [[ "$RUNTIME_ROOT" == "$SKILL_ROOT" && "${INVEST_ALLOW_SKILL_RUNTIME:-0}" != "1" ]]; then
    echo "ERROR: 未设置 INVEST_SKILL_HOME，运行时产物将写回 skill 仓库（违反只读契约）。" >&2
    echo "       请 export INVEST_SKILL_HOME=<宿主运行时目录>（或 INVEST_ALLOW_SKILL_RUNTIME=1 显式允许）。" >&2
    exit 2
fi
export INVEST_SKILL_HOME="$RUNTIME_ROOT"
# Canonicalize the legacy transient variable too; never split prompts from results.
TMP_DIR="$RUNTIME_ROOT"
export INVEST_RUNTIME_DIR="$RUNTIME_ROOT"
LOG_DIR="${INVEST_LOG_DIR:-$RUNTIME_ROOT/logs}/experts"
mkdir -p "$LOG_DIR"

GUARD_CLAIMED=0
GUARD_TOKEN=""

release_guard() {
    if [[ "$GUARD_CLAIMED" -eq 1 ]]; then
        python3 "$SCRIPT_DIR/runtime_guard.py" release-run "$TS_CODE" shell \
            --token "$GUARD_TOKEN" >/dev/null 2>&1 || true
        GUARD_CLAIMED=0
    fi
}

on_signal() {
    echo "⚠ 收到中断信号，终止后台专家进程…" >&2
    local pids
    pids=$(jobs -pr)
    [[ -z "$pids" ]] || kill $pids 2>/dev/null || true
    release_guard
    exit 130
}

# 中断时终止后台专家进程，避免孤儿 agent 占用 API 配额。
trap on_signal INT TERM
trap release_guard EXIT

prompt_file() { echo "$TMP_DIR/invest_prompt_${TS_CODE}_$1.txt"; }
result_file() { echo "$TMP_DIR/invest_result_${TS_CODE}_$1.md"; }
expert_log()  { echo "$LOG_DIR/${TS_CODE}_$1.log"; }
staged_result_file() { echo "$TMP_DIR/.invest_result_${TS_CODE}_$1.${BASHPID}.next"; }

# --- 生成 prompt 文件 ---
generate_prompts() {
    echo "[1/3] 生成 7 位专家 prompt…"
    cd "$SKILL_ROOT"
    local -a sync_arg=()
    [[ "$FORCE_SYNC" -eq 1 ]] && sync_arg=(--force-sync)
    python3 scripts/prepare_prompts.py "$TS_CODE" "${sync_arg[@]}"
}

# --- 校验 prompt 齐全（--no-prepare/--retry 路径） ---
require_prompts() {
    local missing=0
    for entry in "${EXPERTS[@]}"; do
        local expert_id="${entry%%:*}"
        if [[ ! -s "$(prompt_file "$expert_id")" ]]; then
            echo "  ✗ prompt 缺失: $(prompt_file "$expert_id")" >&2
            missing=$((missing + 1))
        fi
    done
    if [[ $missing -gt 0 ]]; then
        echo "ERROR: $missing 份 prompt 缺失，先运行 python3 scripts/prepare_prompts.py $TS_CODE" >&2
        return 2
    fi
    if ! python3 "$SCRIPT_DIR/validate_prompt_bundle.py" "$TS_CODE"; then
        echo "ERROR: prompt bundle 批次/哈希预检失败；禁止启动专家。" >&2
        return 2
    fi
}

# --- 专家结果修复（带着校验失败清单让 agent 定向修复）---
fix_expert() {
    local expert_id="$1"
    local pf rf lf staged errors_file fix_prompt pass rc problems diagnostics
    pf="$(prompt_file "$expert_id")"
    rf="$(result_file "$expert_id")"
    lf="$(expert_log "$expert_id")"
    staged="$(staged_result_file "$expert_id")"
    errors_file="$TMP_DIR/invest_fix_errors_${TS_CODE}_${expert_id}.json"
    fix_prompt="$TMP_DIR/invest_fix_${TS_CODE}_${expert_id}.txt"

    for (( pass=1; pass<=REPAIR_MAX_PASSES; pass++ )); do
        if python3 "$SKILL_ROOT/scripts/collect_results.py" "$TS_CODE" \
            --expert "$expert_id" --check >/dev/null 2>&1; then
            echo "  [fix $pass/$REPAIR_MAX_PASSES] $expert_id — 已通过，无需继续" >> "$lf"
            rm -f "$staged" "$fix_prompt" "$errors_file"
            return 0
        fi

        # 每轮重新收集该专家的剩余问题，下一轮只处理尚未修好的契约项。
        python3 "$SKILL_ROOT/scripts/collect_results.py" "$TS_CODE" \
            --expert "$expert_id" --failing --json \
            > "$errors_file" 2>/dev/null || true
        problems=$(python3 - "$errors_file" "$expert_id" <<'PY' 2>/dev/null || true
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
expert = data.get(sys.argv[2], {})
print(chr(10).join(expert.get("problems", ["（校验错误详情不可得）"])))
PY
)
        [[ -n "$problems" ]] || problems="（校验错误详情不可得）"
        diagnostics=$(python3 - "$errors_file" "$expert_id" <<'PY' 2>/dev/null || true
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
diagnostics = data.get(sys.argv[2], {}).get("diagnostics", {})
print(json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True))
PY
)
        [[ -n "$diagnostics" ]] || diagnostics="{}"

        # 构造修复 prompt：原始任务 + 最新失败输出 + 本轮剩余问题。
        {
            echo "⬛⬛⬛ 有界修复事务 $pass/$REPAIR_MAX_PASSES — 逐项消除机器错误 ⬛⬛⬛"
            echo ''
            echo '最新结果因以下问题未通过单专家校验：'
            echo "$problems"
            echo ''
            echo '完整 diagnostics 对象（所有类别均完整、无截断；必须逐类别逐项处理，不得只修 problems 中的摘要示例）：'
            echo "$diagnostics"
            echo ''
            echo '必须输出一份完整替换文档，不得只解释错误。修复纪律：'
            echo '1. 校验绑定窗口严格是“当前数字末尾到下一个数字开始前”；每一次阿拉伯数字事实都必须在自己的窗口内紧邻真实 [source:]、可重算 [calc:]、[assumption:] 或 [method:]，前文标过不能覆盖后文。'
            echo '2. 只能使用原任务书 JSON 中真实存在的叶子路径；不得猜测层级。'
            echo '   diagnostics 中的 value_only_candidates 只是“数值相同”的检索线索，不是批准来源。必须逐一核对字段语义、报告期与单位；语义不匹配时删除该数字/表述或依据真实路径重算，禁止把候选路径直接套进 [source:] 或 [calc:]。'
            echo '3. [calc] 的公式必须只使用声明的 inputs，并可按 inputs 顺序直接复算；固定阈值或参数改用 [method:] / [assumption:]。'
            echo '   错误反例：21.93/14.98=1.46 [calc...]。末尾 [calc] 只能绑定 1.46，不能越过后续数字回绑 21.93 或 14.98。'
            echo '   合法写法 A：删除裸操作数，只保留“比率为 1.46 [calc: path.a / path.b; inputs: path.a, path.b]”。'
            echo '   合法写法 B：每个数字分别紧邻引用，如“21.93 [source: path.a] / 14.98 [source: path.b] = 1.46 [calc: path.a / path.b; inputs: path.a, path.b]”。'
            echo '4. 必检项证据必须使用任务书给出的候选真实路径；叙事表至少三行，逐字年报定位与 JSON 证据同时有效。'
            echo '5. 必须逐项处理上方 problems，以及完整 diagnostics 的全部类别和每个条目；修复后在思考中逐条复核，不要声称通过，只输出从 --- 开始的完整结果。'
            echo ''
            echo '══════ 最新待修结果 ══════'
            if [[ -s "$rf" ]]; then
                cat "$rf"
            else
                echo '（上一轮未生成结果，请按原始任务书完整生成。）'
            fi
            echo ''
            echo '══════ 原始任务书（路径与契约唯一依据） ══════'
            cat "$pf"
        } > "$fix_prompt"

        echo "  [fix $pass/$REPAIR_MAX_PASSES] $expert_id — 注入剩余错误定向修复…" >> "$lf"
        rm -f "$staged"
        rc=0
        if invoke_model_agent "$EXPERT_CLI" "$staged" "$lf" \
            "$EXPERT_TIMEOUT" "${EXPERT_MODEL:-}" < "$fix_prompt"; then
            rc=0
        else
            rc=$?
        fi
        if [[ "$rc" -eq 0 && -s "$staged" ]]; then
            mv -f "$staged" "$rf"
        elif [[ "$rc" -eq 0 ]]; then
            echo "  [fix $pass/$REPAIR_MAX_PASSES] 修复进程未生成结果" >> "$lf"
            rc=1
        else
            echo "  [fix $pass/$REPAIR_MAX_PASSES] agent exit=$rc" >> "$lf"
        fi
        rm -f "$staged" "$fix_prompt" "$errors_file"

        if [[ "$rc" -eq 0 ]] && python3 "$SKILL_ROOT/scripts/collect_results.py" \
            "$TS_CODE" --expert "$expert_id" --check >/dev/null 2>&1; then
            echo "  [fix $pass/$REPAIR_MAX_PASSES] $expert_id — 单专家门禁通过" >> "$lf"
            return 0
        fi
    done

    echo "  [fix] $expert_id — $REPAIR_MAX_PASSES 轮后仍未通过" >> "$lf"
    rm -f "$staged" "$fix_prompt" "$errors_file"
    return 1
}

# --- 执行单个专家（后台运行）---
run_expert() {
    local expert_id="$1"
    local pf rf lf staged
    pf="$(prompt_file "$expert_id")"
    rf="$(result_file "$expert_id")"
    lf="$(expert_log "$expert_id")"
    staged="$(staged_result_file "$expert_id")"

    echo "  ▶ [$expert_id] 开始…"

    if [[ ! -s "$pf" ]]; then
        echo "prompt 文件缺失: $pf" > "$lf"
        return 2
    fi

    # 每个进程先写唯一 staging 文件，完整退出后再原子替换正式结果。
    rm -f "$staged"
    local rc=0
    case "$EXPERT_CLI" in
        codex|claude)
            if {
                echo '⬛⬛⬛ 你是 invest-skill 分析管线的自动化专家代理 ⬛⬛⬛'
                echo ''
                echo '你只能读取下方任务书并输出最终文档，没有文件、命令或网络工具。请按以下两步执行：'
                echo ''
                echo '1. 在你的思考中完成完整分析（不要写草稿到其他文件）'
                echo '2. 输出到 stdout 前逐项自检：'
                echo '   (a) 第一行必须是 ---（不是则不输出）'
                echo '   (b) frontmatter 含 expert_id, score, verdict, data_date, batch_id'
                echo '   (c) 必检项表格每行 DONE/MISSING + 证据路径 + 结论'
                echo '   (d) 每个数字紧跟 [source:] 或 [calc:]'
                echo '   (e) 总字符数 >= 1200'
                echo '3. 自检通过后直接输出完整分析到 stdout'
                echo '   （严禁写文件后报告路径，严禁在 --- 前输出任何文字）'
                echo ''
                echo '══════ 任务书 ══════'
                cat "$pf"
            } | invoke_model_agent "$EXPERT_CLI" "$staged" "$lf" \
                "$EXPERT_TIMEOUT" "${EXPERT_MODEL:-}"; then
                rc=0
            else
                rc=$?
            fi
            ;;
        *)
            echo "不支持的 EXPERT_CLI: $EXPERT_CLI（支持 codex / claude）" > "$lf"
            return 2
            ;;
    esac
    if [[ "$rc" -eq 0 && -s "$staged" ]]; then
        mv -f "$staged" "$rf"
    elif [[ "$rc" -eq 0 ]]; then
        echo "agent 未生成结果" >> "$lf"
        rc=1
    fi
    rm -f "$staged"
    return "$rc"
}

# --- 并行执行（批量并发控制 + 逐专家退出码收集） ---
declare -A RC_OF=()

wait_batch() {
    local -n _pids="$1"
    local -n _map="$2"
    local pid expert_id
    for pid in "${_pids[@]}"; do
        expert_id="${_map[$pid]}"
        if wait "$pid"; then
            RC_OF["$expert_id"]=0
            echo "  ✓ [$expert_id] 完成（$(wc -c < "$(result_file "$expert_id")" 2>/dev/null || echo 0) bytes）"
        else
            RC_OF["$expert_id"]=$?
            if [[ "${RC_OF[$expert_id]}" == "124" ]]; then
                echo "  ✗ [$expert_id] 超时（${EXPERT_TIMEOUT}s）"
            else
                echo "  ✗ [$expert_id] 失败（exit=${RC_OF[$expert_id]}，日志：$(expert_log "$expert_id")）"
            fi
        fi
    done
}

run_batch() {
    local -a pids=()
    local -A pid2expert=()
    local count=0
    local expert_id pid

    for expert_id in "$@"; do
        run_expert "$expert_id" &
        pid=$!
        pids+=("$pid")
        pid2expert["$pid"]="$expert_id"
        count=$((count + 1))
        if (( count % CONCURRENCY == 0 )); then
            wait_batch pids pid2expert
            pids=()
        fi
    done

    if (( ${#pids[@]} > 0 )); then
        wait_batch pids pid2expert
    fi
}

# --- 校验结果 ---
check_results() {
    cd "$SKILL_ROOT"
    python3 scripts/collect_results.py "$TS_CODE" --check
}

run_fix_batch() {
    local -a pids=()
    local count=0 expert_id pid
    for expert_id in "$@"; do
        fix_expert "$expert_id" &
        pid=$!
        pids+=("$pid")
        count=$((count + 1))
        if (( count % CONCURRENCY == 0 )); then
            for pid in "${pids[@]}"; do wait "$pid" || true; done
            pids=()
        fi
    done
    for pid in "${pids[@]}"; do wait "$pid" || true; done
}

# --- 主流程 ---
main() {
    # --retry 隐含 --no-prepare：结果必须与现有 prompt 同批次（data_date 一致性校验依赖这一点）
    if [[ $RETRY -eq 1 ]]; then
        NO_PREPARE=1
    fi

    echo "══════════════════════════════════════════"
    echo "  invest-skill 专家团独立分析"
    echo "  标的：$TS_CODE | 宿主：$AGENT_HOST | 后端：$EXPERT_CLI ($AGENT_BACKEND_SOURCE)"
    echo "  并发：$CONCURRENCY | 单专家超时：${EXPERT_TIMEOUT}s"
    echo "══════════════════════════════════════════"

    if [[ $NO_PREPARE -eq 0 ]]; then
        generate_prompts
    else
        require_prompts || exit 2
    fi
    validate_agent_backend "$EXPERT_CLI" "${EXPERT_MODEL:-}" || exit $?

    local guard_json
    if ! guard_json=$(python3 "$SCRIPT_DIR/runtime_guard.py" claim-run "$TS_CODE" shell); then
        echo "ERROR: 无法取得专家运行互斥；请先查询当前写入阶段并等待其结束。" >&2
        exit 2
    fi
    GUARD_TOKEN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$guard_json")
    GUARD_CLAIMED=1
    record_agent_execution "$SCRIPT_DIR" "$TS_CODE" experts "$EXPERT_CLI" \
        "$AGENT_HOST" "$CONCURRENCY" "$EXPERT_TIMEOUT" "$REPAIR_MAX_PASSES" >/dev/null

    local -a targets=()
    if [[ $RETRY -eq 1 ]]; then
        local failing
        local failing_rc=0
        failing=$(python3 "$SCRIPT_DIR/collect_results.py" "$TS_CODE" --failing) || failing_rc=$?
        if [[ "$failing_rc" -ne 0 && "$failing_rc" -ne 1 ]]; then
            echo "ERROR: 无法读取失败专家列表（exit=$failing_rc），拒绝把校验故障当作全部通过。" >&2
            exit 2
        fi
        if [[ -z "$failing" ]]; then
            echo "✓ 全部专家结果已通过校验，无需重试"
            exit 0
        fi
        mapfile -t targets <<< "$failing"
        if ! python3 "$SCRIPT_DIR/runtime_guard.py" begin-retry "$TS_CODE" experts >/dev/null; then
            echo "ERROR: 本批专家重试额度已用完；请重建新批次，不得继续重跑。" >&2
            exit 2
        fi
        echo "[2/3] 唯一一次定向修复事务（每位最多 ${REPAIR_MAX_PASSES} 轮），共 ${#targets[@]} 位专家：${targets[*]}"
    else
        # prepare_prompts 负责清理旧批次；此处拒绝覆盖，防止任何并发写入阶段污染结果。
        local entry expert_id
        local -a existing=()
        for entry in "${EXPERTS[@]}"; do
            expert_id="${entry%%:*}"
            [[ ! -e "$(result_file "$expert_id")" ]] || existing+=("$expert_id")
            targets+=("$expert_id")
        done
        if (( ${#existing[@]} > 0 )); then
            echo "ERROR: 已存在专家结果 (${existing[*]})，拒绝 fresh 覆盖。" >&2
            echo "请使用 --retry 修复失败项，或重新运行 prepare_prompts.py 建立新批次。" >&2
            exit 2
        fi
        echo "[2/3] 并行执行 ${#targets[@]} 位专家…"
    fi

    if [[ $RETRY -eq 1 ]]; then
        run_fix_batch "${targets[@]}"
    else
        run_batch "${targets[@]}"
    fi

    echo "[3/3] 校验结果…"
    if check_results; then
        echo ""
        echo "✓ 全部完成。下一步："
        echo "  bash scripts/run_challenges.sh $TS_CODE"
        exit 0
    fi

    echo ""
    local failure_evidence=""
    if failure_evidence=$(python3 "$SCRIPT_DIR/preserve_failure_evidence.py" \
        "$TS_CODE" experts); then
        echo "失败证据已保留：$failure_evidence"
    else
        echo "⚠ 无法写入失败证据快照；现有 prompt/result/log 仍保留。" >&2
    fi
    if [[ $RETRY -eq 0 ]]; then
        echo "✗ 存在未通过校验的专家。只允许一次定向修复："
        echo "  bash scripts/run_experts.sh $TS_CODE --no-prepare --retry"
        echo "若不准备重试，请执行 python3 scripts/cleanup_intermediates.py $TS_CODE。"
    else
        echo "✗ 唯一一次定向修复仍未通过，本批次终止；禁止发布或继续重跑。"
        echo "  已默认保留 prompt、result、日志、重试标记和完整 diagnostics。"
        echo "  复盘或确认终止后显式清理：python3 scripts/cleanup_intermediates.py $TS_CODE"
    fi
    exit 1
}

main
