"""Native Python interface to sigrok via libsigrok bindings.

Uses the sigrok.core SWIG bindings for device scanning, configuration, and
capture. Falls back to sigrok-cli subprocess for protocol decoding (since
libsigrokdecode has no Python bindings).
"""

from __future__ import annotations

import asyncio
import functools
import shutil
import signal
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SigrokError(Exception):
    """Generic sigrok error."""


class SigrokNotFoundError(SigrokError):
    """sigrok Python bindings or sigrok-cli not available."""


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
# Public API — Protocol decoding (falls back to sigrok-cli)
# ---------------------------------------------------------------------------

_SIGROK_CLI = "sigrok-cli"


def _find_sigrok_cli() -> str:
    """Verify sigrok-cli is available and return its path."""
    path = shutil.which(_SIGROK_CLI)
    if path is None:
        raise SigrokNotFoundError(
            "sigrok-cli not found on PATH. Protocol decoding requires sigrok-cli. "
            "Install it with your package manager "
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


async def decode_protocol(
    input_file: str,
    decoder: str,
    decoder_options: dict[str, str] | None = None,
    channel_mapping: dict[str, str] | None = None,
    annotation_filter: str | None = None,
) -> str:
    """Run a protocol decoder on a captured .sr file.

    Uses sigrok-cli since libsigrokdecode has no Python bindings.
    """
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


async def list_decoders() -> list[dict]:
    """List all available protocol decoders.

    Uses sigrok-cli since libsigrokdecode has no Python bindings.
    """
    output = await _run_cli(["--list-supported"])

    decoders = []
    in_decoders = False

    for line in output.splitlines():
        if "protocol decoders" in line.lower():
            in_decoders = True
            continue
        if in_decoders and line.startswith("Supported "):
            break
        if in_decoders and line.strip():
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                decoders.append({"id": parts[0], "description": parts[1]})
            elif len(parts) == 1:
                decoders.append({"id": parts[0], "description": ""})

    return decoders


# ---------------------------------------------------------------------------
# Public API — Export from file (fallback via sigrok-cli)
# ---------------------------------------------------------------------------

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
