#!/bin/bash
# Decode all sigrok example .sr files and save output to txt files.
# This helps us understand the output format for writing transaction formatters.

EXAMPLES="/c/Program Files/sigrok/sigrok-cli/examples"
OUTDIR="/c/Projects/mcp/sigrok-mcp/tests/fixtures/decoded"
mkdir -p "$OUTDIR"

echo "Decoding example .sr files..."
echo ""

# --- I2C: hantek_6022be_powerup.sr ---
echo "=== I2C: hantek_6022be_powerup ==="
sigrok-cli -i "$EXAMPLES/hantek_6022be_powerup.sr" \
  -P i2c:scl=SCL:sda=SDA \
  -A "i2c=start:repeat-start:stop:ack:nack:address-read:address-write:data-read:data-write" \
  > "$OUTDIR/hantek_6022be_i2c.txt" 2>&1
wc -l "$OUTDIR/hantek_6022be_i2c.txt"

# --- SPI: mx25l1605d_read.sr (raw SPI) ---
echo "=== SPI: mx25l1605d_read ==="
sigrok-cli -i "$EXAMPLES/mx25l1605d_read.sr" \
  -P "spi:clk=SCLK:mosi=MOSI:miso=MISO:cs=CS#" \
  -A "spi=mosi-data:miso-data:mosi-transfer:miso-transfer" \
  > "$OUTDIR/mx25l1605d_spi.txt" 2>&1
wc -l "$OUTDIR/mx25l1605d_spi.txt"

# --- SPI Flash: mx25l1605d_read.sr (stacked spiflash) ---
echo "=== SPI Flash: mx25l1605d_read ==="
sigrok-cli -i "$EXAMPLES/mx25l1605d_read.sr" \
  -P "spi:clk=SCLK:mosi=MOSI:miso=MISO:cs=CS#,spiflash" \
  > "$OUTDIR/mx25l1605d_spiflash.txt" 2>&1
wc -l "$OUTDIR/mx25l1605d_spiflash.txt"

# --- UART: mtk3339_8n1_9600.sr ---
echo "=== UART: mtk3339_8n1_9600 ==="
sigrok-cli -i "$EXAMPLES/mtk3339_8n1_9600.sr" \
  -P uart:rx=TX:baudrate=9600 \
  -A "uart=rx-data:tx-data" \
  > "$OUTDIR/mtk3339_uart.txt" 2>&1
wc -l "$OUTDIR/mtk3339_uart.txt"

# --- CAN: mcp2515dm-bm-125kbits_msg_222_5bytes.sr ---
echo "=== CAN: mcp2515dm ==="
sigrok-cli -i "$EXAMPLES/mcp2515dm-bm-125kbits_msg_222_5bytes.sr" \
  -P can:can_rx=CAN_RX \
  > "$OUTDIR/mcp2515dm_can.txt" 2>&1
wc -l "$OUTDIR/mcp2515dm_can.txt"

# --- 1-Wire link: ds28ea00.sr ---
echo "=== 1-Wire link: ds28ea00 ==="
sigrok-cli -i "$EXAMPLES/ds28ea00.sr" \
  -P onewire_link:owr=0 \
  > "$OUTDIR/ds28ea00_onewire_link.txt" 2>&1
wc -l "$OUTDIR/ds28ea00_onewire_link.txt"

# --- 1-Wire network: ds28ea00.sr ---
echo "=== 1-Wire network: ds28ea00 ==="
sigrok-cli -i "$EXAMPLES/ds28ea00.sr" \
  -P onewire_link:owr=0,onewire_network \
  > "$OUTDIR/ds28ea00_onewire_network.txt" 2>&1
wc -l "$OUTDIR/ds28ea00_onewire_network.txt"

# --- 1-Wire ds28ea00 device decoder: ds28ea00.sr ---
echo "=== DS28EA00 device: ds28ea00 ==="
sigrok-cli -i "$EXAMPLES/ds28ea00.sr" \
  -P onewire_link:owr=0,onewire_network,ds28ea00 \
  > "$OUTDIR/ds28ea00_device.txt" 2>&1
wc -l "$OUTDIR/ds28ea00_device.txt"

# --- MDIO: lan8720a_read_write_read.sr ---
echo "=== MDIO: lan8720a ==="
sigrok-cli -i "$EXAMPLES/lan8720a_read_write_read.sr" \
  -P mdio:mdc=MDC:mdio=MDIO \
  > "$OUTDIR/lan8720a_mdio.txt" 2>&1
wc -l "$OUTDIR/lan8720a_mdio.txt"

# --- SD Card: cmd23_cmd18.sr ---
echo "=== SD Card: cmd23_cmd18 ==="
sigrok-cli -i "$EXAMPLES/cmd23_cmd18.sr" \
  -P sdcard_sd:cmd=CMD:clk=CLK \
  > "$OUTDIR/cmd23_cmd18_sdcard.txt" 2>&1
wc -l "$OUTDIR/cmd23_cmd18_sdcard.txt"

# --- DCF77: dcf77_120s.sr ---
echo "=== DCF77: dcf77_120s ==="
sigrok-cli -i "$EXAMPLES/dcf77_120s.sr" \
  -P dcf77:data=DATA \
  > "$OUTDIR/dcf77_120s_dcf77.txt" 2>&1
wc -l "$OUTDIR/dcf77_120s_dcf77.txt"

# --- AM230x: am2301_1mhz.sr ---
echo "=== AM230x: am2301 ==="
sigrok-cli -i "$EXAMPLES/am2301_1mhz.sr" \
  -P am230x:sda=SDA \
  > "$OUTDIR/am2301_am230x.txt" 2>&1
wc -l "$OUTDIR/am2301_am230x.txt"

# --- USB signalling: olimex_stm32-h103_usb_hid.sr ---
echo "=== USB signalling: olimex_stm32 ==="
sigrok-cli -i "$EXAMPLES/olimex_stm32-h103_usb_hid.sr" \
  -P usb_signalling:dm=DM:dp=DP \
  > "$OUTDIR/olimex_stm32_usb_signalling.txt" 2>&1
wc -l "$OUTDIR/olimex_stm32_usb_signalling.txt"

# --- USB packet: olimex_stm32-h103_usb_hid.sr ---
echo "=== USB packet: olimex_stm32 ==="
sigrok-cli -i "$EXAMPLES/olimex_stm32-h103_usb_hid.sr" \
  -P usb_signalling:dm=DM:dp=DP,usb_packet \
  > "$OUTDIR/olimex_stm32_usb_packet.txt" 2>&1
wc -l "$OUTDIR/olimex_stm32_usb_packet.txt"

# --- Z80: kc85-20mhz.sr ---
echo "=== Z80: kc85 ==="
sigrok-cli -i "$EXAMPLES/kc85-20mhz.sr" \
  -P z80:clk=CLK:d0=D0:d1=D1:d2=D2:d3=D3:d4=D4:d5=D5:d6=D6:d7=D7:m1=/M1:rd=/RD:wr=/WR:mreq=/MREQ:iorq=/IORQ:a0=A0:a1=A1:a2=A2:a3=A3:a4=A4:a5=A5:a6=A6:a7=A7:a8=A8:a9=A9:a10=A10:a11=A11:a12=A12:a13=A13:a14=A14:a15=A15 \
  > "$OUTDIR/kc85_z80.txt" 2>&1
wc -l "$OUTDIR/kc85_z80.txt"

# --- AVR ISP: isp_atmega88_erase_chip.sr ---
echo "=== AVR ISP: isp_atmega88 ==="
sigrok-cli -i "$EXAMPLES/isp_atmega88_erase_chip.sr" \
  -P spi:clk=SCK:mosi=MOSI:miso=MISO,avr_isp \
  > "$OUTDIR/isp_atmega88_avr_isp.txt" 2>&1
wc -l "$OUTDIR/isp_atmega88_avr_isp.txt"

# --- ARM ITM: trace_example.sr ---
echo "=== ARM ITM: trace_example ==="
sigrok-cli -i "$EXAMPLES/trace_example.sr" \
  -P arm_itm:data=SWO \
  > "$OUTDIR/trace_example_arm_itm.txt" 2>&1
wc -l "$OUTDIR/trace_example_arm_itm.txt"

echo ""
echo "Done. All decoded output saved to $OUTDIR/"
ls -lh "$OUTDIR/"
