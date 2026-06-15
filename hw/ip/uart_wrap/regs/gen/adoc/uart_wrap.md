<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: uart_wrap
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/uart_wrap/regs/uart_wrap.rdl
-->

## uart_wrap address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x1000

|Offset|       Identifier      |Name|
|------|-----------------------|----|
| 0x000|uart_log_engine_wrap[0]|  — |
| 0x400|uart_log_engine_wrap[1]|  — |
| 0x800|uart_log_engine_wrap[2]|  — |
| 0xC00|uart_log_engine_wrap[3]|  — |

## uart_log_engine_wrap address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x280
- Array Dimensions: [4]
- Array Stride: 0x400
- Total Size: 0x1000

|Offset|     Identifier     |            Name           |
|------|--------------------|---------------------------|
| 0x000|uart_log_engine_ctrl|             —             |
| 0x100|        uart        |UART 16550 Main Address Map|
| 0x200|     log_engine     |             —             |

## uart_log_engine_ctrl address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

|Offset|Identifier|Name|
|------|----------|----|
|  0x0 |   CTRL   |  — |

### CTRL register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  UART_EN |  rw  | 0x0 |  — |

#### UART_EN field

<p>UART Enable. When set, the pad-mux downstream will be forced to accept UART
traffic.</p>

## uart address map

- Absolute Address: 0x100
- Base Offset: 0x100
- Size: 0x28

<p>Contains the mode-independent registers and the read-only registers accessible only
when <code>DLAB = 0</code>.</p>

|Offset|Identifier|Name|
|------|----------|----|
| 0x00 |    RBR   |  — |
| 0x04 |    IER   |  — |
| 0x08 |    IIR   |  — |
| 0x0C |    LCR   |  — |
| 0x10 |    MCR   |  — |
| 0x14 |    LSR   |  — |
| 0x18 |    MSR   |  — |
| 0x1C |    SCR   |  — |
| 0x20 |    ECR   |  — |
| 0x24 |    ITR   |  — |

### RBR register

- Absolute Address: 0x100
- Base Offset: 0x0
- Size: 0x4

<p>Receiver Buffer Register</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |r, ruser| 0x0 |  — |

#### DATA field

<p>Received Data. Contains a received character. If FIFOs are enabled, this field
points to the bottom of the RX FIFO. Otherwise, this field points to a single-
byte Receiver Buffer Register.</p>

### IER register

- Absolute Address: 0x104
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   ERBFI  |  rw  | 0x0 |  — |
|  1 |   ETBEI  |  rw  | 0x0 |  — |
|  2 |   ELSI   |  rw  | 0x0 |  — |
|  3 |   EDSSI  |  rw  | 0x0 |  — |
|  4 |   EFEI   |  rw  | 0x0 |  — |

#### ERBFI field

<p>Enable Receiver Buffer Full (Received Data Ready) Interrupt.</p>

#### ETBEI field

<p>Enable Transmitter Buffer Empty (Transmitter Holding Register Empty)
Interrupt.</p>

#### ELSI field

<p>Enable (Receiver) Line Status Interrupt.</p>

#### EDSSI field

<p>Enable (Delta Status of) Modem Status Interrupt.</p>

#### EFEI field

<p>Enable FIFO Error Interrupt.</p>

### IIR register

- Absolute Address: 0x108
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Identification Register</p>

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
|  0 |INTERRUPT_PENDING|   r  | 0x1 |  — |
| 3:1|   INTERRUPT_ID  |   r  | 0x0 |  — |
| 7:6|  FIFOS_ENABLED  |   r  | 0x0 |  — |

#### INTERRUPT_PENDING field

<p>Interrupt Pending. Active-low.</p>

#### INTERRUPT_ID field

<p>Interrupt ID:
* <code>0x7</code> - FIFO Error Interrupt                         (priority 0)
* <code>0x3</code> - Receiver Line Status Interrupt               (priority 1)
* <code>0x6</code> - Reception Timeout Interrupt                  (priority 2)
* <code>0x2</code> - Received Data Ready Interrupt                (priority 3)
* <code>0x1</code> - Transmitter Holding Register Empty Interrupt (priority 4)
* <code>0x0</code> - Modem Status Interrupt                       (priority 5)</p>

#### FIFOS_ENABLED field

<p>FIFOs Enabled:
* <code>0x0</code> - FIFOs are disabled
* <code>0x3</code> - FIFOs are enabled</p>

### LCR register

- Absolute Address: 0x10C
- Base Offset: 0xC
- Size: 0x4

<p>Line Control Register</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
| 1:0|     WLS    |  rw  | 0x0 |  — |
|  2 |     STB    |  rw  | 0x0 |  — |
|  3 |     PEN    |  rw  | 0x0 |  — |
|  4 |     EPS    |  rw  | 0x0 |  — |
|  5 |STICK_PARITY|  rw  | 0x0 |  — |
|  6 |  SET_BREAK |  rw  | 0x0 |  — |
|  7 |    DLAB    |  rw  | 0x0 |  — |

#### WLS field

<p>Word Length Select:
* <code>0x0</code> - 5 bits per character
* <code>0x1</code> - 6 bits per character
* <code>0x2</code> - 7 bits per character
* <code>0x3</code> - 8 bits per character</p>

#### STB field

<p>Stop Bits:
* <code>0</code> - 1 stop bit.
* <code>1</code> - 2 stop bits (or 1.5 stop bits if word length is set to 5 bits)</p>

#### PEN field

<p>Parity Enable.</p>

#### EPS field

<p>Even Parity Select:
* <code>1</code> - even parity
* <code>0</code> - odd parity</p>

#### STICK_PARITY field

<p>Stick Parity. If set, forces the transmit and received parity bits to be <code>0</code> if
even parity is selected and <code>1</code> if odd parity is selected.</p>

#### SET_BREAK field

<p>Set Break. If set, forces the <code>tx_o</code> output to <code>0</code> to cause a break condition
on the receiving UART.</p>

#### DLAB field

<p>Divisor Latch Access Bit. If set, allows access to the <code>DLL</code> and <code>DLM</code> registers
when accessing addresses <code>0x0</code> and <code>0x4</code>, respectively. If unset, allows access
to the <code>THR</code>, <code>RBR</code>, and <code>IIR</code> registers.</p>

### MCR register

- Absolute Address: 0x110
- Base Offset: 0x10
- Size: 0x4

<p>Modem Control Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |     DTR     |  rw  | 0x0 |  — |
|  1 |     RTS     |  rw  | 0x0 |  — |
|  2 |     OUT1    |  rw  | 0x0 |  — |
|  3 |     OUT2    |  rw  | 0x0 |  — |
|  4 |     LOOP    |  rw  | 0x0 |  — |
|  5 |LINE_LOOPBACK|  rw  | 0x0 |  — |

#### DTR field

<p>Data Terminal Ready. Writing to this bit drives the <code>dtr_no</code> output in the
opposite polarity.</p>

#### RTS field

<p>Request to Send. Writing to this bit drives the <code>rts_no</code> output in the opposite
polarity.</p>

#### OUT1 field

<p>User Output 1. Writing to this bit drives the <code>out1_no</code> in the opposite
polarity.</p>

#### OUT2 field

<p>User Output 2. Writing to this bit drives the <code>out2_no</code> in the opposite
polarity.</p>

#### LOOP field

<p>System Loopback. If set, the transmitter is internally connected to the
receiver. The <code>tx_o</code> output is set to <code>1</code>.</p>

#### LINE_LOOPBACK field

<p>Line Loopback. If set, the <code>rx_i</code> input is internally connected to the
<code>tx_o</code> output.</p>

### LSR register

- Absolute Address: 0x114
- Base Offset: 0x14
- Size: 0x4

<p>Line Status Register</p>

|Bits|    Identifier    | Access|Reset|Name|
|----|------------------|-------|-----|----|
|  0 |        DR        |   r   | 0x0 |  — |
|  1 |        OE        |r, rclr| 0x0 |  — |
|  2 |        PE        |r, rclr| 0x0 |  — |
|  3 |        FE        |r, rclr| 0x0 |  — |
|  4 |        BI        |r, rclr| 0x0 |  — |
|  5 |       THRE       |   r   | 0x1 |  — |
|  6 |       TEMT       |   r   | 0x1 |  — |
|  7 |ERROR_IN_RCVR_FIFO|   r   | 0x0 |  — |

#### DR field

<p>Data Ready. When set, indicates that the RX FIFO (or RBR in non-FIFO
mode) contains data.</p>

#### OE field

<p>Overrun Error. When set, indicates that the RX FIFO (or Receiver Buffer
Register in Non-FIFO Mode) is full when new character is received. In FIFO Mode, the new character
is dropped. In non-FIFO mode, the existing character in the RBR is overwritten.
This bit triggers the Receiver Line Status Interrupt.</p>

#### PE field

<p>Parity Error. When set, indicates that the character at the top of the receiver
FIFO (or RBR in non-FIFO mode) has a parity error. This bit triggers the
Receiver Line Status Interrupt.</p>

#### FE field

<p>Framing Error. When set, indicates that the received character is missing a
stop bit. In FIFO mode, this bit is set when the character reaches the top of
the FIFO. In non-FIFO mode, this bit is set when the character enters the RBR.
This bit triggers the Receiver Line Status Interrupt.</p>

#### BI field

<p>Break Interrupt. When set, indicates that the <code>rx_i</code> input is <code>0</code> for an entire
frame's time (start + data + parity + stop bits). In FIFO mode, this bit set
when the character reaches the top of the receiver FIFO. In non-FIFO mode, this
bit is set when the character enters the RBR. This bit triggers the Receiver
Line Status Interrupt.</p>

#### THRE field

<p>Transmitter Holding Register Empty. When set, indicates that the TX FIFO (or
THR in non-FIFO mode) is empty. Clearing the Transmitter Holding Register Empty
Interrupt does NOT clear this bit.</p>

#### TEMT field

<p>Transmitter Empty. When set, indicates that the transmitter shift register and
the transmitter FIFO (or THR in non-FIFO mode) are empty.</p>

#### ERROR_IN_RCVR_FIFO field

<p>Error in Receiver FIFO. When set, indicates that the receiver FIFO or (RBR in
non-FIFO mode) has the parity, framing, or break error. In other words, at
least one of the PE, FE, and BI bits is set.</p>

### MSR register

- Absolute Address: 0x118
- Base Offset: 0x18
- Size: 0x4

<p>Modem Status Register</p>

|Bits|Identifier| Access|Reset|Name|
|----|----------|-------|-----|----|
|  0 |   DCTS   |r, rclr| 0x0 |  — |
|  1 |   DDSR   |r, rclr| 0x0 |  — |
|  2 |   TERI   |r, rclr| 0x0 |  — |
|  3 |   DDCD   |r, rclr| 0x0 |  — |
|  4 |    CTS   |   r   | 0x0 |  — |
|  5 |    DSR   |   r   | 0x0 |  — |
|  6 |    RI    |   r   | 0x0 |  — |
|  7 |    DCD   |   r   | 0x0 |  — |

#### DCTS field

<p>Delta Clear to Send. When set, indicates that the <code>CTS</code> bit has changed since
the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### DDSR field

<p>Delta Data Set Ready. When set, indicates that the <code>DSR</code> bit has changed since
the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### TERI field

<p>Trailing Edge Ring Indicator. When set, indicates that the <code>RI</code> bit has changed
from a <code>1</code> to a <code>0</code>. This bit triggers the Modem Status Interrupt.</p>

#### DDCD field

<p>Delta Data Carrier Detect. When set, indicates that the <code>DCD</code> bit has changed
since the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### CTS field

<p>Clear to Send. This bit is the active-low version of the <code>cts_ni</code> input.</p>

#### DSR field

<p>Data Set Ready. This bit is the active-low version of the <code>dsr_ni</code> input.</p>

#### RI field

<p>Ring Indicator. This bit is the active-low version of the <code>ri_ni</code> input.</p>

#### DCD field

<p>Data Carrier Detect. This bit is the active-low version of the <code>dcd_ni</code>
input.</p>

### SCR register

- Absolute Address: 0x11C
- Base Offset: 0x1C
- Size: 0x4

<p>Scratch Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|    SCR   |  rw  | 0x0 |  — |

#### SCR field

<p>Scratch. Holds user data.</p>

### ECR register

- Absolute Address: 0x120
- Base Offset: 0x20
- Size: 0x4

<p>Extended Control Register</p>

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
| 1:0|RCVR_TRIGGER_MS2B|  rw  | 0x0 |  — |

#### RCVR_TRIGGER_MS2B field

<p>Receiver FIFO Trigger Level Most Significant 2 Bits. To configure the least
significant 2 bits, use the <code>FCR.RCVR_TRIGGER</code> register field. The
configurations for the trigger levels are:
 * <code>0x0</code> -    1 character
 * <code>0x1</code> -    4 characters
 * <code>0x2</code> -    8 characters
 * <code>0x3</code> -   14 characters
 * <code>0x4</code> -   32 characters
 * <code>0x5</code> -   64 characters
 * <code>0x6</code> -  128 characters
 * <code>0x7</code> -  256 characters
 * <code>0x8</code> -  512 characters
 * <code>0x9</code> - 1024 characters
 * <code>0xA</code> - 2048 characters
 * <code>0xB</code> - 4096 characters</p>

### ITR register

- Absolute Address: 0x124
- Base Offset: 0x24
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   TRBFI  |  rw  | 0x0 |  — |
|  1 |   TTBEI  |  rw  | 0x0 |  — |
|  2 |   TLSI   |  rw  | 0x0 |  — |
|  3 |   TDSSI  |  rw  | 0x0 |  — |
|  4 |   TFEI   |  rw  | 0x0 |  — |
|  5 |   TRTI   |  rw  | 0x0 |  — |

#### TRBFI field

<p>Test Receiver Buffer Full (Received Data Ready) Interrupt. Writing <code>1</code> forces
the interrupt and writing <code>0</code> releases it.</p>

#### TTBEI field

<p>Test Transmitter Buffer Empty (Transmitter Holding Register Empty) Interrupt.
Writing <code>1</code> forces the interrupt and writing <code>0</code> releases it.</p>

#### TLSI field

<p>Test (Receiver) Line Status Interrupt. Writing <code>1</code> forces the interrupt and
writing <code>0</code> releases it.</p>

#### TDSSI field

<p>Test (Delta Status of) Modem Status Interrupt. Writing <code>1</code> forces the
interrupt and writing <code>0</code> releases it.</p>

#### TFEI field

<p>Test FIFO Error Interrupt. Writing <code>1</code> forces the interrupt and writing <code>0</code>
releases it.</p>

#### TRTI field

<p>Test Reception Timeout Interrupt. Writing a <code>1</code> forces the interrupt and
writing <code>0</code> releases it.</p>

## log_engine address map

- Absolute Address: 0x200
- Base Offset: 0x200
- Size: 0x80

<p>Log Engine</p>

|Offset|   Identifier  |Name|
|------|---------------|----|
| 0x00 |      CTRL     |  — |
| 0x04 |LOG_REGION_SIZE|  — |
| 0x08 |LOG_REGION_ADDR|  — |
| 0x10 | LOG_WRITE_ADDR|  — |
| 0x14 |  INTR_STATUS  |  — |
| 0x18 |  INTR_ENABLE  |  — |
| 0x1C |   INTR_TEST   |  — |
| 0x40 |  LOG_CTRL[0]  |  — |
| 0x44 |  LOG_CTRL[1]  |  — |
| 0x48 |  LOG_CTRL[2]  |  — |
| 0x4C |  LOG_CTRL[3]  |  — |
| 0x50 |  LOG_CTRL[4]  |  — |
| 0x54 |  LOG_CTRL[5]  |  — |
| 0x58 |  LOG_CTRL[6]  |  — |
| 0x5C |  LOG_CTRL[7]  |  — |
| 0x60 |  LOG_CTRL[8]  |  — |
| 0x64 |  LOG_CTRL[9]  |  — |
| 0x68 |  LOG_CTRL[10] |  — |
| 0x6C |  LOG_CTRL[11] |  — |
| 0x70 |  LOG_CTRL[12] |  — |
| 0x74 |  LOG_CTRL[13] |  — |
| 0x78 |  LOG_CTRL[14] |  — |
| 0x7C |  LOG_CTRL[15] |  — |

### CTRL register

- Absolute Address: 0x200
- Base Offset: 0x0
- Size: 0x4

<p>Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |    EN    |  rw  | 0x0 |  — |

#### EN field

<p>Log Engine Enable. When set, enables the Log Engine. When unset, disables the
Log Engine and resets all FSMs, flops, and FIFOs.</p>

### LOG_REGION_SIZE register

- Absolute Address: 0x204
- Base Offset: 0x4
- Size: 0x4

<p>Log Region Size Register</p>

|Bits|   Identifier  |Access|Reset|Name|
|----|---------------|------|-----|----|
|19:0|LOG_REGION_SIZE|  rw  | 0x0 |  — |

#### LOG_REGION_SIZE field

<p>Log Region Size. Specified in bytes. Needs to be a multiple of 16.</p>

### LOG_REGION_ADDR register

- Absolute Address: 0x208
- Base Offset: 0x8
- Size: 0x8

<p>Log Region Address Register</p>

| Bits|    Identifier    |Access|Reset|Name|
|-----|------------------|------|-----|----|
| 31:0|LOG_REGION_ADDR_LO|  rw  | 0x0 |  — |
|63:32|LOG_REGION_ADDR_HI|  rw  | 0x0 |  — |

#### LOG_REGION_ADDR_LO field

<p>Log Region Start Address Low.</p>

#### LOG_REGION_ADDR_HI field

<p>Log Region Start Address High.</p>

### LOG_WRITE_ADDR register

- Absolute Address: 0x210
- Base Offset: 0x10
- Size: 0x4

<p>Log Write Address Register</p>

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|31:0|LOG_WRITE_ADDR|  rw  | 0x0 |  — |

#### LOG_WRITE_ADDR field

<p>Log Write Address. This is the address where the log data is written to.</p>

### INTR_STATUS register

- Absolute Address: 0x214
- Base Offset: 0x14
- Size: 0x4

<p>Interrupt Status Register</p>

|Bits|  Identifier |  Access |Reset|Name|
|----|-------------|---------|-----|----|
|  0 |LOG_FETCH_ERR|rw, woclr| 0x0 |  — |
|  4 |LOG_WRITE_ERR|rw, woclr| 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt. Asserted when the bus for fetching log data returns
an error.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt. Asserted when the bus for writing log data returns
an error.</p>

### INTR_ENABLE register

- Absolute Address: 0x218
- Base Offset: 0x18
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |LOG_FETCH_ERR|  rw  | 0x0 |  — |
|  4 |LOG_WRITE_ERR|  rw  | 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt Enable.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt Enable.</p>

### INTR_TEST register

- Absolute Address: 0x21C
- Base Offset: 0x1C
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |LOG_FETCH_ERR|   w  | 0x0 |  — |
|  4 |LOG_WRITE_ERR|   w  | 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt Test. Writing <code>1</code> forces the interrupt.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt Test. Writing <code>1</code> forces the interrupt.</p>

### LOG_CTRL register

- Absolute Address: 0x240
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x244
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x248
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x24C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x250
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x254
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x258
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x25C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x260
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x264
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x268
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x26C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x270
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x274
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x278
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x27C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

## uart_log_engine_wrap address map

- Absolute Address: 0x400
- Base Offset: 0x0
- Size: 0x280
- Array Dimensions: [4]
- Array Stride: 0x400
- Total Size: 0x1000

|Offset|     Identifier     |            Name           |
|------|--------------------|---------------------------|
| 0x000|uart_log_engine_ctrl|             —             |
| 0x100|        uart        |UART 16550 Main Address Map|
| 0x200|     log_engine     |             —             |

## uart_log_engine_ctrl address map

- Absolute Address: 0x400
- Base Offset: 0x0
- Size: 0x4

|Offset|Identifier|Name|
|------|----------|----|
|  0x0 |   CTRL   |  — |

### CTRL register

- Absolute Address: 0x400
- Base Offset: 0x0
- Size: 0x4

<p>Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  UART_EN |  rw  | 0x0 |  — |

#### UART_EN field

<p>UART Enable. When set, the pad-mux downstream will be forced to accept UART
traffic.</p>

## uart address map

- Absolute Address: 0x500
- Base Offset: 0x100
- Size: 0x28

<p>Contains the mode-independent registers and the read-only registers accessible only
when <code>DLAB = 0</code>.</p>

|Offset|Identifier|Name|
|------|----------|----|
| 0x00 |    RBR   |  — |
| 0x04 |    IER   |  — |
| 0x08 |    IIR   |  — |
| 0x0C |    LCR   |  — |
| 0x10 |    MCR   |  — |
| 0x14 |    LSR   |  — |
| 0x18 |    MSR   |  — |
| 0x1C |    SCR   |  — |
| 0x20 |    ECR   |  — |
| 0x24 |    ITR   |  — |

### RBR register

- Absolute Address: 0x500
- Base Offset: 0x0
- Size: 0x4

<p>Receiver Buffer Register</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |r, ruser| 0x0 |  — |

#### DATA field

<p>Received Data. Contains a received character. If FIFOs are enabled, this field
points to the bottom of the RX FIFO. Otherwise, this field points to a single-
byte Receiver Buffer Register.</p>

### IER register

- Absolute Address: 0x504
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   ERBFI  |  rw  | 0x0 |  — |
|  1 |   ETBEI  |  rw  | 0x0 |  — |
|  2 |   ELSI   |  rw  | 0x0 |  — |
|  3 |   EDSSI  |  rw  | 0x0 |  — |
|  4 |   EFEI   |  rw  | 0x0 |  — |

#### ERBFI field

<p>Enable Receiver Buffer Full (Received Data Ready) Interrupt.</p>

#### ETBEI field

<p>Enable Transmitter Buffer Empty (Transmitter Holding Register Empty)
Interrupt.</p>

#### ELSI field

<p>Enable (Receiver) Line Status Interrupt.</p>

#### EDSSI field

<p>Enable (Delta Status of) Modem Status Interrupt.</p>

#### EFEI field

<p>Enable FIFO Error Interrupt.</p>

### IIR register

- Absolute Address: 0x508
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Identification Register</p>

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
|  0 |INTERRUPT_PENDING|   r  | 0x1 |  — |
| 3:1|   INTERRUPT_ID  |   r  | 0x0 |  — |
| 7:6|  FIFOS_ENABLED  |   r  | 0x0 |  — |

#### INTERRUPT_PENDING field

<p>Interrupt Pending. Active-low.</p>

#### INTERRUPT_ID field

<p>Interrupt ID:
* <code>0x7</code> - FIFO Error Interrupt                         (priority 0)
* <code>0x3</code> - Receiver Line Status Interrupt               (priority 1)
* <code>0x6</code> - Reception Timeout Interrupt                  (priority 2)
* <code>0x2</code> - Received Data Ready Interrupt                (priority 3)
* <code>0x1</code> - Transmitter Holding Register Empty Interrupt (priority 4)
* <code>0x0</code> - Modem Status Interrupt                       (priority 5)</p>

#### FIFOS_ENABLED field

<p>FIFOs Enabled:
* <code>0x0</code> - FIFOs are disabled
* <code>0x3</code> - FIFOs are enabled</p>

### LCR register

- Absolute Address: 0x50C
- Base Offset: 0xC
- Size: 0x4

<p>Line Control Register</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
| 1:0|     WLS    |  rw  | 0x0 |  — |
|  2 |     STB    |  rw  | 0x0 |  — |
|  3 |     PEN    |  rw  | 0x0 |  — |
|  4 |     EPS    |  rw  | 0x0 |  — |
|  5 |STICK_PARITY|  rw  | 0x0 |  — |
|  6 |  SET_BREAK |  rw  | 0x0 |  — |
|  7 |    DLAB    |  rw  | 0x0 |  — |

#### WLS field

<p>Word Length Select:
* <code>0x0</code> - 5 bits per character
* <code>0x1</code> - 6 bits per character
* <code>0x2</code> - 7 bits per character
* <code>0x3</code> - 8 bits per character</p>

#### STB field

<p>Stop Bits:
* <code>0</code> - 1 stop bit.
* <code>1</code> - 2 stop bits (or 1.5 stop bits if word length is set to 5 bits)</p>

#### PEN field

<p>Parity Enable.</p>

#### EPS field

<p>Even Parity Select:
* <code>1</code> - even parity
* <code>0</code> - odd parity</p>

#### STICK_PARITY field

<p>Stick Parity. If set, forces the transmit and received parity bits to be <code>0</code> if
even parity is selected and <code>1</code> if odd parity is selected.</p>

#### SET_BREAK field

<p>Set Break. If set, forces the <code>tx_o</code> output to <code>0</code> to cause a break condition
on the receiving UART.</p>

#### DLAB field

<p>Divisor Latch Access Bit. If set, allows access to the <code>DLL</code> and <code>DLM</code> registers
when accessing addresses <code>0x0</code> and <code>0x4</code>, respectively. If unset, allows access
to the <code>THR</code>, <code>RBR</code>, and <code>IIR</code> registers.</p>

### MCR register

- Absolute Address: 0x510
- Base Offset: 0x10
- Size: 0x4

<p>Modem Control Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |     DTR     |  rw  | 0x0 |  — |
|  1 |     RTS     |  rw  | 0x0 |  — |
|  2 |     OUT1    |  rw  | 0x0 |  — |
|  3 |     OUT2    |  rw  | 0x0 |  — |
|  4 |     LOOP    |  rw  | 0x0 |  — |
|  5 |LINE_LOOPBACK|  rw  | 0x0 |  — |

#### DTR field

<p>Data Terminal Ready. Writing to this bit drives the <code>dtr_no</code> output in the
opposite polarity.</p>

#### RTS field

<p>Request to Send. Writing to this bit drives the <code>rts_no</code> output in the opposite
polarity.</p>

#### OUT1 field

<p>User Output 1. Writing to this bit drives the <code>out1_no</code> in the opposite
polarity.</p>

#### OUT2 field

<p>User Output 2. Writing to this bit drives the <code>out2_no</code> in the opposite
polarity.</p>

#### LOOP field

<p>System Loopback. If set, the transmitter is internally connected to the
receiver. The <code>tx_o</code> output is set to <code>1</code>.</p>

#### LINE_LOOPBACK field

<p>Line Loopback. If set, the <code>rx_i</code> input is internally connected to the
<code>tx_o</code> output.</p>

### LSR register

- Absolute Address: 0x514
- Base Offset: 0x14
- Size: 0x4

<p>Line Status Register</p>

|Bits|    Identifier    | Access|Reset|Name|
|----|------------------|-------|-----|----|
|  0 |        DR        |   r   | 0x0 |  — |
|  1 |        OE        |r, rclr| 0x0 |  — |
|  2 |        PE        |r, rclr| 0x0 |  — |
|  3 |        FE        |r, rclr| 0x0 |  — |
|  4 |        BI        |r, rclr| 0x0 |  — |
|  5 |       THRE       |   r   | 0x1 |  — |
|  6 |       TEMT       |   r   | 0x1 |  — |
|  7 |ERROR_IN_RCVR_FIFO|   r   | 0x0 |  — |

#### DR field

<p>Data Ready. When set, indicates that the RX FIFO (or RBR in non-FIFO
mode) contains data.</p>

#### OE field

<p>Overrun Error. When set, indicates that the RX FIFO (or Receiver Buffer
Register in Non-FIFO Mode) is full when new character is received. In FIFO Mode, the new character
is dropped. In non-FIFO mode, the existing character in the RBR is overwritten.
This bit triggers the Receiver Line Status Interrupt.</p>

#### PE field

<p>Parity Error. When set, indicates that the character at the top of the receiver
FIFO (or RBR in non-FIFO mode) has a parity error. This bit triggers the
Receiver Line Status Interrupt.</p>

#### FE field

<p>Framing Error. When set, indicates that the received character is missing a
stop bit. In FIFO mode, this bit is set when the character reaches the top of
the FIFO. In non-FIFO mode, this bit is set when the character enters the RBR.
This bit triggers the Receiver Line Status Interrupt.</p>

#### BI field

<p>Break Interrupt. When set, indicates that the <code>rx_i</code> input is <code>0</code> for an entire
frame's time (start + data + parity + stop bits). In FIFO mode, this bit set
when the character reaches the top of the receiver FIFO. In non-FIFO mode, this
bit is set when the character enters the RBR. This bit triggers the Receiver
Line Status Interrupt.</p>

#### THRE field

<p>Transmitter Holding Register Empty. When set, indicates that the TX FIFO (or
THR in non-FIFO mode) is empty. Clearing the Transmitter Holding Register Empty
Interrupt does NOT clear this bit.</p>

#### TEMT field

<p>Transmitter Empty. When set, indicates that the transmitter shift register and
the transmitter FIFO (or THR in non-FIFO mode) are empty.</p>

#### ERROR_IN_RCVR_FIFO field

<p>Error in Receiver FIFO. When set, indicates that the receiver FIFO or (RBR in
non-FIFO mode) has the parity, framing, or break error. In other words, at
least one of the PE, FE, and BI bits is set.</p>

### MSR register

- Absolute Address: 0x518
- Base Offset: 0x18
- Size: 0x4

<p>Modem Status Register</p>

|Bits|Identifier| Access|Reset|Name|
|----|----------|-------|-----|----|
|  0 |   DCTS   |r, rclr| 0x0 |  — |
|  1 |   DDSR   |r, rclr| 0x0 |  — |
|  2 |   TERI   |r, rclr| 0x0 |  — |
|  3 |   DDCD   |r, rclr| 0x0 |  — |
|  4 |    CTS   |   r   | 0x0 |  — |
|  5 |    DSR   |   r   | 0x0 |  — |
|  6 |    RI    |   r   | 0x0 |  — |
|  7 |    DCD   |   r   | 0x0 |  — |

#### DCTS field

<p>Delta Clear to Send. When set, indicates that the <code>CTS</code> bit has changed since
the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### DDSR field

<p>Delta Data Set Ready. When set, indicates that the <code>DSR</code> bit has changed since
the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### TERI field

<p>Trailing Edge Ring Indicator. When set, indicates that the <code>RI</code> bit has changed
from a <code>1</code> to a <code>0</code>. This bit triggers the Modem Status Interrupt.</p>

#### DDCD field

<p>Delta Data Carrier Detect. When set, indicates that the <code>DCD</code> bit has changed
since the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### CTS field

<p>Clear to Send. This bit is the active-low version of the <code>cts_ni</code> input.</p>

#### DSR field

<p>Data Set Ready. This bit is the active-low version of the <code>dsr_ni</code> input.</p>

#### RI field

<p>Ring Indicator. This bit is the active-low version of the <code>ri_ni</code> input.</p>

#### DCD field

<p>Data Carrier Detect. This bit is the active-low version of the <code>dcd_ni</code>
input.</p>

### SCR register

- Absolute Address: 0x51C
- Base Offset: 0x1C
- Size: 0x4

<p>Scratch Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|    SCR   |  rw  | 0x0 |  — |

#### SCR field

<p>Scratch. Holds user data.</p>

### ECR register

- Absolute Address: 0x520
- Base Offset: 0x20
- Size: 0x4

<p>Extended Control Register</p>

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
| 1:0|RCVR_TRIGGER_MS2B|  rw  | 0x0 |  — |

#### RCVR_TRIGGER_MS2B field

<p>Receiver FIFO Trigger Level Most Significant 2 Bits. To configure the least
significant 2 bits, use the <code>FCR.RCVR_TRIGGER</code> register field. The
configurations for the trigger levels are:
 * <code>0x0</code> -    1 character
 * <code>0x1</code> -    4 characters
 * <code>0x2</code> -    8 characters
 * <code>0x3</code> -   14 characters
 * <code>0x4</code> -   32 characters
 * <code>0x5</code> -   64 characters
 * <code>0x6</code> -  128 characters
 * <code>0x7</code> -  256 characters
 * <code>0x8</code> -  512 characters
 * <code>0x9</code> - 1024 characters
 * <code>0xA</code> - 2048 characters
 * <code>0xB</code> - 4096 characters</p>

### ITR register

- Absolute Address: 0x524
- Base Offset: 0x24
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   TRBFI  |  rw  | 0x0 |  — |
|  1 |   TTBEI  |  rw  | 0x0 |  — |
|  2 |   TLSI   |  rw  | 0x0 |  — |
|  3 |   TDSSI  |  rw  | 0x0 |  — |
|  4 |   TFEI   |  rw  | 0x0 |  — |
|  5 |   TRTI   |  rw  | 0x0 |  — |

#### TRBFI field

<p>Test Receiver Buffer Full (Received Data Ready) Interrupt. Writing <code>1</code> forces
the interrupt and writing <code>0</code> releases it.</p>

#### TTBEI field

<p>Test Transmitter Buffer Empty (Transmitter Holding Register Empty) Interrupt.
Writing <code>1</code> forces the interrupt and writing <code>0</code> releases it.</p>

#### TLSI field

<p>Test (Receiver) Line Status Interrupt. Writing <code>1</code> forces the interrupt and
writing <code>0</code> releases it.</p>

#### TDSSI field

<p>Test (Delta Status of) Modem Status Interrupt. Writing <code>1</code> forces the
interrupt and writing <code>0</code> releases it.</p>

#### TFEI field

<p>Test FIFO Error Interrupt. Writing <code>1</code> forces the interrupt and writing <code>0</code>
releases it.</p>

#### TRTI field

<p>Test Reception Timeout Interrupt. Writing a <code>1</code> forces the interrupt and
writing <code>0</code> releases it.</p>

## log_engine address map

- Absolute Address: 0x600
- Base Offset: 0x200
- Size: 0x80

<p>Log Engine</p>

|Offset|   Identifier  |Name|
|------|---------------|----|
| 0x00 |      CTRL     |  — |
| 0x04 |LOG_REGION_SIZE|  — |
| 0x08 |LOG_REGION_ADDR|  — |
| 0x10 | LOG_WRITE_ADDR|  — |
| 0x14 |  INTR_STATUS  |  — |
| 0x18 |  INTR_ENABLE  |  — |
| 0x1C |   INTR_TEST   |  — |
| 0x40 |  LOG_CTRL[0]  |  — |
| 0x44 |  LOG_CTRL[1]  |  — |
| 0x48 |  LOG_CTRL[2]  |  — |
| 0x4C |  LOG_CTRL[3]  |  — |
| 0x50 |  LOG_CTRL[4]  |  — |
| 0x54 |  LOG_CTRL[5]  |  — |
| 0x58 |  LOG_CTRL[6]  |  — |
| 0x5C |  LOG_CTRL[7]  |  — |
| 0x60 |  LOG_CTRL[8]  |  — |
| 0x64 |  LOG_CTRL[9]  |  — |
| 0x68 |  LOG_CTRL[10] |  — |
| 0x6C |  LOG_CTRL[11] |  — |
| 0x70 |  LOG_CTRL[12] |  — |
| 0x74 |  LOG_CTRL[13] |  — |
| 0x78 |  LOG_CTRL[14] |  — |
| 0x7C |  LOG_CTRL[15] |  — |

### CTRL register

- Absolute Address: 0x600
- Base Offset: 0x0
- Size: 0x4

<p>Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |    EN    |  rw  | 0x0 |  — |

#### EN field

<p>Log Engine Enable. When set, enables the Log Engine. When unset, disables the
Log Engine and resets all FSMs, flops, and FIFOs.</p>

### LOG_REGION_SIZE register

- Absolute Address: 0x604
- Base Offset: 0x4
- Size: 0x4

<p>Log Region Size Register</p>

|Bits|   Identifier  |Access|Reset|Name|
|----|---------------|------|-----|----|
|19:0|LOG_REGION_SIZE|  rw  | 0x0 |  — |

#### LOG_REGION_SIZE field

<p>Log Region Size. Specified in bytes. Needs to be a multiple of 16.</p>

### LOG_REGION_ADDR register

- Absolute Address: 0x608
- Base Offset: 0x8
- Size: 0x8

<p>Log Region Address Register</p>

| Bits|    Identifier    |Access|Reset|Name|
|-----|------------------|------|-----|----|
| 31:0|LOG_REGION_ADDR_LO|  rw  | 0x0 |  — |
|63:32|LOG_REGION_ADDR_HI|  rw  | 0x0 |  — |

#### LOG_REGION_ADDR_LO field

<p>Log Region Start Address Low.</p>

#### LOG_REGION_ADDR_HI field

<p>Log Region Start Address High.</p>

### LOG_WRITE_ADDR register

- Absolute Address: 0x610
- Base Offset: 0x10
- Size: 0x4

<p>Log Write Address Register</p>

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|31:0|LOG_WRITE_ADDR|  rw  | 0x0 |  — |

#### LOG_WRITE_ADDR field

<p>Log Write Address. This is the address where the log data is written to.</p>

### INTR_STATUS register

- Absolute Address: 0x614
- Base Offset: 0x14
- Size: 0x4

<p>Interrupt Status Register</p>

|Bits|  Identifier |  Access |Reset|Name|
|----|-------------|---------|-----|----|
|  0 |LOG_FETCH_ERR|rw, woclr| 0x0 |  — |
|  4 |LOG_WRITE_ERR|rw, woclr| 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt. Asserted when the bus for fetching log data returns
an error.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt. Asserted when the bus for writing log data returns
an error.</p>

### INTR_ENABLE register

- Absolute Address: 0x618
- Base Offset: 0x18
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |LOG_FETCH_ERR|  rw  | 0x0 |  — |
|  4 |LOG_WRITE_ERR|  rw  | 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt Enable.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt Enable.</p>

### INTR_TEST register

- Absolute Address: 0x61C
- Base Offset: 0x1C
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |LOG_FETCH_ERR|   w  | 0x0 |  — |
|  4 |LOG_WRITE_ERR|   w  | 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt Test. Writing <code>1</code> forces the interrupt.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt Test. Writing <code>1</code> forces the interrupt.</p>

### LOG_CTRL register

- Absolute Address: 0x640
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x644
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x648
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x64C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x650
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x654
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x658
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x65C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x660
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x664
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x668
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x66C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x670
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x674
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x678
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0x67C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

## uart_log_engine_wrap address map

- Absolute Address: 0x800
- Base Offset: 0x0
- Size: 0x280
- Array Dimensions: [4]
- Array Stride: 0x400
- Total Size: 0x1000

|Offset|     Identifier     |            Name           |
|------|--------------------|---------------------------|
| 0x000|uart_log_engine_ctrl|             —             |
| 0x100|        uart        |UART 16550 Main Address Map|
| 0x200|     log_engine     |             —             |

## uart_log_engine_ctrl address map

- Absolute Address: 0x800
- Base Offset: 0x0
- Size: 0x4

|Offset|Identifier|Name|
|------|----------|----|
|  0x0 |   CTRL   |  — |

### CTRL register

- Absolute Address: 0x800
- Base Offset: 0x0
- Size: 0x4

<p>Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  UART_EN |  rw  | 0x0 |  — |

#### UART_EN field

<p>UART Enable. When set, the pad-mux downstream will be forced to accept UART
traffic.</p>

## uart address map

- Absolute Address: 0x900
- Base Offset: 0x100
- Size: 0x28

<p>Contains the mode-independent registers and the read-only registers accessible only
when <code>DLAB = 0</code>.</p>

|Offset|Identifier|Name|
|------|----------|----|
| 0x00 |    RBR   |  — |
| 0x04 |    IER   |  — |
| 0x08 |    IIR   |  — |
| 0x0C |    LCR   |  — |
| 0x10 |    MCR   |  — |
| 0x14 |    LSR   |  — |
| 0x18 |    MSR   |  — |
| 0x1C |    SCR   |  — |
| 0x20 |    ECR   |  — |
| 0x24 |    ITR   |  — |

### RBR register

- Absolute Address: 0x900
- Base Offset: 0x0
- Size: 0x4

<p>Receiver Buffer Register</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |r, ruser| 0x0 |  — |

#### DATA field

<p>Received Data. Contains a received character. If FIFOs are enabled, this field
points to the bottom of the RX FIFO. Otherwise, this field points to a single-
byte Receiver Buffer Register.</p>

### IER register

- Absolute Address: 0x904
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   ERBFI  |  rw  | 0x0 |  — |
|  1 |   ETBEI  |  rw  | 0x0 |  — |
|  2 |   ELSI   |  rw  | 0x0 |  — |
|  3 |   EDSSI  |  rw  | 0x0 |  — |
|  4 |   EFEI   |  rw  | 0x0 |  — |

#### ERBFI field

<p>Enable Receiver Buffer Full (Received Data Ready) Interrupt.</p>

#### ETBEI field

<p>Enable Transmitter Buffer Empty (Transmitter Holding Register Empty)
Interrupt.</p>

#### ELSI field

<p>Enable (Receiver) Line Status Interrupt.</p>

#### EDSSI field

<p>Enable (Delta Status of) Modem Status Interrupt.</p>

#### EFEI field

<p>Enable FIFO Error Interrupt.</p>

### IIR register

- Absolute Address: 0x908
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Identification Register</p>

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
|  0 |INTERRUPT_PENDING|   r  | 0x1 |  — |
| 3:1|   INTERRUPT_ID  |   r  | 0x0 |  — |
| 7:6|  FIFOS_ENABLED  |   r  | 0x0 |  — |

#### INTERRUPT_PENDING field

<p>Interrupt Pending. Active-low.</p>

#### INTERRUPT_ID field

<p>Interrupt ID:
* <code>0x7</code> - FIFO Error Interrupt                         (priority 0)
* <code>0x3</code> - Receiver Line Status Interrupt               (priority 1)
* <code>0x6</code> - Reception Timeout Interrupt                  (priority 2)
* <code>0x2</code> - Received Data Ready Interrupt                (priority 3)
* <code>0x1</code> - Transmitter Holding Register Empty Interrupt (priority 4)
* <code>0x0</code> - Modem Status Interrupt                       (priority 5)</p>

#### FIFOS_ENABLED field

<p>FIFOs Enabled:
* <code>0x0</code> - FIFOs are disabled
* <code>0x3</code> - FIFOs are enabled</p>

### LCR register

- Absolute Address: 0x90C
- Base Offset: 0xC
- Size: 0x4

<p>Line Control Register</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
| 1:0|     WLS    |  rw  | 0x0 |  — |
|  2 |     STB    |  rw  | 0x0 |  — |
|  3 |     PEN    |  rw  | 0x0 |  — |
|  4 |     EPS    |  rw  | 0x0 |  — |
|  5 |STICK_PARITY|  rw  | 0x0 |  — |
|  6 |  SET_BREAK |  rw  | 0x0 |  — |
|  7 |    DLAB    |  rw  | 0x0 |  — |

#### WLS field

<p>Word Length Select:
* <code>0x0</code> - 5 bits per character
* <code>0x1</code> - 6 bits per character
* <code>0x2</code> - 7 bits per character
* <code>0x3</code> - 8 bits per character</p>

#### STB field

<p>Stop Bits:
* <code>0</code> - 1 stop bit.
* <code>1</code> - 2 stop bits (or 1.5 stop bits if word length is set to 5 bits)</p>

#### PEN field

<p>Parity Enable.</p>

#### EPS field

<p>Even Parity Select:
* <code>1</code> - even parity
* <code>0</code> - odd parity</p>

#### STICK_PARITY field

<p>Stick Parity. If set, forces the transmit and received parity bits to be <code>0</code> if
even parity is selected and <code>1</code> if odd parity is selected.</p>

#### SET_BREAK field

<p>Set Break. If set, forces the <code>tx_o</code> output to <code>0</code> to cause a break condition
on the receiving UART.</p>

#### DLAB field

<p>Divisor Latch Access Bit. If set, allows access to the <code>DLL</code> and <code>DLM</code> registers
when accessing addresses <code>0x0</code> and <code>0x4</code>, respectively. If unset, allows access
to the <code>THR</code>, <code>RBR</code>, and <code>IIR</code> registers.</p>

### MCR register

- Absolute Address: 0x910
- Base Offset: 0x10
- Size: 0x4

<p>Modem Control Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |     DTR     |  rw  | 0x0 |  — |
|  1 |     RTS     |  rw  | 0x0 |  — |
|  2 |     OUT1    |  rw  | 0x0 |  — |
|  3 |     OUT2    |  rw  | 0x0 |  — |
|  4 |     LOOP    |  rw  | 0x0 |  — |
|  5 |LINE_LOOPBACK|  rw  | 0x0 |  — |

#### DTR field

<p>Data Terminal Ready. Writing to this bit drives the <code>dtr_no</code> output in the
opposite polarity.</p>

#### RTS field

<p>Request to Send. Writing to this bit drives the <code>rts_no</code> output in the opposite
polarity.</p>

#### OUT1 field

<p>User Output 1. Writing to this bit drives the <code>out1_no</code> in the opposite
polarity.</p>

#### OUT2 field

<p>User Output 2. Writing to this bit drives the <code>out2_no</code> in the opposite
polarity.</p>

#### LOOP field

<p>System Loopback. If set, the transmitter is internally connected to the
receiver. The <code>tx_o</code> output is set to <code>1</code>.</p>

#### LINE_LOOPBACK field

<p>Line Loopback. If set, the <code>rx_i</code> input is internally connected to the
<code>tx_o</code> output.</p>

### LSR register

- Absolute Address: 0x914
- Base Offset: 0x14
- Size: 0x4

<p>Line Status Register</p>

|Bits|    Identifier    | Access|Reset|Name|
|----|------------------|-------|-----|----|
|  0 |        DR        |   r   | 0x0 |  — |
|  1 |        OE        |r, rclr| 0x0 |  — |
|  2 |        PE        |r, rclr| 0x0 |  — |
|  3 |        FE        |r, rclr| 0x0 |  — |
|  4 |        BI        |r, rclr| 0x0 |  — |
|  5 |       THRE       |   r   | 0x1 |  — |
|  6 |       TEMT       |   r   | 0x1 |  — |
|  7 |ERROR_IN_RCVR_FIFO|   r   | 0x0 |  — |

#### DR field

<p>Data Ready. When set, indicates that the RX FIFO (or RBR in non-FIFO
mode) contains data.</p>

#### OE field

<p>Overrun Error. When set, indicates that the RX FIFO (or Receiver Buffer
Register in Non-FIFO Mode) is full when new character is received. In FIFO Mode, the new character
is dropped. In non-FIFO mode, the existing character in the RBR is overwritten.
This bit triggers the Receiver Line Status Interrupt.</p>

#### PE field

<p>Parity Error. When set, indicates that the character at the top of the receiver
FIFO (or RBR in non-FIFO mode) has a parity error. This bit triggers the
Receiver Line Status Interrupt.</p>

#### FE field

<p>Framing Error. When set, indicates that the received character is missing a
stop bit. In FIFO mode, this bit is set when the character reaches the top of
the FIFO. In non-FIFO mode, this bit is set when the character enters the RBR.
This bit triggers the Receiver Line Status Interrupt.</p>

#### BI field

<p>Break Interrupt. When set, indicates that the <code>rx_i</code> input is <code>0</code> for an entire
frame's time (start + data + parity + stop bits). In FIFO mode, this bit set
when the character reaches the top of the receiver FIFO. In non-FIFO mode, this
bit is set when the character enters the RBR. This bit triggers the Receiver
Line Status Interrupt.</p>

#### THRE field

<p>Transmitter Holding Register Empty. When set, indicates that the TX FIFO (or
THR in non-FIFO mode) is empty. Clearing the Transmitter Holding Register Empty
Interrupt does NOT clear this bit.</p>

#### TEMT field

<p>Transmitter Empty. When set, indicates that the transmitter shift register and
the transmitter FIFO (or THR in non-FIFO mode) are empty.</p>

#### ERROR_IN_RCVR_FIFO field

<p>Error in Receiver FIFO. When set, indicates that the receiver FIFO or (RBR in
non-FIFO mode) has the parity, framing, or break error. In other words, at
least one of the PE, FE, and BI bits is set.</p>

### MSR register

- Absolute Address: 0x918
- Base Offset: 0x18
- Size: 0x4

<p>Modem Status Register</p>

|Bits|Identifier| Access|Reset|Name|
|----|----------|-------|-----|----|
|  0 |   DCTS   |r, rclr| 0x0 |  — |
|  1 |   DDSR   |r, rclr| 0x0 |  — |
|  2 |   TERI   |r, rclr| 0x0 |  — |
|  3 |   DDCD   |r, rclr| 0x0 |  — |
|  4 |    CTS   |   r   | 0x0 |  — |
|  5 |    DSR   |   r   | 0x0 |  — |
|  6 |    RI    |   r   | 0x0 |  — |
|  7 |    DCD   |   r   | 0x0 |  — |

#### DCTS field

<p>Delta Clear to Send. When set, indicates that the <code>CTS</code> bit has changed since
the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### DDSR field

<p>Delta Data Set Ready. When set, indicates that the <code>DSR</code> bit has changed since
the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### TERI field

<p>Trailing Edge Ring Indicator. When set, indicates that the <code>RI</code> bit has changed
from a <code>1</code> to a <code>0</code>. This bit triggers the Modem Status Interrupt.</p>

#### DDCD field

<p>Delta Data Carrier Detect. When set, indicates that the <code>DCD</code> bit has changed
since the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### CTS field

<p>Clear to Send. This bit is the active-low version of the <code>cts_ni</code> input.</p>

#### DSR field

<p>Data Set Ready. This bit is the active-low version of the <code>dsr_ni</code> input.</p>

#### RI field

<p>Ring Indicator. This bit is the active-low version of the <code>ri_ni</code> input.</p>

#### DCD field

<p>Data Carrier Detect. This bit is the active-low version of the <code>dcd_ni</code>
input.</p>

### SCR register

- Absolute Address: 0x91C
- Base Offset: 0x1C
- Size: 0x4

<p>Scratch Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|    SCR   |  rw  | 0x0 |  — |

#### SCR field

<p>Scratch. Holds user data.</p>

### ECR register

- Absolute Address: 0x920
- Base Offset: 0x20
- Size: 0x4

<p>Extended Control Register</p>

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
| 1:0|RCVR_TRIGGER_MS2B|  rw  | 0x0 |  — |

#### RCVR_TRIGGER_MS2B field

<p>Receiver FIFO Trigger Level Most Significant 2 Bits. To configure the least
significant 2 bits, use the <code>FCR.RCVR_TRIGGER</code> register field. The
configurations for the trigger levels are:
 * <code>0x0</code> -    1 character
 * <code>0x1</code> -    4 characters
 * <code>0x2</code> -    8 characters
 * <code>0x3</code> -   14 characters
 * <code>0x4</code> -   32 characters
 * <code>0x5</code> -   64 characters
 * <code>0x6</code> -  128 characters
 * <code>0x7</code> -  256 characters
 * <code>0x8</code> -  512 characters
 * <code>0x9</code> - 1024 characters
 * <code>0xA</code> - 2048 characters
 * <code>0xB</code> - 4096 characters</p>

### ITR register

- Absolute Address: 0x924
- Base Offset: 0x24
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   TRBFI  |  rw  | 0x0 |  — |
|  1 |   TTBEI  |  rw  | 0x0 |  — |
|  2 |   TLSI   |  rw  | 0x0 |  — |
|  3 |   TDSSI  |  rw  | 0x0 |  — |
|  4 |   TFEI   |  rw  | 0x0 |  — |
|  5 |   TRTI   |  rw  | 0x0 |  — |

#### TRBFI field

<p>Test Receiver Buffer Full (Received Data Ready) Interrupt. Writing <code>1</code> forces
the interrupt and writing <code>0</code> releases it.</p>

#### TTBEI field

<p>Test Transmitter Buffer Empty (Transmitter Holding Register Empty) Interrupt.
Writing <code>1</code> forces the interrupt and writing <code>0</code> releases it.</p>

#### TLSI field

<p>Test (Receiver) Line Status Interrupt. Writing <code>1</code> forces the interrupt and
writing <code>0</code> releases it.</p>

#### TDSSI field

<p>Test (Delta Status of) Modem Status Interrupt. Writing <code>1</code> forces the
interrupt and writing <code>0</code> releases it.</p>

#### TFEI field

<p>Test FIFO Error Interrupt. Writing <code>1</code> forces the interrupt and writing <code>0</code>
releases it.</p>

#### TRTI field

<p>Test Reception Timeout Interrupt. Writing a <code>1</code> forces the interrupt and
writing <code>0</code> releases it.</p>

## log_engine address map

- Absolute Address: 0xA00
- Base Offset: 0x200
- Size: 0x80

<p>Log Engine</p>

|Offset|   Identifier  |Name|
|------|---------------|----|
| 0x00 |      CTRL     |  — |
| 0x04 |LOG_REGION_SIZE|  — |
| 0x08 |LOG_REGION_ADDR|  — |
| 0x10 | LOG_WRITE_ADDR|  — |
| 0x14 |  INTR_STATUS  |  — |
| 0x18 |  INTR_ENABLE  |  — |
| 0x1C |   INTR_TEST   |  — |
| 0x40 |  LOG_CTRL[0]  |  — |
| 0x44 |  LOG_CTRL[1]  |  — |
| 0x48 |  LOG_CTRL[2]  |  — |
| 0x4C |  LOG_CTRL[3]  |  — |
| 0x50 |  LOG_CTRL[4]  |  — |
| 0x54 |  LOG_CTRL[5]  |  — |
| 0x58 |  LOG_CTRL[6]  |  — |
| 0x5C |  LOG_CTRL[7]  |  — |
| 0x60 |  LOG_CTRL[8]  |  — |
| 0x64 |  LOG_CTRL[9]  |  — |
| 0x68 |  LOG_CTRL[10] |  — |
| 0x6C |  LOG_CTRL[11] |  — |
| 0x70 |  LOG_CTRL[12] |  — |
| 0x74 |  LOG_CTRL[13] |  — |
| 0x78 |  LOG_CTRL[14] |  — |
| 0x7C |  LOG_CTRL[15] |  — |

### CTRL register

- Absolute Address: 0xA00
- Base Offset: 0x0
- Size: 0x4

<p>Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |    EN    |  rw  | 0x0 |  — |

#### EN field

<p>Log Engine Enable. When set, enables the Log Engine. When unset, disables the
Log Engine and resets all FSMs, flops, and FIFOs.</p>

### LOG_REGION_SIZE register

- Absolute Address: 0xA04
- Base Offset: 0x4
- Size: 0x4

<p>Log Region Size Register</p>

|Bits|   Identifier  |Access|Reset|Name|
|----|---------------|------|-----|----|
|19:0|LOG_REGION_SIZE|  rw  | 0x0 |  — |

#### LOG_REGION_SIZE field

<p>Log Region Size. Specified in bytes. Needs to be a multiple of 16.</p>

### LOG_REGION_ADDR register

- Absolute Address: 0xA08
- Base Offset: 0x8
- Size: 0x8

<p>Log Region Address Register</p>

| Bits|    Identifier    |Access|Reset|Name|
|-----|------------------|------|-----|----|
| 31:0|LOG_REGION_ADDR_LO|  rw  | 0x0 |  — |
|63:32|LOG_REGION_ADDR_HI|  rw  | 0x0 |  — |

#### LOG_REGION_ADDR_LO field

<p>Log Region Start Address Low.</p>

#### LOG_REGION_ADDR_HI field

<p>Log Region Start Address High.</p>

### LOG_WRITE_ADDR register

- Absolute Address: 0xA10
- Base Offset: 0x10
- Size: 0x4

<p>Log Write Address Register</p>

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|31:0|LOG_WRITE_ADDR|  rw  | 0x0 |  — |

#### LOG_WRITE_ADDR field

<p>Log Write Address. This is the address where the log data is written to.</p>

### INTR_STATUS register

- Absolute Address: 0xA14
- Base Offset: 0x14
- Size: 0x4

<p>Interrupt Status Register</p>

|Bits|  Identifier |  Access |Reset|Name|
|----|-------------|---------|-----|----|
|  0 |LOG_FETCH_ERR|rw, woclr| 0x0 |  — |
|  4 |LOG_WRITE_ERR|rw, woclr| 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt. Asserted when the bus for fetching log data returns
an error.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt. Asserted when the bus for writing log data returns
an error.</p>

### INTR_ENABLE register

- Absolute Address: 0xA18
- Base Offset: 0x18
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |LOG_FETCH_ERR|  rw  | 0x0 |  — |
|  4 |LOG_WRITE_ERR|  rw  | 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt Enable.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt Enable.</p>

### INTR_TEST register

- Absolute Address: 0xA1C
- Base Offset: 0x1C
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |LOG_FETCH_ERR|   w  | 0x0 |  — |
|  4 |LOG_WRITE_ERR|   w  | 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt Test. Writing <code>1</code> forces the interrupt.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt Test. Writing <code>1</code> forces the interrupt.</p>

### LOG_CTRL register

- Absolute Address: 0xA40
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA44
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA48
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA4C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA50
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA54
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA58
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA5C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA60
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA64
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA68
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA6C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA70
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA74
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA78
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xA7C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

## uart_log_engine_wrap address map

- Absolute Address: 0xC00
- Base Offset: 0x0
- Size: 0x280
- Array Dimensions: [4]
- Array Stride: 0x400
- Total Size: 0x1000

|Offset|     Identifier     |            Name           |
|------|--------------------|---------------------------|
| 0x000|uart_log_engine_ctrl|             —             |
| 0x100|        uart        |UART 16550 Main Address Map|
| 0x200|     log_engine     |             —             |

## uart_log_engine_ctrl address map

- Absolute Address: 0xC00
- Base Offset: 0x0
- Size: 0x4

|Offset|Identifier|Name|
|------|----------|----|
|  0x0 |   CTRL   |  — |

### CTRL register

- Absolute Address: 0xC00
- Base Offset: 0x0
- Size: 0x4

<p>Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  UART_EN |  rw  | 0x0 |  — |

#### UART_EN field

<p>UART Enable. When set, the pad-mux downstream will be forced to accept UART
traffic.</p>

## uart address map

- Absolute Address: 0xD00
- Base Offset: 0x100
- Size: 0x28

<p>Contains the mode-independent registers and the read-only registers accessible only
when <code>DLAB = 0</code>.</p>

|Offset|Identifier|Name|
|------|----------|----|
| 0x00 |    RBR   |  — |
| 0x04 |    IER   |  — |
| 0x08 |    IIR   |  — |
| 0x0C |    LCR   |  — |
| 0x10 |    MCR   |  — |
| 0x14 |    LSR   |  — |
| 0x18 |    MSR   |  — |
| 0x1C |    SCR   |  — |
| 0x20 |    ECR   |  — |
| 0x24 |    ITR   |  — |

### RBR register

- Absolute Address: 0xD00
- Base Offset: 0x0
- Size: 0x4

<p>Receiver Buffer Register</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |r, ruser| 0x0 |  — |

#### DATA field

<p>Received Data. Contains a received character. If FIFOs are enabled, this field
points to the bottom of the RX FIFO. Otherwise, this field points to a single-
byte Receiver Buffer Register.</p>

### IER register

- Absolute Address: 0xD04
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   ERBFI  |  rw  | 0x0 |  — |
|  1 |   ETBEI  |  rw  | 0x0 |  — |
|  2 |   ELSI   |  rw  | 0x0 |  — |
|  3 |   EDSSI  |  rw  | 0x0 |  — |
|  4 |   EFEI   |  rw  | 0x0 |  — |

#### ERBFI field

<p>Enable Receiver Buffer Full (Received Data Ready) Interrupt.</p>

#### ETBEI field

<p>Enable Transmitter Buffer Empty (Transmitter Holding Register Empty)
Interrupt.</p>

#### ELSI field

<p>Enable (Receiver) Line Status Interrupt.</p>

#### EDSSI field

<p>Enable (Delta Status of) Modem Status Interrupt.</p>

#### EFEI field

<p>Enable FIFO Error Interrupt.</p>

### IIR register

- Absolute Address: 0xD08
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Identification Register</p>

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
|  0 |INTERRUPT_PENDING|   r  | 0x1 |  — |
| 3:1|   INTERRUPT_ID  |   r  | 0x0 |  — |
| 7:6|  FIFOS_ENABLED  |   r  | 0x0 |  — |

#### INTERRUPT_PENDING field

<p>Interrupt Pending. Active-low.</p>

#### INTERRUPT_ID field

<p>Interrupt ID:
* <code>0x7</code> - FIFO Error Interrupt                         (priority 0)
* <code>0x3</code> - Receiver Line Status Interrupt               (priority 1)
* <code>0x6</code> - Reception Timeout Interrupt                  (priority 2)
* <code>0x2</code> - Received Data Ready Interrupt                (priority 3)
* <code>0x1</code> - Transmitter Holding Register Empty Interrupt (priority 4)
* <code>0x0</code> - Modem Status Interrupt                       (priority 5)</p>

#### FIFOS_ENABLED field

<p>FIFOs Enabled:
* <code>0x0</code> - FIFOs are disabled
* <code>0x3</code> - FIFOs are enabled</p>

### LCR register

- Absolute Address: 0xD0C
- Base Offset: 0xC
- Size: 0x4

<p>Line Control Register</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
| 1:0|     WLS    |  rw  | 0x0 |  — |
|  2 |     STB    |  rw  | 0x0 |  — |
|  3 |     PEN    |  rw  | 0x0 |  — |
|  4 |     EPS    |  rw  | 0x0 |  — |
|  5 |STICK_PARITY|  rw  | 0x0 |  — |
|  6 |  SET_BREAK |  rw  | 0x0 |  — |
|  7 |    DLAB    |  rw  | 0x0 |  — |

#### WLS field

<p>Word Length Select:
* <code>0x0</code> - 5 bits per character
* <code>0x1</code> - 6 bits per character
* <code>0x2</code> - 7 bits per character
* <code>0x3</code> - 8 bits per character</p>

#### STB field

<p>Stop Bits:
* <code>0</code> - 1 stop bit.
* <code>1</code> - 2 stop bits (or 1.5 stop bits if word length is set to 5 bits)</p>

#### PEN field

<p>Parity Enable.</p>

#### EPS field

<p>Even Parity Select:
* <code>1</code> - even parity
* <code>0</code> - odd parity</p>

#### STICK_PARITY field

<p>Stick Parity. If set, forces the transmit and received parity bits to be <code>0</code> if
even parity is selected and <code>1</code> if odd parity is selected.</p>

#### SET_BREAK field

<p>Set Break. If set, forces the <code>tx_o</code> output to <code>0</code> to cause a break condition
on the receiving UART.</p>

#### DLAB field

<p>Divisor Latch Access Bit. If set, allows access to the <code>DLL</code> and <code>DLM</code> registers
when accessing addresses <code>0x0</code> and <code>0x4</code>, respectively. If unset, allows access
to the <code>THR</code>, <code>RBR</code>, and <code>IIR</code> registers.</p>

### MCR register

- Absolute Address: 0xD10
- Base Offset: 0x10
- Size: 0x4

<p>Modem Control Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |     DTR     |  rw  | 0x0 |  — |
|  1 |     RTS     |  rw  | 0x0 |  — |
|  2 |     OUT1    |  rw  | 0x0 |  — |
|  3 |     OUT2    |  rw  | 0x0 |  — |
|  4 |     LOOP    |  rw  | 0x0 |  — |
|  5 |LINE_LOOPBACK|  rw  | 0x0 |  — |

#### DTR field

<p>Data Terminal Ready. Writing to this bit drives the <code>dtr_no</code> output in the
opposite polarity.</p>

#### RTS field

<p>Request to Send. Writing to this bit drives the <code>rts_no</code> output in the opposite
polarity.</p>

#### OUT1 field

<p>User Output 1. Writing to this bit drives the <code>out1_no</code> in the opposite
polarity.</p>

#### OUT2 field

<p>User Output 2. Writing to this bit drives the <code>out2_no</code> in the opposite
polarity.</p>

#### LOOP field

<p>System Loopback. If set, the transmitter is internally connected to the
receiver. The <code>tx_o</code> output is set to <code>1</code>.</p>

#### LINE_LOOPBACK field

<p>Line Loopback. If set, the <code>rx_i</code> input is internally connected to the
<code>tx_o</code> output.</p>

### LSR register

- Absolute Address: 0xD14
- Base Offset: 0x14
- Size: 0x4

<p>Line Status Register</p>

|Bits|    Identifier    | Access|Reset|Name|
|----|------------------|-------|-----|----|
|  0 |        DR        |   r   | 0x0 |  — |
|  1 |        OE        |r, rclr| 0x0 |  — |
|  2 |        PE        |r, rclr| 0x0 |  — |
|  3 |        FE        |r, rclr| 0x0 |  — |
|  4 |        BI        |r, rclr| 0x0 |  — |
|  5 |       THRE       |   r   | 0x1 |  — |
|  6 |       TEMT       |   r   | 0x1 |  — |
|  7 |ERROR_IN_RCVR_FIFO|   r   | 0x0 |  — |

#### DR field

<p>Data Ready. When set, indicates that the RX FIFO (or RBR in non-FIFO
mode) contains data.</p>

#### OE field

<p>Overrun Error. When set, indicates that the RX FIFO (or Receiver Buffer
Register in Non-FIFO Mode) is full when new character is received. In FIFO Mode, the new character
is dropped. In non-FIFO mode, the existing character in the RBR is overwritten.
This bit triggers the Receiver Line Status Interrupt.</p>

#### PE field

<p>Parity Error. When set, indicates that the character at the top of the receiver
FIFO (or RBR in non-FIFO mode) has a parity error. This bit triggers the
Receiver Line Status Interrupt.</p>

#### FE field

<p>Framing Error. When set, indicates that the received character is missing a
stop bit. In FIFO mode, this bit is set when the character reaches the top of
the FIFO. In non-FIFO mode, this bit is set when the character enters the RBR.
This bit triggers the Receiver Line Status Interrupt.</p>

#### BI field

<p>Break Interrupt. When set, indicates that the <code>rx_i</code> input is <code>0</code> for an entire
frame's time (start + data + parity + stop bits). In FIFO mode, this bit set
when the character reaches the top of the receiver FIFO. In non-FIFO mode, this
bit is set when the character enters the RBR. This bit triggers the Receiver
Line Status Interrupt.</p>

#### THRE field

<p>Transmitter Holding Register Empty. When set, indicates that the TX FIFO (or
THR in non-FIFO mode) is empty. Clearing the Transmitter Holding Register Empty
Interrupt does NOT clear this bit.</p>

#### TEMT field

<p>Transmitter Empty. When set, indicates that the transmitter shift register and
the transmitter FIFO (or THR in non-FIFO mode) are empty.</p>

#### ERROR_IN_RCVR_FIFO field

<p>Error in Receiver FIFO. When set, indicates that the receiver FIFO or (RBR in
non-FIFO mode) has the parity, framing, or break error. In other words, at
least one of the PE, FE, and BI bits is set.</p>

### MSR register

- Absolute Address: 0xD18
- Base Offset: 0x18
- Size: 0x4

<p>Modem Status Register</p>

|Bits|Identifier| Access|Reset|Name|
|----|----------|-------|-----|----|
|  0 |   DCTS   |r, rclr| 0x0 |  — |
|  1 |   DDSR   |r, rclr| 0x0 |  — |
|  2 |   TERI   |r, rclr| 0x0 |  — |
|  3 |   DDCD   |r, rclr| 0x0 |  — |
|  4 |    CTS   |   r   | 0x0 |  — |
|  5 |    DSR   |   r   | 0x0 |  — |
|  6 |    RI    |   r   | 0x0 |  — |
|  7 |    DCD   |   r   | 0x0 |  — |

#### DCTS field

<p>Delta Clear to Send. When set, indicates that the <code>CTS</code> bit has changed since
the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### DDSR field

<p>Delta Data Set Ready. When set, indicates that the <code>DSR</code> bit has changed since
the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### TERI field

<p>Trailing Edge Ring Indicator. When set, indicates that the <code>RI</code> bit has changed
from a <code>1</code> to a <code>0</code>. This bit triggers the Modem Status Interrupt.</p>

#### DDCD field

<p>Delta Data Carrier Detect. When set, indicates that the <code>DCD</code> bit has changed
since the last time this register was read. This bit triggers the Modem Status
Interrupt.</p>

#### CTS field

<p>Clear to Send. This bit is the active-low version of the <code>cts_ni</code> input.</p>

#### DSR field

<p>Data Set Ready. This bit is the active-low version of the <code>dsr_ni</code> input.</p>

#### RI field

<p>Ring Indicator. This bit is the active-low version of the <code>ri_ni</code> input.</p>

#### DCD field

<p>Data Carrier Detect. This bit is the active-low version of the <code>dcd_ni</code>
input.</p>

### SCR register

- Absolute Address: 0xD1C
- Base Offset: 0x1C
- Size: 0x4

<p>Scratch Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|    SCR   |  rw  | 0x0 |  — |

#### SCR field

<p>Scratch. Holds user data.</p>

### ECR register

- Absolute Address: 0xD20
- Base Offset: 0x20
- Size: 0x4

<p>Extended Control Register</p>

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
| 1:0|RCVR_TRIGGER_MS2B|  rw  | 0x0 |  — |

#### RCVR_TRIGGER_MS2B field

<p>Receiver FIFO Trigger Level Most Significant 2 Bits. To configure the least
significant 2 bits, use the <code>FCR.RCVR_TRIGGER</code> register field. The
configurations for the trigger levels are:
 * <code>0x0</code> -    1 character
 * <code>0x1</code> -    4 characters
 * <code>0x2</code> -    8 characters
 * <code>0x3</code> -   14 characters
 * <code>0x4</code> -   32 characters
 * <code>0x5</code> -   64 characters
 * <code>0x6</code> -  128 characters
 * <code>0x7</code> -  256 characters
 * <code>0x8</code> -  512 characters
 * <code>0x9</code> - 1024 characters
 * <code>0xA</code> - 2048 characters
 * <code>0xB</code> - 4096 characters</p>

### ITR register

- Absolute Address: 0xD24
- Base Offset: 0x24
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   TRBFI  |  rw  | 0x0 |  — |
|  1 |   TTBEI  |  rw  | 0x0 |  — |
|  2 |   TLSI   |  rw  | 0x0 |  — |
|  3 |   TDSSI  |  rw  | 0x0 |  — |
|  4 |   TFEI   |  rw  | 0x0 |  — |
|  5 |   TRTI   |  rw  | 0x0 |  — |

#### TRBFI field

<p>Test Receiver Buffer Full (Received Data Ready) Interrupt. Writing <code>1</code> forces
the interrupt and writing <code>0</code> releases it.</p>

#### TTBEI field

<p>Test Transmitter Buffer Empty (Transmitter Holding Register Empty) Interrupt.
Writing <code>1</code> forces the interrupt and writing <code>0</code> releases it.</p>

#### TLSI field

<p>Test (Receiver) Line Status Interrupt. Writing <code>1</code> forces the interrupt and
writing <code>0</code> releases it.</p>

#### TDSSI field

<p>Test (Delta Status of) Modem Status Interrupt. Writing <code>1</code> forces the
interrupt and writing <code>0</code> releases it.</p>

#### TFEI field

<p>Test FIFO Error Interrupt. Writing <code>1</code> forces the interrupt and writing <code>0</code>
releases it.</p>

#### TRTI field

<p>Test Reception Timeout Interrupt. Writing a <code>1</code> forces the interrupt and
writing <code>0</code> releases it.</p>

## log_engine address map

- Absolute Address: 0xE00
- Base Offset: 0x200
- Size: 0x80

<p>Log Engine</p>

|Offset|   Identifier  |Name|
|------|---------------|----|
| 0x00 |      CTRL     |  — |
| 0x04 |LOG_REGION_SIZE|  — |
| 0x08 |LOG_REGION_ADDR|  — |
| 0x10 | LOG_WRITE_ADDR|  — |
| 0x14 |  INTR_STATUS  |  — |
| 0x18 |  INTR_ENABLE  |  — |
| 0x1C |   INTR_TEST   |  — |
| 0x40 |  LOG_CTRL[0]  |  — |
| 0x44 |  LOG_CTRL[1]  |  — |
| 0x48 |  LOG_CTRL[2]  |  — |
| 0x4C |  LOG_CTRL[3]  |  — |
| 0x50 |  LOG_CTRL[4]  |  — |
| 0x54 |  LOG_CTRL[5]  |  — |
| 0x58 |  LOG_CTRL[6]  |  — |
| 0x5C |  LOG_CTRL[7]  |  — |
| 0x60 |  LOG_CTRL[8]  |  — |
| 0x64 |  LOG_CTRL[9]  |  — |
| 0x68 |  LOG_CTRL[10] |  — |
| 0x6C |  LOG_CTRL[11] |  — |
| 0x70 |  LOG_CTRL[12] |  — |
| 0x74 |  LOG_CTRL[13] |  — |
| 0x78 |  LOG_CTRL[14] |  — |
| 0x7C |  LOG_CTRL[15] |  — |

### CTRL register

- Absolute Address: 0xE00
- Base Offset: 0x0
- Size: 0x4

<p>Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |    EN    |  rw  | 0x0 |  — |

#### EN field

<p>Log Engine Enable. When set, enables the Log Engine. When unset, disables the
Log Engine and resets all FSMs, flops, and FIFOs.</p>

### LOG_REGION_SIZE register

- Absolute Address: 0xE04
- Base Offset: 0x4
- Size: 0x4

<p>Log Region Size Register</p>

|Bits|   Identifier  |Access|Reset|Name|
|----|---------------|------|-----|----|
|19:0|LOG_REGION_SIZE|  rw  | 0x0 |  — |

#### LOG_REGION_SIZE field

<p>Log Region Size. Specified in bytes. Needs to be a multiple of 16.</p>

### LOG_REGION_ADDR register

- Absolute Address: 0xE08
- Base Offset: 0x8
- Size: 0x8

<p>Log Region Address Register</p>

| Bits|    Identifier    |Access|Reset|Name|
|-----|------------------|------|-----|----|
| 31:0|LOG_REGION_ADDR_LO|  rw  | 0x0 |  — |
|63:32|LOG_REGION_ADDR_HI|  rw  | 0x0 |  — |

#### LOG_REGION_ADDR_LO field

<p>Log Region Start Address Low.</p>

#### LOG_REGION_ADDR_HI field

<p>Log Region Start Address High.</p>

### LOG_WRITE_ADDR register

- Absolute Address: 0xE10
- Base Offset: 0x10
- Size: 0x4

<p>Log Write Address Register</p>

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|31:0|LOG_WRITE_ADDR|  rw  | 0x0 |  — |

#### LOG_WRITE_ADDR field

<p>Log Write Address. This is the address where the log data is written to.</p>

### INTR_STATUS register

- Absolute Address: 0xE14
- Base Offset: 0x14
- Size: 0x4

<p>Interrupt Status Register</p>

|Bits|  Identifier |  Access |Reset|Name|
|----|-------------|---------|-----|----|
|  0 |LOG_FETCH_ERR|rw, woclr| 0x0 |  — |
|  4 |LOG_WRITE_ERR|rw, woclr| 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt. Asserted when the bus for fetching log data returns
an error.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt. Asserted when the bus for writing log data returns
an error.</p>

### INTR_ENABLE register

- Absolute Address: 0xE18
- Base Offset: 0x18
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |LOG_FETCH_ERR|  rw  | 0x0 |  — |
|  4 |LOG_WRITE_ERR|  rw  | 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt Enable.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt Enable.</p>

### INTR_TEST register

- Absolute Address: 0xE1C
- Base Offset: 0x1C
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|  0 |LOG_FETCH_ERR|   w  | 0x0 |  — |
|  4 |LOG_WRITE_ERR|   w  | 0x0 |  — |

#### LOG_FETCH_ERR field

<p>Log Fetch Error Interrupt Test. Writing <code>1</code> forces the interrupt.</p>

#### LOG_WRITE_ERR field

<p>Log Write Error Interrupt Test. Writing <code>1</code> forces the interrupt.</p>

### LOG_CTRL register

- Absolute Address: 0xE40
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE44
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE48
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE4C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE50
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE54
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE58
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE5C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE60
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE64
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE68
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE6C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE70
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE74
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE78
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>

### LOG_CTRL register

- Absolute Address: 0xE7C
- Base Offset: 0x40
- Size: 0x4
- Array Dimensions: [16]
- Array Stride: 0x4
- Total Size: 0x40

<p>Log Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|15:0|  LOG_LEN |  rw  | 0x0 |  — |

#### LOG_LEN field

<p>Log Length. Writing a nonzero value representing the log length in bytes to this field
starts the log transfer process. There are 16 copies of this register, each representing
a log entry. The log entries go through round robin arbitration.</p>
