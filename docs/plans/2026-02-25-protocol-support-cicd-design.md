# Protocol Support, CI/CD, and Project Rename Design

## Changes

### 1. Rename project to sigrok-logicanalyzer-mcp

- PyPI package: `sigrok-logicanalyzer-mcp`
- Python package: `sigrok_logicanalyzer_mcp`
- Entry point: `sigrok-logicanalyzer-mcp`
- Rename `src/sigrok_logic_analyzer_mcp/` to `src/sigrok_logicanalyzer_mcp/`
- Update all imports, pyproject.toml, tests

### 2. License: GPL-3.0-or-later

Same as sigrok-cli/libsigrok. Add LICENSE file and update pyproject.toml.

### 3. Transaction formatters for all example protocols

Each gets a `format_X_transactions()` function and `_SUMMARY_ANNOTATION_FILTERS` entry,
verified against the example .sr files bundled in `tests/fixtures/`.

| Protocol | Example File | Decoder(s) |
|----------|-------------|------------|
| I2C | hantek_6022be_powerup.sr | i2c | (already done) |
| SPI | mx25l1605d_read.sr | spi | (already done) |
| UART | mtk3339_8n1_9600.sr | uart | (already done) |
| 1-Wire | ds28ea00.sr | onewire_link, onewire_network, ds28ea00 |
| CAN | mcp2515dm-bm-125kbits_msg_222_5bytes.sr | can |
| SD Card | cmd23_cmd18.sr | sdcard_sd |
| MDIO | lan8720a_read_write_read.sr | mdio |
| USB | olimex_stm32-h103_usb_hid.sr | usb_signalling, usb_packet |
| DCF77 | dcf77_120s.sr | dcf77 |
| AM230x | am2301_1mhz.sr | am230x |
| Z80 | kc85-20mhz.sr | z80 |
| AVR ISP | isp_atmega88_erase_chip.sr | avr_isp (stacked on spi) |
| SPI Flash | mx25l1605d_read.sr | spiflash (stacked on spi) |
| ARM ITM | trace_example.sr | arm_itm |

### 4. Remaining decoders (untested)

For the ~95 decoders without example files:
- Add `_SUMMARY_ANNOTATION_FILTERS` entries where annotation classes are known
  (queried via `sigrok-cli -P <decoder> --show`)
- Each entry gets a `# untested` comment
- These use the generic `format_decoded_protocol` fallback (no transaction formatter)

### 5. Test fixtures

Copy 13 example .sr files (skipping the 2 large ones: sainsmart 8.6MB, ad5258 1.2MB)
into `tests/fixtures/`. ~220KB total.

### 6. GitHub Actions

**.github/workflows/ci.yml** (push + PR):
- Matrix: Python 3.10, 3.11, 3.12, 3.13 on ubuntu-latest
- Install sigrok-cli via apt
- `pip install -e ".[dev]"`
- `pytest tests/ -v` (unit tests, mocked)
- `pytest tests/integration/ -v` (integration tests against .sr fixtures)

**.github/workflows/publish.yml** (on GitHub Release):
- Build sdist + wheel with `python -m build`
- Publish to PyPI using trusted publisher (OIDC) or `PYPI_API_TOKEN` secret

### 7. pyproject.toml metadata

Complete the project metadata:
- name: sigrok-logicanalyzer-mcp
- license: GPL-3.0-or-later
- author, description, classifiers, urls, python_requires

## Implementation Order

1. Rename project (directory, imports, pyproject.toml, entry points)
2. Add GPL-3.0 LICENSE file, update pyproject.toml
3. Copy example .sr fixtures into tests/fixtures/
4. Explore each example file's decode output to understand annotation format
5. Add annotation filters + transaction formatters per protocol
6. Add integration tests that decode each fixture and assert expected patterns
7. Add remaining untested decoder annotation filters
8. Add GitHub Actions CI workflow
9. Add GitHub Actions publish workflow
10. Final test run, commit
