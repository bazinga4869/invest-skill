# INV-DES-02 — F3/F4 候选冻结与验收设计

- **TASK-ID：** INV-DES-02
- **状态：** PENDING / BLOCKED；不是 READY_FOR_CODE
- **Owner：** 当前未分配（PM 已从虚假 `in_progress` 释放 task board 条目）
- **下一责任人：** invest PM 先完成候选基线归因/冻结设计，再决定是否认领或派给已确认的开发者/工程 QA
- **证据基线：** 本地 task board task-1 revision 4 已释放为 pending；工作区曾记录 79 项 modified/untracked。F3 与部分测试文件 hash 与历史验证摘要不符；既有 `125 passed` / selftest 日志不能证明匹配当前候选 SHA。

## 范围
F3：prompt 中面板/契约确定性注入及示意 `{{F001}}` 与真实 unresolved template 的区分。
F4：初始结果为空/不可解析时 repair 的允许边界、状态闭环及 fail-closed 反例。
候选源码、测试、合同/批次指纹和验证记录之间的可复现绑定。

## 非目标与权限边界
- 不改 F5、门禁阈值、结论严格度、其他标的或模式。
- 不改知识库、专家面板、配置、真实数据；不运行 Provider/凭证、批次、prepare/begin/advance/finalize，不发布。
- F3/F4 代码任务须在设计复核后另建叶任务并经 PM 明确 READY_FOR_CODE；工程 QA 对同一不可变 SHA 独立复核。

## 依赖与阻塞
依赖 INV-BASE-01 已完成只读基线，但结论为证据不足/不可判 PASS。
阻塞：`prepare_prompts.py` 同一 hunk 混有既有 dirty 内容；历史 F3/F4 测试日志不能绑定当前源码快照；目前没有 invest-skill 专属工程 QA/开发者角色被分配；项目工作树 dirty/untracked 尚未逐项归因。

## 验收标准
1. 清点 F3/F4 源码/测试的 git 状态与 SHA，区分授权修复与旧 dirty/untracked；对无法分离的 hunk 给出可审计处理方法。
2. F3 正例：sage context 有/无两种情况下，必须的面板/方法论契约按设计进入 prompt。负例：真实 unresolved template 被拒绝；契约正文的示意 `{{F001}}` 不被误报。
3. F4 正例：空/不可解析首产出可按受控流程 repair 并留证。负例：完全缺首产出、声明 decision 但无法复算、decision 漂移均 fail-closed；不放宽安全门禁。
4. 提供正/负/故障测试矩阵、确切命令/退出码/证据归档；开发验证与独立工程 QA 使用同一不可变候选 SHA。
5. 批次 task ID、数据 batch_id、prompt_contract_hash/wiki_hash、状态与证据 manifest 同源绑定；任何不一致或 abort staging 均拒绝复用。
6. 定义风险、失败处置、回滚与独立 QA/开发依赖；真实数据/Provider/凭证/发布继续独立授权。

## 验证与回滚
当前仅允许只读：`git status --short --branch`、相关 `git diff`、逐文件 SHA 与已有证据核对；本任务不运行 pytest 或批次。候选冻结前保留工作树，不 reset/清理/覆盖；无法绑定日志/源树时维持 BLOCKED，不推定 PASS。

## 下一步
invest PM 完成 INV-DES-03 中 runtime-root 全量静态矩阵后，重新评估候选冻结方案及责任人。PM 给该动作的下一状态更新 ETA：2026-10-16 23:15 Asia/Shanghai；此 ETA 不是代码实现或任务完成承诺。