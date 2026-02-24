# sigrok-logic-analyzer-mcp: Setup & Design

## Overview

An MCP (Model Context Protocol) server that gives Claude Code (or any MCP client) direct access to sigrok-compatible logic analyzers. Capture digital signals, decode protocols (I2C, SPI, UART, CAN, and 130+ others), and analyze timing -- all through tool calls.

Built for the ZeroPlus LAP-C 16128 but works with any sigrok-supported hardware.

## Architecture

```
MCP Client (Claude Code)
    |
    | stdio (JSON-RPC)
    v
server.py              FastMCP server, 6 tools
    |
    +-- capture_store.py    In-memory + .sr file storage, keyed by capture ID
    +-- sigrok_native.py    All hardware and decoding logic
    +-- formatters.py       Output shaping for LLM consumption
```

### sigrok_native.py -- the core

This module has three layers, each using the best available backend:

| Operation | Backend | Why |
|---|---|---|
| Device scanning, capture | `sigrok.core.classes` (libsigrok SWIG bindings) | Direct hardware access, numpy data in-process |
| Protocol decoding | `pysigrok` + `pysigrok-libsigrokdecode` | 130 decoders running natively in Python, no subprocess |
| File export (fallback) | `sigrok-cli` subprocess | Only used when in-memory data isn't available |

### Data flow

```
Hardware -> libsigrok SWIG -> numpy array (in-memory)
                                  |
                                  +-> CaptureStore (keeps data + .sr file)
                                  |
                                  +-> pysigrok decoders (native, in-process)
                                  |       |
                                  |       +-> Annotations (structured text)
                                  |
                                  +-> export_data_from_array (bits/hex/csv)
```

Captures are stored both as `.sr` files (for compatibility) and as in-memory numpy arrays (for fast native access). Each capture is assigned a short ID like `cap_001` that persists for the session.

## Design Decisions

### Native bindings over subprocess

The initial version used `sigrok-cli` for everything. This had several problems:
- Spawning a process for every operation adds latency
- Parsing CLI text output is fragile
- No access to raw sample data between capture and decode
- sigrok-cli must be installed system-wide

The current version uses libsigrok's SWIG Python bindings for hardware interaction and pysigrok for protocol decoding. sigrok-cli is only kept as a fallback for `.sr` file operations when in-memory data isn't available.

### pysigrok for protocol decoding

sigrok's original libsigrokdecode is a C library that hosts Python decoder scripts. It has no Python bindings of its own. pysigrok is a pure-Python reimplementation of the decoder infrastructure:
- `pysigrok` provides the `sigrokdecode` module with `Decoder`, `run_decoders()`, `cond_matches()`
- `pysigrok-libsigrokdecode` provides all 130 protocol decoder scripts, registered as entry points

To feed captured numpy data into decoders, `_NumpyInput` implements the pysigrok Input interface. It iterates sample-by-sample, evaluating wait conditions and emitting logic-level change events. `_AnnotationCollector` implements the Output interface to gather decoded annotations.

### In-memory data with packed integers

libsigrok captures data as `[num_samples, unit_size]` uint8 arrays where each bit position in each byte represents a channel. pysigrok decoders expect packed integer samples where bit N = channel N. `_data_to_packed_ints()` handles this conversion.

### CaptureStore with session-scoped IDs

Rather than passing file paths between tool calls, captures get short IDs (`cap_001`, `cap_002`). This is more natural for LLM conversation and avoids exposing filesystem details. The store keeps both the numpy array (for fast native operations) and the `.sr` file path (for fallback).

The store also tracks `sample_rate` alongside the data, since decoders need it for timing calculations.

### Output formatting for LLMs

Raw logic analyzer output can be enormous (128K samples x 16 channels). The formatters module shapes output for LLM consumption:
- `format_decoded_protocol`: Truncates long decoder output with a count header
- `format_raw_samples`: Windowed view with sample number context
- `summarize_capture_data`: Per-channel stats (edge counts, % high, active/static)

## MCP Tools

| Tool | Purpose |
|---|---|
| `scan_devices` | Find connected logic analyzers |
| `capture` | Acquire digital signals, returns a capture ID |
| `decode_protocol` | Run protocol decoders (I2C, SPI, UART, etc.) on a capture |
| `list_protocol_decoders` | List all 130+ available decoders with search |
| `get_raw_samples` | View raw bit/hex/csv data from a capture window |
| `analyze_capture` | Per-channel activity summary (edges, duty cycle) |
| `list_captures` | Show all captures in the current session |

## Setup

### Dependencies

```
pip install sigrok-logic-analyzer-mcp
```

This pulls in:
- `mcp` -- MCP server framework
- `numpy` -- sample data handling
- `pysigrok` + `pysigrok-libsigrokdecode` -- protocol decoding

For hardware capture, you also need the sigrok SWIG bindings (`python3-libsigrok` package or built from source). Without them, device scanning and capture won't work, but you can still decode `.sr` files.

### MCP client configuration

Add to your MCP client config (e.g. Claude Code `settings.json`):

```json
{
  "mcpServers": {
    "sigrok": {
      "command": "sigrok-logic-analyzer-mcp"
    }
  }
}
```

### Hardware setup (Linux)

For USB logic analyzers, add udev rules so non-root users can access the device:

```bash
# /etc/udev/rules.d/61-sigrok.rules
# ZeroPlus Logic Cube LAP-C
ATTRS{idVendor}=="0c12", ATTRS{idProduct}=="700e", MODE="0664", GROUP="plugdev"
```

Then: `sudo udevadm control --reload-rules && sudo udevadm trigger`

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

Tests cover:
- Parsing helpers (sample rate, channel specs, triggers)
- Data conversion (bits, hex, packed integers)
- Export formatting
- Device scanning and capture (mocked libsigrok)
- **Native protocol decoding** (real pysigrok decoders, end-to-end UART test)
- Decoder listing (real pysigrok entry points)
- sigrok-cli fallback paths (mocked subprocess)
