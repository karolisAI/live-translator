from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from live_translator.errors import MissingDependency


DeviceKind = Literal["input", "output"]


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float


def list_devices(kind: DeviceKind | None = None) -> list[AudioDevice]:
    sd = _sounddevice()
    devices = []
    for index, raw in enumerate(sd.query_devices()):
        device = AudioDevice(
            index=index,
            name=str(raw["name"]),
            max_input_channels=int(raw["max_input_channels"]),
            max_output_channels=int(raw["max_output_channels"]),
            default_sample_rate=float(raw["default_samplerate"]),
        )
        if kind == "input" and device.max_input_channels <= 0:
            continue
        if kind == "output" and device.max_output_channels <= 0:
            continue
        devices.append(device)
    return devices


def resolve_device_index(name: str | None, kind: DeviceKind) -> int | None:
    if not name:
        return None

    candidates = list_devices(kind)
    if name.isdigit():
        requested_index = int(name)
        for device in candidates:
            if device.index == requested_index:
                return requested_index
        raise ValueError(f"Device index {requested_index} is not a valid {kind} device. Run list-{kind}-devices.")

    exact = [device for device in candidates if device.name.lower() == name.lower()]
    if len(exact) == 1:
        return exact[0].index

    partial = [device for device in candidates if name.lower() in device.name.lower()]
    if len(partial) == 1:
        return partial[0].index

    alternate = _swap_virtual_cable_direction(name, kind)
    if alternate:
        alternate_exact = [device for device in candidates if device.name.lower() == alternate.lower()]
        if len(alternate_exact) == 1:
            print(f"Info: mapped {kind} device '{name}' to '{alternate_exact[0].name}'.")
            return alternate_exact[0].index
        alternate_partial = [device for device in candidates if alternate.lower() in device.name.lower()]
        if len(alternate_partial) == 1:
            print(f"Info: mapped {kind} device '{name}' to '{alternate_partial[0].name}'.")
            return alternate_partial[0].index

    if len(partial) > 1:
        matches = "\n".join(f"  [{device.index}] {device.name}" for device in partial)
        raise ValueError(f"Multiple {kind} devices matched '{name}'. Use the full name:\n{matches}")

    hint = f" Did you mean '{alternate}'?" if alternate else ""
    raise ValueError(f"No {kind} device matched '{name}'.{hint} Run list-{kind}-devices.")


def print_devices(kind: DeviceKind) -> None:
    devices = list_devices(kind)
    if not devices:
        print(f"No {kind} devices found.")
        return

    for device in devices:
        channels = device.max_input_channels if kind == "input" else device.max_output_channels
        print(f"[{device.index}] {device.name}")
        print(f"    channels={channels} default_sample_rate={device.default_sample_rate:.0f}")


def probe_devices(kind: DeviceKind) -> None:
    sd = _sounddevice()
    devices = list_devices(kind)
    if not devices:
        print(f"No {kind} devices found.")
        return

    for device in devices:
        ok, detail = _try_open_device(sd, device, kind)
        status = "OPEN OK " if ok else "OPEN BAD"
        print(f"{status} [{device.index}] {device.name}")
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
