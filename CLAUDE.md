# CLAUDE.md — invest-skill 项目配置

> ⚠️ **本文件是项目工程配置，不是 skill 定义。Skill 定义在 `SKILL.md`。**

## Skill 入口

分析协议、专家团架构和执行命令全部在 `SKILL.md` 中定义。本文件只包含项目基础设施配置。

## 双管道日报系统

invest-skill 是一个**双管道每日分析系统**的 Pipe A。每天分析 2 家公司，每家公司产出两份**完全独立**的报告：

```
每日 cron（02:00 / 04:30，DeepSeek API 低谷期 00:30–08:30 内执行）
  │  ⚠️ 调度权归宿主 invest-harness：crontab 条目全部指向
  │     ~/invest-harness/scripts/cron/cron_*.sh（wrapper），本仓库不持有任何定时配置
  ├── Pipe A：invest-skill（本工程）
  │   ├── 触发：宿主 wrapper → scripts/cron_trigger.sh → dsh --profile headless（独立新会话，与 GUI 同模型/skill 目录）
  │   ├── 数据源：Tushare → SQLite（data_tools.py）
  │   ├── 年报证据：../invest-report-wiki → 逐页原文 + 本地 FTS5/BM25 bundle（Sage 摘要可选）
  │   ├── 知识检索：invest-sage → 分专家 sage-wiki live/cache（7+1 执行契约在本工程）
  │   └── 报告：reports/invest_tool/<code>.md  （每公司一个文件）
  │
  └── Pipe B：ai-berkshire（独立工程 ~/ai-berkshire/）
      ├── 数据源：新浪财经（sina_finance.py）
      ├── 方法论：巴菲特-芒格-段永平-李录 四大师八步框架
      └── 报告：reports/ai_berkshire/<code>.md  （每公司一个文件，增量修订）
```

**调度职责边界**：本仓库只提供**执行能力**（cron_trigger.sh / daily_analysis.sh / watchdog.sh /
alert.sh 等被调用入口），**不拥有 crontab 条目、不自行注册定时任务**。"何时跑、跑几次"由调用方
（本机为 invest-harness）决定，通过 `scripts/cron/cron_*.sh` wrapper 注入环境并调用本仓库脚本。

**关键约束**：
- 🚫 两份报告完全独立，不互相引用、不汇总、不交叉验证
- 🚫 invest-skill 不得使用新浪数据；ai-berkshire 不得使用 Tushare 数据
- 🚫 不得修改 ai-berkshire 的任何已有文件
- 🚫 认知任务不得自动启动 Codex/Claude/DSH 等外部 CLI；只用当前主 agent 的原生子代理，且不覆盖 provider/model

### 自动分析 vs 手动分析

| | cron 自动分析 | 用户手动分析 |
|---|---|---|
| 触发方式 | `scripts/cron_trigger.sh` → `dsh --profile headless` | 用户对话中直接指令 |
| 选股范围 | 全 A 股（排除 688 科创板、8xx 北交所、ST） | 用户指定 |
| 跳过规则 | 5 天内已分析过 → 跳过，换下一家 | 不跳过，强制从头完整分析 |
| 状态文件 | `data/auto_state.json` | 不更新 |
| 报告路径 | `reports/invest_tool/<code>.md` | 同路径（覆盖更新） |

## 目录规范

| 目录 | 用途 |
|------|------|
| `SKILL.md` | **Skill 定义**（分析协议、专家团架构） |
| `shared/data_tools.py` | 数据获取工具（纯取数 + 基础数学） |
| `shared/data_source.py` | Tushare + AKShare 抽象层 |
| `shared/report_wiki.py` | invest-report-wiki 公共 CLI 与 bundle 契约适配器 |
| `config.yaml` | 项目配置（`paths.runtime_root` 可指定运行时根） |

**运行时产物不落本仓库**：SQLite 数据库、日志、报告、`auto_state.json` 等全部写入
调用方 `INVEST_SKILL_HOME` 指定的运行时根（本机为
`~/invest-harness/.invest-skill-runtime/`）。本仓库只保留 skill 资产
（协议、脚本、静态契约 `data/experts.json` 等）。路径解析统一走
`shared/project_config.py`（`runtime_root()` / `configured_path()`），不要硬编码。

## Wiki 联动

专家团执行契约仍由本 skill 的 `data/` 和旧版专家文件兼容层提供；通用投资知识
统一从 `../invest-sage` 通过 `sage-wiki query --scope local --format json` 检索，不直接读取
Sage 私有数据库；查询结果按专家主题写入 `INVEST_SKILL_HOME/data/sage_wiki_cache/`，
以内容哈希校验并支持 402/超时/网络失败时降级：
- wiki 中专家依赖的知识页面发生结构性变更时，专家团按自迭代机制更新
- 每次分析前检查 `_cache.json` 中的 `expert_versions`，若版本落后超过 7 天，提示检查 wiki 更新
- 分析完成后，将可复用的通用洞见回流到 wiki 对应的案例库

公司财报语料由独立 `../invest-report-wiki/` 管理。invest-skill 只调用
`bin/report-wiki materialize` 并归档其 bundle，不读取 Sage 私有数据库，不把
财报知识页当作 PDF 原文；年报证据只来自 report-wiki bundle。

## 跨管道对比迭代（第八步）

每次 Pipe A 分析完成后，自动触发 Pipe B（ai-berkshire）→ 四维对比 → 差距记录到 `data/improvement_candidates.json`。

#### 自动触发 Pipe B

Pipe B 由 `~/ai-berkshire` 独立工程触发。在 ai-berkshire 目录下调用其自身的分析指令即可，报告输出到 `reports/ai_berkshire/{code}.md`。不在此处硬编码触发命令。

#### 四维对比（只找差距，不找共识）

| 维度 | 对比问题 |
|------|---------|
| **数据** | ai-berkshire 有哪些数据 invest-skill 没拿到？ |
| **方法论** | ai-berkshire 发现了什么 7+1 专家团遗漏的风险/机会？ |
| **结论** | 两份报告的评级有实质性分歧吗？根源是什么？ |
| **表达** | ai-berkshire 的报告结构/叙事方式是否更清晰？ |

差距记录到 `data/improvement_candidates.json`，通过 3 道质量门禁（实质差距、可操作性、独立性）。

## 持续进化闭环

```
每次双管道分析完成
       │
       ▼
读 Pipe B 报告 → 四维对比
       │
       ▼
发现差距? ── NO ──→ 跳过
       │
      YES
       │
       ▼
记录到 data/improvement_candidates.json
       │
       ├── target: skill → 修改 SKILL.md / config.yaml / data_tools.py
       ├── target: wiki  → 更新 invest-sage 来源/查询契约
       └── target: data  → 扩展 data_tools.py 数据获取能力
       │
       ▼
人工定期 review → 落地 → 标记 resolved
       │
       ▼
下次分析时 skill 和 wiki 已进化 → 报告质量螺旋上升
```

---

## 移植后环境（2026-10-14 起生效，必读）

本工程已从外置盘移植到已授权工作区。上文提及 `../invest-sage`、`~/invest-harness/.invest-skill-runtime/`
的段落属**移植前的历史描述**，以本节为准：

| 项 | 现在 |
|---|---|
| 工程根 | `/Users/bazinga/.dsh/bot/workspace/invest/invest-skill` |
| 运行时根 | `../invest-skill-runtime`（已固定在 `config.yaml` 的 `paths.runtime_root`，**不需要** export `INVEST_SKILL_HOME`） |
| 解释器 | `.venv-macos/bin/python`；或每次开工先 `source ../activate.sh`（把 venv 放到 PATH 最前，避免仓内硬编码 `python3` 踩空） |
| 数据层 | `../invest-report-wiki`（自带 `.venv-macos`，PDF 依赖 pypdfium2 / pdfplumber） |
| 知识层 | `../invest-kb`（投资知识库 AI-Wiki 的桥接仓）：`wiki/concepts/` 是**生成物禁改**，`04_stock-analysis-expert/` 是**人手维护的专家面板** |
| 知识检索 | `invest-kb` MCP，或 `http://127.0.0.1:8787`，或 `sage-wiki` shim |
| 移植说明 | `../PORTING.md`（全部改动、修复记录与校验结果） |

## 编排规则（必须遵守）

1. **默认深度分析**：用户只给标的（"分析 XX 公司"）→ 直接按**深度 7+1** 跑完整流程，不要停下来问模式。
2. 只有用户**明说**"精简 / 快速核验 / 只核对某个事实"才走窄路径；窄路径必须先确认要核对的具体事实，**不得冒充完整报告**。
3. **模式只能升级不能降级**：窄 → 深可直接升级；深 → 窄必须用户开口。
4. **批次运行期间禁止改动 `../invest-kb/04_stock-analysis-expert/`（专家面板目录）**。`prepare_prompts.py` 把 `wiki_hash = tree_hash(wiki_expert_root())` 绑进批次身份，绑的就是这个目录；`wiki/concepts/` 下的镜像是生成物、由维护流程重建，**不影响**批次。契约与面板改动只在**批次之间**做。
5. **两个标识分开记**：报告与 manifest 只带数据包 `batch_id`（skill 冻结契约）；任务批次号只写编排台账 `batches/<批次号>/batch.json`，**不进报告结构**。
6. **编排方无结论权**：报告由 `assemble_report.py` 生成，不得手写；发布前必须经投研复核签字。
7. **工具链中止的重试规则（用户在 2026-10-14 授权）**：同一标的在执行中因**编排/工具链**原因中止（如规则未注入、自检输入格式错误、脚本缺陷等，**非**契约变更、**非**范围变更）时，可直接重新 prepare 新批次重试，**最多 3 次无需重复向用户申请许可**。每 3 次之后的继续重试、以及任何契约/面板变更、标的或模式范围的变更，仍需用户明确批准。每次中止都要在台账保留记录并写明原因，且**不得复用**中止批次的 staging 产物。


## 提交前自检（编排方执行，专家无 shell）

专家 subagent 只读自己那份 prompt、禁止 shell，**跑不了脚本**。所以自检由**编排方**在 `commit` 之前执行。注意 staged 文件是 **v3 结果 JSON**（正文用 `{{F001}}` 占位，数值在渲染时才出现），**不能直接扫 JSON**，必须两步走：

```bash
# 第一步：skill 自带校验 + 渲染（校验不过即停，通常轮不到第二步）
python3 scripts/expert_result_v3.py compile <code> <expert> <staged.next> \
    --sidecar /tmp/check.v3.json --markdown /tmp/check.md

# 第二步：扫渲染文本里的未溯源数字
python3 04_stock-analysis-expert/tools/attribution_check.py /tmp/check.md
```

- 第一步退出码非 0（裸阿拉伯数字、token 合同、calc 复算、必检项覆盖等）→ 按 skill 既有 repair 流程交回该专家，**不得手改产物**
- 第二步退出码 `0` 才允许 `commit`；不为 `0` 同样走 repair
- **不得为了让校验通过而删证据或把数字改成模糊表述**
- 顺序：`begin` → 子代理产出 → 两步自检 → `commit` → `advance`

验收记录（2026-10-14，真实产物）：
- 正向：`-05` 的 2 份真实 staged `.next` → 第一步 COMPILED → 第二步 **0 未溯源**；更早在 6 份门禁通过产出的渲染文本上同样 0 误报
- 反向：在必检项里注入裸数字 `3.5 次` → 第一步即拒绝（`prose token 合同错误 … 含裸阿拉伯数字`），退出码 2
- 防呆：直接把 staged JSON 喂给第二步会以退出码 2 拒绝，并打印正确两步流程

注入说明（重要）：专家 prompt 里**只有专家页正文**是无条件嵌入的（`prepare_prompts.py` 第 1136 行 `{method_text}`）；`_panel.md` 与 `_schema.md` 走 `{sage_context or supp}` 通道（第 1146 行），**sage 有上下文时会被挤掉、不进 prompt**。因此凡是要让专家看到的规则，必须写进 `experts/0*.md` 专家页，而不是只写 `_schema.md`。


