"""可重算的分析批次内容寻址契约。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


HASH_FIELDS = (
    "data_hash", "annual_hash", "wiki_hash", "prompt_contract_hash",
    "prompt_bundle_hash", "batch_id",
)
COMPONENT_FIELDS = (
    "data_hash", "annual_hash", "wiki_hash", "prompt_contract_hash", "prompt_bundle_hash",
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_data_hash(data: dict) -> str:
    normalized = json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))
    meta = normalized.setdefault("meta", {})
    for field in HASH_FIELDS:
        meta.pop(field, None)
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(payload)


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.md")):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def wiki_snapshot_hash(files: dict[str, str]) -> str:
    """对归档的 wiki 相对路径→文本映射重算与 tree_hash 相同的摘要。"""
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(files[name]).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def contract_snapshot_hash(files: list[dict[str, str]]) -> str:
    """对归档的有序 prompt-contract 文件列表重算摘要。"""
    digest = hashlib.sha256()
    for item in files:
        digest.update(str(item.get("name") or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.get("text") or "").encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def prompt_contract_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def prompt_bundle_hash(prompts: dict[str, str | bytes], batch_id: str = "") -> str:
    """绑定实际专家 prompt 字节。

    batch_id 本身由该哈希参与生成。为打破循环依赖，哈希时将 YAML
    frontmatter 中的 batch_id 值归一为占位符 __BATCH_ID__。
    替换仅在首对 --- 内执行，年报正文中的巧合相同字节不受影响。
    """
    digest = hashlib.sha256()
    needle = batch_id.encode("utf-8") if batch_id else b""
    for name in sorted(prompts):
        content = prompts[name]
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        if needle:
            raw = _replace_batch_id_in_frontmatter(raw, needle)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return digest.hexdigest()


def _replace_batch_id_in_frontmatter(raw: bytes, needle: bytes) -> bytes:
    """仅替换 YAML frontmatter（首对 ---）内的 batch_id 值。"""
    lines = raw.split(b"\n")
    in_fm = False
    for i, line in enumerate(lines):
        if line.strip() == b"---":
            in_fm = not in_fm
            if not in_fm:
                break
            continue
        if in_fm and b"batch_id:" in line and needle in line:
            lines[i] = line.replace(needle, b"__BATCH_ID__")
    return b"\n".join(lines)


def batch_id_from_components(components: dict) -> str:
    payload = "\0".join(
        str(components.get(field, ""))
        for field in COMPONENT_FIELDS
    ).encode("ascii")
    return _sha256_bytes(payload)[:24]


def compute_batch_metadata(data: dict, annual_full: str, wiki_root: Path,
                           contract_paths: list[Path],
                           prompt_bundle_hash_value: str | None = None) -> dict[str, str]:
    components = {
        "data_hash": canonical_data_hash(data),
        "annual_hash": _sha256_bytes(annual_full.encode("utf-8")),
        "wiki_hash": tree_hash(wiki_root),
        "prompt_contract_hash": prompt_contract_hash(contract_paths),
    }
    if prompt_bundle_hash_value is not None:
        components["prompt_bundle_hash"] = prompt_bundle_hash_value
    components["batch_id"] = batch_id_from_components(components)
    return components


def validate_batch_metadata(data: dict, annual_full: str, wiki_root: Path,
                            contract_paths: list[Path],
                            prompts: dict[str, str | bytes] | None = None) -> list[str]:
    declared = data.get("meta", {})
    declared_prompt_hash = declared.get("prompt_bundle_hash")
    prompt_problems = []
    computed_prompt_hash = None
    if prompts is not None:
        if not isinstance(declared_prompt_hash, str) or len(declared_prompt_hash) != 64:
            prompt_problems.append("meta.prompt_bundle_hash 缺失或非法")
        else:
            computed_prompt_hash = prompt_bundle_hash(
                prompts, str(declared.get("batch_id") or "")
            )
            if computed_prompt_hash != declared_prompt_hash:
                prompt_problems.append(
                    f"meta.prompt_bundle_hash 与实际 prompt 不一致: "
                    f"{declared_prompt_hash!r} != {computed_prompt_hash!r}"
                )
    expected = compute_batch_metadata(
        data, annual_full, wiki_root, contract_paths,
        computed_prompt_hash if prompts is not None else declared_prompt_hash,
    )
    return prompt_problems + [
        f"meta.{field} 不匹配: {declared.get(field)!r} != {value!r}"
        for field, value in expected.items() if declared.get(field) != value
    ]
