from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from live_translator.errors import MissingDependency


DeviceKind = Literal["input", "output"]
DeviceRole = Literal["physical_input", "translated_output", "meeting_input"]


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    host_api: str


def list_devices(kind: DeviceKind | None = None) -> list[AudioDevice]:
    sd = _sounddevice()
    devices = []
    for index, raw in enumerate(sd.query_devices()):
        host_api_index = int(raw["hostapi"])
        host_api = str(sd.query_hostapis(host_api_index)["name"])
        device = AudioDevice(
            index=index,
            name=str(raw["name"]),
            max_input_channels=int(raw["max_input_channels"]),
            max_output_channels=int(raw["max_output_channels"]),
            default_sample_rate=float(raw["default_samplerate"]),
            host_api=host_api,
        )
        if kind == "input" and device.max_input_channels <= 0:
            continue
        if kind == "output" and device.max_output_channels <= 0:
            continue
        devices.append(device)
    return devices


def resolve_device_index(
    name: str | None,
    kind: DeviceKind,
    *,
    role: DeviceRole | None = None,
) -> int | None:
    if not name:
        return None

    candidates = list_devices(kind)
    if name.strip().lower() == "auto":
        inferred_role = role or ("translated_output" if kind == "output" else "physical_input")
        return _resolve_automatic_device(candidates, kind, inferred_role)

    if name.isdigit():
        requested_index = int(name)
        for device in candidates:
            if device.index == requested_index:
                return requested_index
        raise ValueError(f"Device index {requested_index} is not a valid {kind} device. Run list-{kind}-devices.")

    exact = [device for device in candidates if device.name.lower() == name.lower()]
    if exact:
        return _preferred_device(exact).index

    partial = [device for device in candidates if name.lower() in device.name.lower()]
    if len(partial) == 1:
        return partial[0].index
    if partial and len({device.name.lower() for device in partial}) == 1:
        return _preferred_device(partial).index

    alternate = _swap_virtual_cable_direction(name, kind)
    if alternate:
        alternate_exact = [device for device in candidates if device.name.lower() == alternate.lower()]
        if alternate_exact:
            selected = _preferred_device(alternate_exact)
            print(f"Info: mapped {kind} device '{name}' to '{selected.name}'.")
            return selected.index
        alternate_partial = [device for device in candidates if alternate.lower() in device.name.lower()]
        if len(alternate_partial) == 1:
            print(f"Info: mapped {kind} device '{name}' to '{alternate_partial[0].name}'.")
            return alternate_partial[0].index
        if alternate_partial and len({device.name.lower() for device in alternate_partial}) == 1:
            selected = _preferred_device(alternate_partial)
            print(f"Info: mapped {kind} device '{name}' to '{selected.name}'.")
            return selected.index

    if len(partial) > 1:
        matches = "\n".join(f"  [{device.index}] {device.name}" for device in partial)
        raise ValueError(f"Multiple {kind} devices matched '{name}'. Use the full name:\n{matches}")

    hint = f" Did you mean '{alternate}'?" if alternate else ""
    raise ValueError(f"No {kind} device matched '{name}'.{hint} Run list-{kind}-devices.")


def describe_device_selection(
    name: str | None,
    kind: DeviceKind,
    *,
    role: DeviceRole | None = None,
) -> str:
    index = resolve_device_index(name, kind, role=role)
    return describe_device_index(index, kind)


def describe_device_index(index: int | None, kind: DeviceKind) -> str:
    if index is None:
        return "Windows default"
    device = next(device for device in list_devices(kind) if device.index == index)
    return f"{device.name} [{device.host_api}] (index={device.index})"


def _resolve_automatic_device(
    candidates: list[AudioDevice],
    kind: DeviceKind,
    role: DeviceRole,
) -> int:
    expected_kind: dict[DeviceRole, DeviceKind] = {
        "physical_input": "input",
        "translated_output": "output",
        "meeting_input": "input",
    }
    if expected_kind[role] != kind:
        raise ValueError(f"Automatic device role '{role}' cannot be used for a {kind} device.")

    if role == "physical_input":
        return _resolve_default_microphone(candidates)

    output_device, input_device = _resolve_virtual_cable_pair()
    return output_device.index if role == "translated_output" else input_device.index


def _resolve_default_microphone(candidates: list[AudioDevice]) -> int:
    sd = _sounddevice()
    default = sd.default.device
    try:
        default_index = default[0]
    except (TypeError, IndexError):
        default_index = default
    try:
        default_index = int(default_index)
    except (TypeError, ValueError):
        default_index = -1

    selected = next((device for device in candidates if device.index == default_index), None)
    if selected is None:
        raise ValueError(
            "Windows has no default input device. Set a default microphone in Sound settings "
            "or provide an explicit audio.input_device."
        )
    if _is_virtual_audio_device(selected.name):
        raise ValueError(
            f"Windows default input '{selected.name}' is virtual. Set the physical microphone "
            "as the Windows default input or provide an explicit audio.input_device."
        )

    same_endpoint = [
        device
        for device in candidates
        if _same_friendly_endpoint(device.name, selected.name)
        and not _is_virtual_audio_device(device.name)
    ]
    return _preferred_device(same_endpoint or [selected]).index


def _resolve_virtual_cable_pair() -> tuple[AudioDevice, AudioDevice]:
    outputs = _standard_cable_devices(list_devices("output"), "output")
    inputs = _standard_cable_devices(list_devices("input"), "input")

    for identity in ("a", "default", "b"):
        matching_outputs = [device for device, cable in outputs if cable == identity]
        matching_inputs = [device for device, cable in inputs if cable == identity]
        if matching_outputs and matching_inputs:
            return _preferred_device(matching_outputs), _preferred_device(matching_inputs)

    available_outputs = ", ".join(sorted({cable for _, cable in outputs})) or "none"
    available_inputs = ", ".join(sorted({cable for _, cable in inputs})) or "none"
    raise ValueError(
        "No complete standard VB-CABLE playback/recording pair was found "
        f"(playback identities: {available_outputs}; recording identities: {available_inputs}). "
        "Install or enable both CABLE Input and its matching CABLE Output."
    )


def _standard_cable_devices(
    devices: list[AudioDevice],
    kind: DeviceKind,
) -> list[tuple[AudioDevice, str]]:
    expected_endpoint = "input" if kind == "output" else "output"
    matches: list[tuple[AudioDevice, str]] = []
    pattern = re.compile(r"^CABLE(?:-([AB]))?\s+(INPUT|OUTPUT)\b", re.IGNORECASE)
    for device in devices:
        upper = device.name.upper()
        if "16CH" in upper or "POINT " in upper:
            continue
        match = pattern.match(device.name)
        if not match or match.group(2).lower() != expected_endpoint:
            continue
        identity = (match.group(1) or "default").lower()
        matches.append((device, identity))
    return matches


def _preferred_device(devices: list[AudioDevice]) -> AudioDevice:
    if not devices:
        raise ValueError("No matching audio device was found.")
    return min(devices, key=_device_sort_key)


def _device_sort_key(device: AudioDevice) -> tuple[int, int, int, int]:
    host_priority = {
        "windows wasapi": 0,
        "windows directsound": 1,
        "mme": 2,
        "windows wdm-ks": 3,
    }
    return (
        host_priority.get(device.host_api.lower(), 4),
        0 if int(device.default_sample_rate) == 48000 else 1,
        0 if max(device.max_input_channels, device.max_output_channels) <= 2 else 1,
        device.index,
    )


def _is_virtual_audio_device(name: str) -> bool:
    upper = name.upper()
    return (
        "VB-AUDIO" in upper
        or "VIRTUAL CABLE" in upper
        or upper.startswith("CABLE-")
        or upper.startswith("CABLE ")
    )


def _same_friendly_endpoint(left: str, right: str) -> bool:
    left_normalized = left.strip().lower()
    right_normalized = right.strip().lower()
    if left_normalized == right_normalized:
        return True
    shorter, longer = sorted((left_normalized, right_normalized), key=len)
    return len(shorter) >= 20 and longer.startswith(shorter)


def print_devices(kind: DeviceKind) -> None:
    devices = list_devices(kind)
    if not devices:
        print(f"No {kind} devices found.")
        return

    for device in devices:
        channels = device.max_input_channels if kind == "input" else device.max_output_channels
        print(f"[{device.index}] {device.name}")
        print(
            f"    api={device.host_api} channels={channels} "
            f"default_sample_rate={device.default_sample_rate:.0f}"
        )


def probe_devices(kind: DeviceKind) -> None:
    sd = _sounddevice()
    devices = list_devices(kind)
    if not devices:
        print(f"No {kind} devices found.")
        return

    for device in devices:
        ok, detail = _try_open_device(sd, device, kind)
        status = "OPEN OK " if ok else "OPEN BAD"
        print(f"{status} [{device.index}] {device.name} [{device.host_api}]")
        print(f"    {detail}")


def _swap_virtual_cable_direction(name: str, kind: DeviceKind) -> str | None:
    upper = name.upper()
    if "CABLE" not in upper and "VB-AUDIO" not in upper and "VIRTUAL CABLE" not in upper:
        return None
    if kind == "output" and " OUTPUT" in upper:
        return _replace_case_insensitive(name, " Output", " Input")
    if kind == "input" and " INPUT" in upper:
        return _replace_case_insensitive(name, " Input", " Output")
    return None


def _replace_case_insensitive(text: str, old: str, new: str) -> str:
    index = text.lower().find(old.lower())
    if index < 0:
        return text
    return text[:index] + new + text[index + len(old):]


def _sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise MissingDependency(
            "Missing dependency 'sounddevice'. Install dependencies with: python -m pip install -e ."
        ) from exc
    return sd


def _try_open_device(sd, device: AudioDevice, kind: DeviceKind) -> tuple[bool, str]:
    try:
        import numpy as np
    except ImportError as exc:
        raise MissingDependency(
            "Missing dependency 'numpy'. Install dependencies with: python -m pip install -e ."
        ) from exc

    rates = list(dict.fromkeys([int(device.default_sample_rate), 16000, 48000, 44100]))
    last_error = ""
    for rate in rates:
        try:
            if kind == "input":
                sd.rec(int(rate * 0.05), samplerate=rate, channels=1, dtype="float32", device=device.index)
                sd.wait()
            else:
                silence = np.zeros(int(rate * 0.05), dtype="float32")
                sd.play(silence, samplerate=rate, device=device.index)
                sd.wait()
            return True, f"sample_rate={rate}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return False, last_error
