# Claude Code 入口

这是 Claude Code 的薄入口文件。完整 skill 说明见 [../SKILL.md](../SKILL.md)。

## Claude 专有说明

Claude Code 执行 invest-skill 时，按 SKILL.md 定义的角色切换协议依次执行 7 位专家分析。

如果 Claude Code 支持 `claude --bare -p` 并行 spawn，可将角色切换优化为并行模式（同样输出到 `/tmp/invest_result_*` 文件），由裁判长统一裁决。但 SKILL.md 中的角色切换协议是**默认且必须可用**的模式。

`~/.claude/skills/` 下需安装 llm-wiki skill 以支持 wiki 知识预取。
