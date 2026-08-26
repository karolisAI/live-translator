"""The prepared Parakeet model on disk: where it lives, whether it is complete,
and the one place allowed to fetch it.

Meeting mode must not reach the network, and the guarantee here is structural
rather than a flag. `onnx_asr.load_model(model, path)` hands the path to
`onnx_asr.resolver.Resolver`, which sets `offline=True` for a directory that
already exists and then returns that directory's files directly -- its
`_download_model` branch is never entered. `verify_local_model` runs first so
the directory is known to exist, which is what makes that branch unreachable
rather than merely unlikely.

`download_model` is the exception, and the only function in the application
that contacts a model host. It is reached from `live-translator prepare-models`
and from nowhere else, so "did meeting startup download anything" is a question
about which functions were called, not about what the network happened to be
doing at the time.

Preparing here rather than through onnx-asr also buys the revision pin: onnx-asr
never passes `revision` to `snapshot_download`, so anything it fetches tracks
whatever `main` points at that day.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from live_translator.asr.recognizer import normalize_quantization
from live_translator.defaults import (
    ASR_MODEL_DIR,
    ASR_MODEL_REPO,
    ASR_MODEL_REVISION,
    DEFAULT_ASR_MODEL,
)
from live_translator.errors import MissingDependency, ModelNotPrepared
from live_translator.runtime import approved_runtime_roots, user_data_dir

__all__ = [
    "REVISION_FILE",
    "download_model",
    "model_dir",
    "recorded_revision",
    "required_patterns",
    "verify_local_model",
]

REVISION_FILE = "revision.txt"
"""Records which `ASR_MODEL_REVISION` produced the directory's contents.

Written by `download_model`. A directory populated by hand will not have one,
which is tolerated; a directory carrying a *different* revision is not, because
it means these files are not the ones this build was tested against.
"""

_PREPARE_COMMAND = "live-translator prepare-models --profile <name>"


def model_dir(settings: Any) -> Path:
    """Directory holding the prepared model for `settings`.

    Always absolute, and always the same directory for a given installation:
    preparation and meeting startup are separate runs, often from different
    working directories, and they have to agree on one location without the
    user having to spell it out.

    Returns a path whether or not it exists -- `verify_local_model` is what
    decides that, so callers get one error with one message rather than two.
    """
    configured = Path(getattr(settings, "model_dir", None) or ASR_MODEL_DIR)
    if configured.is_absolute():
        # An explicit absolute directory is honoured as given -- including a
        # model staged by IT outside the app's own roots. This is not routed
        # through the trusted-path resolver on purpose: the model is data, not
        # an executable, and refusing an external absolute location would break
        # the supported "point at a shared/staged model" path.
        return configured

    # An already-prepared directory wins wherever it sits among the approved
    # runtime roots -- never the current working directory -- so a packaged
    # build that ships one is found the same way models/argos and models/tts
    # are, without a checkout the shell happened to launch from standing in.
    for root in approved_runtime_roots():
        candidate = root / configured
        if candidate.is_dir():
            return candidate.resolve()
    return _preparation_root() / configured


def _preparation_root() -> Path:
    """Base directory preparation writes into when nothing is prepared yet.

    An installed build must not write beside its executable, which normally
    sits somewhere unwritable, and neither build may write relative to the
    current directory -- `prepare-models` and `meeting` are run from wherever
    the user's shell happens to be, and a model prepared into one of those
    would be invisible to the other.

    So an installed build uses the per-user location that already holds
    profiles, and a source checkout uses the checkout, beside the other
    prepared assets.
    """
    if getattr(sys, "frozen", False):
        return user_data_dir()
    # The source checkout root: this file is <repo>/src/live_translator/asr/
    # model_store.py, so the repository is four parents up. Computed directly
    # rather than via a runtime-root list so a dev override or root ordering
    # can never redirect where preparation writes.
    return Path(__file__).resolve().parents[3]


def required_patterns(quantization: str | None) -> tuple[str, ...]:
    """Glob patterns for the files a Parakeet TDT load needs.

    Mirrors `onnx_asr.models.nemo.NemoConformerTdt._get_model_files`, including
    its `?` wildcard: the quantized encoder ships as `encoder-model.int8.onnx`,
    and onnx-asr matches it with `encoder-model?int8.onnx` rather than naming
    the separator. Using the same patterns means this check passes exactly when
    onnx-asr's own resolution would, and `test_model_store` asserts the two
    lists still agree so they cannot drift apart silently.

    `config.json` is the one addition. onnx-asr treats it as optional and falls
    back to built-in defaults for `features_size` and `subsampling_factor`, but
    a directory missing it is not the directory `prepare-models` writes, and
    silently recognizing with different feature dimensions is worse than
    refusing to start.
    """
    suffix = f"?{quantization}" if quantization else ""
    return (
        "config.json",
        "vocab.txt",
        f"encoder-model{suffix}.onnx",
        f"decoder_joint-model{suffix}.onnx",
    )


def recorded_revision(directory: Path) -> str | None:
    """The revision `download_model` stamped on `directory`, if it stamped one."""
    path = directory / REVISION_FILE
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def verify_local_model(settings: Any) -> Path:
    """Check the prepared model is complete, and return its directory.

    Raises `ModelNotPrepared` before any audio device is opened, so a machine
    that was never prepared fails at startup with an instruction rather than
    part way through a meeting.
    """
    _require_preparable_model(settings)
    directory = model_dir(settings)

    if not directory.is_dir():
        raise ModelNotPrepared(
            f"The Parakeet model is not prepared. Expected it in '{directory}'. "
            f"Prepare it once on a machine with internet access: {_PREPARE_COMMAND}"
        )

    quantization = normalize_quantization(getattr(settings, "compute_type", None))
    missing = [
        pattern
        for pattern in required_patterns(quantization)
        if not any(path.is_file() for path in directory.glob(pattern))
    ]
    if missing:
        raise ModelNotPrepared(
            f"The prepared Parakeet model in '{directory}' is incomplete. Missing: "
            f"{', '.join(missing)}. Note that asr.compute_type "
            f"'{getattr(settings, 'compute_type', None)}' selects its own model "
            f"files, so a directory prepared for another setting will not do. "
            f"Re-prepare it with: {_PREPARE_COMMAND}"
        )

    found = recorded_revision(directory)
    if found is not None and found != ASR_MODEL_REVISION:
        raise ModelNotPrepared(
            f"The prepared Parakeet model in '{directory}' is revision {found}, "
            f"but this build expects {ASR_MODEL_REVISION}. Re-prepare it with: "
            f"{_PREPARE_COMMAND}"
        )
    return directory


def download_model(settings: Any, *, announce: bool = True) -> Path:
    """Fetch the pinned model into its local directory. Contacts the network.

    The only such function in the application. Everything else reads what this
    leaves behind.
    """
    _require_preparable_model(settings)
    directory = model_dir(settings)
    quantization = normalize_quantization(getattr(settings, "compute_type", None))

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - depends on install state
        raise MissingDependency(
            "Missing dependency 'huggingface_hub'. Install dependencies with: "
            "python -m pip install -e ."
        ) from exc

    if announce:
        print(f"Downloading {ASR_MODEL_REPO} at {ASR_MODEL_REVISION[:12]} into {directory}...")

    directory.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        ASR_MODEL_REPO,
        revision=ASR_MODEL_REVISION,
        local_dir=str(directory),
        allow_patterns=list(_download_patterns(quantization)),
    )
    (directory / REVISION_FILE).write_text(f"{ASR_MODEL_REVISION}\n", encoding="utf-8")

    verify_local_model(settings)
    if announce:
        print(f"Prepared {DEFAULT_ASR_MODEL} ({quantization or 'float32'}) in {directory}.")
    return directory


def _download_patterns(quantization: str | None) -> tuple[str, ...]:
    """Files to fetch: the required ones, plus any external tensor data.

    An ONNX graph too large for a single protobuf keeps its weights in a
    sidecar, which the float32 encoder uses and the int8 one does not. The
    pattern is quantization-specific rather than a blanket `*.onnx?data` so
    preparing int8 does not also drag down the float32 sidecar, which is larger
    than everything else combined.
    """
    required = required_patterns(quantization)
    return (*required, *(f"{pattern}?data" for pattern in required if pattern.endswith(".onnx")))


def _require_preparable_model(settings: Any) -> None:
    """Refuse a model this application has no prepared assets for.

    `--model` can name any onnx-asr model, and onnx-asr would happily fetch it.
    Only the pinned one has a recorded repository, revision and local
    directory, so anything else has to be pointed at its own directory
    explicitly through `asr.model_dir` -- which is also the escape hatch for a
    model staged by IT rather than by this command.
    """
    model = getattr(settings, "model", DEFAULT_ASR_MODEL)
    if model == DEFAULT_ASR_MODEL or getattr(settings, "model_dir", None):
        return
    raise ValueError(
        f"asr.model '{model}' has no prepared local assets. This build pins "
        f"'{DEFAULT_ASR_MODEL}'. Use that model, or set asr.model_dir to a "
        f"directory holding '{model}' prepared some other way."
    )
