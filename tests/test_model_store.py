"""The prepared model on disk, and the guarantee that meeting mode stays offline.

The expensive part of that guarantee is not ours: `onnx_asr` decides whether a
resolved model comes off disk or off the network. So these tests block the two
Hugging Face entry points at the bottom of the stack -- `snapshot_download` and
`hf_hub_download` -- and let anything that would reach them fail loudly. A test
that passes with those blocked is a test that could have run on a machine with
no network at all.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from live_translator.asr.model_store import (
    REVISION_FILE,
    download_model,
    model_dir,
    recorded_revision,
    required_patterns,
    verify_local_model,
)
from live_translator.config import AsrSettings
from live_translator.defaults import (
    ASR_MODEL_DIR,
    ASR_MODEL_REPO,
    ASR_MODEL_REVISION,
    DEFAULT_ASR_MODEL,
)
from live_translator.errors import ModelNotPrepared

INT8_FILES = (
    "config.json",
    "vocab.txt",
    "encoder-model.int8.onnx",
    "decoder_joint-model.int8.onnx",
)


def prepare_dir(directory: Path, files=INT8_FILES, *, revision=ASR_MODEL_REVISION) -> Path:
    """Write a model directory that looks prepared, without the 640 MB."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in files:
        (directory / name).write_text("stand-in for model bytes", encoding="utf-8")
    if revision is not None:
        (directory / REVISION_FILE).write_text(f"{revision}\n", encoding="utf-8")
    return directory


def settings_for(directory: Path, **overrides) -> AsrSettings:
    return replace(AsrSettings(model_dir=str(directory)), **overrides)


@contextmanager
def network_blocked():
    """Fail loudly on any attempt to reach Hugging Face.

    Patched on `huggingface_hub` itself rather than on onnx-asr, because
    onnx-asr imports the two functions inside the call that uses them. Blocking
    the source covers that and every other caller.
    """
    def refuse(*args, **kwargs):
        raise AssertionError(
            f"the network was contacted: {args!r} {kwargs!r}. Meeting mode must "
            f"read the prepared model off disk."
        )

    with patch("huggingface_hub.snapshot_download", side_effect=refuse):
        with patch("huggingface_hub.hf_hub_download", side_effect=refuse):
            yield


class RequiredPatternsTests(unittest.TestCase):
    def test_matches_the_files_onnx_asr_asks_for(self) -> None:
        """Our file list is a copy of onnx-asr's, so it has to be checked
        against the original. If onnx-asr renames a file or changes its
        quantization suffix, validation would otherwise start passing
        directories that cannot actually load."""
        from onnx_asr.models.nemo import NemoConformerTdt

        for quantization in (None, "int8"):
            with self.subTest(quantization=quantization):
                expected = set(NemoConformerTdt._get_model_files(quantization).values())

                self.assertTrue(expected.issubset(set(required_patterns(quantization))))

    def test_quantization_selects_its_own_model_files(self) -> None:
        self.assertIn("encoder-model?int8.onnx", required_patterns("int8"))
        self.assertIn("encoder-model.onnx", required_patterns(None))

    def test_config_json_is_required_beyond_what_onnx_asr_demands(self) -> None:
        """onnx-asr treats config.json as optional and falls back to default
        feature dimensions. Recognizing with the wrong ones would be silent, so
        a directory missing it is rejected instead."""
        self.assertIn("config.json", required_patterns("int8"))


class ModelDirTests(unittest.TestCase):
    def test_defaults_to_the_pinned_location(self) -> None:
        self.assertEqual(model_dir(AsrSettings()).name, Path(ASR_MODEL_DIR).name)

    def test_configured_directory_wins(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(model_dir(settings_for(Path(tmp))), Path(tmp))

    def test_is_absolute_even_when_nothing_is_prepared(self) -> None:
        """`prepare-models` and `meeting` are separate runs from wherever the
        user's shell happens to be. A relative answer would let preparation
        write somewhere meeting startup never looks."""
        self.assertTrue(model_dir(AsrSettings()).is_absolute())
        self.assertTrue(model_dir(AsrSettings(model_dir="models/asr/elsewhere")).is_absolute())

    def test_does_not_follow_the_working_directory(self) -> None:
        import os

        with TemporaryDirectory() as tmp:
            original = os.getcwd()
            try:
                os.chdir(tmp)
                from_elsewhere = model_dir(AsrSettings())
            finally:
                os.chdir(original)

        self.assertEqual(from_elsewhere, model_dir(AsrSettings()))


class VerifyLocalModelTests(unittest.TestCase):
    def test_complete_directory_passes_without_network(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = prepare_dir(Path(tmp) / "parakeet")

            with network_blocked():
                self.assertEqual(verify_local_model(settings_for(directory)), directory)

    def test_missing_directory_fails_without_reaching_the_network(self) -> None:
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "never-prepared"

            with network_blocked():
                with self.assertRaises(ModelNotPrepared) as caught:
                    verify_local_model(settings_for(missing))

        self.assertIn("prepare-models", str(caught.exception))

    def test_incomplete_directory_names_what_is_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = prepare_dir(Path(tmp) / "parakeet", files=("config.json", "vocab.txt"))

            with network_blocked():
                with self.assertRaises(ModelNotPrepared) as caught:
                    verify_local_model(settings_for(directory))

        self.assertIn("encoder-model?int8.onnx", str(caught.exception))

    def test_directory_prepared_for_another_quantization_is_rejected(self) -> None:
        """The float32 and int8 exports are different files. Loading int8
        against a float32 directory is a cache miss, which is exactly the case
        that used to fall through to a download."""
        with TemporaryDirectory() as tmp:
            directory = prepare_dir(
                Path(tmp) / "parakeet",
                files=("config.json", "vocab.txt", "encoder-model.onnx", "decoder_joint-model.onnx"),
            )

            with network_blocked():
                with self.assertRaises(ModelNotPrepared) as caught:
                    verify_local_model(settings_for(directory, compute_type="int8"))

        self.assertIn("compute_type", str(caught.exception))

    def test_revision_mismatch_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = prepare_dir(Path(tmp) / "parakeet", revision="0" * 40)

            with self.assertRaises(ModelNotPrepared) as caught:
                verify_local_model(settings_for(directory))

        self.assertIn(ASR_MODEL_REVISION, str(caught.exception))

    def test_unstamped_directory_is_tolerated(self) -> None:
        """A model staged by hand or by IT has no revision file. Refusing it
        would block the one workflow that never touches the network at all."""
        with TemporaryDirectory() as tmp:
            directory = prepare_dir(Path(tmp) / "parakeet", revision=None)

            self.assertIsNone(recorded_revision(directory))
            self.assertEqual(verify_local_model(settings_for(directory)), directory)

    def test_unpinned_model_without_a_directory_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "no prepared local assets"):
            verify_local_model(AsrSettings(model="nemo-parakeet-tdt-0.6b-v2"))


class DownloadModelTests(unittest.TestCase):
    """The one function allowed to reach the network."""

    def test_pins_the_revision_and_stamps_the_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp) / "parakeet"
            settings = settings_for(directory)

            def fake_download(repo_id, **kwargs):
                prepare_dir(Path(kwargs["local_dir"]), revision=None)
                return kwargs["local_dir"]

            with patch("huggingface_hub.snapshot_download", side_effect=fake_download) as spy:
                download_model(settings, announce=False)

            repo_id, kwargs = spy.call_args.args[0], spy.call_args.kwargs
            self.assertEqual(repo_id, ASR_MODEL_REPO)
            self.assertEqual(kwargs["revision"], ASR_MODEL_REVISION)
            self.assertEqual(recorded_revision(directory), ASR_MODEL_REVISION)

    def test_fetches_only_the_configured_quantization(self) -> None:
        """The float32 encoder keeps its weights in a sidecar larger than
        everything else combined. Preparing int8 must not drag it down."""
        with TemporaryDirectory() as tmp:
            directory = Path(tmp) / "parakeet"

            def fake_download(repo_id, **kwargs):
                prepare_dir(Path(kwargs["local_dir"]), revision=None)
                return kwargs["local_dir"]

            with patch("huggingface_hub.snapshot_download", side_effect=fake_download) as spy:
                download_model(settings_for(directory, compute_type="int8"), announce=False)

            patterns = spy.call_args.kwargs["allow_patterns"]

        self.assertIn("encoder-model?int8.onnx", patterns)
        self.assertNotIn("encoder-model.onnx", patterns)
        self.assertNotIn("*.onnx?data", patterns)

    def test_verifies_what_it_downloaded(self) -> None:
        """A download that returns a partial directory must not be reported as
        a successful preparation."""
        with TemporaryDirectory() as tmp:
            directory = Path(tmp) / "parakeet"

            with patch("huggingface_hub.snapshot_download", side_effect=lambda *a, **k: str(directory)):
                with self.assertRaises(ModelNotPrepared):
                    download_model(settings_for(directory), announce=False)

    def test_refuses_a_model_it_has_no_pin_for(self) -> None:
        with patch("huggingface_hub.snapshot_download") as spy:
            with self.assertRaisesRegex(ValueError, "no prepared local assets"):
                download_model(AsrSettings(model="whisper-base"), announce=False)
            spy.assert_not_called()


class OnnxAsrOfflineContractTests(unittest.TestCase):
    """onnx-asr is what actually decides disk versus network, so the property
    this feature rests on belongs in a test: an existing directory makes its
    resolver offline, and resolution then never reaches Hugging Face.

    Without this, a change in onnx-asr could restore the download fallback and
    every other test here would still pass.
    """

    def test_existing_directory_marks_the_resolver_offline(self) -> None:
        from onnx_asr.loader import create_asr_resolver

        with TemporaryDirectory() as tmp:
            directory = prepare_dir(Path(tmp) / "parakeet")

            resolver = create_asr_resolver(DEFAULT_ASR_MODEL, directory)

            self.assertTrue(resolver.offline)

    def test_resolution_reads_the_directory_instead_of_downloading(self) -> None:
        from onnx_asr.loader import create_asr_resolver

        with TemporaryDirectory() as tmp:
            directory = prepare_dir(Path(tmp) / "parakeet")

            with network_blocked():
                resolver = create_asr_resolver(DEFAULT_ASR_MODEL, directory)
                resolved = resolver.resolve_model(quantization="int8")

        self.assertEqual(resolved["encoder"], directory / "encoder-model.int8.onnx")
        self.assertEqual(resolved["vocab"], directory / "vocab.txt")


if __name__ == "__main__":
    unittest.main()
