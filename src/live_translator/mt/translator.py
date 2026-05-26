from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from live_translator.config import TranslationSettings
from live_translator.errors import MissingDependency
from live_translator.mt.argos_runtime import configure_argos_runtime
from live_translator.runtime import resolve_runtime_path


class TranslationEngine:
    def __init__(self, settings: TranslationSettings) -> None:
        self._settings = settings
        self._translator: Any | None = None
        self._tokenizer: Any | None = None
        self._target_prefix = ""

    def translate(self, text: str) -> str:
        if not text:
            return ""

        engine = self._settings.engine.lower()
        if engine in {"none", "identity", "off"}:
            return text
        if engine == "argos":
            return self._translate_argos(text)

        raise ValueError(f"Unsupported translation engine: {self._settings.engine}")

    def _translate_argos(self, text: str) -> str:
        configure_argos_runtime()
        try:
            import ctranslate2
            import sentencepiece as spm
        except ImportError as exc:
            raise MissingDependency(
                "Missing dependency 'ctranslate2' or 'sentencepiece'. Install dependencies with: python -m pip install -e ."
            ) from exc

        package_path = _argos_package_path(self._settings.source_language, self._settings.target_language)
        model_path = package_path / "model"
        sentencepiece_path = package_path / "sentencepiece.model"
        if not model_path.exists():
            raise FileNotFoundError(f"Argos CTranslate2 model not found: {model_path}")
        if not sentencepiece_path.exists():
            raise FileNotFoundError(f"Argos SentencePiece model not found: {sentencepiece_path}")

        if self._translator is None:
            self._translator = ctranslate2.Translator(str(model_path))
        if self._tokenizer is None:
            self._tokenizer = spm.SentencePieceProcessor(model_file=str(sentencepiece_path))
            self._target_prefix = _target_prefix(package_path)

        source_tokens = self._tokenizer.encode(text, out_type=str)
        target_prefix = [[self._target_prefix]] if self._target_prefix else None
        batches = self._translator.translate_batch(
            [source_tokens],
            target_prefix=target_prefix,
            replace_unknowns=True,
            beam_size=1,
            num_hypotheses=1,
        )
        target_tokens = batches[0].hypotheses[0]
        translated = self._tokenizer.decode_pieces(target_tokens)
        if self._target_prefix and translated.startswith(self._target_prefix):
            translated = translated[len(self._target_prefix) :]
        return translated.replace("_", " ").strip()


def _argos_package_path(source_language: str, target_language: str) -> Path:
    package_name = f"{source_language}_{target_language}"
    env_dir = os.getenv("ARGOS_PACKAGES_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir) / package_name)
    candidates.append(resolve_runtime_path(Path("models") / "argos" / "packages" / package_name))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Bundled Argos package not found for {source_language} -> {target_language}.")


def _target_prefix(package_path: Path) -> str:
    metadata_path = package_path / "metadata.json"
    if not metadata_path.exists():
        return ""
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return str(metadata.get("target_prefix", ""))
