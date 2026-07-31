#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组装 invest-skill 最终报告。

用法：
    python3 scripts/assemble_report.py 603605.SH --name 珀莱雅

工作流：
    1. 默认生成 reports/invest_tool/<code>.draft.md（嵌入专家原文 + 加权评分）
    2. 裁判长（主会话/裁决会话）完善草稿：裁决理由、一行总评、知识索引
    3. --finalize 校验草稿无占位符后更名为正式报告 <code>.md
       （不重新生成——重新生成会覆盖裁判长的裁决内容）

退出码：0 成功；2 草稿已生成但专家结果不完整（综合分 N/A）；1 错误。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))
from scripts.collect_results import expected_batch_id, expected_data_date, validate_expert
from scripts.collect_challenges import validate_challenge
from scripts.collect_cross_reviews import (
    CROSS_REVIEWERS, validate_cross_aggregate,
)
from scripts.verify_report import verify as verify_report
from scripts.verify_manifest import verify as verify_manifest
from shared.batch_contract import (
    contract_snapshot_hash, tree_hash, validate_batch_metadata, wiki_snapshot_hash,
)
from shared.checklist_verify import verify_checklist
from shared.contracts import normalize_ts_code, quality_envelope_errors, snapshot_identity
from shared.data_tools import validate_snapshot
REPORTS_DIR = SKILL_ROOT / "reports" / "invest_tool"
WIKI_ADJUDICATOR = (SKILL_ROOT.parent / "invest-wiki" / "04_stock-analysis-expert"
                    / "adjudicator" / "裁判长-多框架裁判规则.md")
WIKI_ROOT = SKILL_ROOT.parent / "invest-wiki" / "04_stock-analysis-expert"
CHECKLIST_PATH = SKILL_ROOT / "data" / "expert_checklist.json"
EVIDENCE_RULES_PATH = SKILL_ROOT / "data" / "checklist_evidence_rules.json"
EXPERTS_PATH = SKILL_ROOT / "data" / "experts.json"
PROMPT_CONTRACT_PATH = SKILL_ROOT / "scripts" / "prepare_prompts.py"

def load_expert_ids():
    """从 data/experts.json 读取专家 ID 列表（唯一数据源）。"""
    data = json.loads((SKILL_ROOT / "data" / "experts.json").read_text(encoding="utf-8"))
    return [e["id"] for e in data["experts"]]

EXPERTS = load_expert_ids()

# 认知风控官不参与加权（wiki 规则），其 VETO/WARN 作为修正系数
EXPECTED_WEIGHT_KEYS = {
    "financial-auditor", "value-valuator", "moat-analyst",
    "growth-assessor", "management-auditor", "macro-cyclist",
}

# 定稿前必须被裁判长替换的占位符
FINALIZE_PLACEHOLDERS = (
    "待裁判长填写", "[HOLD / PASS / BUY / SELL / OBSERVE]", "结构化自评审待填写"
)


def load_scoring_config() -> dict:
    """从 wiki 裁判规则文件解析机器可读 scoring 配置块。

    wiki 是评分规则的唯一来源，skill 不保存副本。
    硬失败：文件缺失、无 scoring 块、或配置非法时 SystemExit。
    """
    if not WIKI_ADJUDICATOR.exists():
        raise SystemExit(f"裁判规则文件不存在: {WIKI_ADJUDICATOR}")
    text = WIKI_ADJUDICATOR.read_text(encoding="utf-8")
    for block in re.findall(r'```yaml\s*\n(.*?)```', text, re.DOTALL):
        try:
            data = yaml.safe_load(block)
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("scoring"), dict):
            cfg = data["scoring"]
            weights = cfg.get("weights") or {}
            adj = cfg.get("cognitive_adjustment") or {}
            expected_total = cfg.get("expected_weight_total")
            if set(weights) != EXPECTED_WEIGHT_KEYS:
                raise SystemExit(
                    f"scoring.weights 键集非法: {sorted(weights)}，"
                    f"应为 {sorted(EXPECTED_WEIGHT_KEYS)}（认知风控官不参与加权）"
                )
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < 1
                       for v in weights.values()):
                raise SystemExit("scoring.weights 存在非法权重值（需 0-1 之间的小数）")
            if (not isinstance(expected_total, (int, float))
                    or abs(sum(weights.values()) - float(expected_total)) > 1e-9):
                raise SystemExit("scoring.weights 合计与 expected_weight_total 不一致")
            if not all(isinstance(adj.get(k), (int, float)) and 0 < adj.get(k) <= 1
                       for k in ("VETO", "WARN")):
                raise SystemExit("scoring.cognitive_adjustment 需含合法的 VETO/WARN 系数")
            ratings = cfg.get("ratings")
            if (not isinstance(ratings, list) or len(ratings) < 2
                    or any(not isinstance(item, dict)
                           or not isinstance(item.get("min_score"), (int, float))
                           or item.get("verdict") not in {"BUY", "OBSERVE", "HOLD", "PASS"}
                           or not isinstance(item.get("max_allocation_pct"), (int, float))
                           for item in ratings)
                    or sorted((item["min_score"] for item in ratings), reverse=True)
                    != [item["min_score"] for item in ratings]
                    or ratings[-1]["min_score"] != 0):
                raise SystemExit("scoring.ratings 非法或未覆盖 0 分")
            veto_rules = cfg.get("veto_rules")
            if not isinstance(veto_rules, dict) or any(
                key not in EXPERTS or not isinstance(value, list) or not value
                for key, value in veto_rules.items()
            ):
                raise SystemExit("scoring.veto_rules 非法")
            macro_cap = cfg.get("macro_veto_max_allocation_pct")
            if not isinstance(macro_cap, (int, float)) or not 0 <= macro_cap <= 100:
                raise SystemExit("scoring.macro_veto_max_allocation_pct 非法")
            return {
                "weights": {k: float(v) for k, v in weights.items()},
                "cognitive_adjustment": {"VETO": float(adj["VETO"]), "WARN": float(adj["WARN"])},
                "ratings": ratings,
                "veto_rules": veto_rules,
                "macro_veto_max_allocation_pct": float(macro_cap),
            }
    raise SystemExit(f"裁判规则文件中未找到 scoring 配置块（```yaml scoring: ... ```）: {WIKI_ADJUDICATOR}")


def load_results(ts_code: str) -> dict:
    results = {}
    _stub_markers = ["stub 专家评估", "stub 生成，仅用于管线集成测试"]
    for expert_id in EXPERTS:
        file_path = Path(f"/tmp/invest_result_{ts_code}_{expert_id}.md")
        if file_path.exists():
            text = file_path.read_text(encoding="utf-8")
            problems = validate_expert(
                ts_code, expert_id, expected_data_date(ts_code), expected_batch_id(ts_code)
            )
            if any(m in text for m in _stub_markers) or problems:
                detail = "; ".join(problems) if problems else "stub 占位符"
                results[expert_id] = f"<!-- {expert_id} 结果无效: {detail}；已标记为缺失 -->\n"
            else:
                results[expert_id] = text
        else:
            results[expert_id] = f"<!-- {expert_id} 结果缺失 -->\n"
    return results


def load_challenges(ts_code: str) -> dict:
    results = {}
    for expert_id in EXPERTS:
        path = Path(f"/tmp/invest_challenge_result_{ts_code}_{expert_id}.md")
        results[expert_id] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return results


def parse_frontmatter(text: str) -> dict:
    """解析 frontmatter，兼容裸 YAML、```yaml 包裹、以及 frontmatter 前有说明文字的情况。"""
    if not text:
        return {}

    # agent 有时会在 frontmatter 前输出说明性文字；扫描前 20 行找 ---
    lines = text.split("\n")
    if lines[0].strip() != "---":
        for i, line in enumerate(lines[:20]):
            if line.strip() == "---":
                text = "\n".join(lines[i:])
                break

    if not text:
        return {}

    # 第一轮：匹配裸 frontmatter（---\n...\n---\n）
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass

    # 第二轮：去掉 ```yaml 包裹后再试
    clean = re.sub(r'```yaml\s*\n', '', text)
    clean = re.sub(r'\n```\s*\n', '\n', clean)
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', clean, re.DOTALL)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass

    # 第三轮（回退）：在整个原文中搜索任意 ---...--- 块
    if not m:
        m = re.search(r'^---\s*\n(.*?)\n---\s*\n', text, re.MULTILINE | re.DOTALL)
        if m:
            try:
                return yaml.safe_load(m.group(1)) or {}
            except Exception:
                pass
    return {}


def compute_score(results: dict, scoring: dict) -> tuple:
    """返回 (raw, adjusted, scores, details, adjustment, complete)。

    权重与认知修正系数全部来自 wiki scoring 配置。
    任一专家结果缺失或 score 非法时 complete=False，raw/adjusted 为 None——
    综合分宁缺毋假。
    """
    scores = {}
    complete = True
    for expert_id in EXPERTS:
        text = results.get(expert_id, "")
        fm = parse_frontmatter(text)
        score = fm.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 100):
            score = None
        if score is None:
            complete = False
        scores[expert_id] = {
            "score": score,
            "verdict": fm.get("verdict", "UNKNOWN"),
            "conclusion_direction": fm.get("conclusion_direction", "UNKNOWN"),
            "veto_triggers": fm.get("veto_triggers", []),
        }

    if not complete:
        return None, None, scores, [], 1.0, False

    raw = 0.0
    details = []
    for expert_id, weight in scoring["weights"].items():
        s = scores[expert_id]["score"]
        contrib = s * weight
        raw += contrib
        details.append(f"{expert_id}: {s} × {weight} = {contrib:.2f}")

    cognitive = scores.get("cognitive-controller", {})
    # 优先读取专家输出的分级乘数（0.70-1.00），不存在时回退到 verdict 二元映射
    cognitive_multiplier = cognitive.get("cognitive_multiplier")
    if isinstance(cognitive_multiplier, (int, float)) and 0.5 <= cognitive_multiplier <= 1.0:
        adjustment = float(cognitive_multiplier)
    else:
        cognitive_verdict = cognitive.get("verdict", "PASS")
        mapping = scoring.get("cognitive_adjustment", {})
        adjustment = mapping.get(cognitive_verdict, 1.0)

    adjusted = raw * adjustment
    return raw, adjusted, scores, details, adjustment, True


def _verified_industry_history(industry: str, reports_dir: Path = REPORTS_DIR) -> list[dict]:
    """读取有 manifest 哈希背书的同行业历史三级判定。"""
    records = []
    artifacts = reports_dir / "artifacts"
    if not industry or not artifacts.is_dir():
        return records
    for manifest_path in artifacts.glob("*/*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = {
                item.get("name"): item for item in manifest.get("files", [])
                if isinstance(item, dict)
            }
            candidates = [name for name in entries if re.fullmatch(r'invest_level3_.+\.json', name)]
            if len(candidates) != 1:
                continue
            level3_path = manifest_path.parent / candidates[0]
            entry = entries[candidates[0]]
            if not level3_path.is_file() or _sha256(level3_path) != entry.get("sha256"):
                continue
            record = json.loads(level3_path.read_text(encoding="utf-8"))
            directions = record.get("expert_directions")
            if (record.get("industry") != industry or not isinstance(directions, dict)
                    or set(directions) != set(EXPERTS)
                    or any(value not in {"POSITIVE", "NEUTRAL", "NEGATIVE"}
                           for value in directions.values())):
                continue
            records.append({
                "run_id": str(manifest.get("run_id") or manifest_path.parent.name),
                "created_at": str(manifest.get("created_at") or ""),
                "expert_directions": directions,
            })
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(records, key=lambda item: (item["created_at"], item["run_id"]))


def _opposed_experts(record: dict) -> set[str]:
    directions = record.get("expert_directions", {})
    opposed = set()
    for expert_id, own in directions.items():
        if own == "NEUTRAL":
            continue
        peer = [
            value for key, value in directions.items()
            if key != expert_id and value in {"POSITIVE", "NEGATIVE"}
        ]
        positive, negative = peer.count("POSITIVE"), peer.count("NEGATIVE")
        majority = "POSITIVE" if positive > negative else (
            "NEGATIVE" if negative > positive else None
        )
        if majority and own != majority:
            opposed.add(expert_id)
    return opposed


def evaluate_level3(results: dict, scoring: dict, industry: str = "",
                    reports_dir: Path = REPORTS_DIR) -> dict:
    raw, adjusted, scores, _, _, complete = compute_score(results, scoring)
    verdicts = [item.get("verdict") for item in scores.values()]
    pass_count = verdicts.count("PASS")
    veto_count = verdicts.count("VETO")
    severe_split = pass_count > 0 and veto_count > 0 and pass_count + veto_count >= 3
    score_below_40 = bool(complete and adjusted is not None and adjusted < 40)
    directions = {
        expert_id: item.get("conclusion_direction", "UNKNOWN")
        for expert_id, item in scores.items()
    }
    direction_complete = all(
        value in {"POSITIVE", "NEUTRAL", "NEGATIVE"}
        for value in directions.values()
    )
    history = _verified_industry_history(industry, reports_dir) if direction_complete else []
    series = history[-2:] + ([{"run_id": "CURRENT", "expert_directions": directions}]
                            if direction_complete else [])
    opposition_experts = sorted(
        set.intersection(*(_opposed_experts(record) for record in series))
    ) if len(series) >= 3 else []
    industry_opposition = bool(opposition_experts) if len(series) >= 3 else False
    history_status = (
        "EVALUATED_3_RUNS" if len(series) >= 3
        else f"INSUFFICIENT_VERIFIED_HISTORY_{len(series)}_OF_3"
    ) if direction_complete and industry else "MISSING_CURRENT_INDUSTRY_OR_DIRECTION"
    return {
        "severe_verdict_split": severe_split,
        "pass_count": pass_count,
        "veto_count": veto_count,
        "composite_score": round(adjusted, 2) if adjusted is not None else None,
        "composite_score_below_40": score_below_40,
        "industry": industry or None,
        "expert_directions": directions,
        "industry_three_run_opposition": industry_opposition,
        "industry_opposition_experts": opposition_experts,
        "industry_history_run_ids": [item["run_id"] for item in series],
        "industry_history_status": history_status,
        "triggered": severe_split or score_below_40 or industry_opposition,
    }


def validate_devil_challenge(draft: str, ts_code: str, results: dict,
                             challenges: dict, scoring: dict,
                             industry: str = "") -> list[str]:
    problems = []
    if draft.count("## 魔鬼代言人三级质询") != 1:
        problems.append("魔鬼代言人三级质询章节必须且只能出现 1 次")
    visible = re.sub(r'<!--.*?-->', '', draft, flags=re.DOTALL)
    for expert_id, challenge in challenges.items():
        if not challenge or visible.count(challenge) != 1:
            problems.append(f"二级质询回应未唯一嵌入: {expert_id}")
    match = re.search(
        r'^### 第三级触发评估\s*$\n+```yaml\s*\n(.*?)\n```',
        draft, re.MULTILINE | re.DOTALL,
    )
    try:
        declared = yaml.safe_load(match.group(1)) if match else None
    except yaml.YAMLError:
        declared = None
    expected = evaluate_level3(results, scoring, industry)
    if declared != {"level3": expected}:
        problems.append(f"第三级触发评估与机器重算不一致: {declared} != {{'level3': expected}}")
    cross_path = Path(f"/tmp/invest_cross_blind_{ts_code}.md")
    if expected["triggered"]:
        cross_problems = validate_cross_aggregate(ts_code)
        if cross_problems:
            problems.append(f"第三级交叉盲审契约失败: {cross_problems[:3]}")
        elif visible.count(cross_path.read_text(encoding="utf-8")) != 1:
            problems.append("三方交叉盲审结果未唯一嵌入")
    return problems


def load_data_summary(ts_code: str) -> dict:
    data_file = Path(f"/tmp/invest_data_{ts_code}.json")
    if not data_file.exists():
        return {}
    try:
        return json.loads(data_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fmt(value, suffix="") -> str:
    return "N/A" if value is None else f"{value}{suffix}"


def _yoy(current, previous) -> str:
    if current is None or previous in (None, 0):
        return "N/A"
    return f"{(current / previous - 1) * 100:.1f}%"


def _checklist_minimum(report_text: str) -> float:
    results = verify_checklist(report_text)
    percentages = [
        result["covered"] / result["total"] * 100 if result["total"] else 0
        for result in results.values()
    ]
    return min(percentages, default=0.0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_durable(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def archive_run(ts_code: str, draft_file: Path,
                expected_hashes: dict[str, str] | None = None) -> tuple[str, Path]:
    """保存数据、专家报告、质询、三级判定和草稿，供事后复核。"""
    prompts = [Path(f"/tmp/invest_prompt_{ts_code}_{expert_id}.txt") for expert_id in EXPERTS]
    results = [Path(f"/tmp/invest_result_{ts_code}_{expert_id}.md") for expert_id in EXPERTS]
    challenge_prompts = [
        Path(f"/tmp/invest_challenge_prompt_{ts_code}_{expert_id}.txt")
        for expert_id in EXPERTS
    ]
    challenge_results = [
        Path(f"/tmp/invest_challenge_result_{ts_code}_{expert_id}.md")
        for expert_id in EXPERTS
    ]
    level3_path = Path(f"/tmp/invest_level3_{ts_code}.json")
    required = [
        Path(f"/tmp/invest_data_{ts_code}.json"),
        Path(f"/tmp/invest_annual_{ts_code}.txt"),
        draft_file,
    ]
    missing = [str(path) for path in required if not path.exists()]
    for path in [*prompts, *results, *challenge_prompts, *challenge_results, level3_path]:
        if not path.is_file():
            missing.append(str(path))
    cross_path = Path(f"/tmp/invest_cross_blind_{ts_code}.md")
    try:
        level3 = json.loads(level3_path.read_text(encoding="utf-8")) if level3_path.is_file() else {}
    except json.JSONDecodeError:
        level3 = {}
        missing.append(f"三级触发判定不可读: {level3_path}")
    if level3.get("triggered") and not cross_path.is_file():
        missing.append(str(cross_path))
    cross_prompts = [
        Path(f"/tmp/invest_cross_prompt_{ts_code}_{reviewer}.txt")
        for reviewer in CROSS_REVIEWERS
    ]
    cross_results = [
        Path(f"/tmp/invest_cross_result_{ts_code}_{reviewer}.md")
        for reviewer in CROSS_REVIEWERS
    ]
    if level3.get("triggered"):
        for path in [*cross_prompts, *cross_results]:
            if not path.is_file():
                missing.append(str(path))
    if missing:
        raise RuntimeError("归档证据不完整: " + "; ".join(missing))

    run_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f%z")
    archive_dir = REPORTS_DIR / "artifacts" / ts_code / run_id
    archive_dir.mkdir(parents=True, exist_ok=False)
    candidates = [
        Path(f"/tmp/invest_data_{ts_code}.json"),
        Path(f"/tmp/invest_annual_{ts_code}.txt"),
        draft_file,
        *prompts,
        *results,
        *challenge_prompts,
        *challenge_results,
        level3_path,
    ]
    if level3.get("triggered"):
        candidates.extend([*cross_prompts, *cross_results, cross_path])
    files = []
    for source in candidates:
        expected = (expected_hashes or {}).get(str(source.resolve()))
        if expected is not None and _sha256(source) != expected:
            raise RuntimeError(f"归档前证据已发生变化: {source}")
        target = archive_dir / source.name
        shutil.copy2(source, target)
        target_hash = _sha256(target)
        if expected is not None and target_hash != expected:
            raise RuntimeError(f"归档复制期间证据发生变化: {source}")
        files.append({"name": target.name, "sha256": target_hash, "bytes": target.stat().st_size})

    data = json.loads((archive_dir / f"invest_data_{ts_code}.json").read_text(encoding="utf-8"))
    declared_meta = data.get("meta", {})
    wiki_files = {
        str(path.relative_to(WIKI_ROOT)): path.read_text(encoding="utf-8")
        for path in sorted(WIKI_ROOT.rglob("*.md"))
    }
    if (tree_hash(WIKI_ROOT) != declared_meta.get("wiki_hash")
            or wiki_snapshot_hash(wiki_files) != declared_meta.get("wiki_hash")):
        raise RuntimeError("归档时 wiki 快照与批次 wiki_hash 不一致")
    wiki_snapshot_path = archive_dir / "wiki_snapshot.json"
    _write_durable(
        wiki_snapshot_path,
        json.dumps({"files": wiki_files}, ensure_ascii=False, sort_keys=True),
    )
    files.append({
        "name": wiki_snapshot_path.name,
        "sha256": _sha256(wiki_snapshot_path),
        "bytes": wiki_snapshot_path.stat().st_size,
    })

    prompt_contract_sources = [
        PROMPT_CONTRACT_PATH, CHECKLIST_PATH, EVIDENCE_RULES_PATH, EXPERTS_PATH,
    ]
    replay_sources = [
        *prompt_contract_sources,
        SKILL_ROOT / "scripts" / "verify_report.py",
        SKILL_ROOT / "scripts" / "collect_results.py",
        SKILL_ROOT / "scripts" / "prepare_challenges.py",
        SKILL_ROOT / "scripts" / "collect_challenges.py",
        SKILL_ROOT / "scripts" / "prepare_cross_reviews.py",
        SKILL_ROOT / "scripts" / "collect_cross_reviews.py",
        SKILL_ROOT / "scripts" / "assemble_report.py",
        SKILL_ROOT / "scripts" / "verify_manifest.py",
        SKILL_ROOT / "shared" / "batch_contract.py",
        SKILL_ROOT / "shared" / "checklist_verify.py",
        SKILL_ROOT / "shared" / "contracts.py",
        SKILL_ROOT / "shared" / "data_tools.py",
        SKILL_ROOT / "shared" / "review_contracts.py",
    ]
    prompt_contract_files = [
        {"name": path.name, "path": str(path.relative_to(SKILL_ROOT)),
         "text": path.read_text(encoding="utf-8")}
        for path in prompt_contract_sources
    ]
    if contract_snapshot_hash(prompt_contract_files) != declared_meta.get("prompt_contract_hash"):
        raise RuntimeError("归档时 prompt contract 与批次哈希不一致")
    contract_bundle = {
        "prompt_contract_files": prompt_contract_files,
        "replay_files": {
            str(path.relative_to(SKILL_ROOT)): path.read_text(encoding="utf-8")
            for path in dict.fromkeys(replay_sources)
        },
    }
    contract_path = archive_dir / "contract_bundle.json"
    _write_durable(
        contract_path,
        json.dumps(contract_bundle, ensure_ascii=False, sort_keys=True),
    )
    files.append({
        "name": contract_path.name,
        "sha256": _sha256(contract_path),
        "bytes": contract_path.stat().st_size,
    })
    manifest = {
        "run_id": run_id,
        "ts_code": ts_code,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "contract_version": "0.5.1",
        "batch_id": expected_batch_id(ts_code),
        "files": files,
    }
    manifest_path = archive_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_id, manifest_path


def build_report(ts_code: str, name: str, results: dict, data: dict,
                 scoring: dict, challenges: dict, level3: dict,
                 cross_text: str = "", degraded: bool = False) -> str:
    raw, adjusted, scores, details, adjustment, complete = compute_score(results, scoring)

    mode_desc = "降级模式：会话内顺序执行（隔离性受限）" if degraded else "独立进程隔离"
    mode_how = ("会话内顺序执行 7 域分析（fallback，隔离性受限）+ 裁判长综合裁决"
                if degraded else
                "独立 agent 进程并行执行 7 域分析 + 裁判长综合裁决（主会话）")

    market = data.get("market", {})
    stock_info = data.get("stock_info", {})
    annual = data.get("annual", {})
    balance = data.get("balance", {})
    indicators_list = data.get("indicators", {}).get("indicators", [])
    latest_indicator = indicators_list[0] if indicators_list else {}

    # 取最新年度数据
    annual_data = annual.get("annual_data", [])
    latest_annual = annual_data[-1] if annual_data else {}
    prev_annual = annual_data[-2] if len(annual_data) >= 2 else {}
    latest_annual_index = len(annual_data) - 1
    prev_annual_index = len(annual_data) - 2

    # 行业对比数据
    industry = data.get("industry", {})
    industry_stats = industry.get("industry_stats", {})
    target_industry = industry.get("target", {})

    # 核心速览
    analysis_time = datetime.now().astimezone().isoformat(timespec="seconds")
    latest_revenue_yoy = _yoy(latest_annual.get('revenue_yi'), prev_annual.get('revenue_yi'))
    latest_profit_yoy = _yoy(latest_annual.get('net_profit_yi'), prev_annual.get('net_profit_yi'))
    overview = f"""# {name}（{ts_code}）深度投资分析报告

> **分析日期**：{analysis_time}
> **分析模式**：深度分析（7+1 专家团，{mode_desc}）
> **数据基准日**：{market.get('trade_date', 'N/A')}（行情）| 最新财报：{latest_annual.get('year', 'N/A')}年报
> **行业**：{stock_info.get('industry', 'N/A')}
> **股票代码**：{ts_code}
> **批次标识**：`batch_id: {data.get('meta', {}).get('batch_id', 'MISSING')}`
> **生成方式**：{mode_how}
> **数据源声明**：{data.get('meta', {}).get('source_note', '数据源信息不可得')}；`cross_validated={data.get('meta', {}).get('cross_validated', False)}`

---

## 核心数据速览

| 指标 | 数值 | 评价 |
|------|------|------|
| 最新股价 | ¥{_fmt(market.get('close'))} [source: market.close] | {market.get('trade_date', 'N/A')} 收盘 |
| 总市值 | ¥{_fmt(market.get('total_mv_yi'), '亿')} [source: market.total_mv_yi] | — |
| PE(TTM) | {_fmt(market.get('pe_ttm'))} [source: market.pe_ttm] | — |
| PB | {_fmt(market.get('pb'))} [source: market.pb] | — |
| {latest_annual.get('year', 'N/A')}营收 | ¥{_fmt(latest_annual.get('revenue_yi'), '亿')} [source: annual.annual_data[{latest_annual_index}].revenue_yi] | YoY {latest_revenue_yoy} [calc: (current/previous-1)*100; inputs: annual.annual_data[{latest_annual_index}].revenue_yi, annual.annual_data[{prev_annual_index}].revenue_yi] |
| {latest_annual.get('year', 'N/A')}净利 | ¥{_fmt(latest_annual.get('net_profit_yi'), '亿')} [source: annual.annual_data[{latest_annual_index}].net_profit_yi] | YoY {latest_profit_yoy} [calc: (current/previous-1)*100; inputs: annual.annual_data[{latest_annual_index}].net_profit_yi, annual.annual_data[{prev_annual_index}].net_profit_yi] |
| 5年营收CAGR | {_fmt(annual.get('revenue_cagr_5y_pct'), '%')} [source: annual.revenue_cagr_5y_pct] | — |
| 5年净利CAGR | {_fmt(annual.get('profit_cagr_5y_pct'), '%')} [source: annual.profit_cagr_5y_pct] | — |
| 毛利率 | {_fmt(latest_indicator.get('gross_margin_pct'), '%')} [source: indicators.indicators[0].gross_margin_pct] | — |
| 净利率 | {_fmt(latest_indicator.get('net_margin_pct'), '%')} [source: indicators.indicators[0].net_margin_pct] | — |
| ROE | {_fmt(latest_indicator.get('roe_pct'), '%')} [source: indicators.indicators[0].roe_pct] | — |
| 资产负债率 | {_fmt(latest_indicator.get('debt_ratio_pct'), '%')} [source: indicators.indicators[0].debt_ratio_pct] | — |
| 现金 | ¥{_fmt(balance.get('cash_yi'), '亿')} [source: balance.cash_yi] | — |
| 有息负债 | ¥{_fmt(balance.get('interest_debt_yi'), '亿')} [source: balance.interest_debt_yi] | — |"""

    # 追加行业对比表
    if industry_stats:
        overview += """\n\n### 行业对比（公司值 vs 行业中位数）\n\n| 指标 | 公司值 | 行业中位 | 排名百分位 | 样本数 |\n|------|--------|----------|------------|--------|"""
        for metric, label, unit in [
            ("roe_pct", "ROE", "%"),
            ("gross_margin_pct", "毛利率", "%"),
            ("net_margin_pct", "净利率", "%"),
            ("sell_expense_rate_pct", "销售费用率", "%"),
            ("rd_expense_rate_pct", "研发费用率", "%"),
            ("debt_ratio_pct", "资产负债率", "%"),
            ("pe_ttm", "PE(TTM)", ""),
            ("pb", "PB", ""),
        ]:
            if metric in industry_stats and metric in target_industry:
                stats = industry_stats[metric]
                rank = target_industry.get(f"{metric}_rank_pct")
                rank_str = f"{rank}%" if rank is not None else "N/A"
                overview += (
                    f"\n| {label} | {target_industry.get(metric)}{unit} [source: industry.target.{metric}] | "
                    f"{stats.get('median')}{unit} [source: industry.industry_stats.{metric}.median] | "
                    f"{rank_str} [source: industry.target.{metric}_rank_pct] | "
                    f"{stats.get('count')} [source: industry.industry_stats.{metric}.count] |"
                )

    overview += """\n\n**一行总评**：待裁判长填写。\n\n---\n"""

    # 嵌入专家原文
    sections = []
    section_titles = {
        "financial-auditor": "财务排雷 — 财务排雷官评估",
        "value-valuator": "估值安全边际 — 价值估值师评估",
        "growth-assessor": "成长质量 — 成长质量师评估",
        "moat-analyst": "护城河评估 — 护城河分析师评估",
        "cognitive-controller": "认知风控 — 认知风控官评估",
        "macro-cyclist": "宏观周期 — 宏观周期师评估",
        "management-auditor": "管理层评估 — 管理层审计师评估",
    }
    for expert_id in EXPERTS:
        title = section_titles[expert_id]
        sections.append(f"## {title}\n\n{results.get(expert_id, '')}\n")

    challenge_sections = []
    for expert_id in EXPERTS:
        challenge_sections.append(
            f"### {expert_id} 二级质询回应\n\n{challenges.get(expert_id, '')}\n"
        )
    level3_yaml = yaml.safe_dump(
        {"level3": level3}, allow_unicode=True, sort_keys=False,
    ).rstrip()
    challenge_section = (
        "## 魔鬼代言人三级质询\n\n"
        "### 第二级：题库与动态反证\n\n"
        + "\n\n".join(challenge_sections)
        + "\n\n### 第三级触发评估\n\n```yaml\n"
        + level3_yaml
        + "\n```\n"
    )
    if level3.get("triggered"):
        challenge_section += "\n### 第三级：三方交叉盲审\n\n" + cross_text + "\n"
    sections.append(challenge_section)

    def _sub_score(expert_id: str) -> str:
        s = scores[expert_id]
        score_str = s["score"] if s["score"] is not None else "null"
        return f"    {expert_id.replace('-', '_')}: {{ score: {score_str}, verdict: {s['verdict']} }}"

    sub_scores_yaml = "\n".join(_sub_score(e) for e in EXPERTS)
    composite_str = str(round(adjusted)) if complete else "null  # 专家结果不完整，综合分不可计算"
    raw_str = f"{raw:.2f}" if complete else "null"

    # 裁判长裁决模板
    adjudication = f"""---

## 综合裁决 — 裁判长

```yaml
---
adjudicator:
  verdict: [HOLD / PASS / BUY / SELL / OBSERVE]  # 裁判长填写
  composite_score: {composite_str}
  composite_score_raw: {raw_str}
  cognitive_adjustment: {adjustment}
  sub_scores:
{sub_scores_yaml}
  vetoes_triggered: []  # 裁判长填写
  conflicts: []  # 裁判长填写
  review_resolutions: []  # 非 UNCHANGED/CONFIRM 的二、三级意见必须逐项登记采纳/驳回及影响
  position_advice:
    max_allocation_pct: 0
    entry_strategy: 待裁判长填写
    stop_conditions: []
  watch_items: []
  knowledge_refs: []
---
```

### 裁决理由

（裁判长在此撰写综合裁决：一票否决权检查、框架冲突裁决、评分计算说明、最终结论、主要分歧、观察指标。）

**加权评分计算过程**：

| 专家 | 评分 | 权重 | 贡献 |
|------|:----:|:----:|:----:|
"""
    for expert_id, weight in scoring["weights"].items():
        s = scores[expert_id]['score']
        s_str = s if s is not None else "N/A"
        contrib = f"{s * weight:.2f}" if s is not None else "N/A"
        adjudication += f"| {expert_id} | {s_str} | {weight} | {contrib} |\n"
    if complete:
        adjudication += f"| **原始加权分** | — | — | **{raw:.2f}** |\n"
        adjudication += f"| **认知修正** | {scores['cognitive-controller']['verdict']} | ×{adjustment} | **{adjusted:.2f}** |\n"
    else:
        adjudication += "| **综合分** | — | — | **N/A（专家结果不完整，裁判长须定性说明）** |\n"
    adjudication += """
（裁判长继续补充定性裁决……）

---

## 知识索引

（汇总本次分析引用的 wiki 页面清单。）

---

## 结构化自评审

结构化自评审待填写

*报告版本：invest-skill v0.5.1 | 生成时间：{analysis_time}*
"""

    return overview + "\n\n---\n\n".join(sections) + "\n\n" + adjudication


def validate_self_review(draft: str) -> list[str]:
    """只接受结构化自评审章节内的明确分数和独立 PASS 判定。"""
    matches = list(re.finditer(r'^## 结构化自评审\s*$', draft, re.MULTILINE))
    if len(matches) != 1:
        return [f"## 结构化自评审 必须且只能出现 1 次（当前 {len(matches)}）"]
    match = matches[0]
    adjudication = draft.find("## 综合裁决 — 裁判长")
    if adjudication < 0 or match.start() < adjudication:
        return ["结构化自评审必须位于专家原文与综合裁决之后"]
    body = draft[match.end():]
    next_section = re.search(r'^##\s+', body, re.MULTILINE)
    if next_section:
        return ["结构化自评审必须是最后一个二级章节"]
    problems = []
    score_match = re.search(r'^\s*\*\*总分[：:]\s*(\d+)\s*/\s*90\*\*\s*$', body, re.MULTILINE)
    if not score_match or not 72 <= int(score_match.group(1)) <= 90:
        problems.append("自评审总分必须为 72-90/90")
    if not re.search(r'^\s*\*\*判定[：:]\s*PASS\*\*\s*$', body, re.MULTILINE):
        problems.append("自评审必须含独立行 **判定：PASS**")
    dimensions = (
        ("数据可追溯性", 25), ("方法论忠实度", 25),
        ("裁判诚实性与一致性", 25), ("逻辑与表述", 15),
    )
    scores = []
    for label, maximum in dimensions:
        item = re.search(
            rf'^\|\s*{re.escape(label)}\s*\|[^\n|]*?(\d+)\s*/\s*{maximum}[^\n]*\|',
            body, re.MULTILINE,
        )
        if not item or not 0 <= int(item.group(1)) <= maximum:
            problems.append(f"自评审缺少合法维度得分: {label} / {maximum}")
        else:
            scores.append(int(item.group(1)))
    if score_match and len(scores) == len(dimensions) and sum(scores) != int(score_match.group(1)):
        problems.append(f"自评审四维得分之和 {sum(scores)} 与总分不一致")
    if "扣分明细" not in body or not re.search(r'(?:^\s*-\s+.+|无扣分)', body, re.MULTILINE):
        problems.append("自评审缺少扣分明细（无扣分也须明确写出）")
    return problems


def validate_adjudication(draft: str, results: dict | None = None,
                          scoring: dict | None = None,
                          challenges: dict | None = None,
                          ts_code: str | None = None) -> list[str]:
    matches = list(re.finditer(
        r'^## 综合裁决 — 裁判长\s*\n+\s*```yaml\s*\n(.*?)\n```',
        draft, re.MULTILINE | re.DOTALL,
    ))
    if len(matches) != 1:
        return [f"综合裁决 YAML 必须且只能出现 1 次（当前 {len(matches)}）"]
    match = matches[0]
    if not match:
        return ["综合裁决 YAML 缺失或格式非法"]
    try:
        yaml_text = match.group(1).strip()
        if yaml_text.startswith("---"):
            yaml_text = yaml_text[3:].lstrip()
        if yaml_text.endswith("---"):
            yaml_text = yaml_text[:-3].rstrip()
        payload = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        return [f"综合裁决 YAML 无法解析: {exc}"]
    adjudicator = payload.get("adjudicator") if isinstance(payload, dict) else None
    if not isinstance(adjudicator, dict):
        return ["综合裁决 YAML 缺少 adjudicator 映射"]
    problems = []
    if adjudicator.get("verdict") not in {"HOLD", "PASS", "BUY", "SELL", "OBSERVE"}:
        problems.append("综合裁决 verdict 非法")
    score = adjudicator.get("composite_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
        problems.append("综合裁决 composite_score 非法")
    if not isinstance(adjudicator.get("conflicts"), list):
        problems.append("综合裁决 conflicts 必须是列表")
    else:
        for index, conflict in enumerate(adjudicator.get("conflicts", []), 1):
            if (not isinstance(conflict, dict)
                    or not isinstance(conflict.get("experts"), list)
                    or len(conflict.get("experts", [])) < 2
                    or not str(conflict.get("resolution") or "").strip()
                    or not str(conflict.get("rule") or "").strip()):
                problems.append(f"综合裁决 conflicts[{index}] 结构不完整")
    if not isinstance(adjudicator.get("vetoes_triggered"), list):
        problems.append("综合裁决 vetoes_triggered 必须是列表")
    resolutions = adjudicator.get("review_resolutions")
    if not isinstance(resolutions, list):
        problems.append("综合裁决 review_resolutions 必须是列表")
        resolutions = []
    declared_reviews = {}
    for index, item in enumerate(resolutions, 1):
        if (not isinstance(item, dict) or not str(item.get("review") or "").strip()
                or not str(item.get("verdict") or "").strip()
                or not str(item.get("decision") or "").strip()
                or not str(item.get("impact") or "").strip()):
            problems.append(f"综合裁决 review_resolutions[{index}] 结构不完整")
            continue
        review_id = str(item["review"])
        if review_id in declared_reviews:
            problems.append(f"综合裁决 review_resolutions 重复: {review_id}")
        declared_reviews[review_id] = str(item["verdict"])

    required_reviews = {}
    for expert_id, text in (challenges or {}).items():
        verdict_value = parse_frontmatter(text).get("challenge_verdict")
        if verdict_value in {"DOWNGRADED", "UPGRADED"}:
            required_reviews[f"challenge:{expert_id}"] = verdict_value
    if ts_code:
        for reviewer in CROSS_REVIEWERS:
            path = Path(f"/tmp/invest_cross_result_{ts_code}_{reviewer}.md")
            if path.is_file():
                verdict_value = parse_frontmatter(path.read_text(encoding="utf-8")).get("cross_verdict")
                if verdict_value in {"DOWNGRADE", "ESCALATE"}:
                    required_reviews[f"cross:{reviewer}"] = verdict_value
    for review_id, verdict_value in required_reviews.items():
        if declared_reviews.get(review_id) != verdict_value:
            problems.append(
                f"二/三级非中性意见未在裁决登记: {review_id}={verdict_value}"
            )
    position = adjudicator.get("position_advice")
    if not isinstance(position, dict):
        problems.append("综合裁决 position_advice 必须是映射")
        position = {}
    allocation = position.get("max_allocation_pct")
    if (isinstance(allocation, bool) or not isinstance(allocation, (int, float))
            or not 0 <= allocation <= 100):
        problems.append("综合裁决 max_allocation_pct 必须在 0-100 之间")
    if not str(position.get("entry_strategy") or "").strip():
        problems.append("综合裁决 entry_strategy 缺失")
    if (not isinstance(position.get("stop_conditions"), list)
            or not position.get("stop_conditions")):
        problems.append("综合裁决 stop_conditions 必须是非空列表")
    watch_items = adjudicator.get("watch_items")
    if not isinstance(watch_items, list) or not watch_items:
        problems.append("综合裁决 watch_items 必须是非空列表")
    knowledge_refs = adjudicator.get("knowledge_refs")
    if not isinstance(knowledge_refs, list) or len(set(map(str, knowledge_refs or []))) < 3:
        problems.append("综合裁决 knowledge_refs 必须包含至少 3 个唯一 wiki 页面")
    else:
        missing_refs = []
        for raw_ref in knowledge_refs:
            value = str(raw_ref).strip().strip('`')
            value = value[2:-2] if value.startswith('[[') and value.endswith(']]') else value
            value = value.split('|', 1)[0]
            relative = Path(value)
            exists = False
            if not relative.is_absolute() and '..' not in relative.parts:
                direct = WIKI_ROOT / relative
                exists = direct.is_file() or (
                    not direct.suffix and direct.with_suffix('.md').is_file()
                )
                if not exists and len(relative.parts) == 1:
                    exists = any(WIKI_ROOT.rglob(f"{relative.name}.md"))
            if not exists:
                missing_refs.append(str(raw_ref))
        if missing_refs:
            problems.append(f"综合裁决 knowledge_refs 页面不存在: {missing_refs[:3]}")

    def score_tier(value: float) -> dict | None:
        for tier in (scoring or {}).get("ratings", []):
            if value >= float(tier["min_score"]):
                return tier
        return None

    vetoes = adjudicator.get("vetoes_triggered")
    verdict = adjudicator.get("verdict")
    tier = score_tier(float(score)) if isinstance(score, (int, float)) else None
    if tier and isinstance(vetoes, list) and not vetoes:
        expected_verdict = tier["verdict"]
        if verdict != expected_verdict:
            problems.append(
                f"综合裁决 verdict 与 wiki 评分映射不一致: {verdict} != {expected_verdict}"
            )
    if isinstance(vetoes, list) and vetoes and verdict == "BUY":
        problems.append("存在专家 VETO 时禁止裁决 BUY")
    if isinstance(allocation, (int, float)) and not isinstance(allocation, bool):
        if verdict == "BUY" and tier:
            cap = float(tier["max_allocation_pct"])
            if not 0 < allocation <= cap:
                problems.append(f"BUY 的仓位上限必须在 (0,{cap}]%")
        elif verdict == "OBSERVE" and tier and not 0 <= allocation <= float(tier["max_allocation_pct"]):
            problems.append(
                f"OBSERVE 的仓位上限不得超过 {tier['max_allocation_pct']}%"
            )
        elif verdict in {"HOLD", "PASS", "SELL"} and allocation != 0:
            problems.append(f"{verdict} 的 max_allocation_pct 必须为 0")
    if results is not None and scoring is not None:
        raw, adjusted, scores, _, adjustment, complete = compute_score(results, scoring)
        if not complete:
            problems.append("专家分数不完整，不能生成综合裁决")
        else:
            if abs(float(score) - round(adjusted)) > 1e-9 if isinstance(score, (int, float)) else True:
                problems.append(f"composite_score 与机器重算不一致: {score} != {round(adjusted)}")
            raw_declared = adjudicator.get("composite_score_raw")
            if (not isinstance(raw_declared, (int, float))
                    or abs(float(raw_declared) - raw) > 0.011):
                problems.append(f"composite_score_raw 与机器重算不一致: {raw_declared} != {raw:.2f}")
            declared_adjustment = adjudicator.get("cognitive_adjustment")
            if (not isinstance(declared_adjustment, (int, float))
                    or abs(float(declared_adjustment) - adjustment) > 1e-9):
                problems.append("cognitive_adjustment 与机器重算不一致")
            sub_scores = adjudicator.get("sub_scores")
            if not isinstance(sub_scores, dict):
                problems.append("综合裁决 sub_scores 缺失")
            else:
                for expert_id, expert_result in scores.items():
                    declared = sub_scores.get(expert_id.replace("-", "_"))
                    expected = {
                        "score": expert_result["score"],
                        "verdict": expert_result["verdict"],
                    }
                    if declared != expected:
                        problems.append(f"sub_scores.{expert_id} 与专家原文不一致")
            veto_ids = sorted(
                expert_id for expert_id, expert_result in scores.items()
                if expert_result["verdict"] == "VETO"
            )
            declared_vetoes = adjudicator.get("vetoes_triggered")
            if isinstance(declared_vetoes, list) and sorted(declared_vetoes) != veto_ids:
                problems.append(f"vetoes_triggered 与专家 VETO 不一致: {declared_vetoes} != {veto_ids}")
            if veto_ids:
                configured = [
                    set(scoring["veto_rules"][expert_id])
                    for expert_id in veto_ids if expert_id in scoring["veto_rules"]
                ]
                allowed_verdicts = (
                    set.intersection(*configured) if configured
                    else ({str(tier["verdict"])} if tier else set())
                )
                if configured and not allowed_verdicts:
                    problems.append(f"多个 VETO 规则无共同允许结论: {veto_ids}")
                if verdict not in allowed_verdicts:
                    problems.append(
                        f"综合裁决未执行 wiki VETO 规则: {veto_ids} -> {sorted(allowed_verdicts)}"
                    )
                macro_cap = scoring["macro_veto_max_allocation_pct"]
                if ("macro-cyclist" in veto_ids and isinstance(allocation, (int, float))
                        and allocation > macro_cap):
                    problems.append(f"宏观周期师 VETO 时仓位上限不得超过 {macro_cap}%")
    reason = re.search(r'^### 裁决理由\s*$(.*?)(?=^\*\*加权评分计算过程)', draft,
                       re.MULTILINE | re.DOTALL)
    reason_text = re.sub(r'\s+', '', reason.group(1)) if reason else ""
    if len(reason_text) < 120 or "裁判长在此撰写" in reason_text:
        problems.append("裁决理由缺失或过短")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="组装 invest-skill 最终报告")
    parser.add_argument("ts_code", help="股票代码，如 603605.SH")
    parser.add_argument("--name", help="公司中文名")
    parser.add_argument("--finalize", action="store_true",
                        help="定稿：校验草稿无占位符后更名为正式报告（不重新生成，保留裁判长裁决）")
    parser.add_argument("--degraded", action="store_true",
                        help="标注降级模式（fallback 会话内顺序执行，隔离性受限）")
    args = parser.parse_args()

    try:
        ts_code = normalize_ts_code(args.ts_code)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    protected_hashes = {}
    if args.finalize:
        level3_path = Path(f"/tmp/invest_level3_{ts_code}.json")
        protected_paths = [
            Path(f"/tmp/invest_data_{ts_code}.json"),
            Path(f"/tmp/invest_annual_{ts_code}.txt"),
            REPORTS_DIR / f"{ts_code}.draft.md",
            *[Path(f"/tmp/invest_prompt_{ts_code}_{expert_id}.txt") for expert_id in EXPERTS],
            *[Path(f"/tmp/invest_result_{ts_code}_{expert_id}.md") for expert_id in EXPERTS],
            *[Path(f"/tmp/invest_challenge_prompt_{ts_code}_{expert_id}.txt") for expert_id in EXPERTS],
            *[Path(f"/tmp/invest_challenge_result_{ts_code}_{expert_id}.md") for expert_id in EXPERTS],
            level3_path,
        ]
        try:
            stored_level3 = json.loads(level3_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored_level3 = {}
        if stored_level3.get("triggered"):
            protected_paths.extend([
                *[Path(f"/tmp/invest_cross_prompt_{ts_code}_{reviewer}.txt")
                  for reviewer in CROSS_REVIEWERS],
                *[Path(f"/tmp/invest_cross_result_{ts_code}_{reviewer}.md")
                  for reviewer in CROSS_REVIEWERS],
                Path(f"/tmp/invest_cross_blind_{ts_code}.md"),
            ])
        absent = [str(path) for path in protected_paths if not path.is_file()]
        if absent:
            print(f"✗ 定稿证据缺失: {absent}", file=sys.stderr)
            return 2
        protected_hashes = {
            str(path.resolve()): _sha256(path) for path in protected_paths
        }
    scoring = load_scoring_config()  # SystemExit on failure：wiki 是评分规则唯一来源
    data = load_data_summary(ts_code)
    if not data:
        print(f"✗ 同批次数据快照不存在或不可读: /tmp/invest_data_{ts_code}.json", file=sys.stderr)
        return 2
    quality = data.get("data_quality", {})
    envelope_problems = quality_envelope_errors(data)
    if envelope_problems:
        print(f"✗ 数据快照质量状态非法/未通过: {envelope_problems}", file=sys.stderr)
        return 2
    try:
        reference_date = datetime.strptime(str(data.get("meta", {}).get("analysis_date") or ""), "%Y%m%d")
    except ValueError:
        print(f"✗ meta.analysis_date 非法: {data.get('meta', {}).get('analysis_date')!r}", file=sys.stderr)
        return 2
    recomputed_quality = validate_snapshot(data, reference_date=reference_date)
    if any(quality.get(key) != recomputed_quality.get(key) for key in ("status", "errors", "warnings")):
        print(f"✗ data_quality 与重算结果不一致: {recomputed_quality}", file=sys.stderr)
        return 2
    snapshot_codes = {
        data.get(section, {}).get("ts_code") for section in ("stock_info", "market")
        if data.get(section, {}).get("ts_code")
    }
    data_date, batch_id = snapshot_identity(data)
    if snapshot_codes != {ts_code} or not data_date or not batch_id:
        print(
            f"✗ 数据快照身份不完整/不一致: codes={snapshot_codes}, "
            f"data_date={data_date}, batch_id={batch_id}", file=sys.stderr,
        )
        return 2
    annual_file = Path(f"/tmp/invest_annual_{ts_code}.txt")
    if not annual_file.is_file():
        print(f"✗ 同批次年报快照缺失: {annual_file}", file=sys.stderr)
        return 2
    batch_problems = validate_batch_metadata(
        data, annual_file.read_text(encoding="utf-8"), WIKI_ROOT,
        [PROMPT_CONTRACT_PATH, CHECKLIST_PATH, EVIDENCE_RULES_PATH, EXPERTS_PATH],
        prompts={
            f"invest_prompt_{ts_code}_{expert_id}.txt": Path(
                f"/tmp/invest_prompt_{ts_code}_{expert_id}.txt"
            ).read_bytes()
            for expert_id in EXPERTS
            if Path(f"/tmp/invest_prompt_{ts_code}_{expert_id}.txt").is_file()
        },
    )
    if batch_problems:
        print(f"✗ 批次内容哈希校验失败: {batch_problems}", file=sys.stderr)
        return 2
    name = args.name or data.get("stock_info", {}).get("name", ts_code)
    industry_name = str(
        data.get("stock_info", {}).get("industry")
        or data.get("industry", {}).get("industry") or ""
    )

    results = load_results(ts_code)
    validation_errors = {
        expert_id: validate_expert(
            ts_code, expert_id, expected_data_date(ts_code), expected_batch_id(ts_code)
        )
        for expert_id in EXPERTS
    }
    validation_errors = {key: value for key, value in validation_errors.items() if value}
    missing = list(validation_errors)
    challenges = load_challenges(ts_code)
    challenge_errors = {
        expert_id: validate_challenge(ts_code, expert_id)
        for expert_id in EXPERTS
    }
    challenge_errors = {key: value for key, value in challenge_errors.items() if value}

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    draft_file = REPORTS_DIR / f"{ts_code}.draft.md"
    final_file = REPORTS_DIR / f"{ts_code}.md"

    if args.finalize:
        # --finalize 不重新生成报告：裁判长完善的是草稿，重新生成会覆盖其裁决。
        # 只做校验 + 落盘，保证「裁判长看过的内容」与「正式报告」逐字一致。
        if not draft_file.exists():
            print("✗ 草稿不存在，无法定稿。先生成草稿并由裁判长完善：", file=sys.stderr)
            print(f"  python3 scripts/assemble_report.py {ts_code} --name <公司名>", file=sys.stderr)
            return 1
        draft = draft_file.read_text(encoding="utf-8")
        placeholders = [p for p in FINALIZE_PLACEHOLDERS if p in draft]
        if placeholders:
            print(f"✗ 草稿仍含占位符 {placeholders}，裁判长尚未完善，拒绝定稿。", file=sys.stderr)
            return 1
        if validation_errors:
            print(f"✗ 专家结果未通过契约校验，拒绝定稿: {validation_errors}", file=sys.stderr)
            return 1
        if challenge_errors:
            print(f"✗ 二级质询未通过契约校验，拒绝定稿: {challenge_errors}", file=sys.stderr)
            return 1
        review_problems = validate_self_review(draft)
        if review_problems:
            print(f"✗ 结构化自评审未通过: {review_problems}", file=sys.stderr)
            return 1
        adjudication_problems = validate_adjudication(
            draft, results=results, scoring=scoring,
            challenges=challenges, ts_code=ts_code,
        )
        if adjudication_problems:
            print(f"✗ 综合裁决未通过: {adjudication_problems}", file=sys.stderr)
            return 1
        challenge_problems = validate_devil_challenge(
            draft, ts_code, results, challenges, scoring, industry_name,
        )
        if challenge_problems:
            print(f"✗ 魔鬼代言人质询未通过: {challenge_problems}", file=sys.stderr)
            return 1
        expected_level3 = evaluate_level3(results, scoring, industry_name)
        level3_path = Path(f"/tmp/invest_level3_{ts_code}.json")
        try:
            stored_level3 = json.loads(level3_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"✗ 三级触发判定不可读: {exc}", file=sys.stderr)
            return 1
        if stored_level3 != expected_level3:
            print(
                f"✗ 三级触发判定与机器重算不一致: "
                f"{stored_level3} != {expected_level3}", file=sys.stderr,
            )
            return 1
        altered = []
        visible_draft = re.sub(r'<!--.*?-->', '', draft, flags=re.DOTALL)
        for expert_id in EXPERTS:
            result_text = Path(f"/tmp/invest_result_{ts_code}_{expert_id}.md").read_text(encoding="utf-8")
            if visible_draft.count(result_text) != 1:
                altered.append(expert_id)
        if altered:
            print(f"✗ 草稿未逐字嵌入同批次专家原文: {altered}", file=sys.stderr)
            return 1
        checklist_minimum = _checklist_minimum(draft)
        if checklist_minimum < 80:
            print(f"✗ 专家必检项最低覆盖率仅 {checklist_minimum:.1f}%（要求 >=80%）。", file=sys.stderr)
            return 1
        verification = verify_report(draft_file, f"/tmp/invest_data_{ts_code}.json")
        if verification.get("verdict") != "PASS":
            print(f"✗ 报告事实核查未通过: {verification.get('verdict', verification.get('error'))}", file=sys.stderr)
            stats = verification.get("stats")
            if stats:
                print(f"  {stats}", file=sys.stderr)
            return 1

        try:
            run_id, manifest_path = archive_run(
                ts_code, draft_file, expected_hashes=protected_hashes
            )
        except RuntimeError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1
        relative_manifest = manifest_path.relative_to(REPORTS_DIR)
        final_content = draft.rstrip() + f"\n\n<!-- artifact_manifest: {relative_manifest} -->\n"
        temp_file = REPORTS_DIR / f".{ts_code}.{run_id}.tmp"
        _write_durable(temp_file, final_content)
        archived_final = manifest_path.parent / final_file.name
        _write_durable(archived_final, final_content)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append({
            "name": archived_final.name,
            "sha256": _sha256(archived_final),
            "bytes": archived_final.stat().st_size,
        })
        manifest_tmp = manifest_path.with_suffix(".tmp")
        _write_durable(manifest_tmp, json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(manifest_tmp, manifest_path)
        manifest_check = verify_manifest(str(archived_final))
        if manifest_check.get("status") != "PASS":
            temp_file.unlink(missing_ok=True)
            print(f"✗ 发布前 manifest 复核失败: {manifest_check}", file=sys.stderr)
            return 1
        # 所有可能失败的必要门禁均已完成；最后一步才替换正式路径。
        os.replace(temp_file, final_file)
        print(f"✓ 正式报告已原子发布: {final_file}")
        print(f"✓ 审计证据已归档: {manifest_path}")
        return 0

    if validation_errors:
        print(f"✗ 专家结果未通过契约，不生成草稿: {validation_errors}", file=sys.stderr)
        return 2
    if challenge_errors:
        print(f"✗ 二级质询未通过，请先运行 scripts/run_challenges.sh: {challenge_errors}", file=sys.stderr)
        return 2
    level3 = evaluate_level3(results, scoring, industry_name)
    level3_path = Path(f"/tmp/invest_level3_{ts_code}.json")
    _write_durable(level3_path, json.dumps(level3, ensure_ascii=False, indent=2) + "\n")
    cross_path = Path(f"/tmp/invest_cross_blind_{ts_code}.md")
    cross_text = cross_path.read_text(encoding="utf-8") if cross_path.is_file() else ""
    if level3.get("triggered"):
        cross_problems = validate_cross_aggregate(ts_code)
        if cross_problems:
            print(
                "✗ 第三级已触发，交叉盲审未通过；请运行 "
                f"`bash scripts/run_cross_reviews.sh {ts_code}`: {cross_problems[:3]}",
                file=sys.stderr,
            )
            return 2
    report = build_report(
        ts_code, name, results, data, scoring, challenges, level3,
        cross_text=cross_text, degraded=args.degraded,
    )
    draft_file.write_text(report, encoding="utf-8")
    print(f"报告草稿已生成: {draft_file}")
    if missing:
        print(f"警告：以下专家结果缺失: {missing}")
    raw, adjusted, _, _, _, complete = compute_score(results, scoring)
    if complete:
        print(f"原始加权分: {raw:.2f}")
        print(f"认知修正后: {adjusted:.2f}")
    else:
        print("综合分: N/A（专家结果不完整）")
    
    # 跨批次评分校准
    try:
        calib_cmd = [
            sys.executable, str(SKILL_ROOT / "scripts" / "calibrate_scores.py"),
            ts_code, "--json",
        ]
        calib_result = subprocess.run(
            calib_cmd, capture_output=True, text=True, timeout=30,
            cwd=str(SKILL_ROOT),
        )
        if calib_result.returncode == 0:
            calib = json.loads(calib_result.stdout)
            for expert_id, info in calib.get("experts", {}).items():
                z = info.get("z_score")
                if z is not None and abs(z) > 1.5:
                    print(
                        f"⚠ 评分校准 — {expert_id}: z={z:+.2f} "
                        f"(历史 μ={info.get('mean', 0):.0f} σ={info.get('std', 0):.0f} n={info.get('n', 0)})",
                        file=sys.stderr,
                    )
    except Exception:
        pass

    print("下一步：裁判长完善草稿（裁决理由、一行总评、知识索引）后定稿：")
    print(f"  python3 scripts/assemble_report.py {ts_code} --name {name} --finalize")
    return 0 if complete and not validation_errors else 2


if __name__ == "__main__":
    sys.exit(main())
