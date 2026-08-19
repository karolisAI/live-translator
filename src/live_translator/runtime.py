from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "LiveTranslator"


def user_data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def profile_dir() -> Path:
    return user_data_dir() / "profiles"


def diagnostics_dir() -> Path:
    """Per-user home for captured meeting content.

    Resolved through `user_data_dir` on every call rather than cached, because
    group policy can redirect %LOCALAPPDATA% on a corporate machine.
    """
    return user_data_dir() / "diagnostics"


def default_profile_path(profile_name: str = "default") -> Path:
    return profile_dir() / f"{profile_name}.yaml"


def runtime_roots() -> list[Path]:
    roots: list[Path] = [Path.cwd()]
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root).resolve())
    roots.append(Path(__file__).resolve().parents[2])

    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def resolve_runtime_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return candidate

    for root in runtime_roots():
        resolved = root / candidate
        if resolved.exists():
            return resolved
    return candidate
