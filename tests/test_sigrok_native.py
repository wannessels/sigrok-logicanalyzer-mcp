"""Tests for sigrok_native.py — mocked sigrok bindings and pysigrok decoding."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock, PropertyMock

import numpy as np
import pytest

from sigrok_logic_analyzer_mcp.sigrok_native import (
    scan_devices,
    run_capture,
    decode_protocol,
    decode_protocol_from_data,
    list_decoders,
    list_decoders_sync,
    export_data,
    export_data_from_array,
    SigrokNotFoundError,
    DeviceNotFoundError,
    CaptureError,
    DecoderError,
    _parse_sample_rate,
    _parse_channel_spec,
    _parse_triggers,
    _data_to_bits,
    _data_to_hex,
    _data_to_packed_ints,
    _find_sigrok_cli,
)


# ---------------------------------------------------------------------------
# Helper: mock sigrok.core.classes
# ---------------------------------------------------------------------------

def _make_mock_sr():
    """Create a mock sigrok.core.classes module."""
    sr = MagicMock()

    # PacketType enum
    sr.PacketType.LOGIC = "LOGIC"
    sr.PacketType.ANALOG = "ANALOG"
    sr.PacketType.HEADER = "HEADER"
    sr.PacketType.END = "END"

    # ConfigKey
    sr.ConfigKey.SAMPLERATE = MagicMock()
    sr.ConfigKey.SAMPLERATE.parse_string = MagicMock(side_effect=lambda x: int(x))
    sr.ConfigKey.LIMIT_SAMPLES = MagicMock()
    sr.ConfigKey.LIMIT_SAMPLES.parse_string = MagicMock(side_effect=lambda x: int(x))
    sr.ConfigKey.LIMIT_MSEC = MagicMock()
    sr.ConfigKey.LIMIT_MSEC.parse_string = MagicMock(side_effect=lambda x: int(x))

    # TriggerMatchType
    sr.TriggerMatchType.ZERO = "ZERO"
    sr.TriggerMatchType.ONE = "ONE"
    sr.TriggerMatchType.RISING = "RISING"
    sr.TriggerMatchType.FALLING = "FALLING"
    sr.TriggerMatchType.EDGE = "EDGE"

    return sr


def _make_mock_device(vendor="ZeroPlus", model="LAP-C(16128)", version="", num_channels=16):
    """Create a mock sigrok Device."""
    device = MagicMock()
    device.vendor = vendor
    device.model = model
    device.version = version
    channels = []
    for i in range(num_channels):
        ch = MagicMock()
        ch.name = f"D{i}"
        ch.index = i
        ch.enabled = True
        channels.append(ch)
    device.channels = channels
    return device


def _mock_process(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Create a mock asyncio.Process."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(
        return_value=(stdout.encode(), stderr.encode())
    )
    proc.returncode = returncode
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# Unit tests: parsing helpers
# ---------------------------------------------------------------------------

def test_parse_sample_rate_mhz():
    assert _parse_sample_rate("1m") == 1_000_000
    assert _parse_sample_rate("10M") == 10_000_000


def test_parse_sample_rate_khz():
    assert _parse_sample_rate("200k") == 200_000
    assert _parse_sample_rate("500K") == 500_000


def test_parse_sample_rate_plain():
    assert _parse_sample_rate("1000000") == 1_000_000


def test_parse_channel_spec_range():
    assert _parse_channel_spec("0-3") == {0, 1, 2, 3}


def test_parse_channel_spec_list():
    assert _parse_channel_spec("0,1,4,5") == {0, 1, 4, 5}


def test_parse_channel_spec_mixed():
    assert _parse_channel_spec("0-2,5") == {0, 1, 2, 5}


def test_parse_triggers():
    result = _parse_triggers("0=r,1=0")
    assert result == {0: "RISING", 1: "ZERO"}


def test_parse_triggers_all_types():
    result = _parse_triggers("0=0,1=1,2=r,3=f,4=e")
    assert result == {0: "ZERO", 1: "ONE", 2: "RISING", 3: "FALLING", 4: "EDGE"}


# ---------------------------------------------------------------------------
# Unit tests: data conversion
# ---------------------------------------------------------------------------

def test_data_to_bits_single_byte():
    # 0b10010011 = 0x93 -> bits are ch0=1, ch1=1, ch2=0, ch3=0, ch4=1, ch5=0, ch6=0, ch7=1
    data = np.array([[0x93]], dtype=np.uint8)
    bits = _data_to_bits(data, 8)
    assert len(bits) == 1
    assert bits[0] == "11001001"


def test_data_to_bits_fewer_channels():
    data = np.array([[0x05]], dtype=np.uint8)  # 0b00000101 -> ch0=1, ch1=0, ch2=1
    bits = _data_to_bits(data, 3)
    assert bits[0] == "101"


def test_data_to_bits_two_bytes():
    # 2-byte unit_size for 16 channels
    data = np.array([[0xFF, 0x00]], dtype=np.uint8)
    bits = _data_to_bits(data, 16)
    assert bits[0] == "1111111100000000"


def test_data_to_hex():
    data = np.array([[0x93], [0x92], [0x91]], dtype=np.uint8)
    result = _data_to_hex(data)
    assert result == ["93", "92", "91"]


def test_data_to_packed_ints():
    # Single byte: 0x05 = 0b00000101
    data = np.array([[0x05]], dtype=np.uint8)
    packed = _data_to_packed_ints(data)
    assert packed[0] == 0x05

    # Two bytes: [0xFF, 0x01] = 0x01FF
    data = np.array([[0xFF, 0x01]], dtype=np.uint8)
    packed = _data_to_packed_ints(data)
    assert packed[0] == 0x01FF


# ---------------------------------------------------------------------------
# Unit tests: export_data_from_array
# ---------------------------------------------------------------------------

def test_export_data_from_array_bits():
    data = np.array([[0x05], [0x03]], dtype=np.uint8)
    result = export_data_from_array(data, num_channels=4, output_format="bits")
    lines = result.strip().split("\n")
    assert lines[0] == "1010"   # 0x05: ch0=1, ch1=0, ch2=1, ch3=0
    assert lines[1] == "1100"   # 0x03: ch0=1, ch1=1, ch2=0, ch3=0


def test_export_data_from_array_hex():
    data = np.array([[0x93], [0x92]], dtype=np.uint8)
    result = export_data_from_array(data, num_channels=8, output_format="hex")
    lines = result.strip().split("\n")
    assert lines == ["93", "92"]


def test_export_data_from_array_with_channel_filter():
    data = np.array([[0x0F]], dtype=np.uint8)  # ch0-3 high, ch4-7 low
    result = export_data_from_array(
        data, num_channels=8, output_format="bits", channel_filter={0, 2}
    )
    lines = result.strip().split("\n")
    assert lines[0] == "11"  # ch0=1, ch2=1


def test_export_data_from_array_empty():
    data = np.empty((0, 1), dtype=np.uint8)
    result = export_data_from_array(data, num_channels=8)
    assert result == ""


def test_export_data_from_array_csv():
    data = np.array([[0x05]], dtype=np.uint8)
    result = export_data_from_array(data, num_channels=4, output_format="csv")
    lines = result.strip().split("\n")
    assert lines[0] == "1,0,1,0"


# ---------------------------------------------------------------------------
# Async tests: scan_devices (native)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_devices_found():
    mock_sr = _make_mock_sr()
    device = _make_mock_device()
    driver = MagicMock()
    driver.scan.return_value = [device]
    context = MagicMock()
    context.drivers = {"zeroplus-logic-cube": driver}
    mock_sr.Context.create.return_value = context

    import sigrok_logic_analyzer_mcp.sigrok_native as mod
    original = mod._sr
    mod._sr = mock_sr
    try:
        devices = await scan_devices()
        assert len(devices) == 1
        assert "ZeroPlus" in devices[0]["description"]
        assert "LAP-C(16128)" in devices[0]["description"]
        assert devices[0]["channels"] == 16
        assert devices[0]["driver"] == "zeroplus-logic-cube"
    finally:
        mod._sr = original


@pytest.mark.asyncio
async def test_scan_devices_none_found():
    mock_sr = _make_mock_sr()
    driver = MagicMock()
    driver.scan.return_value = []
    context = MagicMock()
    context.drivers = {"zeroplus-logic-cube": driver}
    mock_sr.Context.create.return_value = context

    import sigrok_logic_analyzer_mcp.sigrok_native as mod
    original = mod._sr
    mod._sr = mock_sr
    try:
        with pytest.raises(DeviceNotFoundError, match="No devices found"):
            await scan_devices()
    finally:
        mod._sr = original


@pytest.mark.asyncio
async def test_scan_devices_unknown_driver():
    mock_sr = _make_mock_sr()
    context = MagicMock()
    context.drivers = {"demo": MagicMock()}
    mock_sr.Context.create.return_value = context

    import sigrok_logic_analyzer_mcp.sigrok_native as mod
    original = mod._sr
    mod._sr = mock_sr
    try:
        with pytest.raises(DeviceNotFoundError, match="Unknown driver"):
            await scan_devices(driver="nonexistent")
    finally:
        mod._sr = original


# ---------------------------------------------------------------------------
# Async tests: run_capture (native)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_capture_basic():
    mock_sr = _make_mock_sr()
    device = _make_mock_device(num_channels=4)
    driver = MagicMock()
    driver.scan.return_value = [device]
    context = MagicMock()
    context.drivers = {"zeroplus-logic-cube": driver}

    # Mock session that produces data via callback
    session = MagicMock()
    captured_callback = {}

    def add_cb(cb):
        captured_callback["cb"] = cb

    session.add_datafeed_callback = add_cb

    def mock_run():
        # Simulate a LOGIC packet
        packet = MagicMock()
        packet.type = mock_sr.PacketType.LOGIC
        payload = MagicMock()
        payload.data = np.array([[0x05], [0x0A]], dtype=np.uint8)
        packet.payload = payload
        captured_callback["cb"](device, packet)

    session.run = mock_run
    context.create_session.return_value = session
    mock_sr.Context.create.return_value = context

    import sigrok_logic_analyzer_mcp.sigrok_native as mod
    original = mod._sr
    mod._sr = mock_sr
    try:
        data, num_ch = await run_capture(
            output_file="/tmp/test.sr",
            sample_rate="1m",
            num_samples=1024,
            channels="0-3",
        )
        assert num_ch == 4
        assert data.shape == (2, 1)

        # Verify device was configured
        device.open.assert_called_once()
        device.config_set.assert_any_call(
            mock_sr.ConfigKey.SAMPLERATE,
            1_000_000,
        )
        device.close.assert_called_once()
    finally:
        mod._sr = original


@pytest.mark.asyncio
async def test_run_capture_no_device():
    mock_sr = _make_mock_sr()
    driver = MagicMock()
    driver.scan.return_value = []
    context = MagicMock()
    context.drivers = {"zeroplus-logic-cube": driver}
    mock_sr.Context.create.return_value = context

    import sigrok_logic_analyzer_mcp.sigrok_native as mod
    original = mod._sr
    mod._sr = mock_sr
    try:
        with pytest.raises(CaptureError, match="No devices found"):
            await run_capture(output_file="/tmp/test.sr")
    finally:
        mod._sr = original


# ---------------------------------------------------------------------------
# Native protocol decoding tests (pysigrok)
# ---------------------------------------------------------------------------

def _generate_uart_byte(byte_val, samplerate, baudrate, ch_bit=0):
    """Generate UART signal samples for a single byte."""
    spb = int(samplerate / baudrate)
    samples = []
    samples.extend([0] * spb)  # start bit (low)
    for bit_num in range(8):
        bit = (byte_val >> bit_num) & 1
        samples.extend([bit << ch_bit] * spb)
    samples.extend([(1 << ch_bit)] * spb)  # stop bit (high)
    return samples


def test_decode_protocol_from_data_uart():
    """Test native UART decoding with pysigrok."""
    samplerate = 100000
    baudrate = 9600

    # Build signal: idle + 'H' (0x48) + idle + 'i' (0x69) + idle
    idle = [0x01] * 100
    signal = (
        idle
        + _generate_uart_byte(0x48, samplerate, baudrate)
        + [0x01] * 50
        + _generate_uart_byte(0x69, samplerate, baudrate)
        + [0x01] * 100
    )

    # Convert to the [num_samples, unit_size] format used by capture store
    data = np.array(signal, dtype=np.uint8).reshape(-1, 1)

    result = decode_protocol_from_data(
        data=data,
        num_channels=1,
        sample_rate=samplerate,
        decoder_id="uart",
        decoder_options={"baudrate": "9600"},
        channel_mapping={"rx": "0"},
    )

    # Should decode 'H' (0x48) and 'i' (0x69)
    assert "48" in result
    assert "69" in result
    assert "rx-data" in result


def test_decode_protocol_from_data_with_filter():
    """Test native decoding with annotation filter."""
    samplerate = 100000
    baudrate = 9600

    idle = [0x01] * 100
    signal = idle + _generate_uart_byte(0x48, samplerate, baudrate) + [0x01] * 100
    data = np.array(signal, dtype=np.uint8).reshape(-1, 1)

    result = decode_protocol_from_data(
        data=data,
        num_channels=1,
        sample_rate=samplerate,
        decoder_id="uart",
        decoder_options={"baudrate": "9600"},
        channel_mapping={"rx": "0"},
        annotation_filter="rx-data",
    )

    # With filter, should only have rx-data annotations
    assert "rx-data" in result
    # Should NOT have start/stop bit annotations
    assert "rx-start" not in result


def test_decode_protocol_from_data_unknown_decoder():
    """Test that unknown decoder raises DecoderError."""
    data = np.array([[0x01]], dtype=np.uint8)
    with pytest.raises(DecoderError, match="Unknown decoder"):
        decode_protocol_from_data(
            data=data,
            num_channels=1,
            sample_rate=1000000,
            decoder_id="nonexistent_decoder_xyz",
        )


@pytest.mark.asyncio
async def test_decode_protocol_native_path():
    """Test that decode_protocol uses native path when data is provided."""
    samplerate = 100000
    baudrate = 9600

    idle = [0x01] * 100
    signal = idle + _generate_uart_byte(0x48, samplerate, baudrate) + [0x01] * 100
    data = np.array(signal, dtype=np.uint8).reshape(-1, 1)

    result = await decode_protocol(
        decoder="uart",
        decoder_options={"baudrate": "9600"},
        channel_mapping={"rx": "0"},
        data=data,
        num_channels=1,
        sample_rate=samplerate,
    )

    assert "48" in result


# ---------------------------------------------------------------------------
# Native list_decoders tests (pysigrok entry points)
# ---------------------------------------------------------------------------

def test_list_decoders_sync():
    """Test listing decoders via pysigrok entry points."""
    decoders = list_decoders_sync()
    assert len(decoders) > 0

    # Known decoders should be present
    decoder_ids = {d["id"] for d in decoders}
    assert "uart" in decoder_ids
    assert "i2c" in decoder_ids
    assert "spi" in decoder_ids

    # Each decoder should have an id and description
    for d in decoders:
        assert "id" in d
        assert "description" in d


@pytest.mark.asyncio
async def test_list_decoders_async():
    """Test async wrapper for listing decoders."""
    decoders = await list_decoders()
    assert len(decoders) > 0
    decoder_ids = {d["id"] for d in decoders}
    assert "uart" in decoder_ids


# ---------------------------------------------------------------------------
# Fallback tests: decode via sigrok-cli (when no in-memory data)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_sigrok_cli(monkeypatch):
    """Patch shutil.which to pretend sigrok-cli exists."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/sigrok-cli")


@pytest.mark.asyncio
async def test_decode_cli_fallback(mock_sigrok_cli):
    """Test sigrok-cli fallback when no in-memory data is provided."""
    output = "i2c-1: Write address: 50\ni2c-1: Data write: 00\n"

    with patch("asyncio.create_subprocess_exec", return_value=_mock_process(stdout=output)) as mock_exec:
        result = await decode_protocol(
            input_file="/tmp/test.sr",
            decoder="i2c",
            channel_mapping={"sda": "0", "scl": "1"},
        )

    assert "Write address" in result

    call_args = mock_exec.call_args[0]
    assert "-P" in call_args
    p_idx = list(call_args).index("-P")
    decoder_spec = call_args[p_idx + 1]
    assert "i2c" in decoder_spec
    assert "sda=0" in decoder_spec
    assert "scl=1" in decoder_spec


@pytest.mark.asyncio
async def test_decode_cli_failure(mock_sigrok_cli):
    proc = _mock_process(stderr="Unknown decoder 'foobar'", returncode=1)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(DecoderError):
            await decode_protocol(input_file="/tmp/test.sr", decoder="foobar")


# ---------------------------------------------------------------------------
# Async tests: export_data (via sigrok-cli fallback)
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
