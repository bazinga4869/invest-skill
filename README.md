# invest-skill

面向 A 股公司的可审计投研工具集，包含结构化数据管道、分析 skill 和发布门禁。

**重要**：本仓库与知识库、财报语料仓库是独立项目。数据库、报告、日志、批次 prompt 和其他运行时产物不属于 skill 资产，也不应提交到本仓库。持久化数据/报告路径由 `config.yaml` 的 `paths.runtime_root` 配置，可由 `INVEST_SKILL_HOME` 覆盖；临时批次文件优先使用宿主设置的 `INVEST_RUNTIME_DIR`，其次使用 `INVEST_SKILL_HOME`。两者都未设置时，部分旧入口仍兼容回退到 `/tmp`；生产运行应由宿主 wrapper 显式配置私有运行时目录。

## 项目关系

```
workspace/
├── invest-kb/             # 投研知识库桥接仓
├── invest-report-wiki/    # 公司财报原件、逐页证据与本地 FTS5/BM25
├── invest-skill/          # 本仓库：数据管道 + 分析 skill
│   ├── SKILL.md            # 分析协议与专家团执行流程
│   ├── shared/             # 数据源、路径和证据契约
│   ├── scripts/            # 准备、执行、验证和发布入口
│   └── data/               # 版本化的静态契约文件
└── invest-skill-runtime/  # 配置的运行时目录；不在本仓库内
```

## 快速开始

```bash
cd /path/to/invest-skill

# 需要 Python 3.10 或更新版本
python3 --version

# 安装依赖
pip install -r requirements.txt

# 设置 Tushare token（推荐写入 shell 配置文件持久化）
export TUSHARE_TOKEN="your_token"

# 或者使用 .env 文件（已加入 .gitignore）
cp .env.example .env
# 编辑 .env，填入真实 token

# 使用 DSH 分析（通过 SKILL.md 定义的协议）
# 在 DSH Web GUI 中让 agent 加载 invest-skill 后说"分析 贵州茅台"即可；
# 定时分析由宿主 invest-harness 调度，其 wrapper 调用本仓库 scripts/cron_trigger.sh
```

### Token 配置说明

- **推荐**：把 `export TUSHARE_TOKEN=...` 写入 `~/.bashrc` 或 `~/.zshrc`，这样所有终端会话都可用
- **临时**：当前终端直接 `export TUSHARE_TOKEN=...`
- **项目级**：复制 `.env.example` 为 `.env` 并填写 token（注意：`.env` 已在 `.gitignore` 中，不会提交）

**切勿把真实 token 写入 `config.yaml` 或任何会被 git 追踪的文件。**

## 核心设计

1. **显式依赖**：数据库、报告目录和 wiki 根路径由 `config.yaml` 统一解析
2. **资产与运行时分离**：`schema.sql`、`config.yaml` 和版本化数据契约属于本项目；数据库、报告及其他运行时数据写入配置的运行时目录
3. **数据源抽象**：`shared/data_source.py` 实现 Tushare 主源 + AKShare 备用源，主源失败自动回退
4. **批次绑定**：数据、report-wiki bundle/corpus、年报视图、方法论 wiki 和 prompt 合并生成内容寻址 `batch_id`
5. **可审计**：7 个专业域 0~100 打分，由裁判长综合，完整证据和执行元数据进入 manifest
6. **同源子代理**：认知任务只用当前主 agent 的宿主原生子代理，省略 provider/model 覆盖；不自动调用或切换 Codex/Claude/DSH CLI

年报不由本工程临时抓取。`scripts/prepare_prompts.py` 调用
`../invest-report-wiki/bin/report-wiki materialize`：已有合格语料直接复用，缺少时
由 report-wiki 下载、建立逐页证据和本地 FTS5/BM25 索引；原件、页码或哈希门禁
失败会在专家启动前停止。Sage Wiki 只提供方法论上下文并按专家主题缓存，不参与年报证据准出。

## 数据源

- **主源**：Tushare Pro（需要 `TUSHARE_TOKEN`）
- **备用源**：AKShare（免费，无需 token）
- **策略**：每次请求先走 Tushare；若失败或返回空，自动切换到 AKShare
- 所有数据统一清洗为 Tushare 风格列名，下游无感

通用投资知识通过 `invest-kb` 提供的 MCP 服务或 `sage-wiki` shim 检索，路径与服务由宿主环境配置；不要在调用命令中硬编码工作区绝对路径。专家角色和机器门禁仍属于本 skill 的执行契约。

核心原则：
- wiki 变更方法论页面时，需检查本 skill 是否需要同步更新
- skill 运行前校验 wiki 依赖，缺失时告警
- 任何一方变更契约（config.yaml、schema.sql、评分阈值），需在另一方留下记录
