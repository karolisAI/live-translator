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


if __name__ == "__main__":
    unittest.main()
