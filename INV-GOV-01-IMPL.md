# INV-GOV-01-IMPL — 后续 Skill 工程实现叶任务（设计草案）

- **父任务：** INV-GOV-01（`DESIGN ACCEPTED`，仅治理设计合同静态验收）
- **状态：** `DESIGNING / BLOCKED`；本叶未复核、未 `READY_FOR_CODE`、无开发者 ACK，不得开始代码修改。
- **Owner：** investPM（仅任务设计/状态治理，不担任开发者或独立 QA）
- **候选范围建议：** 仅基于已批准的 INV-DES-03 最终设计与 AC，实现 runtime-root 一致性、调用点 root 注入、用途 allowlist 与 owner-only permission/fail-closed 保护。实现边界须由最终矩阵逐文件列明；不把无人值守治理框架实现与 runtime-root 修复合并。
- **路径范围：** 当前工作区内经本合同冻结的具体文件白名单。初步候选包括 `shared/runtime.py`、`shared/project_config.py`、`shared/data_tools.py`、`shared/report_wiki.py`、`shared/sage_wiki.py` 与 `scripts/` 内 runtime consumer/writer；最终文件集须等 INV-DES-03 全量矩阵确认后冻结。不得改工作区外文件、知识库/专家面板、宿主调度、发布配置或真实运行时数据。
- **非目标：** 不调用 Provider/网络/外部CLI、不连接生产 SQLite、不运行真实批次、不发布；不包含测试执行授权。实现合同不得以本草案作为范围批准。
- **依赖：** INV-DES-03 设计验收、全量矩阵与用途 allowlist 完成；本任务范围/AC/故障用例/命令/预算/回滚经独立只读设计复核；明确且适格的开发者和独立工程 QA 分别在群内 ACK；PM 再显式标记 `READY_FOR_CODE`。

## 待定验收标准（必须在 READY_FOR_REVIEW 之前按最终 INV-DES-03 逐项冻结）

1. 每个生产 reader/writer/deleter/SQLite caller 对应唯一清单行：入口、调用者、root来源、import snapshot与operation root、目标子树、创建/覆盖/删除语义、mode来源与目标权限。
2. 所有 writer/guard 使用同一合同指定的operation root；无隐式 `/tmp` 回退；非法/冲突/越界/过宽既存目标在首个副作用前拒绝。
3. 敏感新目录/文件权限、owner检查、原子替换、SQLite DB与sidecar策略须逐点落实；不放宽现有安全门禁。
4. 修改仅落在冻结文件白名单；任何未计划文件改动触发暂停、归因及PM范围重审。
5. 代码改动有变更清单、风险/回滚说明与可复核提交 SHA；设计或范围变更回退设计，不可边实现边改同一任务合同。

## 必需负例/故障场景与证据

- 非法/缺失/冲突环境变量、相对/绝对越界目标、目录穿越、symlink及过宽既有对象应拒绝；具体可执行命令和零写入断言由最终合同确定。
- stage/replace、SQLite迁移/事务、外部调用边界、清理/发布中断故障必须分别定义；不可把本任务的实现者自测认作独立 QA。
- 本草案没有任何动态验证命令获准。进入 READY_FOR_CODE 前，验证命令、合成输入、mock I/O、临时root、预算/时间限额、停止条件、证据留存与回滚动作须全部定值。

## 责任链 / BLOCKED 原因

- 当前 roster 中仅 `投研复核`具只读合同审查职能；其角色说明不支持将其视为代码开发者或工程 QA。`投研流程`是运行时编排，`wiki_manager`负责投资知识内容；均非适格默认工程 owner。
- **开发者：** 未指定/未 ACK。`quant开发`隶属 log-quant-buddy，不能跨项目自动委派；不得将其直接路由为 invest-skill 开发者。
- **独立工程 QA：** 未指定/未 ACK；投研复核的静态设计复核不能代替工程 QA。
- 依赖 INV-DES-03 仍 BLOCKED，范围分母未冻结；因此当前不可形成确定的路径白名单、可执行 AC 和充分的命令/回滚合同。
- **解除 BLOCKED 的下一步：** @investPM 完成 INV-DES-03 设计闭环与矩阵冻结；随后在本群对本叶合同逐条细化并请求 `@投研复核` 只读合同复核（先 ACK，未 ACK 标 `WAIT_ACK`）；若团队仍无适格开发者/独立 QA，向用户提出最小角色补充建议，未经同意不创建成员。各角色实际 ACK 后再更新正式任务状态。

## 禁止事项与当前交接

- 不得把父任务 `DESIGN ACCEPTED` 误作本叶验收；不得设 `READY_FOR_CODE`、冻结候选 SHA、运行代码/测试/脚本/SQLite/CLI/Provider/批次或触碰工作区外内容。
- 当前唯一执行者为 investPM（草案设计）。下一责任人：@investPM 先闭合 INV-DES-03 和角色适配/指派路径；完整 ETA 未知，不伪报。
