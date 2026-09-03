"""Low-level integrity checks for protected runtime files.

Manifest parsing deliberately does not live here.  These functions form the
small, reusable boundary that every future manifest entry must pass through:
validate a relative path, keep it below the selected trusted root, compare its
byte size, and stream its contents through SHA-256.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path, PurePosixPath

from live_translator.runtime import _is_within

from live_translator.errors import AssetIntegrityError, UntrustedRuntimePath

_HASH_CHUNK_SIZE = 1024 * 1024
_SHA256_HEX_LENGTH = 64


def resolve_asset_path(root: str | Path, relative_path: str) -> Path:
    """Resolve one manifest path below ``root`` without allowing escape.

    Manifest paths have one canonical representation: non-empty POSIX-style
    relative paths.  Rejecting Windows separators as well as absolute and dot
    components prevents two spellings of the same file from bypassing later
    duplicate and allow-list checks.
    """
    manifest_path = validate_asset_path(relative_path)

    resolved_root = Path(root).resolve()
    candidate = resolved_root.joinpath(*manifest_path.parts).resolve()
    if not _is_within(candidate, resolved_root):
        raise UntrustedRuntimePath(
            f"Runtime asset path '{relative_path}' resolves outside its approved root."
        )
    return candidate


def validate_asset_path(relative_path: str) -> PurePosixPath:
    """Validate and return the canonical path syntax used by manifests."""
    if not isinstance(relative_path, str) or not relative_path:
        raise UntrustedRuntimePath("Runtime asset path must be a non-empty string.")
    if "\\" in relative_path:
        raise UntrustedRuntimePath(
            f"Runtime asset path '{relative_path}' must use '/' separators."
        )

    raw_parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise UntrustedRuntimePath(
            f"Runtime asset path '{relative_path}' must be relative and contain no empty, '.' or '..' segments."
        )
    manifest_path = PurePosixPath(relative_path)
    if manifest_path.is_absolute():
        raise UntrustedRuntimePath(
            f"Runtime asset path '{relative_path}' must be relative and contain no '.' or '..' segments."
        )
    # PurePosixPath does not interpret a Windows drive or UNC prefix as
    # absolute, so reject those spellings explicitly on every platform.
    first_part = manifest_path.parts[0]
    if ":" in first_part or relative_path.startswith("//"):
        raise UntrustedRuntimePath(
            f"Runtime asset path '{relative_path}' must not contain a drive or UNC prefix."
        )

    return manifest_path


def sha256_file(path: str | Path, *, chunk_size: int = _HASH_CHUNK_SIZE) -> str:
    """Return a lowercase SHA-256 digest without loading the file into RAM."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_asset(
    root: str | Path,
    relative_path: str,
    *,
    expected_size: int,
    expected_sha256: str,
) -> Path:
    """Verify one protected file and return its resolved path.

    Size is checked first because it cheaply rejects incomplete or obviously
    different files.  Matching size is not treated as proof: SHA-256 is always
    computed before success is returned.
    """
    validate_expected_identity(expected_size, expected_sha256)
    path = resolve_asset_path(root, relative_path)

    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise AssetIntegrityError(
            f"Protected runtime asset is missing: '{relative_path}'."
        ) from exc
    except OSError as exc:
        raise AssetIntegrityError(
            f"Protected runtime asset could not be inspected: '{relative_path}': {exc}."
        ) from exc

    if not path.is_file():
        raise AssetIntegrityError(
            f"Protected runtime asset is not a regular file: '{relative_path}'."
        )
    if stat.st_size != expected_size:
        raise AssetIntegrityError(
            f"Protected runtime asset has an unexpected size: '{relative_path}' "
            f"(expected {expected_size} bytes, found {stat.st_size})."
        )

    try:
        actual_sha256 = sha256_file(path)
    except OSError as exc:
        raise AssetIntegrityError(
            f"Protected runtime asset could not be read: '{relative_path}': {exc}."
        ) from exc
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise AssetIntegrityError(
            f"Protected runtime asset failed SHA-256 verification: '{relative_path}'."
        )
    return path


def validate_expected_identity(expected_size: int, expected_sha256: str) -> None:
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
        raise ValueError("expected_size must be a non-negative integer")
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != _SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ValueError("expected_sha256 must be 64 lowercase hexadecimal characters")
