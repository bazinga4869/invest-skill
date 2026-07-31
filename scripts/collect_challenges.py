#!/usr/bin/env python3
"""校验第二级魔鬼代言人回应。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))
from scripts.collect_results import expected_batch_id, expected_data_date
from shared.contracts import normalize_ts_code
from shared.review_contracts import challenge_prompt_hash

EXPERTS = [item["id"] for item in json.loads(
    (SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8")
)["experts"]]


def validate_challenge(code: str, expert_id: str, base_dir: Path = Path("/tmp")) -> list[str]:
    problems = []
    prompt_path = base_dir / f"invest_challenge_prompt_{code}_{expert_id}.txt"
    result_path = base_dir / f"invest_challenge_result_{code}_{expert_id}.md"
    original_path = base_dir / f"invest_result_{code}_{expert_id}.md"
    if not all(path.is_file() for path in (prompt_path, result_path, original_path)):
        return ["质询 prompt/result/原专家报告缺失"]
    prompt = prompt_path.read_text(encoding="utf-8")
    result = result_path.read_text(encoding="utf-8")
    original = original_path.read_text(encoding="utf-8")
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', result, re.DOTALL)
    try:
        fm = yaml.safe_load(match.group(1)) if match else {}
    except yaml.YAMLError:
        fm = {}
    data_file = base_dir / f"invest_data_{code}.json"
    data = json.loads(data_file.read_text(encoding="utf-8")) if data_file.is_file() else {}
    expected = {
        "expert_id": expert_id,
        "ts_code": code,
        "data_date": str(data.get("market", {}).get("trade_date") or expected_data_date(code) or ""),
        "analysis_date": str(data.get("meta", {}).get("analysis_date") or ""),
        "batch_id": str(data.get("meta", {}).get("batch_id") or expected_batch_id(code) or ""),
        "expert_result_hash": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "challenge_prompt_hash": challenge_prompt_hash(prompt.encode("utf-8")),
    }
    for field, value in expected.items():
        if str((fm or {}).get(field) or "") != value:
            problems.append(f"{field} 不匹配")
    identity_line = f"标的：{code}；专家：{expert_id}；批次：{expected['batch_id']}。"
    if prompt.count(identity_line) != 1:
        problems.append("质询 prompt 身份行缺失或重复")
    if prompt.count(expected["expert_result_hash"]) != 1:
        problems.append("质询 prompt 未绑定原专家报告哈希")
    if not expected["challenge_prompt_hash"]:
        problems.append("质询 prompt 自绑定字段缺失或重复")
    try:
        # 延迟导入避免准备脚本和收集脚本在模块初始化时形成环。
        from scripts.prepare_challenges import expected_challenge_prompt
        rebuilt = expected_challenge_prompt(code, expert_id, base_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        rebuilt = None
        problems.append(f"无法确定性重建质询 prompt: {exc}")
    if rebuilt is not None and prompt != rebuilt:
        problems.append("质询 prompt 与官方生成器确定性重建结果不一致")
    if (fm or {}).get("challenge_verdict") not in {"UNCHANGED", "DOWNGRADED", "UPGRADED"}:
        problems.append("challenge_verdict 非法")
    questions_match = re.search(
        r'^## 质询问题\s*$(.*?)(?=^## 合并回应)', result,
        re.MULTILINE | re.DOTALL,
    )
    prompt_questions = re.findall(r'^(?:题库问题|动态问题|缺失项/薄弱假设追问)：(.+)$', prompt, re.MULTILINE)
    question_body = questions_match.group(1) if questions_match else ""
    expected_question_lines = [
        f"{index}. {question}" for index, question in enumerate(prompt_questions, 1)
    ]
    actual_question_lines = [line.strip() for line in question_body.splitlines() if line.strip()]
    if len(prompt_questions) != 3 or actual_question_lines != expected_question_lines:
        problems.append("未逐字保留 3 个质询问题")
    response_match = re.search(
        r'^## 合并回应（150-300 个中文字符）\s*$\n+(.*?)(?=^##\s+|\Z)',
        result, re.MULTILINE | re.DOTALL,
    )
    response = response_match.group(1).strip() if response_match else ""
    cjk_count = len(re.findall(r'[\u4e00-\u9fff]', response))
    if not 150 <= cjk_count <= 300:
        problems.append(f"合并回应中文字符数 {cjk_count}，要求 150-300")
    if re.search(r'\[(?:source|calc):', response, re.IGNORECASE):
        problems.append("质询回应不得新增数字引用；应回指原报告")
    return problems


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
    for expert_id in EXPERTS:
        problems = validate_challenge(code, expert_id)
        if problems:
            failing.append(expert_id)
            if not args.failing:
                print(f"  ✗ {expert_id}: {'; '.join(problems)}")
        elif not args.failing:
            print(f"  ✓ {expert_id}")
    if args.failing:
        print("\n".join(failing))
    return 0 if not failing else 1


if __name__ == "__main__":
    raise SystemExit(main())
