#!/usr/bin/env python3
"""Prepare, compile and validate ExpertResult v3 artifacts."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from shared.contracts import normalize_ts_code
from shared.expert_result_v3 import (
    ExpertResultV3Error,
    build_native_prompt,
    canonical_bytes,
    parse_result,
    render_markdown,
    validate_result,
    knowledge_paths_from_prompt,
)
from shared.runtime import RUNTIME_ROOT


def paths(code: str, expert_id: str) -> dict[str, Path]:
    return {
        "data": RUNTIME_ROOT / f"invest_data_{code}.json",
        "annual": RUNTIME_ROOT / f"invest_annual_{code}.txt",
        "original_prompt": RUNTIME_ROOT / f"invest_prompt_{code}_{expert_id}.txt",
        "native_prompt": RUNTIME_ROOT / f"invest_native_prompt_{code}_{expert_id}.txt",
        "sidecar": RUNTIME_ROOT / f"invest_result_{code}_{expert_id}.v3.json",
        "markdown": RUNTIME_ROOT / f"invest_result_{code}_{expert_id}.md",
    }


def load_inputs(code: str, expert_id: str) -> tuple[dict, str, str, list[str]]:
    p = paths(code, expert_id)
    data = json.loads(p["data"].read_text(encoding="utf-8"))
    annual = p["annual"].read_text(encoding="utf-8")
    original = p["original_prompt"].read_text(encoding="utf-8")
    knowledge = knowledge_paths_from_prompt(original)
    return data, annual, original, knowledge


def atomic_write(path: Path, content: bytes) -> None:
    staged = path.with_name(f".{path.name}.{os.getpid()}.next")
    try:
        with staged.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def prepare(code: str, expert_id: str) -> Path:
    data, annual, original, _ = load_inputs(code, expert_id)
    prompt = build_native_prompt(
        expert_id=expert_id, ts_code=code, data=data,
        annual_text=annual, original_prompt=original,
    )
    path = paths(code, expert_id)["native_prompt"]
    atomic_write(path, prompt.encode("utf-8"))
    return path


def compile_raw(code: str, expert_id: str, raw_path: Path,
                sidecar_path: Path, markdown_path: Path) -> dict:
    data, annual, _, knowledge = load_inputs(code, expert_id)
    raw = raw_path.read_text(encoding="utf-8")
    result = parse_result(raw)
    validate_result(
        result, expert_id=expert_id, ts_code=code, data=data,
        annual_text=annual, knowledge_paths=knowledge,
    )
    markdown = render_markdown(
        result, expert_id=expert_id, ts_code=code, data=data,
        annual_text=annual, knowledge_paths=knowledge,
    )
    atomic_write(sidecar_path, canonical_bytes(result))
    atomic_write(markdown_path, markdown.encode("utf-8"))
    return {
        "status": "COMPILED", "sidecar": str(sidecar_path),
        "markdown": str(markdown_path),
        "sidecar_bytes": sidecar_path.stat().st_size,
        "markdown_bytes": markdown_path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("ts_code")
    prep.add_argument("expert_id")
    comp = sub.add_parser("compile")
    comp.add_argument("ts_code")
    comp.add_argument("expert_id")
    comp.add_argument("raw_path", type=Path)
    comp.add_argument("--sidecar", type=Path)
    comp.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    try:
        code = normalize_ts_code(args.ts_code)
        if args.command == "prepare":
            output = {"status": "READY", "prompt_path": str(prepare(code, args.expert_id))}
        else:
            p = paths(code, args.expert_id)
            output = compile_raw(
                code, args.expert_id, args.raw_path,
                args.sidecar or p["sidecar"], args.markdown or p["markdown"],
            )
    except (OSError, ValueError, json.JSONDecodeError, ExpertResultV3Error) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
