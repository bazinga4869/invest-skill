# INV-DES-05 — 统一知识库直连、Sage 退场与外部数据源接入设计

- **TASK-ID：** `INV-DES-05`（设计父任务；下列叶任务各自独立验收）
- **状态：** `DESIGNING / BLOCKED`；本文件是待独立复核的设计草案，不是实现/测试授权，也不是 `READY_FOR_CODE`。
- **Owner：** investPM（设计协调、证据与任务树）；不担任 KB 内容 owner、开发者或独立工程 QA。
- **目标 / 范围决策：** 新知识链路直接只读接入 wiki_manager 维护的统一 KB；不把统一 KB 改造成旧 Sage 接口，也不再把 Sage 当新批次知识来源。设计覆盖 Sage 查询/缓存/哈希/校验契约的分阶段退场、旧批次兼容，以及经审查可从活动路径中清理的废弃方案/实现，避免残留误导未来维护。历史批次验证所需的原始证据必须保留或有可复核替代，不能为“清洁”而静默损失。并行评估是否能通过明确授权的只读接口复用 dataPM 数据。只有来源身份、数据契约、权限、批次哈希和失败行为明确后才考虑实现。

## 范围与非目标

- **范围：** 只读盘点本仓配置/代码、wiki_manager 已提供的 KB 只读接口与目录事实、Sage 相关调用/批次字段/历史验证依赖、dataPM 后续提供的接口/schema 合同，以及公开官方产品文档。产出统一 KB 直连方案、Sage 退场/旧批次兼容方案和数据库复用候选架构，含正负/故障验收矩阵、依赖及待授权项。
- **非目标：** 不修改 `config.yaml`、Skill 源码、KB/专家面板、数据库 schema 或 dataPM 数据；不运行 KB CLI/MCP、Sage 查询、SQLite/ClickHouse、测试、批次或 Provider；不读取凭据、环境变量值、真实数据库或 KB 正文；不改变既有 fail-closed 门禁。
- **受限边界：** 统一 KB 与 dataPM 数据库均位于本 Skill 工作区之外。任何实际读取、连接或写入都必须由任务叶明确规范化路径/接口、限额、授权、停止条件和留证；本设计本身不授权外部访问。

## 当前证据与阻塞

1. 当前 [config.yaml](config.yaml#L25-L42) 将 `wiki_dependencies.repo_path` 配为 `../invest-kb`；wiki_manager 只读核实该目录按当前仓库位置解析后不存在。统一库实际目录是 `/Users/bazinga/.dsh/bot/workspace/kb`，当前可见状态为 P0 骨架/方案 v0.1，`INDEX.md` 生成于 2026-10-28，未见正式语义版本；现有条目均为 `draft`，`invest-kb` 在统一库 catalog 中是 K2 外部资产，不是统一库本体。
2. [project_config.py](shared/project_config.py#L70-L87) 显示 `sage_wiki_repo()` 使用配置路径；`wiki_expert_root()` 在面板根缺失时可能回退到 `../invest-wiki`，实际回退目录是否存在未核。[sage_wiki.py](shared/sage_wiki.py#L308-L364) 的旧策略允许新鲜 cache 优先，live 查询失败后最多回退 90 天；当前配置关闭无缓存 builtin fallback。统一 KB 缺失时，live query 会失败；只有通过校验且未超过 max-stale 的旧缓存可能继续提供上下文。以上是代码/配置事实，不是运行态验证。为落实用户最新决策，新设计不得把这条 Sage cache/fallback 继续当成 KB 直连路径。
3. Sage 不是单个 prompt 查询点：`prepare_prompts.py` 导入 `collect_expert_contexts` 并写入 `meta.sage_wiki_hash/status`；`shared/batch_contract.py` 将 `sage_wiki_hash` 列为 batch component；`validate_prompt_bundle.py`、`verify_report.py`、`assemble_report.py` 将 `shared/sage_wiki.py` 纳入冻结合同；定稿的 `knowledge_refs` 解析还读取 `WIKI_ROOT` 与 `SAGE_WIKI_ROOT`。因此退场必须逐项设计新 KB provenance/hash、准入/验证、报告引用和旧 manifest/replay 兼容，不能只删 `sage-wiki` 调用。当前只做了具名代码切片/检索定位，尚非全仓穷尽或实现结论。
4. wiki_manager 提供的候选适配方式是统一库现有 `kbctl search/get` JSON 接口或只读 MCP；只接受 `kind=entry`、`status=verified` 条目，校验 owner、更新时间、来源引用并要求 `kb verify` 通过；逐批记录条目 ID、来源/正文 SHA，并用单独的 `kb_snapshot_hash` 绑定。此为直接 KB 方案建议，不是已执行结果；新版本不再依赖 Sage 作为知识提供者。
5. 当前 [config.yaml](config.yaml#L6-L16) 配置 Skill 自有 SQLite `data/invest_skill.db`，数据源是 Tushare 主源、AKShare 备用。[data_tools.py](shared/data_tools.py#L53-L105) 的 `get_db()` 使用可写 `sqlite3.connect()` 并执行可能写 schema 的 `_migrate_schema()`；直接将 `INVEST_DB_PATH` 指向别人的生产数据库不安全。
6. lead 提供了文档级只读盘点并给出来源路径/SHA：[`DATA_CONTRACT_v0.5.md`](/Users/bazinga/.dsh/bot/workspace/datapm/DATA_CONTRACT_v0.5.md)（`87ec962898804559ac716301e9039ee1d69e7e7eacd46b74908141af8fe6dfdc`）与 [`research_views.sql`](/Users/bazinga/.dsh/bot/workspace/datapm/cloud/server/research_views.sql)（`9c19dad33e628f364a5d6f783c1fc63d2d5f686728edbff20036a41bf8413fb3`）。以下均为 **lead 报告的文档记录**，investPM 未直接读取上述外部文件，也未做运行态核验：
   - **服务/工具：** 2026-10-26 本机切换记录称服务地址为 `127.0.0.1:18080/mcp`、`tools/list` 返回 7 项（`market.get_bars/snapshot`、`ref.get_instruments/adj_factors/st_history`、`pit.get_fundamentals`、`meta.get_dataset_status`）；契约 §6 另列 `market.get_daily`、`pit.get_events` 等不一致清单。因此当前服务可用性及工具注册均为 `UNKNOWN`，不能择一当作当前事实。参考：[切换记录](/Users/bazinga/.dsh/bot/workspace/datapm/cloud/LOCAL_CUTOVER_VERIFICATION_20261026.md#L9-L18)、[历史 7 工具记录](/Users/bazinga/.dsh/bot/workspace/datapm/cloud/incident/ISOLATION_ACCEPTANCE_20261021.md#L67)、[契约工具表](/Users/bazinga/.dsh/bot/workspace/datapm/DATA_CONTRACT_v0.5.md#L1075-L1090)。
   - **ACL/部署：** 10-26 记录称 `mcp_reader` 仅有 `SELECT research.*`，直读 `market.*` / `holdout.*` 被拒，服务绑定回环地址；这是历史记录，不证明当前服务或 ACL。契约为 `DRAFT`，`deployed_unaccepted` 是历史状态，不能推出现已部署并验收。参考：[历史 ACL 记录](/Users/bazinga/.dsh/bot/workspace/datapm/cloud/LOCAL_CUTOVER_VERIFICATION_20261026.md#L39-L50)、[契约部署状态](/Users/bazinga/.dsh/bot/workspace/datapm/DATA_CONTRACT_v0.5.md#L1037-L1060)。
   - **许可/刷新：** 未找到逐数据集许可核验表；契约记载第三方数据仅内部私有使用、不外发/转售，部分分钟级权限或涨跌停来源仍 `pending_review`，不等于已取得逐数据集授权。当前刷新 SLA 为 `UNKNOWN`；文档中的 10 分钟是 coverage 缓存 TTL，不是数据刷新频率；1 分钟采集链曾暂停/退役，不能当作现行可用计划。参考：[许可范围](/Users/bazinga/.dsh/bot/workspace/datapm/DATA_CONTRACT_v0.5.md#L792-L828)、[待审许可项](/Users/bazinga/.dsh/bot/workspace/datapm/DATA_CONTRACT_v0.5.md#L78-L95)、[缓存 TTL](/Users/bazinga/.dsh/bot/workspace/datapm/DATA_CONTRACT_v0.5.md#L973-L979)、[采集链状态](/Users/bazinga/.dsh/bot/workspace/datapm/DATA_CONTRACT_v0.5.md#L758-L775)。
   - **字段/单位：** lead 报告的源端口径包括：`research.bars` 以 `instrument_id/trade_date` 标识，OHLC 为分、volume 为股、日线 amount 为千元；`daily_basic.close` 为元、市值万元、股数万股；PIT 财务金额元，使用 `knowledge_time <= as_of`，修订以 `revision_no` 追加；`ts` 为 Asia/Shanghai，而 `knowledge_time` 时区未找到明文；复权使用 bar 日期对应的 `hfq` 因子，qfq 已从接口移除。参考：[单位/复权/PIT](/Users/bazinga/.dsh/bot/workspace/datapm/DATA_CONTRACT_v0.5.md#L268-L292)、[时间语义](/Users/bazinga/.dsh/bot/workspace/datapm/DATA_CONTRACT_v0.5.md#L652-L662)、[视图字段](/Users/bazinga/.dsh/bot/workspace/datapm/cloud/server/research_views.sql#L8-L33)。
   - **文档 provenance：** lead 报告的 [部署说明](/Users/bazinga/.dsh/bot/workspace/datapm/DEPLOYMENT_LOCAL_20261026.md#L6-L40) SHA `0968525444049641c241dda810f654fcd274c384b4d794aa24a8c7a048a755a3`；[切换核验](/Users/bazinga/.dsh/bot/workspace/datapm/cloud/LOCAL_CUTOVER_VERIFICATION_20261026.md#L9-L50) SHA `2507a55a7a38293587963ff265df82324a347b0cf9b2287809fd234ed3169955`；[隔离验收](/Users/bazinga/.dsh/bot/workspace/datapm/cloud/incident/ISOLATION_ACCEPTANCE_20261021.md#L67) SHA `c80aa06e683fbe66f5350d20c1492fd715341d4a4576301dde90848091ca3835`；[数据字典](/Users/bazinga/.dsh/bot/workspace/datapm/daily/DATA_DICTIONARY.md#L1-L7) SHA `af3997cb2b0e67d6cccde17b6399862543e5e385a8fb4a44bf79503b99dd4992`。以上外部文件路径、内容与 SHA 均为 lead 报告；investPM 未直接打开或独立核验。
   - **结论边界：** 当前服务/工具注册、ACL、逐数据集许可和刷新 SLA 仍 `UNKNOWN`。DataPM 文档足以形成适配设计输入，不足以批准接库、改配置或声称部署已接受。运行态工具/ACL 需 DataPM 与部署方 dsh运维提供新的只读核验记录；许可与刷新 SLA 需 DataPM 补权威材料。公开 ClickHouse `readonly=1` 与 BACKUP/临时表例外只是通用资料，不证明实例 ACL；SQLite `mode=ro` 也不会令当前 `get_db()` 变成安全只读连接。

## Sage 退场静态依赖映射（2026-10-29 14:27 +08）

本表依据当前 Skill 工作区只读检索后逐段读取源码与当前规范文档形成；它是**有界静态映射**，不是运行态验证，也不以 grep 命中数作为覆盖分母。历史台账、旧批次证据与 bug-log 中的 Sage 字样不逐条改写；它们是历史资料，不代表当前调用。未读任何外部 KB 正文、缓存、环境文件或运行时数据，未运行 CLI、测试、批次或 Provider。

| 分类 | 当前证据位置 | 已证实的源码关系 / 退场约束 |
|---|---|---|
| 新批次调用及 Prompt | `scripts/prepare_prompts.py:38,55-57,1033-1064,1152-1167,1456-1475,1531-1538` | 模块导入 Sage adapter；`prepare` 调 `collect_expert_contexts()`，写 `meta.sage_wiki_hash` 与 `meta.sage_wiki`，并把每专家的返回文本/路径注入 Prompt。旧模板把 Sage 与面板契约分段描述；新的 prompt 契约须明确 KB 内容是只读不可信参考、面板/结果契约仍为独立控制面。 |
| Sage CLI、cache 与 source-path 元数据 | `shared/sage_wiki.py:67-135,143-161,211-269,282-415` | 当前解析 `SAGE_WIKI_CLI`/PATH/用户目录，读取可选 `~/.config/invest-sage/runtime.env` 作为子进程环境，调用配置 repo 下的 `sage-wiki query`；另有运行时 cache、query article path 到外部 repo 的 `_source_paths()`、fresh/live/stale-cache/builtin/fail 分支。代码控制流不证明实际 CLI、环境、cache、外部文件或网络曾被访问。新路径不得读旧 cache、起 Sage 子进程或静默接受 builtin。 |
| 配置与专家面板根 | `config.yaml:25-42`; `shared/project_config.py:58-87` | `repo_path` 同时被 `wiki_repo()` / `sage_wiki_repo()` 使用；`wiki_expert_root()` 在配置面板根缺失时可能回退 `../invest-wiki`。面板/方法论契约与通用知识条目不是同一个接口：不得用新 `kb_snapshot_hash` 覆盖现有专家面板 `wiki_hash`，也不得假设统一 KB 现有 P0 内容已提供专家面板。新知识来源必须固定 KB 根且失败关闭；面板根/回退如要迁移，另作有界设计与授权。 |
| 批次哈希字段与算法 | `shared/batch_contract.py:9-36,115-120,132-180` | `sage_wiki_hash` 当前属于 `HASH_FIELDS`、`COMPONENT_FIELDS`，并由 `compute_batch_metadata()` 从 `meta` 读入后参与 `batch_id`；`canonical_data_hash()` 会剔除这些 hash 字段。新设计须按合同版本分别计算旧 Sage component 和新 `kb_snapshot_hash` component；不可原地删字段后让旧批次 ID 悄然改算。保留旧字段用于历史验证，不得为新版本伪造空 Sage 结果或覆盖旧语义。 |
| 冻结控制面及历史回放 | `shared/contracts.py:10-50,61-94`; `scripts/verify_manifest.py:77-84,239-257` | 当前 0.8.0 控制面及 V07 replay 文件集均包含 `shared/sage_wiki.py`；manifest 验证按 `contract_version` 识别 0.5.1/0.6.0/0.7.0/当前版本。现有 `required_replay_files()` 只对 0.7.0 特判，其余版本复用当前 `REQUIRED_REPLAY_FILES`。因此新版本若从当前清单删除 Sage 文件，必须先固定并按版本分派旧 0.8.0 replay 文件集；不能用新清单重解释旧 manifest。新版本号目前仅建议在后续合同设计中递增，不在此确认具体版本号。 |
| Prompt/报告批次验证器 | `scripts/validate_prompt_bundle.py:25-33`; `scripts/verify_report.py:26-30,1089-1095` | 两处都把 `shared/sage_wiki.py` 作为冻结合同文件；报告验证再把 Sage 文件路径交给 `validate_batch_metadata()` 重算身份。退场需让旧批次按旧归档合同验证、新批次按 KB 合同验证；不能只删 import 或文件清单条目。 |
| 报告归档及最终知识引用 | `scripts/assemble_report.py:53-73,665-729,1071-1096` | 裁决的 `knowledge_refs` 当前校验路径与 SHA，并在 `WIKI_ROOT`/`SAGE_WIKI_ROOT` 下寻找；归档时按当前控制面生成 `contract_bundle.json` 并写当前 `contract_version`。新引用须绑定条目 ID、owner、更新时间、来源引用/哈希及正文哈希，并从本批次归档快照重验，不能在最终门禁时改查可变的 live KB。旧格式/旧根解析只在对应历史版本分支保留。 |
| 结果知识路径校验 | `scripts/collect_results.py:35-53,165-191,250-257,382,607` | 当前校验同时遍历 `WIKI_REPO`、面板根和 `LEGACY_WIKI_REPO`，并为无目录的旧标题做同名页面兼容搜索。新版本必须使用独立 KB provenance/snapshot 验证，不允许由这些旧根或同名搜索兜底；历史结果则按版本兼容，不能统一替换全局 root 后破坏旧校验。 |
| 执行 provenance | `scripts/execution_provenance.py:91-100` | 执行记录直接投影 `meta.sage_wiki`。新版本应记录 KB snapshot/provenance/status；旧事件保留原始 Sage 状态供审计，不清空或改写。 |
| 测试契约 | `tests/test_sage_wiki_contract.py:17-117`; `tests/test_runtime_contracts.py:268-307` | 前者覆盖 live、fresh/stale cache、402、缓存篡改和 fail-closed 行为；后者断言 Sage 上下文有/无时面板契约仍注入并处理占位符。未来测试应覆盖新 KB verified/draft/哈希漂移/接口故障、无旧源回退、版本分派及旧批次重放；本阶段未运行测试。 |
| 当前规范文档 / 非调用线索 | `SKILL.md:17-19,81-90,171-186`; `references/data-contract.md:46-53`; `CLAUDE.md:69-76,139-140,190` | 当前规范仍描述 Sage source/cache/`knowledge_refs` 行为，后续实现时需按新版本修订；CLAUDE.md 同时含标明为“移植前历史描述”的旧段，修订时必须保留历史边界。`scripts/prewarm_corpus.py:66-69` 的孤儿 `sage-wiki compile` 是 report-wiki materialize 注释，不能直接等同专家知识 query 退场；若要处理需另证其 CLI 归属。shell 中的 Sage PATH 文字是注释，不是已证实的 query 调用。 |

## KB snapshot schema 与确定性 hash 合同

新批次的 KB provenance 采用 `invest-skill.kb-snapshot.v1`；以下是设计候选合同，不表示 KB 已接入或已有 verified 条目。

```json
{
  "schema_version": "invest-skill.kb-snapshot.v1",
  "source_id": "unified-kb",
  "queries": [{"expert_id": "...", "query": "..."}],
  "entries": [{
    "expert_id": "...", "ordinal": 0, "entry_id": "...",
    "kind": "entry", "status": "verified", "owner": "...",
    "updated_at": "YYYY-MM-DDTHH:MM:SSZ",
    "sources": [{
      "ref": "...", "sha256": "<64 lowercase hex>",
      "source_bytes_base64": "<base64 of exact source bytes>"
    }],
    "body": "<exact KB body string>",
    "body_sha256": "<64 lowercase hex>"
  }],
  "contexts": [{"expert_id": "...", "text": "<exact UTF-8 context injected>"}]
}
```

- 接口返回按 strict UTF-8 解码；不做 trim、换行或 Unicode 规范化。`body_sha256` 对 body 原样 UTF-8 bytes 计算。V1 每个 source 必须归档原始 source bytes 的 base64；final verifier 严格解码后重算 `sha256`，并核对 `ref`、`entry_id` 与 KB 条目中的来源关系。缺原文字节、解码失败、hash 不符或关系不匹配均以 `SOURCE_PROOF_MISSING/INVALID` fail-closed；不可仅保存来源引用和裸 SHA。若来源许可/大小不允许归档原文，当前链路阻塞，不用签名/可信态推断替代；未来如由 KB owner 提供可验证权威签名，应作为新 snapshot schema 与 trust-root 合同单独设计/复核。最终 verifier 只读归档 snapshot，不访问 live KB。
- V1 的 `sources` 只接受原文归档，不含 `attestation` 字段。此选择让最终门禁能重算 source SHA，而不依赖 live KB 或未提供的签名密钥；若存储许可/体积不允许归档原文，当前接入必须停在 `BLOCKED_EXTERNAL_INPUT`。经 KB owner 授权的签名证明可作为未来独立 schema 版本设计，不属于当前 V1。
- 每个 expert 恰有一条 query；queries、contexts 按 `expert_id` Unicode code-point 升序排列。entries 按 `(expert_id, ordinal)` 排列；ordinal 从 0 连续递增。sources 按 `(ref, sha256)` 排序且去重。batch 内 `entry_id` 重复、未知 owner、非 `kind=entry`、非 `status=verified`、无来源、非法时间/hash 或重复 JSON key 均拒绝。contexts 保存真正注入 Prompt 的完整字符串；Prompt 的最终字节另由 `prompt_bundle_hash` 绑定。
- canonical payload bytes 唯一规则：解析对象不得含重复 key、浮点数或 NaN；对象键以 Unicode code point 升序排序，数组顺序按上述规则；按 `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")` 序列化，不追加换行。snapshot hash 为 `SHA256(b"invest-skill:kb_snapshot:v1\0" + canonical_payload_bytes)` 的 64 位小写十六进制。hash 字段不放入被哈希 payload；归档 envelope 单独存 payload 与 `kb_snapshot_hash`。该值进入版本化 `meta.kb_snapshot_hash` 和新批次身份。
- Prompt 准备归档完整 snapshot；最终 verifier 只从本批次 snapshot 重算，不读 live KB。KB root 缺失、无合格 entries、来源/body hash 错、查询超时/格式异常、snapshot 缺失或重算不一致均 fail-closed；不回退 Sage、缓存、`invest-wiki` 或 builtin。

**可复现 hash 向量**（source bytes=`source`；body bytes 与 context UTF-8=`A`）：

- `SHA256(b"source") = 41cf6794ba4200b839c53531555f0f3998df4cbb01a4d5cb0b94e3ca5e23947d`
- `SHA256(b"A") = 559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd`
- canonical payload bytes（无换行）：

```text
{"contexts":[{"expert_id":"e1","text":"A"}],"entries":[{"body":"A","body_sha256":"559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd","entry_id":"kb:test","expert_id":"e1","kind":"entry","ordinal":0,"owner":"qa","sources":[{"ref":"fixture/source.txt","sha256":"41cf6794ba4200b839c53531555f0f3998df4cbb01a4d5cb0b94e3ca5e23947d","source_bytes_base64":"c291cmNl"}],"status":"verified","updated_at":"2026-01-01T00:00:00Z"}],"queries":[{"expert_id":"e1","query":"q"}],"schema_version":"invest-skill.kb-snapshot.v1","source_id":"unified-kb"}
```

- Expected `kb_snapshot_hash = af7df84cbfd990cce8f2c8bd44fac24b51064b257a618b4a1852f89f93709a7d`. Recompute with `printf '%s\0%s' 'invest-skill:kb_snapshot:v1' '<canonical payload bytes>' | shasum -a 256`. Changing any body/provenance/context/ordering byte must change the digest; draft/duplicate-ID/missing-source negatives reject before digest acceptance. This vector was calculated over a literal string only; no product code or test ran.

## Version dispatch、batch ID 与 manifest 验收矩阵

所有分支须显式按 `contract_version` 选择算法和 replay set；未知版本直接拒绝。绝不以“当前 `REQUIRED_REPLAY_FILES`”代替历史版本真值。

| 版本 | batch-ID 组件（顺序固定） | replay / manifest 规则 | 合成 fixture 预期 |
|---|---|---|---|
| `0.5.1` | `data_hash, annual_hash, wiki_hash, prompt_contract_hash, prompt_bundle_hash`（5项） | legacy 分支；检查归档 manifest/file hash、旧合同快照与 5 项 ID。bundle/输入缺失=`LEGACY_UNVERIFIABLE`/非零，不能静默 PASS。 | 完整一致 fixture PASS；删任一已登记文件、改 batch_id、bundle hash 错均 FAIL。 |
| `0.6.0` | 同上 5 项 | 当前代码对 `.6.0` 会把“当前 replay set”去掉 `shared/report_wiki.py`，不是冻结的 V0.6 清单。新设计必须有 literal `V06_REPLAY_FILES` 与一个可复核 `.6.0` fixture；未从历史合同证据确定前，状态为 `LEGACY_UNVERIFIABLE`，禁止声称兼容通过或删除相关历史验证资产。 | 现有输入可复算 5 项 ID；replay set / 正式 PASS fixture 是阻塞项，不能用猜测填充。 |
| `0.7.0` | `data_hash, annual_hash, wiki_hash, prompt_contract_hash, prompt_bundle_hash, report_bundle_hash, report_corpus_hash, sage_wiki_hash`（8项） | `V07_REPLAY_FILES` 冻结为 `config.yaml`、`scripts/agent_backend.sh`、`scripts/cleanup_intermediates.py`、`scripts/execution_provenance.py`、`scripts/normalize_challenge.py`、`scripts/preserve_failure_evidence.py`、`scripts/run_challenges.sh`、`scripts/run_cross_reviews.sh`、`scripts/run_experts.sh`、`scripts/runtime_guard.py`、`scripts/validate_prompt_bundle.py`、`shared/project_config.py`、`shared/report_wiki.py`、`shared/sage_wiki.py`、`shared/runtime.py`。 | 正常归档 fixture PASS；replay 缺 `shared/sage_wiki.py`、错哈希或错 batch_id 必须 FAIL。 |
| `0.8.0` | 同 `.7.0` 的 8 项 | 引入独立 `V08_REPLAY_FILES`，逐字冻结 0.8.0 当时 `BATCH_CONTRACT_FILES` 清单，含 `shared/sage_wiki.py`；另按现有分支核验 report-wiki engine snapshot、verification/adjudication receipts 等。不可让新 V09 当前清单重解释 V08。 | 正常归档 fixture PASS；删 Sage contract、engine snapshot 或 receipt，或改组件值必须 FAIL。 |
| `0.9.0`（建议新版本，待复核） | `data_hash, annual_hash, wiki_hash, prompt_contract_hash, prompt_bundle_hash, report_bundle_hash, report_corpus_hash, kb_snapshot_hash`（8项；以 KB hash 替代 Sage hash，不改变旧算法） | 新 `V09_REPLAY_FILES` 含 KB adapter、snapshot schema/verifier 与新合同；不含 Sage query/cache runtime。archive 要有 snapshot；最终只验证归档 snapshot。 | 正常 KB fixture PASS；缺 snapshot、篡改来源/body/context、重复 ID、draft、缺 owner 或错 batch_id 必须 FAIL，不触发 live 查询回退。 |

**V08_REPLAY_FILES 的冻结清单**（顺序按 0.8.0 `BATCH_CONTRACT_FILES`；该完整清单不得由 V09 修改）：

```text
SKILL.md
config.yaml
references/automation.md
references/data-contract.md
references/execution.md
references/report-gates.md
data/checklist_evidence_rules.json
data/expert_checklist.json
data/expert_result_v3.schema.json
data/experts.json
scripts/assemble_report.py
scripts/cleanup_intermediates.py
scripts/cron_prompt.txt
scripts/cron_trigger.sh
scripts/collect_challenges.py
scripts/collect_cross_reviews.py
scripts/collect_results.py
scripts/execution_provenance.py
scripts/expert_result_v3.py
scripts/native_agent_tasks.py
scripts/normalize_challenge.py
scripts/prepare_challenges.py
scripts/prepare_cross_reviews.py
scripts/prepare_prompts.py
scripts/preserve_failure_evidence.py
scripts/runtime_guard.py
scripts/validate_prompt_bundle.py
scripts/verify_manifest.py
scripts/verify_report.py
shared/batch_contract.py
shared/checklist_verify.py
shared/contracts.py
shared/data_tools.py
shared/expert_result_v3.py
shared/project_config.py
shared/report_wiki.py
shared/review_contracts.py
shared/runtime.py
shared/sage_wiki.py
```

批次 ID 字节向量（仅验证字段顺序/分隔；输入标签不是业务 hash）：五项 `D,A,W,C,P` → `ba9d6493936c0c8f043d441e`；旧八项追加 `B,R,S` → `99bbc3264cc8c3e29f641c80`；V09 八项以 `K` 替代末项 `S` → `cfb90a97b306d93ce8448580`。算法为 `SHA256(ASCII(NUL.join(components)))[:24]`。负例是调换顺序、删空值占位或使用另一版本组件字段；任一均须与向量不符。

**复核用 fixture ID / manifest 预期（设计规格，尚未运行）：** `KB-SNAP-V1-001` 使用上面的 canonical bytes，期望 snapshot hash 为 `af7df84c…3709a7d`；`BATCH-ID-0506-001`、`BATCH-ID-0708-001`、`BATCH-ID-09-001` 分别锁定上面 5/8/8 项向量。manifest fixture 固定 `ts_code=000001.SZ`、`run_id=fixture-<version>`（目录名相同）、报告名 `000001.SZ.md`；每个正例目录按该版本的预期 artifact/replay 集生成完整文件与 SHA/byte ledger，完整一致时预期 `verify_manifest` exit 0。

- V0.5.1 用 `MANIFEST-05-POS-001`、`MANIFEST-05-NEG-LISTED-FILE-MISSING-001`、`MANIFEST-05-NEG-LISTED-HASH-MISMATCH-001`、`MANIFEST-05-NEG-BATCH-ID-001`；缺失 manifest 已登记文件、篡改 hash 或 batch_id 均预期非零。V0.5.1 `is_legacy` 跳过 replay-set completeness 分支，因此**不**用“删除 Sage replay file”作为负例；仅目录中存在但未列入 `manifest.files` 的 replay extra 不触发 replay-completeness 检查；若列入 `manifest.files`，仍受 legacy 的 expected-name/inventory 校验，可能按 unexpected evidence 失败。
- V0.6.0 的正例暂不创建/不宣称 PASS，结果为 `LEGACY_UNVERIFIABLE`，直到找到并冻结原始 V06 合同证据与 `V06_REPLAY_FILES`。该清单冻结后再建 `MANIFEST-06-POS-001` 与缺件/错 hash/batch 的负例。
- V0.7.0、V0.8.0、V0.9.0 分别用 `MANIFEST-07-POS-001`、`MANIFEST-08-POS-001`、`MANIFEST-09-POS-001`，完整一致预期 exit 0；相应 `MANIFEST-07-NEG-REPLAY-MISSING-001`、`MANIFEST-08-NEG-REPLAY-MISSING-001`、`MANIFEST-09-NEG-REPLAY-MISSING-001` 移除该版本 required replay 文件，预期非零并包含“缺少运行契约”；相应 `MANIFEST-07-NEG-BATCH-ID-001`、`MANIFEST-08-NEG-BATCH-ID-001`、`MANIFEST-09-NEG-BATCH-ID-001` 改 batch_id 预期非零并报告身份不匹配。V09 再增加 `KB-SNAP-V1-NEG-SOURCE-PROOF-MISSING` 与 `...-SOURCE-HASH-MISMATCH`（缺 source bytes 或解码重算 hash 不一致）、body/context 改动、snapshot hash 不符、draft/owner 缺失负例，均须非零。V05 的 legacy 负例遵守其不检查 replay completeness 的既有分支，不套用 V07–V09 的负例。

历史版本的 `canonical_data_hash` 继续排除旧 hash/meta 字段；V09 新增 `kb_snapshot_hash` 也须排除，避免循环，但此字段归一化不改变 0.5–0.8 的原数据摘要。`verify_manifest` 要从四路版本常量显式分派 0.5/0.6/0.7/0.8/V09；不允许 fall-through 到“当前”。每个版本的完整合成归档 fixture 应断言预期 `batch_id`、manifest verdict 与缺件错误；所有适用版本负例覆盖 manifest-listed file/hash、batch_id、bundle 和未知 version。只有 replay-completeness 分支的版本（V06 清单固定后、V07–V09）测试缺 required replay file；V05 保持 legacy 分支，不测试它本来就不执行的 replay-subset 检查。真实历史归档样本未访问，synthetic PASS 不冒称已复验真实历史数据；缺少原始历史合同证据的版本保留 `LEGACY_UNVERIFIABLE`。

## 退场与合理删除策略（仅设计候选）

- 可在实施阶段考虑从活动路径删除：已被 KB 适配器替代且无活跃调用者的 Sage query/cache 代码、Sage 专属新批次 metadata/config、重复或明确反向的活动操作文档，以及被版本化 fixture 替换的旧运行测试。删除前须有精确文件 allowlist、全仓调用者/文档引用复核、V0.5–V09 的版本 fixture、旧版本 verifier 不导入/启动 Sage，以及同一候选 SHA 的独立工程 QA；缺一项则保留或标记 blocker。
- 旧报告、manifest、prompt、execution provenance、合同快照、真实/合成证据、KB 正文及运行时 cache 不属于本次“避免污染”的直接删除目标；不得按搜索词清空。对历史数据/缓存的删除必须另有明确路径清单、保留策略、审批和回滚任务。
- `SKILL.md`/`CLAUDE.md` 中相互矛盾的废弃方案可在实施时从活动指引删除，但在正式台账保留一条决定/旧 SHA 记录；历史 bug-log、已发布归档和合同快照不做追溯重写。`prewarm_corpus.py` 的 `sage-wiki compile` 注释未证明属于新知识 query，先不列删除候选。
- 本设计和本轮复核均不执行任何删除。实际删除是后续单独实现任务，必须列明每个路径、替代物、依赖方、删除前检查、版本控制回滚点与 QA 候选 SHA；“允许合理删除”不等于对未列路径作全局清理授权。

## 候选 TASK-ID 树与状态

### `INV-DES-05-KB-01` — 统一 KB 直连合同设计

- **Owner / 状态：** investPM；`DESIGNING / BLOCKED`。wiki_manager 已给出只读源事实和方案，尚未承担实现或 KB 内容维护。
- **依赖：** KB owner 确认规范只读入口及权限；`INV-DES-05-SAGE-RETIREMENT-01` 完成当前调用/批次兼容映射；至少有一条可用于验收的 `verified` 测试条目/fixture，或明确记录目前只有 draft、无法做正向运行验收。
- **交付范围：** 设计唯一来源、只读 JSON 查询/取文、条目过滤、来源归属与 freshness 检查、逐批快照/hash、失败处理及运行态禁止回退边界。
- **AC：**
  1. 规范化唯一 KB 根/接口与身份；不把缺失的 `../invest-kb`、旧 `invest-wiki`、本地缓存或内置文本误称为统一库。
  2. 仅接受 `kind=entry` 且 `status=verified` 的条目；记录条目 ID、owner、更新时间、来源引用、来源 SHA 与正文 SHA，并要求 KB 校验通过。
  3. 按本文件 `invest-skill.kb-snapshot.v1` schema 冻结 canonical JSON、UTF-8、字段/数组顺序、NUL domain separator、来源/body hash 与 `kb_snapshot_hash` 算法；附 literal canonical bytes 与预期 digest，未修改向量必须逐字复现。
  4. 正例：已 verified 且 source 原文字节归档、source/body hash 重算匹配的条目与固定 hash 向量可进入 Prompt 并留证。负例：draft、未知 owner、缺来源/原文字节、过期、重复 ID、source/body hash 不匹配、改动 body/context/order 或校验失败必须拒绝/重算不同 hash。故障例：根缺失、CLI/MCP 超时或格式异常、source 证明缺失、正文哈希漂移、snapshot 缺失时 fail-closed；不得静默回退旧库/cache/builtin。
  5. 另列 verified 条目不足时的运营阻塞与由 KB owner 维护内容的条件；本任务不改 KB、不要求生成内容。
  6. 冻结未来实现所需的命令、隔离 fixture、输入哈希、限额、日志、停止与回滚合同；本设计阶段不执行这些命令。

### `INV-DES-05-SAGE-RETIREMENT-01` — Sage 旧知识链路退场与历史兼容设计

- **Owner / 状态：** investPM；`DESIGNING / BLOCKED`；仅做静态依赖映射及迁移/清理候选设计；本任务不实际删除或改动 Sage 文件。
- **依赖：** `INV-DES-05-KB-01` 选择直接 KB 直连；盘点所有 Sage 查询、cache、batch field/hash、contract path、validator、report `knowledge_refs`、测试和用户文档调用。
- **交付范围：** 为新批次定义不再调用 `sage-wiki`、不写/读 Sage 专属 cache/metadata 的迁移方案；用 `kb_snapshot_hash` 和 KB entry provenance 替代新批次的 Sage context identity；明确当前 `sage_wiki_hash`/`sage_wiki.py` contract hash 的新旧版本兼容和历史报告验证策略。
- **AC：** (1) Sage 引用按运行调用、批次身份/校验、文档/测试分类，列路径/行号和未核范围；不以 grep 作完整性证明。(2) 新批次只读统一 KB `verified` entries，并归档可重算 source SHA 的原文字节；缺源/缺原文字节/缺条目/验证失败即停止，不调用 Sage CLI/cache/builtin/旧 wiki。(3) 按版本表明确 0.5.1/0.6.0 的五组件与 0.7.0/0.8.0 的八组件旧算法，以及建议 0.9.0 的 KB component；附三组 `batch_id` 向量、KB snapshot canonical-byte hash 向量、每版本正/负 manifest fixture 和预期 verdict。V06 replay set 在历史合同证据/fixture 缺失时明确 `LEGACY_UNVERIFIABLE`，不得冒称 PASS。(4) 旧 Sage 批次/manifest/report 只按固定旧算法、合同快照及旧 `knowledge_refs` 规则验证；新版本绝不让 current file list 重解释旧批次。缺旧证据时 fail-closed 并保留阻塞。(5) 区分允许评估删除的活动代码/废弃活动指引与禁止本任务删除的历史报告、manifest、prompt、cache、DB/KB 数据；实施阶段删除须有精确 allowlist、替代/归档、版本 fixtures、独立工程 QA 与回滚，当前不执行。(6) 列出所有未核项、命令/fixture/限额/停止条件；设计阶段不运行 CLI、测试或批次。
- **风险 / 回滚：** 误删 Sage contract path 可能使旧批次无法重放或 manifest verification 失败；V06 replay set 与真实历史 archive 样本当前未核，必须保持 `LEGACY_UNVERIFIABLE/BLOCKED`，不可用假 fixture 声称历史兼容。未来删除仅能按本文件 allowlist 条件执行；回滚需可从版本控制恢复每个删除路径，当前回滚限撤回本叶设计文字。

### `INV-DES-05-DB-01` — dataPM 数据只读复用可行性设计

- **Owner / 状态：** investPM；`BLOCKED_EXTERNAL_INPUT`。lead 提供的 dataPM 契约、视图与切换/隔离记录仅为文档级证据；当前服务/工具注册、ACL、逐数据集许可、刷新 SLA 和运行态仍未核验，不据此批准接入。
- **依赖：** 已收到 lead 转述的文档记录：ClickHouse 25.6.4.12、契约中的 11 个 `research.*` 视图；2026-10-26 文档称 MCP 曾返回另一份 7 工具清单，二者冲突；历史 ACL 记录称 `mcp_reader` 仅有 `SELECT research.*`、拒绝直读 `market.*` / `holdout.*`，但不能代表当前授权；合同标为 `DRAFT`，`deployed_unaccepted` 是历史状态。lead 报告 `research.bars` 以 `instrument_id/trade_date` 标识，OHLC 分、volume 股、daily amount 千元；daily_basic close 元、市值万元、股数万股；PIT 财报金额元，`knowledge_time <= as_of` 且以 `revision_no` 追加修订；`ts` 为 Asia/Shanghai、knowledge_time 时区未明；DataPM 复权采用按 bar 日期取因子的 hfq，qfq 已从其接口移除。未找到逐数据集许可核验表；部分数据源仍 `pending_review`；当前刷新 SLA 为 `UNKNOWN`，30 分钟自检和 10 分钟 coverage cache TTL 都不是数据新鲜度 SLA，1 分钟采集链为暂停/退役历史记录。对本仓 schema、data contract 与适配代码的静态 crosswalk 见下表；本地行情目标 unit 未在 schema/data contract 中完整声明，lead 所述“价格元、vol 手、amount 千元”不能据当前引用提升为已证契约；完整源到目标映射、instrument ID 对应、timezone/复权/report period/PIT revision 语义仍未完成，均保持 `UNKNOWN`。历史文档不证明当前运行态。
- **交付范围：** 将 dataPM 提供的契约与本仓 [schema.sql](schema.sql) 及 data contract 逐字段对照；比较“只读 API/视图/导出 snapshot”方案，优先避免共享可写数据库文件。
- **AC：**
  1. 对每个必需字段记录源表/字段及目标 SQLite 表/字段、单位、时区/日期、复权方式、公告日与报告期语义、缺失/迟滞规则和来源授权。lead 转述的单位仅视为源端文档口径；无法与本仓目标字段一一对应或证据不全之处保持 `UNKNOWN`，不得猜测转换。
  2. 明确连接方式与专用只读身份。若是 ClickHouse，最小化 `SELECT` 授权并排除写/DDL、BACKUP、管理权限和非必要表；仅引用官方设置说明，不替代实例配置验证。若是 SQLite，使用单独只读连接/快照，不允许走当前 `get_db()` 写连接或 migration。
  3. 正例：经授权的只读接口返回完整且口径匹配的合成/脱敏 fixture。负例：无权限、字段缺失、单位/复权/报告期不匹配、查询范围越界必须拒绝。故障例：超时、部分数据、schema 版本漂移、数据过期或接口错误应停止，不静默混用 Tushare/AKShare 或旧快照。
  4. 不更改 dataPM DB、schema、用户/角色、物化视图或共享服务；不连接实例；明确用户/数据 owner 的额外授权门槛。
  5. 将 lead 提供的外部文件路径/SHA 作为待采信 provenance 记录，不宣称 investPM 已核其内容或哈希。当前服务/tool registry 因历史 7-tool 记录与 DRAFT 契约清单冲突而 `UNKNOWN`；ACL 仅有历史记录，需 DataPM/部署方 dsh运维提供当前只读核验；逐数据集许可与刷新 SLA 由 DataPM 补权威材料，当前均 `UNKNOWN`。本仓目标侧已有局部静态 crosswalk，但 `daily_quotes` 的价格/vol/amount unit 无本地契约明文，适配器不做统一转换；lead 报告的“元/手/千元”需进一步给出支持该目标契约的本地证据，否则保持 `UNKNOWN`。`instrument_id` 映射、hfq/qfq、PIT `knowledge_time` 时区与 revision 保留也未闭合。coverage TTL 不冒充刷新 SLA，暂停/退役采集链不冒充现行计划；未获经授权证据前维持 `BLOCKED_EXTERNAL_INPUT`，不连接数据库、不改配置、不发接入结论。

#### 本仓目标侧局部 crosswalk（静态读取；不是接入验收）

以下将 lead 转述的 DataPM 文档口径与本 Skill 本地 schema/数据契约/适配代码作候选字段族对照；没有直接读取 DataPM 文件或运行数据路径。PM 对本地证据文件只读计算的 SHA-256：`schema.sql` `0d8b615a6e9e3bb2869b94cac85463198d2e82826771d841c5448fc95d52f0e9`；`references/data-contract.md` `d8cb6d489d7f04b710f2bd4b57a95e3d3f1edf8feeaa00389c20a93d38345d4c`；`shared/data_source.py` `52a4ff917b85884dd47eab636729b105f7cf6e778cd96538a52e45ed6cecdbf0`；`shared/data_tools.py` `405b9042dc13ee2e0dd6ced4b8f755c2f330a1b064c353c2ff135d653d95f21f`。

| lead 报告的 DataPM 字段族 | 本地候选目标 | 本仓现有证据 | 未闭合项 / 状态 |
|---|---|---|---|
| `research.bars`（`instrument_id/trade_date`）OHLC、volume、amount | `stocks.ts_code` 标识及 `daily_quotes.open/high/low/close/pre_close/change/pct_chg/vol/amount` | 本地列见 `schema.sql:9-23,57-74`；日期格式要求见 `references/data-contract.md:7,12`。Tushare 适配直接重命名/返回 `daily` 字段（`shared/data_source.py:181-190`）；AKShare 适配请求 `qfq` 并仅做数值解析，不做统一单位归一（`:451-484`）。 | lead 报告 DataPM OHLC 为分、volume 为股、amount 为千元，`ts` 用 Asia/Shanghai；需把 `instrument_id` 映射到 `ts_code`，价格分转元、股转手等转换须先冻结。lead 另称 Skill 目标 price=元、vol=手、amount=千元，但本地 schema/data contract 没有这些 unit 声明，且两类适配未统一归一；该目标单位主张不作为已证契约。source/target 对应、source-provider 单位一致性、时区、转换均 `UNKNOWN`；禁止直接复制或混合 provider fallback。 |
| DataPM `daily_basic`（close、估值、市值、股数） | `daily_basic.close/turnover_rate/pe_ttm/pe/pb/ps_ttm/ps/dv_ratio/total_mv/circ_mv/total_share/...` | 目标列见 `schema.sql:80-102`；本地 contract 明确 `total_mv/circ_mv` 为万元，AKShare spot 将元换万元（`references/data-contract.md:7-8`、`shared/data_source.py:523-541`）；消费者将市值从万元换算为亿元，并把总股本作为万股输出（`shared/data_tools.py:142-145,462-476`）。 | lead 报告 DataPM close 元、市值万元、股数万股、倍数为倍；市值单位有本地契约部分印证，close/股数及源字段逐列映射仍需适配验证。当前 endpoint/tool 注册、source freshness、逐数据集许可均未证实。仅为候选映射，不批准载入。 |
| DataPM 复权因子 / adjustment | `daily_quotes.adj_factor` 与行情 price columns | 目标列存在（`schema.sql:70`）；lead 报告 DataPM `hfq` 使用对应 bar 日期因子、`qfq` 已从接口移除；Skill AKShare fallback 仍请求 `adjust="qfq"`（`shared/data_source.py:451-456`）。 | adjustment basis、factor 算法和重叠日期规则未复核；DataPM hfq 与本地 qfq 不是可互换标记。须分 source/mode，禁止在同一批次混用或把因子直接套在 qfq 值上；未冻结前 `UNKNOWN`。 |
| PIT 财报 / 报告修订 | `income`、`balance`、`cashflow`、`fina_indicators` 的金额、`end_date`、`ann_date`/`f_ann_date` | 表列和唯一键见 `schema.sql:106-222`；本地查询按公告日 `ann_date`/`f_ann_date <= as_of` 过滤（`shared/data_tools.py:483-489,525-536`），金额作为元输出并换算亿元（`:500-509`）。 | lead 报告 DataPM 金额为元、按 `knowledge_time <= as_of` 筛选、修订以 `revision_no` 追加；DataPM `ts` 时区为 Asia/Shanghai，但 `knowledge_time` 时区未明。Skill schema 无 `knowledge_time/revision_no`，且 `UNIQUE(ts_code,end_date,report_type)` 等键不能保存同一期多修订；公告日筛选不等价于知识时间。字段映射、双时间轴、修订保留和 timezone 均 `UNKNOWN`，不得声称已支持 PIT。 |

**结论：** 本地只读核对提供了目标表/消费者侧部分证据；lead 补充的 DataPM 文档给出了需要处理的转换/版本差异，但源字段与本地目标单位仍未形成经验证的完整 crosswalk。重点风险为 `instrument_id→ts_code`、OHLC 分转元、volume 股转手、本地 adapter 未统一 normalise、DataPM hfq 与本地 AKShare qfq 冲突、PIT 双时间轴与 revision_no 无法由当前本地 schema 原样表达，以及 knowledge_time 时区未明。当前服务/tool registry/ACL/逐数据集许可/刷新 SLA 仍 UNKNOWN；DB 叶继续 `BLOCKED_EXTERNAL_INPUT`。取得经授权的现态/许可材料并冻结可验证映射前，不评估为可接入，不连接数据库、不改配置。

### `INV-DES-05-REVIEW-01` — 独立设计复核

- **Reviewer candidate:** 投研复核；实际派工、ACK、START 与 verdict 仅以本群真实消息及正式任务台账为准；本设计文件自身不构成派工。
- **依赖：** `INV-DES-05-KB-01` 与 `INV-DES-05-SAGE-RETIREMENT-01` 形成一个稳定、同版本的设计包；DB 子项若仍阻塞，审查范围必须明确为“未决/不作结论”，不能给整体通过。
- **AC：** 对同一冻结设计 SHA 逐条复核 KB snapshot schema/canonical bytes/expected digest、source 原文字节归档与 hash 重算失败规则、版本化 batch-ID 与 manifest 矩阵/向量（特别区分 V05 legacy 负例）、V06 明确阻塞、删改候选边界、来源身份、正负/故障 AC、数据授权、停止与回滚；若 V06 或其他历史证据未知，只能验证其 `LEGACY_UNVERIFIABLE` 处置是否清楚，不能判整体历史兼容通过。此设计复核不替代工程 QA，也不授权删除/实现/测试。
- **Limited review receipt (lead-reported, 2026-10-29):** 投研复核 returned `PASS` (0 blockers, 0 suggestions) on the frozen pre-receipt candidate SHA `2162a689ab1c8661bfa139109d1a2cbb80ce6aee5418c558bff4e348a794a903`, limited to the DB document-evidence boundary and local crosswalk (review scope: this document's cited lines 21–27 and 188–208 plus the named local evidence). This does not authenticate external source documents/content or current runtime state, establish database reusability, or constitute integrated overall-design or engineering-QA approval. The DB remains `BLOCKED_EXTERNAL_INPUT`. This receipt is appended after the review; the updated file digest is not the reviewed SHA and is not itself independently reviewed.

## 全局限制、验证与回滚

- 当前阶段只做代码/配置静态读取和已提供的 KB/dataPM 契约审查；**不运行** KB CLI/MCP、Sage、数据库、测试或批次，不读缓存、密钥或外部数据库内容。
- 未来实现验证命令必须待接口和设计独立复核后在实施/QA 叶任务冻结；不得将公共 WebSearch 命中当作本地实例配置或权限证据。
- 主要风险是错误绑定旧库、把 draft 当 verified、将可写 DB 暴露给 Skill 或把不同来源数据混成同一批次。若方案无法证明只读、来源身份或口径一致，则保持 BLOCKED，不改配置。
- 本设计任务回滚仅撤回本次设计文件/任务台账新增文字；不删除/恢复/修改任何 KB、数据库或运行时数据。不得标记 `READY_FOR_CODE`，也不得派发实现任务。
