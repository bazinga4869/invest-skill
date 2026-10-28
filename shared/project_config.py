"""Small, dependency-light accessors for project paths in config.yaml.

路径分层：
- SKILL_ROOT：skill 资产根（协议、脚本、静态契约 data/experts.json 等），随仓库走。
- runtime_root()：运行时根（DB、日志、报告、状态文件）。优先级：
  1. 环境变量 INVEST_SKILL_HOME（调用方/宿主项目注入）
  2. config.yaml paths.runtime_root（绝对路径，可选）
  3. 回退 SKILL_ROOT（向后兼容；不推荐长期使用）
skill 被任意项目调用时，调用方应设置 INVEST_SKILL_HOME 指向自己的运行时目录，
保证过程文件与数据库不写入 skill 仓库。
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def project_config() -> dict:
    value = yaml.safe_load((SKILL_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError("config.yaml 顶层必须是对象")
    return value


def runtime_root() -> Path:
    """运行时根：DB/日志/报告/状态文件的基目录（见模块 docstring）。"""
    env = os.environ.get("INVEST_SKILL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    configured = project_config().get("paths", {}).get("runtime_root")
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return SKILL_ROOT


def _resolve(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def configured_path(key: str, default: str, base: str = "runtime") -> Path:
    """解析 config.yaml paths.<key>。

    base="runtime"（默认）：相对路径基于运行时根（data/logs/reports 等可变产物）；
    base="skill"：相对路径基于 SKILL_ROOT（schema.sql 等资产）。
    """
    value = project_config().get("paths", {}).get(key, default)
    return _resolve(str(value), runtime_root() if base == "runtime" else SKILL_ROOT)


def wiki_repo() -> Path:
    value = project_config().get("wiki_dependencies", {}).get("repo_path", "../invest-wiki")
    return _resolve(str(value), SKILL_ROOT)


def legacy_wiki_repo() -> Path:
    value = project_config().get("wiki_dependencies", {}).get(
        "legacy_contract_repo_path", "../invest-wiki"
    )
    return _resolve(str(value), SKILL_ROOT)


def sage_wiki_repo() -> Path:
    value = project_config().get("wiki_dependencies", {}).get(
        "repo_path", "../invest-sage"
    )
    return _resolve(str(value), SKILL_ROOT)


def wiki_expert_root() -> Path:
    panel = project_config().get("wiki_dependencies", {}).get("expert_panel", {})
    configured_root = wiki_repo() / str(panel.get("base_path", "04_stock-analysis-expert"))
    if configured_root.is_dir():
        return configured_root
    # Sage Wiki is the knowledge source, but the expert/checklist/adjudicator
    # operational contract is still a local skill dependency until it is
    # represented as Sage entities.  Keep this compatibility root explicit.
    legacy_repo = legacy_wiki_repo()
    legacy_root = legacy_repo / "04_stock-analysis-expert"
    return legacy_root if legacy_root.is_dir() else configured_root


def report_wiki_repo() -> Path:
    value = project_config().get("report_wiki", {}).get(
        "repo_path", "../invest-report-wiki"
    )
    return _resolve(str(value), SKILL_ROOT)


def report_wiki_cli() -> Path:
    override = os.environ.get("INVEST_REPORT_WIKI_CLI")
    if override:
        return _resolve(override, SKILL_ROOT)
    value = project_config().get("report_wiki", {}).get(
        "cli_path", "../invest-report-wiki/bin/report-wiki"
    )
    return _resolve(str(value), SKILL_ROOT)
