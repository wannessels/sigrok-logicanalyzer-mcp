# Protocol Support, CI/CD, and Project Rename — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename project to sigrok-logicanalyzer-mcp, add GPL-3.0 license, add transaction formatters for all example protocols, add untested annotation filters for remaining decoders, replace mocked unit tests with sigrok-cli integration tests, add GitHub Actions CI/CD with PyPI OIDC publishing.

**Architecture:** Transaction formatters parse filtered sigrok-cli annotation output into compact summaries. Each protocol with an example .sr file gets a dedicated formatter function. Integration tests decode the bundled .sr fixtures with sigrok-cli and assert formatter output contains expected patterns. Remaining 95+ decoders get annotation filter entries marked untested.

**Tech Stack:** Python 3.10+, pytest, sigrok-cli, GitHub Actions, hatchling build, PyPI OIDC trusted publisher

---

### Task 1: Rename project

**Files:**
- Rename: `src/sigrok_logic_analyzer_mcp/` → `src/sigrok_logicanalyzer_mcp/`
- Modify: `pyproject.toml`
- Modify: all test files (update imports)

**Step 1: Rename the source directory**

```bash
git mv src/sigrok_logic_analyzer_mcp src/sigrok_logicanalyzer_mcp
```

**Step 2: Update pyproject.toml**

```toml
[project]
name = "sigrok-logicanalyzer-mcp"

[project.scripts]
sigrok-logicanalyzer-mcp = "sigrok_logicanalyzer_mcp.server:main"

[tool.hatch.build.targets.wheel]
packages = ["src/sigrok_logicanalyzer_mcp"]
```

**Step 3: Update all imports in source files**

Replace `sigrok_logic_analyzer_mcp` with `sigrok_logicanalyzer_mcp` in all `.py` files under `src/` and `tests/`.

**Step 4: Update DESIGN.md references**

**Step 5: Verify**

```bash
pip install -e ".[dev]" && python -c "from sigrok_logicanalyzer_mcp import server; print('OK')"
```

**Step 6: Commit**

```bash
git add -A && git commit -m "Rename project to sigrok-logicanalyzer-mcp"
```

---

### Task 2: Add GPL-3.0 license and complete pyproject.toml metadata

**Files:**
- Create: `LICENSE`
- Modify: `pyproject.toml`

**Step 1: Create LICENSE file**

Download GPL-3.0 text or write the standard header. Full GPL-3.0 text.

**Step 2: Update pyproject.toml with full metadata**

```toml
[project]
name = "sigrok-logicanalyzer-mcp"
version = "0.1.0"
description = "MCP server for sigrok logic analyzers — capture, decode, and analyze I2C/SPI/UART/CAN and 100+ protocols"
requires-python = ">=3.10"
license = "GPL-3.0-or-later"
authors = [
    { name = "Wannes Sels" },
]
keywords = ["sigrok", "logic-analyzer", "mcp", "protocol-decoder", "embedded"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering",
    "Topic :: Software Development :: Embedded Systems",
]

[project.urls]
Homepage = "https://github.com/wannessels/sigrok-mcp"
Repository = "https://github.com/wannessels/sigrok-mcp"
Issues = "https://github.com/wannessels/sigrok-mcp/issues"
```

**Step 3: Commit**

```bash
git add LICENSE pyproject.toml && git commit -m "Add GPL-3.0 license and complete project metadata"
```

---

### Task 3: Copy example .sr fixtures and remove mocked unit tests

**Files:**
- Create: `tests/fixtures/*.sr` (13 files, ~220KB)
- Delete: `tests/test_capture_store.py`
- Delete: `tests/test_formatters.py`
- Delete: `tests/test_sigrok_cli.py`

**Step 1: Copy .sr files from sigrok examples**

Copy these 13 files from `C:\Program Files\sigrok\sigrok-cli\examples\` to `tests/fixtures/`:
- am2301_1mhz.sr (5.8K)
- cmd23_cmd18.sr (636B)
- dcf77_120s.sr (97K)
- ds28ea00.sr (2.3K)
- hantek_6022be_powerup.sr (1.4K)
- isp_atmega88_erase_chip.sr (13K)
- kc85-20mhz.sr (3.4K)
- lan8720a_read_write_read.sr (524B)
- mcp2515dm-bm-125kbits_msg_222_5bytes.sr (12K)
- mtk3339_8n1_9600.sr (5.4K)
- mx25l1605d_read.sr (61K)
- olimex_stm32-h103_usb_hid.sr (11K)
- trace_example.sr (11K)

Skip: sainsmart_dds120_powerup_scl_sda_analog.sr (8.6MB), ad5258_read_once_write_continuously_triangle.sr (1.2MB)

**Step 2: Delete mocked unit tests**

Remove `tests/test_capture_store.py`, `tests/test_formatters.py`, `tests/test_sigrok_cli.py`.

**Step 3: Create `tests/conftest.py`**

```python
"""Shared fixtures for integration tests."""
import os
import shutil
import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR

def has_sigrok_cli():
    return shutil.which("sigrok-cli") is not None

skip_no_sigrok = pytest.mark.skipif(
    not has_sigrok_cli(), reason="sigrok-cli not installed"
)
```

**Step 4: Commit**

```bash
git add -A && git commit -m "Add .sr test fixtures, remove mocked unit tests"
```

---

### Task 4: Add CAN transaction formatter

Decode output format (filtered):
```
can-1: Start of frame
can-1: Identifier: 255 (0xff)
can-1: Identifier extension bit: standard frame
can-1: Remote transmission request: data frame
can-1: Data length code: 5
can-1: Data byte 0: 0x01
can-1: Data byte 1: 0x02
can-1: End of frame
```

Target summary format:
```
CAN: 42 frames

#001  ID=0x000 [F0 00 00 1F C0 00 00] DLC=7
#002  ID=0x000 DLC=0
#003  ID=0x7F8 DLC=0
```

**Files:**
- Modify: `src/sigrok_logicanalyzer_mcp/formatters.py`
- Modify: `src/sigrok_logicanalyzer_mcp/sigrok_cli.py` (annotation filter)

**Step 1: Add annotation filter**

In `_SUMMARY_ANNOTATION_FILTERS`:
```python
"can": "can=sof:eof:id:ext-id:full-id:ide:rtr:dlc:data:warnings",
```

**Step 2: Add `format_can_transactions()`**

Parse Start of frame → End of frame groups. Extract ID, DLC, data bytes.

**Step 3: Register in `_TRANSACTION_FORMATTERS`**

**Step 4: Add integration test**

```python
def test_can_decode(fixtures_dir):
    """Decode CAN from mcp2515dm example and verify formatter output."""
    # Run sigrok-cli, apply formatter, assert "ID=" in output
```

**Step 5: Commit**

---

### Task 5: Add 1-Wire / onewire_network transaction formatter

Decode output format (filtered `-A onewire_network=text`):
```
onewire_network-1: Reset/presence: true
onewire_network-1: ROM command: 0x55 'Match ROM'
onewire_network-1: ROM: 0x6700000003a6a842
onewire_network-1: Data: 0xbe
onewire_network-1: Data: 0xaf
```

Target summary:
```
1-Wire: 5 transactions, ROM 0x6700000003a6a842

#001  Match ROM → [BE AF 01 03 03 7F FF 01 10 53]
#002  Match ROM → [44]
```

**Files:** Same as Task 4 pattern.

---

### Task 6: Add MDIO transaction formatter

Decode output (filtered `-A mdio=decode`):
```
mdio-1: READ:  3000 PHYAD: 01 REGAD: 00
mdio-1: WRITE: 8000 PHYAD: 01 REGAD: 00
mdio-1: READ:  8000 PHYAD: 01 REGAD: 00
```

Target summary:
```
MDIO: 3 operations

#001  READ  PHY=01 REG=00 → 0x3000
#002  WRITE PHY=01 REG=00 ← 0x8000
#003  READ  PHY=01 REG=00 → 0x8000
```

---

### Task 7: Add USB packet transaction formatter

Decode output (filtered):
```
usb_packet-1: SOF 1128
usb_packet-1: IN ADDR 2 EP 1
usb_packet-1: DATA0 [ 00 01 00 00 ]
usb_packet-1: ACK
```

Target summary (skip SOF frames, group IN/OUT/SETUP with DATA+handshake):
```
USB: 15 transactions (1154 SOFs filtered)

#001  IN ADDR=2 EP=1 DATA0=[00 01 00 00] ACK
#002  IN ADDR=2 EP=1 NAK
```

---

### Task 8: Add DCF77 formatter

Decode output (filtered):
```
dcf77-1: Minutes: 49
dcf77-1: Hours: 23
dcf77-1: Day: 9
dcf77-1: Day of week: 1 (Monday)
dcf77-1: Month: 1 (January)
dcf77-1: Year: 24
```

Target summary:
```
DCF77: Time decoded

Monday 2024-01-09 23:49
```

---

### Task 9: Add AM230x formatter

Decode output (filtered):
```
am230x-1: Humidity: 52.6 %
am230x-1: Temperature: 25.6 °C
am230x-1: Checksum: OK
```

Target summary:
```
AM230x: 2 readings

#001  Temp=25.6C Humidity=52.6% Checksum=OK
```

---

### Task 10: Add AVR ISP formatter

Decode output:
```
avr_isp-1: Programming enable
avr_isp-1: Vendor code: 0x1e (Atmel)
avr_isp-1: Part family / memory size: 0x93
avr_isp-1: Part number: 0x0a
avr_isp-1: Device: Atmel ATmega88
avr_isp-1: Read fuse bits: 0xff
avr_isp-1: Read fuse high bits: 0xdf
avr_isp-1: Read extended fuse bits: 0xf9
avr_isp-1: Chip erase
```

Target summary:
```
AVR ISP: 20 operations, device: Atmel ATmega88

#001  Programming enable
#002  Device: Atmel ATmega88
#003  Read fuse bits: 0xff
#004  Read fuse high bits: 0xdf
#005  Read extended fuse bits: 0xf9
#006  Chip erase
```

Filter out individual bit annotations, keep meaningful operations. This decoder already outputs high-level annotations, so the formatter mainly deduplicates and numbers.

---

### Task 11: Add SPI Flash formatter

Decode output:
```
spiflash-1: Command: Read data (READ)
spiflash-1: Address: 0x117c00
spiflash-1: Data (256 bytes)
spiflash-1: Read data (addr 0x117c00, 256 bytes): 6f 72 6c 64 ...
```

Target summary:
```
SPI Flash: 4 operations

#001  READ 0x117C00 (256 bytes)
#002  READ 0x117D00 (256 bytes)
#003  READ 0x117E00 (256 bytes)
#004  READ 0x117F00 (256 bytes)
```

Filter to just the summary "Read data (addr ...)" lines and command lines.

---

### Task 12: Add SD Card formatter

Decode output (filtered `-A sdcard_sd=decoded-fields`):
```
sdcard_sd-1: Card status
```

This decoder's `decoded-fields` output is minimal. Use broader filter:
```
sdcard_sd=cmd0:cmd17:cmd18:cmd23:cmd24:cmd25:decoded-fields
```

Target: pass through as-is with line numbering (output is already concise).

---

### Task 13: Add Z80 formatter

The Z80 decoder needs channel mapping that matches the .sr file channel names. The kc85 file uses `CLK`, `/M1`, `/RD`, `/WR`, `/MREQ`, `/IORQ`, `A0`-`A15`, `D0`-`D7`.

Z80 decoder expects lowercase: `clk`, `m1`, `rd`, `wr`, `mreq`, `iorq`, `a0`-`a15`, `d0`-`d7`.

Annotation filter:
```python
"z80": "z80=memrd:memwr:iord:iowr:instr",
```

Target summary:
```
Z80: N instructions

#001  RD 0x8000 → 0x3E
#002  WR 0x0001 ← 0xFF
```

Note: Z80 decode failed in testing with "Unknown option or channel 'clk'" — needs investigation. The channel mapping from .sr file names to decoder channel IDs must match exactly. Mark as **may need debugging**.

---

### Task 14: ARM ITM formatter (placeholder — untested)

ARM ITM decoder stacks on UART, not directly on logic signals. The trace_example.sr file failed with "Unknown option or channel 'data'" — ARM ITM has no required channels, it stacks on UART which stacks on logic.

Correct decode chain: `uart:rx=SWO:baudrate=...,arm_itm`

The baud rate is unknown without investigation. Mark as **untested placeholder**.

---

### Task 15: Add untested annotation filters for remaining decoders

**File:** `src/sigrok_logicanalyzer_mcp/sigrok_cli.py`

For each of the ~95 decoders without example files, add an entry to `_SUMMARY_ANNOTATION_FILTERS` with a `# untested` comment. Query annotation classes via `sigrok-cli -P <decoder> --show` to determine the useful (non-bit) annotations.

Group by category:
- Communication buses: lin, flexray, i2s, gpib, ieee488, modbus, dali, dmx512, etc.
- Memory/storage: eeprom24xx, eeprom93xx, x2444m, sda2506, etc.
- Sensors: lm75, mlx90614, mxc6225xu, ds1307, rtc8564, etc.
- Display/LED: max7219, seven_segment, rgb_led_spi, rgb_led_ws281x, st7735, etc.
- RF/wireless: cc1101, nrf24l01, rfm12, em4100, em4305, t55xx, ir_nec, ir_rc5, ir_rc6, etc.
- Debug: swd, jtag, jtag_ejtag, jtag_stm32, arm_etmv3, arm_tpiu, etc.
- Utility: counter, timing, jitter, guess_bitrate, parallel, pwm, etc.
- USB: usb_power_delivery, usb_request
- Misc: cec, cfp, xfp, qi, wiegand, maple_bus, nes_gamepad, etc.

This is a bulk task — use `sigrok-cli --list-supported` output and `sigrok-cli -P <decoder> --show` for each to get annotation classes.

---

### Task 16: Write integration tests

**File:** `tests/test_integration.py`

One test per example protocol. Each test:
1. Runs `sigrok-cli -i fixture.sr -P decoder:channels -A filter`
2. Passes output through the transaction formatter
3. Asserts expected patterns in output

```python
import subprocess
import pytest
from tests.conftest import skip_no_sigrok, FIXTURES_DIR

@skip_no_sigrok
class TestProtocolDecode:

    def _decode(self, fixture, decoder_spec, annotation_filter=None):
        args = ["sigrok-cli", "-i", os.path.join(FIXTURES_DIR, fixture),
                "-P", decoder_spec]
        if annotation_filter:
            args += ["-A", annotation_filter]
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 0, f"sigrok-cli failed: {result.stderr}"
        return result.stdout

    def test_i2c(self):
        raw = self._decode("hantek_6022be_powerup.sr", "i2c:scl=SCL:sda=SDA",
                          "i2c=start:repeat-start:stop:ack:nack:address-read:address-write:data-read:data-write")
        result = format_i2c_transactions(raw)
        assert "transactions" in result
        assert "W 0x" in result

    def test_can(self):
        raw = self._decode("mcp2515dm-bm-125kbits_msg_222_5bytes.sr",
                          "can:can_rx=CAN_RX",
                          "can=sof:eof:id:ext-id:full-id:ide:rtr:dlc:data:warnings")
        result = format_can_transactions(raw)
        assert "frames" in result
        assert "ID=" in result

    def test_onewire(self):
        raw = self._decode("ds28ea00.sr",
                          "onewire_link:owr=0,onewire_network",
                          "onewire_network=text")
        result = format_onewire_transactions(raw)
        assert "transactions" in result
        assert "ROM" in result or "Match ROM" in result

    def test_mdio(self):
        raw = self._decode("lan8720a_read_write_read.sr",
                          "mdio:mdc=MDC:mdio=MDIO", "mdio=decode")
        result = format_mdio_transactions(raw)
        assert "READ" in result or "WRITE" in result

    def test_usb_packet(self):
        raw = self._decode("olimex_stm32-h103_usb_hid.sr",
                          "usb_signalling:dm=DM:dp=DP,usb_packet",
                          "usb_packet=packet-setup:packet-data0:packet-data1:packet-in:packet-out:packet-sof:packet-ack:packet-nak:packet-stall")
        result = format_usb_transactions(raw)
        assert "transactions" in result or "USB" in result

    def test_dcf77(self):
        raw = self._decode("dcf77_120s.sr", "dcf77:data=DATA",
                          "dcf77=minute:hour:day:day-of-week:month:year")
        result = format_dcf77_transactions(raw)
        assert "DCF77" in result

    def test_am230x(self):
        raw = self._decode("am2301_1mhz.sr", "am230x:sda=SDA",
                          "am230x=humidity:temperature:checksum")
        result = format_am230x_transactions(raw)
        assert "Temp" in result or "Humidity" in result

    def test_uart(self):
        raw = self._decode("mtk3339_8n1_9600.sr",
                          "uart:rx=TX:baudrate=9600", "uart=rx-data:tx-data")
        result = format_uart_transactions(raw)
        assert "bytes" in result

    def test_spi(self):
        raw = self._decode("mx25l1605d_read.sr",
                          "spi:clk=SCLK:mosi=MOSI:miso=MISO:cs=CS#",
                          "spi=mosi-data:miso-data:mosi-transfer:miso-transfer")
        result = format_spi_transactions(raw)
        assert "transfers" in result or "SPI" in result

    def test_avr_isp(self):
        raw = self._decode("isp_atmega88_erase_chip.sr",
                          "spi:clk=SCK:mosi=MOSI:miso=MISO,avr_isp")
        result = format_avr_isp_transactions(raw)
        assert "AVR" in result
        assert "ATmega88" in result

    def test_spiflash(self):
        raw = self._decode("mx25l1605d_read.sr",
                          "spi:clk=SCLK:mosi=MOSI:miso=MISO:cs=CS#,spiflash")
        result = format_spiflash_transactions(raw)
        assert "READ" in result or "SPI Flash" in result

    def test_sdcard(self):
        raw = self._decode("cmd23_cmd18.sr",
                          "sdcard_sd:cmd=CMD:clk=CLK")
        result = format_decoded_protocol(raw)  # generic fallback if no formatter
        assert len(raw) > 0
```

---

### Task 17: Add GitHub Actions CI workflow

**File:** `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main, "claude/*"]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4

      - name: Install sigrok-cli
        run: sudo apt-get update && sudo apt-get install -y sigrok-cli

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install package
        run: pip install -e ".[dev]"

      - name: Run tests
        run: pytest tests/ -v
```

---

### Task 18: Add GitHub Actions publish workflow (OIDC)

**File:** `.github/workflows/publish.yml`

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

permissions:
  id-token: write

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Build
        run: |
          pip install build
          python -m build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

Note: The repo owner must configure the trusted publisher on PyPI:
1. Go to https://pypi.org/manage/account/publishing/
2. Add pending publisher: GitHub, owner=wannessels, repo=sigrok-mcp, workflow=publish.yml, environment=pypi
3. Create a "pypi" environment in GitHub repo settings

---

### Task 19: Final verification and commit

**Step 1:** Run full test suite: `pytest tests/ -v`
**Step 2:** Verify package builds: `pip install build && python -m build`
**Step 3:** Final commit and push
