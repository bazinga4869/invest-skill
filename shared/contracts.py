"""跨脚本共享的输入与批次契约。"""
from __future__ import annotations

import re


_TS_CODE = re.compile(r"^(\d{6})(?:\.(SH|SZ|BJ))?$", re.IGNORECASE)


def normalize_ts_code(value: str) -> str:
    """规范化 A 股代码，并拒绝无法确定交易所的输入。"""
    raw = str(value or "").strip().upper()
    match = _TS_CODE.fullmatch(raw)
    if not match:
        raise ValueError(f"股票代码格式非法: {value!r}")
    symbol, exchange = match.groups()
    if not exchange:
        if symbol[0] in "569":
            exchange = "SH"
        elif symbol[0] in "0123":
            exchange = "SZ"
        elif symbol[0] in "48":
            exchange = "BJ"
        else:
            raise ValueError(f"无法从六位代码判断交易所: {value!r}")
    return f"{symbol}.{exchange}"


def snapshot_identity(data: dict) -> tuple[str | None, str | None]:
    """返回 (data_date, batch_id)，缺失时保留 None 供调用方硬失败。"""
    data_date = data.get("market", {}).get("trade_date")
    batch_id = data.get("meta", {}).get("batch_id")
    return (
        str(data_date) if data_date else None,
        str(batch_id) if batch_id else None,
    )


def quality_envelope_errors(data: dict) -> list[str]:
    """校验声明状态与错误/警告载荷一致，防止伪造 PASS 字符串绕过。"""
    quality = data.get("data_quality")
    if not isinstance(quality, dict):
        return ["data_quality 缺失或不是对象"]
    status = quality.get("status")
    errors = quality.get("errors")
    warnings = quality.get("warnings")
    problems = []
    if status not in {"PASS", "WARN"}:
        problems.append(f"data_quality.status 非法/未通过: {status!r}")
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        problems.append("data_quality.errors 必须是字符串列表")
        errors = []
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        problems.append("data_quality.warnings 必须是字符串列表")
        warnings = []
    if errors:
        problems.append("可发布快照的 data_quality.errors 必须为空")
    if status == "PASS" and warnings:
        problems.append("status=PASS 但 warnings 非空")
    if status == "WARN" and not warnings:
        problems.append("status=WARN 但 warnings 为空")
    return problems
