"""VAD segmentation on audio captured through the second virtual cable (US-1.2).

The inbound direction captures the remote party from CABLE-B rather than a
microphone, so its phrase boundaries were checked on real cable-captured audio
instead of being assumed to match.

The sample is three German sentences in the app's own Piper voice
(de_DE-thorsten-medium, trained on the CC0 Thorsten-Voice dataset), laid out with
a 1.0 s lead-in, 1.5 s gaps and a 1.0 s tail, played into CABLE-B Input, recorded
from CABLE-B Output at 48 kHz mono, aligned, and stored at 16 kHz. Each sentence's
true start and end is its first and last sample above 0.005 amplitude, taken from
the layout before it went through the cable, so the expectations below do not come
from the detector under test.

Measured 2026-09-15 with the settings `setup` writes: every boundary landed within
10 ms of the expected position, identical to the same layout fed in without the
cable, at 48 kHz and at 16 kHz. No retuning was needed. A longer 23-utterance
broadcast clip, not committed, gave the same result: identical boundaries through
the cable and directly. The tolerance here is one 30 ms frame.
"""

import unittest
import wave
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from live_translator.audio.rolling import RollingSpeechChunker
from live_translator.config import AudioSettings, ChunkingSettings, load_config
from live_translator.profiles import write_meeting_profile


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "vad_cable_b_de.wav"
TRUE_BOUNDARIES_SECONDS = (
    (1.000, 2.039),
    (3.539, 5.286),
    (6.786, 8.126),
)
TOLERANCE_SECONDS = 0.030


class FakeSoundDevice:
    pass


def _read_fixture() -> tuple[np.ndarray, int]:
    with wave.open(str(FIXTURE), "rb") as clip:
        rate = clip.getframerate()
        raw = clip.readframes(clip.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, rate


def _generated_profile_chunking() -> ChunkingSettings:
    """The chunking settings a de-en profile from `setup` actually carries."""
    with TemporaryDirectory() as temp_dir:
        profile = write_meeting_profile(
            path=Path(temp_dir) / "de-en.yaml",
            direction="de-en",
            microphone_device="auto",
            translated_output_device="auto",
            meeting_microphone_device="auto",
        )
        return load_config(profile).chunking


def _phrase_boundaries(samples: np.ndarray, rate: int, chunking: ChunkingSettings) -> list[tuple[float, float]]:
    """(start, commit) in seconds for each phrase the chunker emits, fed frame by frame."""
    with (
        patch("live_translator.audio.rolling._audio_packages", return_value=(FakeSoundDevice(), np)),
        patch("live_translator.audio.rolling.resolve_device_index", return_value=None),
        patch("live_translator.audio.rolling._select_sample_rate", return_value=rate),
    ):
        chunker = RollingSpeechChunker(
            AudioSettings(sample_rate=rate),
            chunking,
            emit_while_speaking=False,
            verbose=False,
        )
    frame = chunker._frame_samples
    boundaries = []
    for index in range(len(samples) // frame):
        emitted = chunker._process_block(samples[index * frame : (index + 1) * frame])
        if emitted is None:
            continue
        commit_frame = index + 1
        start_frame = commit_frame - len(emitted) // frame
        boundaries.append((start_frame * frame / rate, commit_frame * frame / rate))
    return boundaries


class CableCapturedVadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chunking = _generated_profile_chunking()
        samples, cls.rate = _read_fixture()
        cls.duration = len(samples) / cls.rate
        cls.phrases = _phrase_boundaries(samples, cls.rate, cls.chunking)
        frame_seconds = cls.chunking.frame_ms / 1000.0
        cls.pre_roll_seconds = ceil(cls.chunking.pre_roll_ms / cls.chunking.frame_ms) * frame_seconds
        cls.silence_seconds = ceil(cls.chunking.silence_ms / cls.chunking.frame_ms) * frame_seconds

    def test_settings_under_test_are_the_ones_measured(self) -> None:
        # The expectations below were measured for these values; a retune must
        # re-measure and update this test rather than silently loosening it.
        self.assertEqual(
            (self.chunking.mode, self.chunking.frame_ms, self.chunking.pre_roll_ms, self.chunking.silence_ms),
            ("vad", 30, 200, 450),
        )

    def test_sample_is_the_recording_the_boundaries_describe(self) -> None:
        self.assertEqual(self.rate, 16000)
        self.assertAlmostEqual(self.duration, 9.13, delta=0.05)

    def test_each_sentence_becomes_exactly_one_phrase(self) -> None:
        self.assertEqual(len(self.phrases), len(TRUE_BOUNDARIES_SECONDS), self.phrases)

    def test_phrases_start_one_pre_roll_before_speech(self) -> None:
        for (start, _), (true_start, _) in zip(self.phrases, TRUE_BOUNDARIES_SECONDS):
            with self.subTest(true_start=true_start):
                self.assertAlmostEqual(start, true_start - self.pre_roll_seconds, delta=TOLERANCE_SECONDS)

    def test_phrases_commit_one_silence_window_after_speech(self) -> None:
        for (_, commit), (_, true_end) in zip(self.phrases, TRUE_BOUNDARIES_SECONDS):
            with self.subTest(true_end=true_end):
                self.assertAlmostEqual(commit, true_end + self.silence_seconds, delta=TOLERANCE_SECONDS)


if __name__ == "__main__":
    unittest.main()
