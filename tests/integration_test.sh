#!/usr/bin/env bash
# integration_test.sh — invest-skill 端到端集成测试
#
# 覆盖：data_tools 全子命令 → prepare_prompts → run_experts(stub 后端)
#       → collect_results → assemble_report → daily_analysis/cron(stub)
#
# stub agent 替代真实 codex/claude CLI，不消耗 API 配额。
# 用法：bash tests/integration_test.sh [ts_code]   （默认 600938.SH）

set -uo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SKILL_ROOT"

# 默认回归必须遵守生产 host-native 边界，不启动任何模型 CLI。旧的外部
# CLI stub 全管线仅在显式兼容测试时运行。
if [[ "${INVEST_RUN_LEGACY_EXTERNAL_INTEGRATION:-0}" != "1" ]]; then
    echo "[host-native integration] provider/model inheritance, staging, commit, retry reservation"
    INVEST_ALLOW_SKILL_RUNTIME=1 python3 -m unittest \
        tests.test_native_agent_tasks tests.test_runtime_contracts -q
    exit $?
fi

# 默认标的需满足本地 DB 有财务/行情数据；report-wiki 在测试模式使用严格
# fixture，不访问真实网络、Sage 或年报缓存。
RAW_CODE="${1:-603605.SH}"
if ! CODE=$(python3 -c \
    'import sys; from shared.contracts import normalize_ts_code; print(normalize_ts_code(sys.argv[1]))' \
    "$RAW_CODE"); then
    echo "ERROR: 股票代码格式非法: $RAW_CODE" >&2
    exit 2
fi

SOURCE_DB="${INVEST_TEST_SOURCE_DB:-$SKILL_ROOT/data/invest_skill.db}"
[[ -s "$SOURCE_DB" ]] || { echo "ERROR: 集成测试数据库不存在: $SOURCE_DB" >&2; exit 2; }
RUN_DIR="$(mktemp -d /tmp/invest_integration.XXXXXX)"
STUB_DIR="$RUN_DIR/stubs"
TEST_LOG_DIR="$RUN_DIR/logs"
TEST_REPORTS_DIR="$RUN_DIR/reports"
TEST_DB="$RUN_DIR/invest_skill.db"
mkdir -p "$STUB_DIR" "$TEST_LOG_DIR" "$TEST_REPORTS_DIR"
# The legacy shell path is tested only with an explicit stub opt-in.  Runtime
# artifacts stay in /tmp because this fixture predates host-native task plans.
export INVEST_SKILL_HOME=/tmp
export INVEST_RUNTIME_DIR=/tmp
export INVEST_ALLOW_EXTERNAL_AGENT=1
export INVEST_AGENT_BACKEND=codex
REPO_DRAFT="$SKILL_ROOT/reports/invest_tool/${CODE}.draft.md"
PASS=0
FAIL=0

ok()   { PASS=$((PASS+1)); echo "  ✓ $*"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $*"; }
check(){ if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi }

draft_state() {
    if [[ -f "$REPO_DRAFT" ]]; then
        sha256sum "$REPO_DRAFT"
    elif [[ -e "$REPO_DRAFT" ]]; then
        printf 'non-regular\n'
    else
        printf 'missing\n'
    fi
}

REPO_DRAFT_STATE_BEFORE="$(draft_state)"
SOURCE_DB_STATE_BEFORE="$(sha256sum "$SOURCE_DB")"

collect_runtime_artifacts() {
    shopt -s nullglob
    RUNTIME_ARTIFACTS=(
        "/tmp/invest_data_${CODE}.json"
        "/tmp/invest_annual_${CODE}.txt"
        "/tmp/invest_report_bundle_${CODE}.json"
        "/tmp/invest_annual_toc_${CODE}.txt"
        "/tmp/invest_results_${CODE}.json"
        "/tmp/invest_level3_${CODE}.json"
        "/tmp/invest_cross_blind_${CODE}.md"
        "/tmp/invest_expert_run_${CODE}.json"
        /tmp/invest_prompt_"${CODE}"_*.txt
        /tmp/invest_result_"${CODE}"_*.md*
        /tmp/invest_draft_"${CODE}"_*.md
        /tmp/invest_fix_"${CODE}"_*.txt
        /tmp/invest_fix_errors_"${CODE}"*.json
        /tmp/invest_retry_"${CODE}"_*.json
        /tmp/.invest_*"${CODE}"*.next
        /tmp/invest_challenge_prompt_"${CODE}"_*.txt
        /tmp/invest_challenge_result_"${CODE}"_*.md
        /tmp/invest_cross_prompt_"${CODE}"_*.txt
        /tmp/invest_cross_result_"${CODE}"_*.md
    )
    shopt -u nullglob
}

cleanup_runtime_artifacts() {
    python3 scripts/cleanup_intermediates.py "$CODE" --keep-logs --keep-draft >/dev/null 2>&1 || true
}

has_runtime_artifacts() {
    local path
    collect_runtime_artifacts
    for path in "${RUNTIME_ARTIFACTS[@]}"; do
        [[ -e "$path" ]] && return 0
    done
    return 1
}

cleanup() {
    cleanup_runtime_artifacts
    rm -rf -- "$RUN_DIR"
}
trap cleanup EXIT

# 集成测试可触发 schema 迁移/年报缓存写入；只允许写临时数据库副本。
if ! cp --reflink=auto -- "$SOURCE_DB" "$TEST_DB"; then
    echo "ERROR: 无法创建集成测试数据库副本" >&2
    exit 2
fi
export INVEST_DB_PATH="$TEST_DB"
# 把分析日钉到本地行情快照，且只在显式测试模式下跳过联网同步。
LATEST_TRADE=$(python3 - "$TEST_DB" "$CODE" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as conn:
    print(conn.execute(
        "SELECT MAX(trade_date) FROM daily_basic WHERE ts_code=?", (sys.argv[2],)
    ).fetchone()[0] or "")
PY
)
[[ "$LATEST_TRADE" =~ ^[0-9]{8}$ ]] || {
    echo "ERROR: 测试数据库缺少 $CODE 行情日期" >&2
    exit 2
}
export INVEST_TEST_MODE=1
export INVEST_SKIP_SYNC=1
export INVEST_ANALYSIS_DATE="${LATEST_TRADE:0:4}-${LATEST_TRADE:4:2}-${LATEST_TRADE:6:2}"
REPORT_WIKI_FIXTURE="$RUN_DIR/report-wiki-bundle.json"
python3 - "$CODE" "$LATEST_TRADE" "$REPORT_WIKI_FIXTURE" <<'PYEOF'
import hashlib, json, sys
from datetime import datetime
from pathlib import Path

from shared.report_wiki import BUNDLE_SCHEMA_VERSION, bundle_hash, expected_fiscal_years

code, as_of_text, destination = sys.argv[1:]
as_of = datetime.strptime(as_of_text, "%Y%m%d")
reports = []
section_specs = [
    ("管理层讨论与分析", "公司持续推进主营业务发展并审慎评估行业变化，经营数据均以正式披露为准。"),
    ("经营情况讨论与分析", "公司围绕产品结构、客户需求与运营效率开展经营，未将目标性表述视为已实现结果。"),
    ("公司未来发展的展望", "公司未来计划受到市场需求、竞争格局与执行能力影响，相关展望不构成业绩承诺。"),
    ("可能面对的风险", "公司识别宏观波动、行业竞争、原材料价格与内部控制等风险，并持续完善应对措施。"),
    ("公司治理", "公司治理事项按照正式公告披露，相关制度、人员与内部控制信息均需逐项核对。"),
    ("重要事项", "公司重要事项包括关联交易与资金占用核查，测试文本不替代正式事实判断。"),
    ("股份变动及股东情况", "公司股份与股东情况以本年度正式披露为准，任何变化均保留原始页码定位。"),
    ("核心竞争力分析", "公司竞争力叙述属于管理层陈述，必须结合结构化数据进行反叙事验证。"),
]
for year in expected_fiscal_years(as_of, 5):
    sections = []
    for page, (name, sentence) in enumerate(section_specs, start=10):
        text = "\n".join(
            f"{sentence}年度{year}核对序号{i}。" for i in range(100)
        )
        sections.append({
            "name": name,
            "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "page_start": page,
            "page_end": page + 1,
        })
    source = f"fixture-{code}-{year}".encode()
    reports.append({
        "fiscal_year": year,
        "report_type": "annual",
        "announcement_date": f"{int(year) + 1}0430",
        "title": f"{year}年年度报告",
        "source_url": f"https://example.invalid/{code}/{year}.pdf",
        "source_path": f"raw/annual/{year}/report.pdf",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "source_bytes": 20_000,
        "page_count": 100,
        "provenance_level": "page-exact",
        "sage_source_status": "compiled",
        "sections": sections,
    })
bundle = {
    "schema_version": BUNDLE_SCHEMA_VERSION,
    "status": "PASS",
    "ts_code": code,
    "as_of": as_of_text,
    "requested_years": expected_fiscal_years(as_of, 5),
    "report_types": ["annual"],
    "corpus_hash": hashlib.sha256(json.dumps(reports, sort_keys=True).encode()).hexdigest(),
    "sage": {
        "workspace": f"companies/{code}/sage",
        "engine_version": "fixture",
        "status": "compiled",
        "coverage_status": "PASS",
        "provenance_status": "PASS",
    },
    "reports": reports,
    "missing": [],
    "warnings": [],
}
bundle["bundle_hash"] = bundle_hash(bundle)
Path(destination).write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
PYEOF
export INVEST_REPORT_WIKI_FIXTURE="$REPORT_WIKI_FIXTURE"

# 不允许上次运行的中间文件影响本次集成结果。
cleanup_runtime_artifacts

# ── stub agent：codex 走 `codex exec -o <rf> -`（CLI 写结果文件）────────────
# 从 -o 路径提取 expert_id，从 /tmp/invest_data_<code>.json 提取 trade_date，
# 生成 collect_results 可校验通过的 frontmatter 结果。
cat > "$STUB_DIR/codex" <<'EOF'
#!/bin/bash
# stub codex：支持 `codex exec -o <rf> -`，prompt 从 stdin 读
if [[ " $* " == *" exec "* && " $* " == *" --help "* ]]; then
    printf '%s\n' '--strict-config --sandbox --ephemeral --ignore-rules'
    exit 0
fi
if [[ " $* " == *" --output-schema /dev/null "* ]]; then
    echo 'Output schema file /dev/null is not valid JSON: EOF while parsing a value at line 1 column 0' >&2
    exit 1
fi
out=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        *)  shift ;;
    esac
done
prompt="$(cat)"
[[ -n "$out" ]] || { echo "stub: 缺少 -o" >&2; exit 1; }
python3 "${INVEST_SKILL_ROOT:-$(pwd)}/tests/stub_agent.py" "$out" <<<"$prompt"
exit $?
base="$(basename "$out")"                       # invest_result_<code>_<expert>.md
code="$(echo "$base" | sed -E 's/^invest_result_([^.]+\.[A-Z]+)_.*/\1/')"
expert="$(echo "$base" | sed -E 's/^invest_result_[^.]+\.[A-Z]+_(.*)\.md$/\1/')"
IFS=$'\t' read -r trade_date analysis_date batch_id < <(python3 -c "import json;d=json.load(open('/tmp/invest_data_${code}.json'));print(d['market']['trade_date'],d['meta']['analysis_date'],d['meta']['batch_id'],sep='\t')" 2>/dev/null)
IFS=$'\t' read -r close total_mv cash < <(python3 -c "import json;d=json.load(open('/tmp/invest_data_${code}.json'));print(d['market']['close'],d['market']['total_mv_yi'],d['balance']['cash_yi'],sep='\t')")
# 失败注入：prompt 含 STUB_FAIL_THIS_EXPERT 时本次不写结果并退出 1
if [[ "$STUB_FAIL_EXPERT" == "$expert" ]]; then
    echo "stub: 注入失败 ($expert)" >&2
    exit 1
fi
cat > "$out" <<RESULT
---
expert_id: "$expert"
ts_code: "$code"
score: 80
verdict: PASS
conclusion_direction: NEUTRAL
veto_triggers: []
data_date: "$trade_date"
analysis_date: "$analysis_date"
batch_id: "$batch_id"
---
# 集成测试专家评估 — $expert

## 总体判断

本报告由集成测试管线自动生成，基于 data_tools.py 提供的原始财务数据完成量化分析。
该标的在本次评估所涉指标上表现正常，未触发任何否决条件。以下分析覆盖核心定量指标
与年报文本的交叉验证，为裁判长综合裁决提供本域视角的参考依据。

## 详细分析

### 定量指标

| 指标 | 数值 | 判定 |
|------|------|------|
| 股价 | ${close} [source: market.close] | 已核对 |
| 总市值 | ${total_mv}亿 [source: market.total_mv_yi] | 已核对 |
| 现金 | ${cash}亿 [source: balance.cash_yi] | 已核对 |

所有数据均来自 /tmp/invest_data_$code.json。关键计算过程如下：

- ROE = 归母净利润 / 归母权益 = 已验证（与 fina_indicators 表交叉一致）
- 毛利率 = (营收 - 营业成本) / 营收 = 已验证
- 经营现金流 / 净利润已按同批次字段核对（Q1 季节效应已单独说明）

### 定性评估

基于年报文本（管理层讨论与分析、经营情况讨论与分析章节）的交叉验证：

1. **管理层战略叙述**：年报中管理层对行业趋势的判断与财务数据一致，收入增长驱动因素
   可被量化为具体产品线或区域的贡献度变化。

2. **反叙事检查**：逐一对比了管理层在最近 3 年年报中的关键承诺与实际财务表现，
   未发现承诺未兑现或战略方向反复变更的信号。管理层对业绩变动的归因（如成本控制、
   渠道优化等）与费用率变化方向一致。

3. **风险披露充分性**：年报"可能面对的风险"章节覆盖了行业竞争、原材料波动、
   政策变化等主要风险类别，且每类风险均有对应的应对措施说明。

## 关键风险与不确定性

- 行业竞争格局变化可能影响未来盈利能力，需持续跟踪市占率变化
- 宏观经济波动对终端消费需求存在潜在压制效应
- 原材料价格波动对毛利率的传导可能存在若干季度的滞后效应

## 叙事–数据交叉验证

| # | 管理层论述 | 对应财务数据字段 | 验证结果 | 证据 |
|---|-----------|------------------|----------|------|
| 1 | 经营稳定 | market.close | ✅ | ${close} [source: market.close] |
| 2 | 规模稳定 | market.total_mv_yi | ✅ | ${total_mv}亿 [source: market.total_mv_yi] |
| 3 | 现金充裕 | balance.cash_yi | ✅ | ${cash}亿 [source: balance.cash_yi] |

## 必检项执行记录

| 必检项 | 状态 | 证据/来源路径 | 结论 |
|--------|------|---------------|------|
$(python3 - "$expert" <<'PY'
import json, sys
for item in json.load(open('data/expert_checklist.json'))[sys.argv[1]]['items']:
    print(f"| {item} | DONE | `market.close` | 已执行并记录结论 |")
PY
)

## 数据使用说明

- 数据来源：Tushare Pro（data_tools.py all 输出），包含行情、利润表、资产负债表、
  现金流量表、财务指标、行业对比、审计意见、业绩预告等全部字段
- 年报文本来源：本批次 report-wiki 证据包，覆盖最近 5 年年度报告关键章节
- 缺失数据：审计意见数据未获取（fina_audit 表无记录），已在分析中标注不确定性
- 行业对比基准：申万行业分类，样本量见 industry_stats 字段

## 知识检索日志

| # | 页面路径 | 发现方式 | 使用深度 |
|---|----------|----------|----------|
| 1 | 04_stock-analysis-expert/index.md | 注入快照 | 全文精读 |
| 2 | experts/$expert.md | 注入快照 | 全文精读 |
| 3 | adjudicator/裁判长-多框架裁判规则.md | 索引 | 关键段落 |
RESULT
EOF

# stub claude：`claude --bare -p ...` 结果写 stdout
cat > "$STUB_DIR/claude" <<'EOF'
#!/bin/bash
prompt="$(cat)"
echo "stub-claude 不支持结果落盘测试，请用 codex stub" >&2
exit 1
EOF
chmod +x "$STUB_DIR/codex" "$STUB_DIR/claude"

echo "════════════════════════════════════════════════"
echo " invest-skill 集成测试 — $CODE"
echo "════════════════════════════════════════════════"

# ══ T1: data_tools 全子命令 ════════════════════════════════════
echo
echo "[T1] data_tools 子命令（真实本地 DB 副本）"
for cmd in stock-info market annual quarterly balance indicators industry forecast; do
    out=$(python3 shared/data_tools.py "$cmd" "$CODE" 2>/dev/null)
    if echo "$out" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
        ok "$cmd 输出合法 JSON"
    else
        bad "$cmd 输出非法: $(echo "$out" | head -1)"
    fi
done

# T1 回归断言：本次评审修复的两个 P1/P3
python3 - "$CODE" <<'PYEOF'
import json, subprocess, sys
code = sys.argv[1]

def run(cmd):
    out = subprocess.run(["python3", "shared/data_tools.py", cmd, code],
                         capture_output=True, text=True)
    return json.loads(out.stdout)

b = run("balance")
assert "balance_history" in b, "balance 缺少 balance_history"
hist = b["balance_history"]
# 回归：history DESC，history[0] 最新；顶层字段 == history[0]
assert hist[0]["year"] >= hist[-1]["year"], f"balance_history 排序错误: {hist[0]['year']} vs {hist[-1]['year']}"
assert b["total_assets_yi"] == hist[0]["total_assets_yi"], "顶层字段与 history[0] 不一致"
print(f"  ✓ balance 排序/顶层断言通过（最新 {hist[0]['year']}，最旧 {hist[-1]['year']}）")

a = run("all").get("audit", {})
if a.get("has_audit"):
    fees = a["latest"]["audit_fees_yi"]
    # 回归：audit_fees 单位为元→亿，A股审计费不可能 >100 亿
    assert fees is None or fees < 100, f"audit_fees_yi={fees} 疑似单位错误"
    print(f"  ✓ audit_fees_yi 单位断言通过（{fees} 亿）")
else:
    print("  - audit 无数据，跳过单位断言")
PYEOF
[[ $? -eq 0 ]] && PASS=$((PASS+2)) || { FAIL=$((FAIL+2)); echo "  ✗ 回归断言失败"; }

# ══ T2: prepare_prompts ════════════════════════════════════════
echo
echo "[T2] prepare_prompts 生成专家 prompt"
DATA_READY=$(python3 shared/data_tools.py all "$CODE" 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('data_quality',{}).get('status') != 'FAIL')" 2>/dev/null || echo False)
if [[ "$DATA_READY" != "True" ]]; then
    bad "确定性快照未通过 data_quality；T2-T5 不能跳过"
else
PREPARE_LOG="$RUN_DIR/prepare.log"
if python3 scripts/prepare_prompts.py "$CODE" >"$PREPARE_LOG" 2>&1; then
    ok "prepare_prompts exit 0"
else
    bad "prepare_prompts 失败: $(tail -n 2 "$PREPARE_LOG" | tr '\n' ' ')"
fi
n=$(ls /tmp/invest_prompt_${CODE}_*.txt 2>/dev/null | wc -l)
[[ $n -eq 7 ]] && ok "7 份 prompt 文件（实际 $n）" || bad "prompt 文件数 $n ≠ 7"
[[ -s /tmp/invest_data_${CODE}.json ]] && ok "invest_data JSON 存在" || bad "invest_data JSON 缺失"
[[ -s /tmp/invest_annual_${CODE}.txt ]] && ok "年报文本存在" || bad "年报文本缺失"
[[ -s /tmp/invest_report_bundle_${CODE}.json ]] \
    && ok "report-wiki 证据包存在" || bad "report-wiki 证据包缺失"
python3 -c "
import json
d = json.load(open('/tmp/invest_data_${CODE}.json'))
assert 'audit' in d, 'all 输出缺 audit 键'
assert d['market']['trade_date'], '缺 trade_date'
" 2>/dev/null && ok "data JSON 含 audit/trade_date" || bad "data JSON 结构不完整"
if rg -q '机器契约可用定位' /tmp/invest_prompt_${CODE}_financial-auditor.txt \
   && rg -q '精确证据卡片（优先从这里复制路径）' /tmp/invest_prompt_${CODE}_financial-auditor.txt \
   && rg -q 'wiki/concepts/' /tmp/invest_prompt_${CODE}_financial-auditor.txt \
   && rg -q '首列必须严格使用 ASCII 数字' /tmp/invest_prompt_${CODE}_financial-auditor.txt; then
    ok "prompt 注入精确 wiki/年报定位与机器格式契约"
else
    bad "prompt 缺少精确定位或机器格式契约"
fi
max_prompt_bytes=$(wc -c /tmp/invest_prompt_${CODE}_*.txt \
    | awk '$2 != "total" {if ($1 > max) max=$1} END {print max+0}')
[[ "$max_prompt_bytes" -le 180000 ]] \
    && ok "单专家 prompt 体积门禁（最大 ${max_prompt_bytes} bytes）" \
    || bad "单专家 prompt 超过 180000 bytes（最大 ${max_prompt_bytes}）"

# ══ T3: run_experts（stub 后端）全管线 ═════════════════════════
echo
echo "[T3] run_experts.sh（stub codex，7 专家全成功）"
rm -f /tmp/invest_result_${CODE}_*.md
# 任一外部所有者 claim 后，shell 路径必须硬拒绝，防止双写。
python3 scripts/runtime_guard.py claim-run "$CODE" challenges >/dev/null
if PATH="$STUB_DIR:/usr/bin:/bin:/usr/local/bin" \
   INVEST_LOG_DIR="$TEST_LOG_DIR" \
   bash scripts/run_experts.sh "$CODE" --no-prepare >/dev/null 2>&1; then
    bad "其他写入阶段已占用时 run_experts 不应启动"
else
    ok "阶段间双写互斥生效"
fi
python3 scripts/runtime_guard.py release-run "$CODE" challenges >/dev/null
if PATH="$STUB_DIR:/usr/bin:/bin:/usr/local/bin" \
   INVEST_LOG_DIR="$TEST_LOG_DIR" \
   RUN_EXPERTS_CONCURRENCY=3 EXPERT_TIMEOUT=60 \
   bash scripts/run_experts.sh "$CODE" --no-prepare >/dev/null 2>&1; then
    ok "run_experts exit 0"
else
    bad "run_experts 非 0"
fi
n=$(ls /tmp/invest_result_${CODE}_*.md 2>/dev/null | wc -l)
[[ $n -eq 7 ]] && ok "7 份结果文件（实际 $n）" || bad "结果文件数 $n ≠ 7"

# ══ T4: collect_results 校验语义 ═══════════════════════════════
echo
echo "[T4] collect_results 校验"
python3 scripts/collect_results.py "$CODE" --check >/dev/null 2>&1 \
    && ok "--check 全通过 exit 0" || bad "--check 应通过却失败"
python3 scripts/collect_results.py "$CODE" --json >/dev/null 2>&1 \
    && [[ -s /tmp/invest_results_${CODE}.json ]] \
    && ok "--json 汇总文件生成" || bad "--json 未生成汇总"

# T4b: 删除一份结果 → check 应失败、--failing 应指出该专家
victim="moat-analyst"
mv /tmp/invest_result_${CODE}_${victim}.md /tmp/invest_result_${CODE}_${victim}.md.bak
python3 scripts/collect_results.py "$CODE" --check >/dev/null 2>&1 \
    && bad "缺一份结果时 --check 应失败" || ok "缺结果时 --check exit 1"
failing=$(python3 scripts/collect_results.py "$CODE" --failing 2>/dev/null)
[[ "$failing" == "$victim" ]] && ok "--failing 正确指出 $victim" || bad "--failing 输出异常: $failing"
failing_json=$(python3 scripts/collect_results.py "$CODE" --failing --json 2>/dev/null || true)
if printf '%s' "$failing_json" \
   | python3 -c "import json,sys; d=json.load(sys.stdin); assert '结果文件缺失' in d['$victim']['problems']"; then
    ok "--failing --json 提供逐专家错误详情"
else
    bad "--failing --json 未提供可解析错误详情"
fi

# T4c: 恢复有效结果并注入 12 个未溯源数字。第 12 项不会出现在 problems
# 的 8 项摘要里，stub 必须从 structured diagnostics 区块读到它；首轮
# 再产出另一组 12 项，第二轮还必须看到刷新后的末项且不含旧末项。
cp /tmp/invest_result_${CODE}_${victim}.md.bak /tmp/invest_result_${CODE}_${victim}.md
{
    printf '\n## 有界修复诊断回归数据\n\n'
    for value in $(seq 987601 987612); do
        printf '待修经营指标 %s亿\n' "$value"
    done
} >> /tmp/invest_result_${CODE}_${victim}.md

# --retry 幂等重试只补跑失败专家。
# 回归用户现场：调用方误先 claim-retry 只形成预留，脚本的
# begin-retry 仍可消费它并启动首次实际修复。
python3 scripts/runtime_guard.py claim-retry "$CODE" experts >/dev/null
if PATH="$STUB_DIR:/usr/bin:/bin:/usr/local/bin" \
   INVEST_LOG_DIR="$TEST_LOG_DIR" \
   STUB_INVALID_FIX_PASSES=1 STUB_STATE_DIR="$RUN_DIR" \
   STUB_FIX_INITIAL_SENTINEL="987612亿" \
   STUB_FIX_REFRESH_SENTINEL="987712亿" \
   RUN_EXPERTS_CONCURRENCY=3 EXPERT_TIMEOUT=60 \
   bash -c 'cd "$1" && bash "$2/scripts/run_experts.sh" "$3" --no-prepare --retry' \
       _ "$RUN_DIR" "$SKILL_ROOT" "$CODE" >/dev/null 2>&1; then
    ok "预 claim 后 --retry 正常启动并 exit 0"
else
    bad "--retry 后仍失败"
fi
[[ -s /tmp/invest_result_${CODE}_${victim}.md ]] && ok "--retry 补齐 $victim" || bad "--retry 未补齐"
[[ "$(cat "$RUN_DIR/fix_pass_${CODE}_${victim}.txt" 2>/dev/null)" == "2" ]] \
    && ok "首轮修复失败后经单专家校验进入第二轮" \
    || bad "有界修复未按预期执行两轮"
if [[ "$(cat "$RUN_DIR/fix_diagnostics_pass_1_${CODE}_${victim}.ok" 2>/dev/null)" == "987612亿" \
      && "$(cat "$RUN_DIR/fix_diagnostics_pass_2_${CODE}_${victim}.ok" 2>/dev/null)" == "987712亿" ]]; then
    ok "有界修复逐轮注入完整且刷新的 structured diagnostics"
else
    bad "有界修复 prompt 未携带摘要外末项或未逐轮刷新"
fi
python3 scripts/collect_results.py "$CODE" --expert "$victim" --check >/dev/null 2>&1 \
    && ok "--expert 单专家门禁通过" || bad "--expert 单专家门禁失败"
rm -f /tmp/invest_result_${CODE}_${victim}.md.bak

# 同批次第二次 retry 必须被门禁拒绝。
victim2="macro-cyclist"
mv /tmp/invest_result_${CODE}_${victim2}.md /tmp/invest_result_${CODE}_${victim2}.md.bak
if PATH="$STUB_DIR:/usr/bin:/bin:/usr/local/bin" \
   INVEST_LOG_DIR="$TEST_LOG_DIR" \
   bash scripts/run_experts.sh "$CODE" --no-prepare --retry >/dev/null 2>&1; then
    bad "同批次第二次 --retry 应被拒绝"
else
    ok "同批次第二次 --retry 被拒绝"
fi
mv /tmp/invest_result_${CODE}_${victim2}.md.bak /tmp/invest_result_${CODE}_${victim2}.md

# ══ T5: assemble_report ════════════════════════════════════════
echo
echo "[T4.5] run_challenges.sh（stub codex，7 份质询）"
rm -f /tmp/invest_challenge_prompt_${CODE}_*.txt \
      /tmp/invest_challenge_result_${CODE}_*.md \
      /tmp/invest_level3_${CODE}.json
if PATH="$STUB_DIR:/usr/bin:/bin:/usr/local/bin" \
   INVEST_LOG_DIR="$TEST_LOG_DIR" \
   RUN_EXPERTS_CONCURRENCY=3 EXPERT_TIMEOUT=60 \
   bash scripts/run_challenges.sh "$CODE" >/dev/null 2>&1; then
    ok "run_challenges exit 0"
else
    bad "run_challenges 非 0"
fi
python3 scripts/collect_challenges.py "$CODE" >/dev/null 2>&1 \
    && ok "二级质询 7/7 通过" || bad "二级质询契约失败"

# 强制构造一次三级触发，覆盖 3 份独立 prompt/result 及聚合契约。
python3 - "$CODE" <<'PYEOF'
import json, sys
from pathlib import Path
Path(f"/tmp/invest_level3_{sys.argv[1]}.json").write_text(
    json.dumps({"triggered": True}, ensure_ascii=False), encoding="utf-8"
)
PYEOF
if PATH="$STUB_DIR:/usr/bin:/bin:/usr/local/bin" \
   INVEST_LOG_DIR="$TEST_LOG_DIR" \
   RUN_EXPERTS_CONCURRENCY=3 EXPERT_TIMEOUT=60 \
   bash scripts/run_cross_reviews.sh "$CODE" >/dev/null 2>&1; then
    ok "触发时三方交叉盲审通过"
else
    bad "三方交叉盲审契约失败"
fi
rm -f /tmp/invest_level3_${CODE}.json \
      /tmp/invest_cross_prompt_${CODE}_*.txt \
      /tmp/invest_cross_result_${CODE}_*.md \
      /tmp/invest_cross_blind_${CODE}.md

echo
echo "[T5] assemble_report 报告组装"
if python3 scripts/assemble_report.py --help >/dev/null 2>&1; then
    if INVEST_REPORTS_DIR="$TEST_REPORTS_DIR" \
       python3 scripts/assemble_report.py "$CODE" >/dev/null 2>&1; then
        rep="$TEST_REPORTS_DIR/${CODE}.draft.md"
        [[ -s "$rep" ]] && ok "报告草稿生成: $(basename "$rep")" || bad "报告草稿未找到"
        ! rg -Fq '{analysis_time}' "$rep" \
            && ok "报告生成时间已展开" || bad "报告残留生成时间占位符"
        python3 scripts/verify_report.py "$rep" --data "/tmp/invest_data_${CODE}.json" --strict >/dev/null 2>&1 \
            && ok "草稿事实核查 PASS" || bad "草稿事实核查未通过"
    else
        bad "assemble_report 执行失败"
    fi
else
    echo "  - assemble_report 无 --help，跳过（接口待确认）"
fi

# 在临时报告目录走真实 --finalize + manifest，不覆盖仓库中的正式报告。
if INVEST_LOG_DIR="$TEST_LOG_DIR" python3 - "$CODE" <<'PYEOF'
import sys, tempfile
from pathlib import Path
import scripts.assemble_report as ar
import scripts.verify_manifest as vm
from scripts.cleanup_intermediates import runtime_paths

code = sys.argv[1]
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    ar.REPORTS_DIR = root
    vm.REPORTS_DIR = root
    sys.argv = ["assemble_report.py", code]
    assert ar.main() == 0
    draft_path = root / f"{code}.draft.md"
    draft = draft_path.read_text(encoding="utf-8")
    draft = draft.replace("entry_strategy: 待裁判长填写", "entry_strategy: 分批买入并保留安全边际")
    draft = draft.replace("待裁判长填写", "已完成裁判长复核")
    draft = draft.replace("[HOLD / PASS / BUY / SELL / OBSERVE]", "BUY")
    draft = draft.replace("max_allocation_pct: 0", "max_allocation_pct: 10")
    draft = draft.replace("stop_conditions: []", "stop_conditions: [现金流与利润持续背离]")
    draft = draft.replace("watch_items: []", "watch_items: [营收增速, 现金流质量]")
    draft = draft.replace(
        "knowledge_refs: []",
        "knowledge_refs: [index.md, experts/01-财务排雷官.md, experts/02-价值估值师.md]",
    )
    draft = draft.replace(
        "结构化自评审待填写",
        """| 维度 | 得分 |
|---|---:|
| 数据可追溯性 | 25 / 25 |
| 方法论忠实度 | 25 / 25 |
| 裁判诚实性与一致性 | 25 / 25 |
| 逻辑与表述 | 15 / 15 |

### 扣分明细

无扣分。

**总分：90 / 90**

**判定：PASS**""",
    )
    draft = draft.replace(
        "（裁判长在此撰写综合裁决：一票否决权检查、框架冲突裁决、评分计算说明、最终结论、主要分歧、观察指标。）",
        "七位专家结果均已完成批次、事实与清单复核。本次没有触发一票否决，"
        "认知风控结论为 PASS，机器重算分数与裁决表一致。财务、估值、成长、护城河、"
        "宏观和管理层视角之间没有无法解释的硬冲突；报告保留数据缺口的降级说明，"
        "不把未知商誉或负债分项写成零。最终裁决为 BUY，但严格受机器仓位上限约束，并持续观察现金流、盈利质量、"
        "行业竞争和管理层承诺兑现情况；若后续数据恶化，应重新运行完整分析而非沿用本批结论。"
    )
    draft_path.write_text(draft, encoding="utf-8")
    sys.argv = ["assemble_report.py", code, "--finalize"]
    assert ar.main() == 0
    final_path = root / f"{code}.md"
    assert vm.verify(str(final_path))["status"] == "PASS"
    assert not [path for path in runtime_paths(code) if path.exists()]
    assert not draft_path.exists()
PYEOF
then
    ok "临时目录定稿与 manifest 验证 PASS"
else
    bad "临时目录定稿或 manifest 验证失败"
fi
fi  # DATA_READY

# ══ T6: daily_analysis / cron（stub 模式） ═════════════════════
echo
echo "[T6] 调度脚本"
bash -n scripts/daily_analysis.sh && ok "daily_analysis.sh 语法" || bad "daily_analysis.sh 语法错误"
bash -n scripts/cron_trigger.sh && ok "cron_trigger.sh 语法" || bad "cron_trigger.sh 语法错误"
ACTIVITY_LOG="$TEST_LOG_DIR/activity.jsonl" INVEST_LOG_DIR="$TEST_LOG_DIR" \
    bash scripts/daily_analysis.sh --dry-run >/dev/null 2>&1 \
    && ok "daily_analysis --dry-run exit 0" || echo "  - daily_analysis --dry-run 非 0（可能无候选股票，人工确认）"

# ══ T7: 发布检查 ═══════════════════════════════════════════════
echo
echo "[T7] 发布检查"
bash tests/test_agent_backend.sh >/dev/null 2>&1 \
    && ok "agent 后端同源选择与跨后端保护" \
    || bad "agent 后端选择契约失败"
if rg -n '^[[:space:]]*python3 .*cleanup_intermediates\.py' \
    scripts/run_experts.sh scripts/run_challenges.sh scripts/run_cross_reviews.sh >/dev/null; then
    bad "认知阶段仍在失败分支自动清理现场"
else
    ok "认知阶段失败默认留证、不自动清理"
fi
# SKILL.md 引用的脚本文件全部存在
missing=0
for f in $(grep -oP '(?<!/)scripts/[a-z_]+\.(sh|py|txt)' SKILL.md | sort -u); do
    [[ -f "$f" ]] || { bad "SKILL.md 引用缺失: $f"; missing=1; }
done
[[ $missing -eq 0 ]] && ok "SKILL.md 脚本引用完整"
# 框线字符残留扫描（P1 污染回归）
grep -qE '^[│╰╭─]+' SKILL.md && bad "SKILL.md 仍有框线字符残留" || ok "SKILL.md 无终端污染残留"
# 密钥扫描：跟踪文件中不出现真实 token 值（变量名引用不算泄漏）。
# tushare token 为 48+ 位十六进制；同时确认 .env 未被跟踪。
if git ls-files | xargs grep -lE '[0-9a-f]{48,}|sk-[a-zA-Z0-9]{20,}' 2>/dev/null | grep -q .; then
    bad "跟踪文件中疑似泄漏密钥"
elif git ls-files --error-unmatch .env >/dev/null 2>&1; then
    bad ".env 被 git 跟踪"
else
    ok "跟踪文件无密钥泄漏"
fi

# ══ T8: 中间数据清理 ═════════════════════════════════════════
echo
echo "[T8] 中间数据清理"
cleanup_runtime_artifacts
if has_runtime_artifacts; then
    bad "仍有 $CODE 的 /tmp 中间文件残留"
else
    ok "$CODE 的 /tmp 中间文件已清理"
fi
[[ "$(draft_state)" == "$REPO_DRAFT_STATE_BEFORE" ]] \
    && ok "skill 目录中的报告草稿状态未被测试改变" \
    || bad "skill 目录中的报告草稿被测试改变"
[[ "$(sha256sum "$SOURCE_DB")" == "$SOURCE_DB_STATE_BEFORE" ]] \
    && ok "源数据库未被集成测试改变" \
    || bad "源数据库被集成测试改变"

# ══ 汇总 ═══════════════════════════════════════════════════════
echo
echo "════════════════════════════════════════════════"
echo " 结果: $PASS 通过, $FAIL 失败"
echo "════════════════════════════════════════════════"
[[ $FAIL -eq 0 ]]
