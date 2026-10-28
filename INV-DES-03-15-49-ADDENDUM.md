# INV-DES-03 — 2026-10-18 15:49 巡检补充

本补充只登记巡检及一项静态调用链观察；不代表全量矩阵、动态验证或工程QA完成。

- **时点与任务状态：**系统采样 `2026-10-18T15:49:29+08:00`；当前收到的 schedule occurrence `2026-10-18T07:49:29.700Z`换算为`15:49:29.700+08:00`，相差约0.7秒，足以识别本轮提醒但不能解开C145–C152历史映射。`schedule_list`仍每1800秒；`team_task_list`为空，`list_agents`仅lead运行，无其他矩阵ACK/交付；实际owner为investPM。主任务仍`IN_PROGRESS/BLOCKED`、非`READY_FOR_CODE`，AC2/3/4/6/9未闭、候选SHA未冻结、无同SHA QA，全量ETA未知。
- **本轮静态路径复核及后续 reviewer 更正：**`native_agent_tasks.py:857-899` 挑战分支以 `staged.with_suffix(...'.normalized')` 派生输出路径，用 `sys.executable`、`cwd=SKILL_ROOT` 调用 normalize，并传入 staged/raw 与 normalized/output 路径；成功后父进程才将normalized替换到result，异常时不发布该结果。父子进程沿环境继承，两个模块都导入shared.runtime，但这不能推出父进程最终环境的具体来源。本记录先前“若缺 env 则该 native 链默认 /tmp”的说法不够准确：native入口本身导入 `shared.runtime` 后，若其成功初始化，模块 `RUNTIME_ROOT` 已捕获一次解析结果；父进程若在启动 native runner 前缺env，则其resolver默认 `/tmp` 并创建root，但父子模块不是独立再从 config.yaml 解析。要判断生产是否用config-only root，关键是父进程启动native runner前是否已注入env、或该入口是否另有配置注入，不能用子进程再次独立重解析来表述。当前源码只确认 runtime resolver本身不读config、env缺省候选为`/tmp`，未证实生产入口的最终env。
- **静态限制：**这给出单一已读调用者的argv构造与失败/提交次序；不证明实际环境、root值、路径allowlist或越界写，也不排除人工/其他外部入口。没有运行子进程或读取/写入任何产物。
- **已核/未核：**已核normalize在native caller中的单一调用、argv path构造、父子cwd/继承语义、结果发布时序与异常分支；未核native runner的实际启动者及其最终env注入方式、完整Python/shell/人工调用分母、根allowlist与坏根首写前拒绝、actual/effective mode和owner、既有过宽文件拒绝、symlink/TOCTOU/故障恢复。静态核验不改变AC状态。
- **执行边界：**未运行脚本/测试/CLI/SQLite/Provider/批次，未触碰runtime、真实数据、知识库/专家面板、凭证或工作区外。
- **下一责任人/动作：**@investPM（本人owner）继续只读核native runner启动者/父进程env注入来源及剩余writer；全量ETA未知。任何动态隔离验证仍需相应授权及独立QA，不越过门禁。
