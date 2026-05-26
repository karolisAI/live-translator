import unittest

import numpy as np

from live_translator.audio.analysis import analyze_audio, has_enough_audio_energy


class AudioAnalysisTests(unittest.TestCase):
    def test_silence_does_not_pass_energy_gate(self) -> None:
        audio = np.zeros(16000, dtype=np.float32)
        stats = analyze_audio(audio, 16000, frame_ms=30, active_rms_threshold=0.012)

        self.assertEqual(stats.rms, 0.0)
        self.assertEqual(stats.peak, 0.0)
        self.assertFalse(
            has_enough_audio_energy(
                stats,
                rms_threshold=0.012,
                peak_threshold=0.035,
                min_active_ratio=0.08,
            )
        )

    def test_tone_passes_energy_gate(self) -> None:
        time = np.arange(16000, dtype=np.float32) / 16000.0
        audio = (0.08 * np.sin(2.0 * np.pi * 440.0 * time)).astype(np.float32)
        stats = analyze_audio(audio, 16000, frame_ms=30, active_rms_threshold=0.012)

        self.assertTrue(
            has_enough_audio_energy(
                stats,
                rms_threshold=0.012,
                peak_threshold=0.035,
                min_active_ratio=0.08,
            )
        )


if __name__ == "__main__":
    unittest.main()
