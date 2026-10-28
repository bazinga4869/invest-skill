# INV-DES-03 08:19补充记录

此文件补充 `INV-DES-03.md` v3.77 的状态段，避免对既有不可变历史段做拼接改写。

- **Owner / 状态：** investPM；主任务 `IN_PROGRESS / BLOCKED`，不是 `READY_FOR_CODE`。本轮巡检：群内C138已报告，未见新主矩阵ACK/外部交付；共享任务板为空，相关成员idle。完整矩阵ETA未知，08:44仅为检查点。
- **核验对象：** `scripts/corpus_ready.py`、其 `daily_analysis.sh` 调用，以及 `shared/report_wiki.py::listing_aware_years`。
- **源码证据：** `daily_analysis.sh:97-103`在数据同步后调用 `corpus_ready.py`。`corpus_ready.py:27-28,78-82`调用 `listing_aware_years()` 后调用 `corpus_ready()`；`:34-64`启动 report-wiki `status` 子进程，cwd为 `report_wiki_repo`，timeout 90s，依据 JSON/退出状态返回门禁结果。代码调用口称只读，但外部CLI实际副作用和timeout后子进程残留没有独立证据。
- **DB边界：** `shared/report_wiki.py:91-105`读取 `INVEST_DB_PATH` 或 `configured_path("db_file", ...)`，用裸 `sqlite3.connect` 查询 `stocks.list_date`，捕获异常后回退默认年数。缺失DB时SQLite可能创建空DB/sidecar再查询失败；这是源码推断、未复现。DB root可与operation root不同；sidecar mode/owner、用途allowlist和拒绝/零副作用行为均未验证。
- **未核范围：** 全量生产调用者/读写删去重分母、SQLite sidecar实测、report-wiki CLI写集及孤儿进程、逐写点mode/owner、allowlist、越界拒绝零写入、TOCTOU与故障恢复。全量ETA未知。
- **禁止事项/证据边界：** 未运行代码、脚本、SQLite或外部CLI；未读运行时数据或工作区外文件。未将上述静态推断描述为已复现动态行为。
- **下一责任人/动作：** @investPM（owner本人）继续逐点核未分类生产调用者/写点；下个检查点约08:49报告新证据与剩余范围。