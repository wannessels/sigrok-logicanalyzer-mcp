"""Tests for formatters.py."""

from sigrok_logic_analyzer_mcp.formatters import (
    format_decoded_protocol,
    format_raw_samples,
    summarize_capture_data,
)


# ---------------------------------------------------------------------------
# format_decoded_protocol
# ---------------------------------------------------------------------------

def test_format_decoded_empty():
    result = format_decoded_protocol("")
    assert "No protocol data" in result


def test_format_decoded_short():
    raw = "i2c: Write addr 0x50\ni2c: Data 0xFF\ni2c: ACK\n"
    result = format_decoded_protocol(raw, max_lines=10)
    assert "3 annotations" in result
    assert "Write addr" in result
    assert "truncated" not in result


def test_format_decoded_truncated():
    lines = [f"i2c: Data {i}" for i in range(500)]
    raw = "\n".join(lines)
    result = format_decoded_protocol(raw, max_lines=100)
    assert "500 annotations" in result
    assert "showing first 100" in result
    assert "400 more lines truncated" in result


# ---------------------------------------------------------------------------
# format_raw_samples
# ---------------------------------------------------------------------------

def test_format_raw_samples_basic():
    raw = "\n".join([f"{i:08b}" for i in range(100)])
    result = format_raw_samples(raw, start_sample=0, window_size=10)
    assert "0-9 of 100" in result
    assert "00000000" in result  # first sample


def test_format_raw_samples_windowed():
    raw = "\n".join([f"line{i}" for i in range(50)])
    result = format_raw_samples(raw, start_sample=20, window_size=5)
    assert "20-24 of 50" in result
    assert "line20" in result
    assert "line24" in result
    assert "line25" not in result


def test_format_raw_samples_empty():
    result = format_raw_samples("")
    assert "No sample data" in result


def test_format_raw_samples_clamps_to_bounds():
    raw = "\n".join(["1010"] * 10)
    result = format_raw_samples(raw, start_sample=8, window_size=100)
    assert "8-9 of 10" in result


# ---------------------------------------------------------------------------
# summarize_capture_data
# ---------------------------------------------------------------------------

def test_summarize_empty():
    result = summarize_capture_data("")
    assert "No sample data" in result


def test_summarize_all_high():
    # sigrok bits format: "CH:11111111 11111111 ..."
    raw = (
        "libsigrok 0.5.2\n"
        "Acquisition with 2/16 channels at 1 MHz\n"
        + "\n".join([f"A0:11111111", f"A1:11111111"] * 10)
    )
    result = summarize_capture_data(raw)
    assert "80 samples" in result  # 10 lines * 8 bits each
    assert "2 channels" in result
    assert "always high" in result


def test_summarize_mixed():
    # Build sigrok-style bits output with known patterns
    # A0: alternating 10101010, A1: all high, A2: all low, A3: mostly low with edges
    lines = [
        "libsigrok 0.5.2",
        "Acquisition with 4/16 channels at 1 MHz",
    ]
    for _ in range(10):
        lines.append("A0:10101010")
        lines.append("A1:11111111")
        lines.append("A2:00000000")
        lines.append("A3:10000000")
    raw = "\n".join(lines)

    result = summarize_capture_data(raw)
    assert "80 samples" in result  # 10 lines * 8 bits
    assert "4 channels" in result
    assert "always high" in result   # A1
    assert "always low" in result    # A2
    assert "active" in result         # A0 and A3
