import unittest

from live_translator.cli import build_parser


class CliTests(unittest.TestCase):
    def test_say_config_does_not_force_tts_engine(self) -> None:
        args = build_parser().parse_args(
            ["say", "--config", "app.meeting-en-de.yaml", "--text", "test"]
        )

        self.assertIsNone(args.tts_engine)

    def test_setup_accepts_de_en_direction(self) -> None:
        args = build_parser().parse_args(
            [
                "setup",
                "--direction",
                "de-en",
                "--input-device",
                "Mic",
                "--translated-output-device",
                "Cable Input",
                "--meeting-microphone-device",
                "Cable Output",
            ]
        )

        self.assertEqual(args.direction, "de-en")

    def test_meeting_accepts_vad_chunker(self) -> None:
        args = build_parser().parse_args(
            [
                "meeting",
                "--profile",
                "en-de",
                "--chunker",
                "vad",
                "--no-speech-threshold",
                "0.88",
                "--log-prob-threshold",
                "-1.7",
                "--input-gain",
                "1.8",
                "--debug-audio-dir",
                "debug-audio",
                "--silence-ms",
                "450",
                "--peak-threshold",
                "0.04",
                "--min-active-ratio",
                "0.12",
                "--min-segment-seconds",
                "1.4",
            ]
        )

        self.assertEqual(args.chunker, "vad")
        self.assertEqual(args.no_speech_threshold, 0.88)
        self.assertEqual(args.log_prob_threshold, -1.7)
        self.assertEqual(args.input_gain, 1.8)
        self.assertEqual(args.debug_audio_dir, "debug-audio")
        self.assertEqual(args.silence_ms, 450)
        self.assertEqual(args.peak_threshold, 0.04)
        self.assertEqual(args.min_active_ratio, 0.12)
        self.assertEqual(args.min_segment_seconds, 1.4)

    def test_meeting_accepts_rolling_chunker(self) -> None:
        args = build_parser().parse_args(
            [
                "meeting",
                "--profile",
                "en-de",
                "--chunker",
                "rolling",
            ]
        )

        self.assertEqual(args.chunker, "rolling")


if __name__ == "__main__":
    unittest.main()
