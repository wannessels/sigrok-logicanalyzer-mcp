# sigrok-logic-analyzer-mcp: Setup & Design

## Overview

An MCP (Model Context Protocol) server that gives Claude Code (or any MCP client) direct access to sigrok-compatible logic analyzers. Capture digital signals, decode protocols (I2C, SPI, UART, CAN, and 100+ others), and analyze timing -- all through tool calls.

Built for the ZeroPlus LAP-C 16128 but works with any sigrok-supported hardware.

This is the initial CLI-based branch. All sigrok interaction happens via `sigrok-cli` subprocess calls. See the `python-bindings` branch for the native Python bindings version with in-process decoding.

## Architecture

```
MCP Client (Claude Code)
    |
    | stdio (JSON-RPC)
    v
server.py              FastMCP server, 6 tools
    |
    +-- capture_store.py    .sr file storage, keyed by capture ID
    +-- sigrok_cli.py       All sigrok-cli subprocess calls
    +-- formatters.py       Output shaping for LLM consumption
```

### sigrok_cli.py -- the core

Every sigrok operation is a `sigrok-cli` subprocess call:

| Operation | sigrok-cli command |
|---|---|
| Device scanning | `sigrok-cli --driver <drv> --scan` |
| Capture | `sigrok-cli --driver <drv> --config samplerate=... --samples ... -o file.sr` |
| Protocol decoding | `sigrok-cli -i file.sr -P decoder:opts` |
| Decoder listing | `sigrok-cli --list-supported` |
| Data export | `sigrok-cli -i file.sr --output-format bits` |

All calls go through a single `_run()` helper that handles subprocess creation, timeout, and error parsing.

### Data flow

```
Hardware -> sigrok-cli -> .sr file (on disk)
                              |
                              +-> CaptureStore (tracks file path + ID)
                              |
                              +-> sigrok-cli -P (protocol decode)
                              |       |
                              |       +-> Text output (parsed)
                              |
                              +-> sigrok-cli --output-format (export)
```

All data passes through `.sr` files on disk. Each capture is assigned a short ID like `cap_001` that persists for the session.

## Design Decisions

### sigrok-cli as the sole backend

This branch uses sigrok-cli for all operations. The advantages:
- Simple: one dependency, well-documented CLI interface
- Portable: sigrok-cli packages exist for most Linux distros
- No build complexity: no SWIG bindings or native compilation needed

The disadvantages (addressed in the `python-bindings` branch):
- Subprocess overhead on every operation
- No access to raw sample data in-memory between capture and decode
- Fragile text parsing of CLI output
- sigrok-cli must be installed system-wide

### CaptureStore with session-scoped IDs

Rather than passing file paths between tool calls, captures get short IDs (`cap_001`, `cap_002`). This is more natural for LLM conversation and avoids exposing filesystem details. The store maps IDs to `.sr` file paths in a temp directory that's cleaned up when the server exits.

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
| `list_protocol_decoders` | List all available decoders with search |
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

You also need `sigrok-cli` installed system-wide:

```bash
# Debian/Ubuntu
apt install sigrok-cli

# macOS
brew install sigrok

# Fedora
dnf install sigrok-cli
```

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
- Output formatting (decoded protocol, raw samples, summaries)
- CaptureStore (ID generation, file tracking, cleanup)
- sigrok-cli calls (mocked subprocess for all operations)

## Branches

- **`claude/initial-commit-session_01Uw9XTMUCTQeDkk5rcEPiAt`** (this branch): CLI-based, uses `sigrok-cli` subprocess for everything
- **`python-bindings`**: Native Python bindings -- libsigrok SWIG for capture, pysigrok for in-process protocol decoding with 130 decoders, numpy data kept in memory
