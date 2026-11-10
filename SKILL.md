---
name: invest-skill
description: A股公司深度投资分析与估值工作流。适用于用户要求分析某家 A 股公司、给出股票代码、询问估值/财报/护城河/成长质量/管理层，或要求生成可审计投资报告；通过七位独立专家、二级质询、条件触发的三方盲审和裁判长形成 7+1 结论。
---

# A 股深度投资分析

执行可复核的 7+1 专家分析。把脚本门禁视为发布契约；失败时禁止推进后续阶段，仅能执行下文明确授权的恢复/唯一重试，终局失败必须停止。不得用文字承诺代替验证结果。修改本协议会使旧批次控制哈希失效，不得沿用活动批次结果。

## 运行边界

- 在本 skill 根目录运行命令。启动本批前将 `INVEST_HOST_AGENT` 设为真实且具体的编排身份，不使用 `current-agent` / `unknown` 等占位值；执行台账与发布签收须可交叉核对。
- 运行时产物（SQLite 数据库、日志、报告、auto_state 状态）写入运行时根：
  由调用方设置 `INVEST_SKILL_HOME`（如宿主项目的 `.invest-skill-runtime/`），
  未设置时回退到本仓库（仅向后兼容，不要把运行时产物长期留在 skill 仓库）。
  `shared/project_config.py` 的 `runtime_root()` / `configured_path()` 是唯一路径入口。
- 使用 `config.yaml` 配置数据库、报告目录、invest-sage 与独立
  `~/invest-report-wiki` 的路径。年报唯一通过其公共 CLI 获取；不要读取 Sage
  私有数据库。
- 运行时文件统一写入 `INVEST_RUNTIME_DIR`（显式设置时）或 `INVEST_SKILL_HOME`；
  两者未设置才允许兼容回退 `/tmp`，不要混用 `TMPDIR`。
- 认知工作必须由**当前主 agent 的宿主原生子代理/委派能力**启动。创建子代理时不得
  指定 provider、model 或另一个产品名，确保子代理自然继承主 agent 的 provider/model、
  认证、配额和会话谱系。宿主没有原生子代理能力时，在任何模型调用前明确停止。
- 使用 `scripts/native_agent_tasks.py` 准备、提交和校验原生子代理任务；每个子代理只读
  计划给出的唯一任务书，只把输出写到给出的 staging 路径，不使用网络、shell 或外部知识。
- `run_experts.sh`、`run_challenges.sh`、`run_cross_reviews.sh` 只保留为显式外部 CLI
  兼容层，默认不得调用、不得自动探测 Codex/Claude、不得跨产品 fallback。只有用户明确
  要求外部 CLI 时，才可同时设置 `INVEST_ALLOW_EXTERNAL_AGENT=1` 和 `--agent`。
- 不要并发运行同一股票的 prepare、专家、质询、盲审或定稿阶段；运行门禁会硬拒绝第二个写入者。

需要理解运行锁、唯一重试、执行元数据或故障恢复时，读取 [执行与恢复](references/execution.md)。

## 工作模式：默认深度 7+1

- **深度 7+1（默认）**：用户只给股票代码、公司名称或说“分析某公司”，直接执行下述全部七专家、七质询、条件盲审和独立裁判/复核流程，不询问模式。用户要求完整估值、评级或跨领域投资结论时同样执行全流程。
- **窄路径（仅用户明确要求）**：只有用户明说“精简 / 快速核验 / 只核对某个事实”等，才先确认具体披露、指标、口径和期间，再进行限定范围核验。单独说“财报审计”不自动授权缩减为窄路径。窄答须标明范围与未执行的环节，不得使用完整 7+1 报告或综合评级的名义。

模式只能升级不能自行降级；深 → 窄必须由用户明确要求。没有完整执行与通过发布门禁，不得宣称产出正式报告。

## 标准流程（深度 7+1）

### 一、确认输入

把代码规范化为 `000001.SZ`、`600000.SH` 或 `430000.BJ`。只有公司名时，先可靠确认唯一证券代码；无法唯一确认则询问用户。

日常运行保持 `config.yaml` 的 `project.analysis_date` 为空。只有用户明确要求历史回测时才钉住日期，并说明这是历史时点分析。

### 二、准备同批次快照

交互式新分析默认强制刷新，避免同日重复分析复用旧缓存：

```bash
python3 scripts/prepare_prompts.py <code> --force-sync
```

用户要求“最新半年报/中报/H1”时必须显式绑定半年度证据，不能只跑年度默认值：

```bash
python3 scripts/prepare_prompts.py <code> --force-sync --include-semiannual --semi-years 2
```

自动化或明确复用当前批次时，可省略 `--force-sync`。该步骤必须同时得到：

- `invest_data_<code>.json`
- `invest_annual_<code>.txt`
- `invest_report_bundle_<code>.json`
- 七份 `invest_prompt_<code>_<expert>.txt`（含真实叶子路径的数据字段字典，作为批次证据与 v3 任务书的输入；原始模板的 Markdown 输出说明不适用于原生专家交付，专家以 begin 生成的唯一 v3 任务书为准）
- 唯一 `meta.batch_id`；
- 行情水位、公告查询完成时间/截止水位、最新报告期次与类型；
- `SKILL.md`、native 运行器、修复器、组装器、验证器、准出规则及 report-wiki 引擎源码树的冻结哈希。

prepare 后任何控制面文件或 report-wiki 引擎字节发生变化，旧批次必须立即终止并重新 prepare；严禁在活动批次中修门禁后继续沿用旧结果。恢复运行前必须重验 trade/report/batch identity，任一变化即废弃旧专家结果。

prepare 内置**模板可满足性自检**（硬门禁）：字段字典路径必须全部真实存在于快照、
prompt 不超体积上限；自检失败（exit 2）视为准备阶段失败，禁止进入专家阶段——
契约不一致在准备阶段暴露，而不是 7 位专家跑完后才暴露。

准备脚本会调用 `~/invest-report-wiki/bin/report-wiki materialize`。已有且通过
验证的公司语料直接复用；缺少时由 report-wiki 自行下载，生成页级原文、章节
哈希和本地 FTS5/BM25 索引。Sage/LLM 摘要不是年报 evidence 的硬依赖；
`--force-sync` 只检查新披露/更正版，不无条件重编译未变化原件。

若 `data_quality.status=FAIL`、report-wiki 未实现或其 bundle 未通过完整年度、
公告日、逐页来源、原件/章节/索引哈希、最新应有年报缺失、方法论 Sage live/cache
契约缺失或 prompt bundle 哈希不一致，立即停止。Sage 查询失败时仅允许使用按专家
主题独立保存且内容哈希通过校验的缓存；无合格缓存仍 fail-closed。
处理取数和口径问题时读取 [数据契约](references/data-contract.md)。

### 三、并行执行七位专家

**先执行注入门禁，再生成 host-native 任务计划**。解释器须使用项目 `.venv-macos/bin/python`，或先 `source ../activate.sh` 后使用下列 `python3`。`INVEST_PANEL_TOOLS` 必须指向受信任专家面板工具目录；先确认两份工具存在，不自动下载替代品。`<runtime-dir>` 必须是本批实际 `shared.runtime.RUNTIME_ROOT` 的绝对路径，不能盲用示例目录。

```bash
# prepare 之后、begin 之前；必须 exit 0
python3 "${INVEST_PANEL_TOOLS:?未配置面板工具目录}/injection_gate.py" --runtime <runtime-dir> --code <code>
```

门禁须确认七份 prompt 都包含 `提交前归属规则`、`待验证假设清单` 且 `batch_id` 一致。保留 stdout/退出码作为编排台账证据；工具不存在或校验失败即停止，禁止派发专家、禁止伪造通过。检查本身不得修改冻结 prompt/专家面板；若必须修改契约或面板，先终止旧批次，仅在批次之间变更并重新 prepare。

注入门禁通过后生成计划：

```bash
python3 scripts/native_agent_tasks.py begin experts <code>
```

读取返回 JSON 的 `jobs[]`，使用当前宿主的原生子代理能力并行委派；**不传 provider/model
覆盖值**。每个子代理严格执行 `jobs[].instruction`。若宿主不给子代理写文件能力，主 agent
把子代理返回的完整文档写入对应 `staged_output_path`；不得改用外部 CLI。主 agent 不得在 `jobs[].instruction` 外追加结论、指定 verdict、指定删改措辞或其他语义指令。提交时必须传回宿主实际 child id；计划会归档 prompt/instruction/staging 哈希和委派回执。**先执行下文“每份 staging 在 commit 前”的两步自检**，两步均通过后才逐一提交并推进门禁：

```bash
python3 scripts/native_agent_tasks.py commit experts <code> <job-id> --child-id <host-child-id>
python3 scripts/native_agent_tasks.py advance experts <code>
```

`advance` 返回 `PASS` 才能继续；返回 `FAIL` 时按其 `next` 进入唯一重试；返回
`CONTINUE` 时，仅并行执行新 `jobs[]` 并重复 commit/advance。

七个领域是：财务排雷、价值估值、成长质量、护城河、认知风控、宏观周期、管理层审计。**专家 staging 交付物是单一 ExpertResult v3 JSON object，不是 Markdown**：

- 以实际任务书的 schema/identity 为准，匹配 `expert_id`、`ts_code`、`data_date`、`analysis_date` 和 `batch_id`；
- prose 中事实、计算、方法阈值和假设分别使用任务书给定的 `{{F001}}`、`{{C:...|...}}`、`{{M:...|...}}`、`{{A:...|...}}` token，不手写数值、YAML frontmatter、`[source:]` 或 `[calc:]`；
- 至少五个 analysis_sections、三条 risks、全部 checklist_conclusions 键；正文合计至少 1200 字符，其余硬要求遵守唯一任务书；
- 不跨专业域替其他专家做结论。编排方不得改写 JSON 的判断或为通过门禁删证据。

**每份 staging 在 commit 前，由编排方执行两步自检**（专家禁止 shell）。使用每个专家独立的绝对检查路径，不能并发共用 `/tmp/check.md`；`<check-prefix>` 位于本批私有运行时目录，不覆盖正式结果：

```bash
python3 scripts/expert_result_v3.py compile <code> <expert> <staged.next> \
  --sidecar <check-prefix>.v3.json --markdown <check-prefix>.md
# 第一步 exit 0 后才执行第二步；输入是渲染后的 Markdown，不是原始 JSON
python3 "${INVEST_PANEL_TOOLS:?未配置面板工具目录}/gate_precheck.py" <check-prefix>.md --expert <expert>
```

两步都 exit 0 才允许执行前述 `commit`。预检失败时将完整 stdout/stderr 与退出码保存到本批运行时目录的独占诊断文件，保留 staging 与真实 child id，以拒收入口登记（不发布失败件）：

```bash
python3 scripts/native_agent_tasks.py reject-precheck <code> <expert> \
  --child-id <host-child-id> --diagnostics <absolute-precheck-diagnostics>
```

处理完全部 jobs（通过件 commit、失败件 reject-precheck）后执行 `advance`，按其 `FAIL/CONTINUE/next` 进入唯一受控修复。诊断和失败原文会留证并进入 repair prompt；不得直接重复 begin、手改产物、删除证据或绕过预检。修复件同样要通过两步自检。

受信任编译器从 v3 JSON 确定性生成 YAML frontmatter、数值、`[source: JSON.path]`、可复算 `[calc: ...; inputs: ...]` 和最终 Markdown；这些是机器渲染结果的契约，不是模型原始输出格式。`commit` 的内部编译不能替代上述提交前预检。

初次失败时只允许执行一次定向重试：

```bash
python3 scripts/native_agent_tasks.py begin experts <code> --retry
```

该事务仍使用当前主 agent 的原生子代理且不覆盖 provider/model。唯一重试事务内最多
3 轮「修复→单专家校验」，每轮只注入冻结的官方原始任务书、该专家最新失败结果与完整 diagnostics（含未溯源数字、缺失路径、覆盖率），模型按诊断定向修复，不重跑已通过专家。首次独立输出的 decision（即使因格式未发布）会单独冻结并在每个 repair prompt 中明示；trace/格式修复必须保持 score、verdict、conclusion_direction 和 veto，任何漂移都会硬失败。若事实变化足以改变判断，应重建批次而不是借 repair 偷换结论。

只要发生 retry，所有 plan、官方任务书、repair prompt、diagnostics、rejected raw/hash、child id 与每轮执行事件都必须进入 retry evidence ledger；缺一项禁止发布。

重试仍失败则终止本批次，不得继续质询或组装报告。失败现场和完整 diagnostics 默认保留；复盘完成后才显式运行 `cleanup_intermediates.py`。

### 四、执行二级魔鬼代言人质询

```bash
python3 scripts/native_agent_tasks.py begin challenges <code>
# 原生并行委派 jobs[]，逐项 commit
python3 scripts/native_agent_tasks.py commit challenges <code> <job-id> --child-id <host-child-id>
python3 scripts/native_agent_tasks.py advance challenges <code>
```

七份回应都必须绑定原报告哈希、结构化 claim/evidence/assumption/risk/checklist/decision 输入束和 challenge prompt 哈希。合法 `challenge_verdict` 只能是 `UNCHANGED`、`DOWNGRADED`、`UPGRADED`。合并回应统一为 180–360 个中文字符，覆盖不利情景、结论是否改变和下一个可证伪数据；不得新增数字事实。任何 `DOWNGRADED`/`UPGRADED` 都自动触发第三级盲审，不能只登记文字却不影响机器触发链。

初次失败时只允许一次：

```bash
python3 scripts/native_agent_tasks.py begin challenges <code> --retry
```

### 五、计算三级触发并生成草稿

```bash
python3 scripts/assemble_report.py <code> --name <公司名>
```

脚本会机器计算三级触发条件。若提示第三级已触发，执行：

```bash
python3 scripts/native_agent_tasks.py begin cross-reviews <code>
# 原生并行委派 jobs[]，逐项 commit
python3 scripts/native_agent_tasks.py commit cross-reviews <code> <job-id> --child-id <host-child-id>
python3 scripts/native_agent_tasks.py advance cross-reviews <code>
python3 scripts/assemble_report.py <code> --name <公司名>
```

三位盲审员使用独立身份 `blind-reviewer-a/b/c`，不能复用原七专家身份；输入必须匿名化原作者、原评分、原评级和原 verdict，三者彼此不可见结论。三位盲审员必须全部通过输入束、prompt 和聚合哈希校验。盲审初次失败时只能用一次 `--retry`，repair 仍须包含官方原始任务书且保持已有有效 verdict。

### 六、裁判长裁决

编排主会话无结论权：必须委派独立原生裁判子代理（不覆盖 provider/model），由其独立形成综合裁决。编排方只把裁判返回内容逐字转录到脚本生成草稿的裁决占位区域，记录真实 child id/身份和输入输出哈希；不得自行填写评级、改写措辞或调整仓位。不得手写整份报告或改动嵌入原文。没有独立裁判时停止在草稿。

裁判的 `adjudicator.identity` 必须填写真实裁判子代理 child id，与编排身份不同。

裁判读取以下材料：

- 生成的 `<code>.draft.md`；
- invest-skill 本地裁判契约及通过 `invest-sage` 标准查询获得的估值、护城河、
  成长、周期和治理知识。专家准备阶段使用 `sage-wiki query --scope local`，
  不直接读取 Sage 私有数据库；
- [报告准出规则](references/report-gates.md)。

在草稿中完成裁决占位符，不得改写或删减嵌入的七份专家原文和七份质询原文。裁决必须明确：

- VETO/WARN 的处理方式；
- 专家冲突及取舍理由；
- 原始加权分、认知修正与明确标注范围的仓位字段：`position_advice.scope=general_research`、`user_context=null` 为默认。默认只作通用研究情景：无经用户确认的持仓、风险承受能力、期限和组合约束时，不得给个性化现有持仓动作或新增实盘配置，现有动作必须 `NONE`、新增仓位必须为零；评级 `BUY/PASS` 不表示要求该用户实际买入。情景总仓位上限不是个人账户建议。个性化建议须声明 `scope=personalized`，`user_context` 必须与同批快照一致并含明确授权 `authorized_personalized=true`、请求 `request`、持仓 `holdings`、风险承受能力 `risk_tolerance`、期限 `investment_horizon`、资金基数 `capital_base`。不得臆造上下文或在 prepare 后手改快照；当前准备入口不能安全纳入这些资料时，停止个性化建议，保留通用研究范围，不能声称已支持完整个性化采集流程；
- 评级、关键证据、反方观点、触发条件与跟踪指标；
- `knowledge_refs` 使用 `{path, sha256}` 绑定实际裁判上下文，不再以“至少三个存在的页面”冒充已阅读证明；
- `## 裁判自检（非独立复核）` 只作声明，不打 90 分、不作为准出凭证。准出依赖机器 strict verification receipt 和 publication receipt。

数据未知就写未知；不能把缺失值当零，不能把相关性写成因果，不能用旧报告或外部口头补数绕过同批次 JSON。

### 七、独立投研复核签收与定稿

先由另一位独立投研复核者审阅**完整最终草稿**及证据，对裁决、反方、缺口和仓位边界作明确 PASS/FAIL；其身份不得等于编排者、裁判或本批专家/质询/盲审子代理身份。保存真实原生 child id（人工复核时保存可追溯人工身份）与完整复核原文，不得把自评或机器 PASS 冒充签字。编排方仅按复核者原话登记，不得代做 PASS 决定。

```bash
# 按实际身份与复核原文填写；身份声明不是密码学认证
python3 scripts/research_review.py <code> \
  --reviewer-identity <实际独立复核者身份> \
  --orchestrator-identity <实际编排者身份> \
  --verdict PASS --statement '<复核者的原始签收意见>'
python3 scripts/assemble_report.py <code> --finalize
python3 scripts/verify_manifest.py <正式报告路径>
```

签收绑定批次和完整 draft SHA-256；签收后草稿任何字节变化都必须重新独立复核签收。FAIL 或缺少签收禁止发布，不得只运行 finalize 重试。只有独立签收有效且后两条命令都成功才宣告完成。定稿采用两阶段发布：先给临时最终字节注入 manifest 标记，再用同一冻结且归档的 verifier 严格核查；随后生成 adjudication receipt、verification receipt、publication receipt，验证 manifest 与 finalize `GATES PASS` 后才原子替换正式路径。定稿会归档数据、report-wiki 证据包及引擎源码树、由该包确定性渲染的年报正文、实际 prompt/result、质询、盲审、retry ledger、完整控制面合同与执行元数据，最后清理可再生中间文件并写 cleanup receipt。

最终向用户简洁报告正式文件路径、评级、综合分、关键风险和数据基准日。若门禁未通过，明确报告失败阶段与可执行的下一步，不得给出伪完成结论。

## 自动化

处理 cron、daily、断点恢复或推送时读取 [自动化运维](references/automation.md)。`daily_analysis.sh` 只能产出待裁决草稿；无裁判长不得发布正式报告。

cron 自动分析由 `scripts/cron_trigger.sh` 拉起宿主 agent 会话执行认知步骤。该主会话
必须使用自身原生子代理能力执行 `native_agent_tasks.py` 返回的任务，子代理不指定
provider/model，因而与主会话同源。禁止在 headless 会话内另启 Codex/Claude/DSH CLI。
