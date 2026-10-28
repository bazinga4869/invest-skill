#!/usr/bin/env python3
"""prewarm_corpus.py — 夜间批量预热 report-wiki 年报语料（离线，无 3600s 上限）。

生产阻塞根因：daily 抽到的新股票首次 materialize 需 1-4h（巨潮下载 + Sage
编译数百篇知识页），prepare 的 3600s 上限必然超时。本脚本在次日 02:00 分析前
把"次日选股 + 历史残留未完成公司 + watchlist"的 materialize 串行跑完（避开
LLM 挤压），使 daily 分析的 prepare 走 _try_reuse 快路径（秒级）。

断点续跑：raw/evidence 确定性可复用；Sage 编译 checkpoint 在 wiki.db 中，
超时只杀父进程，孤儿 compile 继续推进，下一晚自动续跑（幂等）。

用法：
  python3 scripts/prewarm_corpus.py [--date YYYYMMDD] [--count N]
      [--per-stock-minutes M] [--watchlist-timeout-minutes M]
      [--skip-watchlist] [--stale-limit N] [--deadline-hour H] [--dry-run]

退出码：0（单家失败不阻塞其余；状态写入日志与 stdout JSON）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from shared.project_config import (  # noqa: E402
    configured_path, project_config, report_wiki_cli, report_wiki_repo,
    runtime_root,
)
from shared.report_wiki import listing_aware_years  # noqa: E402


def _log_line(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _materialize_one(
    cli: Path, project: Path, code: str, as_of: datetime.date, years: int,
    output: Path, per_stock_seconds: int,
) -> dict:
    """单家公司 materialize；返回结构化结果（不抛异常）。"""
    materialized = output.with_name(
        f".prewarm.{code}.{os.getpid()}.bundle.json"
    )
    materialized.unlink(missing_ok=True)
    command = [
        str(cli), "materialize", "--code", code,
        "--as-of", as_of.strftime("%Y%m%d"), "--years", str(years),
        "--report-types", "annual", "--output", str(materialized),
    ]
    started = datetime.datetime.now()
    try:
        result = subprocess.run(
            command, cwd=str(project), capture_output=True, text=True,
            timeout=per_stock_seconds, check=False,
        )
    except subprocess.TimeoutExpired:
        # 父进程被杀，孤儿 sage-wiki compile 继续推进；下一晚自动续跑
        return {"code": code, "status": "TIMEOUT",
                "seconds": per_stock_seconds,
                "detail": f"materialize 超时（{per_stock_seconds}s），孤儿 compile 将继续推进"}
    finally:
        materialized.unlink(missing_ok=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-800:]
        return {"code": code, "status": "FAIL", "exit": result.returncode,
                "detail": detail}
    try:
        summary = json.loads(result.stdout)
    except json.JSONDecodeError:
        summary = {"status": "FAIL",
                   "detail": "materialize stdout 无法解析: " +
                             result.stdout.strip()[-400:]}
    summary.setdefault("code", code)
    summary["seconds"] = (datetime.datetime.now() - started).total_seconds()
    return summary


def _stale_incomplete(companies_root: Path, limit: int) -> list[str]:
    """raw 已存在但 last_bundle 未 PASS（未发布 bundle）的公司，按最近活动排序。

    这些公司是断点续跑对象：下载/证据可能已完成，仅剩 Sage 编译。
    """
    found: list[tuple[float, str]] = []
    if not companies_root.is_dir():
        return []
    for company_dir in sorted(companies_root.iterdir()):
        if not company_dir.is_dir() or company_dir.name.startswith("."):
            continue
        manifest_path = company_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        last_bundle = manifest.get("last_bundle") or {}
        if last_bundle:
            export = company_dir / "exports" / f"{last_bundle.get('bundle_hash')}.json"
            if export.is_file():
                continue  # 已发布 bundle → 就绪
        raws = list((company_dir / "raw" / "annual").glob("*/report.pdf"))
        if not raws:
            continue
        mtime = manifest_path.stat().st_mtime
        found.append((mtime, company_dir.name))
    found.sort(reverse=True)
    return [code for _mtime, code in found[:limit]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="", help="分析日期 YYYYMMDD，缺省明天")
    parser.add_argument("--count", type=int, default=3, help="预热明日选股数量")
    parser.add_argument("--per-stock-minutes", type=int, default=150)
    parser.add_argument("--watchlist-timeout-minutes", type=int, default=300)
    parser.add_argument("--skip-watchlist", action="store_true")
    parser.add_argument("--stale-limit", type=int, default=2,
                        help="同时续跑的历史未完成公司数上限")
    parser.add_argument("--deadline-hour", type=int, default=1,
                        help="超过该时刻（次日凌晨）不再启动新目标")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    config = project_config()
    cfg_report = config.get("report_wiki", {})
    cli = report_wiki_cli()
    project = report_wiki_repo()
    if not cli.is_file() or not os.access(cli, os.X_OK):
        print(f"ERROR: report-wiki CLI 不可用: {cli}", file=sys.stderr)
        return 2
    runtime = runtime_root()
    log_dir = Path(os.environ.get(
        "INVEST_LOG_DIR", str(Path(runtime) / "logs"),
    ))
    companies_root = project / str(config.get("companies_root", "companies"))

    if args.date:
        try:
            as_of = datetime.datetime.strptime(args.date, "%Y%m%d").date()
        except ValueError:
            print(f"ERROR: --date 非法: {args.date}", file=sys.stderr)
            return 2
    else:
        as_of = datetime.date.today() + datetime.timedelta(days=1)
    seed = as_of.strftime("%Y%m%d")
    log_file = log_dir / f"prewarm_{seed}.log"
    per_stock_seconds = args.per_stock_minutes * 60

    # 1) 明日选股（与 02:00 daily_analysis 同 seed 同口径）
    sys.path.insert(0, str(SKILL_ROOT / "scripts"))
    from pick_stocks import pick  # noqa: E402
    picks = pick(args.count, seed)
    targets: list[tuple[str, str]] = [(code, "pick") for code, _name in picks]
    # 2) 历史残留未完成公司（断点续跑）
    stale = _stale_incomplete(companies_root, args.stale_limit)
    targets.extend((code, "stale") for code in stale)

    results: list[dict] = []
    _log_line(log_file, {"event": "start", "as_of": seed,
                         "targets": targets, "stale": stale})
    if args.dry_run:
        print(json.dumps({
            "as_of": seed, "picks": [c for c, _t in targets if _t == "pick"],
            "stale": stale, "watchlist": "skipped" if args.skip_watchlist else "pending",
        }, ensure_ascii=False, indent=2))
        return 0

    deadline = datetime.datetime.combine(
        as_of, datetime.time(args.deadline_hour, 30),
    )
    for code, kind in targets:
        now = datetime.datetime.now()
        if now >= deadline:
            results.append({"code": code, "kind": kind, "status": "SKIPPED",
                            "detail": f"超过截止时间 {deadline:%H:%M}，不再启动"})
            _log_line(log_file, results[-1])
            print(f"[{now:%H:%M}] ✗ {code} ({kind}) 跳过：超过截止时间")
            continue
        years = listing_aware_years(code, as_of, int(cfg_report.get("history_years", 5)))
        output = Path(runtime) / f".prewarm_{code}.{os.getpid()}.bundle.json"
        print(f"[{now:%H:%M}] ┌─ {code} ({kind}) years={years} …", flush=True)
        try:
            summary = _materialize_one(
                cli, project, code, as_of, years, output, per_stock_seconds,
            )
        finally:
            output.unlink(missing_ok=True)
        summary["kind"] = kind
        results.append(summary)
        _log_line(log_file, summary)
        status = summary.get("status", "FAIL")
        mark = "✓" if status == "PASS" else ("⏳" if status == "TIMEOUT" else "✗")
        print(f"[{datetime.datetime.now():%H:%M}] {mark} {code}: {status} "
              f"({summary.get('seconds', '?')}s)", flush=True)

    if not args.skip_watchlist:
        print("[prewarm] 同步 watchlist …", flush=True)
        try:
            wl = subprocess.run(
                [str(cli), "sync-watchlist", "--format", "json"],
                cwd=str(project), capture_output=True, text=True,
                timeout=args.watchlist_timeout_minutes * 60, check=False,
            )
            wl_payload = {
                "kind": "watchlist", "exit": wl.returncode,
                "detail": (wl.stderr or wl.stdout).strip()[-800:],
            }
            try:
                wl_payload["summary"] = json.loads(wl.stdout)
            except json.JSONDecodeError:
                pass
        except subprocess.TimeoutExpired:
            wl_payload = {"kind": "watchlist", "status": "TIMEOUT",
                          "detail": "watchlist 同步超时（孤儿 compile 将继续）"}
        results.append(wl_payload)
        _log_line(log_file, wl_payload)

    summary = {
        "as_of": seed,
        "status": "PASS",
        "results": [
            {"code": r.get("code"), "kind": r.get("kind"),
             "status": r.get("status"), "seconds": r.get("seconds")}
            for r in results
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"日志: {log_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
