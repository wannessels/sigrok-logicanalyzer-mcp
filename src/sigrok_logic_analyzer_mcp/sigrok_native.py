"""Native Python interface to sigrok via libsigrok and pysigrok bindings.

Uses the sigrok.core SWIG bindings for device scanning, configuration, and
capture. Uses pysigrok (sigrokdecode) for protocol decoding natively in
Python — no sigrok-cli subprocess needed.
"""

from __future__ import annotations

import asyncio
import functools
import shutil
from importlib.metadata import entry_points
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SigrokError(Exception):
    """Generic sigrok error."""


class SigrokNotFoundError(SigrokError):
    """sigrok Python bindings not available."""


class DeviceNotFoundError(SigrokError):
    """No device found during scan."""


class CaptureError(SigrokError):
    """Capture failed."""


class DecoderError(SigrokError):
    """Protocol decoder failed."""


# ---------------------------------------------------------------------------
# Lazy import of sigrok bindings
# ---------------------------------------------------------------------------

_sr = None  # sigrok.core.classes module, loaded lazily


def _get_sr():
    """Lazily import sigrok.core.classes, raising SigrokNotFoundError on failure."""
    global _sr
    if _sr is None:
        try:
            import sigrok.core.classes as sr
            _sr = sr
        except ImportError as e:
            raise SigrokNotFoundError(
                "sigrok Python bindings not found. Install libsigrok with "
                "Python bindings enabled (e.g. 'apt install python3-libsigrok' "
                "or build from source with --enable-python)."
            ) from e
    return _sr


def _get_context():
    """Create and return a libsigrok Context."""
    sr = _get_sr()
    return sr.Context.create()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sample_rate(rate_str: str) -> int:
    """Parse a sample rate string like '1m', '200k', '100' into Hz."""
    rate_str = rate_str.strip().lower()
    multipliers = {"k": 1_000, "m": 1_000_000, "g": 1_000_000_000}
    for suffix, mult in multipliers.items():
        if rate_str.endswith(suffix):
            return int(float(rate_str[:-1]) * mult)
    return int(float(rate_str))


def _parse_channel_spec(spec: str) -> set[int]:
    """Parse a channel spec like '0-3' or '0,1,4,5' into a set of ints."""
    channels: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            channels.update(range(int(start), int(end) + 1))
        else:
            channels.add(int(part))
    return channels


_TRIGGER_MAP = {
    "0": "ZERO",
    "1": "ONE",
    "r": "RISING",
    "f": "FALLING",
    "e": "EDGE",
}


def _parse_triggers(trigger_str: str) -> dict[int, str]:
    """Parse trigger spec '0=r,1=0' into {channel: match_type_name}."""
    triggers: dict[int, str] = {}
    for pair in trigger_str.split(","):
        pair = pair.strip()
        if "=" in pair:
            ch_str, match = pair.split("=", 1)
            ch = int(ch_str.strip())
            match_name = _TRIGGER_MAP.get(match.strip().lower())
            if match_name:
                triggers[ch] = match_name
    return triggers


def _data_to_bits(data: np.ndarray, num_channels: int) -> list[str]:
    """Convert captured numpy data to a list of bit strings.

    Args:
        data: numpy uint8 array of shape [num_samples, unit_size].
        num_channels: total number of channels in the capture.

    Returns:
        List of strings like '10010011', one per sample.
    """
    lines = []
    for row in data:
        # Unpack bytes into individual bits, channel 0 = LSB of first byte
        bits = []
        for byte in row:
            for bit_idx in range(8):
                bits.append((int(byte) >> bit_idx) & 1)
        # Trim to actual channel count
        bits = bits[:num_channels]
        lines.append("".join(str(b) for b in bits))
    return lines


def _data_to_hex(data: np.ndarray) -> list[str]:
    """Convert captured numpy data to hex strings."""
    return ["".join(f"{int(b):02x}" for b in row) for row in data]


def _data_to_packed_ints(data: np.ndarray) -> np.ndarray:
    """Convert [num_samples, unit_size] uint8 data to packed integer samples.

    Each sample becomes a single integer where bit N = channel N.
    This is the format expected by pysigrok decoders.
    """
    result = np.zeros(len(data), dtype=np.uint32)
    for byte_idx in range(data.shape[1]):
        result |= data[:, byte_idx].astype(np.uint32) << (byte_idx * 8)
    return result


# ---------------------------------------------------------------------------
# Public API — Device scanning
# ---------------------------------------------------------------------------

async def scan_devices(driver: str = "zeroplus-logic-cube") -> list[dict]:
    """Scan for connected devices using the specified driver.

    Returns a list of dicts with keys: driver, description, channels, channel_names.
    """
    def _scan():
        context = _get_context()
        if driver not in context.drivers:
            available = ", ".join(sorted(context.drivers.keys()))
            raise DeviceNotFoundError(
                f"Unknown driver '{driver}'. Available drivers: {available}"
            )
        drv = context.drivers[driver]
        devices = drv.scan()
        if not devices:
            raise DeviceNotFoundError(
                f"No devices found with driver '{driver}'. "
                "Check USB connection and permissions (udev rules)."
            )
        result = []
        for dev in devices:
            channel_names = [ch.name for ch in dev.channels]
            desc = f"{dev.vendor} {dev.model}".strip()
            if dev.version:
                desc += f" {dev.version}"
            desc += f" with {len(channel_names)} channels"
            result.append({
                "driver": driver,
                "description": desc,
                "channels": len(channel_names),
                "channel_names": channel_names,
            })
        return result

    return await asyncio.get_event_loop().run_in_executor(None, _scan)


async def get_device_info(driver: str = "zeroplus-logic-cube") -> dict[str, Any]:
    """Get detailed device information."""
    def _info():
        context = _get_context()
        drv = context.drivers[driver]
        devices = drv.scan()
        if not devices:
            raise DeviceNotFoundError(f"No devices found with driver '{driver}'.")
        dev = devices[0]
        dev.open()
        try:
            info = {
                "vendor": dev.vendor,
                "model": dev.model,
                "version": dev.version,
                "channels": [
                    {"name": ch.name, "index": ch.index, "enabled": ch.enabled}
                    for ch in dev.channels
                ],
            }
        finally:
            dev.close()
        return info

    return await asyncio.get_event_loop().run_in_executor(None, _info)


# ---------------------------------------------------------------------------
# Public API — Capture
# ---------------------------------------------------------------------------

async def run_capture(
    output_file: str,
    driver: str = "zeroplus-logic-cube",
    channels: str | None = None,
    sample_rate: str = "1m",
    num_samples: int | None = None,
    duration_ms: int | None = None,
    triggers: str | None = None,
    wait_trigger: bool = False,
) -> tuple[np.ndarray, int]:
    """Run a capture and save to an .sr file.

    Returns (data, num_channels) where data is a numpy uint8 array
    of shape [num_samples, unit_size].
    """
    sr = _get_sr()
    rate_hz = _parse_sample_rate(sample_rate)
    requested_channels = _parse_channel_spec(channels) if channels else None
    trigger_spec = _parse_triggers(triggers) if triggers else None
    limit_samples = num_samples if num_samples is not None else (None if duration_ms else 1024)

    def _capture():
        context = _get_context()
        drv = context.drivers[driver]
        devices = drv.scan()
        if not devices:
            raise CaptureError(f"No devices found with driver '{driver}'.")
        device = devices[0]
        device.open()

        try:
            # Configure sample rate
            device.config_set(
                sr.ConfigKey.SAMPLERATE,
                sr.ConfigKey.SAMPLERATE.parse_string(str(rate_hz)),
            )

            # Configure sample limit
            if limit_samples is not None:
                device.config_set(
                    sr.ConfigKey.LIMIT_SAMPLES,
                    sr.ConfigKey.LIMIT_SAMPLES.parse_string(str(limit_samples)),
                )
            elif duration_ms is not None:
                device.config_set(
                    sr.ConfigKey.LIMIT_MSEC,
                    sr.ConfigKey.LIMIT_MSEC.parse_string(str(duration_ms)),
                )

            # Select channels
            if requested_channels is not None:
                for ch in device.channels:
                    ch.enabled = (ch.index in requested_channels)

            # Count enabled channels for later
            enabled_channels = [ch for ch in device.channels if ch.enabled]
            num_ch = len(enabled_channels)

            # Create session
            session = context.create_session()
            session.add_device(device)

            # Set up triggers if requested
            if trigger_spec:
                trig = context.create_trigger("capture_trigger")
                stage = trig.add_stage()
                for ch in enabled_channels:
                    if ch.index in trigger_spec:
                        match_name = trigger_spec[ch.index]
                        match_type = getattr(sr.TriggerMatchType, match_name)
                        stage.add_match(ch, match_type)
                session.trigger = trig

            # Save to .sr file and collect data
            session.begin_save(output_file)

            chunks: list[np.ndarray] = []

            def datafeed_cb(dev, packet):
                session.append(dev, packet)
                if packet.type == sr.PacketType.LOGIC:
                    chunks.append(packet.payload.data.copy())

            session.add_datafeed_callback(datafeed_cb)

            # Run the capture (blocking)
            session.start()
            session.run()

            if not chunks:
                return np.empty((0, 1), dtype=np.uint8), num_ch

            data = np.concatenate(chunks, axis=0)
            return data, num_ch

        except SigrokError:
            raise
        except Exception as e:
            raise CaptureError(str(e)) from e
        finally:
            device.close()

    return await asyncio.get_event_loop().run_in_executor(None, _capture)


# ---------------------------------------------------------------------------
# Public API — Data export (from in-memory numpy data)
# ---------------------------------------------------------------------------

def export_data_from_array(
    data: np.ndarray,
    num_channels: int,
    output_format: str = "bits",
    channel_filter: set[int] | None = None,
) -> str:
    """Export captured data from a numpy array to a text format.

    Args:
        data: numpy uint8 array of shape [num_samples, unit_size].
        num_channels: total number of channels.
        output_format: 'bits', 'hex', or 'csv'.
        channel_filter: optional set of channel indices to include.

    Returns:
        Formatted data as text.
    """
    if data.size == 0:
        return ""

    if output_format == "hex":
        lines = _data_to_hex(data)
    else:
        # Default to bits
        all_bits = _data_to_bits(data, num_channels)
        if channel_filter is not None:
            # Filter to only requested channels
            filtered = []
            for line in all_bits:
                filtered.append(
                    "".join(line[i] for i in range(len(line)) if i in channel_filter)
                )
            all_bits = filtered
        lines = all_bits

    if output_format == "csv":
        # Convert bits to CSV format
        bit_lines = _data_to_bits(data, num_channels)
        csv_lines = []
        for line in bit_lines:
            if channel_filter is not None:
                vals = [line[i] for i in range(len(line)) if i in channel_filter]
            else:
                vals = list(line)
            csv_lines.append(",".join(vals))
        lines = csv_lines

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public API — Protocol decoding (native via pysigrok)
# ---------------------------------------------------------------------------

def _get_srd():
    """Import sigrokdecode, raising DecoderError on failure."""
    try:
        import sigrokdecode as srd
        return srd
    except ImportError as e:
        raise DecoderError(
            "pysigrok not found. Install with: pip install pysigrok pysigrok-libsigrokdecode"
        ) from e


class _NumpyInput:
    """Feed logic data from a numpy array of packed integer samples into pysigrok."""

    def __init__(
        self,
        data: np.ndarray,
        samplerate: int,
        num_channels: int,
    ) -> None:
        from sigrokdecode.input import Input
        # We manually implement the Input interface instead of subclassing,
        # because we need the callbacks dict from Input.__init__
        self.callbacks: dict = {}
        self.data = data
        self.samplerate = samplerate
        self.logic_channels = [f"D{i}" for i in range(num_channels)]
        self.analog_channels: list[str] = []
        self.samplenum = -1
        self.matched: list[bool] | None = None
        self.last_sample: int | None = None
        self.start_samplenum: int | None = None
        self.unitsize = max(1, (num_channels + 7) // 8)

    def add_callback(self, output_type, output_filter, fun):
        if output_type not in self.callbacks:
            self.callbacks[output_type] = set()
        self.callbacks[output_type].add((output_filter, fun))

    def put(self, startsample, endsample, output_id, data):
        if output_id not in self.callbacks:
            return
        for output_filter, cb in self.callbacks[output_id]:
            cb(startsample, endsample, data)

    def wait(self, conds=None):
        srd = _get_srd()
        if conds is None:
            conds = []
        self.matched = [False]
        while not any(self.matched):
            self.matched = [True] * (len(conds) if conds else 1)
            self.samplenum += 1

            if self.samplenum >= len(self.data):
                if self.start_samplenum is not None:
                    self.put(
                        self.start_samplenum, self.samplenum,
                        srd.OUTPUT_PYTHON, ["logic", self.last_sample],
                    )
                raise EOFError()

            sample = int(self.data[self.samplenum])

            if self.last_sample is None:
                self.last_sample = sample
                self.start_samplenum = self.samplenum

            if self.last_sample != sample:
                self.put(
                    self.start_samplenum, self.samplenum,
                    srd.OUTPUT_PYTHON, ["logic", self.last_sample],
                )
                self.start_samplenum = self.samplenum

            for i, cond in enumerate(conds):
                if "skip" in cond:
                    cond["skip"] -= 1
                    self.matched[i] = cond["skip"] == 0
                    continue
                self.matched[i] = srd.cond_matches(
                    cond, self.last_sample, sample,
                )
            self.last_sample = sample

        bits = []
        for b in range(self.unitsize * 8):
            bits.append((sample >> b) & 0x1)
        return tuple(bits)


class _AnnotationCollector:
    """Collects decoded annotations from pysigrok decoders."""

    def __init__(self) -> None:
        self.annotations: list[dict] = []

    def reset(self):
        self.annotations.clear()

    def start(self):
        pass

    def stop(self):
        pass

    def metadata(self, key, value):
        pass

    def output(self, source, startsample, endsample, data):
        srd = _get_srd()
        # Only collect from actual Decoder instances, not from the Input
        if not isinstance(source, srd.Decoder):
            return
        decoder_cls = type(source)
        ann_index = data[0]
        ann_texts = data[1]
        ann_type = decoder_cls.annotations[ann_index]
        self.annotations.append({
            "start_sample": startsample,
            "end_sample": endsample,
            "ann_id": ann_type[0],
            "ann_desc": ann_type[1],
            "texts": ann_texts,
        })


def _coerce_option_value(opt_def: dict, value: str) -> Any:
    """Coerce a string option value to the type expected by the decoder."""
    default = opt_def.get("default")
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


def decode_protocol_from_data(
    data: np.ndarray,
    num_channels: int,
    sample_rate: int,
    decoder_id: str,
    decoder_options: dict[str, str] | None = None,
    channel_mapping: dict[str, str] | None = None,
    annotation_filter: str | None = None,
) -> str:
    """Run a protocol decoder on in-memory captured data using pysigrok.

    Args:
        data: numpy uint8 array of shape [num_samples, unit_size].
        num_channels: number of logic channels.
        sample_rate: sample rate in Hz.
        decoder_id: decoder name (e.g. 'uart', 'i2c', 'spi').
        decoder_options: decoder options (e.g. {'baudrate': '115200'}).
        channel_mapping: map decoder pins to channel indices
            (e.g. {'rx': '0'} or {'sda': '0', 'scl': '1'}).
        annotation_filter: only show this annotation type (e.g. 'rx-data').

    Returns:
        Decoded protocol output as text lines.
    """
    srd = _get_srd()

    try:
        decoder_cls = srd.get_decoder(decoder_id)
    except (RuntimeError, Exception) as e:
        raise DecoderError(f"Unknown decoder '{decoder_id}': {e}") from e

    # Build options dict starting from defaults
    options = {}
    for opt in getattr(decoder_cls, "options", ()):
        options[opt["id"]] = opt["default"]

    # Apply user overrides
    if decoder_options:
        for key, val in decoder_options.items():
            # Find the option definition to coerce type
            opt_def = None
            for o in getattr(decoder_cls, "options", ()):
                if o["id"] == key:
                    opt_def = o
                    break
            if opt_def is not None:
                options[key] = _coerce_option_value(opt_def, val)
            else:
                options[key] = val

    # Build pin mapping
    pin_map: dict[str, int] = {}
    if channel_mapping:
        for pin_id, ch_str in channel_mapping.items():
            pin_map[pin_id] = int(ch_str)

    # Convert data to packed integers
    packed = _data_to_packed_ints(data)

    # Create input source and output collector
    input_source = _NumpyInput(packed, sample_rate, num_channels)
    collector = _AnnotationCollector()

    decoder_config = [{
        "id": decoder_id,
        "cls": decoder_cls,
        "options": options,
        "pin_mapping": pin_map,
    }]

    ann_filter = annotation_filter
    # pysigrok uses output_filter as the annotation ID string
    try:
        srd.run_decoders(
            input_source, collector, decoder_config,
            output_type=srd.OUTPUT_ANN,
            output_filter=ann_filter,
        )
    except EOFError:
        pass
    except Exception as e:
        raise DecoderError(str(e)) from e

    # Format annotations as text lines
    lines = []
    for ann in collector.annotations:
        text = ann["texts"][0] if ann["texts"] else ""
        lines.append(f"{decoder_id}: {ann['ann_id']}: {text}")

    return "\n".join(lines)


async def decode_protocol(
    input_file: str | None = None,
    decoder: str = "",
    decoder_options: dict[str, str] | None = None,
    channel_mapping: dict[str, str] | None = None,
    annotation_filter: str | None = None,
    *,
    data: np.ndarray | None = None,
    num_channels: int = 0,
    sample_rate: int = 0,
) -> str:
    """Run a protocol decoder.

    If data/num_channels/sample_rate are provided, decodes natively using pysigrok.
    Otherwise, falls back to sigrok-cli on the input_file.
    """
    if data is not None and num_channels > 0 and sample_rate > 0:
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: decode_protocol_from_data(
                data, num_channels, sample_rate, decoder,
                decoder_options, channel_mapping, annotation_filter,
            ),
        )

    # Fallback to sigrok-cli for .sr files without in-memory data
    if input_file is None:
        raise DecoderError("No input data or file provided for decoding.")

    return await _decode_protocol_cli(
        input_file, decoder, decoder_options, channel_mapping, annotation_filter,
    )


# ---------------------------------------------------------------------------
# Public API — List decoders (native via pysigrok)
# ---------------------------------------------------------------------------

def list_decoders_sync() -> list[dict]:
    """List all available protocol decoders using pysigrok entry points."""
    eps = entry_points(group="pysigrok.decoders")
    decoders = []
    for ep in sorted(eps, key=lambda x: x.name):
        try:
            cls = ep.load()
            decoders.append({
                "id": getattr(cls, "id", ep.name),
                "description": getattr(cls, "longname", getattr(cls, "desc", "")),
            })
        except Exception:
            decoders.append({"id": ep.name, "description": "(failed to load)"})
    return decoders


async def list_decoders() -> list[dict]:
    """List all available protocol decoders."""
    return await asyncio.get_event_loop().run_in_executor(None, list_decoders_sync)


# ---------------------------------------------------------------------------
# sigrok-cli fallback (for .sr file decoding without in-memory data)
# ---------------------------------------------------------------------------

_SIGROK_CLI = "sigrok-cli"


def _find_sigrok_cli() -> str:
    """Verify sigrok-cli is available and return its path."""
    path = shutil.which(_SIGROK_CLI)
    if path is None:
        raise SigrokNotFoundError(
            "sigrok-cli not found on PATH. Install it with your package manager "
            "(e.g. 'apt install sigrok-cli' or 'brew install sigrok')."
        )
    return path


async def _run_cli(args: list[str], timeout: float = 30.0) -> str:
    """Run sigrok-cli with the given arguments and return stdout."""
    cmd = [_find_sigrok_cli()] + args

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise DecoderError(f"sigrok-cli timed out after {timeout}s.")

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        raise DecoderError(
            f"sigrok-cli exited with code {proc.returncode}.\n"
            f"stderr: {stderr.strip()}"
        )

    return stdout


async def _decode_protocol_cli(
    input_file: str,
    decoder: str,
    decoder_options: dict[str, str] | None = None,
    channel_mapping: dict[str, str] | None = None,
    annotation_filter: str | None = None,
) -> str:
    """Fallback: run protocol decoder via sigrok-cli subprocess."""
    decoder_spec = decoder
    opts: list[str] = []
    if channel_mapping:
        opts += [f"{sig}={ch}" for sig, ch in channel_mapping.items()]
    if decoder_options:
        opts += [f"{k}={v}" for k, v in decoder_options.items()]
    if opts:
        decoder_spec += ":" + ":".join(opts)

    args = ["-i", input_file, "-P", decoder_spec]
    if annotation_filter:
        args += ["-A", annotation_filter]

    return await _run_cli(args, timeout=30.0)


async def export_data(
    input_file: str,
    output_format: str = "bits",
    channels: str | None = None,
) -> str:
    """Export captured data from an .sr file via sigrok-cli.

    Fallback for when in-memory data is not available.
    """
    args = ["-i", input_file, "--output-format", output_format]
    if channels:
        args += ["--channels", channels]

    return await _run_cli(args, timeout=30.0)
