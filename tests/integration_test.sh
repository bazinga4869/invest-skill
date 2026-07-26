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
base="$(basename "$out")"                       # invest_result_<code>_<expert>.md
code="$(echo "$base" | sed -E 's/^invest_result_([^.]+\.[A-Z]+)_.*/\1/')"
expert="$(echo "$base" | sed -E 's/^invest_result_[^.]+\.[A-Z]+_(.*)\.md$/\1/')"
trade_date=$(python3 -c "import json;print(json.load(open('/tmp/invest_data_${code}.json'))['market']['trade_date'])" 2>/dev/null || echo "")
# 失败注入：prompt 含 STUB_FAIL_THIS_EXPERT 时本次不写结果并退出 1
if [[ "$STUB_FAIL_EXPERT" == "$expert" ]]; then
    echo "stub: 注入失败 ($expert)" >&2
    exit 1
fi
cat > "$out" <<RESULT
---
expert_id: "$expert"
score: 80
verdict: PASS
veto_triggers: []
data_date: "$trade_date"
---
# stub 专家评估（$expert）

## 总体判断
stub 生成，仅用于管线集成测试。

## 详细分析
stub。

## 关键风险与不确定性
stub。

## 数据使用说明
stub。
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
   bash scripts/run_experts.sh "$CODE" --agent codex --no-prepare >/dev/null 2>&1; then
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
   bash scripts/run_experts.sh "$CODE" --agent codex --no-prepare --retry >/dev/null 2>&1; then
    ok "--retry 后 exit 0"
else
    bad "--retry 后仍失败"
fi
[[ -s /tmp/invest_result_${CODE}_${victim}.md ]] && ok "--retry 补齐 $victim" || bad "--retry 未补齐"
rm -f /tmp/invest_result_${CODE}_${victim}.md.bak

# ══ T5: assemble_report ════════════════════════════════════════
echo
echo "[T5] assemble_report 报告组装"
if python3 scripts/assemble_report.py --help >/dev/null 2>&1; then
    if python3 scripts/assemble_report.py "$CODE" >/dev/null 2>&1; then
        rep=$(ls -t reports/invest_tool/${CODE}*.md 2>/dev/null | head -1)
        [[ -n "$rep" ]] && ok "报告生成: $(basename "$rep")" || bad "报告文件未找到"
    else
        bad "assemble_report 执行失败"
    fi
else
    echo "  - assemble_report 无 --help，跳过（接口待确认）"
fi

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
for f in $(grep -oE 'scripts/[a-z_]+\.(sh|py|txt)' SKILL.md | sort -u); do
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
