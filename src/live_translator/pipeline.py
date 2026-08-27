from __future__ import annotations

from pathlib import Path
from threading import Thread
from time import perf_counter

from live_translator.asr import AsrEngine, TranscriptResult, create_asr
from live_translator.audio.analysis import analyze_audio, has_enough_audio_energy
from live_translator.audio.devices import describe_device_selection
from live_translator.audio.io import play_mono, record_mono, write_wav
from live_translator.audio.rolling import RollingSpeechChunker
from live_translator.config import AppConfig
from live_translator.diagnostics import (
    NOTE_SUFFIX,
    CaptureLimits,
    capture_warning,
    resolve_capture_dir,
    segment_audio_name,
    session_directory_name,
    sweep,
)
from live_translator.errors import UntrustedRuntimePath
from live_translator.mt import TranslationEngine
from live_translator.realtime import CapturedSegment, RealtimeMeetingWorkers
from live_translator.tts import RenderedSpeech, TtsSpeaker


class LocalTranslatorPipeline:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._asr: AsrEngine | None = None
        self._translator: TranslationEngine | None = None
        self._speaker: TtsSpeaker | None = None
        self._verbose = False
        self._tts_disabled_reason: str | None = None
        """Set once, on UntrustedRuntimePath from speaker.render().

        render() runs synthesis on the recognition worker (see
        _process_live_segment's docstring), so this has to live here, not on
        the playback loop -- a mistrusted path never actually reaches
        playback, it fails during rendering, one worker earlier.
        """
        self._capture_limits: CaptureLimits | None = None
        self._show_text = False

    def prepare(self, *, include_tts: bool = True) -> None:
        started = perf_counter()
        source = self._config.translation.source_language.upper()
        target = self._config.translation.target_language.upper()
        print("Preparing offline models...")
        print(f"  Speech recognition: {self._config.asr.model}")
        self._get_asr()
        print(f"  Translation: {source} -> {target}")
        self._get_translator().prepare()
        if include_tts:
            print(f"  Speech output: {self._config.tts.engine}")
            speaker = self._get_speaker()
            speaker.validate()
            speaker.warm_up()
        print(f"Ready in {perf_counter() - started:.1f}s.")

    def record_test(self, output_path: str | Path, seconds: float | None = None, play: bool = False) -> None:
        audio = record_mono(self._config.audio, seconds)
        write_wav(output_path, audio, self._config.audio.sample_rate)
        print(f"Wrote {output_path}")
        if play:
            play_mono(audio, self._config.audio)

    def transcribe_once(self, seconds: float | None = None) -> str:
        started = perf_counter()
        print(f"Preparing speech recognition: {self._config.asr.model}")
        self._get_asr()
        print(f"Ready in {perf_counter() - started:.1f}s.")
        audio = record_mono(self._config.audio, seconds)
        result = self._transcribe_audio_if_safe(audio)
        if result is None:
            print("Transcript: ")
            return ""
        print(f"Detected language: {result.language or 'unknown'}")
        print(f"ASR time: {result.inference_seconds:.2f}s for {result.duration_seconds:.2f}s audio")
        self._print_asr_rejections(result)
        print(f"Transcript: {result.text}")
        return result.text

    def translate_once(self, seconds: float | None = None, speak: bool = True) -> str:
        self.prepare(include_tts=speak)
        translator = self._get_translator()
        speaker = self._get_speaker() if speak else None
        start = perf_counter()
        audio = record_mono(self._config.audio, seconds)

        asr_start = perf_counter()
        result = self._transcribe_audio_if_safe(audio)
        asr_seconds = perf_counter() - asr_start
        if result is None:
            total_seconds = perf_counter() - start
            print("Source: ")
            print("Target: ")
            print(
                "Timings: "
                f"audio={len(audio) / self._config.audio.sample_rate:.2f}s "
                f"asr={asr_seconds:.2f}s mt=0.00s tts=0.00s total={total_seconds:.2f}s"
            )
            return ""

        mt_start = perf_counter()
        translated = translator.translate(result.text)
        mt_seconds = perf_counter() - mt_start

        tts_seconds = 0.0
        if speaker is not None and translated:
            tts_start = perf_counter()
            speaker.speak(translated)
            tts_seconds = perf_counter() - tts_start

        total_seconds = perf_counter() - start
        self._print_asr_rejections(result)
        print(f"Source: {result.text}")
        print(f"Target: {translated}")
        print(
            "Timings: "
            f"audio={len(audio) / self._config.audio.sample_rate:.2f}s "
            f"asr={asr_seconds:.2f}s mt={mt_seconds:.2f}s "
            f"tts={tts_seconds:.2f}s total={total_seconds:.2f}s"
        )
        return translated

    def loopback(
        self,
        chunker_mode: str | None = None,
        debug_audio_dir: str | Path | None = None,
        *,
        verbose: bool = False,
        diagnostics: bool = False,
        show_text: bool = False,
    ) -> None:
        self._verbose = verbose
        self._show_text = show_text
        self._print_audio_route()
        self.prepare()
        translator = self._get_translator()
        speaker = self._get_speaker()
        debug_dir = self._start_diagnostics(
            diagnostics=diagnostics, debug_audio_dir=debug_audio_dir
        )
        if debug_dir is None:
            self._expire_old_diagnostics()
        chunker = (chunker_mode or self._config.chunking.mode).lower()
        if chunker in {"phrase", "speech"}:
            chunker = "vad"
        if chunker not in {"fixed", "vad", "rolling"}:
            raise ValueError("Unsupported chunker mode. Use 'fixed', 'vad', or 'rolling'.")

        source = self._config.translation.source_language.upper()
        target = self._config.translation.target_language.upper()
        print(f"Direction: {source} -> {target}")
        print("Live translation active. Listening continuously between phrases.")
        self._announce_text_display()
        if self._verbose and chunker == "vad":
            print(
                f"Chunker=vad silence={self._config.chunking.silence_ms}ms "
                f"min={self._config.chunking.min_segment_seconds:.1f}s "
                f"max={self._config.chunking.max_seconds:.1f}s "
                f"input={self._config.audio.input_device or 'default'} "
                f"output={self._config.audio.output_device or 'default'}"
            )
        elif self._verbose and chunker == "rolling":
            print(
                f"Chunker=rolling emit={self._config.chunking.rolling_window_seconds:.1f}s "
                f"silence={self._config.chunking.silence_ms}ms "
                f"max={self._config.chunking.max_seconds:.1f}s "
                f"input={self._config.audio.input_device or 'default'} "
                f"output={self._config.audio.output_device or 'default'}"
            )
        elif self._verbose:
            print(
                f"Chunker=fixed chunk={self._config.audio.chunk_seconds:.1f}s "
                f"input={self._config.audio.input_device or 'default'} "
                f"output={self._config.audio.output_device or 'default'}"
            )
        workers = self._create_realtime_workers(translator, speaker, debug_dir)
        workers.start()
        interrupted = False
        try:
            if chunker in {"vad", "rolling"}:
                with RollingSpeechChunker(
                    self._config.audio,
                    self._config.chunking,
                    emit_while_speaking=chunker == "rolling",
                    verbose=self._verbose,
                ) as recorder:
                    while not workers.stop_event.is_set():
                        workers.raise_if_failed()
                        audio = recorder.next_chunk(stop_event=workers.stop_event)
                        if audio is not None:
                            workers.submit(audio)
            else:
                while not workers.stop_event.is_set():
                    workers.raise_if_failed()
                    workers.submit(record_mono(self._config.audio, announce=self._verbose))
        except KeyboardInterrupt:
            interrupted = True
        finally:
            workers.stop()
        workers.raise_if_failed()
        if interrupted:
            print("Meeting translation ended.")

    def _get_asr(self) -> AsrEngine:
        if self._asr is None:
            self._asr = create_asr(self._config.asr)
        return self._asr

    def _get_translator(self) -> TranslationEngine:
        if self._translator is None:
            self._translator = TranslationEngine(self._config.translation)
        return self._translator

    def _get_speaker(self) -> TtsSpeaker:
        if self._speaker is None:
            self._speaker = TtsSpeaker(self._config.tts, self._config.audio)
        return self._speaker

    def _process_live_segment(
        self,
        segment: CapturedSegment,
        translator: TranslationEngine,
        speaker: TtsSpeaker,
        debug_dir: Path | None,
    ) -> RenderedSpeech | None:
        """Recognize, translate, and synthesize one phrase.

        Synthesis happens here rather than in the playback worker so that the two
        overlap: this worker renders the next phrase while the previous one is
        still being spoken. It has the room. Measured 2026-08-18, the playback
        worker was busy 4.01s per phrase while phrases arrived every 3.52s, so it
        fell behind on every one and its queue discarded a fifth of them, while
        this worker sat idle for most of the same interval.
        """
        started = perf_counter()
        debug_wav = self._write_debug_audio(debug_dir, segment.number, segment.audio)
        transcript = self._transcribe_audio_if_safe(segment.audio)
        if transcript is None:
            self._write_debug_note(debug_wav, "skipped", "")
            if self._verbose:
                print(f"Segment {segment.number}: skipped in {perf_counter() - started:.2f}s")
            return None

        translated = translator.translate(transcript.text)
        self._write_debug_note(debug_wav, transcript.text, translated)
        self._print_asr_rejections(transcript)
        if self._show_text:
            self._print_translation(transcript.text, translated, transcript.low_confidence)
        # low_confidence is a transcript-only signal, not a TTS gate: on the
        # 100-clip calibration set, most flagged EN segments were near-misses
        # (5 of 7 had WER under 0.19, often a single wrong word), not
        # meaning-changing errors, and avg_logprob doesn't separate the two
        # cleanly enough (r=-0.52 on English) to silence one without also
        # silencing the other. Missing audio for a mostly-correct phrase is
        # its own cost, not a free safety win.
        rendered = self._render_speech(speaker, translated, segment.number) if translated else None
        if self._verbose:
            queue_seconds = max(0.0, started - segment.captured_at)
            print(
                f"Segment {segment.number}: queue={queue_seconds:.2f}s "
                f"recognition+translation+synthesis={perf_counter() - started:.2f}s"
            )
        elif not self._show_text:
            self._print_phrase_progress(
                segment, transcript.low_confidence, perf_counter() - started
            )
        return rendered

    def _render_speech(
        self, speaker: TtsSpeaker, text: str, segment_number: int
    ) -> RenderedSpeech | None:
        """Render text to audio, or None if that fails or is disabled for the session.

        This runs on the recognition worker (see _process_live_segment's
        docstring), so an uncaught exception here would otherwise be fatal to
        the whole meeting via _recognition_loop's outer catch -- the wrong
        blast radius for a synthesis-only failure. UntrustedRuntimePath
        permanently disables further attempts, since a mistrusted path
        resolves the same way again and retrying would only repeat the same
        failure; anything else (a timeout, a corrupted binary) just skips
        this one phrase and keeps trying on the next, since those can be
        transient.
        """
        if self._tts_disabled_reason is not None:
            return None
        try:
            return speaker.render(text)
        except UntrustedRuntimePath as exc:
            self._tts_disabled_reason = str(exc)
            print(
                f"SECURITY WARNING: phrase {segment_number} tried to run a speech "
                f"executable outside every trusted location ({exc}). Spoken "
                f"playback is disabled for the rest of this meeting; "
                f"transcription and translation continue normally."
            )
            return None
        except Exception as exc:
            print(
                f"Warning: speech synthesis failed for phrase {segment_number}: "
                f"{exc}. Continuing without spoken output for this phrase."
            )
            return None

    def _create_realtime_workers(
        self,
        translator: TranslationEngine,
        speaker: TtsSpeaker,
        debug_dir: Path | None,
    ) -> RealtimeMeetingWorkers:
        return RealtimeMeetingWorkers(
            lambda segment: self._process_live_segment(segment, translator, speaker, debug_dir),
            speaker.play,
            segment_queue_size=self._config.realtime.recognition_queue_size,
            playback_queue_size=self._config.realtime.playback_queue_size,
        )

    def _transcribe_audio_if_safe(self, audio) -> TranscriptResult | None:
        if not self._audio_passes_energy_gate(audio):
            return None

        result = self._get_asr().transcribe(audio, self._config.audio.sample_rate)
        if not result.text:
            if result.rejected_segments and self._verbose:
                self._print_asr_rejections(result)
            if self._verbose:
                print("Skipping segment: ASR produced no accepted speech.")
            return None
        return result

    def _audio_passes_energy_gate(self, audio) -> bool:
        stats = analyze_audio(
            audio,
            self._config.audio.sample_rate,
            frame_ms=self._config.chunking.frame_ms,
            active_rms_threshold=self._config.chunking.rms_threshold,
            active_peak_threshold=self._config.chunking.peak_threshold,
        )
        if self._verbose:
            print(
                "Audio gate: "
                f"rms={stats.rms:.4f} peak={stats.peak:.4f} active={stats.active_ratio:.2f} "
                f"duration={stats.duration_seconds:.2f}s"
            )
        if has_enough_audio_energy(
            stats,
            rms_threshold=self._config.chunking.rms_threshold,
            peak_threshold=self._config.chunking.peak_threshold,
            min_active_ratio=self._config.chunking.min_active_ratio,
        ):
            return True

        if self._verbose:
            print(
                "Skipping segment: below speech energy gate "
                f"(rms>={self._config.chunking.rms_threshold:.4f}, "
                f"peak>={self._config.chunking.peak_threshold:.4f}, "
                f"active>={self._config.chunking.min_active_ratio:.2f})."
            )
        return False

    def _print_translation(
        self, source_text: str, target_text: str, low_confidence: bool = False
    ) -> None:
        source = self._config.translation.source_language.upper()
        target = self._config.translation.target_language.upper()
        # A flagged segment is not rejected -- it's still translated, shown,
        # and spoken in full (see _process_live_segment), just marked as one
        # the recognizer itself was uncertain about. On both lines, not just
        # the source one: someone reading only the target-language line
        # deserves the same warning as someone reading the source line. See
        # asr.flag_log_prob_threshold.
        marker = " [low confidence]" if low_confidence else ""
        print()
        print(f"{source}{marker}: {source_text}")
        print(f"{target}{marker}: {target_text}")

    def _announce_text_display(self) -> None:
        """Say once that the conversation will be on screen.

        Showing it is a deliberate choice, but the consequence is easy to
        forget: the terminal keeps scrollback, and a screen share shows it
        live. Not printed under --verbose, whose output other tooling parses.
        """
        if self._show_text and not self._verbose:
            print(
                "Showing transcripts and translations on screen. They remain in "
                "the terminal scrollback and are visible on a screen share."
            )

    def _print_phrase_progress(
        self, segment: CapturedSegment, low_confidence: bool, elapsed_seconds: float
    ) -> None:
        """Confirm a phrase was handled without saying what it was.

        Normal operation must not print meeting content, but it cannot print
        nothing either: translated speech goes to the virtual cable rather than
        the user's own headphones, so they never hear it. Without this line a
        muted microphone and a working session look identical until the other
        side says they heard silence. Number, length and elapsed time carry no
        content and cannot reconstruct any.
        """
        marker = "    low confidence" if low_confidence else ""
        audio_seconds = len(segment.audio) / self._config.audio.sample_rate
        print(
            f"Phrase {segment.number:>3}    {audio_seconds:.1f}s    "
            f"ready in {elapsed_seconds:.1f}s{marker}"
        )

    def _print_asr_rejections(self, result: TranscriptResult) -> None:
        if not self._verbose or not result.rejected_segments:
            return
        reasons = ", ".join(result.rejection_reasons[:3])
        if len(result.rejection_reasons) > 3:
            reasons += ", ..."
        print(f"ASR rejected {result.rejected_segments} low-confidence/no-speech segment(s): {reasons}")

    def _start_diagnostics(
        self, *, diagnostics: bool, debug_audio_dir: str | Path | None
    ) -> Path | None:
        """Decide whether this session captures meeting content, and where.

        Off unless somebody asked for it: the flag, the config setting, or an
        explicit path, which implies the flag so existing habits keep working.
        Returning None is what makes a normal meeting write nothing at all --
        the directory is not created, so there is no empty folder implying
        something was recorded. A directory that cannot be created, or a path
        resolve_capture_dir refuses (e.g. a relative path that climbs outside
        the per-user directory with `..`), returns None too: on a locked-down
        machine, losing diagnostics is an inconvenience and losing the meeting
        is not.
        """
        settings = self._config.diagnostics
        if not (diagnostics or settings.enabled or debug_audio_dir):
            return None

        try:
            root = resolve_capture_dir(settings, debug_audio_dir)
            capture_dir = root / session_directory_name()
            capture_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as exc:
            print(
                f"Diagnostic capture could not start: {exc}. "
                "Continuing without it; the meeting is not affected."
            )
            return None

        self._capture_limits = CaptureLimits(settings, root, capture_dir)
        print(capture_warning(capture_dir, settings))
        return capture_dir

    def _expire_old_diagnostics(self) -> None:
        """Age out old captures even when this session captures nothing.

        Someone who switches capture on once and never again would otherwise
        keep that content forever. Runs off the main thread because a full
        folder takes about 1.8 seconds to walk on this hardware, and nothing
        should delay a meeting starting.
        """
        settings = self._config.diagnostics
        if settings.retention_days <= 0:
            return
        try:
            root = resolve_capture_dir(settings)
        except ValueError:
            return
        if not root.is_dir():
            return

        Thread(
            target=lambda: sweep(settings, root),
            name="live-translator-diagnostics-sweep",
            daemon=True,
        ).start()

    def _note_capture(self, path: Path | None) -> None:
        """Account for a written artifact and report any cleanup it triggered."""
        if self._capture_limits is None:
            return
        result = self._capture_limits.record(path)
        if result:
            print(
                f"Diagnostics reached its {self._config.diagnostics.max_total_mb} MB limit: "
                f"removed the {result.files_removed} oldest file(s), "
                f"{result.bytes_freed / 1024 / 1024:.1f} MB freed."
            )

    def _write_debug_audio(self, debug_dir: Path | None, segment_number: int, audio) -> Path | None:
        if debug_dir is None:
            return None
        path = debug_dir / segment_audio_name(segment_number)
        write_wav(path, audio, self._config.audio.sample_rate)
        self._note_capture(path)
        return path

    def _write_debug_note(self, wav_path: Path | None, source: str, target: str) -> None:
        if wav_path is None:
            return
        note_path = wav_path.with_suffix(NOTE_SUFFIX)
        note_path.write_text(
            "\n".join(
                [
                    f"source={source}",
                    f"target={target}",
                    f"sample_rate={self._config.audio.sample_rate}",
                    f"input_device={self._config.audio.input_device}",
                    f"input_gain={self._config.audio.input_gain}",
                ]
            ),
            encoding="utf-8",
        )
        self._note_capture(note_path)

    def _print_audio_route(self) -> None:
        print("Audio routing:")
        print(
            "  Physical microphone: "
            + describe_device_selection(
                self._config.audio.input_device,
                "input",
                role="physical_input",
            )
        )
        if self._config.audio.output_device:
            print(
                "  Translated output:  "
                + describe_device_selection(
                    self._config.audio.output_device,
                    "output",
                    role="translated_output",
                )
            )
        if self._config.audio.peer_input_device:
            print(
                "  Meeting microphone: "
                + describe_device_selection(
                    self._config.audio.peer_input_device,
                    "input",
                    role="meeting_input",
                )
            )
