# INV-DES-03 09:19巡检补充

本文件补充 `INV-DES-03.md` v3.80。只记录本轮只读源码核验，不代表实现/动态验证或 QA。

- **状态与 owner：** 主任务 `IN_PROGRESS / BLOCKED`，非 `READY_FOR_CODE`；AC2/3/4/6/9未闭。无新主矩阵ACK/交付，任务板为空，相关成员idle；实际owner investPM。全量ETA未知，候选SHA未冻结。
- **核验范围：** `shared/sage_wiki.py:81-94,108-135,143-155,211-242`。
- **query subprocess：** `query()`构造`sage-wiki query ... --scope local --project <repo> --format json`，cwd为配置的sage repo，timeout按config/default 300秒。`_runtime_env()`会解析 `Path.home()/.config/invest-sage/runtime.env`，并将环境变量未覆盖的键加入子进程env。只读了本仓源码，未读取文件内容、未启动CLI；具体凭据、外连、实际读写集、timeout后残留未知。
- **cache：** cache root相对路径以`project_config.runtime_root()`为基，resolve后检查在runtime root内。writer mkdir parents mode 0700，使用排他临时文件、flush/fsync、replace；临时文件没有显式mode。root在project_config中可能来自INVEST_SKILL_HOME/config/skill fallback；containment resolve与后续创建/写入间的symlink/TOCTOU、现存目录/文件mode与owner均未实测。
- **已核：** query命令/cwd/env来源/timeout；cache路径约束与stage-replace写入源码语义。
- **未核：** 子进程实际写集/网络调用/孤儿行为；cache有效mode/owner、symlink/TOCTOU/allowlist拒绝零写入；所有生产consumer/writer/deleter完整去重矩阵与各点root一致性。全量ETA未知。
- **禁止事项/证据边界：** 未运行sage-wiki CLI、测试、Provider/网络；未读取HOME配置、runtime或工作区外文件。
- **下一责任人/动作：** @investPM（主owner本人）继续核剩余调用者/写点，下一检查点约09:49报告新证据/范围；不是全量完成ETA。