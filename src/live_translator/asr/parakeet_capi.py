"""ctypes binding for parakeet.cpp's flat C-API (parakeet_capi.h, ABI v6).

Offline-only wrapper: this project uses Parakeet as a drop-in replacement for
faster-whisper inside the existing VAD-gated phrase pipeline (see
docs/01-architecture.md), not for the streaming/rolling-decode path. Only the
entry points that path needs are bound here.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Optional

import numpy as np

from live_translator.errors import MissingDependency
from live_translator.runtime import resolve_runtime_path

_DLL_NAMES = ["ggml-base.dll", "ggml-cpu.dll", "ggml.dll", "parakeet.dll"]


class ParakeetError(RuntimeError):
    """Raised when a parakeet.cpp C-API call fails."""


class _CtxHandle(ctypes.Structure):
    pass


_CtxPtr = ctypes.POINTER(_CtxHandle)

DECODER_DEFAULT = 0
DECODER_CTC = 1
DECODER_TDT_RNNT = 2


def _load_library() -> ctypes.CDLL:
    if sys.platform != "win32":
        raise MissingDependency("parakeet ASR engine currently only supports Windows (parakeet.dll)")

    tools_dir = resolve_runtime_path("tools/parakeet").resolve()
    if not tools_dir.is_dir():
        raise MissingDependency(
            f"Missing {tools_dir} — expected parakeet.dll and its ggml-*.dll dependencies there."
        )

    os.add_dll_directory(str(tools_dir))

    dll_path = tools_dir / "parakeet.dll"
    if not dll_path.is_file():
        raise MissingDependency(f"Missing {dll_path}")

    return ctypes.CDLL(str(dll_path))


_lib: Optional[ctypes.CDLL] = None

_THREAD_PIN_SYMBOL = "?set_num_threads@pk@@YAXH@Z"
_thread_pinning_available: Optional[bool] = None


class ParakeetCapabilityWarning(RuntimeWarning):
    """An optional, non-ABI parakeet.cpp capability isn't available in the
    loaded DLL. The engine still works -- this is about a degraded feature,
    not a load failure."""


def _get_lib() -> ctypes.CDLL:
    global _lib, _thread_pinning_available
    if _lib is None:
        lib = _load_library()

        lib.parakeet_capi_load.restype = _CtxPtr
        lib.parakeet_capi_load.argtypes = [ctypes.c_char_p]

        lib.parakeet_capi_free.restype = None
        lib.parakeet_capi_free.argtypes = [_CtxPtr]

        lib.parakeet_capi_transcribe_pcm.restype = ctypes.c_void_p
        lib.parakeet_capi_transcribe_pcm.argtypes = [
            _CtxPtr, ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]

        lib.parakeet_capi_transcribe_pcm_lang.restype = ctypes.c_void_p
        lib.parakeet_capi_transcribe_pcm_lang.argtypes = [
            _CtxPtr, ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_char_p,
        ]

        lib.parakeet_capi_transcribe_pcm_batch_json_lang.restype = ctypes.c_void_p
        lib.parakeet_capi_transcribe_pcm_batch_json_lang.argtypes = [
            _CtxPtr, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_int), ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_char_p,
        ]

        lib.parakeet_capi_free_string.restype = None
        lib.parakeet_capi_free_string.argtypes = [ctypes.c_void_p]

        lib.parakeet_capi_last_error.restype = ctypes.c_char_p
        lib.parakeet_capi_last_error.argtypes = [_CtxPtr]

        _lib = lib

        # Startup capability probe: pk::set_num_threads is NOT part of
        # parakeet_capi.h's stable ABI -- it only resolves because this DLL
        # was built with WINDOWS_EXPORT_ALL_SYMBOLS (see CMakeLists.txt),
        # which exposes internal C++ symbols under their mangled MSVC names.
        # A DLL built without that property, or with a different compiler
        # (different name mangling), will be missing this export. Probe once
        # at load time and say so loudly, rather than degrading silently on
        # first use of set_num_threads().
        _thread_pinning_available = hasattr(lib, _THREAD_PIN_SYMBOL)
        if not _thread_pinning_available:
            message = (
                f"parakeet.dll does not export '{_THREAD_PIN_SYMBOL}' (pk::set_num_threads). "
                "This DLL was likely built without WINDOWS_EXPORT_ALL_SYMBOLS, or with a "
                "different compiler/toolchain that mangles C++ names differently -- this "
                "symbol is NOT part of parakeet_capi.h's stable, documented ABI, so it is "
                "expected to vary across DLL builds. Effect: AsrSettings.cpu_threads is "
                "ignored; the engine runs at parakeet.cpp's own built-in default of 8 "
                "threads instead. (This does not affect transcribe_pcm_json/confidence "
                "output -- that goes through parakeet_capi_transcribe_pcm_batch_json_lang, "
                "a documented ABI v3+ entry point present in any correctly built DLL.) "
                "See tools/parakeet/BUILD.md for the exact CMake command used to build the "
                "vendored DLL this binding is validated against."
            )
            warnings.warn(message, ParakeetCapabilityWarning, stacklevel=2)
            print(f"[parakeet_capi] warning: {message}", file=sys.stderr)

    return _lib


def set_num_threads(n: int) -> None:
    """Pin the ggml compute thread count (library default: 8, empirically
    tuned — see ggml_graph.cpp's kDefaultThreads comment; more threads can
    regress throughput on many-core desktops via cross-CCD cache traffic).

    No-ops if the DLL doesn't export the underlying symbol -- see the
    ParakeetCapabilityWarning raised at load time in _get_lib() for why.
    """
    _get_lib()  # ensures _thread_pinning_available has been probed
    if not _thread_pinning_available:
        return
    fn = getattr(_lib, _THREAD_PIN_SYMBOL)
    fn.restype = None
    fn.argtypes = [ctypes.c_int]
    fn(n)


class ParakeetModel:
    """A loaded Parakeet GGUF model. Use as a context manager to auto-free."""

    def __init__(self, gguf_path: str | Path):
        self._lib = _get_lib()
        resolved = resolve_runtime_path(gguf_path).resolve()
        if not resolved.is_file():
            raise MissingDependency(f"Parakeet model not found: {resolved}")

        self._ctx = self._lib.parakeet_capi_load(str(resolved).encode("utf-8"))
        if not self._ctx:
            raise ParakeetError(f"failed to load Parakeet model from {resolved}")

    def __enter__(self) -> "ParakeetModel":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "_ctx", None):
            self._lib.parakeet_capi_free(self._ctx)
            self._ctx = None

    def _take_string(self, ptr: Optional[int]) -> str:
        if not ptr:
            raise ParakeetError(self._last_error())
        text = ctypes.cast(ptr, ctypes.c_char_p).value.decode("utf-8")
        self._lib.parakeet_capi_free_string(ptr)
        return text

    def _last_error(self) -> str:
        msg = self._lib.parakeet_capi_last_error(self._ctx)
        return msg.decode("utf-8") if msg else "unknown error"

    def transcribe_pcm(
        self, samples: np.ndarray, sample_rate: int,
        decoder: int = DECODER_DEFAULT, target_lang: Optional[str] = None,
    ) -> str:
        """`samples`: mono float32 numpy array in [-1, 1]."""
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        buf = samples.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        n = samples.shape[0]

        if target_lang:
            ptr = self._lib.parakeet_capi_transcribe_pcm_lang(
                self._ctx, buf, n, sample_rate, decoder, target_lang.encode("utf-8")
            )
        else:
            ptr = self._lib.parakeet_capi_transcribe_pcm(self._ctx, buf, n, sample_rate, decoder)
        return self._take_string(ptr)

    def transcribe_pcm_json(
        self, samples: np.ndarray, sample_rate: int,
        decoder: int = DECODER_DEFAULT, target_lang: Optional[str] = None,
    ) -> dict:
        """Like transcribe_pcm but returns the JSON document (text, per-word
        start/end/conf) instead of bare text -- needed for confidence-based
        rejection, since the plain transcribe_pcm entry points don't expose
        per-word confidence at all. Single clip, via the n_clips=1 batch-json
        entry point (there's no non-batch PCM+JSON combination in the C-API).
        """
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        buf = samples.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        n_samples = (ctypes.c_int * 1)(samples.shape[0])

        ptr = self._lib.parakeet_capi_transcribe_pcm_batch_json_lang(
            self._ctx, buf, n_samples, 1, sample_rate, decoder,
            (target_lang or "").encode("utf-8"),
        )
        docs = json.loads(self._take_string(ptr))
        return docs[0]
