# invest-skill

基于 invest-wiki 方法论构建的独立投研工具集。

**重要**：本项目与 invest-wiki 是**两个独立项目**。数据库、报告输出均存放在本项目目录下，不混入 wiki 内容区。

## 项目关系

```
/home/bazinga/
├── invest-wiki/          # 知识库（LLM 维护的 Obsidian wiki）
│   ├── 10_meta/公司综合分析 Skill.md
│   ├── 10_meta/Wiki-Skill 联动规范.md
│   └── ...
└── invest-skill/         # 本工程：数据管道 + 分析 skill
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

# 使用 Claude Code 分析（通过 SKILL.md 定义的协议）
# 在项目目录下直接说"分析 贵州茅台"即可
```

### Token 配置说明

- **推荐**：把 `export TUSHARE_TOKEN=...` 写入 `~/.bashrc` 或 `~/.zshrc`，这样所有终端会话都可用
- **临时**：当前终端直接 `export TUSHARE_TOKEN=...`
- **项目级**：复制 `.env.example` 为 `.env` 并填写 token（注意：`.env` 已在 `.gitignore` 中，不会提交）

**切勿把真实 token 写入 `config.yaml` 或任何会被 git 追踪的文件。**

## 核心设计

1. **解耦**：不依赖 wiki 内部文件路径，通过 `config.yaml` 声明 wiki 依赖和方法论引用
2. **自包含**：`schema.sql`、`config.yaml`、数据目录、报告目录都在本项目中
3. **数据源抽象**：`shared/data_source.py` 实现 Tushare 主源 + AKShare 备用源，主源失败自动回退
4. **联动检查**：运行前校验 wiki 依赖页面是否存在；变更时生成 `data/wiki_drift_report.json`
5. **可量化**：6 维度 0~100 打分，输出明确评级

## 数据源

- **主源**：Tushare Pro（需要 `TUSHARE_TOKEN`）
- **备用源**：AKShare（免费，无需 token）
- **策略**：每次请求先走 Tushare；若失败或返回空，自动切换到 AKShare
- 所有数据统一清洗为 Tushare 风格列名，下游无感

详见 invest-wiki 中的 [[Wiki-Skill 联动规范]]。

核心原则：
- wiki 变更方法论页面时，需检查本 skill 是否需要同步更新
- skill 运行前校验 wiki 依赖，缺失时告警
- 任何一方变更契约（config.yaml、schema.sql、评分阈值），需在另一方留下记录
