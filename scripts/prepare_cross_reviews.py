#!/usr/bin/env python3
"""为已触发的第三级生成三份独立交叉盲审 prompt。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))
from scripts.collect_challenges import validate_challenge
from scripts.collect_cross_reviews import (
    CROSS_REVIEWERS, input_bundle_hash, sha256_bytes,
)
from scripts.collect_results import expected_batch_id, expected_data_date, validate_expert
from shared.contracts import normalize_ts_code
from shared.review_contracts import cross_prompt_hash

EXPERTS = [item["id"] for item in json.loads(
    (SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8")
)["experts"]]


def expected_cross_prompt(code: str, reviewer: str,
                          base_dir: Path = Path("/tmp")) -> str:
    """从同批次专家、质询及三级判定确定性重建盲审 prompt。"""
    data = json.loads((base_dir / f"invest_data_{code}.json").read_text(encoding="utf-8"))
    level3_path = base_dir / f"invest_level3_{code}.json"
    bundle_hash = input_bundle_hash(code, base_dir)
    if not bundle_hash:
        raise ValueError("交叉盲审输入束不完整")
    level3_hash = sha256_bytes(level3_path.read_bytes())
    corpus = []
    for expert in EXPERTS:
        corpus.append(
            f"\n\n===== {expert} 原报告 =====\n"
            + (base_dir / f"invest_result_{code}_{expert}.md").read_text(encoding="utf-8")
            + f"\n\n===== {expert} 二级质询 =====\n"
            + (base_dir / f"invest_challenge_result_{code}_{expert}.md").read_text(encoding="utf-8")
        )
    shared = "".join(corpus)
    entries = json.loads((SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8"))["experts"]
    method = next(item["file"] for item in entries if item["id"] == reviewer)
    data_date = str(data.get("market", {}).get("trade_date") or "")
    analysis_date = str(data.get("meta", {}).get("analysis_date") or "")
    batch_id = str(data.get("meta", {}).get("batch_id") or "")
    prompt = f"""你是第三级交叉盲审员 `{reviewer}`。你看不到其他盲审员的结论。
请使用 `{method}` 方法论对七份专家报告与二级质询做交叉反证。
只能使用下方同批次输入；新增数字事实仍须保留原报告的 [source]/[calc] 定位。

身份：code={code}; data_date={data_date}; analysis_date={analysis_date}; batch_id={batch_id}
input_bundle_hash={bundle_hash}; level3_hash={level3_hash}

输出必须直接以以下 frontmatter 开始，正文至少 1000 字符：
---
reviewer_id: "{reviewer}"
ts_code: "{code}"
data_date: "{data_date}"
analysis_date: "{analysis_date}"
batch_id: "{batch_id}"
input_bundle_hash: "{bundle_hash}"
cross_prompt_hash: "__PROMPT_HASH__"
cross_verdict: CONFIRM | DOWNGRADE | ESCALATE
---

# {reviewer} 交叉盲审

## 遗漏与矛盾

## 反事实压力测试

## 对裁判长的影响

===== 同批次输入开始 =====
{shared}
===== 同批次输入结束 =====
""".lstrip()
    prompt_hash = cross_prompt_hash(prompt.encode("utf-8"))
    if not prompt_hash:
        raise ValueError("交叉盲审 prompt 自绑定字段异常")
    prompt = prompt.replace("__PROMPT_HASH__", prompt_hash)
    if cross_prompt_hash(prompt.encode("utf-8")) != prompt_hash:
        raise ValueError("交叉盲审 prompt 哈希二阶段重算不一致")
    return prompt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ts_code")
    args = parser.parse_args()
    try:
        code = normalize_ts_code(args.ts_code)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    level3_path = Path(f"/tmp/invest_level3_{code}.json")
    data_path = Path(f"/tmp/invest_data_{code}.json")
    try:
        level3 = json.loads(level3_path.read_text(encoding="utf-8"))
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"✗ 三级判定或数据快照不可读: {exc}", file=sys.stderr)
        return 2
    if level3.get("triggered") is not True:
        print("✗ 第三级未触发，拒绝生成交叉盲审", file=sys.stderr)
        return 2
    batch_id = expected_batch_id(code)
    data_date = expected_data_date(code)
    for expert in EXPERTS:
        problems = validate_expert(code, expert, data_date, batch_id)
        problems.extend(validate_challenge(code, expert))
        if problems:
            print(f"✗ {expert} 输入未通过门禁: {problems[:3]}", file=sys.stderr)
            return 2
    prompts = {}
    for reviewer in CROSS_REVIEWERS:
        try:
            prompt = expected_cross_prompt(code, reviewer)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"✗ {reviewer} 交叉盲审 prompt 生成失败: {exc}", file=sys.stderr)
            return 2
        prompts[Path(f"/tmp/invest_cross_prompt_{code}_{reviewer}.txt")] = prompt

    staged = {}
    try:
        for path, content in prompts.items():
            temp = path.with_name(f".{path.name}.{os.getpid()}.next")
            with temp.open("w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            staged[path] = temp
        for reviewer in CROSS_REVIEWERS:
            Path(f"/tmp/invest_cross_result_{code}_{reviewer}.md").unlink(missing_ok=True)
        Path(f"/tmp/invest_cross_blind_{code}.md").unlink(missing_ok=True)
        for path, temp in staged.items():
            os.replace(temp, path)
            print(f"✓ {path}")
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
