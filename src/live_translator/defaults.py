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
