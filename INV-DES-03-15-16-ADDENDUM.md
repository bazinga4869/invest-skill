# INV-DES-03 — 2026-10-18 15:16 巡检与 AC4 补充

仅登记只读静态复核与验收测试设计要求，不代表动态验证或任务放行。

- **提醒/采样：**系统采样 `2026-10-18T15:16:32+08:00`；本段无法确认绑定到同一轮的 schedule occurrence，故不借最近可见提醒或后续群消息推断。历史 C 编号/时间仍待底层关联证据，不更改。
- **任务/人员：**`list_agents` 仅 lead 运行；群内本轮 reviewer/Chief 的静态核验已收到，未收到全量矩阵交付或动态验证授权。主owner仍investPM；`INV-DES-03`状态继续 IN_PROGRESS/BLOCKED、非 READY_FOR_CODE；AC2/3/4/6/9未闭、候选SHA未冻结、无同SHA QA、全量ETA未知。没有运行测试、脚本、代码或批次。
- **新纳入 AC4 的 import 链证据（仅源码推断）：**`scripts/normalize_challenge.py:19` 导入 `shared.runtime.RUNTIME_ROOT`；`shared/runtime.py:7-10,29` 在模块 import 时执行进程级 `os.umask(0o077)` 并初始化 root。normalize 的输出 `write_text` 位于 `normalize_challenge.py:141`，没有显式 mode。因此在 POSIX 上“新建文件预期0600”是由该进程 import 链的 umask 推导，不是实现显式承诺或stat实测。覆盖已有宽权限文件时，open-for-write截断不会自动收紧既有 mode；这是 AC4需单独覆盖的 fail-closed策略点。
- **测试隔离风险（源码可确认的全局副作用，未运行）：**`tests/test_runtime_contracts.py:10` 导入 `normalize_raw`；模块导入链到 `shared.runtime` 会改变整个 pytest 进程 umask，且没有局部恢复。该全局副作用会污染同进程后续测试/破坏“operation前后umask不变”的测量。新文件mode、既有过宽目标拒绝、operation前后umask不变均应通过隔离子进程测量；当前测试文件头仅见直接import，尚未发现该目标断言。不得在本轮运行。
- **路径/root 分栏补充：**`shared/runtime.py:12-29` 的 runtime root 解析依 env `INVEST_RUNTIME_DIR > INVEST_SKILL_HOME > /tmp`，不读 config.yaml；`normalize_challenge.py` 的输入prompt/original/data沿RUNTIME_ROOT，raw/output是CLI给定路径。`run_challenges.sh:9-11,49-54,71-94`先从调用环境初始化TMP_DIR并claim，之后才从persistent resolver解析root并覆盖变量；`native_agent_tasks.py:861-864`用`sys.executable`传staged/output，子进程继承环境。静态显示路径来源/初始化时序需要核一致性，但无证据证明现行调用实际读写越界。新的正常调用链是否均有父进程注入合法环境、配置仅存在于config时如何行为，仍待逐点确认；不得把未设置环境必然等同为本环境实际落在`/tmp`并写入。
- **归档身份fallback可达性收窄：**Chief/wiki_manager 复核指出 `verify_manifest` 不直接调用身份helper；归档data文件存在且可读后才进入challenge validator，manifest/batch及expert-result前件还有独立检查。故该处fallback更精确是缺字段时可能影响诊断/一致性自足性，现有静态证据不足以说它改变该 consumer 的PASS/FAIL。批量runtime入口的主要缺陷归root解析/传递AC2/AC3；不据该分支另开一个已证实缺陷。
- **下一步：**@investPM（owner本人）继续只读矩阵，特别补全normalizer所有调用者、root/env传递和其他未分类写点；全量ETA未知。隔离动态验证要有权人批准后另派唯一叶TASK与独立QA，当前不执行。
