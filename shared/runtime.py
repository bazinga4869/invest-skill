"""Shared runtime-directory policy for transient pipeline artifacts."""
from __future__ import annotations

import os
from pathlib import Path

# Transient prompts and model outputs may contain sensitive financial context.
# All processes importing the shared runtime create owner-only artifacts.
os.umask(0o077)


def runtime_root() -> Path:
    """Return runtime root: explicit transient override, then INVEST_SKILL_HOME."""
    raw = (
        os.environ.get("INVEST_RUNTIME_DIR")
        or os.environ.get("INVEST_SKILL_HOME")
        or "/tmp"
    )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("INVEST_RUNTIME_DIR 必须是绝对路径")
    path = path.resolve(strict=False)
    if path == Path("/"):
        raise ValueError("INVEST_RUNTIME_DIR 不得指向文件系统根目录")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


RUNTIME_ROOT = runtime_root()
