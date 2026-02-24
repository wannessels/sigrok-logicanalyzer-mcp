"""Wrapper around sigrok-cli subprocess calls.

All interaction with the sigrok-cli binary is isolated here. Each function
builds a command, runs it via asyncio subprocess, and parses the output.
"""

from __future__ import annotations

import asyncio
import re
import shutil


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SigrokNotFoundError(Exception):
    """sigrok-cli is not installed or not on PATH."""


class SigrokError(Exception):
    """Generic error from sigrok-cli (non-zero exit, stderr output, etc.)."""


class DeviceNotFoundError(SigrokError):
    """No device found during scan."""


class CaptureError(SigrokError):
    """Capture failed (timeout, USB error, device busy, etc.)."""


class DecoderError(SigrokError):
    """Protocol decoder failed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIGROK_CLI = "sigrok-cli"
_DEFAULT_TIMEOUT = 30  # seconds


def _find_sigrok_cli() -> str:
    """Verify sigrok-cli is available and return its path."""
    path = shutil.which(_SIGROK_CLI)
    if path is None:
        raise SigrokNotFoundError(
            "sigrok-cli not found on PATH. Install it with your package manager "
            "(e.g. 'apt install sigrok-cli' or 'brew install sigrok')."
        )
    return path


async def _run(
    args: list[str],
    timeout: float = _DEFAULT_TIMEOUT,
) -> str:
    """Run sigrok-cli with the given arguments and return stdout.

    Raises SigrokError on non-zero exit code.
    """
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
        raise CaptureError(
            f"sigrok-cli timed out after {timeout}s. "
            f"Command: {' '.join(cmd)}"
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        raise SigrokError(
            f"sigrok-cli exited with code {proc.returncode}.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr: {stderr.strip()}"
        )

    return stdout


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def scan_devices(driver: str = "zeroplus-logic-cube") -> list[dict]:
    """Scan for connected devices using the specified driver.

    Returns a list of dicts with keys: driver, description, connection.
    """
    output = await _run(["--driver", driver, "--scan"])

    devices = []
    # sigrok-cli --scan output format:
    #   The following devices were found:
    #   zeroplus-logic-cube - ZeroPlus Logic Cube LAP-C(16128) with 16 channels
    for line in output.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("The following"):
            continue
        devices.append({
            "driver": driver,
            "description": line,
        })

    if not devices:
        raise DeviceNotFoundError(
            f"No devices found with driver '{driver}'. "
            "Check USB connection and permissions (udev rules)."
        )

    return devices


async def get_device_info(driver: str = "zeroplus-logic-cube") -> str:
    """Get detailed device information (sample rates, channels, etc.)."""
    return await _run(["--driver", driver, "--show"])


async def run_capture(
    output_file: str,
    driver: str = "zeroplus-logic-cube",
    channels: str | None = None,
    sample_rate: str = "1m",
    num_samples: int | None = None,
    duration_ms: int | None = None,
    triggers: str | None = None,
    wait_trigger: bool = False,
) -> str:
    """Run a capture and save to an .sr file.

    Args:
        output_file: Path to save the .sr capture file.
        driver: sigrok driver name.
        channels: Channel spec using device names, e.g. "A0-A7" or "A0,A1,B0,B1".
        sample_rate: Sample rate, e.g. "1m" for 1 MHz, "200k" for 200 kHz.
        num_samples: Number of samples to capture (mutually exclusive with duration_ms).
        duration_ms: Capture duration in milliseconds.
        triggers: Trigger spec, e.g. "A0=r,A1=0" (channel A0 rising, A1 low).
        wait_trigger: If True, suppress pre-trigger data.

    Returns:
        sigrok-cli stdout (usually empty on success).
    """
    args = ["--driver", driver, "--config", f"samplerate={sample_rate}"]

    if channels:
        args += ["--channels", channels]

    if num_samples is not None:
        args += ["--samples", str(num_samples)]
    elif duration_ms is not None:
        args += ["--time", str(duration_ms)]
    else:
        # Default: capture 1024 samples
        args += ["--samples", "1024"]

    if triggers:
        args += ["--triggers", triggers]

    if wait_trigger:
        args += ["--wait-trigger"]

    args += ["--output-file", output_file]

    # Captures may take longer, especially with triggers
    timeout = 60.0
    if duration_ms:
        timeout = max(timeout, duration_ms / 1000 + 10)

    try:
        return await _run(args, timeout=timeout)
    except SigrokError as e:
        raise CaptureError(str(e)) from e


async def decode_protocol(
    input_file: str,
    decoder: str,
    decoder_options: dict[str, str] | None = None,
    channel_mapping: dict[str, str] | None = None,
    annotation_filter: str | None = None,
) -> str:
    """Run a protocol decoder on a captured .sr file.

    Args:
        input_file: Path to the .sr capture file.
        decoder: Decoder name, e.g. "i2c", "spi", "uart".
        decoder_options: Decoder-specific options, e.g. {"baudrate": "115200"}.
        channel_mapping: Map protocol signals to channels,
            e.g. {"sda": "0", "scl": "1"} or {"rx": "0"}.
        annotation_filter: Annotation filter, e.g. "i2c=data-write" to show
            only specific annotation classes.

    Returns:
        Decoded protocol output as text.
    """
    # Build the decoder spec: decoder[:key=val:key=val]
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

    try:
        return await _run(args, timeout=30.0)
    except SigrokError as e:
        raise DecoderError(str(e)) from e


async def list_decoders() -> list[dict]:
    """List all available protocol decoders.

    Returns a list of dicts with keys: id, description.
    """
    output = await _run(["--list-supported"])

    decoders = []
    in_decoders = False

    for line in output.splitlines():
        # The decoder section starts with "Supported protocol decoders:"
        if "protocol decoders" in line.lower():
            in_decoders = True
            continue
        # Sections end when a new "Supported ..." header appears
        if in_decoders and line.startswith("Supported "):
            break
        if in_decoders and line.strip():
            # Format: "  i2c       Inter-Integrated Circuit"
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                decoders.append({"id": parts[0], "description": parts[1]})
            elif len(parts) == 1:
                decoders.append({"id": parts[0], "description": ""})

    return decoders


async def export_data(
    input_file: str,
    output_format: str = "bits",
    channels: str | None = None,
) -> str:
    """Export captured data in a text format.

    Args:
        input_file: Path to the .sr capture file.
        output_format: One of "bits", "hex", "ascii", "csv".
        channels: Optional channel filter.

    Returns:
        Formatted data as text.
    """
    args = ["-i", input_file, "--output-format", output_format]
    if channels:
        args += ["--channels", channels]

    return await _run(args, timeout=30.0)
