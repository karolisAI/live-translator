from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from live_translator.audio.io import play_mono, read_wav_mono
from live_translator.config import AudioSettings, TtsSettings
from live_translator.errors import MissingDependency
from live_translator.runtime import resolve_runtime_path


class TtsSpeaker:
    def __init__(self, tts_settings: TtsSettings, audio_settings: AudioSettings) -> None:
        self._tts_settings = tts_settings
        self._audio_settings = audio_settings

    def speak(self, text: str) -> None:
        if not text:
            return

        engine = self._tts_settings.engine.lower()
        if engine in {"none", "off"}:
            return
        if engine in {"pyttsx3", "sapi"}:
            self._speak_pyttsx3(text)
            return
        if engine in {"piper", "piper-cli"}:
            self._speak_piper(text)
            return

        raise ValueError(f"Unsupported TTS engine: {self._tts_settings.engine}")

    def _speak_pyttsx3(self, text: str) -> None:
        try:
            import pyttsx3
        except ImportError as exc:
            raise MissingDependency(
                "Missing dependency 'pyttsx3'. Install dependencies with: python -m pip install -e ."
            ) from exc

        if self._audio_settings.output_device:
            print("Warning: pyttsx3 uses the Windows default output device; configured output_device is ignored.")

        engine = pyttsx3.init()
        if self._tts_settings.voice:
            selected = None
            for voice in engine.getProperty("voices"):
                if self._tts_settings.voice.lower() in f"{voice.id} {voice.name}".lower():
                    selected = voice.id
                    break
            if selected is None:
                raise ValueError(f"pyttsx3 voice not found: {self._tts_settings.voice}")
            engine.setProperty("voice", selected)
        engine.say(text)
        engine.runAndWait()

    def _speak_piper(self, text: str) -> None:
        if not self._tts_settings.model_path:
            raise ValueError("tts.model_path is required when tts.engine is 'piper'.")
        piper_exe = resolve_piper_exe(self._tts_settings.piper_exe)
        if piper_exe is None:
            raise MissingDependency(
                f"Missing Piper executable '{self._tts_settings.piper_exe}'. Install Piper or set tts.piper_exe."
            )

        model_path = resolve_runtime_path(self._tts_settings.model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Piper model not found: {model_path}")
        config_path = piper_model_config_path(model_path)
        if not config_path.exists():
            raise FileNotFoundError(
                f"Piper voice config not found: {config_path}. Download the matching .onnx.json file."
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
            wav_path = Path(temp.name)

        try:
            command = [
                piper_exe,
                "--model",
                str(model_path),
                "--output_file",
                str(wav_path),
            ]
            if self._tts_settings.speaker:
                command.extend(["--speaker", self._tts_settings.speaker])

            completed = subprocess.run(
                command,
                input=text,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or "Piper failed to synthesize audio.")

            samples, sample_rate = read_wav_mono(wav_path)
            playback_settings = self._audio_settings
            if sample_rate != self._audio_settings.sample_rate:
                print(
                    f"Warning: Piper WAV sample rate is {sample_rate}; playback uses device resampling."
                )
                playback_settings = AudioSettings(
                    sample_rate=sample_rate,
                    chunk_seconds=self._audio_settings.chunk_seconds,
                    input_device=self._audio_settings.input_device,
                    output_device=self._audio_settings.output_device,
                    peer_input_device=self._audio_settings.peer_input_device,
                    peer_output_device=self._audio_settings.peer_output_device,
                    input_gain=self._audio_settings.input_gain,
                    playback_gain=self._audio_settings.playback_gain,
                )
            play_mono(samples, playback_settings)
        finally:
            wav_path.unlink(missing_ok=True)


def resolve_piper_exe(piper_exe: str) -> str | None:
    path = resolve_runtime_path(piper_exe)
    if path.exists():
        return str(path)
    return shutil.which(piper_exe)


def piper_model_config_path(model_path: str | Path) -> Path:
    return Path(model_path).with_suffix(".onnx.json")
