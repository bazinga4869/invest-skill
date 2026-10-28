# INV-DES-04 — Hermes cron 旧路径与静默失败设计

- **TASK-ID：** INV-DES-04
- **状态：** PENDING / BLOCKED（未开始；不得计为 in_progress）
- **Owner：** invest PM（待依赖解除后正式 claim）
- **依赖：** INV-DES-03 runtime-root 合同与入口路径策略先验收，避免两项同时改变运行根契约。
- **下一责任人：** invest PM 在 INV-DES-03 关闭/拆出已授权下游后，再决定 claim 或拆成实现叶任务。
- **正式记录：** 本文件 `/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/INV-DES-04.md`。

## 目标
只处理 Hermes cron 相关的过期绝对路径、默认日志目录、env 文件缺失/命令失败时的可观察性，避免脚本静默失败或把日志写到 skill 仓库。该任务不承担 runtime resolver 的设计与修改。

## 范围
- `scripts/cron_hermes_daily.sh`、`scripts/cron_hermes_push.sh` 的 `SKILL_DIR`、`INVEST_SKILL_HOME`、`INVEST_LOG_DIR`、目录/日志写入与错误传播。
- `scripts/hermes_push_prompt.txt`、`scripts/cron_prompt.txt`、`README.md` 与其中活动使用的旧 `/home/bazinga/...` 路径。
- `scripts/prepare_prompts.py` prompt 正文中的 `/home/bazinga/invest-sage` 路径。改动会改变 prompt bytes/合同哈希，必须使批次身份可追踪；不在本任务启动新批次。
- `references/bug-log-2026-08-17.md` 等历史记录先分类；已明确为历史事实的路径不自动改写。

## 非目标 / 权限边界
- 不改真实 crontab、宿主机 cron 配置、外部仓库、真实 runtime 数据或数据库。
- 不触发 Hermes/外部 Provider、网络、凭证或真实推送；不发布。
- 不重定义 `INVEST_SKILL_HOME` / `INVEST_RUNTIME_DIR` 优先级；若依赖 runtime-root 改动必须等待 INV-DES-03 并建立显式依赖。
- 不修改量化项目、知识库/专家面板、F3/F4 或任何投资准出阈值。

## 交付物与 AC
1. 逐文件逐行列出活动旧路径、日志目录、source env 逻辑、`set -e`/错误传播；区分活动入口、prompt 内容、文档指引与历史日志，不遗漏/误改历史记录。
2. 设计有可观察的启动失败语义：允许的 env/config 路径被校验；缺少 env/config、目录不可写、旧路径不存在、命令失败等情形须明确非零退出或按明确策略跳过，并输出可诊断错误；禁止静默继续并报告成功。
3. shell wrapper 的 DB/log/report/runtime 路径必须按 INV-DES-03 最终约定解析；任何 failure path 在首个写操作前 fail-closed；日志和状态写入不能落入 SKILL_ROOT 或未授权路径。
4. prompt 正文不含过期机器绝对路径；如需引用 Sage/Wiki，应使用可移植的环境/项目配置描述。prompt 改动逐字节纳入 contract/batch hash，要求停止旧活动批次并在之后新批次中重新绑定；本任务本身不启动批次。
5. 编写隔离 shell 测试设计：仅使用临时 fixture、mock Hermes/外部命令、测试不存在/只读目录、环境变量冲突/空值；断言失败退出码、日志可观察性、无生产路径写入/外部调用。不得在本设计阶段运行脚本或测试。
6. 更新相应用户文档；静态检索证明活动入口不再引用失效路径，历史文档保留标注。提供依赖、回滚（revert commit）、候选 SHA 与独立 QA 同 SHA 验收要求。

## 验证与回滚
设计阶段仅只读文件审阅、grep/行号核对。实现阶段验证命令需在隔离目录运行 stubbed shell tests，并检查所有 output paths 与退出码；禁止真实 cron/Hermes/Provider。回滚仅 revert 对应的独立候选提交，不回滚/覆盖其他 dirty 状态。

## 当前线索（未验收）
wiki_manager 在群内只读报告：`cron_hermes_daily.sh:7` / `cron_hermes_push.sh:6` 是旧 `/home/bazinga/invest-skill`；`/home` 是 root-owned symlink、当前用户不可写，`/home/bazinga` 不存在；`$HOME/.config/invest-skill.env` 缺失，故 source 块跳过。两脚本均无 `set -e`，`LOG_DIR` 默认指旧 `SKILL_DIR/logs`，其 `mkdir`、重定向与 push 脚本 `cd` 会失败后继续，后续 prompt 读取为空。此为当前主机路径/env状态检查，不是实际运行脚本或跨机器动态复现；不存在可作为 0755/0644 的实际日志文件证据，故不计入 INV-DES-03 AC4 mode 分母。另发现 `prepare_prompts.py:1154`、`cron_prompt.txt:97-98`、`hermes_push_prompt.txt`、`README.md` 的 `/home/bazinga/invest-sage` / `/home/bazinga/invest-skill` 旧路径。PM 已把此独立缺陷登记 INV-DES-04（pending，blocked_by INV-DES-03）；不在本任务修复或运行。
