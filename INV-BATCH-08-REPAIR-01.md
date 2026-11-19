# INV-BATCH-08-REPAIR-01 · 真实批次 603605.SH 专家层门禁修复执行方案（rev4）

- TASK-ID：`INV-BATCH-08-REPAIR-01`
- 批次：`603605.SH-20261014-08`（data_batch_id `d4450143cd0858a8260f0bd4`，transaction `2e3c97d7805891517d1515eb`）
- owner：投研流程（执行）｜独立复核：投研复核｜接受：investPM
- 依据：用户 2026-10-28 m00630「修复吧」；群公告 v1.6 第 8 条
- 状态：`REV4_FOR_REVIEW`（v1.6 第 8 条：投研复核 PASS + PM 接受后方可执行）

## 0. 变更记录

| 版本 | SHA-256 | 复核结论 |
|---|---|---|
| rev1 | `2726f4c995adaed44a41d17d4cc1a9ac4e392d47afa26d4c5279af95ec58c748` | FAIL，4 阻塞项（另有 PM 自查发现的 4 个假哈希、1 个不存在的 `data/calculation_specs.json`） |
| rev2 | `2142fbbbe2d91dc12386772171dcb907b504056a8138ed1df07311e5c718dedd` | FAIL，3 阻塞项：写集/回滚自相矛盾、N3 未证明实际约束 |
| rev3 | `feed30f569b064dbf3f163707557e9532b592ab2c2c0b95d463221d8ec9049e9` | FAIL，3 阻塞项：探针清理与"不清理现场"冲突、profile 正则过宽且非 create-only、回滚未防替换与并发 |

rev4 逐项处置（对应投研复核 2026-10-28 16:1x 意见）：

| # | 阻塞项（rev3 复核） | rev4 处置 |
|---|---|---|
| 1 | P2–P4 若意外写入成功要「立即删除禁写区文件」，与「停止、不清理现场」及禁止破坏性操作冲突；探针不能证明所有进程继承沙箱 | §7 N3 全部改为**零写入探针**：负向探针只对**已存在文件**做 `O_WRONLY` 打开（不写一个字节、不创建、不删除），即使沙箱失效也不产生任何副作用，**不设任何清理动作**；新增 P5「孙进程继承」与 P6「沙箱内 rm 被拒」。整轮只有 `run.sh` 一个入口在沙箱内启动，所有子进程天然继承（P5 实证） |
| 2 | 结果文件正则允许任意专家名；profile 不强制 14 个精确路径或 create-only；journal 的进程/禁止追加删除仅是文字约束 | §4.1 把 `regex` 换成 **14 条精确 `literal`**，并全局 `(deny file-write-unlink)`（沙箱自身禁止删除，已实测）。create-only 由三件事共同保证：精确 literal + 执行前 14 路径不存在性登记 + 新增 AC7「运行时根目录增量必须是这 14 个文件加 `repair01/` 树，多一个即 FAIL」。journal 约束改为**内容级可检**：写入必须保持 JSON 可解析且 `phase`/`transaction_id` 不变，前后哈希入链（§4.3） |
| 3 | 回滚仅凭登记哈希删除，未防核验后被替换；journal 恢复未先核对当前内容是否被他人改动 | §8 新增 **§8.2 单写者窗口**（回滚与修复期间禁止其他 Bot 操作运行时根）+ 删除前用**已打开的 fd 做 fstat 校验**（dev/ino/size/mtime_ns + fd 内容哈希）再 unlink，并登记 inode；journal 恢复前先比对当前哈希 == 记录的事后哈希，不等则**不恢复**、标 `journal_modified_by_third_party` STOP |

## 1. 目标与非目标

目标：让 `603605.SH-20261014-08` 的 7 位专家全部通过 `compile` + `gate_precheck` 并 `commit`，使批次可进入后续挑战/裁定/报告装配。

非目标：不改门禁、不放宽诊断；不改契约、schema、专家面板、checklist 规则、数据源；不重新取数；不做报告装配、manifest、发布；不触碰 RUN-02/V5 合成链（仍 STOP）；不调用 `prepare`（仍 STOP）。

## 2. 根因（PM 只读复现，实测）

6 处失败全部是专家自写作 / token 语法缺陷，不是数据缺口、不是门禁缺陷。

数据充分性：`../invest-skill-runtime/invest_data_603605.SH.json` 中 `annual[].sell_expense_yi`、`annual[].revenue_yi` 齐全；`market.pe_ttm=12.0863`、`market.pb`、`market.total_mv` 均存在。

| 专家 | 位置 | 类别 | 实测判词 |
|---|---|---|---|
| financial-auditor | L56 | 语义错配 | 数字左侧措辞被判为 revenue 路径要求，实际是余额陈述 |
| cognitive-controller | L72 | 语义错配 | `25.77%` 旁措辞被判 `market.pb` 路径，实际写现金流 |
| moat-analyst | L80 | 语义错配 | `25.77%` 同行上下文冲突（年报/可能面对的风险） |
| macro-cyclist | L78 | 语义错配 | `3.3897` 旁措辞被判要求 `total_mv` |
| value-valuator | L83 | 语义错配 | `period_count` 数字旁写现金流措辞 |
| value-valuator | L35 | calc 未绑定 + 单位不符 | 原写法 `[calc:]` 落在数字 span 之外 |
| growth-assessor | — | compile FAIL | `calc 无法复算: selling_expense/revenue\|F243,F202`；`{{C:}}` 用字段别名当公式 |

**`[calc:]` 写法实测对照**（用 `scripts/collect_results.py: build_expert_diagnostics` 对真实数据跑，2026-10-28）：

| 形态 | 文本 | 实测 `untraced_numbers` | 判定 |
|---|---|---|---|
| A | `8.2738% [calc: 100*(1/market.pe_ttm); inputs: market.pe_ttm]` | **0** | 唯一可过形态：数值与 `%` 紧贴成一个 span，tag 紧随其后；unit 为 `%` 时公式须为 `100*(1/x)` 乘式 |
| B | `8.2738 [calc: 100*(1/market.pe_ttm); inputs: market.pe_ttm]%` | 1（L5） | 必失败：`%` 落在 tag 之后，span 内无单位 |
| C | `8.2738% [calc: 100/market.pe_ttm; inputs: market.pe_ttm]` | 1（L5） | 必失败：公式形状不被 `%` 单位接受（即使算术等值） |

## 3. 输入硬绑定（任何一项不符即 STOP，不改输入去迁就）

批次与数据：

| 项 | 路径 | SHA-256 |
|---|---|---|
| 数据包 | `../invest-skill-runtime/invest_data_603605.SH.json` | `4d6125afcb26e877849ae2c2bf7c1b880bdc77400f21f3b876ae11558ead3565` |
| 年报文本 | `../invest-skill-runtime/invest_annual_603605.SH.txt` | `2b63e709639cab2c962bbcd4abf1385b51511380b262ece566c0983cef9bda83` |
| 批次台账 | `../invest-skill-runtime/batches/603605.SH-20261014-08/batch.json` | `538230eb3978f96d135305869f4f011c45e09f86960a5b8c0cc8a34d48acb9eb` |

契约与诊断代码（只读；不一致即 STOP 并回报 PM，不得就地更新哈希）：

| 项 | 路径 | SHA-256 |
|---|---|---|
| 诊断入口（`build_expert_diagnostics`） | `scripts/collect_results.py` | `3786d5f70d11765b9ce4b2b7a32a4a39d8906bc7f21e662f8bd2ce2c1a29b01e` |
| 数字溯源 / `calculation_specs()` / `SEMANTIC_PATH_RULES` | `scripts/verify_report.py` | `6cae520e664f20a6b565e4f59b7ee03cbcccf7962f3d12b973119552ab2e0cef` |
| checklist 覆盖 | `shared/checklist_verify.py` | `3ba605bcc7a687b0878a38aaa5e9ab28ea46dcdf02f4f77384b666b6c0c79157` |
| v3 编译（`{{C:}}` 变量解析） | `shared/expert_result_v3.py` | `d2df148e8218c4a3abe2e18324f404acb6925777f0af90d4ff426ca538e61b15` |

7 位专家原产物（只读，禁止改写；`../invest-skill-runtime/batches/603605.SH-20261014-08/checks/`）：

| 项 | 文件 | SHA-256 |
|---|---|---|
| financial-auditor | `financial-auditor.md` | `b0a61399ee7788e7e28699732bc08174fa0db7442b803ece7ee7a84284b158c2` |
| value-valuator | `value-valuator.md` | `0e8d53a47412807db1b6f0ebddb9ea183ab4c192e0d71d2d0c7e6c88c0f91b6b` |
| moat-analyst | `moat-analyst.md` | `f4b3048b0aa0c74effa19f2f5e22c1d664b09172a9c124ab8bf6550881136bcc` |
| cognitive-controller | `cognitive-controller.md` | `41b21b21b585a34093ab4d6519f318c3aa85181b39eb33e52046827ba03c884e` |
| macro-cyclist | `macro-cyclist.md` | `efdcf647003dac5fcb75ca253897a4e58473bef3c63eba9f2aceb7c7a5401077` |
| growth-assessor | 无 `.md`（compile FAIL 未落盘） | — |
| management-auditor | `management-auditor.md`（已 PASS，须原样提交） | `13e60eab9ce49507f89861d6d4a7b47998c05e7671563faada0509632f2b5de3` |

growth-assessor 失败现场（只读，唯一绑定）：

| 项 | 路径 | SHA-256 |
|---|---|---|
| growth staged（2026-10-25 21:55 本次真实运行产物） | `evidence/native-experts-20261025/staging-next/invest_native_output_603605.SH_experts_growth-assessor.07b158ecc72991dc15641a13ae0a9083.next` | `d3eecdad9dda7ca05ba31972bda2f35ec41fada2c7bcd7334f48f777f9091807` |

> 同目录 `…growth-assessor.02664588….next`、`….bf4c675a….next` 是 2026-10-14 历史文件，**非本次输入**，只读、不得引用、不得删除。

七份 prompt（实际使用 `invest_native_prompt_*`，与 `invest_native_original_prompt_*` 同值）：

| 专家 | `invest_native_prompt_603605.SH_<expert>.txt` SHA-256 | `invest_prompt_603605.SH_<expert>.txt` SHA-256 |
|---|---|---|
| financial-auditor | `d1fb140e2524df752ee17663a0bda9a273b079637fe10830943fd1459e354d46` | `67c6caa1b3943b369f0a442e44ab03f98a932b827e66fe23cd5ffc8a76791f7e` |
| value-valuator | `800217cb8ae7f0c6e4985667bcd82abc6f5b0c50f49baa62b73550f219cd2925` | `81e441d95d3b6940b48bb7b336843920b080d14f7cd09c0df2cd0f2909b906db` |
| moat-analyst | `1d97aefab9adcfcf53537601109a075c969da0ec5f46b6d4a6d85e86a0b69fbd` | `4c6635c6d7c0030e22e23aeb6d1eadeb6d9de29bc4d51cabcc25fbce9ad0cd42` |
| cognitive-controller | `df61c0a52bdd359eb5c58af13ccbcd83d54dc6ae24efa2a4dbe34b7fb960c849` | `0364861d98fedca331de82deca42a155286212d521bb48952e832127dfc0438f` |
| macro-cyclist | `f52b0069c1758bc20daaa2cb01b7a3130090a536eb9a81ad9b196ee30b7b7296` | `3c4f362e831d06890e3a3ff5c5e784b35b996d8e6931104cfca4d51f7d5f9991` |
| growth-assessor | `a2f60aa938c16195028117bbfcd01e5a3de82e453c57151e365754825280d250` | `f1e7eeb5976cf9d128ab04327a2f03b714ab0c4e051d9fbb3cc91c95104650b8` |
| management-auditor | `a87f1533e0dcc3e298b51defc79bd224948f7e6f33e79d7c513f9c4424be818d` | `ddb9273f637af4fe9a20be841cfd25edca6bbc5b0f666d6a50c0c0530b5c17d4` |

prompt 一律不改。若修复需要改 prompt，属方案外变更，STOP 回报 PM。

## 4. 写入隔离（内核级强制 + 穷举白名单）

### 4.1 强制机制

整轮修复只有**一个入口**，在沙箱内启动；所有 python 子进程、shell 子壳、子代理落盘都继承同一 profile，不存在"部分步骤在沙箱外跑"的分支：

```bash
env PYTHONDONTWRITEBYTECODE=1 /usr/bin/sandbox-exec -f <repo>/INV-BATCH-08-REPAIR-01.sandbox.sb \
    /bin/bash <repo>/evidence/repair01/run.sh
```

`INV-BATCH-08-REPAIR-01.sandbox.sb` 全文（**规则后写者优先**）：

```scheme
(version 1)
(allow default)
(deny file-write*)
(deny file-write-unlink)
(allow file-write* (subpath "/private/tmp/repair01-scratch"))
(allow file-write*
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_execution_603605.SH.json")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_native_run_603605.SH.json")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_expert_run_603605.SH.json")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_financial-auditor.md")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_financial-auditor.v3.json")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_value-valuator.md")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_value-valuator.v3.json")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_moat-analyst.md")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_moat-analyst.v3.json")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_cognitive-controller.md")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_cognitive-controller.v3.json")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_macro-cyclist.md")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_macro-cyclist.v3.json")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_growth-assessor.md")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_growth-assessor.v3.json")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_management-auditor.md")
  (literal "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/invest_result_603605.SH_management-auditor.v3.json"))
(deny file-write*
  (subpath "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/batches")
  (subpath "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/evidence")
  (subpath "/Users/bazinga/.dsh/bot/workspace/invest/invest-kb")
  (subpath "/Users/bazinga/.dsh/bot/workspace/invest/invest-report-wiki"))
(allow file-write*
  (subpath "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime/batches/603605.SH-20261014-08-repair01"))
```

设计要点：

- **无通配**：结果文件是 14 条精确 `literal`，没有 `regex`，因此不可能写到第 15 个路径。
- **沙箱自身禁止删除**：`(deny file-write-unlink)` 全局生效，沙箱内任何进程（含孙进程）都无法 unlink，包括自己刚建的文件——修复阶段"只增不删"由内核保证，不靠自觉。
- **既有批次不可写**：先 `deny …/batches`（覆盖 `…-08/`），再在最后 `allow …/batches/…-repair01/` 放行新目录；`…-repair01/` 必须由 `run.sh` 在沙箱内 `mkdir -p` 创建，不得预先手工建。
- **仓外零写**：仓库工作树、`evidence/`、`invest-kb`、`invest-report-wiki`、`$HOME` 全部落在 deny 或默认 deny 之下；`PYTHONDONTWRITEBYTECODE=1` 防 `__pycache__`。
- profile 与 `run.sh` 均留档在 `repair01/` 并记哈希；记录里写入本次沙箱 profile 哈希，事后可复算"跑的确实是这份 profile"。

### 4.2 白名单（沙箱允许 = 本任务唯一可写集合）

1. `../invest-skill-runtime/batches/603605.SH-20261014-08-repair01/`（须不存在；存在即 STOP）：`repair-record.json`、`pre-run/`、`checks/`、`repaired/`、`probe/`。
2. `../invest-skill-runtime/` 根下 14 个 **create-only** 结果文件（实测当前存在数 0）：
   `invest_result_603605.SH_<expert>.{md,v3.json}`，`<expert>` ∈ {financial-auditor, value-valuator, moat-analyst, cognitive-controller, macro-cyclist, growth-assessor, management-auditor}。
3. 3 个脚本 journal（见 4.3 例外条款）。
4. `/tmp/repair01-scratch/`（临时目录）。

### 4.3 journal 例外条款（回应阻塞项 1）

journal 现状（执行前必须复算并比对）：

| 文件（`../invest-skill-runtime/`） | 当前 SHA-256 | 当前用途 |
|---|---|---|
| `invest_execution_603605.SH.json` | `f66df889c77d5d8c5358ef673e19d04d552969f4690470899a21058d872046ed` | 执行台账状态机 |
| `invest_native_run_603605.SH.json` | `3cffe140eef3c3db9316b609f89c718d3fd1f0c63c525ea91f75187a4cf3eb2b` | 原生专家事务状态（`phase=experts`、`transaction_id=2e3c97d7…`） |
| `invest_expert_run_603605.SH.json` | `b5f2f0ab96cff9eed8ab265f0b1610a6abcf9503f5e1c0d07518e05c4b3f407f` | 专家运行锁/序号 |

规则：

- 这 3 个文件是**脚本自有状态**，由 `scripts/run_experts.sh`、`scripts/collect_results.py` 以「整文件重写」方式更新。这是**唯一被允许的既有文件写操作**。
- 沙箱无法按进程身份授权，因此改按**内容级可检条件**约束，写后立即断言：
  1. JSON 仍可解析；
  2. `invest_native_run_603605.SH.json` 的 `ts_code`、`batch_id`、`transaction_id`、`phase` 与执行前一致（只允许 `pass`/`retry` 等运行态字段变化）；
  3. 三个文件写后哈希记入 `repair-record.json` 的 `journal_after`；
  4. 任何字段出现冻结集合之外的新增键 → 视为越权改写，STOP。
- `(deny file-write-unlink)` 保证沙箱内不能删除它们；禁止 rename（同属 unlink/create 语义，已被沙箱阻断）。
- **除这 3 个文件外，"禁止改写既有文件"无任何例外**；§4.2 第 1、2 项全部是新建。
- 写前把原件 `cp -p` 到 `repair01/pre-run/`（复制发生在沙箱内，目标在允许 subpath 内）。

### 4.4 写前断言（全部通过才继续）

1. `test ! -e …-repair01`；
2. 14 个结果文件逐个 `test ! -e`；
3. 3 个 journal 哈希与 §4.3 表一致；
4. `batches/603605.SH-20261014-08/` 与 `evidence/` 全树哈希快照（供 AC1/AC6 比对）；
5. 沙箱探针 P1–P4（§7 N3）全部符合预期 —— 不通过则沙箱无效，STOP。

## 5. 执行步骤

1. §3 哈希核对 + §4.4 断言（含 P1–P4）；任一不符 → STOP 并写 `repair-record.json`（exit 2）。
2. `cp -p` 3 个 journal 到 `pre-run/`；写 `repair-record.json`：候选 HEAD、方案 SHA、输入哈希表、`planned` 全部计划路径。
3. 6 位不合格专家按 §2 指示修文本：只改被判中的行/句（措辞、`[calc:]` 形态、`{{C:}}` 公式），不重写整篇、不新增无数据支撑的数字；结论与管理思路不变。
4. 每位：`compile` → `gate_precheck`，日志落 `repair01/checks/`；失败按诊断改一处再跑，**单专家上限 3 轮**，超限 STOP。
5. 7 位（6 修复 + management-auditor 原样）双关通过后，按 create-only 规则 `commit` 写 14 个结果文件；每写一个立即在 `repair-record.json` 的 `created` 追加 `{path, sha256, at}` 并 fsync；逐个校验存在且非空。
6. 停在专家阶段边界：只做一次 `advance` 预检并报告是否需要 repair，不做挑战/裁定/报告装配。

## 6. 验收标准

- **AC1 输入不变性**：§3 全部条目执行时哈希一致；`batches/603605.SH-20261014-08/` 与 `evidence/` 全树哈希与执行前快照逐字节一致。
- **AC2 七位双关通过**：7 位 `compile`/`gate_precheck` 均 exit 0，日志齐备；`management-auditor.md` 提交前后均为 `13e60eab…632f2b5de3`。
- **AC3 修复最小性**：逐专家 diff 只落在被判中的行；无新增未溯源数字、无假设清单外结论。
- **AC4 产物完整性**：14 个文件 create-only 创建、非空、`compile` 重放与提交物哈希一致。
- **AC5 门禁未被削弱**：N1–N3 全部符合预期。
- **AC6 现场保全**：原 6 份失败件、`…-08/`、`evidence/native-experts-20261025/` 哈希不变；`repair-record.json` 完整记录写集与轮次。
- **AC7 增量白名单**：比对 `../invest-skill-runtime/` 执行前后的目录清单（含隐藏文件），新增条目必须**恰好**是 `batches/603605.SH-20261014-08-repair01/` 子树 + 14 个结果文件；多出任何一条即为 FAIL。同时 `batches/…-08/` 与 `evidence/` 全树哈希逐字节一致。
- **AC8 profile 可复算**：`repair-record.json` 记录的 `sandbox_profile_sha256` 与 `repair01/` 内存档 profile 哈希一致；PM 已于 2026-10-28 16:0x 用本方案 profile 原文实测：可被 `sandbox-exec` 正常加载、对 `…-08/batch.json` 零字节 `O_WRONLY` 打开返回 `Operation not permitted` 且内容哈希不变、沙箱内 `rm` 该文件被拒。

## 7. 负控

- **N1 门禁可复现失败**：用原 `value-valuator.md`（`0e8d53a4…`）重跑 `gate_precheck`，必须仍 FAIL 且至少含 L35/L83 中一处 —— 证明门禁未因本次修复被放宽。
- **N2 calc 形态互斥**：按 §2 表 A/B/C 各跑一次，必须 A=0、B=1、C=1。
- **N3 写入隔离强制生效（内核级，零副作用探针）**：整轮在 §4.1 沙箱内运行，同沙箱内执行 6 个探针。**任何探针都不创建、不修改、不删除被保护区域的任何内容**，因此没有"事后清理"动作，与"停止、不清理现场"无冲突：

  | 探针 | 动作 | 期望 | 若不符合 |
  |---|---|---|---|
  | P1（允许侧） | 在 `repair01/probe/` 新建 `p1` 写入 `ok` | 成功 | 沙箱过严 → STOP，保留现场 |
  | P2（既有批次） | 对 **已存在** 的 `batches/603605.SH-20261014-08/batch.json` 做 `os.open(O_WRONLY)`，**一个字节都不写**，随即 close | `PermissionError/EPERM` | 打开成功 → close、记 `sandbox_ineffective`、复算该文件哈希仍与 §3 一致（证明未写）→ STOP |
  | P3（仓库） | 对已存在的 `<repo>/data/expert_checklist.json` 同样零字节打开 | `EPERM` | 同上 |
  | P4（工作区外） | 对已存在的 `$HOME/.zshrc` 同样零字节打开 | `EPERM` | 同上 |
  | P5（孙进程继承） | `run.sh` 内再起 `bash -c` 子进程做 P2 同动作 | `EPERM` | 成功 → 记 `sandbox_not_inherited` → STOP |
  | P6（禁止删除） | 沙箱内 `rm repair01/probe/p1`（自己刚建的文件） | `EPERM` | 成功 → 记 `unlink_not_blocked` → STOP |

  说明：负向探针对**已存在文件**做零字节 `O_WRONLY` 打开——沙箱有效时得到 `EPERM`；即使沙箱失效，也**不会写入任何字节、不会新建文件、不会改变 mtime**，无需清理，因此不构成破坏性操作。PM 已于 2026-10-28 16:0x 在本机实测该探针语义（`Operation not permitted`，文件内容与 mtime 未变）及 `deny file-write-unlink`（连自己新建的文件也删不掉）。
- **N4 重入幂等**：再次执行 §4.4 断言，`repair01/` 已存在 → 必须 STOP 而非覆盖。
- **N5 无越权取数**：全程无 Tushare/sage/网络调用，`invest_data_603605.SH.json` 哈希不变。
- **N6 journal 外零改写**：`batches/…-08/` 与 `evidence/` 全树哈希在修复前后完全一致（与 AC1 同源、独立复算一次）。

## 8. 回滚（单写者窗口 + fd 校验，只允许两种动作）

停止（立即 exit，不重试、不清理现场）：§3 任一哈希不符；§4.4 任一断言失败；P2–P6 任一不符合预期；单专家 3 轮未过；`created` 记录写入失败；出现白名单外写入需求；§8.2 单写者窗口被破坏。

### 8.1 判定表

| 对象 | 条件 | 动作 |
|---|---|---|
| 14 个结果文件 | 存在，且 `lstat` 的 `st_dev/st_ino/st_size/st_mtime_ns` 与 `created` 登记一致，且以只读 fd 读出的 sha256 == 登记值 | 用该 fd 所在路径 unlink，随后断言 `not lexists`，记 `deleted` |
| 14 个结果文件 | 存在，但上述任一项不符（被替换/被改写） | **不删**，记 `rollback_conflict`，STOP 上报 |
| 14 个结果文件 | 不存在 | 记 `already_absent`，继续 |
| `created` 段缺失/损坏 | — | **不删任何东西**，保留现场，STOP 上报 |
| 3 个 journal | 当前哈希 == `journal_after` 登记值（说明这段时间无第三方改动） | `cp -p pre-run/<name> <name>`（**唯一允许的既有文件覆盖**），随后断言哈希 == `pre-run` 副本哈希 |
| 3 个 journal | 当前哈希 ≠ `journal_after`（第三方已改动） | **不恢复**，记 `journal_modified_by_third_party`，STOP 上报 |
| 3 个 journal | `pre-run` 副本缺失或哈希不符 | **不恢复**，记 `journal_restore_blocked`，STOP 上报 |

回滚本身在沙箱**外**执行（沙箱全局禁 unlink，回滚需要删除），因此必须由 §8.2 的单写者窗口保护。

### 8.2 单写者窗口（并发安全）

- 修复开始前，PM 在群内声明窗口：`[起, 止]` 内除 owner 外任何 Bot 不得对 `../invest-skill-runtime/` 执行写命令；窗口写入 `repair-record.json` 的 `window` 段。
- 回滚前重新校验：3 个 journal 当前哈希必须等于 `journal_after`，且 `batches/…-08/` 与 `evidence/` 全树哈希等于执行前快照——任一不符即视为窗口被破坏，**不执行任何删除/恢复**，STOP 上报。
- 删除动作先用只读 fd `fstat` 校验身份（dev/ino/size/mtime_ns + 内容哈希），再按路径 unlink；校验与删除之间仍有极小的 TOCTOU 窗口，靠"单写者窗口 + 删除后 `lexists` 断言 + 删除动作逐条入 `rollback` 日志"控制。若删除后发现同路径又被创建，立即 STOP 并上报（不改写、不重删）。

其它约束：不删除、不改写任何执行前已存在的文件（journal 恢复是唯一例外）；`repair01/` 与全部日志作为证据保留，不清理；回滚后重跑 AC1/AC6 快照比对。

## 9. 执行与 Provider 边界

- 专家产出由**本会话原生子代理**（`subagent`）按已冻结 prompt 生成，只返回文本；子代理无 shell、无写权限，由 owner 统一落盘，落盘本身受 §4.1 沙箱约束。
- 不启动 codex / claude / dsh 等外部 CLI，不覆盖 provider/model，不调用外部模型或付费服务，不联网取数。
- 不读取 `.env`，不使用任何凭据。
- 不改变任何 TASK 的 READY_FOR_CODE；不解除 `prepare` STOP；不解除 RUN-02/V5 的 STOP。

## 10. 交付物

- `batches/603605.SH-20261014-08-repair01/repair-record.json`（输入哈希、轮次、`planned`/`created`、探针结果）
- `repair01/checks/*.log`、`repair01/probe/*`（探针结果）、`repair01.sandbox.sb` 与 `run.sh`（含哈希）
- 14 个结果文件
- 修复报告：逐专家「判词 → 改了什么 → 为什么不算放宽门禁」，附 N1–N6 与 AC1–AC6 证据路径
