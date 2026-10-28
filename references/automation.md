# 自动化运维契约

仅在运行或排查 cron、daily、Hermes 推送时读取。

## 职责边界

- **调度归属**：本仓库不持有 crontab 条目、不自行注册定时任务。定时调度由调用方
  （本机为 invest-harness）负责：`~/invest-harness/scripts/cron/cron_*.sh` wrapper
  注入环境（source `~/.config/invest-skill.env` + 兜底 `INVEST_SKILL_HOME`）后调用
  本仓库执行器。排查定时问题时先看宿主 crontab 与 wrapper 日志。
- **运行时根**：DB、日志、报告、`auto_state.json` 等持久产物写入调用方 `INVEST_SKILL_HOME`
  指定的目录（本机：`~/invest-harness/.invest-skill-runtime/`），不回写 skill 仓库。
  `cron_trigger.sh` / `daily_analysis.sh` 会 source `~/.config/invest-skill.env`
  获取 `INVEST_SKILL_HOME`；手动运行前请先 `export INVEST_SKILL_HOME=...`，
  或依赖 `config.yaml paths.runtime_root`（绝对路径）。
- **运行时根防护**：入口脚本（cron_trigger/daily_analysis/native_agent_tasks/
  prepare_prompts）在 `INVEST_SKILL_HOME` 未设置时 **exit 2 拒绝运行**
  （除非 `INVEST_ALLOW_SKILL_RUNTIME=1` 显式逃逸），防止运行时产物写回 skill 仓库。
- **失败告警**：`scripts/alert.sh` 写 `logs/alert.jsonl` 并推送 Telegram/Discord（hermes send，
  无 LLM）；`cron_trigger.sh` 所有失败分支接入；`scripts/watchdog.sh` 工作日 08:00 健康检查
  （最近 30h 无成功报告且无告警记录时推送，幂等）。
- `daily_analysis.sh`：纯 shell 只选股、同步和生成 prompt；它无法创建“当前主 agent 的原生子代理”，因此在认知阶段安全停止，绝不猜测外部模型 CLI。
- `cron_trigger.sh`：确定性地选股/同步/准备；**DSH headless 主会话**负责用自身原生子代理执行 `native_agent_tasks.py` 的专家、质询和盲审任务，再完成裁决、自评审和 finalize。子代理不传 provider/model 覆盖。外层设置 `INVEST_DEFER_CLEANUP=1`，收到 `CRON_DONE` 后再次用同批次 JSON 严格核查，PASS 后才更新状态与清理。
- 选股读 SQLite `stocks` 表（排除 688/8xx/ST，按 `auto_state.json` 轮转）；`auto_state.json` 缺失时自动重建默认状态，不再依赖 `data/stock_pool.json`（遗留文件、无生产者）。
- `native_agent_tasks.py`：为当前主 agent 输出 provider/model 均为空的原生子代理计划，管理 staging/commit、互斥锁和唯一重试。所有入口继承同一绝对 `INVEST_RUNTIME_DIR`（未设时继承 `INVEST_SKILL_HOME`）。外部 CLI 三脚本仅为用户显式 opt-in 的兼容层，自动化不得调用。

## 断点与成功判定

断点分两级：数据新鲜且 `collect_results.py --check` 7/7 通过时可从二级质询继续；再满足 `collect_challenges.py` 7/7 时才可直接进入裁判长阶段。专家和质询结果的 `data_date`、`batch_id`、原报告哈希均须与快照一致。准备新批次会清理旧结果，避免同日混批。

cron 成功同时要求：agent exit 0、合法 `CRON_DONE`、正式报告非空、`verify_report.py --strict` PASS、`verify_manifest.py` PASS。任何一项失败均不得更新状态或记录 success。

## 清理

交互式 `--finalize` 在 manifest 归档后自动调用 `cleanup_intermediates.py`。cron 因需要外层独立复核而延后清理，复核成功后调用同一脚本。清理范围包括本代码的数据、report-wiki bundle、年报兼容视图、专家 prompt/result、质询、盲审、重试/互斥标记、staging、draft 和阶段日志；不得删除 report-wiki 公司语料、其他代码的中间文件或历史正式报告。

report-wiki 的 watchlist 同步由 `~/invest-report-wiki/bin/report-wiki sync-watchlist`
独立调度；它只更新财报语料，不自动触发本 skill 的公司分析或发布。

## 语料预热与断点续跑（materialize 首次建库）

**背景**：首次下载和本地解析五年 PDF 仍可能较慢，但 Sage/LLM 编译已从年报证据
准出中移除，不再因付费 API、余额或长摘要任务阻塞 prepare。

**机制**（2026-08-22 起）：

- `scripts/prewarm_corpus.py`：夜间批量预热原件、页级 evidence 和本地 FTS5/BM25。
  相同原件哈希直接复用；`report-wiki sync-watchlist` 单家公司失败不阻塞其他公司。
  宿主应经 `~/invest-harness/scripts/cron/cron_prewarm.sh` 调度（建议 18:00-20:00）。
- `scripts/corpus_ready.py`：`daily_analysis.sh` prepare 前的只读快速门禁。
  只有原件、页级证据和本地搜索索引均 PASS 才放行；Sage 摘要状态不参与该门禁。
- 方法论 `invest-sage` 按七个专家主题独立缓存。fresh cache 避免重复付费查询；live
  402/超时/网络失败时回退通过内容哈希校验且未超过策略期限的 cache，无 cache
  保持 fail-closed 并给出清晰原因。
- 上市年份感知：`prepare_prompts.py` 用 `listing_aware_years()` 按
  `stocks.list_date` 收敛应有年报年度（上市不足 5 年的公司不要求上市前年报）；
  `pick_stocks.py` 排除最近应有年报披露截止（次年 6/30）后才上市、巨潮无档的股票。
- 报告 wiki 侧：巨潮全文 PDF 无年度标题（"年报全文"）时按同日"年度报告摘要"配对
  推断年度（修复宝胜股份类缺年）；另有年度定向关键词重试与 `search_pages` 加大。

活动日志写入 `logs/activity.jsonl`；只有发布门禁通过才使用 `status=success`。草稿生成应记录 `skipped/pending adjudication`，不能计作正式报告成功。
