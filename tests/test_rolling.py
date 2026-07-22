import unittest
from threading import Event
from unittest.mock import patch

import numpy as np

from live_translator.audio.rolling import RollingSpeechChunker
from live_translator.config import AudioSettings, ChunkingSettings


class FakeSoundDevice:
    pass


class RollingSpeechChunkerTests(unittest.TestCase):
    def _chunker(
        self,
        *,
        emit_while_speaking: bool = True,
        min_speech_ms: int = 10,
        min_segment_seconds: float = 0.03,
        rolling_window_seconds: float | None = None,
        pre_roll_ms: int = 10,
    ) -> RollingSpeechChunker:
        sample_rate = 1000
        with (
            patch("live_translator.audio.rolling._audio_packages", return_value=(FakeSoundDevice(), np)),
            patch("live_translator.audio.rolling.resolve_device_index", return_value=3),
            patch("live_translator.audio.rolling._select_sample_rate", return_value=sample_rate),
        ):
            return RollingSpeechChunker(
                AudioSettings(sample_rate=sample_rate, input_device="3"),
                ChunkingSettings(
                    frame_ms=10,
                    silence_ms=20,
                    min_speech_ms=min_speech_ms,
                    min_segment_seconds=min_segment_seconds,
                    rolling_window_seconds=rolling_window_seconds or min_segment_seconds,
                    pre_roll_ms=pre_roll_ms,
                    max_seconds=1.0,
                    rms_threshold=0.01,
                    peak_threshold=0.01,
                    min_active_ratio=0.01,
                ),
                emit_while_speaking=emit_while_speaking,
                verbose=False,
            )

    def test_trailing_silence_resets_without_emitting_silence_forever(self) -> None:
        chunker = self._chunker()
        speech = np.full(chunker._frame_samples, 0.05, dtype=np.float32)
        silent = np.zeros(chunker._frame_samples, dtype=np.float32)

        first = chunker._process_block(np.concatenate([speech, speech, speech]))
        self.assertIsNotNone(first)
        self.assertTrue(chunker._speech_started)

        self.assertIsNone(chunker._process_block(silent))
        self.assertIsNone(chunker._process_block(silent))
        self.assertFalse(chunker._speech_started)
        self.assertEqual(chunker._frames, [])

        self.assertIsNone(chunker._process_block(np.concatenate([silent] * 6)))
        self.assertFalse(chunker._speech_started)

    def test_trailing_silence_emits_new_tail_then_resets(self) -> None:
        chunker = self._chunker(min_segment_seconds=0.05)
        speech = np.full(chunker._frame_samples, 0.05, dtype=np.float32)
        silent = np.zeros(chunker._frame_samples, dtype=np.float32)

        first = chunker._process_block(np.concatenate([speech] * 5))
        self.assertIsNotNone(first)

        self.assertIsNone(chunker._process_block(speech))
        self.assertIsNone(chunker._process_block(silent))
        self.assertIsNone(chunker._process_block(silent))
        tail = chunker._process_block(silent)

        self.assertIsNotNone(tail)
        self.assertEqual(len(tail), chunker._frame_samples * 5)
        self.assertFalse(chunker._speech_started)
        self.assertIsNone(chunker._process_block(np.concatenate([silent] * 4)))

    def test_callback_keeps_latest_window_and_resets_stale_segment(self) -> None:
        chunker = self._chunker()
        old_speech = np.full(chunker._frame_samples, 0.5, dtype=np.float32)
        chunker._frames = [old_speech]
        chunker._speech_started = True
        chunker._new_speech_frames = 1

        values = [0.05, 0.06, 0.07, 0.08, 0.09]
        for value in values:
            frame = np.full(chunker._frame_samples, value, dtype=np.float32)
            chunker._callback(frame.reshape(-1, 1), len(frame), None, None)

        self.assertEqual(chunker._queue.qsize(), chunker._emit_frames)
        self.assertEqual(chunker._dropped_blocks, 2)

        emitted = chunker.next_chunk()

        self.assertEqual(len(emitted), chunker._frame_samples * chunker._emit_frames)
        self.assertFalse(np.any(np.isclose(emitted, 0.5)))
        np.testing.assert_allclose(
            [
                float(np.mean(emitted[index : index + chunker._frame_samples]))
                for index in range(0, len(emitted), chunker._frame_samples)
            ],
            values[-chunker._emit_frames :],
            atol=1e-6,
        )
        self.assertEqual(chunker._dropped_blocks, 0)

    def test_vad_mode_keeps_collecting_while_speech_continues(self) -> None:
        chunker = self._chunker(emit_while_speaking=False, min_segment_seconds=0.03)
        speech = np.full(chunker._frame_samples, 0.05, dtype=np.float32)
        silent = np.zeros(chunker._frame_samples, dtype=np.float32)

        self.assertIsNone(chunker._process_block(np.concatenate([speech] * 6)))
        self.assertIsNone(chunker._process_block(silent))
        emitted = chunker._process_block(silent)

        self.assertIsNotNone(emitted)
        self.assertEqual(len(emitted), chunker._frame_samples * 8)
        self.assertFalse(chunker._speech_started)

    def test_short_noise_trigger_is_not_emitted(self) -> None:
        chunker = self._chunker(
            emit_while_speaking=False,
            min_speech_ms=30,
            min_segment_seconds=0.03,
        )
        spike = np.full(chunker._frame_samples, 0.05, dtype=np.float32)
        silent = np.zeros(chunker._frame_samples, dtype=np.float32)

        self.assertIsNone(chunker._process_block(spike))
        self.assertIsNone(chunker._process_block(silent))
        self.assertIsNone(chunker._process_block(silent))
        self.assertFalse(chunker._speech_started)

    def test_next_chunk_exits_when_session_stops(self) -> None:
        chunker = self._chunker()
        stop_event = Event()
        stop_event.set()

        self.assertIsNone(chunker.next_chunk(stop_event=stop_event))

    def test_rolling_window_is_independent_from_vad_minimum(self) -> None:
        chunker = self._chunker(
            min_segment_seconds=0.03,
            rolling_window_seconds=0.08,
        )

        self.assertEqual(chunker._min_segment_frames, 3)
        self.assertEqual(chunker._emit_frames, 8)


if __name__ == "__main__":
    unittest.main()
