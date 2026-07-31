#!/usr/bin/env python3
"""为 7 位专家生成第二级「Wiki 题库 + 动态问题」质询 prompt。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
WIKI_ROOT = SKILL_ROOT.parent / "invest-wiki" / "04_stock-analysis-expert"
sys.path.insert(0, str(SKILL_ROOT))

from scripts.collect_results import (
    expected_batch_id, expected_data_date, parse_frontmatter, validate_expert,
)
from shared.review_contracts import challenge_prompt_hash
from scripts.verify_report import extract_numbers
from shared.checklist_verify import check_expert_coverage, load_checklist
from shared.contracts import normalize_ts_code


def experts() -> list[dict]:
    return json.loads((SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8"))["experts"]


def question_bank(method_text: str) -> list[str]:
    match = re.search(
        r'^## 魔鬼代言人问题库\s*$(.*?)(?=^##\s+|\Z)',
        method_text, re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []
    return [
        re.sub(r'\*\*', '', item.group(1)).strip()
        for item in re.finditer(r'^\d+\.\s+(.+)$', match.group(1), re.MULTILINE)
    ]


def select_fact(result_text: str) -> tuple[str, str]:
    for finding in extract_numbers(result_text):
        if finding.get("category") != "data":
            continue
        paths = list(finding.get("declared_sources", []))
        for spec in finding.get("calculation_specs", []):
            paths.extend(spec.get("inputs", []))
        if paths:
            return finding.get("raw", str(finding.get("value"))), paths[0]
    return "核心数字结论", "未找到可重算路径"


def expected_challenge_prompt(code: str, expert_id: str,
                              base_dir: Path = Path("/tmp")) -> str:
    """从受批次约束的输入确定性重建单份二级质询 prompt。"""
    entry = {item["id"]: item for item in experts()}[expert_id]
    data = json.loads((base_dir / f"invest_data_{code}.json").read_text(encoding="utf-8"))
    result_text = (base_dir / f"invest_result_{code}_{expert_id}.md").read_text(
        encoding="utf-8"
    )
    batch_id = str(data.get("meta", {}).get("batch_id") or "")
    data_date = str(data.get("market", {}).get("trade_date") or "")
    method_path = WIKI_ROOT / "experts" / f"{entry['file']}.md"
    bank = question_bank(method_path.read_text(encoding="utf-8"))
    if len(bank) < 4:
        raise ValueError(f"{expert_id} 问题库少于 4 题")
    index = int(hashlib.sha256(f"{batch_id}:{expert_id}".encode()).hexdigest(), 16) % len(bank)
    bank_question = bank[index]
    raw, path = select_fact(result_text)
    dynamic_question = (
        f"你的报告将 {raw} 绑定到 `{path}`。如果该项相对当前值向不利方向"
        "恶化 10% [assumption: 魔鬼代言人不利压力情景，不是当前事实]，"
        "哪一段推理首先失效，score/verdict 是否必须下调？"
    )
    coverage = check_expert_coverage(expert_id, result_text, load_checklist())
    missing_items = [item["item"] for item in coverage["items"] if not item["found"]]
    missing_question = (
        f"你对「{missing_items[0]}」未完成有效覆盖。这一缺口在什么情景下会"
        "反转原结论，最低还需要什么证据？"
        if missing_items else "请指出原报告中最薄弱的一项假设，并给出可证伪它的下一个数据点。"
    )
    result_hash = hashlib.sha256(result_text.encode("utf-8")).hexdigest()
    fm = parse_frontmatter(result_text)
    prompt = f"""你正在接受 invest-skill 第二级魔鬼代言人质询。只回答质询，不要重写原报告。

标的：{code}；专家：{expert_id}；批次：{batch_id}。

题库问题：{bank_question}

动态问题：{dynamic_question}

缺失项/薄弱假设追问：{missing_question}

请用 150-300 个中文字符合并回应三个问题，必须正面说明不利情景、结论是否改变、以及下一个可证伪数据；不得新增无来源数字。

输出必须严格使用：
---
expert_id: "{expert_id}"
ts_code: "{code}"
data_date: "{data_date}"
analysis_date: "{fm.get('analysis_date')}"
batch_id: "{batch_id}"
expert_result_hash: "{result_hash}"
challenge_prompt_hash: "__PROMPT_HASH__"
challenge_verdict: UNCHANGED | DOWNGRADED | UPGRADED
---

# {expert_id} 魔鬼代言人回应

## 质询问题

1. {bank_question}
2. {dynamic_question}
3. {missing_question}

## 合并回应（150-300 个中文字符）

一段连续回应。
""".lstrip()
    prompt_hash = challenge_prompt_hash(prompt.encode("utf-8"))
    if not prompt_hash:
        raise ValueError(f"{expert_id} 质询 prompt 自绑定字段异常")
    prompt = prompt.replace("__PROMPT_HASH__", prompt_hash)
    if challenge_prompt_hash(prompt.encode("utf-8")) != prompt_hash:
        raise ValueError(f"{expert_id} 质询 prompt 哈希自校验失败")
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
    batch_id = expected_batch_id(code)
    data_date = expected_data_date(code)
    if not batch_id or not data_date:
        print("✗ 同批次数据快照缺失", file=sys.stderr)
        return 2
    checklist = load_checklist()
    outputs = {}
    for entry in experts():
        expert_id = entry["id"]
        result_path = Path(f"/tmp/invest_result_{code}_{expert_id}.md")
        problems = validate_expert(code, expert_id, data_date, batch_id)
        if problems:
            print(f"✗ {expert_id} 原报告未通过门禁: {problems[:3]}", file=sys.stderr)
            return 2
        try:
            prompt = expected_challenge_prompt(code, expert_id)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"✗ {expert_id} 质询 prompt 生成失败: {exc}", file=sys.stderr)
            return 2
        outputs[Path(f"/tmp/invest_challenge_prompt_{code}_{expert_id}.txt")] = prompt

    staged = {}
    try:
        for path, content in outputs.items():
            temp_path = path.with_name(f".{path.name}.{os.getpid()}.next")
            with temp_path.open("w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            staged[path] = temp_path
        # 所有 prompt 都已持久化后才清理旧回应；混合状态会被
        # collect_challenges 的原报告哈希/批次门禁拒绝。
        for path in outputs:
            result_path = Path(
                str(path).replace("invest_challenge_prompt_", "invest_challenge_result_")
                .replace(".txt", ".md")
            )
            result_path.unlink(missing_ok=True)
        for path, temp_path in staged.items():
            os.replace(temp_path, path)
            print(f"✓ {path} ({len(outputs[path])} chars)")
    finally:
        for temp_path in staged.values():
            temp_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
