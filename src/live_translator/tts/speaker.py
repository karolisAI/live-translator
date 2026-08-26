from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from live_translator.audio.io import play_mono, read_wav_mono
from live_translator.config import AudioSettings, TtsSettings
from live_translator.errors import MissingDependency
from live_translator.runtime import resolve_trusted_path


@dataclass(frozen=True)
class RenderedSpeech:
    """Audio ready to play, produced before the previous phrase has finished.

    `samples` is None for an engine that cannot separate synthesis from playback,
    in which case `text` is carried through and spoken at playback time instead.
    """

    text: str
    samples: Any | None = None
    sample_rate: int = 0


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

    def validate(self) -> None:
        engine = self._tts_settings.engine.lower()
        if engine in {"none", "off"}:
            return
        if engine in {"pyttsx3", "sapi"}:
            if self._audio_settings.output_device:
                raise ValueError(
                    "pyttsx3 cannot target audio.output_device. Use Piper for virtual-cable meeting routing."
                )
            try:
                import pyttsx3  # noqa: F401
            except ImportError as exc:
                raise MissingDependency(
                    "Missing dependency 'pyttsx3'. Install it with: python -m pip install -e \".[tts]\""
                ) from exc
            return
        if engine not in {"piper", "piper-cli"}:
            raise ValueError(f"Unsupported TTS engine: {self._tts_settings.engine}")
        self._resolve_piper_assets()

    def _speak_pyttsx3(self, text: str) -> None:
        try:
            import pyttsx3
        except ImportError as exc:
            raise MissingDependency(
                "Missing dependency 'pyttsx3'. Install dependencies with: python -m pip install -e ."
            ) from exc

        if self._audio_settings.output_device:
            raise ValueError(
                "pyttsx3 cannot target audio.output_device. Use Piper for virtual-cable meeting routing."
            )

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

    def warm_up(self) -> None:
        """Pay Piper's first-run cost at startup rather than on the first phrase.

        Measured 2026-08-18 over a two-minute run: the first synthesis of a session
        took 3.61s against a 0.68s median for the rest of the run. The cost is
        loading the voice model and whatever the OS has not cached yet, and it lands
        on the first thing the speaker says, which is the worst place for it.

        Synthesises to a temporary file and discards it, so nothing is heard. A
        failure is deliberately not fatal: `validate()` has already checked the
        assets, and a warm-up that cannot run means a slow first phrase, not a
        broken session.
        """
        if self._tts_settings.engine.lower() not in {"piper", "piper-cli"}:
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
            wav_path = Path(temp.name)
        try:
            self._synthesize_piper("Warming up.", wav_path)
        except Exception:
            return
        finally:
            wav_path.unlink(missing_ok=True)

    def _synthesize_piper(self, text: str, wav_path: Path) -> None:
        """Run Piper once, writing audio to `wav_path`. Does not play anything."""
        piper_exe, model_path = self._resolve_piper_assets()

        command = [
            piper_exe,
            "--model",
            str(model_path),
            "--output_file",
            str(wav_path),
        ]
        if self._tts_settings.speaker:
            command.extend(["--speaker", self._tts_settings.speaker])
        if self._tts_settings.length_scale is not None:
            command.extend(["--length_scale", str(self._tts_settings.length_scale)])

        try:
            completed = subprocess.run(
                command,
                input=text,
                text=True,
                capture_output=True,
                check=False,
                timeout=self._tts_settings.piper_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            # subprocess.run already kills the child process itself before
            # raising this -- nothing left to clean up, just translate it
            # into a clear error instead of letting it propagate raw.
            raise RuntimeError(
                f"Piper ({piper_exe}) did not finish within "
                f"{self._tts_settings.piper_timeout_seconds:.0f}s and was terminated."
            ) from exc
        except OSError as exc:
            # A trusted, existing path can still fail to actually run --
            # permissions, a corrupted binary, or (Windows) "not a valid
            # Win32 application". subprocess.run raises OSError for these
            # rather than returning a CompletedProcess, so the returncode
            # check below never sees them; without this they'd propagate
            # as a raw OSError instead of a clear, actionable error.
            raise RuntimeError(f"Piper executable could not be run ({piper_exe}): {exc}") from exc
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Piper failed to synthesize audio.")

    def render(self, text: str) -> RenderedSpeech | None:
        """Turn text into audio without playing it.

        Separating this from `play()` is what lets a caller overlap the two: the
        next phrase can be synthesized while the current one is still being
        spoken. Doing both in one worker costs synthesis plus playback per phrase,
        which is more time than phrases take to arrive, so the queue behind it
        overflows and speech is discarded.

        Only Piper can be split this way. pyttsx3 synthesizes and plays in a single
        call, so its text is carried through and spoken by `play()` instead.
        """
        if not text:
            return None

        engine = self._tts_settings.engine.lower()
        if engine in {"none", "off"}:
            return None
        if engine not in {"piper", "piper-cli"}:
            return RenderedSpeech(text)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
            wav_path = Path(temp.name)
        try:
            self._synthesize_piper(text, wav_path)
            samples, sample_rate = read_wav_mono(wav_path)
        finally:
            wav_path.unlink(missing_ok=True)
        return RenderedSpeech(text, samples, sample_rate)

    def play(self, rendered: RenderedSpeech | None) -> None:
        """Play what `render()` produced."""
        if rendered is None:
            return
        if rendered.samples is None:
            self.speak(rendered.text)
            return

        settings = self._audio_settings
        if rendered.sample_rate != settings.sample_rate:
            settings = AudioSettings(
                sample_rate=rendered.sample_rate,
                chunk_seconds=settings.chunk_seconds,
                input_device=settings.input_device,
                output_device=settings.output_device,
                peer_input_device=settings.peer_input_device,
                input_gain=settings.input_gain,
                playback_gain=settings.playback_gain,
            )
        play_mono(rendered.samples, settings)

    def _speak_piper(self, text: str) -> None:
        self.play(self.render(text))

    def _resolve_piper_assets(self) -> tuple[str, Path]:
        if not self._tts_settings.model_path:
            raise ValueError("tts.model_path is required when tts.engine is 'piper'.")
        piper_exe = resolve_piper_exe(self._tts_settings.piper_exe)
        if piper_exe is None:
            raise MissingDependency(
                f"Missing Piper executable '{self._tts_settings.piper_exe}'. Install Piper or set tts.piper_exe."
            )

        model_path = resolve_trusted_path(self._tts_settings.model_path)
        config_path = piper_model_config_path(model_path)
        if not config_path.exists():
            raise FileNotFoundError(
                f"Piper voice config not found: {config_path}. Download the matching .onnx.json file."
            )
        runtime_dir = Path(piper_exe).resolve().parent
        for companion in ("piper_phonemize.dll", "onnxruntime.dll", "espeak-ng-data"):
            if not (runtime_dir / companion).exists():
                raise FileNotFoundError(f"Piper runtime asset not found: {runtime_dir / companion}")
        return piper_exe, model_path


def resolve_piper_exe(piper_exe: str) -> str | None:
    """Resolve `piper_exe` to a trusted, existing path, or None if it isn't
    found under any approved location. No longer falls back to searching
    PATH -- PATH is not an approved runtime location. A resolved-but-
    untrusted path (UntrustedRuntimePath) is deliberately not caught here
    and propagates, since collapsing it into None would hide that the
    executable does exist somewhere, just not somewhere this app trusts."""
    try:
        return str(resolve_trusted_path(piper_exe))
    except FileNotFoundError:
        return None


def piper_model_config_path(model_path: str | Path) -> Path:
    return Path(model_path).with_suffix(".onnx.json")
