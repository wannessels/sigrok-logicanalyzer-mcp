"""MCP server for sigrok logic analyzers.

Exposes logic analyzer functionality (capture, decode, analyze) as MCP tools
for use with Claude Code or other MCP clients. Uses stdio transport.

Usage:
    python -m sigrok_mcp.server
    # or via the entry point:
    sigrok-mcp
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP, Context

from sigrok_mcp.capture_store import CaptureStore, CaptureNotFoundError
from sigrok_mcp import sigrok_cli
from sigrok_mcp.formatters import (
    format_decoded_protocol,
    format_raw_samples,
    summarize_capture_data,
)


# ---------------------------------------------------------------------------
# Lifespan — initializes and tears down the CaptureStore
# ---------------------------------------------------------------------------

@dataclass
class AppContext:
    store: CaptureStore


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    store = CaptureStore()
    try:
        yield AppContext(store=store)
    finally:
        store.cleanup()


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "sigrok",
    instructions=(
        "Logic analyzer server for embedded debugging. "
        "Use scan_devices to find hardware, capture to acquire signals, "
        "then decode_protocol to analyze I2C/SPI/UART traffic. "
        "Captures are referenced by ID (e.g. cap_001) across tool calls."
    ),
    lifespan=app_lifespan,
)


def _get_store(ctx: Context) -> CaptureStore:
    """Extract the CaptureStore from the lifespan context."""
    return ctx.request_context.lifespan_context.store


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def scan_devices(
    driver: str = "zeroplus-logic-cube",
) -> str:
    """Scan for connected sigrok-compatible logic analyzers.

    Args:
        driver: sigrok driver name. Default is "zeroplus-logic-cube" for
                ZeroPlus LAP-C devices. Other common drivers: "fx2lafw",
                "saleae-logic-pro", "dreamsourcelab-dslogic".
    """
    try:
        devices = await sigrok_cli.scan_devices(driver=driver)
    except sigrok_cli.DeviceNotFoundError as e:
        return str(e)
    except sigrok_cli.SigrokNotFoundError as e:
        return str(e)

    lines = [f"Found {len(devices)} device(s):"]
    for dev in devices:
        lines.append(f"  - {dev['description']}")
    return "\n".join(lines)


@mcp.tool()
async def capture(
    ctx: Context,
    sample_rate: str = "1m",
    num_samples: int | None = None,
    duration_ms: int | None = None,
    channels: str | None = None,
    triggers: str | None = None,
    wait_trigger: bool = False,
    driver: str = "zeroplus-logic-cube",
    description: str = "",
) -> str:
    """Capture digital signals from the logic analyzer.

    Acquires samples and saves them for later analysis with decode_protocol
    or get_raw_samples. Returns a capture ID to reference the data.

    Args:
        sample_rate: Sample rate — e.g. "1m" (1 MHz), "200k", "10m", "100m".
        num_samples: Number of samples to capture. Use this OR duration_ms.
        duration_ms: Capture duration in milliseconds. Use this OR num_samples.
        channels: Channel selection — e.g. "0-3" or "0,1,4,5". Default: all.
        triggers: Trigger conditions — e.g. "0=r" (ch0 rising edge),
                  "0=r,1=0" (ch0 rising AND ch1 low). Trigger types:
                  0=low, 1=high, r=rising, f=falling.
        wait_trigger: If true, only output data after the trigger fires.
        driver: sigrok driver name.
        description: Optional label for this capture.
    """
    store = _get_store(ctx)
    capture_id, file_path = store.new_capture(description=description)

    try:
        await sigrok_cli.run_capture(
            output_file=file_path,
            driver=driver,
            channels=channels,
            sample_rate=sample_rate,
            num_samples=num_samples,
            duration_ms=duration_ms,
            triggers=triggers,
            wait_trigger=wait_trigger,
        )
    except sigrok_cli.SigrokError as e:
        return f"Capture failed: {e}"

    size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

    parts = [
        f"Capture saved as {capture_id}",
        f"  File: {file_path} ({size} bytes)",
        f"  Sample rate: {sample_rate}",
    ]
    if channels:
        parts.append(f"  Channels: {channels}")
    if num_samples:
        parts.append(f"  Samples: {num_samples}")
    elif duration_ms:
        parts.append(f"  Duration: {duration_ms} ms")
    if triggers:
        parts.append(f"  Triggers: {triggers}")
    if description:
        parts.append(f"  Description: {description}")

    parts.append("")
    parts.append(
        "Use decode_protocol, get_raw_samples, or analyze_capture "
        f"with capture_id=\"{capture_id}\" to examine the data."
    )
    return "\n".join(parts)


@mcp.tool()
async def decode_protocol(
    ctx: Context,
    capture_id: str,
    protocol: str,
    channel_mapping: str | None = None,
    options: str | None = None,
    annotation_filter: str | None = None,
    max_results: int = 200,
) -> str:
    """Run a protocol decoder on a captured signal.

    This is the primary tool for embedded debugging — it decodes I2C, SPI,
    UART, and 100+ other protocols from captured digital signals.

    Args:
        capture_id: ID from a previous capture (e.g. "cap_001").
        protocol: Decoder name — common ones: "i2c", "spi", "uart", "1wire",
                  "jtag", "can", "lin", "usb_signalling", "sdcard_spi".
        channel_mapping: Map protocol signals to LA channels — e.g.
                         "sda=0,scl=1" for I2C, "mosi=0,miso=1,sck=2,cs=3"
                         for SPI, "rx=0" for UART.
        options: Decoder options — e.g. "baudrate=115200" for UART,
                 "cpol=0,cpha=0,bitorder=msb-first" for SPI.
        annotation_filter: Show only specific annotations — e.g. "uart=tx-data"
                           or "i2c=data-write".
        max_results: Maximum decoded frames to return (default 200).
    """
    store = _get_store(ctx)
    try:
        info = store.get(capture_id)
    except CaptureNotFoundError as e:
        return str(e)

    # Parse channel_mapping "sda=0,scl=1" -> {"sda": "0", "scl": "1"}
    ch_map = None
    if channel_mapping:
        ch_map = {}
        for pair in channel_mapping.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                ch_map[k.strip()] = v.strip()

    # Parse options "baudrate=115200,parity=none" -> {"baudrate": "115200", ...}
    opts = None
    if options:
        opts = {}
        for pair in options.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                opts[k.strip()] = v.strip()

    try:
        raw = await sigrok_cli.decode_protocol(
            input_file=info.file_path,
            decoder=protocol,
            decoder_options=opts,
            channel_mapping=ch_map,
            annotation_filter=annotation_filter,
        )
    except sigrok_cli.DecoderError as e:
        return f"Decoder error: {e}"

    return format_decoded_protocol(raw, max_lines=max_results)


@mcp.tool()
async def list_protocol_decoders(
    filter: str | None = None,
) -> str:
    """List available protocol decoders.

    sigrok includes 100+ protocol decoders for common embedded protocols.

    Args:
        filter: Optional search string to filter decoder list (case-insensitive).
    """
    try:
        decoders = await sigrok_cli.list_decoders()
    except sigrok_cli.SigrokError as e:
        return f"Error listing decoders: {e}"

    if filter:
        needle = filter.lower()
        decoders = [
            d for d in decoders
            if needle in d["id"].lower() or needle in d["description"].lower()
        ]

    if not decoders:
        return "No matching decoders found."

    lines = [f"Available decoders ({len(decoders)}):"]
    for d in decoders:
        lines.append(f"  {d['id']:<20} {d['description']}")
    return "\n".join(lines)


@mcp.tool()
async def get_raw_samples(
    ctx: Context,
    capture_id: str,
    start_sample: int = 0,
    num_samples: int = 1000,
    output_format: str = "bits",
    channels: str | None = None,
) -> str:
    """Get a window of raw sample data from a capture.

    Useful for examining signal timing, checking for glitches, or viewing
    raw bit patterns before/after a protocol event.

    Args:
        capture_id: ID from a previous capture (e.g. "cap_001").
        start_sample: Offset into the capture (0-indexed).
        num_samples: Number of samples to return (max 5000).
        output_format: "bits" (binary), "hex", or "csv".
        channels: Optional channel filter (e.g. "0-3").
    """
    store = _get_store(ctx)
    try:
        info = store.get(capture_id)
    except CaptureNotFoundError as e:
        return str(e)

    num_samples = min(num_samples, 5000)

    try:
        raw = await sigrok_cli.export_data(
            input_file=info.file_path,
            output_format=output_format,
            channels=channels,
        )
    except sigrok_cli.SigrokError as e:
        return f"Error reading samples: {e}"

    return format_raw_samples(raw, start_sample=start_sample, window_size=num_samples)


@mcp.tool()
async def analyze_capture(
    ctx: Context,
    capture_id: str,
    channels: str | None = None,
) -> str:
    """Get a high-level summary of a capture.

    Reports per-channel activity: edge counts, percentage high, whether the
    channel is active or static. Useful for quickly identifying which
    channels have signals and estimating bus frequencies.

    Args:
        capture_id: ID from a previous capture (e.g. "cap_001").
        channels: Optional channel filter (e.g. "0-3").
    """
    store = _get_store(ctx)
    try:
        info = store.get(capture_id)
    except CaptureNotFoundError as e:
        return str(e)

    try:
        raw = await sigrok_cli.export_data(
            input_file=info.file_path,
            output_format="bits",
            channels=channels,
        )
    except sigrok_cli.SigrokError as e:
        return f"Error analyzing capture: {e}"

    return summarize_capture_data(raw)


@mcp.tool()
async def list_captures(ctx: Context) -> str:
    """List all captures from this session.

    Shows capture IDs, file sizes, and descriptions.
    """
    store = _get_store(ctx)
    captures = store.list_captures()

    if not captures:
        return "No captures yet. Use the capture tool to acquire signals."

    lines = [f"Captures ({len(captures)}):"]
    for cap in captures:
        desc = f" — {cap['description']}" if cap.get("description") else ""
        lines.append(
            f"  {cap['id']}  {cap['size_bytes']:>8} bytes{desc}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
