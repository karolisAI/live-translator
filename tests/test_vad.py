import unittest
from unittest.mock import patch

import numpy as np

from live_translator.audio.vad import record_speech_segment
from live_translator.config import AudioSettings, ChunkingSettings


class FakeInputStream:
    def __init__(self, *, blocks: list[np.ndarray], callback, **kwargs) -> None:
        self.blocks = blocks
        self.callback = callback
        self.kwargs = kwargs

    def __enter__(self):
        for block in self.blocks:
            self.callback(block.reshape(-1, 1).astype(np.float32), len(block), None, None)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSoundDevice:
    def __init__(self, blocks: list[np.ndarray]) -> None:
        self.blocks = blocks
        self.input_stream_calls: list[dict[str, object]] = []

    def InputStream(self, **kwargs):  # noqa: N802
        self.input_stream_calls.append(kwargs)
        return FakeInputStream(blocks=self.blocks, **kwargs)


class VadTests(unittest.TestCase):
    def test_vad_uses_continuous_stream_capture(self) -> None:
        sample_rate = 16000
        frame_samples = int(sample_rate * 0.03)
        silent = np.zeros(frame_samples, dtype=np.float32)
        speech = np.full(frame_samples, 0.05, dtype=np.float32)
        blocks = [np.concatenate([silent, speech, silent, silent])]
        fake_sd = FakeSoundDevice(blocks)

        with (
            patch("live_translator.audio.vad._audio_packages", return_value=(fake_sd, np)),
            patch("live_translator.audio.vad.resolve_device_index", return_value=3),
            patch("live_translator.audio.vad._select_sample_rate", return_value=sample_rate),
        ):
            audio = record_speech_segment(
                AudioSettings(sample_rate=sample_rate, input_device="3"),
                ChunkingSettings(
                    frame_ms=30,
                    silence_ms=60,
                    min_speech_ms=30,
                    min_segment_seconds=0.09,
                    pre_roll_ms=30,
                    max_seconds=1.0,
                    rms_threshold=0.01,
                    peak_threshold=0.01,
                    min_active_ratio=0.01,
                ),
                verbose=False,
            )

        self.assertEqual(len(fake_sd.input_stream_calls), 1)
        stream_kwargs = fake_sd.input_stream_calls[0]
        self.assertEqual(stream_kwargs["device"], 3)
        self.assertEqual(stream_kwargs["blocksize"], frame_samples)
        self.assertEqual(stream_kwargs["samplerate"], sample_rate)
        np.testing.assert_array_equal(audio, blocks[0])

    def test_vad_detects_peak_energy_even_when_rms_is_low(self) -> None:
        sample_rate = 16000
        frame_samples = int(sample_rate * 0.03)
        silent = np.zeros(frame_samples, dtype=np.float32)
        speech = np.zeros(frame_samples, dtype=np.float32)
        speech[::80] = 0.06
        blocks = [np.concatenate([silent, speech, silent, silent])]
        fake_sd = FakeSoundDevice(blocks)

        with (
            patch("live_translator.audio.vad._audio_packages", return_value=(fake_sd, np)),
            patch("live_translator.audio.vad.resolve_device_index", return_value=3),
            patch("live_translator.audio.vad._select_sample_rate", return_value=sample_rate),
        ):
            audio = record_speech_segment(
                AudioSettings(sample_rate=sample_rate, input_device="3"),
                ChunkingSettings(
                    frame_ms=30,
                    silence_ms=60,
                    min_speech_ms=30,
                    min_segment_seconds=0.09,
                    pre_roll_ms=30,
                    max_seconds=1.0,
                    rms_threshold=0.02,
                    peak_threshold=0.05,
                    min_active_ratio=0.01,
                ),
                verbose=False,
            )

        self.assertEqual(len(fake_sd.input_stream_calls), 1)
        np.testing.assert_array_equal(audio, blocks[0])

    def test_vad_resamples_back_to_pipeline_rate(self) -> None:
        capture_rate = 48000
        pipeline_rate = 16000
        frame_samples = int(capture_rate * 0.03)
        silent = np.zeros(frame_samples, dtype=np.float32)
        speech = np.full(frame_samples, 0.05, dtype=np.float32)
        blocks = [silent, speech, silent, silent]
        fake_sd = FakeSoundDevice(blocks)

        with (
            patch("live_translator.audio.vad._audio_packages", return_value=(fake_sd, np)),
            patch("live_translator.audio.vad.resolve_device_index", return_value=3),
            patch("live_translator.audio.vad._select_sample_rate", return_value=capture_rate),
        ):
            audio = record_speech_segment(
                AudioSettings(sample_rate=pipeline_rate, input_device="3"),
                ChunkingSettings(
                    frame_ms=30,
                    silence_ms=60,
                    min_speech_ms=30,
                    min_segment_seconds=0.09,
                    pre_roll_ms=30,
                    max_seconds=1.0,
                    rms_threshold=0.01,
                    peak_threshold=0.01,
                    min_active_ratio=0.01,
                ),
                verbose=False,
            )

        self.assertEqual(len(fake_sd.input_stream_calls), 1)
        self.assertEqual(len(audio), int(round((frame_samples * 4) * pipeline_rate / capture_rate)))
        self.assertAlmostEqual(float(np.max(audio)), 0.05, places=4)

    def test_vad_resets_short_false_trigger_before_next_phrase(self) -> None:
        sample_rate = 1000
        frame_samples = int(sample_rate * 0.03)
        silent = np.zeros(frame_samples, dtype=np.float32)
        false_trigger = np.full(frame_samples, 0.02, dtype=np.float32)
        speech = np.full(frame_samples, 0.05, dtype=np.float32)
        blocks = [
            np.concatenate(
                [
                    false_trigger,
                    silent,
                    silent,
                    speech,
                    speech,
                    speech,
                    silent,
                    silent,
                ]
            )
        ]
        fake_sd = FakeSoundDevice(blocks)

        with (
            patch("live_translator.audio.vad._audio_packages", return_value=(fake_sd, np)),
            patch("live_translator.audio.vad.resolve_device_index", return_value=3),
            patch("live_translator.audio.vad._select_sample_rate", return_value=sample_rate),
        ):
            audio = record_speech_segment(
                AudioSettings(sample_rate=sample_rate, input_device="3"),
                ChunkingSettings(
                    frame_ms=30,
                    silence_ms=60,
                    min_speech_ms=90,
                    min_segment_seconds=0.15,
                    pre_roll_ms=30,
                    max_seconds=1.0,
                    rms_threshold=0.01,
                    peak_threshold=0.01,
                    min_active_ratio=0.01,
                ),
                verbose=False,
            )

        self.assertEqual(len(audio), frame_samples * 6)
        self.assertFalse(np.any(np.isclose(audio, 0.02)))
        self.assertEqual(int(np.count_nonzero(np.isclose(audio, 0.05))), frame_samples * 3)

    def test_input_gain_affects_detection_without_double_gain(self) -> None:
        sample_rate = 1000
        frame_samples = int(sample_rate * 0.03)
        silent = np.zeros(frame_samples, dtype=np.float32)
        quiet_speech = np.full(frame_samples, 0.006, dtype=np.float32)
        fallback_speech = np.full(frame_samples, 0.05, dtype=np.float32)
        blocks = [
            np.concatenate(
                [
                    quiet_speech,
                    silent,
                    silent,
                    fallback_speech,
                    silent,
                    silent,
                ]
            )
        ]
        fake_sd = FakeSoundDevice(blocks)

        with (
            patch("live_translator.audio.vad._audio_packages", return_value=(fake_sd, np)),
            patch("live_translator.audio.vad.resolve_device_index", return_value=3),
            patch("live_translator.audio.vad._select_sample_rate", return_value=sample_rate),
        ):
            audio = record_speech_segment(
                AudioSettings(sample_rate=sample_rate, input_device="3", input_gain=2.0),
                ChunkingSettings(
                    frame_ms=30,
                    silence_ms=60,
                    min_speech_ms=30,
                    min_segment_seconds=0.09,
                    pre_roll_ms=0,
                    max_seconds=1.0,
                    rms_threshold=0.01,
                    peak_threshold=0.01,
                    min_active_ratio=0.01,
                ),
                verbose=False,
            )

        self.assertEqual(len(audio), frame_samples * 3)
        self.assertAlmostEqual(float(np.max(audio)), 0.012, places=5)


if __name__ == "__main__":
    unittest.main()
