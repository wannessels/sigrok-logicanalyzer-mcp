# Decode Efficiency Design

## Problem

The `decode_protocol` tool returns raw sigrok-cli output which is extremely verbose:
- 11,968 lines (127KB) for 308 I2C transactions
- Individual bit annotations (0, 1, 0, 1...) dominate the output
- Even with annotation filters, 1,534 lines (30KB) remains too much for LLMs
- Requires two tool calls (capture + decode) for the most common workflow

## Design

### 1. New `capture_and_decode` tool

Single tool call for the most common workflow: capture signals and decode a protocol.

Parameters:
- `protocol`: decoder name (i2c, spi, uart, etc.)
- `channel_mapping`: signal-to-channel mapping (e.g. "sda=A0,scl=A1")
- `sample_rate`: default "1m"
- `num_samples` / `duration_ms`: capture size
- `channels`: channel selection
- `triggers`: trigger conditions
- `wait_trigger`: suppress pre-trigger data
- `trigger_timeout`: timeout when using triggers, default 30s
- `driver`: default "zeroplus-logic-cube"
- `options`: decoder options (e.g. "baudrate=115200")
- `detail`: "summary" (default) or "raw"
- `description`: optional label

Returns compact transaction summary by default, full annotations with detail="raw".
Always saves .sr file and raw decode output for later retrieval.

### 2. Improved `decode_protocol` tool

Add `detail` parameter: "summary" (default) or "raw".
- "summary": smart annotation filter + transaction grouping
- "raw": full sigrok-cli output (existing behavior)

Cache raw decode output alongside .sr files for re-use.

### 3. Smart annotation filters

Auto-apply `-A` filters for known protocols to strip individual bit annotations:
- i2c: `-A i2c=start:stop:ack:nack:address-read:address-write:data-read:data-write`
- spi: `-A spi=mosi-data:miso-data`
- uart: `-A uart=tx-data:rx-data`
- Other protocols: no filter (pass through as-is)

### 4. Transaction grouping formatters

Parse filtered decode output into compact transaction summaries per protocol.

**I2C example:**
```
I2C: 308 transactions, 1 device (0x59) | 131071 samples @ 1MHz

#001  W 0x59: [0B 00]
#002  W 0x59: [00] | R 0x59: [00]
#003  W 0x59: [0B A7]
```

**SPI example:**
```
SPI: 45 transfers | 8192 samples @ 10MHz

#001  MOSI>[A0 00 00] MISO<[FF 3C 80]
#002  MOSI>[A1 55] MISO<[FF FF]
```

**UART example:**
```
UART @ 115200: 256 bytes | 50000 samples @ 1MHz

TX> "Hello World\r\n"
RX< [06]
TX> "AT+STATUS\r\n"
```

**Unknown protocols:** fall back to filtered line-per-annotation output.

### 5. Trigger timeout

The `capture` and `capture_and_decode` tools accept `trigger_timeout` (default 30s).
This replaces the hardcoded 60s timeout when triggers are used.
Without triggers, timeout is computed from duration_ms or defaults to 30s.

### 6. CaptureStore changes

Store raw decode output alongside captures:
- `cap_001.sr` - capture file (existing)
- `cap_001_i2c_raw.txt` - cached raw decode output (new)

`decode_protocol` checks for cached output before re-running sigrok-cli.

## Implementation Order

1. Add `trigger_timeout` to `capture` tool and `sigrok_cli.run_capture`
2. Add annotation filter presets for known protocols in `sigrok_cli.py`
3. Add transaction grouping formatters in `formatters.py` (I2C, SPI, UART)
4. Add decode result caching to CaptureStore
5. Add `detail` parameter to `decode_protocol`
6. Add `capture_and_decode` tool
7. Update tests
