"""Tests for sigrok_cli.py — mocked subprocess calls."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from sigrok_logic_analyzer_mcp.sigrok_cli import (
    scan_devices,
    run_capture,
    decode_protocol,
    list_decoders,
    export_data,
    SigrokNotFoundError,
    DeviceNotFoundError,
    CaptureError,
    DecoderError,
    _find_sigrok_cli,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_process(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Create a mock asyncio.Process."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(
        return_value=(stdout.encode(), stderr.encode())
    )
    proc.returncode = returncode
    proc.kill = MagicMock()
    return proc


@pytest.fixture
def mock_sigrok_cli(monkeypatch):
    """Patch shutil.which to pretend sigrok-cli exists."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/sigrok-cli")


# ---------------------------------------------------------------------------
# _find_sigrok_cli
# ---------------------------------------------------------------------------

def test_find_sigrok_cli_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(SigrokNotFoundError, match="not found"):
        _find_sigrok_cli()


def test_find_sigrok_cli_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/sigrok-cli")
    assert _find_sigrok_cli() == "/usr/bin/sigrok-cli"


# ---------------------------------------------------------------------------
# scan_devices
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_devices_found(mock_sigrok_cli):
    output = (
        "The following devices were found:\n"
        "zeroplus-logic-cube - ZeroPlus Logic Cube LAP-C(16128) with 16 channels\n"
    )

    with patch("asyncio.create_subprocess_exec", return_value=_mock_process(stdout=output)):
        devices = await scan_devices()

    assert len(devices) == 1
    assert "LAP-C(16128)" in devices[0]["description"]
    assert devices[0]["driver"] == "zeroplus-logic-cube"


@pytest.mark.asyncio
async def test_scan_devices_none_found(mock_sigrok_cli):
    with patch("asyncio.create_subprocess_exec", return_value=_mock_process(stdout="")):
        with pytest.raises(DeviceNotFoundError, match="No devices found"):
            await scan_devices()


# ---------------------------------------------------------------------------
# run_capture
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_capture_basic(mock_sigrok_cli):
    with patch("asyncio.create_subprocess_exec", return_value=_mock_process()) as mock_exec:
        await run_capture(
            output_file="/tmp/test.sr",
            sample_rate="1m",
            num_samples=1024,
            channels="0-3",
        )

    # Verify the command was constructed correctly
    call_args = mock_exec.call_args[0]
    assert "--driver" in call_args
    assert "zeroplus-logic-cube" in call_args
    assert "--config" in call_args
    assert "samplerate=1m" in call_args
    assert "--channels" in call_args
    assert "0-3" in call_args
    assert "--samples" in call_args
    assert "1024" in call_args
    assert "--output-file" in call_args
    assert "/tmp/test.sr" in call_args


@pytest.mark.asyncio
async def test_run_capture_with_triggers(mock_sigrok_cli):
    with patch("asyncio.create_subprocess_exec", return_value=_mock_process()) as mock_exec:
        await run_capture(
            output_file="/tmp/test.sr",
            triggers="0=r,1=0",
            wait_trigger=True,
        )

    call_args = mock_exec.call_args[0]
    assert "--triggers" in call_args
    assert "0=r,1=0" in call_args
    assert "--wait-trigger" in call_args


@pytest.mark.asyncio
async def test_run_capture_with_duration(mock_sigrok_cli):
    with patch("asyncio.create_subprocess_exec", return_value=_mock_process()) as mock_exec:
        await run_capture(
            output_file="/tmp/test.sr",
            duration_ms=500,
        )

    call_args = mock_exec.call_args[0]
    assert "--time" in call_args
    assert "500" in call_args


@pytest.mark.asyncio
async def test_run_capture_failure(mock_sigrok_cli):
    proc = _mock_process(stderr="USB error", returncode=1)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(CaptureError, match="USB error"):
            await run_capture(output_file="/tmp/test.sr")


# ---------------------------------------------------------------------------
# decode_protocol
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decode_i2c(mock_sigrok_cli):
    output = "i2c-1: Write address: 50\ni2c-1: Data write: 00\ni2c-1: Data read: FF\n"

    with patch("asyncio.create_subprocess_exec", return_value=_mock_process(stdout=output)) as mock_exec:
        result = await decode_protocol(
            input_file="/tmp/test.sr",
            decoder="i2c",
            channel_mapping={"sda": "0", "scl": "1"},
        )

    assert "Write address" in result

    call_args = mock_exec.call_args[0]
    assert "-P" in call_args
    # The decoder spec should include channel mapping
    p_idx = list(call_args).index("-P")
    decoder_spec = call_args[p_idx + 1]
    assert "i2c" in decoder_spec
    assert "sda=0" in decoder_spec
    assert "scl=1" in decoder_spec


@pytest.mark.asyncio
async def test_decode_uart_with_options(mock_sigrok_cli):
    output = "uart-1: TX data: 48\nuart-1: TX data: 65\n"

    with patch("asyncio.create_subprocess_exec", return_value=_mock_process(stdout=output)) as mock_exec:
        result = await decode_protocol(
            input_file="/tmp/test.sr",
            decoder="uart",
            decoder_options={"baudrate": "115200", "parity": "none"},
            channel_mapping={"rx": "0"},
        )

    call_args = mock_exec.call_args[0]
    p_idx = list(call_args).index("-P")
    decoder_spec = call_args[p_idx + 1]
    assert "uart" in decoder_spec
    assert "baudrate=115200" in decoder_spec


@pytest.mark.asyncio
async def test_decode_failure(mock_sigrok_cli):
    proc = _mock_process(stderr="Unknown decoder 'foobar'", returncode=1)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(DecoderError):
            await decode_protocol(input_file="/tmp/test.sr", decoder="foobar")


# ---------------------------------------------------------------------------
# list_decoders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_decoders(mock_sigrok_cli):
    output = (
        "Supported hardware drivers:\n"
        "  fx2lafw        fx2lafw\n"
        "\n"
        "Supported protocol decoders:\n"
        "  i2c            Inter-Integrated Circuit\n"
        "  spi            Serial Peripheral Interface\n"
        "  uart           Universal Asynchronous Receiver/Transmitter\n"
        "\n"
        "Supported input formats:\n"
        "  csv            CSV\n"
    )

    with patch("asyncio.create_subprocess_exec", return_value=_mock_process(stdout=output)):
        decoders = await list_decoders()

    assert len(decoders) == 3
    assert decoders[0]["id"] == "i2c"
    assert decoders[1]["id"] == "spi"
    assert decoders[2]["id"] == "uart"
    assert "Inter-Integrated" in decoders[0]["description"]


# ---------------------------------------------------------------------------
# export_data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_bits(mock_sigrok_cli):
    output = "10010011\n10010010\n10010001\n"

    with patch("asyncio.create_subprocess_exec", return_value=_mock_process(stdout=output)) as mock_exec:
        result = await export_data(
            input_file="/tmp/test.sr",
            output_format="bits",
            channels="0-7",
        )

    assert result == output
    call_args = mock_exec.call_args[0]
    assert "--output-format" in call_args
    assert "bits" in call_args
