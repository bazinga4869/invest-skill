# INV-DES-03 — 2026-10-18 14:49 巡检补充

本补充只记本轮巡检及 `normalize_challenge.py` 静态调用链；不构成设计通过、代码授权或动态证据。

- **巡检：**系统采样 `2026-10-18T14:49:29+08:00`；提醒 occurrence `2026-10-18T06:49:29.700Z` 换算为 `14:49:29.700+08:00`，仅支持识别本轮提醒，不重建历史C编号。`schedule_list`显示每1800秒；当前 `team_task_list`为空，`list_agents`仅lead运行，无其他矩阵ACK/交付。主owner仍 investPM。任务保持 `IN_PROGRESS/BLOCKED`、非 `READY_FOR_CODE`；AC2/3/4/6/9未闭、候选SHA未冻结、无同SHA QA、全量ETA未知。
- **新增只读切片：**`scripts/normalize_challenge.py:123-145` CLI从模块级 `RUNTIME_ROOT` 读取challenge prompt、original expert report和data (`:132-138`)，但 raw input/output paths 来自命令行参数 (`:127-128,139-141`)；输出由 `args.output_path.write_text()`写入，函数内未见把该目标 resolve 到RUNTIME_ROOT、对其做allowlist/root containment校验或显式mode设置。本轮仅静态看到这个不对称路径来源；未读取raw文件、未执行normalize、未核shell/调用者如何构造output_path、目标路径是否位于runtime或实际mode/owner。输出参数是潜在 writer boundary，不能仅凭CLI可调用路径判越界。
- `scripts/run_challenges.sh:100-120`将`${TMP_DIR}`下的 staged/normalized/result paths传给 agent/normalize CLI，并在成功后 `mv -f` 归一结果；shell前段先取`INVEST_RUNTIME_DIR`/`INVEST_SKILL_HOME`/`/tmp`并claim-run，后段才解析并覆写运行root (`:9-11,49-54,71-94`)。这些行在合同已有root时序切片里出现过；本轮只将其作为normalize output path调用者语义旁证，不重复计为新切片，也未执行runner或子进程。normalize CLI 若被其他调用者直接传入非授权 output path，目前未逐一盘点。
- **分类：**normalize CLI 为 runtime-source reader + caller-supplied-path writer。导入 `shared.runtime` 会在 import 链设置进程级 umask 077；POSIX 新建文件预期0600属静态推断，未stat；覆盖既有文件不会收紧原mode。若经 `run_challenges.sh` 调用，path构造受脚本当前root时序影响；但调用时具体root、绝对/相对参数行为、父目录创建方及fail-closed约束尚未验证。可能的安全验收需核：所有调用者唯一输出路径、在首次open前同一root/用途allowlist校验、拒绝路径零写入、文件mode/既有目标策略、写/replace中断恢复；动态验证需另行授权。
- **未核：**normalize CLI全部调用者及允许output子树分母；路径解析、symlink/TOCTOU、有效mode/owner、失败写入边界、其余全仓消费者/写删完整清单。未运行代码、测试、shell、CLI、SQLite、Provider或批次，未访问runtime、真实数据或工作区外。
- **下一责任人/动作：**@investPM（本人owner）继续只读核 normalize output调用者及其他未分类写点；全量ETA未知。若需要隔离动态证明，先走相应授权，不越过门禁。
