# INV-SMOKE-03-DESIGN-01 — Prepare-only 合成 fixture 注入设计

- **版本 / 来源：**v0.3，2026-11-02。此前临时稿 `/tmp/inv-des-03-synthetic-fixture-design.md` 已不可读，故本稿为基于可见交接记录重建的新版本，**不是逐字恢复**。旧稿 SHA `2b4df2f544acbb60ed6c32caf942913eefb30a6510febca0aeb7153ccc24b18a` 及其限范围 PASS 只作历史记录，不自动适用于本稿；本稿需重新审查并产生新 SHA。
- **状态：**`DRAFT / NOT_RELEASED / NOT_READY_FOR_CODE`。仅设计，不授权读源码、代码修改、测试执行、prepare/CLI、DB/Wiki/Sage/Provider、runtime 写入或真实数据访问。候选基线和设计输入来自既有群记录；本轮未重新核验源码树。
- **父任务 / 拟任务：**`INV-SMOKE-03`；`INV-SMOKE-03-PREPARE-FIXTURE-SEAM-IMPL-01` 仍只是建议任务，不正式开启、不分配开发者或工程 QA。

## 1. 目标与范围

设计一个只能由可信 test harness 显式调用的 prepare-only 合成 fixture 路径，用完全合成输入生成 prepare 阶段的 7 份 prompt。只验证此阶段的依赖注入、输入/输出身份、现有 prompt 自检与写集边界；不执行专家，不做挑战、交叉复核、裁决、报告装配或完整流水线验收。

标准生产 prepare 的默认路径和既有门禁必须保持；fixture 产物不得称作生产报告、真实数据验证、Sage live PASS、完整流水线 PASS 或正式批次。方案不得把现有 `INVEST_TEST_MODE` / `INVEST_SKIP_SYNC` 当作安全隔离证明。

## 2. 既有静态证据（由先前授权核查记录转述，本轮未读源码）

1. `prepare_prompts.py` 的标准路径通过 data 工具取得数据；已有核查记录称，即使同步步骤可被 test flags 跳过，后续 `data_tools all` 仍打开 SQLite，`get_db()` 还可能做 schema migration/commit。因此不得把标准入口宣称为 DB-free。
2. `INVEST_TEST_MODE=1` 加 report-wiki fixture 可选本地 annual bundle，但 prepare 后续仍可调用 `report_wiki_engine_files()` 读取配置的外部引擎源码；bundle fixture 不等于 report-wiki 全隔离。
3. Sage 存在合成 fixture 路径可绕过查询/缓存，但已有观察记录称其状态可显示为 `mode=live` / `model=test-fixture`，不能直接作为 live 成功证据。
4. Wiki helper 接收 `wiki_root`；先按页面名查找，未命中时扫描 Markdown 标题。标准链路中 Wiki root 来源及从 harness 显式注入该 root 的能力尚未证明。
5. 导入 `shared.runtime` 可设置 umask 并解析/创建 runtime root；标准 prepare 还使用 run lease，并在 runtime root 写入、清理和逐项替换多个文件。不能声称此多文件提交原子。

以上均为历史静态观察，不是本轮复核或运行证据。确切 source SHA、当前行号、完整调用图和运行时效果 UNKNOWN。

## 3. 设计选择：side-effect-free core + 显式依赖

### 3.1 架构

采用内部依赖对象（暂名 `PrepareDependencies`）和独立、无 import-time I/O 的 prepare core：

- `shared/prepare_core.py`（候选新模块）只接收已构造的依赖、合成输入和输出 root，负责既有 prepare-only 纯编排、prompt 构建、现有 validator 调用及输出计划；不得在 import 时读配置、连接 DB、创建 runtime、解析外部 Wiki/Sage 路径或启动子进程。
- `scripts/prepare_prompts.py` 保留生产 CLI/wrapper。仅在 production entry 内按原路径建立生产依赖，再调用 core；不得改变生产默认行为、门禁和报告格式。production wrapper 拒绝 fixture capability。
- `tests/prepare_fixture_harness.py`（或等价 test-only harness，最终名字待开发设计冻结）只导入 side-effect-free core，不能导入会初始化生产依赖的 CLI wrapper。harness 使用显式合成依赖对象，不借助全局 monkeypatch 改写 production resolver。

若经后续授权核查发现无法把无副作用 core 与 production import 分离，或拆分会扩大本设计范围/改动既有门禁，立即 STOP 并提交设计变更；不得直接从标准 CLI “先运行再看”或依靠运行后 cleanup。

### 3.2 依赖接口

依赖对象包含互斥 provider，并在触碰任何项目依赖前完成全量验证：

- `mode`: 仅 `production` 或 `synthetic_fixture`；默认 production。
- `data_provider`: fixture 模式只读取 manifest 绑定的合成 JSON，不 import/call `shared.data_tools`，不打开 SQLite。
- `annual_provider`: fixture 模式只读取本地 synthetic report bundle；不调用 report-wiki CLI、不读 engine 源码、不设外部 repo cwd、不 refresh。
- `wiki_root`: 只能是 manifest 绑定的 fixture 页面目录；不得走 config 默认 Wiki root。若不能从调用链安全注入，则 blocker。
- `sage_provider`: 只返回 manifest 绑定的 synthetic context，显示 fixture provenance；不调用 Sage CLI、repo metadata traversal、cache fallback 或 Provider。
- `run_root`: 由已授权 harness context 传入的、唯一新建隔离目录；不得直接信任普通用户环境变量。

production 与 fixture providers 混用、mode 不明、capability/manifest 缺失或不一致时，必须在任何 runtime 初始化、DB open、外部进程或输出写入前非零 fail closed。test capability 不得由单个 env var、CLI 参数、`INVEST_TEST_MODE` 或 `INVEST_SKIP_SYNC` 激活；不可从父 shell、cron/headless 隐式继承。

## 4. 合成输入合同：已知 / 拟定 / UNKNOWN

所有输入由 fixture harness 生成并冻结，不接触真实/历史产物。以下“已知”均指先前授权静态核查的群内报告转述，本轮未重读源码；不等于 runtime 验证或完整 schema 冻结。

### 4.1 Data JSON

**已知（静态观察）：**
- `cmd_all` 顶层组装 `stock_info`、`market`、`annual`、`quarterly`、`balance`、`indicators`、`audit`、`industry`、`forecast`、`macro`、`meta`、`data_quality`；报告所引范围为 `shared/data_tools.py:1149–1163`。
- 已观察到的数据组件构造范围为 `shared/data_tools.py:450–907`；覆盖股票身份、行情/估值、年度与季度历史、资产负债/指标、审计、预告、行业与宏观等。具体字段名和值规则应以已有引用切片为准，不从类别描述补造字段。
- `validate_snapshot`（报告范围 `shared/data_tools.py:910–1146`）检查代码/主要分区一致性；行情日期距分析日 0–7 天；年度序列非空、年份唯一有序且最新财年匹配；最近四季连续且季度/日期一致，并校验关键字段与 TTM/FCF；资产负债、指标、审计和预期财年匹配。市值与股价×股本偏差超过 5% 会失败；缺同行样本、宏观或部分资产负债字段可触发 warning。状态按 errors/warnings 区分 FAIL/WARN/PASS。
- `cmd_all` 的 `generated_at` 使用当前时间；生产组件执行可能触 SQLite，宏观组件可能触数据源。因此 fixture 不得调用 production `cmd_all`。

**拟定 fixture 合同：**保留固定测试代码 `999999.SZ` 与固定分析日；提供上述所有顶层分区、内部身份一致性和足以通过既有 `validate_snapshot` 的合成字段；将时间来源显式固定，保证重复输入确定性。验证函数可复用，但生产 data acquisition/write 函数不得调用。fixture 中所有 identity/provenance 明示 synthetic，不能表示为真实证券批次或真实数据源验证。

**UNKNOWN / 冻结前必须核清：**完整必需字段和类型、各分区的精确 identity key、`data_quality` envelope/阈值及降级规则、批次/契约 helper 行为、exact analysis date/generation time 字段、validator 引用的外部常量。未核实字段不得臆造为正式 schema，也不得以 fixture 专用宽松路径跳过现有身份/质量门禁。

### 4.2 Annual bundle

**已知（静态观察）：**`shared/report_wiki.py:132–441` 的 `validate_report_bundle` 结构检查需要受支持的 schema version、PASS 状态、标的/分析时点、完整年份及报告类型/期次、bundle/corpus hash、空 `missing`、warnings 和 Sage 状态；v2 还检查 evidence/summary/search 状态及 search 内容 hash、文档数和页数。`reports` 项目包括 period、公告日、标题、HTTP(S) 来源、受限相对路径、source hash/bytes、页数与 `page-exact` provenance；v2 另检查 build/document/sections/rules hashes、evidence path、parser/OCR、下载时间。`sections` 要求 section name 唯一、正文与 text hash 一致、页码合法，并覆盖 MD&A 和风险章节。

**拟定 fixture 合同：**只构造本地 synthetic bundle，不调用 report-wiki CLI、engine snapshot reader、外部 repo 或 refresh。为满足 HTTP(S) 形状而不冒充真实来源，拟用 IANA 保留的 `.invalid` 主机（如 `https://fixture.invalid/...`），并在 bundle/manifest 中显式记录 `source_kind=synthetic_fixture`、synthetic fixture ID、内容 hash 与“不是实际公告/页码证据”标记。section/body/pages 均为虚构文本。该 `.invalid` URL 与 synthetic provenance 是提案，必须确认 validator/consumer 支持且绝不会被访问；不能把虚构页码标成真实 `page-exact`。

如现有生产 validator 强制 `page-exact` 或不接受 synthetic provenance，不得伪造真实证据或放松生产验证；应设计仅 test-capability 下的明确 fixture schema/validator 分支，且 production 默认继续拒绝 fixture。是否允许这类 test-only schema 是需评审决定的设计门槛。

**UNKNOWN / 冻结前必须核清：**`SUPPORTED_BUNDLE_SCHEMAS` 的值；hash 正则、canonical/hash helper；`MIN_ANNUAL_PAGES`、`MIN_SECTION_CHARS`、`MIN_ANNUAL_VISIBLE_CHARS` 数值；bundle/corpus/search/build/document/rules hashes 的完整生成输入；年份/报告期/公告日准确规则；受限相对路径和 evidence 约束；synthetic provenance 如何通过校验且不泄漏到生产。

### 4.3 Wiki、Sage 与 manifest

- **Wiki 已知：**resolver 先按页面名匹配，未命中会扫描 Markdown 标题；方法输入显式链接到唯一文件名可减少 fallback，但不能代替禁止真实 Wiki/config root。resolver root 是否能从注入 seam 贯通仍 UNKNOWN。
- **Sage 拟定：**纯 fixture context 与显式 `source=fixture`、`provider_called=false`、fixture digest；绝不伪装 `mode=live`。具体 consumer schema/状态字段 UNKNOWN。
- **Manifest 拟定：**schema version、task ID、候选 source SHA、fixture mode、adapter 类型、固定标的/日期、每个输入 canonical path+SHA-256、run ID/root、预期产物、完整写集、synthetic provenance 与外部访问禁令。canonical serialization、domain separator、hash 向量和上述未知 bundle/data 字段均待冻结；不得用占位 hash 声称通过。

所有生成必须确定性：相同 manifest 与输入字节得到相同规范化 prompts；会变化的时间/随机/环境字段必须固定注入或明确排除在 hash 范围外并记录理由。

## 5. 写入边界和失败语义

- 输入 fixture root 与输出 run_root 分离；输入只读且清单封闭。run_root 必须全新、不存在，父目录、symlink、canonical identity 和与 repo/runtime/DB/报告/Wiki/Sage 根不重叠性必须可证明；任一不明即 STOP。
- 在 capability、provider 类型、manifest/schema/hash、目录身份和精确写集全部验证前，**零项目文件写入**。输出只能是 7 份 prompts、规定的最小运行 evidence 与最终完成 manifest；其他路径均禁止。
- 先在 run_root 内以本次独占 stage 写每个输出，再逐文件 replace。prepare 多文件输出不原子：部分替换后失败时保留失败现场，不自动清理/重试，不生成 completion manifest，任何下游不得消费该批。
- completion manifest 仅在全部预期输出存在且 hash/provenance/self-check 通过后 create-only 写入，作为唯一成功标记；已有目标、stage 身份无法核验、异常清理策略不明或写集偏差一律 STOP/FAIL。
- 任何真实 SQLite/DB、report-wiki CLI/engine、真实 Wiki/config root、Sage CLI/cache/repo/Provider、默认 runtime 的访问企图，必须有副作用前的拒绝证据。若只能事后观察结果，不能证明未访问，隔离验收失败。
- production path 不接受 fixture capability；fixture 产物明确标注 synthetic，不能导入 production runtime/report pipeline。

## 6. 未来执行序列（当前不执行）

1. 可信 harness 先读取并校验 manifest 与只读 fixture package；不导入项目生产 CLI。
2. 校验 candidate/input hash、mode/provider、capability、run_root 不存在、父路径身份、完整写集和受支持平台；失败时零写入退出。
3. 构造 fixture dependencies 后才 import side-effect-free core；如有任何 production adapter 或 import-time runtime side effect，立即停止。
4. 只运行 prepare-only core；不得启动专家、Sage、report-wiki、DB、Provider 或下游阶段。
5. 验证七份 prompts 的 schema、身份绑定、hash、synthetic provenance 及精确写集；全部通过才提交 completion manifest。
6. 记录命令、allowlisted 环境（无秘密值）、退出码、stdout/stderr hash、依赖拒绝探针、输入/输出 hash、文件清单和失败现场。失败不自动 cleanup/retry。

## 7. 验收标准（未来，由设计冻结后的实现与独立 QA 执行）

**正向：**完整 frozen manifest + 所有纯 fixture providers 仅经 side-effect-free core 生成 7 份预期 prompts；输入输出 hashes、身份字段和 synthetic provenance 全匹配；实际写集等于批准清单且只在唯一 run_root；completion manifest 最后生成。可证明零 DB、零外部 CLI/engine、零真实 Wiki/Sage/Provider、零默认 runtime 访问。

**负向/故障（区分已观察规则与待核合同）：**
- **Data 已知门禁负例：**代码/关键分区身份不一致、行情日期距分析日超出 0–7 天、年度为空/年份重复或乱序/最新财年不匹配、最近四季不连续或季度/日期不一致、TTM/FCF 错误、资产负债/指标/审计财年不匹配、市值与股价×股本偏差超过 5%，按已观察的 `validate_snapshot` 规则应 FAIL。同行样本/宏观/部分资产负债字段缺失可能只产生 warning；不得把 WARN 偷升为 PASS，须断言实际 errors/warnings/status 映射。精确字段名、边界值与 warning 分类仍待核。
- **Annual 已知结构负例：**不支持的 schema version、状态非 PASS、缺失标的/分析时点/报告期信息、`missing` 非空、report/section hash 不符、非法相对路径、重复 section name、非法页码、缺必需管理层讨论/风险章节，按已观察 validator 的要求拒绝。v2 的 evidence/summary/search/build/document/sections/rules 相关字段只按对应 schema 版本检查。精确 schema 常量和 canonical hash 规则尚未核实。
- synthetic annual 来源必须明确合成，建议 `.invalid` URL 仅满足 HTTP(S) 形状，且带 `source_kind=synthetic_fixture`；不得伪造真实公告、真实页数或 `page-exact` provenance。若现有 validator 只接受真实型 provenance，必须 STOP 并设计 test-only 合成 provenance 分支；不得放宽 production validator 或把合成证据标作真实。
- production+fixture、fixture+production、错误/缺失 capability、manifest 缺项/错版、input hash mismatch、data/annual schema 错误、wiki link 缺页、Sage provenance 缺失，均在项目 IO 前非零退出且无输出写入。
- run_root 已存在、父级或目标 symlink、目录不可信、路径越界、清单外写入、fixture mode 泄漏到 production wrapper：拒绝执行，不覆盖/删除已有对象。
- 注入 staging/write/fsync/replace/self-check 失败：目标写集外零变化；不产生 completion manifest，不自动清理未知 stage、不重试，失败证据保留。
- 试图触发真实 adapter 时，必须在 SQLite/子进程/文件访问等副作用发生前由隔离机制拒绝；任何无法证明拦截先于副作用的情形判 FAIL/STOP。
- 七份 prompts 的任一身份/hash 不一致、输出缺失或多出文件，整批 FAIL，不能把逐文件 replace 描述为组原子提交。

不包括标准生产 prepare、真实数据/DB/Wiki/Sage/Provider 或完整 experts/challenges/reviews/adjudication/report pipeline。

## 8. 待授权源码核查清单（精确建议范围；本轮没有读取，需 Lead 另行书面放行）

建议对登记的干净候选 `f585407d8712f3bed0e236e4b1bf403970cf60aa` / tree `1580b755d0e923e04fec91fad3e55f53e4d8e45b` 做一次前置身份确认，限下列已有记录行段；完成后再做一次身份/clean 收尾确认。本轮设计修订未重新读取或 grep 源文件。未来核查须由 Lead 另行书面放行；不得访问 config/DB/Wiki/runtime/凭据/真实数据。身份/行号漂移、需上下文或出现未列依赖即 STOP 并申请新增范围：

| 待核事项 | 建议精确 path/line | 核查问题及边界 |
|---|---|---|
| prepare 入口、依赖构造、data/annual/Wiki/Sage 调用与写集 | `scripts/prepare_prompts.py:241–321, 713–755, 997–1064, 1336–1435, 1456–1492, 1612–1648` | 确认 side-effect-free seam、调用顺序、七份 prompt 与输出写点；不运行。已有读取片段只作旧证据，不视为本次新授权。 |
| data schema 与 DB bypass 可行性 | `shared/data_tools.py:53–105, 252–341, 1020–1203` | 只读确认必需字段和可替代 adapter；严禁连接、读取 DB 或 sidecar。 |
| annual bundle/报告引擎边界 | `shared/report_wiki.py:32–55, 468–558`；`scripts/prepare_prompts.py:294–321, 1415–1435, 1477–1492` | 确认 fixture adapter 是否能完整替代，不访问外部 repo/config、不运行 CLI。 |
| Wiki root 注入与 resolver fallback | `scripts/prepare_prompts.py:713–755, 1400–1410, 1460–1475` | 确认 root 是否从入口贯通、fallback 是否可禁用；不访问真实 Wiki/config。 |
| Sage fixture 状态、query/cache/metadata 路径 | `shared/sage_wiki.py:67–161, 211–269, 282–415`；`scripts/prepare_prompts.py:1456–1469` | 确认 status/provenance 如何传入 prompt；不访问 Sage/cache/repo、不运行 Provider。 |
| import-time runtime 与 lease | `shared/runtime.py:1–29`；`scripts/runtime_guard.py:58–153` | 确认 core/harness 能否在所有副作用之前建立隔离；不访问实际 runtime、不创建目录。 |
| data/annual/wiki/prompt validator 最小 schema | `scripts/validate_prompt_bundle.py:12–38, 41–179, 182–201`；额外 validator 必须另列 exact path/line | 只读核实必要字段与门禁；不运行 validator/test。 |
| 异常、cleanup 与部分写失败边界 | `scripts/prepare_prompts.py:1336–1435, 1612–1648` | 确认 fail-closed 和现有退出契约；不读 runtime/output/evidence。 |

### 8.1 为冻结 data/annual 合同仍需定位的 helper 与常量（本轮未查）

以下符号/定义行不在本轮允许范围内，行号保持 `UNKNOWN`；表中是下一次申请的精确定位建议，不是读取授权。若 Lead 选择先定位，定位只输出指定文件内的符号定义行号/直接 callee 名，不输出正文；拿到行号后再申请精确函数体读取。

| 合同项 | 精确文件/符号定位建议 | 定位后仍需核实 |
|---|---|---|
| Annual schema 支持集 | 文件：`shared/report_wiki.py`；符号：`SUPPORTED_BUNDLE_SCHEMAS`。建议未来做仅输出该文件中此精确符号赋值定义行的定位；定义行/函数体范围目前 `UNKNOWN`。 | 每个 schema 的适用字段；不默认所有 schema 均支持同样 v1/v2 字段。 |
| Annual 限值 | 文件：`shared/report_wiki.py`；精确符号：`MIN_ANNUAL_PAGES`、`MIN_SECTION_CHARS`、`MIN_ANNUAL_VISIBLE_CHARS`。仅定位这些赋值行；定义行目前 `UNKNOWN`。 | 精确数值、作用条件及按 schema 的差异。 |
| Annual hash/规范化 | 文件：`shared/report_wiki.py`；已知调用范围 `132–441`，需从该范围确定 hash regex 与 canonical/hash helper 的确切符号，再只定位其定义行。helper 名/定义行 `UNKNOWN`。 | 输入字节范围、编码/规范化、domain separator、字节数计数、路径约束及任一版本是否需 build/source hash。 |
| Data quality envelope | 文件：`shared/data_tools.py`；已知调用范围 `910–1163`（`validate_snapshot` 与 `cmd_all`）。须先从已授权观察中列出 `data_quality` builder/validator 直接 callee 名，再仅定位这些符号在该文件内的定义行；名称/行号 `UNKNOWN`。 | required/optional 字段、warning/fail 映射和 fixture 中 synthetic source 标记位置；不能将 warning 降级或绕过检查。 |
| Batch/contract identity | 起始调用范围：`shared/data_tools.py:910–1146` 与 `scripts/prepare_prompts.py:241–321, 1336–1435`。helper 名称/所属文件 `UNKNOWN`；先识别这些已授权片段内直接引用的身份/contract symbol，再由 Lead 决定是否批准相应定义行定位。 | fixture identity 的允许格式、与生产身份门禁的隔离关系、是否可只在 fixture capability 下识别 synthetic id；不得伪造生产 batch authenticity。 |

**建议的最小定位步骤：**另请 Lead 授权一次 DSH `grep`/符号定位，仅作用于 `shared/report_wiki.py` 与 `shared/data_tools.py`；只返回上表列出的常量定义行、`validate_report_bundle`/`cmd_all` 已知调用的直接 helper 定义行，以及 data/identity 相关直接引用符号名，不返回函数正文、不跨文件搜索。身份或符号未找到即记 `UNKNOWN`，不扩大范围。之后再按实际命中位置逐个申请精确只读函数体/常量行段。`validate_report_bundle` 已记录从 `shared/report_wiki.py:132` 起，顶层常量可能在此前，但不得假设都在 `1–131`；hash helper 位置也可能在别处。任何 helper 如解析到其他文件，必须另请 Lead 列明 path/line 后授权。

如果上述已批准历史范围不足以回答单一问题，只列精确缺口 path/line 和原因另请 Lead 放行，不得自行扩读。任何源码核查均不等于代码执行或运行批准。

## 9. 未冻结责任与下一门禁

目前无开发者、独立工程 QA、固定输入 package、准确新增/修改文件写集、测试隔离实现、测试命令、rollback 或候选实现 SHA；均为 `UNKNOWN / NOT_ASSIGNED`。开发与 QA 暂不创建/分派，待设计及核查范围收敛后由用户/Lead另行裁定。

本稿通过独立设计复核和 PM 接受也不自动变成 `READY_FOR_CODE`。必须先获 Lead 的精确源码只读 release、完成核查并把 unknown 收敛为明确设计；之后另行冻结实现任务、写集、候选 SHA、测试命令、隔离与回滚，再由 PM 决定是否放行开发，并为同一不可变 SHA 指派独立工程 QA。当前维持 `DRAFT / NOT_RELEASED / NOT_READY_FOR_CODE / NO RUN / NO TEST`。
