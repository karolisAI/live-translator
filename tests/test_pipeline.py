import io
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from live_translator.config import AppConfig, AsrSettings, RealtimeSettings
from live_translator.asr.base import TranscriptResult
from live_translator.errors import ModelNotPrepared, UntrustedRuntimePath
from live_translator.pipeline import LocalTranslatorPipeline
from live_translator.tts.speaker import RenderedSpeech


class FakeSpeaker:
    def __init__(self) -> None:
        self.rendered: list[str] = []
        self.played: list[RenderedSpeech | None] = []
        self.spoken: list[str] = []
        self.render_exception: Exception | None = None

    def render(self, text: str) -> RenderedSpeech:
        self.rendered.append(text)
        if self.render_exception is not None:
            raise self.render_exception
        return RenderedSpeech(text, samples=[0.0], sample_rate=16000)

    def play(self, rendered: RenderedSpeech | None) -> None:
        self.played.append(rendered)

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def close(self) -> None:
        pass


class PipelineTests(unittest.TestCase):
    def test_realtime_queue_sizes_come_from_config(self) -> None:
        pipeline = LocalTranslatorPipeline(
            AppConfig(realtime=RealtimeSettings(recognition_queue_size=3, playback_queue_size=2))
        )

        workers = pipeline._create_realtime_workers(object(), FakeSpeaker(), None)

        self.assertEqual(workers._segments.maxsize, 3)
        self.assertEqual(workers._playback.maxsize, 2)

    def test_recognition_worker_synthesizes_so_playback_only_plays(self) -> None:
        """Synthesis must happen in the recognition worker. If it drifts back into
        the playback worker, that worker again costs synthesis plus playback per
        phrase, which is more than phrases take to arrive, and speech gets dropped."""
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return f"target: {text}"

        class FakeSegment:
            number = 1
            audio = [0.0] * 16000
            captured_at = 0.0

        transcript = TranscriptResult(
            text="source", language="en", duration_seconds=1.0, inference_seconds=0.1
        )
        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript):
            with redirect_stdout(io.StringIO()):
                result = pipeline._process_live_segment(
                    FakeSegment(), FakeTranslator(), speaker, None
                )

        self.assertEqual(speaker.rendered, ["target: source"])
        self.assertIsInstance(result, RenderedSpeech)
        self.assertEqual(result.text, "target: source")
        self.assertEqual(speaker.played, [])  # playback is the other worker's job

    def test_skipped_segment_renders_nothing(self) -> None:
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()

        class FakeSegment:
            number = 2
            audio = [0.0] * 16000
            captured_at = 0.0

        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=None):
            result = pipeline._process_live_segment(FakeSegment(), object(), speaker, None)

        self.assertIsNone(result)
        self.assertEqual(speaker.rendered, [])

    def test_low_confidence_segment_is_still_rendered(self) -> None:
        """low_confidence is a transcript-only marker (see PrintTranslationTests),
        not a TTS gate: on the 100-clip calibration set, most flagged EN
        segments were near-misses rather than meaning-changing errors, and
        avg_logprob doesn't separate the two cleanly enough to silence one
        without also silencing the other -- so flagged segments are voiced
        the same as any other accepted segment."""
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return f"target: {text}"

        class FakeSegment:
            number = 3
            audio = [0.0] * 16000
            captured_at = 0.0

        transcript = TranscriptResult(
            text="unsicher",
            language="de",
            duration_seconds=1.0,
            inference_seconds=0.1,
            low_confidence=True,
        )
        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript):
            result = pipeline._process_live_segment(
                FakeSegment(), FakeTranslator(), speaker, None
            )

        self.assertIsInstance(result, RenderedSpeech)
        self.assertEqual(speaker.rendered, ["target: unsicher"])

    def test_untrusted_executable_disables_further_synthesis_for_the_session(self) -> None:
        """Regression: this handling used to live in realtime.py's playback
        loop, where UntrustedRuntimePath from Piper could never actually
        reach it -- render() runs on the recognition worker (this method),
        so an uncaught exception here was fatal to the whole meeting via
        _recognition_loop's outer catch, instead of just disabling playback.
        This exercises the real path: speaker.render() itself raising, not
        a fake speak() standing in for it."""
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()
        speaker.render_exception = UntrustedRuntimePath(
            "piper.exe resolved outside every approved root"
        )

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return f"target: {text}"

        class FakeSegment:
            number = 1
            audio = [0.0] * 16000
            captured_at = 0.0

        transcript = TranscriptResult(
            text="source", language="en", duration_seconds=1.0, inference_seconds=0.1
        )
        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript):
            first = pipeline._process_live_segment(FakeSegment(), FakeTranslator(), speaker, None)
            second = pipeline._process_live_segment(FakeSegment(), FakeTranslator(), speaker, None)

        self.assertIsNone(first)
        self.assertIsNone(second)
        # render() was attempted once (that's how the untrusted path was
        # discovered) but never retried on the second phrase, since a
        # mistrusted path resolves the same way again.
        self.assertEqual(len(speaker.rendered), 1)

    def test_a_synthesis_failure_skips_one_phrase_and_keeps_trying(self) -> None:
        """Unlike UntrustedRuntimePath, a timeout or a corrupted binary can be
        transient -- it must not permanently disable synthesis, just skip the
        one phrase that hit it."""
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()
        speaker.render_exception = RuntimeError(
            "Piper (piper.exe) did not finish within 30s and was terminated."
        )

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return f"target: {text}"

        class FakeSegment:
            number = 1
            audio = [0.0] * 16000
            captured_at = 0.0

        transcript = TranscriptResult(
            text="source", language="en", duration_seconds=1.0, inference_seconds=0.1
        )
        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript):
            first = pipeline._process_live_segment(FakeSegment(), FakeTranslator(), speaker, None)
            speaker.render_exception = None
            second = pipeline._process_live_segment(FakeSegment(), FakeTranslator(), speaker, None)

        self.assertIsNone(first)
        self.assertIsInstance(second, RenderedSpeech)
        self.assertEqual(len(speaker.rendered), 2)


class TranslateOnceTests(unittest.TestCase):
    """translate_once (the one-shot debug/testing command) follows the same
    policy as the live path: a flagged transcript is translated, printed,
    and spoken exactly like any other accepted transcript."""

    def _run(self, *, low_confidence: bool) -> FakeSpeaker:
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return f"target: {text}"

        transcript = TranscriptResult(
            text="source",
            language="en",
            duration_seconds=1.0,
            inference_seconds=0.1,
            low_confidence=low_confidence,
        )
        with (
            patch.object(pipeline, "prepare"),
            patch.object(pipeline, "_get_translator", return_value=FakeTranslator()),
            patch.object(pipeline, "_get_speaker", return_value=speaker),
            patch("live_translator.pipeline.record_mono", return_value=[0.0] * 16000),
            patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript),
        ):
            pipeline.translate_once()
        return speaker

    def test_speaks_a_confident_translation(self) -> None:
        speaker = self._run(low_confidence=False)
        self.assertEqual(speaker.spoken, ["target: source"])

    def test_speaks_a_low_confidence_translation_too(self) -> None:
        speaker = self._run(low_confidence=True)
        self.assertEqual(speaker.spoken, ["target: source"])


class NormalModeOutputTests(unittest.TestCase):
    """A normal meeting must not print what was said. Diagnostics privacy: the
    console is the one place meeting content leaked without anyone opting in,
    and terminal scrollback keeps it for the rest of the session."""

    def _run_segment(
        self, *, verbose: bool, show_text: bool = False, low_confidence: bool = False
    ) -> str:
        pipeline = LocalTranslatorPipeline(AppConfig())
        pipeline._verbose = verbose
        pipeline._show_text = show_text

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return "geheime Übersetzung"

        class FakeSegment:
            number = 7
            audio = [0.0] * 16000
            captured_at = 0.0

        transcript = TranscriptResult(
            text="confidential source",
            language="en",
            duration_seconds=1.0,
            inference_seconds=0.1,
            low_confidence=low_confidence,
        )
        buffer = io.StringIO()
        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript):
            with redirect_stdout(buffer):
                pipeline._process_live_segment(
                    FakeSegment(), FakeTranslator(), FakeSpeaker(), None
                )
        return buffer.getvalue()

    def test_normal_mode_prints_neither_source_nor_target(self) -> None:
        output = self._run_segment(verbose=False)

        self.assertNotIn("confidential source", output)
        self.assertNotIn("geheime Übersetzung", output)

    def test_normal_mode_still_confirms_the_phrase_was_handled(self) -> None:
        """Without this the user has no signal at all: translated speech goes to
        the virtual cable, not to their own headphones."""
        output = self._run_segment(verbose=False)

        self.assertIn("Phrase", output)
        self.assertIn("7", output)

    def test_low_confidence_is_marked_without_showing_the_text(self) -> None:
        output = self._run_segment(verbose=False, low_confidence=True)

        self.assertIn("low confidence", output)
        self.assertNotIn("confidential source", output)

    def test_verbose_alone_does_not_print_source_or_target(self) -> None:
        """--verbose is operational telemetry -- audio gates, per-segment
        timing -- not a second way to display meeting content. Someone
        troubleshooting VAD during a confidential meeting should not retain
        the conversation in scrollback without asking for it specifically."""
        output = self._run_segment(verbose=True, show_text=False)

        self.assertNotIn("confidential source", output)
        self.assertNotIn("geheime Übersetzung", output)

    def test_verbose_alone_still_shows_its_own_telemetry(self) -> None:
        """The fix above must not silence --verbose entirely, only the text."""
        output = self._run_segment(verbose=True, show_text=False)

        self.assertIn("Segment 7:", output)

    def test_verbose_and_show_text_together_shows_the_text(self) -> None:
        """Asking for both must not cancel either one out."""
        output = self._run_segment(verbose=True, show_text=True)

        self.assertIn("confidential source", output)
        self.assertIn("geheime Übersetzung", output)


class PrintTranslationTests(unittest.TestCase):
    """low_confidence is a marker on an otherwise fully shown segment, not a
    second rejection -- both source and target text always print in full."""

    def test_marks_both_lines_when_flagged(self) -> None:
        """The marker used to appear on the source line only -- someone
        reading just the target-language line would never see any warning
        at all, even though the segment is spoken and shown just like any
        other (see PipelineTests.test_low_confidence_segment_is_still_rendered)."""
        pipeline = LocalTranslatorPipeline(AppConfig())
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            pipeline._print_translation("unsicherer Satz", "uncertain sentence", low_confidence=True)

        lines = buffer.getvalue().splitlines()
        source_line = next(line for line in lines if "unsicherer Satz" in line)
        target_line = next(line for line in lines if "uncertain sentence" in line)
        self.assertIn("[low confidence]", source_line)
        self.assertIn("[low confidence]", target_line)

    def test_no_marker_when_not_flagged(self) -> None:
        pipeline = LocalTranslatorPipeline(AppConfig())
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            pipeline._print_translation("klarer Satz", "clear sentence", low_confidence=False)

        self.assertNotIn("[low confidence", buffer.getvalue())


class SpeakerShutdownTests(unittest.TestCase):
    """prepare() starts a resident Piper process, and a subprocess child is
    not killed automatically when this process exits. Every exit path out of
    a command that called prepare() therefore has to close the speaker, not
    just the happy one."""

    def _pipeline_with_fake_speaker(self):
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()
        speaker.closed = 0
        speaker.close = lambda: setattr(speaker, "closed", speaker.closed + 1)
        return pipeline, speaker

    def test_loopback_closes_the_speaker_when_it_fails_before_the_worker_loop(self) -> None:
        """An unsupported chunker raises after prepare() has already warmed
        Piper up. Verified against a real process count before this was
        fixed: it left an orphaned piper.exe behind."""
        pipeline, speaker = self._pipeline_with_fake_speaker()

        with (
            patch.object(pipeline, "_print_audio_route"),
            patch.object(pipeline, "prepare"),
            patch.object(pipeline, "_get_translator"),
            patch.object(pipeline, "_get_speaker", return_value=speaker),
        ):
            with self.assertRaises(ValueError):
                pipeline.loopback(chunker_mode="nonsense")

        self.assertEqual(speaker.closed, 1)

    def test_translate_once_closes_the_speaker_when_preparation_fails(self) -> None:
        pipeline, speaker = self._pipeline_with_fake_speaker()

        with (
            patch.object(pipeline, "prepare", side_effect=RuntimeError("model exploded")),
            patch.object(pipeline, "_get_speaker", return_value=speaker),
        ):
            with self.assertRaises(RuntimeError):
                pipeline.translate_once()

        self.assertEqual(speaker.closed, 1)

    def test_translate_once_does_not_build_a_speaker_when_not_speaking(self) -> None:
        """--no-speak must not start a Piper process just to close it."""
        pipeline = LocalTranslatorPipeline(AppConfig())

        with (
            patch.object(pipeline, "prepare"),
            patch.object(pipeline, "_get_translator"),
            patch.object(pipeline, "_get_speaker") as get_speaker,
            patch("live_translator.pipeline.record_mono", return_value=[0.0] * 16000),
            patch.object(pipeline, "_transcribe_audio_if_safe", return_value=None),
        ):
            pipeline.translate_once(speak=False)

        get_speaker.assert_not_called()


class OfflineStartupOrderTests(unittest.TestCase):
    """`loopback` opens the microphone only after `prepare()` returns, so an
    unprepared machine has to fail while there is still no meeting audio in the
    process at all. Asserting the ordering is the only way to keep it: both
    calls succeed independently, and only their sequence carries the property.
    """

    def test_missing_model_fails_before_any_audio_is_captured(self) -> None:
        with TemporaryDirectory() as tmp:
            config = replace(
                AppConfig(), asr=AsrSettings(model_dir=str(Path(tmp) / "never-prepared"))
            )
            pipeline = LocalTranslatorPipeline(config)

            with patch("live_translator.pipeline.record_mono") as fake_record:
                with redirect_stdout(io.StringIO()):
                    with self.assertRaises(ModelNotPrepared):
                        pipeline.prepare()

            fake_record.assert_not_called()


class ShowTextTests(unittest.TestCase):
    """A deliberate way to watch the conversation, without the debug output.

    Normal mode shows no content and --verbose shows content buried in gate
    lines and per-segment timings, so watching a meeting meant reading roughly
    seven lines per phrase to find three. This flag restores the old readable
    view as an explicit act.
    """

    def _run_segment(self, *, verbose: bool, show_text: bool) -> str:
        pipeline = LocalTranslatorPipeline(AppConfig())
        pipeline._verbose = verbose
        pipeline._show_text = show_text

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return "geheime Uebersetzung"

        class FakeSegment:
            number = 4
            audio = [0.0] * 16000
            captured_at = 0.0

        transcript = TranscriptResult(
            text="confidential source",
            language="en",
            duration_seconds=1.0,
            inference_seconds=0.1,
        )
        buffer = io.StringIO()
        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript):
            with redirect_stdout(buffer):
                pipeline._process_live_segment(
                    FakeSegment(), FakeTranslator(), FakeSpeaker(), None
                )
        return buffer.getvalue()

    def test_show_text_prints_the_conversation(self) -> None:
        output = self._run_segment(verbose=False, show_text=True)

        self.assertIn("confidential source", output)
        self.assertIn("geheime Uebersetzung", output)

    def test_show_text_replaces_the_phrase_counter(self) -> None:
        """Both would be redundant: the text itself shows the pipeline is alive."""
        output = self._run_segment(verbose=False, show_text=True)

        self.assertNotIn("Phrase", output)

    def test_show_text_does_not_bring_the_debug_output_with_it(self) -> None:
        output = self._run_segment(verbose=False, show_text=True)

        self.assertNotIn("Segment 4", output)
        self.assertNotIn("Audio gate", output)

    def test_default_still_shows_no_content(self) -> None:
        output = self._run_segment(verbose=False, show_text=False)

        self.assertNotIn("confidential source", output)
        self.assertIn("Phrase", output)

    def test_it_says_once_that_the_conversation_will_be_visible(self) -> None:
        pipeline = LocalTranslatorPipeline(AppConfig())
        pipeline._show_text = True
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            pipeline._announce_text_display()

        self.assertIn("scrollback", buffer.getvalue())

    def test_verbose_does_not_gain_the_announcement(self) -> None:
        """--verbose output is parsed by the latency harness; leave it alone."""
        pipeline = LocalTranslatorPipeline(AppConfig())
        pipeline._show_text = True
        pipeline._verbose = True
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            pipeline._announce_text_display()

        self.assertEqual(buffer.getvalue(), "")



if __name__ == "__main__":
    unittest.main()
