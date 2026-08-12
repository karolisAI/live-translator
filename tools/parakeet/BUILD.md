# Vendored parakeet.cpp DLLs — build manifest

These are the exact binaries `parakeet_capi.py` and every accuracy/memory/beam-size
finding in this evaluation were tested against. Use these, don't rebuild your own —
a different `parakeet.cpp` version or build config can silently change or drop the
`WINDOWS_EXPORT_ALL_SYMBOLS` behavior this binding's thread-pinning feature depends
on (see `parakeet_capi.py`'s `ParakeetCapabilityWarning` for what happens if it's
missing — the engine still works, thread pinning just silently degrades to the
library's own default of 8).

## Source

- Repo: https://github.com/mudler/parakeet.cpp
- Commit: `1bfbebfaaf493866f49597cd3b7901959d395c60` (2026-07-29)
- Submodule `third_party/ggml`: https://github.com/ggml-org/ggml @ `e705c5fed490514458bdd2eaddc43bd098fcce9b` (v0.13.0)
- `parakeet_capi.h` ABI version: v6

## Build environment

- Windows, MSVC 19.44 (Visual Studio 2022 Community, toolset v143)
- CMake 4.4.1
- CPU-only build — no NVIDIA GPU on the build machine, so no CUDA/Vulkan backend

## Exact commands (PowerShell, as actually run)

Two gotchas hit while building this, neither obvious from parakeet.cpp's own
docs — both included below so you don't lose time rediscovering them.

**Gotcha 1: CMake installed via `winget` is not on PATH by default.**
`winget install Kitware.CMake` puts `cmake.exe` at
`C:\Program Files\CMake\bin` without registering it — `cmake` from a fresh
shell fails with "not recognized" even though it's installed. Add it to
`$env:Path` for the session (or fix PATH permanently in System Settings).

```powershell
$env:Path += ";C:\Program Files\CMake\bin"

git clone --recursive https://github.com/mudler/parakeet.cpp
Set-Location parakeet.cpp
git checkout 1bfbebfaaf493866f49597cd3b7901959d395c60

cmake -B build-shared -G "Visual Studio 17 2022" -A x64 -DPARAKEET_SHARED=ON -DPARAKEET_BUILD_CLI=ON
cmake --build build-shared --config Release -j
```

`-DPARAKEET_SHARED=ON` builds `parakeet.dll`; the project's own `CMakeLists.txt`
sets `WINDOWS_EXPORT_ALL_SYMBOLS ON` on that target unconditionally (not a flag we
chose — it's baked into this parakeet.cpp version), which is what exposes the
undocumented `pk::set_num_threads` symbol this binding's `set_num_threads()` uses.
`-DPARAKEET_BUILD_CLI=ON` isn't required by the Python binding, only used for
manual testing/quantization (`parakeet-cli.exe quantize ...`).

**Gotcha 2: `parakeet-cli.exe` fails with `STATUS_DLL_NOT_FOUND` unless the
ggml DLLs' directory is on PATH first.** The build puts `parakeet.dll` in
`build-shared\Release\` but `ggml.dll` / `ggml-base.dll` / `ggml-cpu.dll` in
`build-shared\bin\Release\` — a *different* directory. Windows won't find
them via the exe's own directory alone. Needed before running the CLI at
all (transcribe, quantize, info — everything):

```powershell
$env:Path = "$PWD\build-shared\bin\Release;$PWD\build-shared\Release;" + $env:Path

# sanity check -- should print usage, not a DLL-not-found error
& ".\build-shared\examples\cli\Release\parakeet-cli.exe"

# quantize example (see main README's "Getting the model" for the
# f16-source-doesn't-work / needs-f32-source gotcha on this step)
& ".\build-shared\examples\cli\Release\parakeet-cli.exe" quantize `
    "path\to\model-f32.gguf" "path\to\model-q8_0.gguf" q8_0
```

The Python binding (`parakeet_capi.py`) does not have this problem — it calls
`os.add_dll_directory()` on `tools/parakeet/` before loading `parakeet.dll`,
so it finds all four DLLs automatically as long as they're all in that one
folder together (which is also why the vendored bundle keeps all four DLLs
in a single flat directory rather than mirroring the build tree's split
layout).

## Files and checksums (SHA256)

| File | SHA256 | Source |
|---|---|---|
| `parakeet.dll` | `9bf6652fb58e96b3cfb957a7c26d7ca3951b4aa6060c90341c3367490ce0ba7c` | `build-shared/Release/parakeet.dll` |
| `ggml.dll` | `0843d28784d1d892912d6d889531b87631b26afb123d86eebc2a6987387a8aae` | `build-shared/bin/Release/ggml.dll` |
| `ggml-base.dll` | `df0d6377c61cba19ceb30aebb6c8754dd47c53dc9edf28dced48c8f33a868eb5` | `build-shared/bin/Release/ggml-base.dll` |
| `ggml-cpu.dll` | `f6121b5a698645e7a375e004e46a157136be8b62c4a30ff0c7dfa3bb01862750` | `build-shared/bin/Release/ggml-cpu.dll` |

Verify after copying:

```powershell
Get-FileHash tools\parakeet\parakeet.dll -Algorithm SHA256
```

## If you rebuild anyway

You'll get a working DLL (the documented C-API surface — `transcribe_pcm`,
`transcribe_pcm_lang`, `transcribe_pcm_batch_json_lang`, etc. — is stable and not
affected by compiler/toolchain differences). What might silently differ:

- `set_num_threads()` support, if your build lacks `WINDOWS_EXPORT_ALL_SYMBOLS` or
  uses a different compiler with different C++ name mangling. You'll get a loud
  `ParakeetCapabilityWarning` at import time if this happens, not silent breakage.
- Performance characteristics (this evaluation's latency/memory numbers were
  measured against this exact commit and build).
