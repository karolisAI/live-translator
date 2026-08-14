"""Synthesize German decimal-number phrases with Piper, feed them through
ParakeetAsr, and inspect per-word confidence at the number tokens -- a
self-contained reproduction of the decimal-number drop reported in
parakeet-engine-comparison-de.md (aleks-parakeet failed 0/5 decimals tested
there: "Stärke 7,4" -> "Stärke sieben", "1000 Menschen" -> "Menschen").

Requires tools/piper/piper.exe and models/tts/de_DE-thorsten-medium.onnx
(already part of this repo's TTS setup).

Usage:
    .venv/Scripts/python.exe scripts/diagnose_decimal_numbers.py
"""

from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.asr.parakeet_capi import ParakeetModel

from asr_eval_common import read_wav

REPO = Path(__file__).resolve().parents[1]
PIPER = REPO / "tools" / "piper" / "piper.exe"
VOICE = REPO / "models" / "tts" / "de_DE-thorsten-medium.onnx"
OUT_DIR = REPO / "eval" / "de-en" / "decimal-diagnostic"

# Phrases mirroring the report's failure examples, plus variants to isolate
# the cause: digit-form vs spelled-out, comma vs period decimal separator.
PHRASES = {
    "digit_comma": "Erdstöße der Stärke 7,4 hatten sich ereignet.",
    "digit_period": "Erdstöße der Stärke 7.4 hatten sich ereignet.",
    "spoken_komma": "Erdstöße der Stärke sieben Komma vier hatten sich ereignet.",
    "beben_comma": "1999 verwüstete ein Beben der Stärke 6,9 die Region.",
    "casualties": "Damals starben mehr als 1000 Menschen.",
    "small_decimal": "Die Rate lag bei 1,2 Prozent.",
}


def synthesize(text: str, out_wav: Path) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(PIPER), "--model", str(VOICE), "--output_file", str(out_wav)],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {proc.stderr}")


def main() -> None:
    if not PIPER.is_file():
        print(f"missing {PIPER}")
        sys.exit(1)
    if not VOICE.is_file():
        print(f"missing {VOICE}")
        sys.exit(1)

    model = ParakeetModel("models/parakeet/nemotron-3.5-asr-streaming-0.6b-f16.gguf")

    for name, text in PHRASES.items():
        wav_path = OUT_DIR / f"{name}.wav"
        synthesize(text, wav_path)
        samples, sample_rate = read_wav(str(wav_path))
        doc = model.transcribe_pcm_json(samples, sample_rate, target_lang="de")

        print(f"=== {name} ===")
        print(f"  input text:  {text}")
        print(f"  transcribed: {doc['text']}")
        for w in doc.get("words", []):
            if w["w"] == "<de-DE>":
                continue
            flag = "  <<<" if w["conf"] < 0.5 else ""
            print(f"    {w['w']:<14} conf={w['conf']:.3f}{flag}")
        print()


if __name__ == "__main__":
    main()
