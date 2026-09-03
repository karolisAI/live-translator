import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from live_translator.asset_manifest import load_manifest, parse_manifest, verify_manifest
from live_translator.errors import AssetIntegrityError, ManifestValidationError


def _valid_manifest() -> dict:
    return {
        "schema_version": 1,
        "manifest_id": "live-translator-runtime-assets-v1",
        "protected_roots": [
            {
                "path": "tools/piper",
                "component": "piper-runtime",
                "reject_unlisted": True,
                "exclude": [],
            }
        ],
        "assets": [
            {
                "path": "tools/piper/piper.exe",
                "sha256": "a" * 64,
                "size": 42,
                "component": "piper-runtime",
                "version": "2023.11.14-2",
                "source": "https://example.invalid/piper.zip",
            }
        ],
    }


class AssetManifestTests(unittest.TestCase):
    def test_valid_manifest_is_parsed_into_immutable_records(self) -> None:
        manifest = parse_manifest(_valid_manifest())

        self.assertEqual(manifest.schema_version, 1)
        self.assertEqual(manifest.protected_roots[0].path.as_posix(), "tools/piper")
        self.assertEqual(manifest.assets[0].sha256, "a" * 64)

    def test_load_manifest_reads_utf8_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(json.dumps(_valid_manifest()), encoding="utf-8")

            manifest = load_manifest(path)

        self.assertEqual(manifest.manifest_id, "live-translator-runtime-assets-v1")

    def test_missing_manifest_is_reported_as_validation_error(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ManifestValidationError, "could not be read"):
                load_manifest(Path(temp_dir) / "missing.json")

    def test_duplicate_json_object_key_is_rejected(self) -> None:
        text = (
            '{"schema_version":1,"schema_version":1,"manifest_id":"x",'
            '"protected_roots":[],"assets":[]}'
        )
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(text, encoding="utf-8")

            with self.assertRaisesRegex(ManifestValidationError, "Duplicate JSON"):
                load_manifest(path)

    def test_unsupported_schema_version_is_rejected(self) -> None:
        document = _valid_manifest()
        document["schema_version"] = 2

        with self.assertRaisesRegex(ManifestValidationError, "schema_version"):
            parse_manifest(document)

    def test_unknown_and_missing_fields_are_rejected(self) -> None:
        for mutate in (
            lambda document: document.update({"unexpected": True}),
            lambda document: document.pop("manifest_id"),
            lambda document: document["assets"][0].update({"unexpected": True}),
            lambda document: document["assets"][0].pop("source"),
        ):
            document = _valid_manifest()
            mutate(document)
            with self.subTest(document=document), self.assertRaisesRegex(
                ManifestValidationError, "invalid fields"
            ):
                parse_manifest(document)

    def test_duplicate_asset_paths_are_rejected_case_insensitively(self) -> None:
        document = _valid_manifest()
        duplicate = deepcopy(document["assets"][0])
        duplicate["path"] = "TOOLS/PIPER/PIPER.EXE"
        document["assets"].append(duplicate)

        with self.assertRaisesRegex(ManifestValidationError, "Duplicate asset"):
            parse_manifest(document)

    def test_asset_outside_every_protected_root_is_rejected(self) -> None:
        document = _valid_manifest()
        document["assets"][0]["path"] = "models/asr/model.onnx"

        with self.assertRaisesRegex(ManifestValidationError, "exactly one"):
            parse_manifest(document)

    def test_overlapping_roots_make_asset_ownership_ambiguous(self) -> None:
        document = _valid_manifest()
        document["protected_roots"].append(
            {
                "path": "tools/piper/subdir",
                "component": "piper-runtime",
                "reject_unlisted": True,
                "exclude": [],
            }
        )
        document["assets"][0]["path"] = "tools/piper/subdir/file.bin"

        with self.assertRaisesRegex(ManifestValidationError, "exactly one"):
            parse_manifest(document)

    def test_asset_component_must_match_owning_root(self) -> None:
        document = _valid_manifest()
        document["assets"][0]["component"] = "parakeet-model"

        with self.assertRaisesRegex(ManifestValidationError, "does not match"):
            parse_manifest(document)

    def test_arbitrary_exclusion_is_rejected(self) -> None:
        document = _valid_manifest()
        document["protected_roots"][0]["exclude"] = ["evil/**"]

        with self.assertRaisesRegex(ManifestValidationError, "cannot choose"):
            parse_manifest(document)

    def test_parakeet_cache_is_the_only_approved_exclusion(self) -> None:
        document = _valid_manifest()
        document["protected_roots"][0] = {
            "path": "models/asr/parakeet-tdt-0.6b-v3",
            "component": "parakeet-model",
            "reject_unlisted": True,
            "exclude": [".cache/**"],
        }
        document["assets"][0].update(
            {
                "path": "models/asr/parakeet-tdt-0.6b-v3/config.json",
                "component": "parakeet-model",
            }
        )

        self.assertEqual(parse_manifest(document).protected_roots[0].exclude, (".cache/**",))

    def test_invalid_asset_identity_is_rejected(self) -> None:
        for field, value in (("size", -1), ("sha256", "A" * 64)):
            document = _valid_manifest()
            document["assets"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ManifestValidationError):
                parse_manifest(document)

    def test_invalid_manifest_path_is_rejected(self) -> None:
        document = _valid_manifest()
        document["assets"][0]["path"] = "tools/piper/../evil.exe"

        with self.assertRaisesRegex(ManifestValidationError, r"\.\."):
            parse_manifest(document)

    def test_reject_unlisted_must_be_true(self) -> None:
        document = _valid_manifest()
        document["protected_roots"][0]["reject_unlisted"] = False

        with self.assertRaisesRegex(ManifestValidationError, "must be true"):
            parse_manifest(document)

    def test_verify_manifest_checks_hash_and_returns_verified_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset = root / "tools" / "piper" / "piper.exe"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"approved")
            document = _valid_manifest()
            document["assets"][0]["size"] = len(b"approved")
            document["assets"][0]["sha256"] = hashlib.sha256(b"approved").hexdigest()

            result = verify_manifest(parse_manifest(document), root)

        self.assertEqual(result["tools/piper/piper.exe"], asset.resolve())

    def test_verify_manifest_rejects_unlisted_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset = root / "tools" / "piper" / "piper.exe"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"approved")
            (asset.parent / "injected.dll").write_bytes(b"bad")
            document = _valid_manifest()
            document["assets"][0]["size"] = len(b"approved")
            document["assets"][0]["sha256"] = hashlib.sha256(b"approved").hexdigest()

            with self.assertRaisesRegex(AssetIntegrityError, "unlisted"):
                verify_manifest(parse_manifest(document), root)

    def test_verify_manifest_rejects_modified_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset = root / "tools" / "piper" / "piper.exe"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"modified")

            with self.assertRaisesRegex(AssetIntegrityError, "unexpected size"):
                verify_manifest(parse_manifest(_valid_manifest()), root)

    def test_verify_manifest_can_select_one_component(self) -> None:
        document = _valid_manifest()
        document["protected_roots"].append(
            {
                "path": "models/tts",
                "component": "piper-voice",
                "reject_unlisted": True,
                "exclude": [],
            }
        )
        document["assets"].append(
            {
                "path": "models/tts/voice.onnx",
                "sha256": "b" * 64,
                "size": 99,
                "component": "piper-voice",
                "version": "1",
                "source": "https://example.invalid/voice.onnx",
            }
        )
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "tools" / "piper" / "piper.exe"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b"approved")
            document["assets"][0]["size"] = len(b"approved")
            document["assets"][0]["sha256"] = hashlib.sha256(b"approved").hexdigest()

            result = verify_manifest(
                parse_manifest(document), root, components={"piper-runtime"}
            )

        self.assertEqual(set(result), {"tools/piper/piper.exe"})

    def test_parakeet_cache_exclusion_covers_nested_metadata(self) -> None:
        document = _valid_manifest()
        document["protected_roots"][0] = {
            "path": "models/asr/parakeet-tdt-0.6b-v3",
            "component": "parakeet-model",
            "reject_unlisted": True,
            "exclude": [".cache/**"],
        }
        document["assets"][0].update(
            {
                "path": "models/asr/parakeet-tdt-0.6b-v3/config.json",
                "component": "parakeet-model",
                "size": len(b"approved"),
                "sha256": hashlib.sha256(b"approved").hexdigest(),
            }
        )
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir) / "relocated-model"
            directory.mkdir()
            (directory / "config.json").write_bytes(b"approved")
            metadata = directory / ".cache" / "huggingface" / "download" / "config.metadata"
            metadata.parent.mkdir(parents=True)
            metadata.write_text("metadata", encoding="utf-8")

            from live_translator.asset_manifest import verify_manifest_root

            verify_manifest_root(
                parse_manifest(document),
                "models/asr/parakeet-tdt-0.6b-v3",
                directory,
            )


if __name__ == "__main__":
    unittest.main()
