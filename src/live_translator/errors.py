from __future__ import annotations

import importlib.util


class MissingDependency(RuntimeError):
    pass


def require_package(module_name: str, install_name: str | None = None) -> None:
    if importlib.util.find_spec(module_name) is None:
        package = install_name or module_name
        raise MissingDependency(
            f"Missing dependency '{package}'. Install dependencies with: python -m pip install -e ."
        )
