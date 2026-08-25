import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from live_translator.config import AudioSettings, TtsSettings
from live_translator.tts.speaker import TtsSpeaker


class TtsSpeakerTests(unittest.TestCase):
    def test_piper_length_scale_is_passed_explicitly(self) -> None:
        speaker = TtsSpeaker(
            TtsSettings(
                engine="piper",
                model_path="voice.onnx",
                length_scale=1.0,
            ),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run,
            patch(
                "live_translator.tts.speaker.read_wav_mono",
                return_value=(np.zeros(160, dtype=np.float32), 16000),
            ),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.speak("Hello")

        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["--length_scale", "1.0"])

    def test_warm_up_synthesizes_once_without_playing(self) -> None:
        """The point of warming up is to pay Piper's first-run cost at startup.
        Playing the warm-up audio would put a noise into the meeting instead."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run,
            patch("live_translator.tts.speaker.play_mono") as play,
        ):
            speaker.warm_up()

        self.assertEqual(run.call_count, 1)
        play.assert_not_called()

    def test_warm_up_is_skipped_when_piper_is_not_the_engine(self) -> None:
        speaker = TtsSpeaker(TtsSettings(engine="none"), AudioSettings())

        with patch("live_translator.tts.speaker.subprocess.run") as run:
            speaker.warm_up()

        run.assert_not_called()

    def test_warm_up_failure_does_not_stop_startup(self) -> None:
        """A warm-up that cannot run means a slow first phrase, not a dead session."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1, "", "piper exploded"),
            ),
        ):
            speaker.warm_up()  # must not raise


if __name__ == "__main__":
    unittest.main()
