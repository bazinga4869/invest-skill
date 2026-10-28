# INV-DES-03 — 2026-10-18 20:49 巡检 / cleanup lease 交叉核验

仅记录只读巡检和 cleanup 候选/guard 的代码交叉检查，不执行清理，不声称发生误删。

- **巡检：**采样`2026-10-18T20:49:29+08:00`；schedule occurrence `2026-10-18T12:49:29.700Z`换算`20:49:29.700+08:00`约差0.7秒，仅识别本轮提醒，不解C145–C161历史映射。排程每1800秒，task board为空、roster仅lead运行，无其他主矩阵ACK/交付；owner仍investPM。主任务IN_PROGRESS/BLOCKED、非READY_FOR_CODE，AC2/3/4/6/9未闭，候选SHA未冻结、无同SHA QA、完整矩阵ETA未知。
- **更正：cleanup候选与lease guard交叉核：**复核`cleanup_intermediates.py:23-35`后，精确列表第31项确为`invest_expert_run_{ts_code}.json`；`runtime_guard.run_state_path()`同名（`runtime_guard.py:30-32`），且两模块默认root都源自同一导入期`shared.runtime.RUNTIME_ROOT`（`runtime_guard.py:17-19`、cleanup `:18,82`）。故cleanup默认runtime候选精确包含该租约文件。cleanup函数没有读取/检查该租约，候选遍历会按常规unlink/删除（cleanup `:93-110`）。另有`.invest_execution_{code}.lock`候选是另一文件，不应与run-state混为一谈。
- **互斥语义及边界：**`claim_run()`读取run state；若state存在即拒绝，然后以`os.open(O_CREAT|O_EXCL)`原子创建该state（`runtime_guard.py:109-128,67-78`）。`assert_idle()`也依赖此state作活动阶段判定（`:145-153`）。所以若活动租约文件被cleanup删除，之后的claim可能看不到已有状态并成功；这是由代码可推导的条件性破坏互斥机制，不是已发生的互斥失效/并发写事实。触发仍需cleanup与活动run在同一代码、同一默认runtime root和时间窗口重叠；上游caller是否保证idle尚未穷尽，另有删除与读取之间的TOCTOU需设计处理。
- **retry state交叉项：**`runtime_guard.retry_state_path()`命名`invest_retry_<code>_<phase>_<batch_id>.json`（`:34-36`），与cleanup glob `invest_retry_<code>_*.json`（cleanup `:54`）匹配。run-state为精确候选；retry state为pattern候选。两者均应纳入AC9活动状态防删除/终态清理矩阵。仍无实际state被删或静默互斥失效证据。
- **已核/未核：**已核cleanup精确run-state候选与runtime_guard run_state_path同名、默认root来源相同、cleanup本身无lease check、retry state glob命中、guard基于run-state存在性拒绝第二claim；未核所有cleanup callers是否均在上游做idle/终态检查、调用者root/实参与allowlist、活动/终态正负隔离语义、race下先检查后删、receipt与run关联、partial deletion恢复。AC2/3/6/9仍未闭。
- **执行边界：**未运行cleanup、runtime_guard、测试、CLI、脚本、SQLite、Provider/批次；未读取runtime/真实数据/报告或工作区外资源。
- **下一责任人/动作：**@investPM（本人owner）继续逐call-site追cleanup前置idle/终态校验和run_id/receipt关联；全量ETA未知。动态删除/lease故障验证需另行授权与独立QA。
