#!/usr/bin/env python3
"""评分校准工具：读取当前专家评分 + 历史基线，输出 z-score 归一化表。

用法：
    python3 scripts/calibrate_scores.py 603605.SH
    python3 scripts/calibrate_scores.py 603605.SH --json

历史数据来源：logs/activity.jsonl 中 phase="expert" 的记录。
基线要求：每专家至少 5 次历史评分才计算均值/标准差，否则标注「样本不足」。
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]

# 专家列表
EXPERTS_DATA = json.loads((SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8"))
EXPERTS = [e["id"] for e in EXPERTS_DATA["experts"]]


def parse_frontmatter(text: str) -> dict:
    """从专家结果文件中提取 frontmatter。"""
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if m:
        try:
            import yaml
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass
    return {}


def get_current_scores(ts_code: str) -> dict:
    """从 /tmp/invest_result_*.md 读取本次各专家评分。"""
    scores = {}
    for eid in EXPERTS:
        p = Path(f"/tmp/invest_result_{ts_code}_{eid}.md")
        if p.exists():
            fm = parse_frontmatter(p.read_text(encoding="utf-8"))
            s = fm.get("score")
            scores[eid] = s if isinstance(s, int) and 0 <= s <= 100 else None
        else:
            scores[eid] = None
    return scores


def get_historical_baselines() -> dict:
    """从 activity log 读取历史专家评分，计算每专家均值/标准差。"""
    log_path = SKILL_ROOT / "logs" / "activity.jsonl"
    history = {eid: [] for eid in EXPERTS}
    if not log_path.exists():
        return {eid: {"n": 0} for eid in EXPERTS}

    for line in log_path.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("phase") != "expert":
            continue
        eid = rec.get("expert_id", "")
        sc = rec.get("score")
        if eid in history and isinstance(sc, (int, float)):
            history[eid].append(float(sc))

    baselines = {}
    for eid in EXPERTS:
        h = history[eid]
        if len(h) >= 5:
            baselines[eid] = {
                "n": len(h),
                "mean": round(statistics.mean(h), 1),
                "std": round(statistics.stdev(h), 1),
            }
        else:
            baselines[eid] = {"n": len(h), "mean": None, "std": None}
    return baselines


def main():
    parser = argparse.ArgumentParser(description="评分校准：z-score 归一化")
    parser.add_argument("ts_code", help="股票代码")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    scores = get_current_scores(args.ts_code)
    baselines = get_historical_baselines()

    result = {"ts_code": args.ts_code, "experts": {}}
    for eid in EXPERTS:
        s = scores.get(eid)
        b = baselines.get(eid, {})
        mean = b.get("mean")
        std = b.get("std")
        n = b.get("n", 0)

        z = None
        if s is not None and mean is not None and std is not None and std > 0:
            z = round((s - mean) / std, 2)

        result["experts"][eid] = {
            "score": s,
            "baseline_n": n,
            "baseline_mean": mean,
            "baseline_std": std,
            "z_score": z,
        }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 表格输出
    print(f"\n评分校准 — {args.ts_code}")
    print(f"{'专家':<22s} {'当前分':>6s}  {'历史均值':>8s}  {'标准差':>6s}  {'z-score':>7s}  {'判定':>6s}")
    print("-" * 70)
    for eid in EXPERTS:
        r = result["experts"][eid]
        s = r["score"]
        mean = r["baseline_mean"]
        std = r["baseline_std"]
        z = r["z_score"]
        n = r["baseline_n"]

        if s is None:
            print(f"{eid:<22s} {'N/A':>6s}")
            continue

        if z is not None:
            z_str = f"{z:+.2f}"
            tag = "↑偏高" if z > 1.5 else ("↓偏低" if z < -1.5 else "正常")
        else:
            z_str = "N/A"
            if n < 5:
                tag = f"样本不足({n})"
            else:
                tag = "无基线"

        print(f"{eid:<22s} {str(s):>6s}  "
              f"{str(mean) if mean is not None else 'N/A':>8s}  "
              f"{str(std) if std is not None else 'N/A':>6s}  "
              f"{z_str:>7s}  {tag:>6s}")

    print(f"\n> z-score > +1.5：评分显著高于该专家历史均值（可能过于乐观）")
    print(f"> z-score < -1.5：评分显著低于该专家历史均值（可能过于悲观）")
    print(f"> 样本要求：每专家 ≥ 5 次历史评分才计算基线\n")

    # 同时输出加权评分对比
    weights = {
        "financial-auditor": 0.25, "value-valuator": 0.25,
        "moat-analyst": 0.20, "growth-assessor": 0.10,
        "management-auditor": 0.10, "cognitive-controller": 0.05,
        "macro-cyclist": 0.05,
    }
    raw_total = 0
    cal_total = 0
    valid = 0
    for eid in EXPERTS:
        r = result["experts"][eid]
        s = r["score"]
        w = weights.get(eid, 0.10)
        if s is not None:
            raw_total += s * w
            valid += 1
            if r["z_score"] is not None:
                # 校准分 = 50 + z * 10（将 z-score 映射到 0-100 尺度）
                cal_score = max(0, min(100, 50 + r["z_score"] * 10))
                cal_total += cal_score * w
    if valid > 0:
        print(f"原始加权分：{raw_total:.1f}")
        if cal_total > 0:
            print(f"校准加权分：{cal_total:.1f}（仅对 z-score 可用的专家做校准）")


if __name__ == "__main__":
    main()
