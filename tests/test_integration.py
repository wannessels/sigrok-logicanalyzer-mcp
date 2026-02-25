"""Integration tests using sigrok-cli against .sr fixture files."""

import os
import subprocess

from tests.conftest import skip_no_sigrok, FIXTURES_DIR
from sigrok_logicanalyzer_mcp.formatters import (
    format_i2c_transactions,
    format_spi_transactions,
    format_uart_transactions,
    format_can_transactions,
    format_onewire_transactions,
    format_mdio_transactions,
    format_usb_transactions,
    format_dcf77_transactions,
    format_am230x_transactions,
    format_avr_isp_transactions,
    format_spiflash_transactions,
    format_sdcard_transactions,
    format_decoded_summary,
)


def _decode(fixture, decoder_spec, annotation_filter=None):
    """Run sigrok-cli on a fixture file and return stdout."""
    args = ["sigrok-cli", "-i", os.path.join(FIXTURES_DIR, fixture), "-P", decoder_spec]
    if annotation_filter:
        args += ["-A", annotation_filter]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, f"sigrok-cli failed: {result.stderr}"
    return result.stdout


@skip_no_sigrok
class TestProtocolDecode:
    def test_i2c(self):
        raw = _decode(
            "hantek_6022be_powerup.sr",
            "i2c:scl=SCL:sda=SDA",
            "i2c=start:repeat-start:stop:ack:nack:address-read:address-write:data-read:data-write",
        )
        result = format_i2c_transactions(raw)
        assert "transactions" in result
        assert "W 0x" in result or "R 0x" in result

    def test_spi(self):
        raw = _decode(
            "mx25l1605d_read.sr",
            "spi:clk=SCLK:mosi=MOSI:miso=MISO:cs=CS#",
            "spi=mosi-data:miso-data:mosi-transfer:miso-transfer",
        )
        result = format_spi_transactions(raw)
        assert "SPI" in result

    def test_uart(self):
        raw = _decode(
            "mtk3339_8n1_9600.sr",
            "uart:rx=TX:baudrate=9600",
            "uart=rx-data:tx-data",
        )
        result = format_uart_transactions(raw)
        assert "bytes" in result

    def test_can(self):
        raw = _decode(
            "mcp2515dm-bm-125kbits_msg_222_5bytes.sr",
            "can:can_rx=CAN_RX",
            "can=sof:eof:id:ext-id:full-id:ide:rtr:dlc:data:warnings",
        )
        result = format_can_transactions(raw)
        assert "frames" in result
        assert "ID=" in result

    def test_onewire(self):
        raw = _decode(
            "ds28ea00.sr",
            "onewire_link:owr=0,onewire_network",
            "onewire_network",
        )
        result = format_onewire_transactions(raw)
        assert "transactions" in result
        assert "ROM" in result

    def test_mdio(self):
        raw = _decode(
            "lan8720a_read_write_read.sr",
            "mdio:mdc=MDC:mdio=MDIO",
            "mdio=decode",
        )
        result = format_mdio_transactions(raw)
        assert "READ" in result
        assert "WRITE" in result
        assert "PHY=" in result

    def test_usb_packet(self):
        raw = _decode(
            "olimex_stm32-h103_usb_hid.sr",
            "usb_signalling:dm=DM:dp=DP,usb_packet",
            "usb_packet",
        )
        result = format_usb_transactions(raw)
        assert "USB" in result
        assert "SOFs filtered" in result

    def test_dcf77(self):
        raw = _decode(
            "dcf77_120s.sr",
            "dcf77:data=DATA",
            "dcf77=minute:hour:day:day-of-week:month:year",
        )
        result = format_dcf77_transactions(raw)
        assert "DCF77" in result
        assert "23" in result  # hours
        assert "49" in result  # minutes

    def test_am230x(self):
        raw = _decode(
            "am2301_1mhz.sr",
            "am230x:sda=SDA",
            "am230x=humidity:temperature:checksum",
        )
        result = format_am230x_transactions(raw)
        assert "readings" in result
        assert "Temp=" in result
        assert "Humidity=" in result

    def test_avr_isp(self):
        raw = _decode(
            "isp_atmega88_erase_chip.sr",
            "spi:clk=SCK:mosi=MOSI:miso=MISO,avr_isp",
            "avr_isp",
        )
        result = format_avr_isp_transactions(raw)
        assert "AVR ISP" in result
        assert "ATmega88" in result

    def test_spiflash(self):
        raw = _decode(
            "mx25l1605d_read.sr",
            "spi:clk=SCLK:mosi=MOSI:miso=MISO:cs=CS#,spiflash",
            "spiflash",
        )
        result = format_spiflash_transactions(raw)
        assert "SPI Flash" in result
        assert "READ" in result

    def test_sdcard(self):
        raw = _decode(
            "cmd23_cmd18.sr",
            "sdcard_sd:cmd=CMD:clk=CLK",
            "sdcard_sd=cmd18:cmd23:decoded-fields",
        )
        result = format_sdcard_transactions(raw)
        assert "SD Card" in result
        assert len(raw) > 0

    def test_format_decoded_summary_dispatch(self):
        """Verify format_decoded_summary dispatches to the right formatter."""
        raw = _decode(
            "lan8720a_read_write_read.sr",
            "mdio:mdc=MDC:mdio=MDIO",
            "mdio=decode",
        )
        result = format_decoded_summary(raw, "mdio")
        assert "MDIO" in result
        assert "operations" in result
