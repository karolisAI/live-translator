import unittest
from unittest.mock import patch

import numpy as np

from live_translator.audio.route_test import test_output_to_input_route as run_route_test


class FakeSoundDevice:
    def __init__(self, capture) -> None:
        self._capture = capture

    def playrec(self, output, *, samplerate, **_kwargs):
        played = np.asarray(output, dtype=np.float32).reshape(-1)
        captured = self._capture(played, samplerate)
        return np.asarray(captured, dtype=np.float32).reshape(-1, 1)

    def wait(self) -> None:
        return None


class RouteTestTests(unittest.TestCase):
    def _run_route_test(self, capture):
        sound_device = FakeSoundDevice(capture)
        with (
            patch("live_translator.audio.route_test._audio_packages", return_value=(sound_device, np)),
            patch("live_translator.audio.route_test.resolve_device_index", return_value=1),
            patch("live_translator.audio.route_test._candidate_rates", return_value=[16000]),
        ):
            return run_route_test(
                output_device="output",
                input_device="input",
                sample_rate=16000,
            )

    def test_generated_tone_passes(self) -> None:
        result = self._run_route_test(lambda played, _rate: played * 0.5)

        self.assertTrue(result.passed)
        self.assertGreater(result.tone_rms, 0.05)
        self.assertGreater(result.tone_ratio, 0.99)

    def test_loud_unrelated_tone_does_not_false_pass(self) -> None:
        def capture(played, sample_rate):
            time = np.arange(len(played), dtype=np.float32) / float(sample_rate)
            return 0.2 * np.sin(2.0 * np.pi * 440.0 * time)

        result = self._run_route_test(capture)

        self.assertGreater(result.rms, 0.1)
        self.assertLess(result.tone_rms, 0.01)
        self.assertFalse(result.passed)

    def test_loud_noise_does_not_false_pass(self) -> None:
        random = np.random.default_rng(42)

        def capture(played, _sample_rate):
            return random.normal(0.0, 0.08, len(played)).astype(np.float32)

        result = self._run_route_test(capture)

        self.assertGreater(result.rms, 0.05)
        self.assertLess(result.tone_ratio, 0.1)
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
