# INV-DES-06-POSITION-SCOPE-01 — 仓位语义范围化设计决定

- **Status:** `DECISION_PROPOSED` / `DRAFT` / `NOT_RELEASED` / `NOT_READY_FOR_CODE`（§6 四项已由 lead 裁定；仅剩"② 改动作者与授权来源"未闭合）
- **范围:** 仅针对工作树中 ② 组未提交改动的**语义、理由、影响面与验收条件**。不含实现授权、不含代码审查结论、不构成 commit 许可。
- **作者:** skill专家（2026-11-10，Asia/Shanghai）
- **证据基础（已读）:** 本群 investPM 对 ② 组的改动描述；工作树当前文档文本 `SKILL.md:212`、`references/report-gates.md:17`、`references/execution.md` 相关 hunk；`git status --porcelain` 与 `git diff --stat`（仅元数据）。
- **他人提供的证据（未由我复验）:** lead 于 2026-11-10 的 bounded 符号定位结论——校验实现在 `scripts/assemble_report.py:1056–1076`，冻结上下文取自 `load_data_summary(ts_code)["user_context"]`；`prepare_prompts.py` 对 `user_context`/`scope` 零命中；全仓写入方仅 `assemble_report.py`、`tests/test_report_gates.py`、`SKILL.md:212`、`references/report-gates.md:17`。本页引用该结论时**一律注明来源**，不当作本人核实。
- **未做:** 未读源码（`scripts/*.py`、`shared/*.py`）、未运行代码或测试、未访问 DB/runtime/真实数据、未暂存或提交。
- **结论先行:** 三项决定成立，但**必须成套生效**。单独删除旧校验而不补齐 scope 一致性校验，会产生门禁空窗（见 §2），属未验证变更。

---

## 1. 三项决定

### D1 通用研究强制零新增仓

通用研究（默认路径）必须满足：`position_advice.scope=general_research`、`user_context=null`、`existing_position_action=NONE`、`new_allocation_pct=0`。总仓位上限只表示研究情景上限，不是个人账户建议。

**理由**

1. **适当性输入缺失。** 没有经用户确认的持仓、风险承受能力、期限和资金基数时，任何 `new_allocation_pct>0` 都等于对某个未知账户的隐含下单建议，无法验证适当性。
2. **可复现性。** 同一份研究结论在不同账户上应是不同动作；把仓位写进通用产出，会让"同一批次产出"无法复现为同一语义。
3. **责任边界。** 报告是研究情景，不是投资建议；零仓是让这条边界在字段层面可机器校验，而非只写在文档里。
4. **失败关闭。** 缺上下文时默认零仓，而不是按乐观假设填一个数，符合本项目既有的 fail-closed 取向。

**影响面:** 所有 `BUY/PASS` 结论的仓位字段；裁判 YAML 的仓位段；finalize 前的仓位语义校验；报告正文措辞（不得出现"买入 X%"式个人化表述）。存量报告的仓位数值与新语义不可比。

### D2 个性化必须绑定同批冻结上下文

`scope=personalized` 必须同时具备：`user_context.authorized_personalized=true`，以及 `request`、`holdings`、`risk_tolerance`、`investment_horizon`、`capital_base`，且该上下文与**同批次快照**一致。缺任一字段、未授权、或与批次不一致即拒绝。

**理由**

1. **可审计。** 适当性判断的输入必须可追溯、可冻结；事后补写的持仓等于事后编造理由。
2. **防篡改。** 与 `batch_id` / 快照 hash 绑定，堵住 prepare 之后手改快照这条捷径。
3. **不猜。** 缺资料时不得臆造默认值，也不得用"典型投资者"假设替代。
4. **诚实标注能力。** `SKILL.md:212` 已明确：准备入口当前不能安全纳入这些资料时，应停止个性化建议、保留通用研究范围，**不得声称已支持完整个性化采集流程**。

**影响面:** 按 lead 的 bounded 定位（2026-11-10，未由我复验），`prepare` 入口对 `user_context`/`scope` 零命中，个性化路径**当前必然被拒绝**。即 D2 处于"规则已定义、入口未接入"状态。

**现态记录（必须写进任何对外说明）:** 入口未接入 ⇒ 个性化请求必须被拒、产出必须落 `general_research`；不得以"规则已写"推断"能力已具备"，任何文案不得称"已支持个性化采集"。这不是缺陷隐瞒——`SKILL.md:212` 本身已规定该情形应停止个性化建议——但把它当"已支持"就是虚假能力声明。

### D3 删除 `BUY/PASS` 必须 `new_allocation_pct>0`

**理由**

1. 该规则把**评级**与**个人资金动作**强制耦合，与 D1 直接冲突：通用研究要求零仓，旧规则又要求 BUY/PASS 必须正仓，二者不可能同时满足。
2. 二者并存的实际后果只有三种：伪造仓位、为了过门禁把评级降级、或绕过校验。三种都是质量损失。
3. 删除**不是放松门禁**，而是把约束从"必须有仓位"换成"仓位语义必须显式标注且与 scope 自洽"。约束总量不降反升（新增 scope 枚举、通用零仓、个性化完整性三项）。
4. `BUY` 表达的是研究判断，不是对该用户的买入指令；评级与仓位解耦才能让二者各自可验证。

**影响面:** 原有校验点移除。若不补齐新校验即为空窗（见 §2）。
**判定依据:** `references/report-gates.md:17` 已写明"`BUY/PASS` 不再强制正新增仓位"，与 D1/D2 同段落，属同一决定的文档表达。

---

## 2. 为什么必须成套：删除与补偿

| 旧规则 | 问题 | 新组合的补偿 | 只删不补的后果 |
|---|---|---|---|
| `BUY/PASS` ⇒ `new_allocation_pct>0` | 与 D1 冲突，无法满足 | AC2 通用零仓 + AC3 评级与仓位解耦 | 仓位字段完全无约束，可写任意值 |
| 无 scope 概念 | 通用与个性化混在一份产出里，无法区分 | AC1 scope 枚举强制显式 | 无法判断某条建议该受哪套规则约束 |
| 无用户上下文校验 | 可声称个性化却不给依据 | AC4/AC5 完整性与绑批校验 | "个性化"成为免检标签 |

---

## 3. 影响面清单

| 文件 | 变更量（`git diff --stat`） | 与 ② 的关系 | 证据状态 |
|---|---|---|---|
| `SKILL.md` | 80 行 | `:212` 仓位语义段落即 ② 的规则正文 | 已读当前文本 |
| `references/report-gates.md` | 7 行 | `:17` 门禁第 5 条含 scope/上下文/BUY-PASS 三句 | 已读当前文本 |
| `scripts/assemble_report.py` | 45 行 | finalize 前仓位/scope 校验在其 `:1056–1076`；冻结上下文取自 `load_data_summary(ts_code)["user_context"]` | lead bounded 定位，**我未复验** |
| `tests/test_report_gates.py` | 32 行 | ①②③ 共用测试面 | **未读**、未运行 |
| `references/execution.md` | 4 行 | 与 ② 的仓位语义**无写入关系**（按 lead 写入方清单） | 排除，不计入影响面 |
| `shared/contracts.py` | 2 行 | 与本组语义**无写入关系**（按 lead 写入方清单） | 排除，不计入影响面 |

**已裁定**

- ② 与 ① 的顺序：**② 在前**（仓位/scope 是内容校验，独立投研复核是最后一道闸；签收后不得再出现阻塞性校验失败）。
- 存量口径：**只对新批次生效**，已发布报告不回溯判 FAIL、不重跑。
- 定位结论：`prepare_prompts.py` 对 `user_context`/`scope` 零命中 ⇒ 个性化路径当前必然被拒（此结论由 lead 给出）。

**仍未知**

- ② 的改动**作者与授权来源**：`UNKNOWN`，investPM 正在核；核清前不得提交。

---

## 4. 失败关闭与禁止行为

1. 缺字段、值非法、上下文不一致 → **失败（FAIL）**，不得静默降级、不得填默认值。
2. 准备入口不支持用户上下文 → 显式停止个性化建议，产出落回 `general_research`，并在产出中记录降级原因；**不得**声称已支持个性化。
3. 不得在 `prepare` 之后修改快照或 `user_context`；任何修改须重开批次。
4. 不得把 `scope=personalized` 当作"可以用任意仓位"的开关；它只放宽"零仓"，不放宽完整性。
5. 不得以"旧规则已删除"为由跳过新校验——删除与新增是同一条决定的两半。

---

## 5. 验收条件（同一份未提交工作树）

| AC | 内容 | 通过判据 |
|---|---|---|
| AC1 | scope 枚举 | 仅接受 `general_research` / `personalized`；其他值 FAIL，错误信息含字段名与非法值 |
| AC2 | 通用零仓 | `general_research` 时 `user_context=null`、`existing_position_action=NONE`、`new_allocation_pct=0`；任一不满足 FAIL，且指明具体字段 |
| AC3 | 评级解耦 | `BUY` 或 `PASS` + `new_allocation_pct=0` → PASS（证明旧校验确已移除且评级未被绑死） |
| AC4 | 个性化完整性 | `personalized` 缺 `authorized_personalized`/`request`/`holdings`/`risk_tolerance`/`investment_horizon`/`capital_base` 任一 → FAIL |
| AC5 | 绑定同批 | `user_context` 与同批快照 hash 不一致 → FAIL；快照在 prepare 后被修改 → FAIL |
| AC6 | 不静默降级 | 缺资料时输出必须显式标 `general_research` 并记录原因；产出中不得出现个性化措辞或非零新增仓 |
| AC7 | 溯源 | 每次校验或降级留下可复核记录（scope、原因、上下文来源 hash） |
| AC8 | 存量口径 | 新规则**仅对新批次生效**；已发布报告不回溯判 FAIL、不重跑、不改写 |
| AC9 | 入口未接入现态 | `prepare` 入口未接入 `user_context`/`scope` 期间，`:personalized` 请求必须被拒绝并落 `general_research`；任何产出/文案不得声称支持个性化采集 |

刚性要求：AC1–AC7 中任意一条无对应测试用例，**不得**声称 ② 已验证；AC8/AC9 为口径与现态约束，需 PM 在批次台账中显式登记。测试通过也不等于验收，验收需独立 QA + PM 记录。

---

## 6. 裁定结果（lead，2026-11-10）

| 项 | 裁定 | 对本页的影响 |
|---|---|---|
| bounded 定位授权 | 已由 lead 执行完毕（符号/字段级，未读函数体） | §3 三项 `UNKNOWN` 降为已定位；证据标注为 lead 提供，我未复验 |
| ② 与 ① 的顺序 | **② 在前**，① 为最后一道闸 | 写进 §3「已裁定」；AC 不新增，但 QA 需按此顺序验 |
| 存量报告口径 | **仅新批次生效**，不回溯 | AC8 已按此改写 |
| ② 改动作者与授权来源 | 仍 `UNKNOWN`，investPM 在核 | **核清前不得提交**；本页只主张语义成立，不主张实现合规 |

**遗留：** 仅「作者与授权来源」一项未闭合。其闭合责任在 investPM，不在本页。

---

## 7. 本页不包含

不含 READY_FOR_CODE、不含实现或修改授权、不含 commit/push/merge 许可、不含对现有代码正确性的判定。本页是设计决定，不是验收结论；任何"设计通过"都不能外推为"实现已验证"。
