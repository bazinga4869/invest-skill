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

# 默认标的需满足：本地 DB 有财务/行情数据 + ~/企业年报 有近 5 年 sections JSON
# （prepare_prompts 对年报文本硬失败）。603605.SH（珀莱雅）两者齐全。
CODE="${1:-603605.SH}"
STUB_DIR="$(mktemp -d /tmp/invest_test_stubs.XXXXXX)"
PASS=0
FAIL=0

ok()   { PASS=$((PASS+1)); echo "  ✓ $*"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $*"; }
check(){ if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi }

cleanup() {
    rm -rf "$STUB_DIR"
    # T5 生成的草稿是 stub 内容，不留在 reports/ 里污染
    rm -f "$SKILL_ROOT/reports/invest_tool/${CODE}.draft.md"
}
trap cleanup EXIT

# ── stub agent：codex 走 `codex exec -o <rf> -`（CLI 写结果文件）────────────
# 从 -o 路径提取 expert_id，从 /tmp/invest_data_<code>.json 提取 trade_date，
# 生成 collect_results 可校验通过的 frontmatter 结果。
cat > "$STUB_DIR/codex" <<'EOF'
#!/bin/bash
# stub codex：支持 `codex exec -o <rf> -`，prompt 从 stdin 读
out=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        *)  shift ;;
    esac
done
prompt="$(cat)"
[[ -n "$out" ]] || { echo "stub: 缺少 -o" >&2; exit 1; }
python3 "$(pwd)/tests/stub_agent.py" "$out" <<<"$prompt"
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
- 年报文本来源：巨潮资讯网（data_tools.py annual-report 输出），
  覆盖最近 5 年年度报告的关键章节
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
echo "[T1] data_tools 子命令（真实 DB）"
for cmd in stock-info market annual quarterly balance indicators industry forecast annual-report; do
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
    echo "  - SKIP T2-T5：真实 DB 未通过 data_quality；离线数据契约由 unittest 覆盖"
else
if python3 scripts/prepare_prompts.py "$CODE" >/dev/null 2>&1; then
    ok "prepare_prompts exit 0"
else
    bad "prepare_prompts 失败"
fi
n=$(ls /tmp/invest_prompt_${CODE}_*.txt 2>/dev/null | wc -l)
[[ $n -eq 7 ]] && ok "7 份 prompt 文件（实际 $n）" || bad "prompt 文件数 $n ≠ 7"
[[ -s /tmp/invest_data_${CODE}.json ]] && ok "invest_data JSON 存在" || bad "invest_data JSON 缺失"
[[ -s /tmp/invest_annual_${CODE}.txt ]] && ok "年报文本存在" || bad "年报文本缺失"
python3 -c "
import json
d = json.load(open('/tmp/invest_data_${CODE}.json'))
assert 'audit' in d, 'all 输出缺 audit 键'
assert d['market']['trade_date'], '缺 trade_date'
" 2>/dev/null && ok "data JSON 含 audit/trade_date" || bad "data JSON 结构不完整"

# ══ T3: run_experts（stub 后端）全管线 ═════════════════════════
echo
echo "[T3] run_experts.sh（stub codex，7 专家全成功）"
rm -f /tmp/invest_result_${CODE}_*.md
if PATH="$STUB_DIR:/usr/bin:/bin:/usr/local/bin" \
   RUN_EXPERTS_CONCURRENCY=7 EXPERT_TIMEOUT=60 \
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

# T4c: --retry 幂等重试只补跑失败专家
if PATH="$STUB_DIR:/usr/bin:/bin:/usr/local/bin" \
   RUN_EXPERTS_CONCURRENCY=7 EXPERT_TIMEOUT=60 \
   bash scripts/run_experts.sh "$CODE" --no-prepare --retry >/dev/null 2>&1; then
    ok "--retry 后 exit 0"
else
    bad "--retry 后仍失败"
fi
[[ -s /tmp/invest_result_${CODE}_${victim}.md ]] && ok "--retry 补齐 $victim" || bad "--retry 未补齐"
rm -f /tmp/invest_result_${CODE}_${victim}.md.bak

# ══ T5: assemble_report ════════════════════════════════════════
echo
echo "[T4.5] run_challenges.sh（stub codex，7 份质询）"
rm -f /tmp/invest_challenge_prompt_${CODE}_*.txt \
      /tmp/invest_challenge_result_${CODE}_*.md \
      /tmp/invest_level3_${CODE}.json
if PATH="$STUB_DIR:/usr/bin:/bin:/usr/local/bin" \
   RUN_EXPERTS_CONCURRENCY=7 EXPERT_TIMEOUT=60 \
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
    if python3 scripts/assemble_report.py "$CODE" >/dev/null 2>&1; then
        rep="reports/invest_tool/${CODE}.draft.md"
        [[ -s "$rep" ]] && ok "报告草稿生成: $(basename "$rep")" || bad "报告草稿未找到"
        python3 scripts/verify_report.py "$rep" --data "/tmp/invest_data_${CODE}.json" --strict >/dev/null 2>&1 \
            && ok "草稿事实核查 PASS" || bad "草稿事实核查未通过"
    else
        bad "assemble_report 执行失败"
    fi
else
    echo "  - assemble_report 无 --help，跳过（接口待确认）"
fi

# 在临时报告目录走真实 --finalize + manifest，不覆盖仓库中的正式报告。
if python3 - "$CODE" <<'PYEOF'
import sys, tempfile
from pathlib import Path
import scripts.assemble_report as ar
import scripts.verify_manifest as vm

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
bash scripts/daily_analysis.sh --dry-run >/dev/null 2>&1 \
    && ok "daily_analysis --dry-run exit 0" || echo "  - daily_analysis --dry-run 非 0（可能无候选股票，人工确认）"

# ══ T7: 发布检查 ═══════════════════════════════════════════════
echo
echo "[T7] 发布检查"
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

# ══ 汇总 ═══════════════════════════════════════════════════════
echo
echo "════════════════════════════════════════════════"
echo " 结果: $PASS 通过, $FAIL 失败"
echo "════════════════════════════════════════════════"
[[ $FAIL -eq 0 ]]
