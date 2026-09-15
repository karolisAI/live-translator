import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from live_translator.asset_manifest import load_manifest
from live_translator.cli import build_config, build_parser
from live_translator.config import AppConfig, TtsSettings, TranslationSettings
from live_translator.tts.voices import VOICE_MODELS, voice_model


class VoiceSelectionTests(unittest.TestCase):
    def config(self, language="de", engine="piper"):
        return AppConfig(
            tts=TtsSettings(engine=engine, model_path="models/tts/custom.onnx"),
            translation=TranslationSettings(target_language=language),
        )

    def build(self, flags, config=None, command="meeting"):
        args = build_parser().parse_args([command, *flags])
        with patch("live_translator.cli.load_config", return_value=config or self.config()):
            return build_config(args)

    def test_both_genders_for_both_languages(self):
        for language in VOICE_MODELS:
            for gender, model in VOICE_MODELS[language].items():
                with self.subTest(language=language, gender=gender):
                    config = self.build(["--voice", gender], self.config(language))
                    self.assertEqual(config.tts.model_path, model)

    def test_omitted_selection_preserves_profile(self):
        self.assertEqual(self.build([]).tts.model_path, "models/tts/custom.onnx")

    def test_meeting_accepts_explicit_model(self):
        self.assertEqual(self.build(["--tts-model", "models/tts/test.onnx"]).tts.model_path,
                         "models/tts/test.onnx")

    def test_conflicting_selection_is_rejected(self):
        for flag in ("--tts-model", "--tts-voice"):
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, "not both"):
                self.build(["--voice", "female", flag, "custom"])

    def test_non_piper_engine_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires the Piper"):
            self.build(["--voice", "female"], self.config(engine="none"))

    def test_engine_override_can_select_voice_without_profile_model(self):
        config = replace(self.config(engine="none"), tts=TtsSettings())
        self.assertEqual(self.build(["--tts-engine", "piper", "--voice", "female"], config).tts.model_path,
                         voice_model("de", "female"))

    def test_target_override_is_used(self):
        self.assertEqual(self.build(["--voice", "female", "--target-language", "en"],
                                    command="loopback").tts.model_path, voice_model("en", "female"))

    def test_unsupported_language_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "No bundled"):
            self.build(["--voice", "female"], self.config("fr"))

    def test_registered_models_and_configs_are_manifest_protected(self):
        root = Path(__file__).resolve().parents[1]
        manifest = load_manifest(root / "packaging/runtime-assets.manifest.json")
        paths = {asset.path.as_posix() for asset in manifest.assets}
        for models in VOICE_MODELS.values():
            for model in models.values():
                self.assertIn(model, paths)
                self.assertIn(model + ".json", paths)


if __name__ == "__main__":
    unittest.main()
