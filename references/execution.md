# 执行、隔离与恢复

仅在运行分析、处理并发冲突或排查失败时读取。

## Host-native 隔离模型

认知任务由当前主 agent 的宿主原生子代理能力执行。调用原生 delegate/subagent 时省略
provider/model 覆盖，使子代理继承主 agent 的模型路由、认证、配额和会话谱系。不得从
DSH 主会话另启 Codex/Claude CLI，也不得从 Codex/Claude 主会话另启其他产品。

`scripts/native_agent_tasks.py begin <phase> <code>` 在任何子代理调用前完成任务书、批次、
运行锁和重试门禁，并输出 `jobs[]`。每个子代理只读 `prompt_path`，把完整文档写入
`staged_output_path`；主 agent 不得在 `jobs[].instruction` 外追加语义指令，随后逐项以 `commit ... --child-id <host-child-id>` 绑定真实宿主委派回执，最后 `advance` 运行机器校验。计划同时记录 prompt/instruction/staging hash、bytes 和估算 token；超限或含未解析占位符时在委派前失败。专家唯一重试中的后续修复轮由 `advance` 返回 `CONTINUE + jobs[]`，不会重跑已通过专家。

宿主没有原生子代理能力时直接停止；绝不自动选择系统 PATH 上恰好存在的模型 CLI。
`run_experts.sh`、`run_challenges.sh`、`run_cross_reviews.sh` 仅是显式兼容层，必须由用户明确
设置 `INVEST_ALLOW_EXTERNAL_AGENT=1` 并指定 `--agent` 才可能运行。

这是模型上下文和工具能力隔离，不宣称容器或虚拟机级 OS 隔离。子代理不得读取兄弟
任务、使用网络/shell 或外部知识；staging、原子替换与校验由受信任脚本管理。

## 同股票互斥

`runtime_guard.py` 使用 `${INVEST_RUNTIME_DIR:-${INVEST_SKILL_HOME:-/tmp}}/invest_expert_run_<code>.json` 串行化 prepare、experts、challenges、cross-reviews 和 finalize。租约包含随机 token；正常脚本只释放自己取得的租约。

查看状态：

```bash
python3 scripts/runtime_guard.py status <code>
```

只有确认对应进程已经退出且租约确属遗留时，才人工释放：

```bash
python3 scripts/runtime_guard.py release-run <code> <owner>
```

不要在仍有工作进程存活时释放或删除门禁文件。

prepare 把 `SKILL.md`、执行/修复/组装/验证脚本、准出规则和 report-wiki 引擎源码树纳入批次控制哈希；begin、commit、advance、resume 与 finalize 都必须重算。任一文件变化即停止旧批次，修复代码后必须重新 prepare，禁止在活动批次上热补丁续跑。

## 唯一重试

experts、challenges、cross-reviews 各自每批只允许一次重试。`claim-retry` 只预留，`begin-retry` 才原子消费实际机会；脚本直接调用 `begin-retry`。repair prompt 必须同时包含官方原始任务书、最新失败结果、完整 diagnostics 和机器冻结的首次独立 decision（即使首次结果因格式未发布）；格式/trace 修复不得改变 score/verdict/direction/veto。失败列表收集本身异常时必须返回错误，不能把空输出解释为全部通过。

旧版只有 `used_at` 的标记，只能在确认重试从未实际启动后迁移：

```bash
python3 scripts/runtime_guard.py recover-retry <code> <phase>
```

## 运行目录与元数据

需要自定义临时位置时，在整个管线开始前设置一个绝对路径：

```bash
export INVEST_RUNTIME_DIR=/absolute/private/runtime
```

不要设置为 `/`，也不要在阶段之间改变。未显式设置时继承 `INVEST_SKILL_HOME`。
每个认知阶段会更新 `invest_execution_<code>.json`；host-native 模式记录
`backend=host-native`、`model=inherit-parent`、批次、并发、修复轮数、child id 与全部状态事件，不伪造或猜测具体 provider。finalize 必须写入 `GATES PASS` 并把执行元数据、adjudication/verification/publication receipts 纳入发布链。

## 失败留证与清理

认知阶段校验失败时默认保留 prompt、result、日志和重试标记，并原子写入 `invest_failure_<code>_<phase>.json`；专家阶段文件包含完整 structured diagnostics。发生 retry 时，begin/commit/rejected/continue/terminal 各时点的 plan、官方任务书、repair prompt、diagnostics、raw/hash 与 child receipt 都快照进 native archive，并在 finalize 打包为 `invest_retry_evidence_<code>.json`。唯一重试失败后不得自动清理，否则无法区分内容错误和门禁误报。

完成复盘并确认终止后，显式清理单只股票：

```bash
python3 scripts/cleanup_intermediates.py <code>
```

清理只覆盖该代码的可再生运行文件、阶段日志和草稿，不删除正式报告及历史 artifact。
