from __future__ import annotations

from live_translator.errors import MissingDependency
from live_translator.mt.argos_runtime import configure_argos_runtime

APPROVED_ARGOS_PACKAGE_VERSION = "1.3"


def print_installed_argos_packages() -> None:
    package = _argos_package_module()
    installed = package.get_installed_packages()
    if not installed:
        print("No Argos language packages installed.")
        return

    for item in installed:
        print(f"{item.from_code} -> {item.to_code}: {item.package_version}")


def install_argos_package(source_language: str, target_language: str) -> None:
    package = _argos_package_module()
    print("Updating Argos package index...")
    package.update_package_index()

    available = package.get_available_packages()
    matches = [
        item
        for item in available
        if item.from_code == source_language and item.to_code == target_language
        and item.package_version == APPROVED_ARGOS_PACKAGE_VERSION
    ]
    if not matches:
        raise ValueError(
            f"No approved Argos package {APPROVED_ARGOS_PACKAGE_VERSION} found for "
            f"{source_language} -> {target_language}. Do not install an unreviewed version; "
            "update the runtime asset manifest and tests first."
        )

    selected = matches[0]
    print(
        f"Downloading approved Argos package {source_language} -> {target_language} "
        f"version {APPROVED_ARGOS_PACKAGE_VERSION}..."
    )
    downloaded_path = selected.download()
    print(f"Installing {downloaded_path}...")
    package.install_from_path(downloaded_path)
    print(f"Installed Argos package {source_language} -> {target_language}.")


def _argos_package_module():
    configure_argos_runtime()
    try:
        from argostranslate import package
    except ImportError as exc:
        raise MissingDependency(
            "Missing dependency 'argostranslate'. Install it with: python -m pip install -e \".[translate]\""
        ) from exc
    return package
