"""MCP server for sigrok logic analyzers.

Exposes logic analyzer functionality (capture, decode, analyze) as MCP tools
for use with Claude Code or other MCP clients. Uses stdio transport.

Usage:
    python -m sigrok_logicanalyzer_mcp.server
    # or via the entry point:
    sigrok-logicanalyzer-mcp
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP, Context

from sigrok_logicanalyzer_mcp.capture_store import CaptureStore, CaptureNotFoundError
from sigrok_logicanalyzer_mcp import sigrok_cli
from sigrok_logicanalyzer_mcp.formatters import (
    format_decoded_protocol,
    format_decoded_summary,
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
        "Use capture_and_decode for one-step capture + protocol analysis "
        "(I2C, SPI, UART, etc.). Use scan_devices to find hardware. "
        "Use decode_protocol to re-analyze a saved capture with different "
        "settings or detail='raw' for full annotations. "
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
    trigger_timeout: float = 30.0,
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
        channels: Channel selection — e.g. "A0-A7" or "A0,A1,B0,B1". Channel
                  names depend on the device (ZeroPlus uses A0-A7, B0-B7;
                  fx2lafw uses D0-D7). Default: all.
        triggers: Trigger conditions — e.g. "A0=0" (ch A0 low), "A0=1" (ch A0 high).
                  Supported types depend on device (ZeroPlus: 0=low, 1=high only).
        wait_trigger: If true, only output data after the trigger fires.
        trigger_timeout: Timeout in seconds when waiting for a trigger (default 30).
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
            trigger_timeout=trigger_timeout,
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
        f'with capture_id="{capture_id}" to examine the data.'
    )
    return "\n".join(parts)


def _parse_key_value_pairs(text: str) -> dict[str, str]:
    """Parse 'key=val,key=val' into a dict."""
    result = {}
    for pair in text.split(","):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            result[k.strip()] = v.strip()
    return result


async def _run_decode(
    store: CaptureStore,
    capture_id: str,
    protocol: str,
    channel_mapping: str | None,
    options: str | None,
    annotation_filter: str | None,
    detail: str,
) -> str:
    """Shared decode logic for decode_protocol and capture_and_decode."""
    try:
        info = store.get(capture_id)
    except CaptureNotFoundError as e:
        return str(e)

    ch_map = _parse_key_value_pairs(channel_mapping) if channel_mapping else None
    opts = _parse_key_value_pairs(options) if options else None

    is_summary = detail == "summary"

    # For summary mode, use smart annotation filter unless user overrides
    effective_filter = annotation_filter
    if is_summary and not annotation_filter:
        effective_filter = sigrok_cli.get_summary_annotation_filter(protocol)

    # Check cache for raw mode (summary always re-filters)
    if not is_summary:
        cached = store.get_cached_decode(capture_id, protocol)
        if cached and not annotation_filter and not options:
            return format_decoded_protocol(cached)

    try:
        raw = await sigrok_cli.decode_protocol(
            input_file=info.file_path,
            decoder=protocol,
            decoder_options=opts,
            channel_mapping=ch_map,
            annotation_filter=effective_filter,
        )
    except sigrok_cli.DecoderError as e:
        return f"Decoder error: {e}"

    # Cache the raw output
    store.cache_decode(capture_id, protocol, raw)

    if is_summary:
        return format_decoded_summary(raw, protocol)
    return format_decoded_protocol(raw)


@mcp.tool()
async def decode_protocol(
    ctx: Context,
    capture_id: str,
    protocol: str,
    channel_mapping: str | None = None,
    options: str | None = None,
    annotation_filter: str | None = None,
    detail: str = "summary",
) -> str:
    """Run a protocol decoder on a captured signal.

    This is the primary tool for embedded debugging — it decodes I2C, SPI,
    UART, and 100+ other protocols from captured digital signals.

    Args:
        capture_id: ID from a previous capture (e.g. "cap_001").
        protocol: Decoder name — common ones: "i2c", "spi", "uart", "1wire",
                  "jtag", "can", "lin", "usb_signalling", "sdcard_spi".
        channel_mapping: Map protocol signals to LA channels — e.g.
                         "sda=A0,scl=A1" for I2C, "mosi=A0,miso=A1,sck=A2,cs=A3"
                         for SPI, "rx=A0" for UART. Use the device's channel
                         names (run scan_devices to see available channels).
        options: Decoder options — e.g. "baudrate=115200" for UART,
                 "cpol=0,cpha=0,bitorder=msb-first" for SPI.
        annotation_filter: Show only specific annotations — e.g. "uart=tx-data"
                           or "i2c=data-write". Overrides the default summary filter.
        detail: "summary" (default) — compact transaction view, or
                "raw" — full sigrok-cli annotations.
    """
    store = _get_store(ctx)
    return await _run_decode(
        store,
        capture_id,
        protocol,
        channel_mapping,
        options,
        annotation_filter,
        detail,
    )


@mcp.tool()
async def capture_and_decode(
    ctx: Context,
    protocol: str,
    channel_mapping: str,
    sample_rate: str = "1m",
    num_samples: int | None = None,
    duration_ms: int | None = None,
    channels: str | None = None,
    triggers: str | None = None,
    wait_trigger: bool = False,
    trigger_timeout: float = 30.0,
    driver: str = "zeroplus-logic-cube",
    options: str | None = None,
    detail: str = "summary",
    description: str = "",
) -> str:
    """Capture signals and decode a protocol in one step.

    This is the fastest way to analyze a bus — captures data from the logic
    analyzer, runs a protocol decoder, and returns a compact transaction
    summary. The capture is saved for follow-up analysis.

    Args:
        protocol: Decoder name — "i2c", "spi", "uart", etc.
        channel_mapping: Map protocol signals to LA channels — e.g.
                         "sda=A0,scl=A1" for I2C, "mosi=A0,miso=A1,sck=A2,cs=A3"
                         for SPI, "rx=A0" for UART.
        sample_rate: Sample rate — e.g. "1m" (1 MHz), "200k", "10m".
        num_samples: Number of samples to capture. Use this OR duration_ms.
        duration_ms: Capture duration in milliseconds. Use this OR num_samples.
        channels: Channel selection — e.g. "A0,A1". Default: all.
        triggers: Trigger conditions — e.g. "A0=0" (ch A0 low).
                  Supported types depend on device (ZeroPlus: 0=low, 1=high).
        wait_trigger: If true, only output data after the trigger fires.
        trigger_timeout: Timeout in seconds when waiting for a trigger (default 30).
        driver: sigrok driver name.
        options: Decoder options — e.g. "baudrate=115200" for UART.
        detail: "summary" (default) — compact transaction view, or
                "raw" — full sigrok-cli annotations.
        description: Optional label for this capture.
    """
    store = _get_store(ctx)
    capture_id, file_path = store.new_capture(description=description)

    # 1. Capture
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
            trigger_timeout=trigger_timeout,
        )
    except sigrok_cli.SigrokError as e:
        return f"Capture failed: {e}"

    size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

    # 2. Decode
    decode_result = await _run_decode(
        store,
        capture_id,
        protocol,
        channel_mapping,
        options,
        None,
        detail,
    )

    # 3. Format response
    parts = [
        f"Capture {capture_id} ({size} bytes, {sample_rate} sample rate)",
    ]
    if description:
        parts[0] += f" — {description}"
    parts.append("")
    parts.append(decode_result)
    parts.append("")
    parts.append(
        f'Use decode_protocol with capture_id="{capture_id}" '
        f'for re-analysis or detail="raw" for full annotations.'
    )
    return "\n".join(parts)


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
            d
            for d in decoders
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
        channels: Optional channel filter (e.g. "A0-A3").
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
        channels: Optional channel filter (e.g. "A0-A3").
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
        lines.append(f"  {cap['id']}  {cap['size_bytes']:>8} bytes{desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
