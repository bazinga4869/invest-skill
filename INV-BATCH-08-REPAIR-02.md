# INV-BATCH-08-REPAIR-02 · 副本内修复 + 正式根内核禁写（L3 选项 A 加固版 rev2）

- TASK-ID：`INV-BATCH-08-REPAIR-02`（rev1 `ee73cba5…` 被复核 FAIL，本版为修订）
- 目标：把 `603605.SH-20261014-08` 的 6 位不合格专家在**副本**内修到 `compile` + 诊断门禁全 0；正式运行时根由**内核规则**禁止任何写入
- owner：投研流程｜独立复核：投研复核｜接受：investPM｜裁定：chief
- 依据：用户 2026-10-28 m00922「继续」；`INV-BATCH-08-REPAIR-01-L3.md`；群公告 v1.6 第 8 条
- 状态：`REV2_FOR_REVIEW`

## 0. rev2 对 rev1 三条 FAIL 的处置

| rev1 阻塞项 | rev2 处置 |
|---|---|
| ① `INVEST_SKILL_HOME` 只影响 `runtime_root()`，`configured_path` 仍接受绝对路径，未证明所有执行器/子进程/链接都不指向正式根；事后哈希不能阻止首次写入 | **改为内核禁写**：单条 `(deny file-write* (subpath 正式根))`，不依赖代码是否尊重环境变量。写入尝试被内核拒绝在发生之前，不是事后发现。已实测 6 项（含符号链接穿透、rename、删除），见 §3.2 |
| ② 逐文件内容哈希不覆盖目录/符号链接/元数据，也发现不了"写后恢复原值" | 哈希改为**清单**：`find` 记录 `type`(f/l/d) + 符号链接目标 + size + mtime + inode；并且"写后恢复"在本方案下不可能发生——写入被内核拒绝，而非事后比对 |
| ③ AC3/AC6 只规定诊断结果，未证明等同权威 `gate_precheck`；回滚直接删副本无审批 | 门禁事实已核实：本机**不存在** `gate_precheck.py`、无 `INVEST_PANEL_TOOLS`；批次自己的门禁日志首行即写"诊断代码来自 skill 本体"，`batch.json` 的 `precommit_gate_summary` 也由该代码产出。AC3/AC6 明确绑定 `scripts/collect_results.py: build_expert_diagnostics` + `shared/expert_result_v3.py compile`（与批次同源同版，哈希钉死）。回滚改为**不删除**，副本保留并标记放弃 |

## 1. 事实核对（本机实测）

- `find ~ -name gate_precheck.py` 无结果；环境中无 `INVEST_PANEL_TOOLS`。CLAUDE.md 提到的外部面板门禁在本机未安装。
- 批次 `checks/<expert>.gate-precheck.log` 首行：`门禁预检：macro-cyclist @ macro-cyclist.md（数据包 603605.SH，诊断代码来自 skill 本体）`。
- 因此"权威门禁"在本机的唯一实现就是仓库内 `build_expert_diagnostics`；它也是产生 `BLOCKED_PRECOMMIT_GATE` 的同一段代码。

## 2. 输入绑定

| 项 | 值 |
|---|---|
| 正式根 | `/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime`（12 MB，125 文件；执行时复算） |
| 副本 | `/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime-repair02`（必须不存在；存在即 STOP） |
| 数据包 | `invest_data_603605.SH.json` = `4d6125afcb26e877849ae2c2bf7c1b880bdc77400f21f3b876ae11558ead3565` |
| 年报 | `invest_annual_603605.SH.txt` = `2b63e709639cab2c962bbcd4abf1385b51511380b262ece566c0983cef9bda83` |
| 批次台账 | `batches/603605.SH-20261014-08/batch.json` = `538230eb3978f96d135305869f4f011c45e09f86960a5b8c0cc8a34d48acb9eb` |
| 原 5 份失败件 | financial `b0a61399…84b158c2`、value `0e8d53a4…88c0f91b6b`、moat `f4b3048b…881136bcc`、cognitive `41b21b21…27ba03c884e`、macro `efdcf647…7c7a5401077` |
| management（不得改） | `13e60eab9ce49507f89861d6d4a7b47998c05e7671563faada0509632f2b5de3` |
| growth 失败现场 | `evidence/native-experts-20261025/staging-next/…growth-assessor.07b158ec….next` = `d3eecdad…f9091807` |
| 门禁代码 | `scripts/collect_results.py` `3786d5f7…a29b01e`（`build_expert_diagnostics` 在 :346；`DIAGNOSTIC_CATEGORIES` 在 :62-70）、`scripts/verify_report.py` `6cae520e…ab2e0cef`、`shared/checklist_verify.py` `3ba605bc…c0c79157`、`shared/expert_result_v3.py` `d2df148e…38e61b15` |

## 3. 隔离机制

### 3.1 双保险

1. **路径重定向**：`export INVEST_SKILL_HOME=<副本>`，让走 `runtime_root()` 的代码落到副本（`shared/project_config.py:32-44`）。
2. **内核禁写**（真正的隔离）：整轮在

```bash
/usr/bin/sandbox-exec -f <repo>/evidence/repair02/formal-root-readonly.sb /bin/bash <repo>/evidence/repair02/run.sh
```

下运行，profile 只有三条规则：

```scheme
(version 1)
(allow default)
(deny file-write* (subpath "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime"))
(deny file-write-unlink (subpath "/Users/bazinga/.dsh/bot/workspace/invest/invest-skill-runtime"))
```

不设白名单、不列 permit 路径、不依赖任何脚本行为：**只要目标是正式根，任何进程（含孙进程、含通过符号链接穿透）都写不进去**；副本与 `evidence/repair02/` 在 deny 之外，正常可写。

### 3.2 机制实测（2026-10-28，用 `/tmp` 同构目录，未触碰正式根）

| # | 动作 | 结果 |
|---|---|---|
| 1 | 直接 `touch` 正式根内新文件 | `Operation not permitted`，未创建 |
| 2 | 写副本内文件 | 允许 |
| 3 | 经副本内**符号链接**写正式根文件 | `Operation not permitted`，目标文件内容不变（仍为 `orig`） |
| 4 | 经**符号链接目录**在正式根内建文件 | `Operation not permitted`，未创建 |
| 5 | 沙箱内 `mv`/删除正式根文件 | `Operation not permitted`，文件仍在 |
| 6 | 写副本与 `/tmp` 其它路径 | 允许 |

### 3.3 彩排（不触碰正式根）

正式运行前，用**同一 profile 结构**把 deny 目标换成一次性诱饵目录 `/tmp/repair02-decoy/`（内含正式根同构小树），在沙箱内跑一次"写正式根同构路径"的彩排：必须得到 `EPERM`。彩排通过只证明 profile 形状有效；正式运行时 deny 目标是正式根本身，无需再向正式根发起任何写入尝试。

## 4. 写集

允许写：`<副本>/`（全部运行时写入）、`<repo>/evidence/repair02/`（新建证据目录：`formal-tree-before.txt`、`formal-tree-after.txt`、`formal-root-readonly.sb`、`run.sh`、`logs/`、`diff/`、`report.md`、`record.json`）、本方案与 `INV-DES-03-TASKS.md`（PM 维护）。
禁止：正式根任何写入（内核强制）、`../invest-kb`、`../invest-report-wiki`、仓库既有文件；不调用 `prepare`；不做挑战/裁定/装配/发布。

## 5. 执行步骤

1. 生成 `formal-tree-before.txt`：`find 正式根 -mindepth 1 -print0 | sort -z` 后对每条记录 `type`(f/l/d)、`size`、`mtime`、`inode`、符号链接目标、以及文件内容的 `sha256`（目录记 `-`）。
2. `cp -a` 正式根 → 副本；对副本做同格式清单，与 before 除 inode 外逐条一致才继续。
3. 彩排（§3.3）通过后，在沙箱内启动 `run.sh`：`export INVEST_SKILL_HOME=<副本>`；复算 §2 关键哈希。
4. 6 位专家按 `INV-BATCH-08-REPAIR-01.md` rev4 §2 判词修文本（只改被判行；`[calc:]` 用实测形态 A；`{{C:}}` 只用 `current/previous/a/b/xN`）。每改一处：`expert_result_v3.py compile` → `build_expert_diagnostics`，七类全 0 才算过；单专家上限 3 轮，超限 STOP。
5. 7 位（6 修 + management 原样）在副本内生成 14 个 `invest_result_603605.SH_<expert>.{md,v3.json}`。
6. 生成 `formal-tree-after.txt`，与 before 比对。
7. 产出逐专家 diff 与报告。

## 6. 验收

- **AC1 正式根零变化**：`formal-tree-before.txt` 与 `formal-tree-after.txt` 逐行相同（含 d/l/f 类型、符号链接目标、size、mtime、inode、内容 sha256）。
- **AC2 禁写机制生效**：彩排记录 + `run.sh` 全程无 `EPERM` 之外的异常；`record.json` 记录 profile 哈希。
- **AC3 6 位双关通过**：副本内 `expert_result_v3.py compile` exit 0 且 `build_expert_diagnostics` 七类全 0（`invalid_sources`/`invalid_calculations`/`invalid_checklist_evidence`/`out_of_domain_checklist_evidence`/`qualitative_contradictions`/`unsourced_claims`/`untraced_numbers`）。
- **AC4 management-auditor 未改**：副本内 md 哈希 == `13e60eab…2b5de3`。
- **AC5 修复最小性**：逐专家 diff 只落在被判行；无新增未溯源数字。
- **AC6 门禁未削弱**：副本内**原始** `value-valuator.md` 另存后重跑诊断，必须仍 FAIL 且命中 L35/L83（与批次日志同源同版）。
- **AC7 交付边界**：14 个结果文件只在副本；正式根不存在任何 `invest_result_603605.SH_*`。
- **AC8 副本完整性**：副本内 6 份被修文件之外的既有文件哈希与 before 一致。

## 7. 停止条件与回滚

停止：副本已存在；副本与正式根除 inode 外不一致；彩排未获 `EPERM`；关键哈希不符；单专家 3 轮未过；出现白名单外写入需求。

回滚：**不删除任何文件**。副本 `../invest-skill-runtime-repair02/` 保留并标记 `abandoned`（写入 `record.json`）；因为正式根由内核禁止写入且 AC1 证明零变化，无需恢复任何状态。副本的删除属破坏性操作，须用户单独批准，本方案不做。

## 8. 落回（不在本任务内）

`INV-BATCH-08-PROMOTE-01` 另行立项：只写 14 个新建文件 + 3 个 journal 更新，需用户/chief 决定并单独走复核。本任务只交副本产物、diff 与报告。
