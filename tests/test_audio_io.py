import unittest
from unittest.mock import patch

import numpy as np

from live_translator.audio.io import _resample_audio, play_mono
from live_translator.config import AudioSettings


class _FakeOutputStream:
    def __init__(self, owner, device: int) -> None:
        self._owner = owner
        self._device = device

    def start(self) -> None:
        self._owner.starts.append(self._device)
        if self._owner.start_failures_remaining:
            self._owner.start_failures_remaining -= 1
            raise RuntimeError("temporary WASAPI host error")

    def write(self, frames) -> None:
        self._owner.writes.append((self._device, frames.shape))

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeSoundDevice:
    def __init__(self, start_failures: int = 0) -> None:
        self.starts: list[int] = []
        self.writes: list[tuple[int, tuple[int, ...]]] = []
        self.start_failures_remaining = start_failures

    def OutputStream(self, *, device: int, **_kwargs):
        return _FakeOutputStream(self, device)

    def query_devices(self, _device=None, **_kwargs):
        return {"max_output_channels": 2}


class AudioIoTests(unittest.TestCase):
    def test_resample_48k_to_16k_preserves_duration(self) -> None:
        samples = np.arange(6, dtype=np.float32)

        resampled = _resample_audio(np, samples, 48000, 16000)

        np.testing.assert_array_equal(resampled, np.array([0.0, 3.0], dtype=np.float32))

    def test_downsampling_filters_frequencies_above_target_nyquist(self) -> None:
        source_rate = 48000
        samples = np.sin(
            2.0 * np.pi * 12000.0 * np.arange(source_rate // 10) / source_rate
        ).astype(np.float32)

        resampled = _resample_audio(np, samples, source_rate, 16000)

        self.assertEqual(len(resampled), 1600)
        self.assertLess(float(np.sqrt(np.mean(np.square(resampled)))), 0.05)

    def test_upsampling_piper_audio_preserves_duration_and_pitch(self) -> None:
        source_rate = 22050
        target_rate = 48000
        frequency = 440.0
        time = np.arange(source_rate, dtype=np.float32) / source_rate
        source = np.sin(2.0 * np.pi * frequency * time).astype(np.float32)

        resampled = _resample_audio(np, source, source_rate, target_rate)
        spectrum = np.abs(np.fft.rfft(resampled))
        frequencies = np.fft.rfftfreq(len(resampled), 1.0 / target_rate)
        measured_frequency = float(frequencies[int(np.argmax(spectrum))])

        self.assertEqual(len(resampled), target_rate)
        self.assertAlmostEqual(measured_frequency, frequency, delta=1.0)

    def test_playback_retries_transient_start_failure_on_same_endpoint(self) -> None:
        sounddevice = _FakeSoundDevice(start_failures=1)
        settings = AudioSettings(sample_rate=48000, output_device="auto")

        with (
            patch("live_translator.audio.io._audio_packages", return_value=(sounddevice, np)),
            patch("live_translator.audio.io.resolve_device_index", return_value=26),
            patch("live_translator.audio.io._select_sample_rate", return_value=48000),
            patch(
                "live_translator.audio.io.describe_device_index",
                side_effect=lambda index, _kind: f"device {index}",
            ),
            patch("live_translator.audio.io.sleep"),
        ):
            play_mono(np.zeros(480, dtype=np.float32), settings)

        self.assertEqual(sounddevice.starts, [26, 26])
        self.assertEqual(sounddevice.writes, [(26, (480, 2))])

    def test_playback_reports_persistent_start_failure_after_three_attempts(self) -> None:
        sounddevice = _FakeSoundDevice(start_failures=3)
        settings = AudioSettings(sample_rate=48000, output_device="auto")

        with (
            patch("live_translator.audio.io._audio_packages", return_value=(sounddevice, np)),
            patch("live_translator.audio.io.resolve_device_index", return_value=26),
            patch("live_translator.audio.io._select_sample_rate", return_value=48000),
            patch(
                "live_translator.audio.io.describe_device_index",
                side_effect=lambda index, _kind: f"device {index}",
            ),
            patch("live_translator.audio.io.sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Could not play translated speech"):
                play_mono(np.zeros(480, dtype=np.float32), settings)

        self.assertEqual(sounddevice.starts, [26, 26, 26])
        self.assertEqual(sounddevice.writes, [])


if __name__ == "__main__":
    unittest.main()
