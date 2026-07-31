"""全流程追踪模块 — 写磁盘，零 token 消耗。

用法：
    from shared.trace import Trace
    t = Trace("603605.SH", "珀莱雅")

    t.phase("sync", "start", msg="开始同步数据")
    # ... do work ...
    t.phase("sync", "ok", duration_ms=1234, msg="同步完成")

    t.expert("financial-auditor", "start")
    # ... expert runs ...
    t.expert("financial-auditor", "ok", score=87, verdict="PASS", duration_ms=4567)

    t.phase("report", "ok", verdict="HOLD", score=53, msg="报告生成完成")
    t.close()

输出：logs/trace/603605.SH_2026-07-30T153000.jsonl
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = SKILL_ROOT / "logs" / "trace"


class Trace:
    def __init__(self, code: str, name: str = ""):
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        self.code = code
        self.name = name
        self._start_times = {}  # phase -> start timestamp
        self._trace_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self._path = TRACE_DIR / f"{code}_{self._trace_id}.jsonl"
        self._closed = False

    def _write(self, record: dict):
        record.setdefault("ts", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        record.setdefault("code", self.code)
        record.setdefault("name", self.name)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def phase(self, phase: str, status: str, **kwargs):
        """记录流程阶段事件。phase: sync|prompt|adjudicate|report|review|cleanup
        status: start|ok|warn|error|skip"""
        if status == "start":
            self._start_times[phase] = time.time()
        elif phase in self._start_times:
            kwargs.setdefault("duration_ms", round((time.time() - self._start_times.pop(phase)) * 1000))
        self._write({"phase": phase, "status": status, **kwargs})

    def expert(self, expert_id: str, status: str, **kwargs):
        """记录单个专家阶段事件。status: start|ok|warn|error"""
        key = f"expert:{expert_id}"
        if status == "start":
            self._start_times[key] = time.time()
        elif key in self._start_times:
            kwargs.setdefault("duration_ms", round((time.time() - self._start_times.pop(key)) * 1000))
        self._write({"phase": "expert", "expert_id": expert_id, "status": status, **kwargs})

    def metric(self, key: str, value, **kwargs):
        """记录自定义指标（如 prompt 大小、数据量等）。"""
        self._write({"phase": "metric", "metric": key, "value": value, **kwargs})

    def error(self, phase: str, msg: str, **kwargs):
        """便捷的错误记录。"""
        self._write({"phase": phase, "status": "error", "msg": msg, **kwargs})

    def close(self):
        if not self._closed:
            # 处理所有未关闭的 phase
            for key, start in list(self._start_times.items()):
                dur = round((time.time() - start) * 1000)
                if key.startswith("expert:"):
                    self._write({"phase": "expert", "expert_id": key.split(":", 1)[1],
                                 "status": "timeout", "duration_ms": dur, "msg": "未正常关闭"})
                else:
                    self._write({"phase": key, "status": "timeout", "duration_ms": dur, "msg": "未正常关闭"})
            self._start_times.clear()
            self._closed = True

    @property
    def path(self):
        return str(self._path)
