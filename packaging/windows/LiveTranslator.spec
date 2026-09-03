# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH).parents[1]

datas = []
binaries = []
hiddenimports = []

for package in [
    "ctranslate2",
    "onnx_asr",
    "onnxruntime",
    "sentencepiece",
]:
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package)
    except Exception:
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

for source, target in [
    ("models/argos", "models/argos"),
    ("models/tts", "models/tts"),
    ("tools/piper", "tools/piper"),
    ("packaging/runtime-assets.manifest.json", "."),
    ("README.md", "."),
    ("docs", "docs"),
    ("app.example.yaml", "."),
]:
    path = ROOT / source
    if path.exists():
        datas.append((str(path), target))


a = Analysis(
    [str(ROOT / "src" / "live_translator_launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "argostranslate",
        "spacy",
        "stanza",
        "thinc",
        "torch",
        "torchvision",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LiveTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LiveTranslator",
)
