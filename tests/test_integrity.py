import hashlib
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from live_translator.errors import AssetIntegrityError, UntrustedRuntimePath
from live_translator.integrity import resolve_asset_path, sha256_file, verify_asset


class RuntimeAssetIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.relative_path = "models/example.bin"
        self.content = b"approved runtime asset\x00\x01"
        self.asset = self.root / "models" / "example.bin"
        self.asset.parent.mkdir(parents=True)
        self.asset.write_bytes(self.content)
        self.sha256 = hashlib.sha256(self.content).hexdigest()

    def test_valid_asset_is_accepted_and_resolved(self) -> None:
        result = verify_asset(
            self.root,
            self.relative_path,
            expected_size=len(self.content),
            expected_sha256=self.sha256,
        )

        self.assertEqual(result, self.asset.resolve())

    def test_one_byte_modification_is_rejected(self) -> None:
        changed = bytearray(self.content)
        changed[-1] ^= 1
        self.asset.write_bytes(changed)

        with self.assertRaisesRegex(AssetIntegrityError, "SHA-256"):
            verify_asset(
                self.root,
                self.relative_path,
                expected_size=len(self.content),
                expected_sha256=self.sha256,
            )

    def test_missing_asset_is_rejected(self) -> None:
        self.asset.unlink()

        with self.assertRaisesRegex(AssetIntegrityError, "missing"):
            verify_asset(
                self.root,
                self.relative_path,
                expected_size=len(self.content),
                expected_sha256=self.sha256,
            )

    def test_incorrect_expected_size_is_rejected_before_hashing(self) -> None:
        with self.assertRaisesRegex(AssetIntegrityError, "unexpected size"):
            verify_asset(
                self.root,
                self.relative_path,
                expected_size=len(self.content) + 1,
                expected_sha256=self.sha256,
            )

    def test_incorrect_expected_hash_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssetIntegrityError, "SHA-256"):
            verify_asset(
                self.root,
                self.relative_path,
                expected_size=len(self.content),
                expected_sha256="0" * 64,
            )

    def test_posix_absolute_manifest_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(UntrustedRuntimePath, "relative"):
            resolve_asset_path(self.root, "/models/example.bin")

    def test_windows_drive_manifest_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(UntrustedRuntimePath, "drive"):
            resolve_asset_path(self.root, "C:/models/example.bin")

    def test_parent_traversal_is_rejected(self) -> None:
        with self.assertRaisesRegex(UntrustedRuntimePath, "relative"):
            resolve_asset_path(self.root, "../outside.bin")

    def test_windows_separator_is_rejected(self) -> None:
        with self.assertRaisesRegex(UntrustedRuntimePath, "separators"):
            resolve_asset_path(self.root, r"models\example.bin")

    def test_empty_path_component_is_rejected_before_normalization(self) -> None:
        with self.assertRaisesRegex(UntrustedRuntimePath, "empty"):
            resolve_asset_path(self.root, "models//example.bin")

    def test_current_directory_component_is_rejected_before_normalization(self) -> None:
        with self.assertRaisesRegex(UntrustedRuntimePath, "empty"):
            resolve_asset_path(self.root, "models/./example.bin")

    def test_windows_drive_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(UntrustedRuntimePath, "drive"):
            resolve_asset_path(self.root, "C:/models/example.bin")

    def test_symlink_resolving_outside_root_is_rejected(self) -> None:
        with TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "outside.bin"
            outside.write_bytes(self.content)
            link = self.root / "models" / "linked.bin"
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"This process cannot create file symlinks: {exc}")

            with self.assertRaisesRegex(UntrustedRuntimePath, "outside"):
                resolve_asset_path(self.root, "models/linked.bin")

    def test_invalid_expected_size_is_rejected(self) -> None:
        for value in (-1, 1.5, True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "expected_size"):
                verify_asset(
                    self.root,
                    self.relative_path,
                    expected_size=value,  # type: ignore[arg-type]
                    expected_sha256=self.sha256,
                )

    def test_invalid_expected_hash_is_rejected(self) -> None:
        for value in ("A" * 64, "0" * 63, "g" * 64):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "expected_sha256"):
                verify_asset(
                    self.root,
                    self.relative_path,
                    expected_size=len(self.content),
                    expected_sha256=value,
                )

    def test_sha256_file_streams_all_chunks(self) -> None:
        self.assertEqual(sha256_file(self.asset, chunk_size=3), self.sha256)

    def test_sha256_file_rejects_non_positive_chunk_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "chunk_size"):
            sha256_file(self.asset, chunk_size=0)


if __name__ == "__main__":
    unittest.main()
