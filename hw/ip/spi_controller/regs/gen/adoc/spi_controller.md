<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: spi_controller
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/spi_controller/regs/spi_controller.rdl
-->

## spi_controller address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x38

|Offset| Identifier |Name|
|------|------------|----|
| 0x00 | INTR_STATUS|  — |
| 0x04 | INTR_ENABLE|  — |
| 0x08 |  INTR_TEST |  — |
| 0x10 |    CTRL    |  — |
| 0x14 |   STATUS   |  — |
| 0x18 |     CFG    |  — |
| 0x1C |    CSID    |  — |
| 0x20 |     CMD    |  — |
| 0x24 |   RXDATA   |  — |
| 0x28 |   TXDATA   |  — |
| 0x2C |ERROR_ENABLE|  — |
| 0x30 |ERROR_STATUS|  — |
| 0x34 |EVENT_ENABLE|  — |

### INTR_STATUS register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>Interrupt Status Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   ERROR  |   r  | 0x0 |  — |
|  4 | SPI_EVENT|   r  | 0x0 |  — |

#### ERROR field

<p>Error Interrupt. Asserted when any bit in the ERROR_STATUS register is set.</p>

#### SPI_EVENT field

<p>SPI Event Interrupt. Asserted when any event associated with a bit in the
EVENT_ENABLE register occurs.</p>

### INTR_ENABLE register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   ERROR  |  rw  | 0x0 |  — |
|  4 | SPI_EVENT|  rw  | 0x0 |  — |

#### ERROR field

<p>Error Interrupt Enable.</p>

#### SPI_EVENT field

<p>SPI Event Interrupt Enable.</p>

### INTR_TEST register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   ERROR  |  rw  | 0x0 |  — |
|  4 | SPI_EVENT|  rw  | 0x0 |  — |

#### ERROR field

<p>Error Interrupt Test. Writing <code>1</code> to this bit forces the Error Interrupt and
writing <code>0</code> releases it.</p>

#### SPI_EVENT field

<p>SPI Event Interrupt Test. Writing <code>1</code> to this bit forces the SPI Event
Interrupt and writing <code>0</code> releases it.</p>

### CTRL register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

<p>Control Register</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
| 7:0|RX_WATERMARK|  rw  | 0x7F|  — |
|15:8|TX_WATERMARK|  rw  | 0x0 |  — |
| 29 |  OUTPUT_EN |  rw  | 0x0 |  — |
| 30 |   SW_RST   |   w  | 0x0 |  — |
| 31 |    SPIEN   |  rw  | 0x0 |  — |

#### RX_WATERMARK field

<p>If !!EVENT_ENABLE.RXWM is set, the IP will send
an interrupt when the depth of the RX FIFO reaches
RX_WATERMARK words (32b each).</p>

#### TX_WATERMARK field

<p>If !!EVENT_ENABLE.TXWM is set, the IP will send
an interrupt when the depth of the TX FIFO drops below
TX_WATERMARK words (32b each).</p>

#### OUTPUT_EN field

<p>Enable the SPI host output buffers for the sck, csb, and sd lines.  This allows
the SPI_HOST IP to connect to the same bus as other SPI controllers without
interference.</p>

#### SW_RST field

<p>Clears the entire IP to the reset state when set to 1, including
the FIFOs, the CDC's, the core state machine and the shift register.
In the current implementation, the CDC FIFOs are drained not reset.
Therefore software must confirm that both FIFO's empty before releasing
the IP from reset.</p>

#### SPIEN field

<p>Enables the SPI Controller. On reset, this field is 0, meaning
that no transactions can proceed.</p>

### STATUS register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

<p>Status Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 7:0 |   TXQD   |   r  | 0x0 |  — |
| 15:8|   RXQD   |   r  | 0x0 |  — |
|19:16|   CMDQD  |   r  | 0x0 |  — |
|  20 |   RXWM   |   r  | 0x0 |  — |
|  22 | BYTEORDER|   r  | 0x0 |  — |
|  23 |  RXSTALL |   r  | 0x0 |  — |
|  24 |  RXEMPTY |   r  | 0x0 |  — |
|  25 |  RXFULL  |   r  | 0x0 |  — |
|  26 |   TXWM   |   r  | 0x0 |  — |
|  27 |  TXSTALL |   r  | 0x0 |  — |
|  28 |  TXEMPTY |   r  | 0x0 |  — |
|  29 |  TXFULL  |   r  | 0x0 |  — |
|  30 |  ACTIVE  |   r  | 0x0 |  — |
|  31 |   READY  |   r  | 0x0 |  — |

#### TXQD field

<p>Transmit queue depth. Indicates how many unsent 32-bit words
are currently in the TX FIFO.  When active, this result may
be an overestimate due to synchronization delays.</p>

#### RXQD field

<p>Receive queue depth. Indicates how many unread 32-bit words are
currently in the RX FIFO.  When active, this result may an
underestimate due to synchronization delays.</p>

#### CMDQD field

<p>Command queue depth. Indicates how many unread 32-bit words are
currently in the command segment queue.</p>

#### RXWM field

<p>If high, the number of 32-bits in the RX FIFO now exceeds the
!!CONTROL.RX_WATERMARK entries (32b each).</p>

#### BYTEORDER field

<p>The value of the ByteOrder parameter, provided so that firmware
can confirm proper IP configuration.</p>

#### RXSTALL field

<p>If high, signifies that an ongoing transaction has stalled
due to lack of available space in the RX FIFO</p>

#### RXEMPTY field

<p>When high, indicates that the receive fifo is empty.
Any reads from RX FIFO will cause an error interrupt.</p>

#### RXFULL field

<p>When high, indicates that the receive fifo is full.  Any
ongoing transactions will stall until firmware reads some
data from !!RXDATA.</p>

#### TXWM field

<p>If high, the amount of data in the TX FIFO has fallen below the
level of !!CONTROL.TX_WATERMARK words (32b each).</p>

#### TXSTALL field

<p>If high, signifies that an ongoing transaction has stalled
due to lack of data in the TX FIFO</p>

#### TXEMPTY field

<p>When high, indicates that the transmit data fifo is empty.</p>

#### TXFULL field

<p>When high, indicates that the transmit data fifo is full.
Any further writes to !!RXDATA will create an error interrupt.</p>

#### ACTIVE field

<p>When high, indicates the SPI host is processing a previously
issued command.</p>

#### READY field

<p>When high, indicates the SPI host is ready to receive
commands. Writing to COMMAND when READY is low is
an error, and will trigger an interrupt.</p>

### CFG register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

<p>Configuration Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 15:0|  CLKDIV  |  rw  | 0x0 |  — |
|19:16|  CSNIDLE |  rw  | 0x0 |  — |
|23:20| CSNTRAIL |  rw  | 0x0 |  — |
|27:24|  CSNLEAD |  rw  | 0x0 |  — |
|  29 |  FULLCYC |  rw  | 0x0 |  — |
|  30 |   CPHA   |  rw  | 0x0 |  — |
|  31 |   CPOL   |  rw  | 0x0 |  — |

#### CLKDIV field

<p>Core clock divider.  Slows down subsequent SPI transactions by a
factor of (CLKDIV+1) relative to the core clock frequency.  The
period of sck, T(sck) then becomes <code>2*(CLK_DIV+1)*T(core)</code></p>

#### CSNIDLE field

<p>Minimum idle time between commands. Indicates the minimum
number of sck half-cycles to hold cs_n high between commands.
Setting this register to zero creates a minimally-wide CS_N-high
pulse of one-half sck cycle.</p>

#### CSNTRAIL field

<p>CS_N Trailing Time.  Indicates the number of half sck cycles,
CSNTRAIL+1, to leave between last edge of sck and the rising
edge of cs_n. Setting this register to zero corresponds
to the minimum delay of one-half sck cycle.</p>

#### CSNLEAD field

<p>CS_N Leading Time.  Indicates the number of half sck cycles,
CSNLEAD+1, to leave between the falling edge of cs_n and
the first edge of sck.  Setting this register to zero
corresponds to the minimum delay of one-half sck cycle</p>

#### FULLCYC field

<p>Full cycle.  Modifies the CPHA sampling behaviour to allow
for longer device logic setup times.  Rather than sampling the SD
bus a half cycle after shifting out data, the data is sampled
a full cycle after shifting data out.  This means that if
CPHA = 0, data is shifted out on the trailing edge, and
sampled a full cycle later.  If CPHA = 1, data is shifted and
sampled with the trailing edge, also separated by a
full cycle.</p>

#### CPHA field

<p>The phase of the sck clock signal relative to the data. When
CPHA = 0, the data changes on the trailing edge of sck
and is typically sampled on the leading edge.  Conversely
if CPHA = 1 high, data lines change on the leading edge of
sck and are typically sampled on the trailing edge.
CPHA should be chosen to match the phase of the selected
device.  The sampling behavior is modified by the
!!CONFIGOPTS.FULLCYC bit.</p>

#### CPOL field

<p>The polarity of the sck clock signal.  When CPOL is 0,
sck is low when idle, and emits high pulses.   When CPOL
is low, sck is high when idle, and emits a series of low
pulses.</p>

### CSID register

- Absolute Address: 0x1C
- Base Offset: 0x1C
- Size: 0x4

<p>Chip Select ID Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   CSID   |  rw  | 0x0 |  — |

#### CSID field

<p>Chip Select ID</p>

### CMD register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x4

<p>Command Register</p>

| Bits|Identifier| Access |Reset|Name|
|-----|----------|--------|-----|----|
| 8:0 |    LEN   |w, wuser| 0x0 |  — |
|  9  |   CSAAT  |    w   | 0x0 |  — |
|11:10|   SPEED  |    w   | 0x0 |  — |
|13:12| DIRECTION|    w   | 0x0 |  — |

#### LEN field

<p>Segment Length.</p>
<p>For read or write segments, this field controls the
number of 1-byte bursts to transmit and or receive in
this command segment.  The number of cyles required
to send or received a byte will depend on !!COMMAND.SPEED.
For dummy segments, (!!COMMAND.DIRECTION == 0), this register
controls the number of dummy cycles to issue.
The number of bytes (or dummy cycles) in the segment will be
equal to !!COMMAND.LEN + 1.</p>

#### CSAAT field

<p>Chip select active after transaction.  If CSAAT = 0, the
chip select line is raised immediately at the end of the
command segment.   If !!COMMAND.CSAAT = 1, the chip select
line is left low at the end of the current transaction
segment.  This allows the creation longer, more
complete SPI transactions, consisting of several separate
segments for issuing instructions, pausing for dummy cycles,
and transmitting or receiving data from the device.</p>

#### SPEED field

<p>The speed for this command segment: "0" = Standard SPI. "1" = Dual SPI.
"2"=Quad SPI,  "3": RESERVED.</p>

#### DIRECTION field

<p>The direction for the following command: "0" = Dummy cycles
(no TX/RX). "1" = Rx only, "2" = Tx only, "3" = Bidirectional
Tx/Rx (Standard SPI mode only).</p>

### RXDATA register

- Absolute Address: 0x24
- Base Offset: 0x24
- Size: 0x4

<p>Received Data Register</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
|31:0|  RXDATA  |r, ruser| 0x0 |  — |

#### RXDATA field

<p>SPI Received Data.</p>

### TXDATA register

- Absolute Address: 0x28
- Base Offset: 0x28
- Size: 0x4

<p>Transmit Data Register</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
|31:0|  TXDATA  |w, wuser| 0x0 |  — |

#### TXDATA field

<p>SPI Transmit Data.</p>

### ERROR_ENABLE register

- Absolute Address: 0x2C
- Base Offset: 0x2C
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  CMDBUSY |  rw  | 0x1 |  — |
|  4 | OVERFLOW |  rw  | 0x1 |  — |
|  8 | UNDERFLOW|  rw  | 0x1 |  — |
| 12 | CMDINVAL |  rw  | 0x1 |  — |
| 16 | CSIDINVAL|  rw  | 0x1 |  — |

#### CMDBUSY field

<p>Command Error: If this bit is set, the block sends an error
interrupt whenever a command is issued while busy (i.e. a 1 is
when !!STATUS.READY is not asserted.)</p>

#### OVERFLOW field

<p>Overflow Errors: If this bit is set, the block sends an
error interrupt whenever the TX FIFO overflows.</p>

#### UNDERFLOW field

<p>Underflow Errors: If this bit is set, the block sends an
error interrupt whenever there is a read from !!RXDATA
but the RX FIFO is empty.</p>

#### CMDINVAL field

<p>Invalid Command Errors: If this bit is set, the block sends an
error interrupt whenever a command is sent with invalid values for
!!COMMAND.SPEED or !!COMMAND.DIRECTION.</p>

#### CSIDINVAL field

<p>Invalid CSID: If this bit is set, the block sends an error interrupt whenever
a command is submitted, but CSID exceeds NumCS.</p>

### ERROR_STATUS register

- Absolute Address: 0x30
- Base Offset: 0x30
- Size: 0x4

|Bits| Identifier|  Access |Reset|Name|
|----|-----------|---------|-----|----|
|  0 |  CMDBUSY  |rw, woclr| 0x0 |  — |
|  4 |  OVERFLOW |rw, woclr| 0x0 |  — |
|  8 | UNDERFLOW |rw, woclr| 0x0 |  — |
| 12 |  CMDINVAL |rw, woclr| 0x0 |  — |
| 16 | CSIDINVAL |rw, woclr| 0x0 |  — |
| 20 |ACCESSINVAL|rw, woclr| 0x0 |  — |

#### CMDBUSY field

<p>Indicates a write to !!COMMAND when !!STATUS.READY = 0.</p>

#### OVERFLOW field

<p>Indicates that firmware has overflowed the TX FIFO</p>

#### UNDERFLOW field

<p>Indicates that firmware has attempted to read from
!!RXDATA when the RX FIFO is empty.</p>

#### CMDINVAL field

<p>Indicates an invalid command segment, meaning either an invalid value of
!!COMMAND.SPEED or a request for bidirectional data transfer at dual or quad
speed</p>

#### CSIDINVAL field

<p>Indicates a command was attempted with an invalid value for !!CSID.</p>

#### ACCESSINVAL field

<p>Indicates that TLUL attempted to write to TXDATA with no bytes enabled. Such
'zero byte' writes are not supported.</p>

### EVENT_ENABLE register

- Absolute Address: 0x34
- Base Offset: 0x34
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  RXFULL  |  rw  | 0x0 |  — |
|  4 |  TXEMPTY |  rw  | 0x0 |  — |
|  8 |   RXWM   |  rw  | 0x0 |  — |
| 12 |   TXWM   |  rw  | 0x0 |  — |
| 16 |   READY  |  rw  | 0x0 |  — |
| 20 |   IDLE   |  rw  | 0x0 |  — |

#### RXFULL field

<p>Assert to send a spi_event interrupt whenever !!STATUS.RXFULL
goes high</p>

#### TXEMPTY field

<p>Assert to send a spi_event interrupt whenever !!STATUS.TXEMPTY
goes high</p>

#### RXWM field

<p>Assert to send a spi_event interrupt whenever the number of 32-bit words in
the RX FIFO is greater than !!CONTROL.RX_WATERMARK. To prevent the
reassertion of this interrupt, read more data from the RX FIFO, or
increase !!CONTROL.RX_WATERMARK.</p>

#### TXWM field

<p>Assert to send a spi_event interrupt whenever the number of 32-bit words in
the TX FIFO is less than !!CONTROL.TX_WATERMARK.  To prevent the
reassertion of this interrupt add more data to the TX FIFO, or
reduce !!CONTROL.TX_WATERMARK.</p>

#### READY field

<p>Assert to send a spi_event interrupt whenever !!STATUS.READY
goes high</p>

#### IDLE field

<p>Assert to send a spi_event interrupt whenever !!STATUS.ACTIVE
goes low</p>
