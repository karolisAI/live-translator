"""Strict parsing for the approved runtime asset manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from live_translator.errors import AssetIntegrityError, ManifestValidationError, UntrustedRuntimePath
from live_translator.integrity import (
    resolve_asset_path,
    validate_asset_path,
    validate_expected_identity,
    verify_asset,
)

SCHEMA_VERSION = 1

_TOP_LEVEL_KEYS = {"schema_version", "manifest_id", "protected_roots", "assets"}
_ROOT_KEYS = {"path", "component", "reject_unlisted", "exclude"}
_ASSET_KEYS = {"path", "sha256", "size", "component", "version", "source"}
_ALLOWED_COMPONENTS = {"piper-runtime", "piper-voice", "parakeet-model", "argos"}
_ALLOWED_EXCLUSIONS = {
    "models/asr/parakeet-tdt-0.6b-v3": (".cache/**",),
}


@dataclass(frozen=True)
class ProtectedRoot:
    path: PurePosixPath
    component: str
    reject_unlisted: bool
    exclude: tuple[str, ...]


@dataclass(frozen=True)
class AssetEntry:
    path: PurePosixPath
    sha256: str
    size: int
    component: str
    version: str
    source: str


@dataclass(frozen=True)
class AssetManifest:
    schema_version: int
    manifest_id: str
    protected_roots: tuple[ProtectedRoot, ...]
    assets: tuple[AssetEntry, ...]


def verify_manifest(
    manifest: AssetManifest,
    runtime_root: str | Path,
    *,
    components: Iterable[str] | None = None,
) -> dict[str, Path]:
    """Verify selected manifest components and reject unlisted files.

    The returned mapping uses canonical manifest paths as keys. Callers can
    therefore use the exact Path object that was verified instead of resolving
    a configured path a second time.
    """
    selected = set(components) if components is not None else {
        root.component for root in manifest.protected_roots
    }
    unknown = selected - _ALLOWED_COMPONENTS
    if unknown:
        raise ValueError(f"Unsupported manifest component(s): {sorted(unknown)!r}")

    selected_roots = [root for root in manifest.protected_roots if root.component in selected]
    selected_assets = [asset for asset in manifest.assets if asset.component in selected]
    if selected and not selected_roots:
        raise AssetIntegrityError(
            f"Runtime asset manifest has no protected roots for: {sorted(selected)!r}."
        )

    verified: dict[str, Path] = {}
    for asset in selected_assets:
        key = asset.path.as_posix()
        verified[key] = verify_asset(
            runtime_root,
            key,
            expected_size=asset.size,
            expected_sha256=asset.sha256,
        )

    approved_keys = {asset.path.as_posix().casefold() for asset in selected_assets}
    for protected_root in selected_roots:
        root_path = resolve_asset_path(runtime_root, protected_root.path.as_posix())
        if not root_path.is_dir():
            raise AssetIntegrityError(
                f"Protected runtime root is missing or is not a directory: '{protected_root.path}'."
            )
        for candidate in root_path.rglob("*"):
            relative_to_root = candidate.relative_to(root_path).as_posix()
            if _is_excluded(relative_to_root, protected_root.exclude):
                continue
            manifest_path = protected_root.path.joinpath(relative_to_root).as_posix()
            if candidate.is_symlink():
                raise AssetIntegrityError(
                    f"Protected runtime root contains a symbolic link: '{manifest_path}'."
                )
            if candidate.is_file() and manifest_path.casefold() not in approved_keys:
                raise AssetIntegrityError(
                    f"Protected runtime root contains an unlisted file: '{manifest_path}'."
                )
    return verified


def verify_manifest_root(
    manifest: AssetManifest,
    manifest_root: str,
    actual_root: str | Path,
) -> dict[str, Path]:
    """Verify one protected root at a relocatable on-disk location.

    Installed Parakeet models live below the user's data directory while a
    source checkout keeps the same files below the repository. Their approved
    contents are identical even though the absolute parent is not.
    """
    wanted = validate_asset_path(manifest_root)
    matches = [root for root in manifest.protected_roots if root.path == wanted]
    if len(matches) != 1:
        raise AssetIntegrityError(
            f"Runtime asset manifest must contain exactly one protected root '{manifest_root}'."
        )
    protected_root = matches[0]
    directory = Path(actual_root).resolve()
    if not directory.is_dir():
        raise AssetIntegrityError(
            f"Protected runtime root is missing or is not a directory: '{directory}'."
        )

    assets = [asset for asset in manifest.assets if asset.path.is_relative_to(wanted)]
    verified: dict[str, Path] = {}
    approved_relative: set[str] = set()
    for asset in assets:
        relative = asset.path.relative_to(wanted).as_posix()
        approved_relative.add(relative.casefold())
        verified[asset.path.as_posix()] = verify_asset(
            directory,
            relative,
            expected_size=asset.size,
            expected_sha256=asset.sha256,
        )

    for candidate in directory.rglob("*"):
        relative = candidate.relative_to(directory).as_posix()
        if _is_excluded(relative, protected_root.exclude):
            continue
        full_manifest_path = wanted.joinpath(relative).as_posix()
        if candidate.is_symlink():
            raise AssetIntegrityError(
                f"Protected runtime root contains a symbolic link: '{full_manifest_path}'."
            )
        if candidate.is_file() and relative.casefold() not in approved_relative:
            raise AssetIntegrityError(
                f"Protected runtime root contains an unlisted file: '{full_manifest_path}'."
            )
    return verified


def load_manifest(path: str | Path) -> AssetManifest:
    """Read UTF-8 JSON and reject duplicate object keys before validation."""
    manifest_path = Path(path)
    try:
        text = manifest_path.read_text(encoding="utf-8")
        document = json.loads(text, object_pairs_hook=_unique_object)
    except ManifestValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(
            f"Runtime asset manifest could not be read: '{manifest_path}': {exc}."
        ) from exc
    return parse_manifest(document)


def parse_manifest(document: Any) -> AssetManifest:
    """Validate an already-decoded manifest without touching runtime files."""
    top = _require_object(document, "manifest")
    _require_exact_keys(top, _TOP_LEVEL_KEYS, "manifest")

    version = top["schema_version"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise ManifestValidationError(
            f"Unsupported runtime asset manifest schema_version: {version!r}."
        )
    manifest_id = _require_non_empty_string(top["manifest_id"], "manifest_id")

    roots_value = top["protected_roots"]
    assets_value = top["assets"]
    if not isinstance(roots_value, list) or not roots_value:
        raise ManifestValidationError("protected_roots must be a non-empty array.")
    if not isinstance(assets_value, list) or not assets_value:
        raise ManifestValidationError("assets must be a non-empty array.")

    roots = tuple(_parse_root(value, index) for index, value in enumerate(roots_value))
    _reject_duplicate_paths((root.path for root in roots), "protected root")
    assets = tuple(_parse_asset(value, index) for index, value in enumerate(assets_value))
    _reject_duplicate_paths((asset.path for asset in assets), "asset")

    for asset in assets:
        owners = [root for root in roots if asset.path.is_relative_to(root.path)]
        if len(owners) != 1:
            raise ManifestValidationError(
                f"Asset '{asset.path}' must belong to exactly one protected root; found {len(owners)}."
            )
        if asset.component != owners[0].component:
            raise ManifestValidationError(
                f"Asset '{asset.path}' component '{asset.component}' does not match "
                f"protected root component '{owners[0].component}'."
            )

    return AssetManifest(version, manifest_id, roots, assets)


def _parse_root(value: Any, index: int) -> ProtectedRoot:
    label = f"protected_roots[{index}]"
    item = _require_object(value, label)
    _require_exact_keys(item, _ROOT_KEYS, label)
    path = _manifest_path(item["path"], f"{label}.path")
    component = _component(item["component"], f"{label}.component")
    if item["reject_unlisted"] is not True:
        raise ManifestValidationError(f"{label}.reject_unlisted must be true.")
    exclude = item["exclude"]
    if not isinstance(exclude, list) or not all(isinstance(entry, str) for entry in exclude):
        raise ManifestValidationError(f"{label}.exclude must be an array of strings.")
    expected_exclusions = _ALLOWED_EXCLUSIONS.get(path.as_posix(), ())
    if tuple(exclude) != expected_exclusions:
        raise ManifestValidationError(
            f"{label}.exclude must be exactly {list(expected_exclusions)!r}; "
            "manifests cannot choose additional unchecked paths."
        )
    return ProtectedRoot(path, component, True, tuple(exclude))


def _parse_asset(value: Any, index: int) -> AssetEntry:
    label = f"assets[{index}]"
    item = _require_object(value, label)
    _require_exact_keys(item, _ASSET_KEYS, label)
    path = _manifest_path(item["path"], f"{label}.path")
    component = _component(item["component"], f"{label}.component")
    version = _require_non_empty_string(item["version"], f"{label}.version")
    source = _require_non_empty_string(item["source"], f"{label}.source")
    try:
        validate_expected_identity(item["size"], item["sha256"])
    except ValueError as exc:
        raise ManifestValidationError(f"{label}: {exc}.") from exc
    return AssetEntry(
        path=path,
        sha256=item["sha256"],
        size=item["size"],
        component=component,
        version=version,
        source=source,
    )


def _manifest_path(value: Any, label: str) -> PurePosixPath:
    try:
        return validate_asset_path(value)
    except UntrustedRuntimePath as exc:
        raise ManifestValidationError(f"{label}: {exc}") from exc


def _component(value: Any, label: str) -> str:
    component = _require_non_empty_string(value, label)
    if component not in _ALLOWED_COMPONENTS:
        raise ManifestValidationError(f"{label} has unsupported value '{component}'.")
    return component


def _require_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestValidationError(f"{label} must be an object.")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unknown:
            details.append(f"unknown {unknown}")
        raise ManifestValidationError(f"{label} has invalid fields: {', '.join(details)}.")


def _require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{label} must be a non-empty string.")
    return value


def _reject_duplicate_paths(paths, label: str) -> None:
    seen: set[str] = set()
    for path in paths:
        normalized = path.as_posix().casefold()
        if normalized in seen:
            raise ManifestValidationError(f"Duplicate {label} path: '{path}'.")
        seen.add(normalized)


def _is_excluded(relative_path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if relative_path == prefix or relative_path.startswith(prefix + "/"):
                return True
        elif relative_path == pattern:
            return True
    return False


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestValidationError(f"Duplicate JSON object key: '{key}'.")
        result[key] = value
    return result
