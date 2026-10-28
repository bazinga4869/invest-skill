"""跨脚本共享的输入与批次契约。"""
from __future__ import annotations

import re
from pathlib import Path


# 本批次会影响取数、委派、修复、裁判、发布和复核语义的完整控制面。
# prepare 绑定这些字节；后续任一阶段检测到变化都必须终止旧批次并重新 prepare。
BATCH_CONTRACT_FILES = (
    "SKILL.md",
    "config.yaml",
    "references/automation.md",
    "references/data-contract.md",
    "references/execution.md",
    "references/report-gates.md",
    "data/checklist_evidence_rules.json",
    "data/expert_checklist.json",
    "data/expert_result_v3.schema.json",
    "data/experts.json",
    "scripts/assemble_report.py",
    "scripts/cleanup_intermediates.py",
    "scripts/cron_prompt.txt",
    "scripts/cron_trigger.sh",
    "scripts/collect_challenges.py",
    "scripts/collect_cross_reviews.py",
    "scripts/collect_results.py",
    "scripts/execution_provenance.py",
    "scripts/expert_result_v3.py",
    "scripts/native_agent_tasks.py",
    "scripts/normalize_challenge.py",
    "scripts/prepare_challenges.py",
    "scripts/prepare_cross_reviews.py",
    "scripts/prepare_prompts.py",
    "scripts/preserve_failure_evidence.py",
    "scripts/runtime_guard.py",
    "scripts/validate_prompt_bundle.py",
    "scripts/verify_manifest.py",
    "scripts/verify_report.py",
    "shared/batch_contract.py",
    "shared/checklist_verify.py",
    "shared/contracts.py",
    "shared/data_tools.py",
    "shared/expert_result_v3.py",
    "shared/project_config.py",
    "shared/report_wiki.py",
    "shared/review_contracts.py",
    "shared/runtime.py",
    "shared/sage_wiki.py",
)


def batch_contract_paths(skill_root: Path) -> list[Path]:
    paths = [skill_root / relative for relative in BATCH_CONTRACT_FILES]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"批次控制面文件缺失: {missing[:3]}")
    return paths


_TS_CODE = re.compile(r"^(\d{6})(?:\.(SH|SZ|BJ))?$", re.IGNORECASE)
CONTRACT_VERSION = "0.8.0"
PREVIOUS_CONTRACT_VERSION = "0.7.0"
PRE_REPORT_WIKI_CONTRACT_VERSION = "0.6.0"
LEGACY_CONTRACT_VERSION = "0.5.1"

# 0.7 归档的历史重放边界；必须保留，避免 skill 升级后把旧 manifest 误判为损坏。
V07_REPLAY_FILES = (
    "config.yaml",
    "scripts/agent_backend.sh",
    "scripts/cleanup_intermediates.py",
    "scripts/execution_provenance.py",
    "scripts/normalize_challenge.py",
    "scripts/preserve_failure_evidence.py",
    "scripts/run_challenges.sh",
    "scripts/run_cross_reviews.sh",
    "scripts/run_experts.sh",
    "scripts/runtime_guard.py",
    "scripts/validate_prompt_bundle.py",
    "shared/project_config.py",
    "shared/report_wiki.py",
    "shared/sage_wiki.py",
    "shared/runtime.py",
)

# Host-native 生产运行实际使用的重放边界。外部 CLI 兼容脚本不参与默认运行，
# 因而不应挤占 manifest；若未来显式启用外部模式，应由该模式另行声明其重放文件。
REQUIRED_REPLAY_FILES = BATCH_CONTRACT_FILES


def required_replay_files(contract_version: str) -> tuple[str, ...]:
    if contract_version == PREVIOUS_CONTRACT_VERSION:
        return V07_REPLAY_FILES
    return REQUIRED_REPLAY_FILES

# ── 评级词汇表（单一事实源）──────────────────────────────
# 消费方：assemble_report 定稿校验、cron_trigger CRON_DONE 解析、prompt 模板。
# 任何评级集合变更只改这里；wiki scoring.ratings 的 verdict 必须是本集合子集。
RATINGS = ("BUY", "SELL", "HOLD", "PASS", "OBSERVE", "REDUCE", "AVOID")

# CRON_DONE 行正则（供 shell 端 check_cron_done 使用，避免 bash 内重复硬编码）
CRON_DONE_RE = (
    r"^CRON_DONE [0-9]{6}\.(SH|SZ|BJ) ("
    + "|".join(RATINGS)
    + r") ([0-9]|[1-9][0-9]|100)$"
)

# 知识检索日志契约：prompt 中"预填知识页面"表格的保底行数（不足时用方法论页补齐）
KNOWLEDGE_LOG_MIN_ROWS = 3


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
