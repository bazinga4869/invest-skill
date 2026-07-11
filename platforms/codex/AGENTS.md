# Codex 入口

这是 Codex 的薄入口文件。完整 skill 说明见 [../SKILL.md](../SKILL.md)。

## Codex 专有说明

Codex 按 SKILL.md 定义的角色切换协议执行。不依赖子进程 spawn（Codex 不支持嵌套 `codex exec`）。

执行前确保 Codex 已安装 llm-wiki skill（`~/.codex/skills/llm-wiki/`），以支持 wiki 知识预取。
