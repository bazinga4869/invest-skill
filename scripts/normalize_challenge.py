#!/usr/bin/env python3
"""把模型生成的质询内容封装成确定性的受信任结果契约。"""
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

from shared.contracts import normalize_ts_code
from shared.review_contracts import challenge_prompt_hash
from shared.runtime import RUNTIME_ROOT

VALID_VERDICTS = {"UNCHANGED", "DOWNGRADED", "UPGRADED"}


def prompt_questions(prompt: str) -> list[str]:
    return re.findall(
        r"^(?:题库问题|动态问题|缺失项/薄弱假设追问)：(.+)$",
        prompt,
        re.MULTILINE,
    )


def _yaml_mapping(text: str) -> dict:
    candidates = [text]
    frontmatter = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if frontmatter:
        candidates.insert(0, frontmatter.group(1))
    fenced = re.search(r"```(?:yaml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1))
    for candidate in candidates:
        try:
            value = yaml.safe_load(candidate)
        except yaml.YAMLError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def extract_verdict(raw: str) -> str:
    mapping = _yaml_mapping(raw)
    verdict = str(mapping.get("challenge_verdict") or "").strip().upper()
    if verdict in VALID_VERDICTS:
        return verdict
    matches = set(re.findall(
        r"challenge_verdict\s*[:：]\s*[\"']?(UNCHANGED|DOWNGRADED|UPGRADED)",
        raw,
        re.IGNORECASE,
    ))
    normalized = {item.upper() for item in matches}
    if len(normalized) == 1:
        return normalized.pop()
    raise ValueError("模型输出缺少唯一合法的 challenge_verdict")


def extract_response(raw: str) -> str:
    mapping = _yaml_mapping(raw)
    response = mapping.get("response")
    if isinstance(response, str) and response.strip():
        return response.strip()

    match = re.search(
        r"^##\s*(?:合并)?(?:回应|答复|回答)[^\n]*\n+(.*?)(?=^##\s+|\Z)",
        raw,
        re.MULTILINE | re.DOTALL,
    )
    if match and match.group(1).strip():
        return match.group(1).strip()

    keyed = re.search(r"^response\s*[:：]\s*(?:\|\s*)?\n?(.*)\Z", raw, re.MULTILINE | re.DOTALL)
    if keyed and keyed.group(1).strip():
        return keyed.group(1).strip()
    raise ValueError("模型输出缺少非空 response/合并回应")


def normalize_raw(raw: str, prompt: str, original: str, data: dict,
                  code: str, expert_id: str) -> str:
    questions = prompt_questions(prompt)
    if len(questions) != 3:
        raise ValueError("受信任质询 prompt 不是 3 个问题")
    prompt_hash = challenge_prompt_hash(prompt.encode("utf-8"))
    if not prompt_hash:
        raise ValueError("受信任质询 prompt 自绑定哈希异常")
    verdict = extract_verdict(raw)
    response = extract_response(raw)
    meta = data.get("meta", {})
    market = data.get("market", {})
    return f'''---
expert_id: "{expert_id}"
ts_code: "{code}"
data_date: "{market.get('trade_date') or ''}"
analysis_date: "{meta.get('analysis_date') or ''}"
batch_id: "{meta.get('batch_id') or ''}"
expert_result_hash: "{hashlib.sha256(original.encode('utf-8')).hexdigest()}"
challenge_prompt_hash: "{prompt_hash}"
challenge_verdict: {verdict}
---

# {expert_id} 魔鬼代言人回应

## 质询问题

1. {questions[0]}
2. {questions[1]}
3. {questions[2]}

## 合并回应（180-360 个中文字符）

{response}
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ts_code")
    parser.add_argument("expert_id")
    parser.add_argument("raw_path", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()
    try:
        code = normalize_ts_code(args.ts_code)
        prompt = (RUNTIME_ROOT / f"invest_challenge_prompt_{code}_{args.expert_id}.txt").read_text(
            encoding="utf-8"
        )
        original = (RUNTIME_ROOT / f"invest_result_{code}_{args.expert_id}.md").read_text(
            encoding="utf-8"
        )
        data = json.loads((RUNTIME_ROOT / f"invest_data_{code}.json").read_text(encoding="utf-8"))
        raw = args.raw_path.read_text(encoding="utf-8")
        normalized = normalize_raw(raw, prompt, original, data, code, args.expert_id)
        args.output_path.write_text(normalized, encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: 质询结果规范化失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
