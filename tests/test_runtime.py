import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from live_translator.errors import UntrustedRuntimePath
from live_translator.runtime import (
    approved_runtime_roots,
    dev_runtime_root,
    resolve_trusted_path,
)


class ApprovedRuntimeRootsTests(unittest.TestCase):
    """The current working directory must never appear here -- that's the
    entire point of this module. Everything else (frozen exe dir, bundle
    dir, dev override) is additive on top of the package root."""

    def test_cwd_is_never_included(self) -> None:
        with TemporaryDirectory() as cwd_dir:
            original_cwd = os.getcwd()
            os.chdir(cwd_dir)
            try:
                roots = approved_runtime_roots()
            finally:
                os.chdir(original_cwd)
            self.assertNotIn(Path(cwd_dir).resolve(), roots)

    def test_frozen_exe_directory_is_included(self) -> None:
        with TemporaryDirectory() as exe_dir:
            fake_exe = Path(exe_dir) / "LiveTranslator.exe"
            with (
                patch("sys.frozen", True, create=True),
                patch("sys.executable", str(fake_exe)),
            ):
                roots = approved_runtime_roots()
            self.assertIn(Path(exe_dir).resolve(), roots)

    def test_bundle_directory_is_included_when_set(self) -> None:
        with TemporaryDirectory() as bundle_dir:
            with patch("sys._MEIPASS", bundle_dir, create=True):
                roots = approved_runtime_roots()
            self.assertIn(Path(bundle_dir).resolve(), roots)


class DevRuntimeRootTests(unittest.TestCase):
    """LIVE_TRANSLATOR_DEV_RUNTIME_ROOT exists to unblock local development,
    never active unless a developer deliberately sets it."""

    def test_unset_by_default(self) -> None:
        env = dict(os.environ)
        env.pop("LIVE_TRANSLATOR_DEV_RUNTIME_ROOT", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(dev_runtime_root())

    def test_returns_the_resolved_path_when_set(self) -> None:
        with TemporaryDirectory() as dev_dir:
            with patch.dict(os.environ, {"LIVE_TRANSLATOR_DEV_RUNTIME_ROOT": dev_dir}):
                result = dev_runtime_root()
            self.assertEqual(result, Path(dev_dir).resolve())

    def test_never_honored_in_a_frozen_build(self) -> None:
        """The whole point of restricting this: a real installed build must
        never trust a directory just because the env var happened to be set
        in its environment, for example left over from an earlier test
        session on a shared machine."""
        with TemporaryDirectory() as dev_dir:
            with (
                patch.dict(os.environ, {"LIVE_TRANSLATOR_DEV_RUNTIME_ROOT": dev_dir}),
                patch("sys.frozen", True, create=True),
            ):
                self.assertIsNone(dev_runtime_root())

    def test_resolve_trusted_path_only_honors_it_once_explicitly_set(self) -> None:
        """The actual point of the override: a path outside every other
        approved root is untrusted before it's set, resolvable after --
        exercised against the real approved_runtime_roots(), not a mock."""
        with TemporaryDirectory() as dev_dir:
            target = Path(dev_dir) / "custom-piper.exe"
            target.write_text("fake")

            env = dict(os.environ)
            env.pop("LIVE_TRANSLATOR_DEV_RUNTIME_ROOT", None)
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(UntrustedRuntimePath):
                    resolve_trusted_path(target)

            with patch.dict(os.environ, {**env, "LIVE_TRANSLATOR_DEV_RUNTIME_ROOT": dev_dir}):
                result = resolve_trusted_path(target)
            self.assertEqual(result, target.resolve())


class ResolveTrustedPathTests(unittest.TestCase):
    """resolve_trusted_path()'s actual job: find a candidate under one of the
    approved roots, and refuse anything that resolves outside all of them --
    regardless of how it got there (absolute path, traversal, or simply
    existing somewhere else entirely). Roots are mocked here so these tests
    don't depend on sys.frozen/_MEIPASS plumbing -- see
    ApprovedRuntimeRootsTests for that."""

    def _with_roots(self, *roots: Path):
        return patch("live_translator.runtime.approved_runtime_roots", return_value=list(roots))

    def test_resolves_inside_an_approved_root(self) -> None:
        with TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            target = root / "tools" / "piper" / "piper.exe"
            target.parent.mkdir(parents=True)
            target.write_text("fake")

            with self._with_roots(root):
                result = resolve_trusted_path("tools/piper/piper.exe")

            self.assertEqual(result, target.resolve())

    def test_a_file_only_present_outside_every_approved_root_is_not_found(self) -> None:
        """Stands in for 'only in the working directory' -- the file exists,
        it's just not under an approved root, so the search must not find it."""
        with TemporaryDirectory() as root_dir, TemporaryDirectory() as elsewhere_dir:
            root = Path(root_dir)
            target = Path(elsewhere_dir) / "tools" / "piper" / "piper.exe"
            target.parent.mkdir(parents=True)
            target.write_text("fake")

            with self._with_roots(root):
                with self.assertRaises(FileNotFoundError):
                    resolve_trusted_path("tools/piper/piper.exe")

    def test_absolute_path_inside_an_approved_root_is_accepted(self) -> None:
        with TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            target = root / "piper.exe"
            target.write_text("fake")

            with self._with_roots(root):
                result = resolve_trusted_path(target)

            self.assertEqual(result, target.resolve())

    def test_absolute_path_outside_every_approved_root_is_rejected(self) -> None:
        """Being absolute is not itself trust -- the old resolver accepted
        any absolute path outright; this one still requires containment."""
        with TemporaryDirectory() as root_dir, TemporaryDirectory() as attacker_dir:
            root = Path(root_dir)
            attacker_exe = Path(attacker_dir) / "evil.exe"
            attacker_exe.write_text("fake")

            with self._with_roots(root):
                with self.assertRaises(UntrustedRuntimePath):
                    resolve_trusted_path(attacker_exe)

    def test_traversal_is_rejected_before_any_search(self) -> None:
        with TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            with self._with_roots(root):
                with self.assertRaises(UntrustedRuntimePath):
                    resolve_trusted_path("../../evil.exe")

    def test_not_found_error_lists_what_was_searched(self) -> None:
        with TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            with self._with_roots(root):
                with self.assertRaisesRegex(FileNotFoundError, "piper.exe"):
                    resolve_trusted_path("piper.exe")


if __name__ == "__main__":
    unittest.main()
