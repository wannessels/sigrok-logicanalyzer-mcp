"""Tests for formatters.py."""

from sigrok_logicanalyzer_mcp.formatters import (
    format_decoded_protocol,
    format_decoded_summary,
    format_i2c_transactions,
    format_spi_transactions,
    format_uart_transactions,
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


# ---------------------------------------------------------------------------
# format_i2c_transactions
# ---------------------------------------------------------------------------

def test_i2c_transactions_empty():
    result = format_i2c_transactions("")
    assert "No I2C data" in result


def test_i2c_transactions_write():
    raw = (
        "i2c-1: Start\n"
        "i2c-1: Write\n"
        "i2c-1: Address write: 50\n"
        "i2c-1: ACK\n"
        "i2c-1: Data write: 0B\n"
        "i2c-1: ACK\n"
        "i2c-1: Data write: 00\n"
        "i2c-1: ACK\n"
        "i2c-1: Stop\n"
    )
    result = format_i2c_transactions(raw)
    assert "1 transactions" in result
    assert "0x50" in result
    assert "W 0x50: [0B 00]" in result


def test_i2c_transactions_write_then_read():
    raw = (
        "i2c-1: Start\n"
        "i2c-1: Write\n"
        "i2c-1: Address write: 59\n"
        "i2c-1: ACK\n"
        "i2c-1: Data write: 00\n"
        "i2c-1: ACK\n"
        "i2c-1: Start repeat\n"
        "i2c-1: Read\n"
        "i2c-1: Address read: 59\n"
        "i2c-1: ACK\n"
        "i2c-1: Data read: FF\n"
        "i2c-1: NACK\n"
        "i2c-1: Stop\n"
    )
    result = format_i2c_transactions(raw)
    assert "1 transactions" in result
    assert "W 0x59: [00] | R 0x59: [FF]" in result


def test_i2c_transactions_multiple():
    raw = (
        "i2c-1: Start\n"
        "i2c-1: Write\n"
        "i2c-1: Address write: 59\n"
        "i2c-1: ACK\n"
        "i2c-1: Data write: 0B\n"
        "i2c-1: ACK\n"
        "i2c-1: Stop\n"
        "i2c-1: Start\n"
        "i2c-1: Write\n"
        "i2c-1: Address write: 59\n"
        "i2c-1: ACK\n"
        "i2c-1: Data write: A7\n"
        "i2c-1: ACK\n"
        "i2c-1: Stop\n"
    )
    result = format_i2c_transactions(raw)
    assert "2 transactions" in result
    assert "#001" in result
    assert "#002" in result


def test_i2c_transactions_truncated():
    # Build many transactions
    lines = []
    for _ in range(10):
        lines.extend([
            "i2c-1: Start",
            "i2c-1: Write",
            "i2c-1: Address write: 50",
            "i2c-1: ACK",
            "i2c-1: Data write: FF",
            "i2c-1: ACK",
            "i2c-1: Stop",
        ])
    raw = "\n".join(lines)
    result = format_i2c_transactions(raw, max_transactions=3)
    assert "10 transactions" in result
    assert "#003" in result
    assert "#004" not in result
    assert "7 more" in result


# ---------------------------------------------------------------------------
# format_uart_transactions
# ---------------------------------------------------------------------------

def test_uart_transactions_empty():
    result = format_uart_transactions("")
    assert "No UART data" in result


def test_uart_transactions_tx_rx():
    raw = (
        "uart-1: TX data: 48\n"
        "uart-1: TX data: 69\n"
        "uart-1: RX data: 06\n"
    )
    result = format_uart_transactions(raw)
    assert "3 bytes" in result
    assert "2 segments" in result
    assert "TX>" in result
    assert "RX<" in result
    assert "48 69" in result
    assert '"Hi"' in result


# ---------------------------------------------------------------------------
# format_spi_transactions
# ---------------------------------------------------------------------------

def test_spi_transactions_empty():
    result = format_spi_transactions("")
    assert "No SPI data" in result


# ---------------------------------------------------------------------------
# format_decoded_summary
# ---------------------------------------------------------------------------

def test_decoded_summary_i2c_uses_formatter():
    raw = (
        "i2c-1: Start\n"
        "i2c-1: Write\n"
        "i2c-1: Address write: 50\n"
        "i2c-1: ACK\n"
        "i2c-1: Data write: FF\n"
        "i2c-1: ACK\n"
        "i2c-1: Stop\n"
    )
    result = format_decoded_summary(raw, "i2c")
    assert "W 0x50: [FF]" in result


def test_decoded_summary_unknown_falls_back():
    raw = "custom-1: Something\ncustom-1: Other\n"
    result = format_decoded_summary(raw, "custom_decoder")
    assert "2 annotations" in result
