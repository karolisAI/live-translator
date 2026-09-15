"""Bundled Piper voice selection; no discovery or downloads at meeting startup."""

VOICE_MODELS = {
    "de": {
        "male": "models/tts/de_DE-thorsten-medium.onnx",
        "female": "models/tts/de_DE-kerstin-low.onnx",
    },
    "en": {
        "male": "models/tts/en_US-hfc_male-medium.onnx",
        "female": "models/tts/en_US-hfc_female-medium.onnx",
    },
}


def voice_model(language: str, voice: str) -> str:
    try:
        return VOICE_MODELS[language.lower()][voice.lower()]
    except KeyError as exc:
        raise ValueError(
            f"No bundled {voice!r} Piper voice for target language {language!r}. "
            "Supported target languages: en, de."
        ) from exc
