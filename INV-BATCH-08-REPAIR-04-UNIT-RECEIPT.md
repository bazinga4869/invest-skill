# INV-BATCH-08-REPAIR-04：百分点单位修复的执行回执（receipt）

- **收据编号**：INV-BATCH-08-REPAIR-04-UNIT-RECEIPT
- **执行人**：investPM（编排方）
- **时间**：2026-11-20 09:10–09:30 +08
- **承载提交**：`b33af26f22af5f92f611c9c2a936297c9422068d`（`fix(gate): 百分点与 % 不再是同一个单位，重复单位写法必须阻塞`），已推送到 `origin/main`，推送后 `git rev-list --count origin/main..main` = **0**
- **触发**：投研复核判定「修复只在工作树、HEAD 仍是错的」；lead 的 B1/B2/B3 + S1–S4

这份文件不是设计稿，也不是新证据来源：它只回答四个可核对的问题——**谁改的、改了哪个对象、改前改后各是什么、用哪条门禁得到的什么结论**。

---

## 1. 谁改、改了什么

| 项 | 值 |
|---|---|
| 改动对象（产物） | `batches/603605.SH-20261014-08-repair01/checks/value-valuator.md`（runtime 产物，不在 git 里） |
| 触发改动的代码 | `scripts/verify_report.py`、`shared/expert_result_v3.py`、`scripts/collect_results.py`、`tests/test_report_gates.py` |
| 改动人 | investPM（编排方）；**不是**专家重新产出，专家文本自 batch08 起未变 |
| 输入 payload | `staging/value-valuator.repair.v3.json`，SHA-256 `caec201fde8178c86c4c2c0820050d8ed5339fe168dd07d553ca587042e25404`（**未改动**） |
| 数据包 | `invest_data_603605.SH.json` / `invest_annual_603605.SH.txt`（batch08 同源，未改动） |
| 解释器 | CPython 3.11.17 + pandas 3.1.1 + pyyaml（`/tmp/inv-venv311`，由 `uv venv` 现场重建；旧 venv 已随 /tmp 清理消失） |

改动内容见 §4 与 `INV-BATCH-08-REPAIR-03-STAGE-A-EVIDENCE.md` §8；本条只记**结果**。

---

## 2. 改前 / 改后（同一 payload、同一数据、同一门禁）

| | 改前 | 改后 |
|---|---|---|
| 代码 | `5bc1a0d`（HEAD，`calculation_unit()` 把「百分点」折成 `%`） | `b33af26`（百分点是独立单位） |
| 渲染文本（L35） | `粗略差额为 6.9478% [calc: 100*(1/market.pe_ttm)-macro.indicators.shibor.week_pct; inputs: …]。` | `粗略差额为 6.9478 个百分点 [calc: 100*(1/market.pe_ttm)-macro.indicators.shibor.week_pct; inputs: …]。` |
| 产物文件 SHA-256 | `07211fcbd8a276ec3b292e75a551f4a16a760eaf194e8f97cc1ff025dad83391`（17878 B） | `922e6f1646832ff9e3aade47db248f49e6e0cb780ff2035236128fefec8a912a` |
| 同一份文本的权威门禁结论 | **rc=0「✓ 全部诊断为空，可以 commit」** ← 盲区 | rc=1，判 `untraced_numbers` 2 条（`L35 '6.9478%'`、`L72 '6.9478%'`） |

上表第 4 行是本次返工的全部理由：**改前的错误写法能过门禁，改后不能**。数值 6.9478 与 L83 的 8 等其余数字全程未变。

改前产物的渲染方法（任何人可复现）：`git archive 5bc1a0d | tar -x -C /tmp/before_head`，然后用 `/tmp/before_head/scripts/expert_result_v3.py` 编译同一份 `staging/value-valuator.repair.v3.json`。

---

## 3. 跑的哪条门禁、rc 与判词原文

权威门禁是 `<invest-kb>/04_stock-analysis-expert/tools/gate_precheck.py`（`--skill-root` 指 skill 本体、`--runtime` 指 runtime），其诊断代码 `from scripts.collect_results import build_expert_diagnostics` 与批次门禁同源。

```text
# A) 改前产物 + 改前代码（复现盲区）
门禁预检：value-valuator @ before_head_vv.md（数据包 603605.SH，诊断代码来自 skill 本体）
✓ 全部诊断为空，可以 commit
rc=0

# B) 改前产物 + 改后代码（补丁生效，错误写法被拦）
✗ untraced_numbers：2 条
    L35 '6.9478%' 以市盈率倒数估算盈利收益率，得到 8.2738% [calc: 100*(1/market.pe_ttm); inputs: market.pe_ttm]；…
    L72 '6.9478%' | 盈利收益率 vs 无风险利率 | DONE | …
rc=1

# C) 改后产物 + 改后代码（正确写法，放行）
门禁预检：value-valuator @ value-valuator.md（数据包 603605.SH，诊断代码来自 skill 本体）
✓ 全部诊断为空，可以 commit
rc=0
```

另做的两条**形状回归**（把错误写法直接喂进门禁，证明它不再静默通过）：

```text
# D) "6.9478% [calc: …] 个百分点"（同一数字两种单位）
✗ invalid_calculations：2 条
    L3 '6.9478% [calc: 100*(1/market.pe_ttm)-mac' …
    L3 '] 个百分点' …
rc=1

# E) "1.326% [source: …]%"（token 单位 + 模板字面单位重复）
✗ invalid_calculations：1 条
    L3 ']%' 短期利率 1.326% [source: macro.indicators.shibor.week_pct]%
rc=1
```

---

## 4. 完整重放命令

```bash
R=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime
K=/Volumes/MacData/workspace/invest/invest-kb
D=$R/batches/603605.SH-20261014-08-repair01

# 用已提交的代码取一份干净树（不读工作树）
rm -rf /tmp/head && mkdir -p /tmp/head
git -C /Volumes/MacData/workspace/invest-skill archive b33af26 | tar -x -C /tmp/head

# 渲染
INVEST_RUNTIME_DIR=$R python3.11 /tmp/head/scripts/expert_result_v3.py compile 603605.SH value-valuator \
  $D/staging/value-valuator.repair.v3.json --sidecar /tmp/vv.v3.json --markdown /tmp/vv.md

# 权威门禁（--skill-root 必须是这份干净树或 skill 本体，给错会 rc=2）
python3.11 $K/04_stock-analysis-expert/tools/gate_precheck.py /tmp/vv.md \
  --expert value-valuator --skill-root /tmp/head --runtime $R
# 期望 rc=0；/tmp/vv.md 的 SHA-256 应为 922e6f1646832ff9e3aade47db248f49e6e0cb780ff2035236128fefec8a912a
```

---

## 5. S1：用已提交的 commit 重渲七位（产物与 commit 绑定）

从 `git archive b33af26` 的干净树渲染、跑门禁，再与 runtime 现有 `checks/*.md` 逐字节比对：

| 专家 | compile rc | gate rc | 与 runtime 产物比对 | `checks/<expert>.md` SHA-256 |
|---|---|---|---|---|
| financial-auditor | 0 | 0 | IDENTICAL | `c08eb735f3ac2421fe8af6fb350aa8c58ca3e7a263fc62029fb9985d64de75e4` |
| value-valuator | 0 | 0 | IDENTICAL | `922e6f1646832ff9e3aade47db248f49e6e0cb780ff2035236128fefec8a912a` |
| moat-analyst | 0 | 0 | IDENTICAL | `a9c62447630e3ec94d990d398305265bd3b6d7759b1dbae6f8734189a14322db` |
| cognitive-controller | 0 | 0 | IDENTICAL | `10b62d32c83ae754bcdd068a3c2e2ef2a422dceb251df004f5da1d3ef2a4bc15` |
| macro-cyclist | 0 | 0 | IDENTICAL | `c6b97d2ab374af96aa6b7e06661befa79a0ac7ea27ee7a4558f6852500000f0c` |
| growth-assessor | 0 | 0 | IDENTICAL | `c4e7152906a904bf394c37215a39138cf18ba5274707511b99e7c36adf973dac` |
| management-auditor | 0 | 0 | IDENTICAL | `13e60eab9ce49507f89861d6d4a7b47998c05e7671563faada0509632f2b5de3` |

结论：7/7 `compile=0 && gate=0`，且**从 commit 渲出的字节与 runtime 现有产物完全一致**——11-19 用未提交代码渲的那批产物，与 `b33af26` 脱钩的问题已消除。

---

## 6. 负控（batch08 原始产物，用新门禁复跑）

| 专家 | rc | 诊断形状 |
|---|---|---|
| financial-auditor | 1 | untraced_numbers 1 |
| value-valuator | 1 | untraced_numbers 3 **+ invalid_calculations 6（新增命中）** |
| moat-analyst | 1 | untraced_numbers 1 |
| cognitive-controller | 1 | untraced_numbers 1 |
| macro-cyclist | 1 | untraced_numbers 1 |
| management-auditor | 0 | 全部诊断为空 |
| growth-assessor | 编译失败 | `calc 无法复算: selling_expense/revenue|F243,F202`（原状） |

**披露**：value-valuator 的 `untraced_numbers` 仍是原判词的 3 条，新增的 6 条 `invalid_calculations` 全部是「`]%`、`] 个百分点`」重复单位——新诊断在**原始产物**上的真实命中，不是回归。因此不能再说「负控与 batch08 逐条完全一致」，只能说「**形状一致（5 FAIL / 1 PASS / 1 compile FAIL），value-valuator 多 6 条新增类别**」。

---

## 7. S2：growth-assessor 失败件存档

`batches/603605.SH-20261014-08-repair01/failure-archive/growth-assessor/`：

| 文件 | 说明 | SHA-256 |
|---|---|---|
| `original.next` | 2026-10-25 21:55 原生输出原件（transaction `2e3c97d7…`），从 runtime 根目录隐藏 `.next` 拷入 | `d3eecdad9dda7ca05ba31972bda2f35ec41fada2c7bcd7334f48f777f9091807` |
| `compile.batch08.log` | batch08 当时记录的失败（一行） | 随文件 |
| `README.md` | 重放命令 + 边界（原件不得覆盖） | 随文件 |

重放已实测：`compile` 仍返回 `{"status":"ERROR","error":"calc 无法复算: selling_expense/revenue|F243,F202"}`、rc=2。

---

## 8. S3 / S4

- **S3**：单位常量由 `百分点` 改为 `个百分点`，`normalize_report_unit()` 同时接受两种写法并归一到带量词形态，`_join_number_unit()` 给中文单位补空格 → 渲染为 `6.9478 个百分点 [calc: …]`（本 receipt §2 的「改后」即该形态）。
- **S4**：`README.md`「测试与全链路状态」补一条——外置盘上偶发 `rc=2「✗ skill 根目录不对」` 是 `scripts/collect_results.py` 瞬时不可见，**重跑即可；连续两次都 rc=2 才算环境问题**，别当门禁真失败去改判据。

---

## 9. 限制（必须随结论一起读）

1. **仍不是全链路**：`commit`/`advance`/challenges/cross-review/裁决/`assemble_report`/report-wiki 物化/manifest/复核签收/发布一律未跑。
2. **repair01 只作证据与门禁回归夹具**（lead 2026-11-20 书面决定，见 `INV-BATCH-08-REPAIR-03-STAGE-A-EVIDENCE.md` §6.2）：不得作为发布来源；对外报告必须由专家按同一判词重跑产出。
3. **本 receipt 不覆盖**：`evaluate_calculation` 仍不校验 calc 操作数量纲（同量级量纲混用可能静默通过），属独立缺陷，已单独立单为 `INV-DEFECT-DIM-01`（见 `INV-BACKLOG-01.md`），本次不实现。
4. **推送通道（2026-11-20 09:20 已修复，本节为实测事实）**

   - **改前**：`origin` = `git@github.com:bazinga4869/invest-skill.git`（SSH）。本机 `~/.ssh` 只有 `homelab_ops_ed25519`、`rustdesk_tunnel_ed25519`，没有 GitHub 的 key，`ssh-add -l` 无 identity，SSH 通道实际从来不通。本次两笔提交（`b33af26`、`28190f1`）是在改之前推的，靠显式 `-c credential.helper='!gh auth git-credential'` + 直接写 HTTPS URL 绕行。
   - **改后**：`origin` = `https://github.com/bazinga4869/invest-skill.git`（HTTPS），由 lead 于 2026-11-20 09:20 +08 修改。`credential.helper=osxkeychain`（系统级，来自 CommandLineTools 的 gitconfig），`gh` 已登录 `bazinga4869`。
   - **验证命令与结果**：

     ```text
     $ git config --get remote.origin.url
     https://github.com/bazinga4869/invest-skill.git
     $ git config --get credential.helper
     osxkeychain
     $ git ls-remote origin main
     <sha>	refs/heads/main            # 短 sha 28190f1，与本地 origin/main 一致
     $ GIT_TERMINAL_PROMPT=0 git push --dry-run origin main
     Everything up-to-date
     $ git fetch -q origin main && git rev-list --count origin/main..main
     0
     ```

   - **一行回退**（不要执行，回退需要先造 GitHub key 并注册，属用户凭据层面）：`git remote set-url origin git@github.com:bazinga4869/invest-skill.git`
   - **结论**：推送通道现在是 HTTPS，可直接 `git push origin main`，不需要再带 `gh auth git-credential` 那套写法。

---

## 10. 复核建议

投研复核只需核三处：§2 的「改前能过、改后不能过」、§5 的七位 SHA-256 是否与 `git archive b33af26` 自渲一致、§6 的负控形状与「新增 6 条」是否如实披露。以上都不需要访问数据库、不涉及专家调用。
