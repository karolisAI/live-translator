"""Measure process memory footprint of loading + running an ASR engine.

No new dependency: reads Win32 GetProcessMemoryInfo directly via ctypes,
same approach this project already uses to talk to parakeet.dll.

Run once per engine (separate processes -- loading both in one process would
conflate their allocators and isn't how production ever runs them):

    .venv/Scripts/python.exe scripts/measure_memory.py parakeet
    .venv/Scripts/python.exe scripts/measure_memory.py faster-whisper
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.config import AsrSettings

from asr_eval_common import read_wav

DEBUG_DIR = Path(__file__).resolve().parents[1] / "debug-en-de"


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
ctypes.windll.kernel32.GetCurrentProcess.argtypes = []
ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_ProcessMemoryCountersEx), wintypes.DWORD,
]


def memory_mb() -> tuple[float, float]:
    """Returns (working_set_mb, private_bytes_mb) for the current process."""
    counters = _ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(_ProcessMemoryCountersEx)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    if not ok:
        raise OSError(f"GetProcessMemoryInfo failed: {ctypes.WinError()}")
    return counters.WorkingSetSize / (1024 * 1024), counters.PrivateUsage / (1024 * 1024)


def report(label: str, ws_mb: float, priv_mb: float) -> None:
    print(f"{label:<28} working_set={ws_mb:8.1f} MB   private={priv_mb:8.1f} MB")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"parakeet", "faster-whisper"}:
        print(f"usage: {sys.argv[0]} <parakeet|faster-whisper> [gguf_path]")
        sys.exit(1)
    engine = sys.argv[1]
    gguf_path = sys.argv[2] if len(sys.argv) > 2 else "models/parakeet/nemotron-3.5-asr-streaming-0.6b-f16.gguf"

    ws0, priv0 = memory_mb()
    report("baseline (imports only)", ws0, priv0)

    if engine == "parakeet":
        from live_translator.asr import ParakeetAsr

        settings = AsrSettings(
            engine="parakeet",
            model=gguf_path,
            cpu_threads=8,
            source_language="en",
        )
        asr = ParakeetAsr(settings)
    else:
        from live_translator.asr import FasterWhisperAsr

        settings = AsrSettings(
            engine="faster-whisper",
            model="base",
            device="cpu",
            compute_type="int8",
            cpu_threads=8,
            source_language="en",
        )
        asr = FasterWhisperAsr(settings)

    ws1, priv1 = memory_mb()
    report(f"after {engine} model load", ws1, priv1)
    report("  delta from load", ws1 - ws0, priv1 - priv0)

    peak_ws, peak_priv = ws1, priv1
    for wav_path in sorted(DEBUG_DIR.glob("segment-*.wav"))[:10]:
        samples, sample_rate = read_wav(wav_path)
        asr.transcribe(samples, sample_rate)
        ws, priv = memory_mb()
        peak_ws, peak_priv = max(peak_ws, ws), max(peak_priv, priv)

    report("peak during inference", peak_ws, peak_priv)
    report("  delta load -> peak", peak_ws - ws1, peak_priv - priv1)
    report("  delta baseline -> peak", peak_ws - ws0, peak_priv - priv0)


if __name__ == "__main__":
    main()
