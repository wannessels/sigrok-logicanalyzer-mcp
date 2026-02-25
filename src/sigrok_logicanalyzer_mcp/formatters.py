"""Format sigrok output for LLM consumption.

Raw logic analyzer data can be huge (128K samples x 16 channels). These
functions transform it into concise, human-readable summaries that an LLM
can reason about effectively.
"""

from __future__ import annotations

import re
from collections import Counter


def format_decoded_protocol(raw_output: str, max_lines: int = 200) -> str:
    """Clean up and truncate protocol decoder output.

    Adds a summary header with the total transaction count and indicates
    if output was truncated.
    """
    lines = raw_output.strip().splitlines()
    total = len(lines)

    if total == 0:
        return "No protocol data decoded. Check channel mapping and decoder settings."

    if total <= max_lines:
        return f"Decoded {total} annotations:\n\n" + "\n".join(lines)

    truncated = lines[:max_lines]
    return (
        f"Decoded {total} annotations (showing first {max_lines}):\n\n"
        + "\n".join(truncated)
        + f"\n\n... ({total - max_lines} more lines truncated)"
    )


def format_raw_samples(
    raw_output: str,
    start_sample: int = 0,
    window_size: int = 1000,
) -> str:
    """Extract a window of raw samples from sigrok output.

    Works with bits/hex/csv output formats. Returns the requested window
    with sample number annotations.
    """
    lines = raw_output.strip().splitlines()
    total = len(lines)

    if total == 0:
        return "No sample data available."

    # Clamp window to available data
    start = max(0, min(start_sample, total - 1))
    end = min(start + window_size, total)
    window = lines[start:end]

    header = (
        f"Samples {start}-{end - 1} of {total} total "
        f"(showing {end - start} samples):\n"
    )

    return header + "\n".join(window)


def summarize_capture_data(raw_output: str) -> str:
    """Generate a high-level summary of captured sample data.

    Analyzes the bits-format output to report:
    - Total samples per channel
    - Per-channel activity (edge counts, percentage high)

    sigrok bits output looks like:
        libsigrok 0.5.2
        Acquisition with 2/16 channels at 1 MHz
        A0:11111111 00001111 ...
        A1:00000000 11110000 ...
        A0:11111111 00001111 ...
        ...
    Each line has a channel label prefix and groups of 8 bits separated by spaces.
    """
    lines = raw_output.strip().splitlines()
    if not lines:
        return "No sample data to summarize."

    # Parse sigrok bits format: collect bit strings per channel name
    channel_bits: dict[str, list[str]] = {}
    channel_order: list[str] = []

    for line in lines:
        # Match lines like "A0:11111111 00001111 ..."
        if ":" not in line:
            continue
        label, _, data = line.partition(":")
        label = label.strip()
        data = data.strip()
        # Skip non-data lines (e.g. header lines with colons)
        if not data or not all(c in "01 " for c in data):
            continue
        bits = data.replace(" ", "")
        if not bits:
            continue
        if label not in channel_bits:
            channel_bits[label] = []
            channel_order.append(label)
        channel_bits[label].append(bits)

    if not channel_bits:
        return "No sample data to summarize (could not parse channel data)."

    summary_lines = []

    # Compute per-channel stats
    header_parts = []
    for ch_name in channel_order:
        all_bits = "".join(channel_bits[ch_name])
        total = len(all_bits)
        high_count = all_bits.count("1")
        # Count edges (transitions)
        edge_count = 0
        for i in range(1, total):
            if all_bits[i] != all_bits[i - 1]:
                edge_count += 1
        header_parts.append((ch_name, total, high_count, edge_count))

    total_samples = header_parts[0][1] if header_parts else 0

    summary_lines.append(
        f"Capture summary: {total_samples} samples, {len(channel_order)} channels"
    )
    summary_lines.append("")
    summary_lines.append(
        f"{'Channel':<10} {'High %':>8} {'Edges':>8}   {'Activity'}"
    )
    summary_lines.append("-" * 45)

    for ch_name, total, high_count, edge_count in header_parts:
        pct_high = (high_count / total * 100) if total > 0 else 0
        if edge_count > 0:
            activity = "active"
        elif high_count == total:
            activity = "always high"
        elif high_count == 0:
            activity = "always low"
        else:
            activity = "static"
        summary_lines.append(
            f"{ch_name:<10} {pct_high:>7.1f}% {edge_count:>8}   {activity}"
        )

    return "\n".join(summary_lines)


# ---------------------------------------------------------------------------
# Transaction grouping formatters
# ---------------------------------------------------------------------------

def _parse_annotations(raw_output: str) -> list[str]:
    """Strip the decoder prefix (e.g. 'i2c-1: ') and return annotation values."""
    annotations = []
    for line in raw_output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Lines look like "i2c-1: Start" or "uart-1: 48"
        _, _, value = line.partition(": ")
        if value:
            annotations.append(value)
    return annotations


def format_i2c_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Group filtered I2C annotations into compact transaction summaries.

    Expects output from sigrok-cli with the I2C summary annotation filter
    (start, repeat-start, stop, ack, nack, address-read/write, data-read/write).

    Returns lines like:
        #001  W 0x59: [0B 00]
        #002  W 0x59: [00] | R 0x59: [00]
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No I2C data decoded."

    transactions: list[str] = []
    addresses: Counter[str] = Counter()
    current_segments: list[str] = []
    current_dir = ""
    current_addr = ""
    current_data: list[str] = []

    def _flush_segment():
        nonlocal current_dir, current_addr, current_data
        if current_addr:
            data_str = " ".join(current_data) if current_data else ""
            seg = f"{current_dir} 0x{current_addr}"
            if data_str:
                seg += f": [{data_str}]"
            current_segments.append(seg)
        current_dir = ""
        current_addr = ""
        current_data = []

    def _flush_transaction():
        nonlocal current_segments
        if current_segments:
            transactions.append(" | ".join(current_segments))
        current_segments = []

    for ann in annotations:
        if ann == "Start":
            _flush_segment()
            _flush_transaction()
        elif ann == "Start repeat":
            _flush_segment()
        elif ann == "Stop":
            _flush_segment()
            _flush_transaction()
        elif ann == "Write":
            current_dir = "W"
        elif ann == "Read":
            current_dir = "R"
        elif ann.startswith("Address write: "):
            current_addr = ann.split(": ", 1)[1]
            addresses[current_addr] += 1
        elif ann.startswith("Address read: "):
            current_addr = ann.split(": ", 1)[1]
            addresses[current_addr] += 1
        elif ann.startswith("Data write: "):
            current_data.append(ann.split(": ", 1)[1])
        elif ann.startswith("Data read: "):
            current_data.append(ann.split(": ", 1)[1])
        # ACK/NACK ignored for summary

    # Flush any remaining
    _flush_segment()
    _flush_transaction()

    total = len(transactions)
    addr_summary = ", ".join(
        f"0x{addr}" for addr, _ in addresses.most_common()
    )

    lines = [f"I2C: {total} transactions, devices: {addr_summary}", ""]

    for i, txn in enumerate(transactions[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {txn}")

    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more transactions)")

    return "\n".join(lines)


def format_spi_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Group filtered SPI annotations into compact transfer summaries.

    Expects output with mosi-data, miso-data, mosi-transfer, miso-transfer.

    Returns lines like:
        #001  MOSI>[A0 00 00] MISO<[FF 3C 80]
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No SPI data decoded."

    # SPI doesn't have start/stop framing like I2C. Group by transfer
    # annotations, or just pair up MOSI/MISO data bytes.
    transfers: list[str] = []
    mosi_bytes: list[str] = []
    miso_bytes: list[str] = []

    def _flush():
        nonlocal mosi_bytes, miso_bytes
        if mosi_bytes or miso_bytes:
            parts = []
            if mosi_bytes:
                parts.append(f"MOSI>[{' '.join(mosi_bytes)}]")
            if miso_bytes:
                parts.append(f"MISO<[{' '.join(miso_bytes)}]")
            transfers.append(" ".join(parts))
            mosi_bytes = []
            miso_bytes = []

    for ann in annotations:
        # Transfer annotations mark CS boundaries
        if ann.startswith("MOSI transfer") or ann.startswith("MISO transfer"):
            _flush()
        elif ann.startswith("MOSI data") or re.match(r'^[0-9A-Fa-f]{2}$', ann):
            # mosi-data annotations vary: sometimes "MOSI data: XX" or just "XX"
            val = ann.split(": ", 1)[1] if ": " in ann else ann
            mosi_bytes.append(val.upper())
        elif ann.startswith("MISO data"):
            val = ann.split(": ", 1)[1]
            miso_bytes.append(val.upper())

    _flush()

    total = len(transfers)
    lines = [f"SPI: {total} transfers", ""]

    for i, txn in enumerate(transfers[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {txn}")

    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more transfers)")

    return "\n".join(lines)


def format_uart_transactions(raw_output: str, max_bytes: int = 2000) -> str:
    """Group filtered UART annotations into TX/RX byte streams.

    Expects output with rx-data and tx-data annotations.

    Returns lines like:
        TX> 48 65 6C 6C 6F  "Hello"
        RX< 06              "."
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No UART data decoded."

    # Group consecutive TX or RX bytes
    segments: list[tuple[str, list[str]]] = []
    current_dir = ""
    current_bytes: list[str] = []

    for ann in annotations:
        # UART annotations: "TX data: XX" or "RX data: XX" or just hex value
        direction = ""
        value = ""
        if ann.startswith("TX data"):
            direction = "TX"
            value = ann.split(": ", 1)[1] if ": " in ann else ""
        elif ann.startswith("RX data"):
            direction = "RX"
            value = ann.split(": ", 1)[1] if ": " in ann else ""
        else:
            continue

        if direction != current_dir:
            if current_bytes:
                segments.append((current_dir, current_bytes))
            current_dir = direction
            current_bytes = []
        current_bytes.append(value.upper())

    if current_bytes:
        segments.append((current_dir, current_bytes))

    total_bytes = sum(len(s[1]) for s in segments)
    lines = [f"UART: {total_bytes} bytes in {len(segments)} segments", ""]

    byte_count = 0
    for direction, data in segments:
        if byte_count >= max_bytes:
            lines.append(f"\n... (truncated at {max_bytes} bytes)")
            break
        prefix = "TX>" if direction == "TX" else "RX<"
        hex_str = " ".join(data)
        # Try to render as ASCII where possible
        ascii_str = ""
        try:
            ascii_str = "".join(
                chr(int(b, 16)) if 0x20 <= int(b, 16) < 0x7F else "."
                for b in data
            )
        except ValueError:
            pass
        if ascii_str:
            lines.append(f'{prefix} {hex_str}  "{ascii_str}"')
        else:
            lines.append(f"{prefix} {hex_str}")
        byte_count += len(data)

    return "\n".join(lines)


# Map protocol names to their transaction formatter
_TRANSACTION_FORMATTERS = {
    "i2c": format_i2c_transactions,
    "spi": format_spi_transactions,
    "uart": format_uart_transactions,
}


def format_decoded_summary(raw_output: str, protocol: str, max_transactions: int = 500) -> str:
    """Format decoded output as a compact transaction summary.

    Uses protocol-specific formatter if available, otherwise falls back
    to the generic line-based formatter.
    """
    formatter = _TRANSACTION_FORMATTERS.get(protocol)
    if formatter:
        return formatter(raw_output, max_transactions=max_transactions)
    return format_decoded_protocol(raw_output, max_lines=max_transactions)
