import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from live_translator.mt import argos_runtime
from live_translator.mt.argos_runtime import configure_argos_runtime, validate_override_dir


class ConfigureArgosRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        # _last_validated_packages_dir is module-level state that otherwise
        # persists across tests (and across the whole test session) -- reset
        # it so each test starts as if nothing had been validated yet,
        # regardless of what an earlier test happened to validate.
        argos_runtime._last_validated_packages_dir = None

    def test_skips_bundled_detection_when_already_set_to_a_valid_directory(self) -> None:
        with TemporaryDirectory() as already_set_dir:
            with (
                patch.dict(os.environ, {"ARGOS_PACKAGES_DIR": already_set_dir}),
                patch("live_translator.mt.argos_runtime.resolve_trusted_path") as resolve,
            ):
                configure_argos_runtime()

                resolve.assert_not_called()
                self.assertEqual(os.environ["ARGOS_PACKAGES_DIR"], already_set_dir)

    def test_rejects_a_relative_value_before_the_argostranslate_library_sees_it(self) -> None:
        """A relative ARGOS_PACKAGES_DIR would resolve against the current
        working directory -- the same loophole the executable-loading fix
        closes, reintroduced here if this weren't caught."""
        with patch.dict(os.environ, {"ARGOS_PACKAGES_DIR": "relative/dir"}):
            with self.assertRaisesRegex(ValueError, "absolute"):
                configure_argos_runtime()

    def test_rejects_a_value_that_is_not_an_existing_directory(self) -> None:
        with TemporaryDirectory() as parent_dir:
            nonexistent = str(Path(parent_dir) / "does-not-exist")
            with patch.dict(os.environ, {"ARGOS_PACKAGES_DIR": nonexistent}):
                with self.assertRaisesRegex(ValueError, "not an existing directory"):
                    configure_argos_runtime()

    def test_sets_it_from_the_bundled_default_when_found(self) -> None:
        with TemporaryDirectory() as bundled_dir:
            bundled = Path(bundled_dir)
            env = dict(os.environ)
            env.pop("ARGOS_PACKAGES_DIR", None)
            with (
                patch.dict(os.environ, env, clear=True),
                patch(
                    "live_translator.mt.argos_runtime.resolve_trusted_path",
                    return_value=bundled,
                ),
            ):
                configure_argos_runtime()

                self.assertEqual(os.environ["ARGOS_PACKAGES_DIR"], str(bundled))

    def test_does_not_revalidate_the_same_value_on_a_later_call(self) -> None:
        """Regression: this used to stat and print on every call once
        ARGOS_PACKAGES_DIR was set -- once per phrase in a live meeting."""
        with TemporaryDirectory() as already_set_dir:
            with (
                patch.dict(os.environ, {"ARGOS_PACKAGES_DIR": already_set_dir}),
                patch(
                    "live_translator.mt.argos_runtime.validate_override_dir",
                    wraps=validate_override_dir,
                ) as validate,
            ):
                configure_argos_runtime()
                configure_argos_runtime()
                configure_argos_runtime()

                validate.assert_called_once_with("ARGOS_PACKAGES_DIR", already_set_dir)

    def test_revalidates_when_the_value_changes(self) -> None:
        """The cache is keyed by value, not a one-shot flag -- a genuinely
        different ARGOS_PACKAGES_DIR must still be validated."""
        with TemporaryDirectory() as first_dir, TemporaryDirectory() as second_dir:
            with patch(
                "live_translator.mt.argos_runtime.validate_override_dir",
                wraps=validate_override_dir,
            ) as validate:
                with patch.dict(os.environ, {"ARGOS_PACKAGES_DIR": first_dir}):
                    configure_argos_runtime()
                with patch.dict(os.environ, {"ARGOS_PACKAGES_DIR": second_dir}):
                    configure_argos_runtime()

                self.assertEqual(
                    validate.call_args_list,
                    [
                        unittest.mock.call("ARGOS_PACKAGES_DIR", first_dir),
                        unittest.mock.call("ARGOS_PACKAGES_DIR", second_dir),
                    ],
                )

    def test_leaves_it_unset_when_the_bundled_default_is_missing(self) -> None:
        """The regression this guards: resolve_trusted_path raising
        FileNotFoundError (nothing bundled in this install/checkout) must not
        crash startup -- it just means no override gets set, same behaviour
        as before this existed."""
        env = dict(os.environ)
        env.pop("ARGOS_PACKAGES_DIR", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "live_translator.mt.argos_runtime.resolve_trusted_path",
                side_effect=FileNotFoundError("not found"),
            ),
        ):
            configure_argos_runtime()  # must not raise

            self.assertNotIn("ARGOS_PACKAGES_DIR", os.environ)


class ValidateOverrideDirTests(unittest.TestCase):
    """Shared by ARGOS_PACKAGES_DIR and XDG_DATA_HOME: legitimate to point
    outside the app's bundle, but must be well-formed and visible when active."""

    def test_returns_the_path_and_announces_it(self) -> None:
        with TemporaryDirectory() as override_dir:
            with patch("builtins.print") as mock_print:
                result = validate_override_dir("ARGOS_PACKAGES_DIR", override_dir)

            self.assertEqual(result, Path(override_dir))
            mock_print.assert_called_once()
            self.assertIn("ARGOS_PACKAGES_DIR", mock_print.call_args.args[0])
            self.assertIn(override_dir, mock_print.call_args.args[0])

    def test_rejects_a_relative_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute"):
            validate_override_dir("XDG_DATA_HOME", "relative/dir")

    def test_rejects_a_path_that_does_not_exist(self) -> None:
        with TemporaryDirectory() as parent_dir:
            nonexistent = str(Path(parent_dir) / "does-not-exist")
            with self.assertRaisesRegex(ValueError, "not an existing directory"):
                validate_override_dir("XDG_DATA_HOME", nonexistent)

    def test_rejects_a_path_that_is_a_file_not_a_directory(self) -> None:
        with TemporaryDirectory() as parent_dir:
            a_file = Path(parent_dir) / "not-a-directory"
            a_file.write_text("")
            with self.assertRaisesRegex(ValueError, "not an existing directory"):
                validate_override_dir("XDG_DATA_HOME", str(a_file))


if __name__ == "__main__":
    unittest.main()
