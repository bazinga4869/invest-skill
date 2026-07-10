# CLAUDE.md — invest-skill 项目配置

> ⚠️ **本文件是项目工程配置，不是 skill 定义。Skill 定义在 `SKILL.md`。**

## Skill 入口

分析协议、专家团架构、spawn 命令模板等全部在 `SKILL.md` 中定义。本文件只包含项目基础设施配置。

## 双管道日报系统

invest-skill 是一个**双管道每日分析系统**的 Pipe A。每天分析 2 家公司，每家公司产出两份**完全独立**的报告：

```
每日 cron（10:00 / 14:30）
  │
  ├── Pipe A：invest-skill（本工程）
  │   ├── 触发：scripts/cron_trigger.sh → claude -p（独立新会话）
  │   ├── 数据源：Tushare → SQLite（data_tools.py）
  │   ├── 方法论：invest-wiki/04_stock-analysis-expert/ 7+1 专家团
  │   └── 报告：reports/invest_tool/<code>.md  （每公司一个文件）
  │
  └── Pipe B：ai-berkshire（独立工程 ~/ai-berkshire/）
      ├── 数据源：新浪财经（sina_finance.py）
      ├── 方法论：巴菲特-芒格-段永平-李录 四大师八步框架
      └── 报告：reports/ai_berkshire/<code>.md  （每公司一个文件，增量修订）
```

**关键约束**：
- 🚫 两份报告完全独立，不互相引用、不汇总、不交叉验证
- 🚫 invest-skill 不得使用新浪数据；ai-berkshire 不得使用 Tushare 数据
- 🚫 不得修改 ai-berkshire 的任何已有文件

### 自动分析 vs 手动分析

| | cron 自动分析 | 用户手动分析 |
|---|---|---|
| 触发方式 | `scripts/cron_trigger.sh` → `claude -p` | 用户对话中直接指令 |
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
| `data/` | SQLite 数据库 |
| `reports/` | 分析报告输出 |
| `config.yaml` | 项目配置 |

## Wiki 联动

专家团配置来自 `../invest-wiki/04_stock-analysis-expert/`。wiki 的 `_schema.md` 定义了自迭代机制：
- wiki 中专家依赖的知识页面发生结构性变更时，专家团按自迭代机制更新
- 每次分析前检查 `_cache.json` 中的 `expert_versions`，若版本落后超过 7 天，提示检查 wiki 更新
- 分析完成后，将可复用的通用洞见回流到 wiki 对应的案例库

## 跨管道对比迭代（第八步）

每次 Pipe A 分析完成后，自动触发 Pipe B（ai-berkshire）→ 四维对比 → 差距记录到 `data/improvement_candidates.json`。

#### 自动触发 Pipe B

```bash
TODAY=$(date +%Y-%m-%d)
CODE="<ts_code>"
NAME="<公司名>"
REPORT_B="reports/ai_berkshire/${CODE}.md"

if [ -f "$REPORT_B" ]; then
    echo "Pipe B 报告已存在，跳过生成"
else
    SHORT="${CODE%.*}"
    EXCH="${CODE##*.}"
    if [ "$EXCH" = "SH" ]; then SINA_CODE="SH${SHORT}"; else SINA_CODE="SZ${SHORT}"; fi

    cd ~/ai-berkshire
    claude --bare -p "
分析 ${NAME}（${CODE}，新浪代码 ${SINA_CODE}）。

**数据获取**：所有数据必须从 tools/sina_finance.py 获取。
  - python3 tools/sina_finance.py all ${SINA_CODE}

**分析要求**：按 ai-berkshire 四大师八步框架完成完整分析。

**输出**：报告保存到 ~/invest-skill/${REPORT_B}
" --permission-mode bypassPermissions --allowedTools "Read,Bash,Write,Edit" 2>&1 | tail -5
fi
```

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
       ├── target: wiki  → 修改 invest-wiki 专家文件或方法论页面
       └── target: data  → 扩展 data_tools.py 数据获取能力
       │
       ▼
人工定期 review → 落地 → 标记 resolved
       │
       ▼
下次分析时 skill 和 wiki 已进化 → 报告质量螺旋上升
```
