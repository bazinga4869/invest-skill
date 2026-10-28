"""Read-only invest-sage query adapter with per-expert validated caching."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from shared.project_config import project_config, runtime_root, sage_wiki_repo


CACHE_SCHEMA_VERSION = "invest-skill.sage-cache.v1"


class SageWikiError(RuntimeError):
    pass


@dataclass(frozen=True)
class SageHit:
    path: str
    content: str
    score: float


@dataclass(frozen=True)
class CachedContext:
    expert_id: str
    query: str
    content: str
    source_paths: tuple[str, ...]
    content_sha256: str
    model: str
    created_at: dt.datetime


def context_hash(contexts: dict[str, tuple[str, list[str]]]) -> str:
    digest = hashlib.sha256()
    for expert_id in sorted(contexts):
        text, paths = contexts[expert_id]
        digest.update(expert_id.encode())
        digest.update(b"\0")
        for path in paths:
            digest.update(path.encode())
            digest.update(b"\0")
        digest.update(text.encode())
        digest.update(b"\0")
    return digest.hexdigest()


_QUERIES = {
    "financial-auditor": "财务报表 现金流 盈利质量 审计 风险 会计",
    "value-valuator": "内在价值 安全边际 估值 现金流 折现率",
    "growth-assessor": "成长股 增长质量 ROIC 复投 市场空间",
    "moat-analyst": "护城河 竞争优势 品牌 转换成本 网络效应 成本优势",
    "cognitive-controller": "投资心理 认知偏误 管理层叙事 反事实 不确定性",
    "macro-cyclist": "经济周期 宏观经济 利率 通胀 政策 行业周期",
    "management-auditor": "管理层 公司治理 资本配置 股东回报 激励 诚信",
}


def _cli() -> str:
    """Resolve sage-wiki in minimal cron PATH environments."""
    value = os.environ.get("SAGE_WIKI_CLI")
    if value:
        return value
    found = shutil.which("sage-wiki")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "sage-wiki"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return "sage-wiki"


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env_file = Path.home() / ".config" / "invest-sage" / "runtime.env"
    if env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in env:
                env[key] = value
    return env


def _model_name(env: dict[str, str] | None = None) -> str:
    values = env or _runtime_env()
    for key in (
        "SAGE_WIKI_MODEL", "INVEST_SAGE_MODEL", "DEEPSEEK_MODEL",
        "ANTHROPIC_MODEL", "OPENAI_MODEL",
    ):
        if values.get(key):
            return values[key]
    return "configured-by-invest-sage"


def query(question: str) -> SageHit:
    if not question.strip():
        raise SageWikiError("Sage Wiki query 不能为空")
    cfg = project_config().get("wiki_dependencies", {})
    project = sage_wiki_repo()
    if not project.is_dir():
        raise SageWikiError(f"invest-sage 项目不存在: {project}")
    command = [
        _cli(), "query", question, "--scope", "local", "--project", str(project),
        "--format", "json",
    ]
    try:
        result = subprocess.run(
            command, cwd=str(project), capture_output=True, text=True,
            timeout=int(cfg.get("query_timeout_seconds", 300)), check=False,
            env=_runtime_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SageWikiError(f"Sage Wiki query 失败: {exc}") from exc
    if result.returncode != 0:
        raise SageWikiError(
            f"Sage Wiki query exit={result.returncode}: "
            f"{(result.stderr or result.stdout).strip()[-1000:]}"
        )
    content = result.stdout.strip()
    if not content:
        raise SageWikiError("Sage Wiki query 返回空内容")
    return SageHit(path="query:" + question, content=content, score=1.0)


def _cache_config() -> dict:
    value = project_config().get("wiki_dependencies", {}).get("cache", {})
    return value if isinstance(value, dict) else {}


def cache_root() -> Path:
    cfg = _cache_config()
    configured = Path(str(cfg.get("dir", "data/sage_wiki_cache"))).expanduser()
    root = configured if configured.is_absolute() else runtime_root() / configured
    resolved = root.resolve(strict=False)
    runtime = runtime_root().resolve(strict=False)
    try:
        resolved.relative_to(runtime)
    except ValueError as exc:
        raise SageWikiError(
            f"Sage cache 必须位于 INVEST_SKILL_HOME 运行时根内: {resolved}"
        ) from exc
    return resolved


def _cache_path(expert_id: str) -> Path:
    if expert_id not in _QUERIES:
        raise SageWikiError(f"未配置 Sage Wiki 查询主题: {expert_id}")
    return cache_root() / f"{expert_id}.json"


def _parse_datetime(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("created_at 缺失")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _load_cache(expert_id: str) -> CachedContext | None:
    path = _cache_path(expert_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cache 不是 JSON 对象")
        if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError("schema_version 不匹配")
        question = _QUERIES[expert_id]
        if payload.get("expert_id") != expert_id or payload.get("query") != question:
            raise ValueError("expert_id/query 不匹配")
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content 为空")
        content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if payload.get("content_sha256") != content_sha:
            raise ValueError("content_sha256 重算不一致")
        paths = payload.get("source_paths")
        if not isinstance(paths, list) or not paths or not all(
            isinstance(item, str) and item for item in paths
        ):
            raise ValueError("source_paths 非法")
        return CachedContext(
            expert_id=expert_id,
            query=question,
            content=content,
            source_paths=tuple(paths),
            content_sha256=content_sha,
            model=str(payload.get("model") or "unknown"),
            created_at=_parse_datetime(payload.get("created_at")),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # Invalid cache is never silently trusted; preserve the file for audit.
        raise SageWikiError(f"Sage cache 校验失败 {path}: {exc}") from exc


def _write_cache(
    expert_id: str,
    content: str,
    source_paths: list[str],
    *,
    model: str,
    now: dt.datetime,
) -> CachedContext:
    path = _cache_path(expert_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "expert_id": expert_id,
        "query": _QUERIES[expert_id],
        "model": model,
        "created_at": now.astimezone(dt.timezone.utc).isoformat(),
        "snapshot_date": now.astimezone(dt.timezone.utc).date().isoformat(),
        "source_paths": source_paths,
        "content_sha256": content_sha,
        "content": content,
    }
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return CachedContext(
        expert_id=expert_id,
        query=_QUERIES[expert_id],
        content=content,
        source_paths=tuple(source_paths),
        content_sha256=content_sha,
        model=model,
        created_at=now.astimezone(dt.timezone.utc),
    )


def _source_paths(content: str, question: str) -> list[str]:
    paths: list[str] = []
    for slug in re.findall(r"\[\[([^]|#]+)", content):
        slug = slug.strip()
        filename = slug if slug.endswith(".md") else slug + ".md"
        candidate = sage_wiki_repo() / "wiki" / "concepts" / filename
        if not candidate.is_file():
            matches = sorted(sage_wiki_repo().rglob(filename))
            candidate = matches[0] if matches else candidate
        if candidate.is_file():
            path = candidate.relative_to(sage_wiki_repo()).as_posix()
            if path not in paths:
                paths.append(path)
    if not paths:
        paths.append("query:" + question)
    return paths


def _format_context(hit: SageHit, max_chars: int) -> tuple[str, list[str]]:
    text = hit.content[:max_chars]
    paths = _source_paths(hit.content, hit.path.removeprefix("query:"))
    return f"\n## Sage Wiki 检索结果：{hit.path}\n{text}\n", paths


def _cache_age_days(cache: CachedContext, now: dt.datetime) -> float:
    return max(0.0, (now - cache.created_at).total_seconds() / 86400)


def _context_for_expert(
    expert_id: str,
    *,
    max_chars: int,
    now: dt.datetime,
) -> tuple[tuple[str, list[str]], dict]:
    question = _QUERIES.get(expert_id)
    if not question:
        raise SageWikiError(f"未配置 Sage Wiki 查询主题: {expert_id}")
    if os.environ.get("INVEST_TEST_MODE") == "1":
        text = (
            f"测试模式 Sage Wiki query fixture：{question}。"
            "仅用于验证任务书管线，不代表生产知识结果。"
        )
        paths = [
            "wiki/concepts/moat.md",
            "wiki/concepts/cash-flow-generating-assets.md",
            "wiki/concepts/economic-moat.md",
        ]
        return (text, paths), {
            "mode": "live", "snapshot_date": now.date().isoformat(),
            "model": "test-fixture",
            "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "error": None,
        }

    cfg = _cache_config()
    enabled = bool(cfg.get("enabled", True))
    fresh_days = int(cfg.get("fresh_days", 7))
    max_stale_days = int(cfg.get("max_stale_days", 90))
    allow_builtin = bool(cfg.get("allow_builtin_without_cache", False))
    cached: CachedContext | None = None
    cache_error: str | None = None
    if enabled:
        try:
            cached = _load_cache(expert_id)
        except SageWikiError as exc:
            cache_error = str(exc)
    if cached is not None and _cache_age_days(cached, now) <= fresh_days:
        return (cached.content[:max_chars], list(cached.source_paths)), {
            "mode": "cache", "snapshot_date": cached.created_at.date().isoformat(),
            "model": cached.model, "content_sha256": cached.content_sha256,
            "error": None,
        }

    try:
        hit = query(question)
        text, paths = _format_context(hit, max_chars)
        saved = _write_cache(
            expert_id, text, paths, model=_model_name(), now=now,
        ) if enabled else CachedContext(
            expert_id, question, text, tuple(paths),
            hashlib.sha256(text.encode()).hexdigest(), _model_name(), now,
        )
        return (text, paths), {
            "mode": "live", "snapshot_date": now.date().isoformat(),
            "model": saved.model, "content_sha256": saved.content_sha256,
            "error": cache_error,
        }
    except SageWikiError as live_error:
        if cached is not None and _cache_age_days(cached, now) <= max_stale_days:
            return (cached.content[:max_chars], list(cached.source_paths)), {
                "mode": "cache", "snapshot_date": cached.created_at.date().isoformat(),
                "model": cached.model, "content_sha256": cached.content_sha256,
                "error": str(live_error),
            }
        if allow_builtin:
            text = "Sage Wiki 当前不可用；仅使用 invest-skill 内置专家方法论。"
            return (text, []), {
                "mode": "builtin", "snapshot_date": now.date().isoformat(),
                "model": "builtin", "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "error": str(live_error),
            }
        detail = str(live_error)
        if cache_error:
            detail += f"；cache_error={cache_error}"
        if cached is not None:
            detail += (
                f"；最近 cache 已超过 max_stale_days={max_stale_days}"
            )
        else:
            detail += "；无通过校验的 cache"
        raise SageWikiError(f"{expert_id}: {detail}") from live_error


def collect_expert_contexts(
    expert_ids: list[str] | tuple[str, ...],
    *,
    max_chars: int = 24_000,
    now: dt.datetime | None = None,
) -> tuple[dict[str, tuple[str, list[str]]], dict]:
    """Load all expert topics independently and return contexts plus run status."""
    timestamp = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    contexts: dict[str, tuple[str, list[str]]] = {}
    topics: dict[str, dict] = {}
    failures: list[str] = []
    for expert_id in expert_ids:
        try:
            context, topic = _context_for_expert(
                expert_id, max_chars=max_chars, now=timestamp,
            )
        except SageWikiError as exc:
            failures.append(str(exc))
            topics[expert_id] = {
                "mode": "failed", "snapshot_date": None, "model": None,
                "content_sha256": None, "error": str(exc),
            }
            continue
        contexts[expert_id] = context
        topics[expert_id] = topic
    if failures:
        raise SageWikiError("；".join(failures))
    modes = {topic["mode"] for topic in topics.values()}
    if modes == {"live"}:
        status, mode = "OK", "live"
    elif modes == {"builtin"}:
        status, mode = "DEGRADED", "builtin"
    else:
        status, mode = "DEGRADED", "cache"
    dates = [
        str(topic.get("snapshot_date")) for topic in topics.values()
        if topic.get("snapshot_date")
    ]
    errors = [
        f"{expert_id}: {topic['error']}"
        for expert_id, topic in topics.items() if topic.get("error")
    ]
    return contexts, {
        "status": status,
        "mode": mode,
        "error": "；".join(errors) if errors else None,
        "snapshot_date": min(dates) if dates else timestamp.date().isoformat(),
        "topics": topics,
    }


def expert_context(
    expert_id: str,
    *,
    limit: int = 5,
    max_chars: int = 24_000,
) -> tuple[str, list[str]]:
    """Backward-compatible single-topic API, now backed by validated cache."""
    del limit  # The public query contract currently returns one aggregated result.
    contexts, _status = collect_expert_contexts([expert_id], max_chars=max_chars)
    return contexts[expert_id]
