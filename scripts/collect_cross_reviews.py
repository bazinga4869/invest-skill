#!/usr/bin/env python3
"""校验三份独立交叉盲审并生成可归档聚合原文。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))
from shared.contracts import normalize_ts_code
from shared.review_contracts import cross_prompt_hash

EXPERTS = [item["id"] for item in json.loads(
    (SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8")
)["experts"]]
CROSS_REVIEWERS = (
    "financial-auditor", "value-valuator", "cognitive-controller",
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def input_paths(code: str, base_dir: Path = Path("/tmp")) -> list[Path]:
    return [
        *[base_dir / f"invest_result_{code}_{expert}.md" for expert in EXPERTS],
        *[base_dir / f"invest_challenge_result_{code}_{expert}.md" for expert in EXPERTS],
        base_dir / f"invest_level3_{code}.json",
    ]


def input_bundle_hash(code: str, base_dir: Path = Path("/tmp")) -> str | None:
    paths = input_paths(code, base_dir)
    if not all(path.is_file() for path in paths):
        return None
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_cross_review(code: str, reviewer: str,
                          base_dir: Path = Path("/tmp")) -> list[str]:
    problems = []
    prompt_path = base_dir / f"invest_cross_prompt_{code}_{reviewer}.txt"
    result_path = base_dir / f"invest_cross_result_{code}_{reviewer}.md"
    data_path = base_dir / f"invest_data_{code}.json"
    if not all(path.is_file() for path in (prompt_path, result_path, data_path)):
        return ["交叉盲审 prompt/result/数据快照缺失"]
    prompt = prompt_path.read_bytes()
    text = result_path.read_text(encoding="utf-8")
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["数据快照不可读"]
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    try:
        fm = yaml.safe_load(match.group(1)) if match else {}
    except yaml.YAMLError:
        fm = {}
    expected = {
        "reviewer_id": reviewer,
        "ts_code": code,
        "data_date": str(data.get("market", {}).get("trade_date") or ""),
        "analysis_date": str(data.get("meta", {}).get("analysis_date") or ""),
        "batch_id": str(data.get("meta", {}).get("batch_id") or ""),
        "input_bundle_hash": str(input_bundle_hash(code, base_dir) or ""),
        "cross_prompt_hash": cross_prompt_hash(prompt),
    }
    for field, value in expected.items():
        if str((fm or {}).get(field) or "") != value:
            problems.append(f"{field} 不匹配")
    try:
        # 延迟导入，避免准备脚本在加载本收集模块时形成初始化环。
        from scripts.prepare_cross_reviews import expected_cross_prompt
        rebuilt = expected_cross_prompt(code, reviewer, base_dir).encode("utf-8")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        rebuilt = None
        problems.append(f"无法确定性重建交叉盲审 prompt: {exc}")
    if rebuilt is not None and prompt != rebuilt:
        problems.append("交叉盲审 prompt 与官方生成器确定性重建结果不一致")
    if (fm or {}).get("cross_verdict") not in {"CONFIRM", "DOWNGRADE", "ESCALATE"}:
        problems.append("cross_verdict 非法")
    if len(text.strip()) < 1000:
        problems.append(f"交叉盲审正文过短: {len(text.strip())} < 1000")
    for heading in ("## 遗漏与矛盾", "## 反事实压力测试", "## 对裁判长的影响"):
        if text.count(heading) != 1:
            problems.append(f"缺少或重复章节: {heading}")
    return problems


def build_aggregate(code: str, base_dir: Path = Path("/tmp")) -> str:
    data = json.loads((base_dir / f"invest_data_{code}.json").read_text(encoding="utf-8"))
    level3_path = base_dir / f"invest_level3_{code}.json"
    level3_hash = sha256_bytes(level3_path.read_bytes())
    bundle_hash = input_bundle_hash(code, base_dir)
    header = {
        "ts_code": code,
        "data_date": str(data.get("market", {}).get("trade_date") or ""),
        "analysis_date": str(data.get("meta", {}).get("analysis_date") or ""),
        "batch_id": str(data.get("meta", {}).get("batch_id") or ""),
        "input_bundle_hash": bundle_hash,
        "level3_hash": level3_hash,
        "reviewer_ids": list(CROSS_REVIEWERS),
    }
    parts = ["---\n" + yaml.safe_dump(header, allow_unicode=True, sort_keys=False).rstrip()
             + "\n---\n\n# 三方交叉盲审原文\n"]
    for reviewer in CROSS_REVIEWERS:
        result = (base_dir / f"invest_cross_result_{code}_{reviewer}.md").read_text(
            encoding="utf-8"
        )
        parts.append(f"\n## 盲审方：{reviewer}\n\n{result.rstrip()}\n")
    return "".join(parts)


def validate_cross_aggregate(code: str, base_dir: Path = Path("/tmp")) -> list[str]:
    problems = []
    aggregate = base_dir / f"invest_cross_blind_{code}.md"
    if not aggregate.is_file():
        return ["三方交叉盲审聚合原文缺失"]
    for reviewer in CROSS_REVIEWERS:
        problems.extend(
            f"{reviewer}: {problem}"
            for problem in validate_cross_review(code, reviewer, base_dir)
        )
    if problems:
        return problems
    expected = build_aggregate(code, base_dir)
    if aggregate.read_text(encoding="utf-8") != expected:
        problems.append("三方交叉盲审聚合原文与三份结果不一致")
    return problems


def write_durable(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.next")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ts_code")
    parser.add_argument("--failing", action="store_true")
    args = parser.parse_args()
    try:
        code = normalize_ts_code(args.ts_code)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    failing = []
    for reviewer in CROSS_REVIEWERS:
        problems = validate_cross_review(code, reviewer)
        if problems:
            failing.append(reviewer)
            if not args.failing:
                print(f"  ✗ {reviewer}: {'; '.join(problems)}")
        elif not args.failing:
            print(f"  ✓ {reviewer}")
    if args.failing:
        print("\n".join(failing))
    if failing:
        return 1
    aggregate_path = Path(f"/tmp/invest_cross_blind_{code}.md")
    write_durable(aggregate_path, build_aggregate(code))
    if not args.failing:
        print(f"✓ 三方交叉盲审已聚合: {aggregate_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
