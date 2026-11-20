# INV-BACKLOG-01：待办与登记

本文件只做**登记**，不含实现。所有条目在阶段 3（全链路，待用户批准）之前不进入编码。

| 单号 | 主题 | 状态 |
|---|---|---|
| `BL-01` | CI 侧校验 `Committed-by` trailer | OPEN（等 CI 接入窗口） |
| `INV-DEFECT-DIM-01` | `evaluate_calculation` 不校验量纲 | OPEN（只立单，不实现） |
| `REG-UNIT-01` | token 单位与模板单位并存（`元 [calc: …]元/股`） | OPEN（登记，暂不改） |

状态词只有三个：`OPEN`（已登记待做）、`WAITING_USER`（等用户授权）、`DONE`（有提交与复核证据）。

---

## BL-01：CI 侧校验 `Committed-by` trailer

**背景与依据**：本 clone 没有装钩子——`.githooks` 不存在，`.git/hooks` 只有 `*.sample`。所以 `Committed-by:` 是手写的，仓内**无从证伪**「没用 `--no-verify`」。lead 2026-11-20 裁定：**不装本机钩子**（只约束一台机、谁都能绕），改为 CI 侧校验 trailer。

**作用对象（范围要窄）**

1. 只校验推到 `main` 的提交；其他分支不拦。
2. 非 merge 提交逐个校验；merge 提交按「被合并分支的每个提交」校验，squash 合并按合并后的单个提交校验。
3. 不做历史追溯：从 CI 启用点算起，启用时的 `main` sha 写进 CI 配置常量（如 `TRAILER_ENFORCE_FROM=<sha>`），早于它的提交跳过。

**看哪个字段**

提交消息**末尾的 trailer 块**（最后一段连续的 `Key: value` 行）里必须有且仅有一行：

```text
Committed-by: <bot-name>
```

`<bot-name>` 必须精确匹配 roster 白名单（大小写敏感；前后空格不算匹配）。roster 取自 CI 变量或仓内清单文件，两者只允许一个来源，避免双份漂移。

**失败判据与报错码**

| 情形 | 码 | 期望 |
|---|---|---|
| trailer 块里没有 `Committed-by` | `E_CI_NO_COMMITTED_BY` | rc=1 |
| 出现多行 `Committed-by` | `E_CI_MULTI_COMMITTED_BY` | rc=1 |
| 值不在白名单 | `E_CI_UNKNOWN_BOT` | rc=1 |
| 值是占位（`待填`/`待补`/`TBD`/`TODO`/`FIXME`/`unknown`/`UNKNOWN`/`none`/`null`/`<…>`） | `E_CI_PLACEHOLDER_COMMITTED_BY` | rc=1 |
| 有 `Committed-by` 但不在末尾 trailer 块（在正文中段）、或以缩进形式出现 | `E_CI_NOT_IN_TRAILER_BLOCK` | rc=1 |
| 单行、在末尾 trailer 块、值在白名单 | — | rc=0 |

报错输出必须含三样：错误码、违规 commit 短 sha、一行修法（例：`git commit --amend -m "…\n\nCommitted-by: investPM"`）。CI 只校验，**不重写历史**。

**负例（CI 自测要覆盖）**

1. 无 trailer 的提交 → `E_CI_NO_COMMITTED_BY`
2. 两行 `Committed-by` → `E_CI_MULTI_COMMITTED_BY`
3. `Committed-by: 待填` → `E_CI_PLACEHOLDER_COMMITTED_BY`
4. `Committed-by: 某人`（不在白名单）→ `E_CI_UNKNOWN_BOT`
5. 正确内容但写在正文中段 → `E_CI_NOT_IN_TRAILER_BLOCK`

**不做**：不装本机钩子、不动 `.githooks`、不引新依赖、不改写已推送提交。

---

## INV-DEFECT-DIM-01：`evaluate_calculation` 不校验量纲

**现象**：`evaluate_calculation` 只比对数值能否从 formula 复算，不比对**量纲**。同一个数配不同量纲的模板单位仍能通过门禁，例：`9.1744 元 [calc: …]元/股`——`元` 与 `元/股` 量纲不同，门禁 rc=0。

**为什么单独立单**：这是**语义层缺失**（量纲模型），与 `%`／`个百分点` 的渲染层修复、`]%` 重复单位的形状检查不在同一层，塞进 repair 系列会混淆两类缺陷。

**与现有诊断的关系**：现有 `invalid_calculations` 判「单位由 token 自带时又与模板字面单位冲突（重复单位）」；`untraced_numbers` 判「数字没有 calc/source 溯源」。两者都**不判量纲是否匹配**，所以本缺陷现在属于静默通过。

**可执行判据（实现时按此造负例）**

| # | 输入 | 期望 |
|---|---|---|
| 1 | `current` 单位 `元`，模板单位 `元/股` | 新诊断 `unit_mismatch`，rc=1 |
| 2 | `current` 单位 `亿元`，模板单位 `元` | `unit_scale_mismatch`（量级差 1e8），rc=1 |
| 3 | `current` 单位 `元/股`，模板 `元/股` | rc=0（正例） |
| 4 | `%` 与 `个百分点` 混用 | 现有 `invalid_calculations` 已拦（回归，不重复计新项） |

落点：`shared/expert_result_v3.py` 的 `evaluate_calculation` + `scripts/collect_results.py` 的 `build_expert_diagnostics`；诊断名不得与 `invalid_calculations`／`untraced_numbers` 重名。

**状态**：`OPEN`，只立单不实现。修不修、什么时候修，等阶段 3 的用户卡。

---

## REG-UNIT-01：token 单位与模板单位并存

**现象**：`9.1744 元 [calc: …]元/股`——token 自带 `元`，模板又拼了 `元/股`。

**为什么现在不改**（三条，缺一条都不成立）

1. 属**既有模板写法**：历史批次一直这么渲染，不是本次 repair 引入的。
2. **门禁当前不判**：现有诊断只拦「`]` 后紧跟单位」的重复，`元 [calc: …]元/股` 这种中间隔着 token 的形态不在判据内。
3. **改了会动全部历史产物**：模板一改，所有历史 `checks/*.md` 的字节与 sha256 全变，已签收的证据链要整体重算——超出本批范围。

**何时处理**：与 `INV-DEFECT-DIM-01` 一起在阶段 3 评估——量纲模型落地时，顺带决定模板单位该由谁提供（token 还是模板），二者只能有一个来源。

**登记位置**：本节；不另建单。
