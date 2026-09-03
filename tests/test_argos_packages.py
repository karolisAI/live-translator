import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from live_translator.mt.argos_packages import (
    APPROVED_ARGOS_PACKAGE_VERSION,
    install_argos_package,
)


def _package(version: str):
    return SimpleNamespace(
        from_code="en",
        to_code="de",
        package_version=version,
        download=MagicMock(return_value=f"en_de-{version}.argosmodel"),
    )


class ArgosPackageInstallTests(unittest.TestCase):
    def test_installs_the_approved_version_not_the_first_match(self) -> None:
        newer = _package("2.0")
        approved = _package(APPROVED_ARGOS_PACKAGE_VERSION)
        package_module = SimpleNamespace(
            update_package_index=MagicMock(),
            get_available_packages=MagicMock(return_value=[newer, approved]),
            install_from_path=MagicMock(),
        )

        with patch(
            "live_translator.mt.argos_packages._argos_package_module",
            return_value=package_module,
        ):
            install_argos_package("en", "de")

        newer.download.assert_not_called()
        approved.download.assert_called_once()
        package_module.install_from_path.assert_called_once_with("en_de-1.3.argosmodel")

    def test_refuses_an_unreviewed_version(self) -> None:
        newer = _package("2.0")
        package_module = SimpleNamespace(
            update_package_index=MagicMock(),
            get_available_packages=MagicMock(return_value=[newer]),
            install_from_path=MagicMock(),
        )

        with patch(
            "live_translator.mt.argos_packages._argos_package_module",
            return_value=package_module,
        ):
            with self.assertRaisesRegex(ValueError, "No approved Argos package 1.3"):
                install_argos_package("en", "de")

        newer.download.assert_not_called()
        package_module.install_from_path.assert_not_called()


if __name__ == "__main__":
    unittest.main()
