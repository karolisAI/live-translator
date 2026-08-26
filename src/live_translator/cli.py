from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Callable

from live_translator.asr import SUPPORTED_ASR_ENGINES, create_asr
from live_translator.asr.model_store import download_model, model_dir, verify_local_model
from live_translator.audio.route_test import test_output_to_input_route
from live_translator.audio.devices import (
    DeviceRole,
    describe_device_selection,
    print_devices,
    probe_devices,
    resolve_device_index,
)
from live_translator.audio.io import _audio_packages, _select_sample_rate
from live_translator.config import apply_cli_overrides, load_config
from live_translator.errors import MissingDependency, ModelNotPrepared
from live_translator.mt import TranslationEngine
from live_translator.mt.argos_packages import install_argos_package, print_installed_argos_packages
from live_translator.pipeline import LocalTranslatorPipeline
from live_translator.profiles import SUPPORTED_DIRECTIONS, prompt_for_device, write_meeting_profile
from live_translator.runtime import default_profile_path
from live_translator.tts import TtsSpeaker

TRANSLATION_ENGINES = ("identity", "argos")
TTS_ENGINES = ("none", "pyttsx3", "piper")
CHUNKER_MODES = ("fixed", "vad", "rolling")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return int(args.func(args) or 0)
    except (MissingDependency, FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live-translator",
        description="Offline phrase-level speech translation for Windows meetings.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="create a local meeting profile")
    setup.add_argument("--profile", default="default", help="profile name under %%LOCALAPPDATA%%/LiveTranslator/profiles")
    setup.add_argument("--config-out", default=None, help="explicit output config path")
    setup.add_argument("--direction", choices=SUPPORTED_DIRECTIONS, default="en-de")
    setup.add_argument("--input-device", default=None, help="physical microphone override; defaults to automatic selection")
    setup.add_argument("--translated-output-device", default=None, help="virtual playback override; defaults to automatic selection")
    setup.add_argument("--meeting-microphone-device", default=None, help="meeting microphone override; defaults to automatic selection")
    setup.add_argument(
        "--interactive-devices",
        action="store_true",
        help="select devices interactively instead of writing automatic selectors",
    )
    setup.add_argument("--seconds", type=float, default=4.0, help="fixed-mode fallback chunk duration")
    setup.set_defaults(func=cmd_setup)

    meeting = subparsers.add_parser("meeting", help="run a one-way meeting translation profile")
    meeting.add_argument("--profile", default="default", help="profile name to load")
    meeting.add_argument("--config", default=None, help="explicit profile/config path")
    meeting.add_argument("--seconds", type=float, default=None, help="override fixed-mode chunk duration")
    meeting.add_argument("--asr-engine", default=None, choices=SUPPORTED_ASR_ENGINES, help="override the ASR engine")
    meeting.add_argument("--model", default=None, help="ASR model name or local model path")
    meeting.add_argument("--input-gain", type=float, default=None, help="multiply microphone samples before ASR")
    meeting.add_argument("--debug-audio-dir", default=None, help="write each ASR input chunk as a WAV file")
    meeting.add_argument("--verbose", action="store_true", help="show audio gates and per-segment timings")
    add_chunker_options(meeting)
    meeting.set_defaults(func=cmd_meeting)

    route = subparsers.add_parser("route-test", help="test translated output reaching the meeting microphone endpoint")
    route.add_argument("--profile", default="default", help="profile name to load when --config is omitted")
    route.add_argument("--config", default=None, help="YAML config file")
    route.add_argument("--meeting-microphone-device", default=None, help="override audio.peer_input_device")
    route.add_argument("--seconds", type=float, default=1.0)
    route.set_defaults(func=cmd_route_test)

    doctor = subparsers.add_parser("doctor", help="check local dependencies")
    doctor.add_argument(
        "--profile",
        default=None,
        help="profile name to validate; omit to check dependencies only",
    )
    doctor.add_argument("--config", default=None, help="also validate config-specific settings")
    doctor.add_argument(
        "--prepare-models",
        action="store_true",
        help="also verify and load the profile's speech model from the local "
        "model directory, without downloading; translation and voice are "
        "checked by any profile validation",
    )
    doctor.set_defaults(func=cmd_doctor)

    prepare = subparsers.add_parser(
        "prepare-models",
        help="download the pinned speech model for offline use (needs internet)",
        description="The only command that downloads a speech model. Every "
        "other command, meeting mode included, reads what this leaves on disk "
        "and never contacts a model host.",
    )
    prepare.add_argument("--profile", default="default", help="profile name to read the model settings from")
    prepare.add_argument("--config", default=None, help="explicit profile/config path")
    prepare.set_defaults(func=cmd_prepare_models)

    list_inputs = subparsers.add_parser("list-input-devices", help="list capture devices")
    list_inputs.set_defaults(func=lambda _args: print_devices("input"))

    list_outputs = subparsers.add_parser("list-output-devices", help="list playback devices")
    list_outputs.set_defaults(func=lambda _args: print_devices("output"))

    probe_inputs = subparsers.add_parser("probe-input-devices", help="try opening each capture device")
    probe_inputs.set_defaults(func=lambda _args: probe_devices("input"))

    probe_outputs = subparsers.add_parser("probe-output-devices", help="try opening each playback device with silence")
    probe_outputs.set_defaults(func=lambda _args: probe_devices("output"))

    record = subparsers.add_parser("record-test", help="record a short microphone sample")
    add_common_options(record)
    record.add_argument("--out", default="record-test.wav", help="output WAV path")
    record.add_argument("--play", action="store_true", help="play the captured audio")
    record.set_defaults(func=cmd_record_test)

    say = subparsers.add_parser("say", help="speak text through a configured TTS backend")
    say.add_argument("--config", default=None, help="YAML config file")
    say.add_argument("--text", required=True, help="text to speak")
    say.add_argument("--output-device", default=None, help="output device full or partial friendly name")
    add_tts_options(say)
    say.set_defaults(func=cmd_say)

    translate_text = subparsers.add_parser("translate-text", help="translate typed text without microphone input")
    translate_text.add_argument("--config", default=None, help="YAML config file")
    translate_text.add_argument("--text", required=True, help="text to translate")
    add_language_options(translate_text)
    translate_text.add_argument("--translation-engine", choices=TRANSLATION_ENGINES, default="argos")
    translate_text.set_defaults(func=cmd_translate_text)

    if not getattr(sys, "frozen", False):
        argos_list = subparsers.add_parser("argos-list", help="list installed Argos language packages")
        argos_list.set_defaults(func=cmd_argos_list)

        argos_install = subparsers.add_parser("argos-install", help="download and install an Argos language package")
        argos_install.add_argument("--source-language", required=True, help="source language code")
        argos_install.add_argument("--target-language", required=True, help="target language code")
        argos_install.set_defaults(func=cmd_argos_install)

    transcribe = subparsers.add_parser("transcribe-once", help="record once and transcribe locally")
    add_common_options(transcribe)
    transcribe.set_defaults(func=cmd_transcribe_once)

    translate = subparsers.add_parser("translate-once", help="record once, translate, and optionally speak")
    add_common_options(translate)
    add_language_options(translate)
    translate.add_argument("--translation-engine", choices=TRANSLATION_ENGINES, default=None)
    add_tts_options(translate)
    translate.add_argument("--no-speak", action="store_true", help="print only; do not synthesize speech")
    translate.set_defaults(func=cmd_translate_once)

    loopback = subparsers.add_parser("loopback", help="continuous local translate loop")
    add_common_options(loopback)
    add_language_options(loopback)
    loopback.add_argument("--translation-engine", choices=TRANSLATION_ENGINES, default=None)
    add_tts_options(loopback)
    add_chunker_options(loopback)
    loopback.add_argument("--debug-audio-dir", default=None, help="write each ASR input chunk as a WAV file")
    loopback.add_argument("--verbose", action="store_true", help="show audio gates and per-segment timings")
    loopback.set_defaults(func=cmd_loopback)

    return parser


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, help="YAML config file")
    parser.add_argument("--seconds", type=float, default=None, help="recording/chunk seconds")
    parser.add_argument("--input-device", default=None, help="input device full or partial friendly name")
    parser.add_argument("--output-device", default=None, help="output device full or partial friendly name")
    parser.add_argument("--input-gain", type=float, default=None, help="multiply microphone samples before ASR")
    parser.add_argument("--asr-engine", default=None, choices=SUPPORTED_ASR_ENGINES, help="override the ASR engine")
    parser.add_argument("--model", default=None, help="ASR model name or local model path")


def add_language_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-language", default=None, help="source language code, or auto")
    parser.add_argument("--target-language", default=None, help="target language code")


def add_tts_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tts-engine", choices=TTS_ENGINES, default=None)
    parser.add_argument("--tts-voice", default=None, help="TTS voice name or partial voice identifier")
    parser.add_argument("--tts-model", default=None, help="Piper .onnx voice model path")
    parser.add_argument("--piper-exe", default=None, help="Piper executable path or command name")
    parser.add_argument(
        "--tts-length-scale",
        type=float,
        default=None,
        help="Piper duration scale; 1.0 uses a natural voice pace",
    )
    parser.add_argument(
        "--piper-timeout",
        type=float,
        default=None,
        help="seconds to wait for Piper before treating it as hung (default 30.0)",
    )


def add_chunker_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--chunker", choices=CHUNKER_MODES, default=None, help="fixed windows or VAD speech segments")
    parser.add_argument("--log-prob-threshold", type=float, default=None, help="average per-token log-probability below which a phrase is rejected")
    parser.add_argument("--flag-log-prob-threshold", type=float, default=None, help="average per-token log-probability below which an accepted phrase is flagged low_confidence instead of rejected; must be greater than --log-prob-threshold")
    parser.add_argument("--vad-threshold", type=float, default=None, help="RMS threshold for --chunker vad")
    parser.add_argument("--peak-threshold", type=float, default=None, help="minimum audio peak before ASR runs")
    parser.add_argument("--min-active-ratio", type=float, default=None, help="minimum ratio of active frames before ASR runs")
    parser.add_argument("--min-segment-seconds", type=float, default=None, help="minimum audio duration sent to ASR")
    parser.add_argument(
        "--rolling-window-seconds",
        type=float,
        default=None,
        help="window duration for experimental rolling mode",
    )
    parser.add_argument("--silence-ms", type=int, default=None, help="trailing silence before a VAD segment commits")
    parser.add_argument("--max-seconds", type=float, default=None, help="maximum VAD segment length")


def cmd_doctor(args: argparse.Namespace) -> int:
    config_path = _doctor_config_path(args)
    if args.prepare_models and config_path is None:
        raise ValueError(
            "--prepare-models needs a profile to know which model to check; "
            "pass --profile <name> or --config <path>."
        )

    checks = [
        ("numpy", "audio arrays", True),
        ("sounddevice", "audio capture/playback", True),
        ("onnx_asr", "local ASR", True),
        ("onnxruntime", "ASR runtime", True),
        ("ctranslate2", "bundled Argos model inference", True),
        ("sentencepiece", "bundled Argos tokenization", True),
        ("yaml", "YAML config", True),
    ]

    missing_required = False
    for module_name, purpose, required in checks:
        found = importlib.util.find_spec(module_name) is not None
        label = "OK" if found else "MISSING"
        required_text = "required" if required else "optional"
        print(f"{label:7} {module_name:16} {required_text:8} {purpose}")
        if required and not found:
            missing_required = True

    config_ok = True
    if config_path is not None:
        config_ok = _print_config_checks(
            load_config(config_path),
            prepare_models=args.prepare_models,
        )
    if missing_required:
        print("Install required packages with: python -m pip install -e .")
    if missing_required or not config_ok:
        return 1
    return 0


def _doctor_config_path(args: argparse.Namespace) -> Path | None:
    """Config to validate, or None when doctor should only check dependencies."""
    if args.config:
        return Path(args.config)
    if args.profile:
        return default_profile_path(args.profile)
    return None


def _print_config_checks(config, *, prepare_models: bool) -> bool:
    checks: list[tuple[str, Callable[[], str]]] = [
        (
            "audio.input",
            lambda: _audio_device_detail(
                config.audio.input_device,
                "input",
                config.audio.sample_rate,
                "physical_input",
            ),
        ),
    ]
    if config.tts.engine.lower() not in {"none", "off"} or config.audio.output_device:
        checks.append(
            (
                "audio.output",
                lambda: _audio_device_detail(
                    config.audio.output_device,
                    "output",
                    config.audio.sample_rate,
                    "translated_output",
                ),
            )
        )
    if config.audio.peer_input_device:
        checks.append(
            (
                "meeting.input",
                lambda: _audio_device_detail(
                    config.audio.peer_input_device,
                    "input",
                    config.audio.sample_rate,
                    "meeting_input",
                ),
            )
        )

    def prepare_translation() -> str:
        TranslationEngine(config.translation).prepare()
        return (
            f"{config.translation.engine} "
            f"{config.translation.source_language}->{config.translation.target_language}"
        )

    def validate_tts() -> str:
        TtsSpeaker(config.tts, config.audio).validate()
        return config.tts.engine

    checks.append(("translation", prepare_translation))
    checks.append(("speech.output", validate_tts))
    if prepare_models:
        checks.append(("speech.model", lambda: _prepare_asr_model(config)))

    print()
    print("Config checks:")
    passed = True
    for label, check in checks:
        try:
            detail = check()
            print(f"{'OK':7} {label:16} {detail}")
        except (MissingDependency, FileNotFoundError, ValueError, RuntimeError) as exc:
            passed = False
            print(f"{'FAIL':7} {label:16} {exc}")
    if not prepare_models:
        print(f"{'INFO':7} {'speech.model':16} run doctor with --prepare-models before a demo")
    return passed


def _audio_device_detail(
    device: str | None,
    kind: str,
    target_rate: int,
    role: DeviceRole,
) -> str:
    sd, _ = _audio_packages()
    index = resolve_device_index(device, kind, role=role)  # type: ignore[arg-type]
    channels = 2 if role == "translated_output" else 1
    rate = _select_sample_rate(
        sd,
        index,
        kind,
        target_rate,
        channels=channels,
        announce=False,
    )
    if index is None:
        return f"Windows default (index=default, {rate} Hz)"
    raw = sd.query_devices(index)
    host_api = sd.query_hostapis(int(raw["hostapi"]))["name"]
    return f"{raw['name']} [{host_api}] (index={index}, {rate} Hz)"


def _prepare_asr_model(config) -> str:
    """Load the prepared model from disk. Never downloads.

    `create_asr` verifies the local model directory before it loads, so a
    machine that was never prepared fails here with the `prepare-models`
    command in the message.
    """
    create_asr(config.asr)
    return f"{config.asr.model} loaded from {model_dir(config.asr)}"


def cmd_prepare_models(args: argparse.Namespace) -> int:
    if args.config is None:
        config_path = default_profile_path(args.profile)
        if not config_path.exists():
            raise FileNotFoundError(
                f"No '{args.profile}' profile yet at '{config_path}'. Create it first "
                f"with: live-translator setup --profile {args.profile}"
            )
        args.config = str(config_path)
    config = load_config(Path(args.config))
    try:
        directory = verify_local_model(config.asr)
    except ModelNotPrepared:
        directory = download_model(config.asr)
    else:
        print(f"Already prepared: {config.asr.model} in {directory}.")
    print()
    print("Meeting mode can now run without internet access:")
    print(f"  live-translator meeting --config \"{args.config}\"")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    profile_path = Path(args.config_out) if args.config_out else default_profile_path(args.profile)
    if args.interactive_devices:
        microphone = args.input_device or prompt_for_device("input", "Select your physical microphone")
        output = args.translated_output_device or prompt_for_device(
            "output",
            "Select the virtual playback endpoint that receives translated speech",
        )
        meeting_microphone = args.meeting_microphone_device or prompt_for_device(
            "input",
            "Select the matching virtual recording endpoint for the meeting app microphone",
        )
    else:
        microphone = args.input_device or "auto"
        output = args.translated_output_device or "auto"
        meeting_microphone = args.meeting_microphone_device or "auto"
    written = write_meeting_profile(
        path=profile_path,
        direction=args.direction,
        microphone_device=microphone,
        translated_output_device=output,
        meeting_microphone_device=meeting_microphone,
        chunk_seconds=args.seconds,
    )
    print(f"Wrote profile: {written}")
    print()
    print("Meeting app setup:")
    print("  Microphone: the automatically selected matching CABLE Output")
    print("  Speaker: your real headphones, not the translated output endpoint")
    print()
    print(f"Run a route check with: live-translator route-test --config \"{written}\"")
    print(f"Start translation with: live-translator meeting --config \"{written}\"")
    return 0


def cmd_meeting(args: argparse.Namespace) -> int:
    if args.config is None:
        args.config = str(default_profile_path(args.profile))
    config = build_config(args)
    LocalTranslatorPipeline(config).loopback(
        debug_audio_dir=args.debug_audio_dir,
        verbose=args.verbose,
    )
    return 0


def cmd_route_test(args: argparse.Namespace) -> int:
    if args.config is None:
        args.config = str(default_profile_path(args.profile))
    config = build_config(args)
    meeting_input = args.meeting_microphone_device or config.audio.peer_input_device
    if not meeting_input:
        raise ValueError("Set audio.peer_input_device in the profile or pass --meeting-microphone-device.")
    if not config.audio.output_device:
        raise ValueError("Set audio.output_device to the virtual playback endpoint.")

    result = test_output_to_input_route(
        output_device=config.audio.output_device,
        input_device=meeting_input,
        sample_rate=config.audio.sample_rate,
        duration_seconds=args.seconds,
    )
    status = "PASS" if result.passed else "FAIL"
    output_detail = describe_device_selection(
        config.audio.output_device,
        "output",
        role="translated_output",
    )
    input_detail = describe_device_selection(
        meeting_input,
        "input",
        role="meeting_input",
    )
    print(
        f"{status}: {output_detail} -> {input_detail} "
        f"tone_rms={result.tone_rms:.4f} tone_ratio={result.tone_ratio:.2f} "
        f"sample_rate={result.sample_rate}"
    )
    if not result.passed:
        print("The meeting app probably will not hear translated audio on that microphone endpoint.")
        return 1
    return 0


def cmd_record_test(args: argparse.Namespace) -> int:
    config = build_config(args)
    LocalTranslatorPipeline(config).record_test(args.out, args.seconds, args.play)
    return 0


def cmd_say(args: argparse.Namespace) -> int:
    if args.config is None and args.tts_engine is None:
        args.tts_engine = "pyttsx3"
    config = build_config(args)
    TtsSpeaker(config.tts, config.audio).speak(args.text)
    return 0


def cmd_translate_text(args: argparse.Namespace) -> int:
    config = build_config(args)
    translated = TranslationEngine(config.translation).translate(args.text)
    print(translated)
    return 0


def cmd_argos_list(_args: argparse.Namespace) -> int:
    print_installed_argos_packages()
    return 0


def cmd_argos_install(args: argparse.Namespace) -> int:
    install_argos_package(args.source_language, args.target_language)
    return 0


def cmd_transcribe_once(args: argparse.Namespace) -> int:
    config = build_config(args)
    LocalTranslatorPipeline(config).transcribe_once(args.seconds)
    return 0


def cmd_translate_once(args: argparse.Namespace) -> int:
    config = build_config(args)
    LocalTranslatorPipeline(config).translate_once(args.seconds, speak=not args.no_speak)
    return 0


def cmd_loopback(args: argparse.Namespace) -> int:
    config = build_config(args)
    LocalTranslatorPipeline(config).loopback(
        debug_audio_dir=args.debug_audio_dir,
        verbose=args.verbose,
    )
    return 0


def build_config(args: argparse.Namespace):
    config_path = Path(args.config) if args.config else None
    if config_path is None and getattr(args, "use_default_profile", False):
        config_path = default_profile_path()
    config = load_config(config_path)
    return apply_cli_overrides(
        config,
        seconds=getattr(args, "seconds", None),
        input_device=getattr(args, "input_device", None),
        output_device=getattr(args, "output_device", None),
        input_gain=getattr(args, "input_gain", None),
        asr_engine=getattr(args, "asr_engine", None),
        model=getattr(args, "model", None),
        source_language=getattr(args, "source_language", None),
        target_language=getattr(args, "target_language", None),
        translation_engine=getattr(args, "translation_engine", None),
        tts_engine=getattr(args, "tts_engine", None),
        tts_voice=getattr(args, "tts_voice", None),
        tts_model_path=getattr(args, "tts_model", None),
        piper_exe=getattr(args, "piper_exe", None),
        tts_length_scale=getattr(args, "tts_length_scale", None),
        piper_timeout_seconds=getattr(args, "piper_timeout", None),
        log_prob_threshold=getattr(args, "log_prob_threshold", None),
        flag_log_prob_threshold=getattr(args, "flag_log_prob_threshold", None),
        chunker_mode=getattr(args, "chunker", None),
        vad_threshold=getattr(args, "vad_threshold", None),
        peak_threshold=getattr(args, "peak_threshold", None),
        min_active_ratio=getattr(args, "min_active_ratio", None),
        min_segment_seconds=getattr(args, "min_segment_seconds", None),
        silence_ms=getattr(args, "silence_ms", None),
        max_seconds=getattr(args, "max_seconds", None),
        rolling_window_seconds=getattr(args, "rolling_window_seconds", None),
    )
