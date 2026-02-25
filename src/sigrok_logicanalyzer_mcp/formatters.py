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


def format_can_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Group filtered CAN annotations into compact frame summaries.

    Expects output with annotation filter:
      can=sof:eof:id:ext-id:full-id:ide:rtr:dlc:data:warnings

    Returns lines like:
        #001  ID=0x000 [F0 00 00 1F C0 00 00] DLC=7
        #002  ID=0x000 DLC=0
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No CAN data decoded."

    frames: list[str] = []
    current_id = ""
    current_ext_id = ""
    current_full_id = ""
    current_dlc = ""
    current_rtr = ""
    current_data: list[str] = []
    in_frame = False

    def _flush():
        nonlocal current_id, current_ext_id, current_full_id, current_dlc
        nonlocal current_rtr, current_data, in_frame
        if not in_frame:
            return
        # Use full ID for extended frames, standard ID otherwise
        if current_full_id:
            id_str = f"ID=0x{current_full_id}"
        elif current_id:
            id_str = f"ID=0x{current_id}"
        else:
            id_str = "ID=?"
        parts = [id_str]
        if current_data:
            parts.append(f"[{' '.join(current_data)}]")
        if current_dlc:
            parts.append(f"DLC={current_dlc}")
        if current_rtr == "remote frame":
            parts.append("RTR")
        frames.append(" ".join(parts))
        current_id = current_ext_id = current_full_id = ""
        current_dlc = current_rtr = ""
        current_data = []
        in_frame = False

    for ann in annotations:
        if ann == "Start of frame":
            _flush()
            in_frame = True
        elif ann == "End of frame":
            _flush()
        elif ann.startswith("Identifier:") and "extension" not in ann:
            # "Identifier: 255 (0xff)"
            m = re.search(r'\(0x([0-9a-fA-F]+)\)', ann)
            if m:
                current_id = m.group(1)
        elif ann.startswith("Full Identifier:"):
            m = re.search(r'\(0x([0-9a-fA-F]+)\)', ann)
            if m:
                current_full_id = m.group(1)
        elif ann.startswith("Data length code:"):
            current_dlc = ann.split(": ", 1)[1].strip()
        elif ann.startswith("Remote transmission request:"):
            current_rtr = ann.split(": ", 1)[1].strip()
        elif ann.startswith("Data byte"):
            val = ann.split(": ", 1)[1].strip()
            if val.startswith("0x"):
                val = val[2:]
            current_data.append(val.upper())

    _flush()

    total = len(frames)
    lines = [f"CAN: {total} frames", ""]
    for i, f in enumerate(frames[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {f}")
    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more frames)")
    return "\n".join(lines)


def format_onewire_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Group filtered 1-Wire network annotations into transaction summaries.

    Expects output with annotation filter: onewire_network
    Lines like:
        onewire_network-1: Reset/presence: true
        onewire_network-1: ROM command: 0x55 'Match ROM'
        onewire_network-1: ROM: 0x6700000003a6a842
        onewire_network-1: Data: 0xbe
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No 1-Wire data decoded."

    transactions: list[str] = []
    roms: Counter[str] = Counter()
    current_cmd = ""
    current_rom = ""
    current_data: list[str] = []

    def _flush():
        nonlocal current_cmd, current_rom, current_data
        if current_cmd or current_data:
            parts = []
            if current_cmd:
                parts.append(current_cmd)
            if current_rom:
                parts.append(f"ROM={current_rom}")
            if current_data:
                parts.append(f"[{' '.join(current_data)}]")
            transactions.append(" ".join(parts) if parts else "Reset")
        current_cmd = ""
        current_rom = ""
        current_data = []

    for ann in annotations:
        if ann.startswith("Reset/presence"):
            _flush()
        elif ann.startswith("ROM command:"):
            # "ROM command: 0x55 'Match ROM'"
            m = re.search(r"'(.+)'", ann)
            current_cmd = m.group(1) if m else ann.split(": ", 1)[1]
        elif ann.startswith("ROM:"):
            current_rom = ann.split(": ", 1)[1].strip()
            roms[current_rom] += 1
        elif ann.startswith("Data:"):
            val = ann.split(": ", 1)[1].strip()
            if val.startswith("0x"):
                val = val[2:]
            current_data.append(val.upper())

    _flush()

    total = len(transactions)
    rom_summary = ", ".join(roms.keys()) if roms else "none"
    lines = [f"1-Wire: {total} transactions, ROM {rom_summary}", ""]
    for i, txn in enumerate(transactions[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {txn}")
    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more transactions)")
    return "\n".join(lines)


def format_mdio_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Format filtered MDIO annotations into compact read/write summaries.

    Expects output with annotation filter: mdio=decode
    Lines like:
        mdio-1: READ:  3000 PHYAD: 01 REGAD: 00
        mdio-1: WRITE: 8000 PHYAD: 01 REGAD: 00
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No MDIO data decoded."

    operations: list[str] = []
    for ann in annotations:
        if ann.startswith("READ:") or ann.startswith("WRITE:"):
            parts = ann.split()
            # parts: ['READ:', '3000', 'PHYAD:', '01', 'REGAD:', '00']
            op = parts[0].rstrip(":")
            data = parts[1] if len(parts) > 1 else "?"
            phy = parts[3] if len(parts) > 3 else "?"
            reg = parts[5] if len(parts) > 5 else "?"
            arrow = "->" if op == "READ" else "<-"
            operations.append(f"{op:<5} PHY={phy} REG={reg} {arrow} 0x{data}")

    total = len(operations)
    lines = [f"MDIO: {total} operations", ""]
    for i, op in enumerate(operations[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {op}")
    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more operations)")
    return "\n".join(lines)


def format_usb_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Group filtered USB packet annotations, skipping SOFs.

    Expects output with annotation filter: usb_packet
    Groups token (IN/OUT/SETUP) + data (DATA0/DATA1) + handshake (ACK/NAK/STALL).
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No USB data decoded."

    transactions: list[str] = []
    sof_count = 0
    current_parts: list[str] = []

    def _flush():
        nonlocal current_parts
        if current_parts:
            transactions.append(" ".join(current_parts))
        current_parts = []

    for ann in annotations:
        # Skip low-level fields
        if ann.startswith("SYNC:") or ann.startswith("CRC") or ann.startswith("PID:") or ann.startswith("Frame:"):
            continue
        # SOF summary line: "SOF 1128"
        if ann.startswith("SOF "):
            sof_count += 1
            continue
        # Token packets: "IN ADDR 2 EP 1", "OUT ADDR 0 EP 0", "SETUP ADDR 0 EP 0"
        if ann.startswith("IN ") or ann.startswith("OUT ") or ann.startswith("SETUP "):
            _flush()
            current_parts.append(ann)
        # Data packets: "DATA0 [ 00 01 00 00 ]"
        elif ann.startswith("DATA0") or ann.startswith("DATA1"):
            current_parts.append(ann)
        # Handshake
        elif ann in ("ACK", "NAK", "STALL"):
            current_parts.append(ann)
            _flush()

    _flush()

    total = len(transactions)
    lines = [f"USB: {total} transactions ({sof_count} SOFs filtered)", ""]
    for i, txn in enumerate(transactions[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {txn}")
    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more transactions)")
    return "\n".join(lines)


def format_dcf77_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Format filtered DCF77 annotations into a time/date summary.

    Expects output with annotation filter:
      dcf77=minute:hour:day:day-of-week:month:year
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No DCF77 data decoded."

    minutes = hours = day = dow = month = year = ""
    for ann in annotations:
        if ann.startswith("Minutes:"):
            minutes = ann.split(": ", 1)[1]
        elif ann.startswith("Hours:"):
            hours = ann.split(": ", 1)[1]
        elif ann.startswith("Day:"):
            day = ann.split(": ", 1)[1]
        elif ann.startswith("Day of week:"):
            dow = ann.split(": ", 1)[1]
        elif ann.startswith("Month:"):
            month = ann.split(": ", 1)[1]
        elif ann.startswith("Year:"):
            year = ann.split(": ", 1)[1]

    lines = ["DCF77: Time decoded", ""]
    if dow:
        lines.append(f"Day of week: {dow}")
    if year and month and day:
        lines.append(f"Date: 20{year}-{month.split()[0]:>02}-{day:>02}")
    if hours and minutes:
        lines.append(f"Time: {hours}:{minutes:>02}")
    return "\n".join(lines)


def format_am230x_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Format filtered AM230x (DHT) annotations into sensor readings.

    Expects output with annotation filter: am230x=humidity:temperature:checksum
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No AM230x data decoded."

    readings: list[str] = []
    humidity = temperature = checksum = ""
    for ann in annotations:
        if ann.startswith("Humidity:"):
            humidity = ann.split(": ", 1)[1]
        elif ann.startswith("Temperature:"):
            temperature = ann.split(": ", 1)[1]
        elif ann.startswith("Checksum:"):
            checksum = ann.split(": ", 1)[1]
            parts = []
            if temperature:
                parts.append(f"Temp={temperature}")
            if humidity:
                parts.append(f"Humidity={humidity}")
            if checksum:
                parts.append(f"Checksum={checksum}")
            readings.append(" ".join(parts))
            humidity = temperature = checksum = ""

    total = len(readings)
    lines = [f"AM230x: {total} readings", ""]
    for i, r in enumerate(readings[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {r}")
    return "\n".join(lines)


def format_avr_isp_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Format filtered AVR ISP annotations into operation summaries.

    Expects output with annotation filter: avr_isp
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No AVR ISP data decoded."

    operations: list[str] = []
    device = ""
    for ann in annotations:
        if ann.startswith("Device:"):
            device = ann.split(": ", 1)[1]
        operations.append(ann)

    # Deduplicate consecutive identical operations
    deduped: list[str] = []
    for op in operations:
        if not deduped or deduped[-1] != op:
            deduped.append(op)

    total = len(deduped)
    header = f"AVR ISP: {total} operations"
    if device:
        header += f", device: {device}"
    lines = [header, ""]
    for i, op in enumerate(deduped[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {op}")
    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more operations)")
    return "\n".join(lines)


def format_spiflash_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Format filtered SPI Flash annotations into command summaries.

    Expects output with annotation filter: spiflash
    Keeps only the summary "Read data (addr ...)" lines and command lines.
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No SPI Flash data decoded."

    operations: list[str] = []
    for ann in annotations:
        # Keep summary read lines and command lines, skip address bits and raw data
        if ann.startswith("Read data (addr") or ann.startswith("Write data (addr"):
            # "Read data (addr 0x117c00, 256 bytes): 6f 72 ..."
            # Truncate the data portion
            parts = ann.split("): ", 1)
            operations.append(parts[0] + ")")
        elif ann.startswith("Command:"):
            operations.append(ann)
        elif ann.startswith("Address:"):
            continue  # skip, included in summary
        elif ann.startswith("Address bits"):
            continue
        elif ann.startswith("Data ("):
            continue  # skip raw data count

    # Deduplicate: Command lines followed by their summary
    deduped: list[str] = []
    for op in operations:
        if op.startswith("Command:") and deduped and deduped[-1] == op:
            continue
        deduped.append(op)

    total = len(deduped)
    lines = [f"SPI Flash: {total} operations", ""]
    for i, op in enumerate(deduped[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {op}")
    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more operations)")
    return "\n".join(lines)


def format_sdcard_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Format filtered SD Card annotations into command summaries.

    Expects output with annotation filter covering command classes.
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No SD Card data decoded."

    # Keep only meaningful annotations (commands, replies, card status)
    operations: list[str] = []
    for ann in annotations:
        if re.match(r'^[01]$', ann):
            continue  # skip raw bits
        operations.append(ann)

    total = len(operations)
    lines = [f"SD Card: {total} annotations", ""]
    for i, op in enumerate(operations[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {op}")
    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more annotations)")
    return "\n".join(lines)


def format_z80_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Format filtered Z80 annotations into instruction/memory operation summaries.

    Expects output with annotation filter: z80=memrd:memwr:iord:iowr:instr
    Note: Z80 decode may need debugging for channel mapping.
    """
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No Z80 data decoded."

    total = len(annotations)
    lines = [f"Z80: {total} operations", ""]
    for i, ann in enumerate(annotations[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {ann}")
    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more operations)")
    return "\n".join(lines)


def format_arm_itm_transactions(raw_output: str, max_transactions: int = 500) -> str:
    """Format ARM ITM annotations. Untested — ARM ITM stacks on UART."""
    annotations = _parse_annotations(raw_output)
    if not annotations:
        return "No ARM ITM data decoded."

    total = len(annotations)
    lines = [f"ARM ITM: {total} annotations", ""]
    for i, ann in enumerate(annotations[:max_transactions]):
        lines.append(f"#{i + 1:03d}  {ann}")
    if total > max_transactions:
        lines.append(f"\n... ({total - max_transactions} more annotations)")
    return "\n".join(lines)


# Map protocol names to their transaction formatter
_TRANSACTION_FORMATTERS = {
    "i2c": format_i2c_transactions,
    "spi": format_spi_transactions,
    "uart": format_uart_transactions,
    "can": format_can_transactions,
    "onewire_network": format_onewire_transactions,
    "mdio": format_mdio_transactions,
    "usb_packet": format_usb_transactions,
    "dcf77": format_dcf77_transactions,
    "am230x": format_am230x_transactions,
    "avr_isp": format_avr_isp_transactions,
    "spiflash": format_spiflash_transactions,
    "sdcard_sd": format_sdcard_transactions,
    "z80": format_z80_transactions,
    "arm_itm": format_arm_itm_transactions,  # untested
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
