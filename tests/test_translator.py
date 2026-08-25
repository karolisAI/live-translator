import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from live_translator.mt import translator
from live_translator.mt.translator import _argos_package_path, validate_override_dir


class ArgosPackagePathTests(unittest.TestCase):
    """ARGOS_PACKAGES_DIR / XDG_DATA_HOME are legitimate production overrides
    (kept deliberately, unlike the bundled-default path's dev-only escape
    hatch) -- what matters here is that a missing bundled-default candidate
    falls through to them rather than aborting the whole search."""

    def setUp(self) -> None:
        # _last_validated_xdg_data_home is module-level state that otherwise
        # persists across tests -- reset it so each test starts as if
        # nothing had been validated yet, regardless of what an earlier
        # test happened to validate.
        translator._last_validated_xdg_data_home = None

    def _no_bundled_default(self):
        """Guarantee the bundled-default candidate never matches, regardless
        of what's actually on disk in this repo/environment."""
        return patch("live_translator.runtime.approved_runtime_roots", return_value=[])

    def test_env_override_is_used_when_it_has_the_package(self) -> None:
        with TemporaryDirectory() as env_dir, TemporaryDirectory() as xdg_dir:
            package_dir = Path(env_dir) / "en_de"
            package_dir.mkdir()

            with (
                self._no_bundled_default(),
                patch.dict(
                    os.environ, {"ARGOS_PACKAGES_DIR": env_dir, "XDG_DATA_HOME": xdg_dir}
                ),
            ):
                result = _argos_package_path("en", "de")

            self.assertEqual(result, package_dir)

    def test_falls_through_to_xdg_when_env_override_lacks_the_package(self) -> None:
        """Covers two fall-throughs at once: the missing bundled-default
        candidate, and an ARGOS_PACKAGES_DIR that's set but doesn't contain
        this language pair -- neither should abort the search early."""
        with TemporaryDirectory() as env_dir, TemporaryDirectory() as xdg_dir:
            xdg_package = Path(xdg_dir) / "argos-translate" / "packages" / "en_de"
            xdg_package.mkdir(parents=True)

            with (
                self._no_bundled_default(),
                patch.dict(
                    os.environ, {"ARGOS_PACKAGES_DIR": env_dir, "XDG_DATA_HOME": xdg_dir}
                ),
            ):
                result = _argos_package_path("en", "de")

            self.assertEqual(result, xdg_package)

    def test_raises_a_clear_actionable_error_when_nothing_is_found(self) -> None:
        with TemporaryDirectory() as env_dir, TemporaryDirectory() as xdg_dir:
            with (
                self._no_bundled_default(),
                patch.dict(
                    os.environ, {"ARGOS_PACKAGES_DIR": env_dir, "XDG_DATA_HOME": xdg_dir}
                ),
            ):
                with self.assertRaisesRegex(FileNotFoundError, "argos-install"):
                    _argos_package_path("en", "de")

    def test_rejects_a_relative_xdg_data_home(self) -> None:
        env = dict(os.environ)
        env.pop("ARGOS_PACKAGES_DIR", None)
        env["XDG_DATA_HOME"] = "relative/dir"
        with self._no_bundled_default(), patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "absolute"):
                _argos_package_path("en", "de")

    def test_rejects_an_xdg_data_home_that_does_not_exist(self) -> None:
        with TemporaryDirectory() as parent_dir:
            nonexistent = str(Path(parent_dir) / "does-not-exist")
            env = dict(os.environ)
            env.pop("ARGOS_PACKAGES_DIR", None)
            env["XDG_DATA_HOME"] = nonexistent
            with self._no_bundled_default(), patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(ValueError, "not an existing directory"):
                    _argos_package_path("en", "de")

    def test_a_malformed_xdg_data_home_does_not_break_resolution_when_unused(self) -> None:
        """Regression: XDG_DATA_HOME used to be validated eagerly, before the
        search even checked whether an earlier candidate already resolved the
        package -- so a merely-present-but-malformed value broke a setup that
        was otherwise working. It must only be validated once the search
        actually needs it."""
        with TemporaryDirectory() as env_dir:
            package_dir = Path(env_dir) / "en_de"
            package_dir.mkdir()

            env = dict(os.environ)
            env["ARGOS_PACKAGES_DIR"] = env_dir
            env["XDG_DATA_HOME"] = "relative/dir"  # would raise "absolute" if validated
            with self._no_bundled_default(), patch.dict(os.environ, env, clear=True):
                result = _argos_package_path("en", "de")

            self.assertEqual(result, package_dir)

    def test_does_not_revalidate_the_same_xdg_data_home_on_a_later_call(self) -> None:
        """Regression: this used to stat and print XDG_DATA_HOME on every
        call -- once per phrase in a live meeting, same as the
        ARGOS_PACKAGES_DIR spam this PR already fixed elsewhere. The package
        has to actually resolve under XDG (not ARGOS_PACKAGES_DIR) each call,
        otherwise the search returns before ever reaching XDG validation."""
        with TemporaryDirectory() as env_dir, TemporaryDirectory() as xdg_dir:
            xdg_package = Path(xdg_dir) / "argos-translate" / "packages" / "en_de"
            xdg_package.mkdir(parents=True)

            with (
                self._no_bundled_default(),
                patch.dict(
                    os.environ, {"ARGOS_PACKAGES_DIR": env_dir, "XDG_DATA_HOME": xdg_dir}
                ),
                patch(
                    "live_translator.mt.translator.validate_override_dir",
                    wraps=validate_override_dir,
                ) as validate,
            ):
                _argos_package_path("en", "de")
                _argos_package_path("en", "de")
                _argos_package_path("en", "de")

            validate.assert_called_once_with("XDG_DATA_HOME", xdg_dir)

    def test_revalidates_when_xdg_data_home_changes(self) -> None:
        with (
            TemporaryDirectory() as env_dir,
            TemporaryDirectory() as first_xdg,
            TemporaryDirectory() as second_xdg,
        ):
            Path(first_xdg, "argos-translate", "packages", "en_de").mkdir(parents=True)
            Path(second_xdg, "argos-translate", "packages", "en_de").mkdir(parents=True)

            with (
                self._no_bundled_default(),
                patch(
                    "live_translator.mt.translator.validate_override_dir",
                    wraps=validate_override_dir,
                ) as validate,
            ):
                with patch.dict(
                    os.environ, {"ARGOS_PACKAGES_DIR": env_dir, "XDG_DATA_HOME": first_xdg}
                ):
                    _argos_package_path("en", "de")
                with patch.dict(
                    os.environ, {"ARGOS_PACKAGES_DIR": env_dir, "XDG_DATA_HOME": second_xdg}
                ):
                    _argos_package_path("en", "de")

            self.assertEqual(
                validate.call_args_list,
                [
                    unittest.mock.call("XDG_DATA_HOME", first_xdg),
                    unittest.mock.call("XDG_DATA_HOME", second_xdg),
                ],
            )

    def test_unset_xdg_data_home_uses_the_default_without_validation(self) -> None:
        """The ~/.local/share default is not an operator override -- it must
        not be validated or require existing, only an explicit value should."""
        env = dict(os.environ)
        env.pop("ARGOS_PACKAGES_DIR", None)
        env.pop("XDG_DATA_HOME", None)
        with self._no_bundled_default(), patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(FileNotFoundError, "argos-install"):
                _argos_package_path("en", "de")  # must fail on "not found", not validation


if __name__ == "__main__":
    unittest.main()
