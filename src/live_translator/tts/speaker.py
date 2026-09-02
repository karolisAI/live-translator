from __future__ import annotations

import json
import subprocess
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any

from live_translator.audio.io import play_mono, read_wav_mono
from live_translator.config import AudioSettings, TtsSettings
from live_translator.errors import MissingDependency
from live_translator.runtime import resolve_trusted_path


class _PersistentPiper:
    """One `piper.exe`, fed via `--json-input`, kept alive for the session.

    Spawning a fresh process per phrase pays a fixed ~0.41s (process start,
    voice model reload) on top of the ~0.02s/word Piper itself needs once
    warm -- measured 2026-08-17, isolated from playback. This pays that cost
    once, at construction, instead of on every phrase.

    stdout is drained on a background thread because a hung request has to
    be detectable with a timeout, and a blocking read on a Windows pipe has
    no timeout of its own. stderr gets its own draining thread too: Piper
    logs one "real-time factor" line per phrase, and an unread pipe fills
    its OS buffer over a long meeting and blocks the child outright.
    """

    def __init__(self, piper_exe: str, model_path: Path, tts_settings: TtsSettings) -> None:
        args = [piper_exe, "--model", str(model_path), "--json-input"]
        if tts_settings.speaker:
            args += ["--speaker", tts_settings.speaker]
        if tts_settings.length_scale is not None:
            args += ["--length_scale", str(tts_settings.length_scale)]

        self._timeout = tts_settings.piper_timeout_seconds
        try:
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # Named explicitly rather than left to the locale. Without
                # this Python encodes with the console codepage (cp1252 here),
                # which cannot represent Polish or Czech characters -- the
                # cause of a meeting-ending UnicodeEncodeError that has been in
                # the product since May. `errors="replace"` covers the read
                # side, where the only thing this cares about is that a line
                # arrived at all, never what it says.
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise RuntimeError(f"Piper executable could not be run ({piper_exe}): {exc}") from exc

        self._responses: Queue[str | None] = Queue()
        self._stderr_tail: deque[str] = deque(maxlen=20)
        Thread(target=self._drain_stdout, daemon=True).start()
        Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stdout(self) -> None:
        try:
            for line in self._process.stdout:
                self._responses.put(line)
        finally:
            # Signals "the process stopped producing output" to synthesize(),
            # whether that's a clean exit or a crash.
            self._responses.put(None)

    def _drain_stderr(self) -> None:
        for line in self._process.stderr:
            self._stderr_tail.append(line)

    def is_alive(self) -> bool:
        return self._process.poll() is None

    def synthesize(self, text: str, wav_path: Path) -> None:
        """Ask the resident process to render `text` to `wav_path`.

        The absolute path is what `--json-input` actually honors here --
        `--output_dir` was tried and does not override where this Piper
        build writes; passing the full path per request sidesteps that
        rather than depending on it.
        """
        if not self.is_alive():
            # TtsSpeaker._get_resident_piper already replaces a dead process
            # rather than reusing it, so this is belt-and-braces -- but a
            # queue left holding a late answer from a previous request is
            # exactly the state that must never serve a new one, so the guard
            # belongs on the object itself and not only on today's caller.
            raise RuntimeError("Piper process is no longer running.")
        request = json.dumps({"text": text, "output_file": str(wav_path)})
        try:
            self._process.stdin.write(request + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"Piper process is no longer running: {exc}") from exc

        try:
            response = self._responses.get(timeout=self._timeout)
        except Empty as exc:
            # Kill it rather than leave it running. Requests and responses are
            # matched only by order, so a process that answers *after* its
            # request timed out hands that stale answer to the next phrase and
            # every phrase after it -- reporting success while the WAV it names
            # belongs to the previous request. One slow phrase would silently
            # break synthesis for the rest of the meeting. A dead process makes
            # is_alive() false, so the next call transparently starts a fresh
            # one instead.
            self._process.kill()
            raise RuntimeError(
                f"Piper did not finish within {self._timeout:g}s and was terminated."
            ) from exc
        if response is None:
            detail = "".join(self._stderr_tail).strip()
            raise RuntimeError("Piper process exited unexpectedly" + (f": {detail}" if detail else "."))

    def close(self) -> None:
        try:
            self._process.stdin.close()
        except OSError:
            pass
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()


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
        self._resident_piper: _PersistentPiper | None = None

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
        """Start the resident Piper process now, paying its model-load cost
        at startup instead of on whatever phrase happens to be first.

        Measured 2026-08-18 over a two-minute run: the first synthesis of a
        session took 3.61s against a 0.68s median for the rest of the run
        under the old per-phrase-process design. A resident process pays
        that load once, here.

        A failure is deliberately not fatal: `validate()` has already checked
        the assets, and a warm-up that cannot run means a slow first phrase,
        not a broken session -- `_synthesize_piper` gets its own chance to
        start the process on the first real call.
        """
        if self._tts_settings.engine.lower() not in {"piper", "piper-cli"}:
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
            wav_path = Path(temp.name)
        try:
            self._get_resident_piper().synthesize("Warming up.", wav_path)
            # Also pay read_wav_mono's own first-call cost here rather than on
            # the first real phrase. Measured 2026-08-26: with the process
            # already resident, synthesize() itself is fast (~0.12s) on the
            # first real call, but read_wav_mono went 0.69s -> 0.02s between
            # its first and second invocations regardless -- a cost that
            # belongs to that function, not to Piper, and warm-up should
            # absorb it too since the whole point is a fast first phrase.
            read_wav_mono(wav_path)
        except Exception:
            return
        finally:
            wav_path.unlink(missing_ok=True)

    def _get_resident_piper(self) -> _PersistentPiper:
        if self._resident_piper is not None and self._resident_piper.is_alive():
            return self._resident_piper
        if self._resident_piper is not None:
            # Reap the dead one before replacing it, rather than dropping the
            # reference and leaving the OS handle around.
            self._resident_piper.close()
            self._resident_piper = None
        piper_exe, model_path = self._resolve_piper_assets()
        self._resident_piper = _PersistentPiper(piper_exe, model_path, self._tts_settings)
        return self._resident_piper

    def _synthesize_piper(self, text: str, wav_path: Path) -> None:
        """Hand text to the resident Piper process, writing audio to `wav_path`.

        Starts the process on first use if `warm_up()` was never called --
        the one-shot `say`/`translate-once` commands reach here directly --
        so every caller gets a working synthesis path without needing to
        know the process is resident at all. Also restarts it transparently
        if a previous request left it dead.
        """
        piper = self._get_resident_piper()
        piper.synthesize(text, wav_path)

    def close(self) -> None:
        """Stop the resident Piper process, if one was ever started.

        `subprocess.Popen`'s children are not killed automatically when this
        process exits on Windows -- skipping this leaks a `piper.exe` past
        the end of every session that used one.
        """
        if self._resident_piper is not None:
            self._resident_piper.close()
            self._resident_piper = None

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
