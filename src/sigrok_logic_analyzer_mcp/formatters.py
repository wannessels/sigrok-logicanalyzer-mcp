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
    - Total samples
    - Per-channel activity (edge counts, percentage high)
    """
    lines = raw_output.strip().splitlines()
    if not lines:
        return "No sample data to summarize."

    total_samples = len(lines)

    # For bits format, each line is something like "10010011" or "1001 0011"
    # Determine channel count from first line
    first_line = lines[0].replace(" ", "")
    num_channels = len(first_line)

    if num_channels == 0:
        return f"Total samples: {total_samples} (unable to parse channel data)"

    # Per-channel stats
    high_counts = [0] * num_channels
    edge_counts = [0] * num_channels
    prev_bits: list[str | None] = [None] * num_channels

    for line in lines:
        bits = line.replace(" ", "")
        if len(bits) != num_channels:
            continue
        for ch in range(num_channels):
            b = bits[ch]
            if b == "1":
                high_counts[ch] += 1
            if prev_bits[ch] is not None and b != prev_bits[ch]:
                edge_counts[ch] += 1
            prev_bits[ch] = b

    summary_lines = [
        f"Capture summary: {total_samples} samples, {num_channels} channels",
        "",
        f"{'Channel':<10} {'High %':>8} {'Edges':>8} {'Activity':>10}",
        "-" * 40,
    ]

    for ch in range(num_channels):
        pct_high = (high_counts[ch] / total_samples * 100) if total_samples > 0 else 0
        activity = "active" if edge_counts[ch] > 0 else "static"
        if edge_counts[ch] == 0:
            if high_counts[ch] == total_samples:
                activity = "always high"
            elif high_counts[ch] == 0:
                activity = "always low"
        summary_lines.append(
            f"CH{ch:<8} {pct_high:>7.1f}% {edge_counts[ch]:>8} {activity:>10}"
        )

    return "\n".join(summary_lines)
