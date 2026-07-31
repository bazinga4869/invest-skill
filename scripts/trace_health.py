#!/usr/bin/env python3
"""Trace 健康分析器 — 读取日志目录，输出流程健康报告。

用法：
    python3 scripts/trace_health.py                    # 汇总所有分析的健康状况
    python3 scripts/trace_health.py --code 603605.SH   # 只看某只股票
    python3 scripts/trace_health.py --days 7           # 只看最近 N 天
    python3 scripts/trace_health.py --failing           # 只看异常
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = SKILL_ROOT / "logs" / "trace"


def load_traces(days: int = None, code: str = None):
    """加载所有 trace 文件，返回事件列表。"""
    events = []
    if not TRACE_DIR.exists():
        return events

    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for f in sorted(TRACE_DIR.glob("*.jsonl")):
        if code and not f.name.startswith(code):
            continue
        try:
            for line in f.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                    if cutoff:
                        ts = ev.get("ts", "")
                        try:
                            et = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if et < cutoff:
                                continue
                        except Exception:
                            pass
                    events.append(ev)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
    return events


def analyze(events: list) -> dict:
    """分析事件列表，返回统计。"""
    if not events:
        return {"error": "无 trace 数据"}

    # 按 phase 聚合
    phases = defaultdict(lambda: {"total": 0, "ok": 0, "error": 0, "timeout": 0, "crash": 0,
                                   "durations": [], "codes": set()})
    experts = defaultdict(lambda: {"total": 0, "ok": 0, "error": 0, "durations": []})
    codes = set()
    all_durations = []

    for ev in events:
        phase = ev.get("phase", "unknown")
        status = ev.get("status", "unknown")
        code = ev.get("code", "")
        expert_id = ev.get("expert_id", "")
        dur = ev.get("duration_ms")

        if code:
            codes.add(code)

        if status != "start":
            phases[phase]["total"] += 1
            phases[phase]["codes"].add(code)
            if dur and isinstance(dur, (int, float)):
                phases[phase]["durations"].append(dur)
                all_durations.append(dur)

        if status == "ok":
            phases[phase]["ok"] += 1
            if expert_id:
                experts[expert_id]["ok"] += 1
                experts[expert_id]["total"] += 1
                if dur and isinstance(dur, (int, float)):
                    experts[expert_id]["durations"].append(dur)
        elif status == "error":
            phases[phase]["error"] += 1
            if expert_id:
                experts[expert_id]["error"] += 1
                experts[expert_id]["total"] += 1
        elif status in ("timeout", "crash"):
            phases[phase][status] += 1
            if expert_id:
                experts[expert_id]["total"] += 1

    return {
        "total_events": len([e for e in events if e.get("status") != "start"]),
        "unique_codes": sorted(codes),
        "phases": dict(phases),
        "experts": dict(experts),
    }


def print_health(stats: dict, show_failing_only: bool = False):
    if "error" in stats:
        print(stats["error"])
        return

    print(f"\n{'='*60}")
    print(f"  Trace 健康报告")
    print(f"  分析数: {len(stats['unique_codes'])} 只股票 | 事件: {stats['total_events']}")
    print(f"{'='*60}")

    # 阶段汇总
    print(f"\n{'阶段':<15s} {'总计':>5s} {'通过':>5s} {'失败':>5s} {'超时':>5s} {'通过率':>7s} {'平均耗时':>10s}")
    print("-" * 60)
    for phase in ["sync", "prompt", "expert", "adjudicate", "report", "review"]:
        p = stats["phases"].get(phase)
        if not p:
            continue
        if show_failing_only and p["error"] == 0 and p.get("timeout", 0) == 0:
            continue
        total = p["total"]
        ok = p["ok"]
        err = p["error"]
        to = p.get("timeout", 0)
        rate = f"{ok/total*100:.0f}%" if total > 0 else "N/A"
        avg_dur = f"{sum(p['durations'])/len(p['durations'])/1000:.1f}s" if p['durations'] else "N/A"
        print(f"{phase:<15s} {total:>5d} {ok:>5d} {err:>5d} {to:>5d} {rate:>7s} {avg_dur:>10s}")

    # 专家汇总
    if stats["experts"]:
        print(f"\n{'专家':<25s} {'次数':>5s} {'通过':>5s} {'失败':>5s} {'通过率':>7s} {'平均耗时':>10s}")
        print("-" * 60)
        for eid in sorted(stats["experts"]):
            e = stats["experts"][eid]
            if show_failing_only and e["error"] == 0:
                continue
            total = e["total"]
            ok = e["ok"]
            err = e["error"]
            rate = f"{ok/total*100:.0f}%" if total > 0 else "N/A"
            avg_dur = f"{sum(e['durations'])/len(e['durations'])/1000:.1f}s" if e['durations'] else "N/A"
            print(f"{eid:<25s} {total:>5d} {ok:>5d} {err:>5d} {rate:>7s} {avg_dur:>10s}")

    # 最近异常
    print(f"\n{'='*60}")
    print("  最近异常事件（最多 5 条）：")
    found = 0
    for f in sorted(TRACE_DIR.glob("*.jsonl"), reverse=True):
        if found >= 5:
            break
        for line in f.read_text(encoding="utf-8").strip().split("\n"):
            if found >= 5:
                break
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
                if ev.get("status") in ("error", "timeout", "crash"):
                    phase = ev.get("phase", "?")
                    code = ev.get("code", "?")
                    msg = ev.get("msg", ev.get("stderr_tail", ev.get("error", "")))[:80]
                    print(f"  ⚠ {code} [{phase}] {msg}")
                    found += 1
            except Exception:
                pass
    if found == 0:
        print("  （无异常）")
    print(f"{'='*60}\n")


def main():
    p = argparse.ArgumentParser(description="Trace 健康分析器")
    p.add_argument("--code", help="只看某只股票")
    p.add_argument("--days", type=int, help="只看最近 N 天")
    p.add_argument("--failing", action="store_true", help="只看异常")
    args = p.parse_args()

    events = load_traces(days=args.days, code=args.code)
    stats = analyze(events)
    print_health(stats, show_failing_only=args.failing)


if __name__ == "__main__":
    main()
