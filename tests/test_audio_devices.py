import unittest
from types import SimpleNamespace
from unittest.mock import patch

from live_translator.audio.devices import (
    AudioDevice,
    resolve_device_index,
)


def _input_device(
    index: int,
    name: str,
    host_api: str = "Windows WASAPI",
) -> AudioDevice:
    return AudioDevice(
        index=index,
        name=name,
        max_input_channels=2,
        max_output_channels=0,
        default_sample_rate=48000.0,
        host_api=host_api,
    )


def _output_device(
    index: int,
    name: str,
    host_api: str = "Windows WASAPI",
) -> AudioDevice:
    return AudioDevice(
        index=index,
        name=name,
        max_input_channels=0,
        max_output_channels=2,
        default_sample_rate=48000.0,
        host_api=host_api,
    )


def _default_sounddevice(input_index: int) -> SimpleNamespace:
    return SimpleNamespace(default=SimpleNamespace(device=(input_index, -1)))


def _inventory(
    *,
    inputs: list[AudioDevice],
    outputs: list[AudioDevice],
):
    def list_for_kind(kind: str | None = None) -> list[AudioDevice]:
        if kind == "input":
            return inputs
        if kind == "output":
            return outputs
        return [*inputs, *outputs]

    return list_for_kind


class AudioDeviceSelectionTests(unittest.TestCase):
    def test_none_keeps_portaudio_default_device_semantics(self) -> None:
        with patch("live_translator.audio.devices.list_devices") as list_devices:
            selected = resolve_device_index(None, "input", role="physical_input")

        self.assertIsNone(selected)
        list_devices.assert_not_called()

    def test_explicit_numeric_index_remains_supported(self) -> None:
        devices = [_input_device(47, "Microphone (USB Headset)")]

        with patch("live_translator.audio.devices.list_devices", return_value=devices):
            selected = resolve_device_index("47", "input", role="physical_input")

        self.assertEqual(selected, 47)

    def test_explicit_duplicate_friendly_name_prefers_wasapi(self) -> None:
        devices = [
            _input_device(1, "Microphone (USB Headset)", "MME"),
            _input_device(13, "Microphone (USB Headset)", "Windows DirectSound"),
            _input_device(30, "Microphone (USB Headset)", "Windows WASAPI"),
        ]

        with patch("live_translator.audio.devices.list_devices", return_value=devices):
            selected = resolve_device_index("Microphone (USB Headset)", "input")

        self.assertEqual(selected, 30)

    def test_auto_physical_input_maps_windows_default_to_its_wasapi_endpoint(self) -> None:
        devices = [
            _input_device(4, "CABLE-A Output (VB-Audio Virtual Cable A)"),
            _input_device(1, "Microphone (USB Headset)", "MME"),
            _input_device(32, "Microphone Array (AMD Audio Device)", "Windows WASAPI"),
            _input_device(30, "Microphone (USB Headset)", "Windows WASAPI"),
        ]

        with (
            patch("live_translator.audio.devices.list_devices", return_value=devices),
            patch(
                "live_translator.audio.devices._sounddevice",
                return_value=_default_sounddevice(1),
            ),
        ):
            selected = resolve_device_index("auto", "input", role="physical_input")

        self.assertEqual(selected, 30)

    def test_auto_physical_input_tracks_reordered_indices(self) -> None:
        inventories = (
            (
                [_input_device(26, "Microphone Array (AMD Audio Device)")],
                26,
                26,
            ),
            (
                [
                    _input_device(26, "CABLE-A Output (VB-Audio Virtual Cable A)"),
                    _input_device(3, "Microphone Array (AMD Audio Device)", "MME"),
                    _input_device(41, "Microphone Array (AMD Audio Device)"),
                ],
                3,
                41,
            ),
        )

        for devices, default_index, expected in inventories:
            with (
                self.subTest(expected=expected),
                patch("live_translator.audio.devices.list_devices", return_value=devices),
                patch(
                    "live_translator.audio.devices._sounddevice",
                    return_value=_default_sounddevice(default_index),
                ),
            ):
                selected = resolve_device_index("auto", "input", role="physical_input")
                self.assertEqual(selected, expected)

    def test_auto_physical_input_matches_truncated_default_name_to_wasapi(self) -> None:
        devices = [
            _input_device(3, "Microphone Array (AMD Audio Dev", "MME"),
            _input_device(32, "Microphone Array (AMD Audio Device)", "Windows WASAPI"),
        ]

        with (
            patch("live_translator.audio.devices.list_devices", return_value=devices),
            patch(
                "live_translator.audio.devices._sounddevice",
                return_value=_default_sounddevice(3),
            ),
        ):
            selected = resolve_device_index("auto", "input", role="physical_input")

        self.assertEqual(selected, 32)

    def test_auto_translated_output_prefers_standard_cable_a_wasapi_endpoint(self) -> None:
        devices = [
            _output_device(9, "CABLE-A Input (VB-Audio Virtual Cable A)", "MME"),
            _output_device(21, "CABLE-A Input (VB-Audio Virtual Cable A)", "Windows DirectSound"),
            _output_device(24, "CABLE-B Input (VB-Audio Virtual Cable B)"),
            _output_device(26, "CABLE-A Input (VB-Audio Virtual Cable A)"),
            _output_device(28, "CABLE-A In 16ch (VB-Audio Virtual Cable A)"),
            _output_device(35, "Output (VB-Audio Point A)", "Windows WDM-KS"),
        ]
        inputs = [_input_device(33, "CABLE-A Output (VB-Audio Virtual Cable A)")]

        with patch(
            "live_translator.audio.devices.list_devices",
            side_effect=_inventory(inputs=inputs, outputs=devices),
        ):
            selected = resolve_device_index("auto", "output", role="translated_output")

        self.assertEqual(selected, 26)

    def test_auto_meeting_input_prefers_standard_cable_a_wasapi_endpoint(self) -> None:
        devices = [
            _input_device(4, "CABLE-A Output (VB-Audio Virtual Cable A)", "MME"),
            _input_device(16, "CABLE-A Output (VB-Audio Virtual Cable A)", "Windows DirectSound"),
            _input_device(31, "CABLE-B Output (VB-Audio Virtual Cable B)"),
            _input_device(33, "CABLE-A Output (VB-Audio Virtual Cable A)"),
            _input_device(34, "CABLE-A Output (VB-Audio Point A)", "Windows WDM-KS"),
        ]
        outputs = [_output_device(26, "CABLE-A Input (VB-Audio Virtual Cable A)")]

        with patch(
            "live_translator.audio.devices.list_devices",
            side_effect=_inventory(inputs=devices, outputs=outputs),
        ):
            selected = resolve_device_index("auto", "input", role="meeting_input")

        self.assertEqual(selected, 33)

    def test_auto_virtual_roles_support_unlettered_vb_cable(self) -> None:
        output_devices = [_output_device(7, "CABLE Input (VB-Audio Virtual Cable)")]
        input_devices = [_input_device(8, "CABLE Output (VB-Audio Virtual Cable)")]

        inventory = _inventory(inputs=input_devices, outputs=output_devices)
        with patch("live_translator.audio.devices.list_devices", side_effect=inventory):
            translated = resolve_device_index("auto", "output", role="translated_output")
        with patch("live_translator.audio.devices.list_devices", side_effect=inventory):
            meeting = resolve_device_index("auto", "input", role="meeting_input")

        self.assertEqual(translated, 7)
        self.assertEqual(meeting, 8)

    def test_auto_input_without_role_defaults_to_physical_input(self) -> None:
        devices = [_input_device(30, "Microphone (USB Headset)")]

        with (
            patch("live_translator.audio.devices.list_devices", return_value=devices),
            patch(
                "live_translator.audio.devices._sounddevice",
                return_value=_default_sounddevice(30),
            ),
        ):
            selected = resolve_device_index("auto", "input")

        self.assertEqual(selected, 30)

    def test_auto_rejects_role_with_wrong_device_kind(self) -> None:
        with patch("live_translator.audio.devices.list_devices", return_value=[]):
            with self.assertRaisesRegex(ValueError, "cannot be used for a output device"):
                resolve_device_index("auto", "output", role="physical_input")

    def test_auto_virtual_role_reports_missing_vb_cable(self) -> None:
        devices = [_output_device(25, "Speakers (USB Headset)")]

        with patch("live_translator.audio.devices.list_devices", return_value=devices):
            with self.assertRaisesRegex(ValueError, "(?i)(VB-CABLE|virtual cable|CABLE)"):
                resolve_device_index("auto", "output", role="translated_output")

    def test_ambiguous_explicit_partial_name_lists_matching_devices(self) -> None:
        devices = [
            _input_device(30, "Microphone (USB Headset)"),
            _input_device(32, "Microphone Array (AMD Audio Device)"),
        ]

        with patch("live_translator.audio.devices.list_devices", return_value=devices):
            with self.assertRaisesRegex(ValueError, "Multiple input devices matched 'Microphone'") as error:
                resolve_device_index("Microphone", "input")

        self.assertIn("[30] Microphone (USB Headset)", str(error.exception))
        self.assertIn("[32] Microphone Array (AMD Audio Device)", str(error.exception))


if __name__ == "__main__":
    unittest.main()
