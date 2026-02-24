"""Format sigrok output for LLM consumption.

Raw logic analyzer data can be huge (128K samples x 16 channels). These
functions transform it into concise, human-readable summaries that an LLM
can reason about effectively.
"""

from __future__ import annotations


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
