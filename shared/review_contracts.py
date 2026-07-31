"""二级质询与三级盲审的 prompt 字节绑定。"""
from __future__ import annotations

import hashlib
import re


def _self_bound_hash(content: bytes, field: bytes) -> str:
    pattern = field + br':\s*"[^"]+"'
    replacement = field + b': "__PROMPT_HASH__"'
    normalized, count = re.subn(pattern, replacement, content)
    return hashlib.sha256(normalized).hexdigest() if count == 1 else ""


def challenge_prompt_hash(content: bytes) -> str:
    return _self_bound_hash(content, b"challenge_prompt_hash")


def cross_prompt_hash(content: bytes) -> str:
    return _self_bound_hash(content, b"cross_prompt_hash")
