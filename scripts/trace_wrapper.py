#!/usr/bin/env python3
"""流程追踪包装器 — 在核心脚本外包裹，零侵入。

用法：
    python3 scripts/trace_wrapper.py --phase sync --code 603605.SH --name 珀莱雅 -- \\
        python3 shared/data_tools.py sync 603605.SH

    python3 scripts/trace_wrapper.py --phase prompt --code 603605.SH --name 珀莱雅 -- \\
        python3 scripts/prepare_prompts.py 603605.SH

    python3 scripts/trace_wrapper.py --phase expert --code 603605.SH --name 珀莱雅 \\
        --expert financial-auditor -- \\
        codex exec - < prompt.txt

输出：logs/trace/<code>_<timestamp>.jsonl
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = SKILL_ROOT / "logs" / "trace"
TRACE_DIR.mkdir(parents=True, exist_ok=True)


def write_trace(code: str, name: str, ts: str, record: dict):
    record.setdefault("ts", ts)
    record.setdefault("code", code)
    record.setdefault("name", name)
    trace_file = TRACE_DIR / f"{code}_{ts.replace(':', '').replace('-', '')[:15]}.jsonl"
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return trace_file


def main():
    p = argparse.ArgumentParser(description="流程追踪包装器")
    p.add_argument("--phase", required=True, help="阶段: sync|prompt|expert|adjudicate|report|review")
    p.add_argument("--code", required=True, help="股票代码")
    p.add_argument("--name", default="", help="公司名")
    p.add_argument("--expert", default="", help="专家 ID（expert 阶段）")
    p.add_argument("--timeout", type=int, default=600, help="超时秒数，默认 600")
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="要执行的命令")
    args = p.parse_args()

    if not args.cmd or args.cmd[0] == "--":
        args.cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else []
    if not args.cmd:
        print("错误：未提供要执行的命令", file=sys.stderr)
        sys.exit(1)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = time.time()

    # 记录开始
    rec = {"phase": args.phase, "status": "start", "cmd": " ".join(args.cmd)}
    if args.expert:
        rec["expert_id"] = args.expert
    trace_file = write_trace(args.code, args.name, ts, rec)

    # 执行命令
    try:
        r = subprocess.run(args.cmd, capture_output=True, text=True,
                          timeout=args.timeout, cwd=str(SKILL_ROOT))
        duration_ms = round((time.time() - t0) * 1000)
        exit_code = r.returncode

        status = "ok" if exit_code == 0 else "error"
        rec = {
            "phase": args.phase, "status": status,
            "duration_ms": duration_ms, "exit_code": exit_code,
            "stdout_bytes": len(r.stdout), "stderr_bytes": len(r.stderr),
        }
        if args.expert:
            rec["expert_id"] = args.expert
        if exit_code != 0:
            rec["stderr_tail"] = r.stderr[-500:] if r.stderr else ""

        # 尝试从 stdout 提取关键指标
        if args.phase in ("prompt", "expert"):
            rec["metrics"] = _extract_metrics(r.stdout, args.phase)

        write_trace(args.code, args.name, ts, rec)

        # 透传 stdout/stderr
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        sys.exit(exit_code)

    except subprocess.TimeoutExpired:
        duration_ms = round((time.time() - t0) * 1000)
        rec = {"phase": args.phase, "status": "timeout",
               "duration_ms": duration_ms, "timeout_s": args.timeout}
        if args.expert:
            rec["expert_id"] = args.expert
        write_trace(args.code, args.name, ts, rec)
        print(f"\n[trace] ⚠ 超时 ({args.timeout}s)", file=sys.stderr)
        sys.exit(124)
    except Exception as e:
        duration_ms = round((time.time() - t0) * 1000)
        rec = {"phase": args.phase, "status": "crash",
               "duration_ms": duration_ms, "error": str(e)[:500]}
        if args.expert:
            rec["expert_id"] = args.expert
        write_trace(args.code, args.name, ts, rec)
        raise


def _extract_metrics(stdout: str, phase: str) -> dict:
    """从 stdout 提取关键指标。"""
    m = {}
    if phase == "prompt":
        import re
        # 提取 "专家 prompt: /tmp/... (12345 字符)"
        for match in re.finditer(r'专家 prompt:.*\((\d+) 字符\)', stdout):
            pass
        # 提取 "全部 prompt 准备完成"
        if "全部 prompt 准备完成" in stdout:
            m["prompts_generated"] = 7
    return m


if __name__ == "__main__":
    main()
