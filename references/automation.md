# 自动化运维契约

仅在运行或排查 cron、daily、Hermes 推送时读取。

## 职责边界

- `daily_analysis.sh`：选股、同步、生成 prompt、执行专家与二级质询、生成 `.draft.md`；无裁判长时不得定稿。
- `cron_trigger.sh`：确定性地选股/同步/准备；Codex 会话负责专家、二级质询、裁决、自评审和 finalize；外层收到 `CRON_DONE` 后再次用同批次 JSON 运行严格核查，PASS 后才更新 `auto_state.json` 与清理。
- `run_experts.sh --no-prepare`：调用方已准备 prompt 时使用，避免二次取数导致批次漂移。失败最多有界重试一次，仍失败则停止。

## 断点与成功判定

断点分两级：数据新鲜且 `collect_results.py --check` 7/7 通过时可从二级质询继续；再满足 `collect_challenges.py` 7/7 时才可直接进入裁判长阶段。专家和质询结果的 `data_date`、`batch_id`、原报告哈希均须与快照一致。准备新批次会清理旧结果，避免同日混批。

cron 成功同时要求：agent exit 0、合法 `CRON_DONE`、正式报告非空、`verify_report.py --strict` PASS、`verify_manifest.py` PASS。任何一项失败均不得更新状态或记录 success。

## 清理

先确认 manifest 已归档，再清理本次代码对应的数据、年报、专家 prompt/result、质询 prompt/result、三级判定/盲审和 draft。不得删除其他代码的中间文件或历史正式报告。

活动日志写入 `logs/activity.jsonl`；只有发布门禁通过才使用 `status=success`。草稿生成应记录 `skipped/pending adjudication`，不能计作正式报告成功。
