"""Wrapper around sigrok-cli subprocess calls.

All interaction with the sigrok-cli binary is isolated here. Each function
builds a command, runs it via asyncio subprocess, and parses the output.
"""

from __future__ import annotations

import asyncio
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

# Annotation filters that strip individual bit annotations for known protocols.
# Used when detail="summary" to get only high-level decode output from sigrok-cli.
_SUMMARY_ANNOTATION_FILTERS: dict[str, str] = {
    # --- Tested with example .sr files ---
    "i2c": "i2c=start:repeat-start:stop:ack:nack:address-read:address-write:data-read:data-write",
    "spi": "spi=mosi-data:miso-data:mosi-transfer:miso-transfer",
    "uart": "uart=rx-data:tx-data",
    "can": "can=sof:eof:id:ext-id:full-id:ide:rtr:dlc:data:warnings",
    "onewire_network": "onewire_network",
    "mdio": "mdio=decode",
    "usb_packet": "usb_packet",
    "dcf77": "dcf77=minute:hour:day:day-of-week:month:year",
    "am230x": "am230x=humidity:temperature:checksum",
    "avr_isp": "avr_isp",
    "spiflash": "spiflash",
    "sdcard_sd": "sdcard_sd=cmd0:cmd2:cmd3:cmd6:cmd7:cmd8:cmd9:cmd10:cmd11:cmd12:cmd13:cmd16:cmd17:cmd18:cmd23:cmd24:cmd25:cmd41:cmd55:decoded-fields",
    "z80": "z80=memrd:memwr:iord:iowr:instr",  # may need channel mapping debugging
    "arm_itm": "arm_itm",  # untested -- stacks on UART
    # --- Untested: communication buses ---
    "ac97": "ac97",  # untested
    "flexray": "flexray",  # untested
    "gpib": "gpib",  # untested
    "i2s": "i2s",  # untested
    "ieee488": "ieee488",  # untested
    "lin": "lin",  # untested
    "modbus": "modbus",  # untested
    "dali": "dali",  # untested
    "dmx512": "dmx512",  # untested
    "midi": "midi",  # untested
    "spdif": "spdif",  # untested
    "dsi": "dsi",  # untested
    "cec": "cec",  # untested
    "lpc": "lpc",  # untested
    "microwire": "microwire",  # untested
    "ps2": "ps2",  # untested
    "ssi32": "ssi32",  # untested
    "swim": "swim",  # untested
    "wiegand": "wiegand",  # untested
    "parallel": "parallel",  # untested
    "tdm_audio": "tdm_audio",  # untested
    "iec": "iec",  # untested
    # --- Untested: memory/storage ---
    "eeprom24xx": "eeprom24xx",  # untested
    "eeprom93xx": "eeprom93xx",  # untested
    "x2444m": "x2444m",  # untested
    "sda2506": "sda2506",  # untested
    "sdcard_spi": "sdcard_spi",  # untested
    # --- Untested: sensors ---
    "lm75": "lm75",  # untested
    "mlx90614": "mlx90614",  # untested
    "mxc6225xu": "mxc6225xu",  # untested
    "ds1307": "ds1307",  # untested
    "ds2408": "ds2408",  # untested
    "ds243x": "ds243x",  # untested
    "ds28ea00": "ds28ea00",  # untested
    "rtc8564": "rtc8564",  # untested
    "atsha204a": "atsha204a",  # untested
    "pca9571": "pca9571",  # untested
    "tca6408a": "tca6408a",  # untested
    # --- Untested: display/LED ---
    "max7219": "max7219",  # untested
    "seven_segment": "seven_segment",  # untested
    "rgb_led_spi": "rgb_led_spi",  # untested
    "rgb_led_ws281x": "rgb_led_ws281x",  # untested
    "st7735": "st7735",  # untested
    "tlc5620": "tlc5620",  # untested
    # --- Untested: RF/wireless ---
    "cc1101": "cc1101",  # untested
    "nrf24l01": "nrf24l01",  # untested
    "rfm12": "rfm12",  # untested
    "em4100": "em4100",  # untested
    "em4305": "em4305",  # untested
    "t55xx": "t55xx",  # untested
    "ir_nec": "ir_nec",  # untested
    "ir_rc5": "ir_rc5",  # untested
    "ir_rc6": "ir_rc6",  # untested
    "ook": "ook",  # untested
    "ook_oregon": "ook_oregon",  # untested
    "ook_vis": "ook_vis",  # untested
    "qi": "qi",  # untested
    "mrf24j40": "mrf24j40",  # untested
    # --- Untested: debug ---
    "swd": "swd",  # untested
    "jtag": "jtag",  # untested
    "jtag_ejtag": "jtag_ejtag",  # untested
    "jtag_stm32": "jtag_stm32",  # untested
    "arm_etmv3": "arm_etmv3",  # untested
    "arm_tpiu": "arm_tpiu",  # untested
    "avr_pdi": "avr_pdi",  # untested
    "mcs48": "mcs48",  # untested
    # --- Untested: USB ---
    "usb_signalling": "usb_signalling",  # untested
    "usb_power_delivery": "usb_power_delivery",  # untested
    "usb_request": "usb_request",  # untested
    # --- Untested: utility ---
    "counter": "counter",  # untested
    "timing": "timing",  # untested
    "jitter": "jitter",  # untested
    "guess_bitrate": "guess_bitrate",  # untested
    "pwm": "pwm",  # untested
    "miller": "miller",  # untested
    "morse": "morse",  # untested
    "graycode": "graycode",  # untested
    "rc_encode": "rc_encode",  # untested
    "stepper_motor": "stepper_motor",  # untested
    # --- Untested: misc ---
    "cfp": "cfp",  # untested
    "xfp": "xfp",  # untested
    "edid": "edid",  # untested
    "hdcp": "hdcp",  # untested
    "maple_bus": "maple_bus",  # untested
    "nes_gamepad": "nes_gamepad",  # untested
    "nunchuk": "nunchuk",  # untested
    "pan1321": "pan1321",  # untested
    "amulet_ascii": "amulet_ascii",  # untested
    "ade77xx": "ade77xx",  # untested
    "adf435x": "adf435x",  # untested
    "adns5020": "adns5020",  # untested
    "aud": "aud",  # untested
    "enc28j60": "enc28j60",  # untested
    "onewire_link": "onewire_link",  # untested
    "i2cdemux": "i2cdemux",  # untested
    "i2cfilter": "i2cfilter",  # untested
}


def get_summary_annotation_filter(decoder: str) -> str | None:
    """Return the default annotation filter for summary mode, or None."""
    return _SUMMARY_ANNOTATION_FILTERS.get(decoder)


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
            f"sigrok-cli timed out after {timeout}s. Command: {' '.join(cmd)}"
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
        devices.append(
            {
                "driver": driver,
                "description": line,
            }
        )

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
    trigger_timeout: float = 30.0,
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
        trigger_timeout: Timeout in seconds when waiting for a trigger (default 30).

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

    # Compute timeout: trigger waits use trigger_timeout, duration-based
    # captures need at least duration + buffer, otherwise use default.
    if triggers:
        timeout = trigger_timeout
    elif duration_ms:
        timeout = max(_DEFAULT_TIMEOUT, duration_ms / 1000 + 10)
    else:
        timeout = _DEFAULT_TIMEOUT

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
