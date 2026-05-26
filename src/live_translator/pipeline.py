from __future__ import annotations

from pathlib import Path
from time import perf_counter

from live_translator.asr import FasterWhisperAsr
from live_translator.asr.faster_whisper_engine import TranscriptResult
from live_translator.audio.analysis import analyze_audio, has_enough_audio_energy
from live_translator.audio.io import play_mono, record_mono, write_wav
from live_translator.audio.rolling import RollingSpeechChunker
from live_translator.audio.vad import record_speech_segment
from live_translator.config import AppConfig
from live_translator.mt import TranslationEngine
from live_translator.tts import TtsSpeaker


class LocalTranslatorPipeline:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._asr: FasterWhisperAsr | None = None
        self._translator: TranslationEngine | None = None
        self._speaker: TtsSpeaker | None = None

    def record_test(self, output_path: str | Path, seconds: float | None = None, play: bool = False) -> None:
        audio = record_mono(self._config.audio, seconds)
        write_wav(output_path, audio, self._config.audio.sample_rate)
        print(f"Wrote {output_path}")
        if play:
            play_mono(audio, self._config.audio)

    def transcribe_once(self, seconds: float | None = None) -> str:
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

    def loopback(self, chunker_mode: str | None = None, debug_audio_dir: str | Path | None = None) -> None:
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

        print("Starting local loopback. Press Ctrl+C to stop.")
        if chunker == "vad":
            print(
                f"Chunker=vad silence={self._config.chunking.silence_ms}ms "
                f"min={self._config.chunking.min_segment_seconds:.1f}s "
                f"max={self._config.chunking.max_seconds:.1f}s "
                f"input={self._config.audio.input_device or 'default'} "
                f"output={self._config.audio.output_device or 'default'}"
            )
        elif chunker == "rolling":
            print(
                f"Chunker=rolling emit={self._config.chunking.min_segment_seconds:.1f}s "
                f"silence={self._config.chunking.silence_ms}ms "
                f"max={self._config.chunking.max_seconds:.1f}s "
                f"input={self._config.audio.input_device or 'default'} "
                f"output={self._config.audio.output_device or 'default'}"
            )
        else:
            print(
                f"Chunker=fixed chunk={self._config.audio.chunk_seconds:.1f}s "
                f"input={self._config.audio.input_device or 'default'} "
                f"output={self._config.audio.output_device or 'default'}"
            )
        try:
            segment_number = 0
            if chunker == "rolling":
                with RollingSpeechChunker(self._config.audio, self._config.chunking) as recorder:
                    while True:
                        segment_number += 1
                        started = perf_counter()
                        audio = recorder.next_chunk()
                        debug_wav = self._write_debug_audio(debug_dir, segment_number, audio)
                        transcript = self._transcribe_audio_if_safe(audio)
                        if transcript is None:
                            self._write_debug_note(debug_wav, "skipped", "")
                            print(f"Segment total: {perf_counter() - started:.2f}s")
                            continue
                        translated = translator.translate(transcript.text)
                        self._write_debug_note(debug_wav, transcript.text, translated)
                        self._print_asr_rejections(transcript)
                        if transcript.text:
                            print(f"Source: {transcript.text}")
                            print(f"Target: {translated}")
                        if translated:
                            speaker.speak(translated)
                        print(f"Segment total: {perf_counter() - started:.2f}s")
            else:
                while True:
                    segment_number += 1
                    started = perf_counter()
                    audio = self._record_loopback_segment(chunker)
                    debug_wav = self._write_debug_audio(debug_dir, segment_number, audio)
                    transcript = self._transcribe_audio_if_safe(audio)
                    if transcript is None:
                        self._write_debug_note(debug_wav, "skipped", "")
                        print(f"Segment total: {perf_counter() - started:.2f}s")
                        continue
                    translated = translator.translate(transcript.text)
                    self._write_debug_note(debug_wav, transcript.text, translated)
                    self._print_asr_rejections(transcript)
                    if transcript.text:
                        print(f"Source: {transcript.text}")
                        print(f"Target: {translated}")
                    if translated:
                        speaker.speak(translated)
                    print(f"Segment total: {perf_counter() - started:.2f}s")
        except KeyboardInterrupt:
            print("Stopped.")

    def _get_asr(self) -> FasterWhisperAsr:
        if self._asr is None:
            self._asr = FasterWhisperAsr(self._config.asr)
        return self._asr

    def _get_translator(self) -> TranslationEngine:
        if self._translator is None:
            self._translator = TranslationEngine(self._config.translation)
        return self._translator

    def _get_speaker(self) -> TtsSpeaker:
        if self._speaker is None:
            self._speaker = TtsSpeaker(self._config.tts, self._config.audio)
        return self._speaker

    def _record_loopback_segment(self, chunker: str):
        if chunker == "vad":
            return record_speech_segment(self._config.audio, self._config.chunking)
        return record_mono(self._config.audio)

    def _transcribe_audio_if_safe(self, audio) -> TranscriptResult | None:
        if not self._audio_passes_energy_gate(audio):
            return None

        result = self._get_asr().transcribe(audio, self._config.audio.sample_rate)
        if not result.text:
            if result.rejected_segments:
                self._print_asr_rejections(result)
            print("Skipping segment: ASR produced no accepted speech.")
            return None
        return result

    def _audio_passes_energy_gate(self, audio) -> bool:
        stats = analyze_audio(
            audio,
            self._config.audio.sample_rate,
            frame_ms=self._config.chunking.frame_ms,
            active_rms_threshold=self._config.chunking.rms_threshold,
        )
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

        print(
            "Skipping segment: below speech energy gate "
            f"(rms>={self._config.chunking.rms_threshold:.4f}, "
            f"peak>={self._config.chunking.peak_threshold:.4f}, "
            f"active>={self._config.chunking.min_active_ratio:.2f})."
        )
        return False

    def _print_asr_rejections(self, result: TranscriptResult) -> None:
        if not result.rejected_segments:
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
