# INV-DES-03 08:45巡检补充

本文件补充 `INV-DES-03.md` v3.79。08:19原状态段存在历史截断，已在合同中标注勿作证据；该时点具体核验材料见 `INV-DES-03-08-19-ADDENDUM.md`。

- **状态/owner：** INV-DES-03 `IN_PROGRESS / BLOCKED`，非 `READY_FOR_CODE`；AC2/3/4/6/9未闭。实际owner为investPM。08:45巡检无新矩阵ACK/外部交付；任务板为空，相关成员idle。候选SHA未冻结，动态验证未批准，全量ETA未知。
- **核验对象：** `daily_analysis.sh:88-103`、`corpus_ready.py:40-82`、`shared/report_wiki.py:91-105`。
- **源码证据：** daily先运行`data_tools.py sync`，成功后写activity success，然后才进入corpus门禁。`corpus_ready.py`先调用`listing_aware_years()`后运行report-wiki `status`子进程。因此仅status命令的意图为只读，不等于完整daily前置门禁零写入。
- **SQLite边界：** `listing_aware_years()`读取`INVEST_DB_PATH`或configured DB root，用裸`sqlite3.connect`查询`stocks.list_date`；异常捕获并回退默认年限。缺失DB可能创建DB/sidecar，是源码推断而非实测。实际DB root、sidecar权限/owner、用途allowlist未验证。
- **外部CLI边界：** status参数为`status --code ... --as-of ... --years ... --format json`，cwd为`report_wiki_repo`且timeout 90秒。CLI实现、外部写集、timeout后孤儿进程均未核。没有访问仓外路径、运行CLI或连接数据库。
- **未核：** 所有生产consumer/reader/writer/deleter的完整去重分母；逐点root、mode/owner和allowlist；拒绝越界零写入、TOCTOU及故障恢复动态证据；外部入口与调用参数。全量ETA未知。
- **下一责任人/动作：** @investPM（本人owner）继续核尚未分类路径，约09:14报告具体证据/剩余范围；该检查点不是全量完成ETA。