"""ASR metadata shared by modules that cannot import each other.

`asr` imports `config` (for `AsrSettings`), so `config` cannot import anything
under `asr` in return -- and reaching for an `asr` submodule runs that package's
`__init__` either way, so there is no back door. Both sides still have to agree
on which engines exist and which model is the default, and `profiles` needs the
model name when it writes a profile, so those facts live here, in a module that
imports nothing.

`ASR_ENGINES` maps a config `asr.engine` value onto the class implementing it,
written as "module:attribute" so this module stays import-free. `create_asr`
resolves an entry, `config` validates against the keys, and the CLI offers them
as `--asr-engine` choices: adding an engine here reaches all three.
"""

from __future__ import annotations

__all__ = [
    "ASR_ENGINES",
    "ASR_MODEL_DIR",
    "ASR_MODEL_REPO",
    "ASR_MODEL_REVISION",
    "DEFAULT_ASR_ENGINE",
    "DEFAULT_ASR_MODEL",
    "SUPPORTED_ASR_ENGINES",
]

DEFAULT_ASR_MODEL = "nemo-parakeet-tdt-0.6b-v3"

ASR_ENGINES: dict[str, str] = {
    "parakeet": "live_translator.asr.parakeet_engine:ParakeetAsr",
}

SUPPORTED_ASR_ENGINES: tuple[str, ...] = tuple(ASR_ENGINES)

DEFAULT_ASR_ENGINE = "parakeet"
"""Engine used when a profile or `AsrSettings` does not name one."""

ASR_MODEL_REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
"""Hugging Face repository holding the ONNX export of `DEFAULT_ASR_MODEL`.

onnx-asr keeps the same mapping in its own `resolver.model_repos`, but never
exposes it, and never lets a caller pin a revision. Recording it here is what
makes `prepare-models` able to fetch the model itself, at a fixed revision,
without going through onnx-asr's downloader at all.
"""

ASR_MODEL_REVISION = "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce"
"""Commit pinned for reproducible preparation.

A commit hash rather than `main` on purpose: `snapshot_download` resolves a
branch name by asking the Hub what it points at, so `main` would let the model
change between two preparations of the same application build.
"""

ASR_MODEL_DIR = "models/asr/parakeet-tdt-0.6b-v3"
"""Where `prepare-models` writes the model, relative to the runtime root.

Alongside `models/argos` and `models/tts` so all three prepared assets are
found, validated and packaged the same way.
"""
