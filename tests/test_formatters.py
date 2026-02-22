"""Tests for formatters.py."""

from sigrok_mcp.formatters import (
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
    raw = "\n".join(["11"] * 100)
    result = summarize_capture_data(raw)
    assert "100 samples" in result
    assert "2 channels" in result
    assert "always high" in result


def test_summarize_mixed():
    # 4-channel data: ch0 toggles, ch1 always high, ch2 always low, ch3 toggles
    samples = []
    for i in range(100):
        ch0 = "1" if i % 2 == 0 else "0"
        ch1 = "1"
        ch2 = "0"
        ch3 = "1" if i % 10 == 0 else "0"
        samples.append(f"{ch0}{ch1}{ch2}{ch3}")
    raw = "\n".join(samples)

    result = summarize_capture_data(raw)
    assert "100 samples" in result
    assert "4 channels" in result
    assert "always high" in result  # ch1
    assert "always low" in result   # ch2
    assert "active" in result        # ch0 and ch3
