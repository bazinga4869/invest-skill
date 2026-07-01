# CLAUDE.md — invest-skill

本文件为 Claude Code / 其他 AI Agent 提供 invest-skill 项目的协作规范。

## 项目定位

invest-skill 是基于 invest-wiki 方法论的**独立工程仓库**，负责：
- 本地投研数据库维护
- 量化筛选与分析 skill
- 综合报告生成

**它不是 wiki 的一部分**。数据库、报告、代码均存放在本项目内，不向 invest-wiki 写入内容。

## 与 invest-wiki 的关系

- **知识来源**：invest-wiki 是方法论来源（如 综合报告编写规范、价值投资框架）
- **显式契约**：`config.yaml` 中声明了所有 wiki 依赖页面
- **联动检查**：`analyze_company.py` 运行前会校验这些 wiki 页面是否存在
- **双向感知**：
  - 修改 invest-wiki 的方法论页面后，应检查 invest-skill 是否需要同步
  - 修改 invest-skill 的评分逻辑/报告结构后，应检查是否与 wiki 方法论冲突

## 目录规范

| 目录 | 用途 |
|------|------|
| `company-analysis/` | 单公司分析 skill |
| `shared/` | 公共工具模块 |
| `tests/` | 测试 |
| `data/` | SQLite 数据库与 drift 报告（gitignore） |
| `reports/` | 综合报告输出（gitignore） |

## 修改 checklist

每次修改本 skill 后：

1. 检查 `config.yaml` 中的 `wiki_dependencies` 是否仍准确
2. 若修改了评分逻辑或报告结构，检查 invest-wiki 中对应方法论页面是否需要同步更新
3. 在 `data/wiki_drift_report.json` 中无未处理 drift 时再发布
4. 更新本 README.md 与 `company-analysis/README.md`

## 跨项目协调

invest-wiki 中的协调入口：
- [[Wiki-Skill 联动规范]]
- [[公司综合分析 Skill]]
- `10_meta/shared-memory.md`

修改 invest-skill 前，建议先读取 invest-wiki 的上述页面。
