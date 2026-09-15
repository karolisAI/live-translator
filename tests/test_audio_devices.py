import unittest
from types import SimpleNamespace
from unittest.mock import patch

from live_translator.audio.devices import (
    AudioDevice,
    check_inbound_route,
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


def _default_sounddevice(input_index: int, output_index: int = -1) -> SimpleNamespace:
    return SimpleNamespace(default=SimpleNamespace(device=(input_index, output_index)))


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

    def test_auto_remote_input_selects_cable_b_recording_endpoint(self) -> None:
        output_devices = [
            _output_device(26, "CABLE-A Input (VB-Audio Virtual Cable A)"),
            _output_device(24, "CABLE-B Input (VB-Audio Virtual Cable B)"),
        ]
        input_devices = [
            _input_device(33, "CABLE-A Output (VB-Audio Virtual Cable A)"),
            _input_device(5, "CABLE-B Output (VB-Audio Virtual Cable B)", "MME"),
            _input_device(31, "CABLE-B Output (VB-Audio Virtual Cable B)"),
        ]

        inventory = _inventory(inputs=input_devices, outputs=output_devices)
        with patch("live_translator.audio.devices.list_devices", side_effect=inventory):
            remote = resolve_device_index("auto", "input", role="remote_input")
        with patch("live_translator.audio.devices.list_devices", side_effect=inventory):
            meeting = resolve_device_index("auto", "input", role="meeting_input")

        self.assertEqual(remote, 31)
        self.assertEqual(meeting, 33)

    def test_auto_remote_input_leaves_unlettered_cable_for_outbound(self) -> None:
        output_devices = [
            _output_device(7, "CABLE Input (VB-Audio Virtual Cable)"),
            _output_device(24, "CABLE-B Input (VB-Audio Virtual Cable B)"),
        ]
        input_devices = [
            _input_device(8, "CABLE Output (VB-Audio Virtual Cable)"),
            _input_device(31, "CABLE-B Output (VB-Audio Virtual Cable B)"),
        ]

        inventory = _inventory(inputs=input_devices, outputs=output_devices)
        with patch("live_translator.audio.devices.list_devices", side_effect=inventory):
            remote = resolve_device_index("auto", "input", role="remote_input")
        with patch("live_translator.audio.devices.list_devices", side_effect=inventory):
            translated = resolve_device_index("auto", "output", role="translated_output")

        self.assertEqual(remote, 31)
        self.assertEqual(translated, 7)

    def test_auto_remote_input_requires_a_second_cable(self) -> None:
        single_cable_inventories = {
            "unlettered only": (
                [_input_device(8, "CABLE Output (VB-Audio Virtual Cable)")],
                [_output_device(7, "CABLE Input (VB-Audio Virtual Cable)")],
            ),
            # With no other pair, the outbound direction already falls back to
            # CABLE-B, so the inbound direction must not share it.
            "cable B only": (
                [_input_device(31, "CABLE-B Output (VB-Audio Virtual Cable B)")],
                [_output_device(24, "CABLE-B Input (VB-Audio Virtual Cable B)")],
            ),
        }

        for label, (inputs, outputs) in single_cable_inventories.items():
            with (
                self.subTest(label),
                patch(
                    "live_translator.audio.devices.list_devices",
                    side_effect=_inventory(inputs=inputs, outputs=outputs),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "second virtual cable"):
                    resolve_device_index("auto", "input", role="remote_input")

    def test_unlettered_vb_audio_point_is_not_a_cable_endpoint(self) -> None:
        # VBMatrix names this endpoint without a trailing letter, so it has no
        # space after "Point"; it must still not complete the default cable pair.
        output_devices = [_output_device(7, "CABLE Input (VB-Audio Virtual Cable)")]
        input_devices = [_input_device(92, "CABLE Output (VB-Audio Point)", "Windows WDM-KS")]

        with patch(
            "live_translator.audio.devices.list_devices",
            side_effect=_inventory(inputs=input_devices, outputs=output_devices),
        ):
            with self.assertRaisesRegex(ValueError, "No complete standard VB-CABLE"):
                resolve_device_index("auto", "input", role="meeting_input")

    def test_auto_headset_output_maps_windows_default_to_its_wasapi_endpoint(self) -> None:
        devices = [
            _output_device(7, "CABLE Input (VB-Audio Virtual Cable)"),
            _output_device(3, "Headphones (Jabra Evolve2 65)", "MME"),
            _output_device(44, "Speakers (AMD Audio Device)"),
            _output_device(40, "Headphones (Jabra Evolve2 65)"),
        ]

        with (
            patch("live_translator.audio.devices.list_devices", return_value=devices),
            patch(
                "live_translator.audio.devices._sounddevice",
                return_value=_default_sounddevice(-1, output_index=3),
            ),
        ):
            selected = resolve_device_index("auto", "output", role="headset_output")

        self.assertEqual(selected, 40)

    def test_auto_headset_output_rejects_a_virtual_default_output(self) -> None:
        virtual_defaults = {
            "vb-cable": _output_device(7, "CABLE Input (VB-Audio Virtual Cable)"),
            "vbmatrix point": _output_device(8, "Input (VBMatrix Point 2)"),
        }

        for label, virtual in virtual_defaults.items():
            devices = [virtual, _output_device(40, "Headphones (Jabra Evolve2 65)")]
            with (
                self.subTest(label),
                patch("live_translator.audio.devices.list_devices", return_value=devices),
                patch(
                    "live_translator.audio.devices._sounddevice",
                    return_value=_default_sounddevice(-1, output_index=virtual.index),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "default output .* is virtual"):
                    resolve_device_index("auto", "output", role="headset_output")

    def test_auto_headset_output_requires_a_default_output(self) -> None:
        devices = [_output_device(40, "Headphones (Jabra Evolve2 65)")]

        with (
            patch("live_translator.audio.devices.list_devices", return_value=devices),
            patch(
                "live_translator.audio.devices._sounddevice",
                return_value=_default_sounddevice(-1, output_index=-1),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "no default output device"):
                resolve_device_index("auto", "output", role="headset_output")

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


class InboundRouteGuardTests(unittest.TestCase):
    OUTPUTS = [
        _output_device(26, "CABLE-A Input (VB-Audio Virtual Cable A)"),
        _output_device(9, "CABLE-A Input (VB-Audio Virtual Cable A)", "MME"),
        _output_device(24, "CABLE-B Input (VB-Audio Virtual Cable B)"),
        _output_device(40, "Headphones (Jabra Evolve2 65)"),
        _output_device(3, "Headphones (Jabra Evolve2 65)", "MME"),
    ]
    INPUTS = [
        _input_device(33, "CABLE-A Output (VB-Audio Virtual Cable A)"),
        _input_device(31, "CABLE-B Output (VB-Audio Virtual Cable B)"),
        _input_device(30, "Microphone (Jabra Evolve2 65)"),
    ]

    def _check(self, *, outbound_output: str | None, inbound_input: str | None, inbound_output: str | None) -> None:
        with patch(
            "live_translator.audio.devices.list_devices",
            side_effect=_inventory(inputs=self.INPUTS, outputs=self.OUTPUTS),
        ):
            check_inbound_route(
                outbound_output=outbound_output,
                inbound_input=inbound_input,
                inbound_output=inbound_output,
            )

    def test_second_cable_in_and_headset_out_is_accepted(self) -> None:
        self._check(
            outbound_output="CABLE-A Input (VB-Audio Virtual Cable A)",
            inbound_input="CABLE-B Output (VB-Audio Virtual Cable B)",
            inbound_output="Headphones (Jabra Evolve2 65)",
        )

    def test_inbound_output_into_any_virtual_cable_is_refused(self) -> None:
        for virtual_output in (
            "CABLE-A Input (VB-Audio Virtual Cable A)",
            # Same cable, listed under another host API with a different index.
            "9",
            "CABLE-B Input (VB-Audio Virtual Cable B)",
        ):
            with self.subTest(virtual_output):
                with self.assertRaisesRegex(ValueError, "is a virtual device"):
                    self._check(
                        outbound_output="CABLE-A Input (VB-Audio Virtual Cable A)",
                        inbound_input="CABLE-B Output (VB-Audio Virtual Cable B)",
                        inbound_output=virtual_output,
                    )

    def test_inbound_output_matching_the_outbound_output_is_refused(self) -> None:
        # Without a cable, e.g. while testing, both directions could name the same
        # real device; the MME entry "3" is the same endpoint as WASAPI "40".
        with self.assertRaisesRegex(ValueError, "also the outbound direction's output"):
            self._check(
                outbound_output="Headphones (Jabra Evolve2 65)",
                inbound_input="CABLE-B Output (VB-Audio Virtual Cable B)",
                inbound_output="3",
            )

    def test_inbound_input_from_a_microphone_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a virtual cable"):
            self._check(
                outbound_output="CABLE-A Input (VB-Audio Virtual Cable A)",
                inbound_input="Microphone (Jabra Evolve2 65)",
                inbound_output="Headphones (Jabra Evolve2 65)",
            )

    def test_inbound_input_from_the_outbound_cable_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "records the outbound direction's cable"):
            self._check(
                outbound_output="CABLE-A Input (VB-Audio Virtual Cable A)",
                inbound_input="CABLE-A Output (VB-Audio Virtual Cable A)",
                inbound_output="Headphones (Jabra Evolve2 65)",
            )

    def test_unset_inbound_devices_are_refused(self) -> None:
        for inbound_input, inbound_output in (
            (None, "Headphones (Jabra Evolve2 65)"),
            ("CABLE-B Output (VB-Audio Virtual Cable B)", None),
        ):
            with self.subTest(inbound_input=inbound_input, inbound_output=inbound_output):
                with self.assertRaisesRegex(ValueError, "needs an explicit"):
                    self._check(
                        outbound_output="CABLE-A Input (VB-Audio Virtual Cable A)",
                        inbound_input=inbound_input,
                        inbound_output=inbound_output,
                    )


if __name__ == "__main__":
    unittest.main()
