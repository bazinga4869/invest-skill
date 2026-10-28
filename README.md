# invest-skill

基于 invest-sage Sage Wiki 知识检索构建的独立投研工具集。

**重要**：本项目与 invest-sage、invest-report-wiki 是独立项目。数据库、报告输出均存放在本项目目录下，不混入知识库内容区。

## 项目关系

```
/home/bazinga/
├── invest-sage/          # Sage Wiki 投资知识库
│   ├── 10_meta/公司综合分析 Skill.md
│   ├── 10_meta/Wiki-Skill 联动规范.md
│   └── ...
├── invest-report-wiki/   # 公司财报原件、逐页证据与本地 FTS/BM25（Sage 摘要可选）
└── invest-skill/         # 本工程：结构化数据管道 + 分析 skill
    ├── SKILL.md           # Skill 定义（分析协议、专家团架构）
    ├── shared/            # 数据获取工具
    ├── config.yaml        # 与 wiki 的显式契约
    ├── schema.sql         # 自包含的数据库 schema
    ├── data/              # SQLite 数据库（gitignore）
    └── reports/           # 综合报告输出（gitignore）
```

## 快速开始

```bash
cd /home/bazinga/invest-skill

# 安装依赖
pip install -r requirements.txt

# 设置 Tushare token（推荐写入 shell 配置文件持久化）
export TUSHARE_TOKEN="your_token"

# 或者使用 .env 文件（已加入 .gitignore）
cp .env.example .env
# 编辑 .env，填入真实 token

# 使用 DSH 分析（通过 SKILL.md 定义的协议）
# 在 DSH Web GUI 中让 agent 加载 invest-skill 后说"分析 贵州茅台"即可；
# 定时分析由宿主 invest-harness 调度（crontab → scripts/cron/cron_daily_analysis.sh → 本工程执行器）
```

### Token 配置说明

- **推荐**：把 `export TUSHARE_TOKEN=...` 写入 `~/.bashrc` 或 `~/.zshrc`，这样所有终端会话都可用
- **临时**：当前终端直接 `export TUSHARE_TOKEN=...`
- **项目级**：复制 `.env.example` 为 `.env` 并填写 token（注意：`.env` 已在 `.gitignore` 中，不会提交）

**切勿把真实 token 写入 `config.yaml` 或任何会被 git 追踪的文件。**

## 核心设计

1. **显式依赖**：数据库、报告目录和 wiki 根路径由 `config.yaml` 统一解析
2. **自包含**：`schema.sql`、`config.yaml`、数据目录、报告目录都在本项目中
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

通用投资知识通过 `sage-wiki query --scope local --project /home/bazinga/invest-sage --format json`
检索；专家角色和机器门禁仍属于本 skill 的执行契约。

核心原则：
- wiki 变更方法论页面时，需检查本 skill 是否需要同步更新
- skill 运行前校验 wiki 依赖，缺失时告警
- 任何一方变更契约（config.yaml、schema.sql、评分阈值），需在另一方留下记录
