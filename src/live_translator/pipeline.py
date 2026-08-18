from __future__ import annotations

from pathlib import Path
from time import perf_counter

from live_translator.asr import AsrEngine, TranscriptResult, create_asr
from live_translator.audio.analysis import analyze_audio, has_enough_audio_energy
from live_translator.audio.devices import describe_device_selection
from live_translator.audio.io import play_mono, record_mono, write_wav
from live_translator.audio.rolling import RollingSpeechChunker
from live_translator.config import AppConfig
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
    ) -> None:
        self._verbose = verbose
        self._print_audio_route()
        self.prepare()
        translator = self._get_translator()
        speaker = self._get_speaker()
        debug_dir = Path(debug_audio_dir) if debug_audio_dir else None
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            print(f"Writing debug audio chunks to {debug_dir}")
        chunker = (chunker_mode or self._config.chunking.mode).lower()
        if chunker in {"phrase", "speech"}:
            chunker = "vad"
        if chunker not in {"fixed", "vad", "rolling"}:
            raise ValueError("Unsupported chunker mode. Use 'fixed', 'vad', or 'rolling'.")

        source = self._config.translation.source_language.upper()
        target = self._config.translation.target_language.upper()
        print(f"Direction: {source} -> {target}")
        print("Live translation active. Listening continuously between phrases.")
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
        self._print_translation(transcript.text, translated, transcript.low_confidence)
        rendered = speaker.render(translated) if translated else None
        if self._verbose:
            queue_seconds = max(0.0, started - segment.captured_at)
            print(
                f"Segment {segment.number}: queue={queue_seconds:.2f}s "
                f"recognition+translation+synthesis={perf_counter() - started:.2f}s"
            )
        return rendered

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
        # A flagged segment is not rejected -- it's still translated and shown
        # in full, just marked as one the recognizer itself was uncertain
        # about, favoring a visible-but-quiet marker over silently dropping
        # possibly-correct content. See asr.flag_log_prob_threshold.
        marker = " [low confidence]" if low_confidence else ""
        print()
        print(f"{source}{marker}: {source_text}")
        print(f"{target}: {target_text}")

    def _print_asr_rejections(self, result: TranscriptResult) -> None:
        if not self._verbose or not result.rejected_segments:
            return
        reasons = ", ".join(result.rejection_reasons[:3])
        if len(result.rejection_reasons) > 3:
            reasons += ", ..."
        print(f"ASR rejected {result.rejected_segments} low-confidence/no-speech segment(s): {reasons}")

    def _write_debug_audio(self, debug_dir: Path | None, segment_number: int, audio) -> Path | None:
        if debug_dir is None:
            return None
        path = debug_dir / f"segment-{segment_number:04d}.wav"
        write_wav(path, audio, self._config.audio.sample_rate)
        return path

    def _write_debug_note(self, wav_path: Path | None, source: str, target: str) -> None:
        if wav_path is None:
            return
        note_path = wav_path.with_suffix(".txt")
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
