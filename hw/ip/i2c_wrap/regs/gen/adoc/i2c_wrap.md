<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: i2c_wrap
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/i2c_wrap/regs/i2c_wrap.rdl
-->

## i2c_wrap address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0xE0C

|Offset|Identifier|Name|
|------|----------|----|
| 0x000|  i2c[0]  |  — |
| 0x200|  i2c[1]  |  — |
| 0x400|  i2c[2]  |  — |
| 0xE00| i2c_ctrl |  — |

## i2c address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x84
- Array Dimensions: [3]
- Array Stride: 0x200
- Total Size: 0x600

|Offset|        Identifier       |Name|
|------|-------------------------|----|
| 0x00 |        INTR_STATE       |  — |
| 0x04 |       INTR_ENABLE       |  — |
| 0x08 |        INTR_TEST        |  — |
| 0x0C |        SMBUS_CTRL       |  — |
| 0x10 |           CTRL          |  — |
| 0x14 |          STATUS         |  — |
| 0x18 |          RDATA          |  — |
| 0x1C |          FDATA          |  — |
| 0x20 |        FIFO_CTRL        |  — |
| 0x24 |     HOST_FIFO_CONFIG    |  — |
| 0x28 |    TARGET_FIFO_CONFIG   |  — |
| 0x2C |     HOST_FIFO_STATUS    |  — |
| 0x30 |    TARGET_FIFO_STATUS   |  — |
| 0x34 |           OVRD          |  — |
| 0x38 |           VAL           |  — |
| 0x3C |         TIMING0         |  — |
| 0x40 |         TIMING1         |  — |
| 0x44 |         TIMING2         |  — |
| 0x48 |         TIMING3         |  — |
| 0x4C |         TIMING4         |  — |
| 0x50 |       TIMEOUT_CTRL      |  — |
| 0x54 |        TARGET_ID        |  — |
| 0x58 |         ACQDATA         |  — |
| 0x5C |          TXDATA         |  — |
| 0x60 |    HOST_TIMEOUT_CTRL    |  — |
| 0x64 |   TARGET_TIMEOUT_CTRL   |  — |
| 0x68 |    TARGET_NACK_COUNT    |  — |
| 0x6C |     TARGET_ACK_CTRL     |  — |
| 0x70 |    ACQ_FIFO_NEXT_DATA   |  — |
| 0x74 |HOST_NACK_HANDLER_TIMEOUT|  — |
| 0x78 |    CONTROLLER_EVENTS    |  — |
| 0x7C |      TARGET_EVENTS      |  — |
| 0x80 |       SMBUS_STATUS      |  — |

### INTR_STATE register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>Interrupt Status Register</p>

|Bits|       Identifier       |  Access |Reset|Name|
|----|------------------------|---------|-----|----|
|  0 |      FMT_THRESHOLD     |    r    | 0x0 |  — |
|  1 |      RX_THRESHOLD      |    r    | 0x0 |  — |
|  2 |      ACQ_THRESHOLD     |    r    | 0x0 |  — |
|  3 |       RX_OVERFLOW      |rw, woclr| 0x0 |  — |
|  4 |     CONTROLLER_HALT    |    r    | 0x0 |  — |
|  5 |    SCL_INTERFERENCE    |rw, woclr| 0x0 |  — |
|  6 |    SDA_INTERFERENCE    |rw, woclr| 0x0 |  — |
|  7 |     STRETCH_TIMEOUT    |rw, woclr| 0x0 |  — |
|  8 |      SDA_UNSTABLE      |rw, woclr| 0x0 |  — |
|  9 |      CMD_COMPLETE      |rw, woclr| 0x0 |  — |
| 10 |       TX_STRETCH       |    r    | 0x0 |  — |
| 11 |      TX_THRESHOLD      |    r    | 0x0 |  — |
| 12 |       ACQ_STRETCH      |    r    | 0x0 |  — |
| 13 |       UNEXP_STOP       |rw, woclr| 0x0 |  — |
| 14 |      HOST_TIMEOUT      |rw, woclr| 0x0 |  — |
| 15 |        SMBALERT        |rw, woclr| 0x0 |  — |
| 16 |CONTROLLER_TX_FIFO_ERROR|rw, woclr| 0x0 |  — |
| 17 |CONTROLLER_RX_FIFO_ERROR|rw, woclr| 0x0 |  — |
| 18 |  TARGET_TX_FIFO_ERROR  |rw, woclr| 0x0 |  — |
| 19 |  TARGET_RX_FIFO_ERROR  |rw, woclr| 0x0 |  — |

#### FMT_THRESHOLD field

<p>Controller Mode interrupt: remains asserted while the Controller TX FIFO level
is less than <code>HOST_FIFO_CONFIG.FMT_THRESH</code>.</p>

#### RX_THRESHOLD field

<p>Controller Mode interrupt: remains asserted while the Controller RX FIFO level
is greater than <code>HOST_FIFO_CONFIG.RX_THRESH</code>.</p>

#### ACQ_THRESHOLD field

<p>Target Mode interrupt: remains asserted while the Target RX FIFO level is
greater than <code>TARGET_FIFO_CONFIG.ACQ_THRESH</code>.</p>

#### RX_OVERFLOW field

<p>Controller Mode interrupt: asserted when the Controller RX FIFO overflows.
Write <code>1</code> to clear.</p>

#### CONTROLLER_HALT field

<p>Controller Mode interrupt: remains asserted while this controller halts. The
flags in the <code>CONTROLLER_EVENTS</code> register explain the reason(s) for the
halting. Clearing the <code>CONTROLLER_EVENTS</code> flags clears this interrupt.</p>

#### SCL_INTERFERENCE field

<p>Controller Mode interrupt: asserted when SCL is unexpectedly pulled LOW by
another controller. Write <code>1</code> to clear.</p>

#### SDA_INTERFERENCE field

<p>Controller Mode interrupt: asserted when SDA is unexpectedly pulled LOW by
another controller. Write <code>1</code> to clear.</p>

#### STRETCH_TIMEOUT field

<p>Controller Mode interrupt: asserted when the target stretches the clock longer
than <code>TIMEOUT_CTRL.VAL</code> (valid only when <code>TIMEOUT_CTRL.MODE = 0</code>). Write <code>1</code> to
clear.</p>

#### SDA_UNSTABLE field

<p>Controller Mode interrupt: asserted when the target fails to keep SDA stable
during a transmission. Write <code>1</code> to clear.</p>

#### CMD_COMPLETE field

<p>Controller/Target Mode interrupt: asserted when this/the controller finishes
generating a STOP or repeated START. Write <code>1</code> to clear.</p>

#### TX_STRETCH field

<p>Target Mode interrupt: remains asserted while this target is stretching the
clock or has halted. The flags in the <code>TARGET_EVENTS</code> register explain the
reason(s) for clock stretching/halting. Clearing the <code>TARGET_EVENTS</code> flags
clears this interrupt.</p>

#### TX_THRESHOLD field

<p>Target Mode interrupt: remains asserted while the Target TX FIFO level is less
than <code>TARGET_FIFO_CONFIG.TX_THRESH</code>.</p>

#### ACQ_STRETCH field

<p>Target Mode interrupt: remains asserted while the target is stretching the clock
because 1) the Target RX FIFO is full or 2) the <code>TARGET_ACK_CTRL.NBYTES</code> count
has reached <code>0</code> (only if <code>CTRL.ACK_CTRL_EN = 1</code>).</p>

#### UNEXP_STOP field

<p>Target Mode interrupt: asserted when the controller sends this target a STOP
before this target NACKs. Write <code>1</code> to clear.</p>

#### HOST_TIMEOUT field

<p>Target Mode interrupt: asserted when the controller stops generating the clock
longer than <code>HOST_TIMEOUT_CTRL.VAL</code>. Write <code>1</code> to clear.</p>

#### SMBALERT field

<p>Controller Mode interrupt: asserted when <code>smbalert_ni</code> is asserted. Write <code>1</code>
to clear.</p>

#### CONTROLLER_TX_FIFO_ERROR field

<p>Controller Mode interrupt: asserted when the Controller TX FIFO has a parity
error. Write <code>1</code> to clear.</p>

#### CONTROLLER_RX_FIFO_ERROR field

<p>Controller Mode interrupt: asserted when the Controller RX FIFO has a parity
error. Write <code>1</code> to clear.</p>

#### TARGET_TX_FIFO_ERROR field

<p>Target Mode interrupt: asserted when the Target TX FIFO has a parity error.
Write <code>1</code> to clear.</p>

#### TARGET_RX_FIFO_ERROR field

<p>Target Mode interrupt: asserted when the Target RX FIFO has a parity error.
Write <code>1</code> to clear.</p>

### INTR_ENABLE register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|       Identifier       |Access|Reset|Name|
|----|------------------------|------|-----|----|
|  0 |      FMT_THRESHOLD     |  rw  | 0x0 |  — |
|  1 |      RX_THRESHOLD      |  rw  | 0x0 |  — |
|  2 |      ACQ_THRESHOLD     |  rw  | 0x0 |  — |
|  3 |       RX_OVERFLOW      |  rw  | 0x0 |  — |
|  4 |     CONTROLLER_HALT    |  rw  | 0x0 |  — |
|  5 |    SCL_INTERFERENCE    |  rw  | 0x0 |  — |
|  6 |    SDA_INTERFERENCE    |  rw  | 0x0 |  — |
|  7 |     STRETCH_TIMEOUT    |  rw  | 0x0 |  — |
|  8 |      SDA_UNSTABLE      |  rw  | 0x0 |  — |
|  9 |      CMD_COMPLETE      |  rw  | 0x0 |  — |
| 10 |       TX_STRETCH       |  rw  | 0x0 |  — |
| 11 |      TX_THRESHOLD      |  rw  | 0x0 |  — |
| 12 |       ACQ_STRETCH      |  rw  | 0x0 |  — |
| 13 |       UNEXP_STOP       |  rw  | 0x0 |  — |
| 14 |      HOST_TIMEOUT      |  rw  | 0x0 |  — |
| 15 |        SMBALERT        |  rw  | 0x0 |  — |
| 16 |CONTROLLER_TX_FIFO_ERROR|  rw  | 0x0 |  — |
| 17 |CONTROLLER_RX_FIFO_ERROR|  rw  | 0x0 |  — |
| 18 |  TARGET_TX_FIFO_ERROR  |  rw  | 0x0 |  — |
| 19 |  TARGET_RX_FIFO_ERROR  |  rw  | 0x0 |  — |

#### FMT_THRESHOLD field

<p>Enables the <code>FMT_THRESHOLD</code> interrupt.</p>

#### RX_THRESHOLD field

<p>Enables the <code>RX_THRESHOLD</code> interrupt.</p>

#### ACQ_THRESHOLD field

<p>Enables the <code>ACQ_THRESHOLD</code> interrupt.</p>

#### RX_OVERFLOW field

<p>Enables the <code>RX_OVERFLOW</code> interrupt.</p>

#### CONTROLLER_HALT field

<p>Enables the <code>CONTROLLER_HALT</code> interrupt.</p>

#### SCL_INTERFERENCE field

<p>Enables the <code>SCL_INTERFERENCE</code> interrupt.</p>

#### SDA_INTERFERENCE field

<p>Enables the <code>SDA_INTERFERENCE</code> interrupt.</p>

#### STRETCH_TIMEOUT field

<p>Enables the <code>STRETCH_TIMEOUT</code> interrupt.</p>

#### SDA_UNSTABLE field

<p>Enables the <code>SDA_UNSTABLE</code> interrupt.</p>

#### CMD_COMPLETE field

<p>Enables the <code>CMD_COMPLETE</code> interrupt.</p>

#### TX_STRETCH field

<p>Enables the <code>TX_STRETCH</code> interrupt.</p>

#### TX_THRESHOLD field

<p>Enables the <code>TX_THRESHOLD</code> interrupt.</p>

#### ACQ_STRETCH field

<p>Enables the <code>ACQ_STRETCH</code> interrupt.</p>

#### UNEXP_STOP field

<p>Enables the <code>UNEXP_STOP</code> interrupt.</p>

#### HOST_TIMEOUT field

<p>Enables the <code>HOST_TIMEOUT</code> interrupt.</p>

#### SMBALERT field

<p>Enables the <code>SMBALERT</code> interrupt.</p>

#### CONTROLLER_TX_FIFO_ERROR field

<p>Enables the <code>CONTROLLER_TX_FIFO_ERROR</code> interrupt.</p>

#### CONTROLLER_RX_FIFO_ERROR field

<p>Enables the <code>CONTROLLER_RX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_TX_FIFO_ERROR field

<p>Enables the <code>TARGET_TX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_RX_FIFO_ERROR field

<p>Enables the <code>TARGET_RX_FIFO_ERROR</code> interrupt.</p>

### INTR_TEST register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|       Identifier       |Access|Reset|Name|
|----|------------------------|------|-----|----|
|  0 |      FMT_THRESHOLD     |  rw  | 0x0 |  — |
|  1 |      RX_THRESHOLD      |  rw  | 0x0 |  — |
|  2 |      ACQ_THRESHOLD     |  rw  | 0x0 |  — |
|  3 |       RX_OVERFLOW      |   w  | 0x0 |  — |
|  4 |     CONTROLLER_HALT    |  rw  | 0x0 |  — |
|  5 |    SCL_INTERFERENCE    |   w  | 0x0 |  — |
|  6 |    SDA_INTERFERENCE    |   w  | 0x0 |  — |
|  7 |     STRETCH_TIMEOUT    |   w  | 0x0 |  — |
|  8 |      SDA_UNSTABLE      |   w  | 0x0 |  — |
|  9 |      CMD_COMPLETE      |   w  | 0x0 |  — |
| 10 |       TX_STRETCH       |  rw  | 0x0 |  — |
| 11 |      TX_THRESHOLD      |  rw  | 0x0 |  — |
| 12 |       ACQ_STRETCH      |  rw  | 0x0 |  — |
| 13 |       UNEXP_STOP       |   w  | 0x0 |  — |
| 14 |      HOST_TIMEOUT      |   w  | 0x0 |  — |
| 15 |        SMBALERT        |   w  | 0x0 |  — |
| 16 |CONTROLLER_TX_FIFO_ERROR|   w  | 0x0 |  — |
| 17 |CONTROLLER_RX_FIFO_ERROR|   w  | 0x0 |  — |
| 18 |  TARGET_TX_FIFO_ERROR  |   w  | 0x0 |  — |
| 19 |  TARGET_RX_FIFO_ERROR  |   w  | 0x0 |  — |

#### FMT_THRESHOLD field

<p>Writing <code>1</code> forces the <code>FMT_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### RX_THRESHOLD field

<p>Writing <code>1</code> forces the <code>RX_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### ACQ_THRESHOLD field

<p>Writing <code>1</code> forces the <code>ACQ_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### RX_OVERFLOW field

<p>Writing <code>1</code> forces the <code>RX_OVERFLOW</code> interrupt.</p>

#### CONTROLLER_HALT field

<p>Writing <code>1</code> forces the <code>CONTROLLER_HALT</code> interrupt. Writing <code>0</code> releases it.</p>

#### SCL_INTERFERENCE field

<p>Writing <code>1</code> forces the <code>SCL_INTERFERENCE</code> interrupt.</p>

#### SDA_INTERFERENCE field

<p>Writing <code>1</code> forces the <code>SDA_INTERFERENCE</code> interrupt.</p>

#### STRETCH_TIMEOUT field

<p>Writing <code>1</code> forces the <code>STRETCH_TIMEOUT</code> interrupt.</p>

#### SDA_UNSTABLE field

<p>Writing <code>1</code> forces the <code>SDA_UNSTABLE</code> interrupt.</p>

#### CMD_COMPLETE field

<p>Writing <code>1</code> forces the <code>CMD_COMPLETE</code> interrupt.</p>

#### TX_STRETCH field

<p>Writing <code>1</code> forces the <code>TX_STRETCH</code> interrupt. Writing a <code>0</code> releases it.</p>

#### TX_THRESHOLD field

<p>Writing <code>1</code> forces the <code>TX_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### ACQ_STRETCH field

<p>Writing <code>1</code> forces the <code>ACQ_STRETCH</code> interrupt. Writing <code>0</code> releases it.</p>

#### UNEXP_STOP field

<p>Writing <code>1</code> forces the <code>UNEXP_STOP</code> interrupt.</p>

#### HOST_TIMEOUT field

<p>Writing <code>1</code> forces the <code>HOST_TIMEOUT</code> interrupt.</p>

#### SMBALERT field

<p>Writing <code>1</code> forces the <code>SMBALERT</code> interrupt.</p>

#### CONTROLLER_TX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>CONTROLLER_TX_FIFO_ERROR</code> interrupt.</p>

#### CONTROLLER_RX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>CONTROLLER_RX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_TX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>TARGET_TX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_RX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>TARGET_RX_FIFO_ERROR</code> interrupt.</p>

### SMBUS_CTRL register

- Absolute Address: 0xC
- Base Offset: 0xC
- Size: 0x4

<p>SMBus Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  SMBSUS  |  rw  | 0x0 |  — |
|  4 | SMBALERT |  rw  | 0x0 |  — |

#### SMBSUS field

<p>Controller Mode control: asserts the <code>smbsus_no</code> output.</p>

#### SMBALERT field

<p>Target Mode control: asserts the <code>smbalert_no</code> output. This bit clears itself
when the controller addresses this target.</p>

### CTRL register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

<p>Control Register</p>

|Bits|         Identifier        |Access|Reset|Name|
|----|---------------------------|------|-----|----|
|  0 |         ENABLEHOST        |  rw  | 0x0 |  — |
|  1 |        ENABLETARGET       |  rw  | 0x0 |  — |
|  2 |           LLPBK           |  rw  | 0x0 |  — |
|  3 |  NACK_ADDR_AFTER_TIMEOUT  |  rw  | 0x0 |  — |
|  4 |        ACK_CTRL_EN        |  rw  | 0x0 |  — |
|  5 |MULTI_CONTROLLER_MONITOR_EN|  rw  | 0x0 |  — |
|  6 |     TX_STRETCH_CTRL_EN    |  rw  | 0x0 |  — |
|  7 |     ACQ_START_STOP_EN     |  rw  | 0x0 |  — |

#### ENABLEHOST field

<p>Global control: configures this device's operating mode.
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 0</code> — Controller Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 1</code> — Target Mode
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 1</code> — Hybrid Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 0</code> — Monitor Mode</p>

#### ENABLETARGET field

<p>Global control: configures this device's operating mode.
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 0</code> — Controller Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 1</code> — Target Mode
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 1</code> — Hybrid Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 0</code> — Monitor Mode</p>

#### LLPBK field

<p>Global control: enables line loop-back. In Controller Mode, the internal logic
sees the <code>smbalert_ni</code> input as deasserted. In Target Mode, this target sends
all received SDA data back out, and the internal logic sees received data as
all 1's.</p>

#### NACK_ADDR_AFTER_TIMEOUT field

<p>Target Mode control: NACK address after timeout. If this bit is:
* <code>0</code> - This target ACKs the address byte even if a Stretch Timeout occurs
        (useful for SMBus).
* <code>1</code> - This target NACKs the address byte when a Stretch Timeout occurs.</p>

#### ACK_CTRL_EN field

<p>Target Mode control: enables the Software ACK Control Mechanism. If this bit is:
* <code>0</code> - This target ACKs a data byte whenever the ACQ FIFO has space.
* <code>1</code> - This target ACKs the first <code>TARGET_ACK_CTRL.NBYTES</code> bytes. If another
        byte arrives, this target stretches the clock and awaits software
        intervention (and asserts <code>STATUS.ACK_CTRL_STRETCH</code>). The software can
         1. accept the new byte(s) by reloading the <code>TARGET_ACK_CTRL.NBYTES</code>
            counter; or
         2. reject the new byte(s) by writing <code>1</code> to <code>TARGET_ACK_CTRL.NACK</code>
            (useful for SMBus).</p>

#### MULTI_CONTROLLER_MONITOR_EN field

<p>Global control: enables the Bus Monitor. Set this bit to <code>1</code>
only in a multi-controller environment.</p>
<p>If a <code>0</code>-&gt;<code>1</code> transition happens while <code>ENABLEHOST</code> and <code>ENABLETARGET</code> are both
<code>0</code>, the Bus Monitor will enable and begin in the 'Bus Busy' state. To
transition to a 'Bus Free' state, <code>HOST_TIMEOUT_CTRL</code> must be nonzero so the
Bus Monitor may count out idle cycles to confirm the freedom to transmit. In
addition, the Bus Monitor will track whether the bus is free based on the
enabled timeouts and detected STOP symbols. For Multi-Controller Mode, ensure
<code>MULTI_CONTROLLER_MONITOR_EN</code> becomes <code>1</code> no later than <code>ENABLEHOST</code> or
<code>ENABLETARGET</code>. This bit can be set at the same time as either or both of the
other two, though.</p>
<p>Note that if <code>MULTI_CONTROLLER_MONITOR_EN</code> is set after <code>ENABLEHOST</code> or
<code>ENABLETARGET</code>, the Bus Monitor will begin in the 'Bus Free' state instead.
This would violate the proper protocol for a controller to join a multi-controller
environment. However, if this controller is known to be the first to join, this
ordering will enable skipping the idle wait.</p>
<p>When <code>0</code>, the bus monitor will report that the bus is always free, so the
Controller FSM is never blocked from transmitting.</p>

#### TX_STRETCH_CTRL_EN field

<p>Target mode control: enables the Software TX Stretch Control Mechanism. If this
bit is:
 * <code>0</code> - Automatic TX Stretch: When this target receives a READ address
         byte, it only stretches the clock if the TX FIFO is empty; otherwise,
         it pops the FIFO and transmits the data byte. The target never sets
         the <code>TARGET_EVENTS</code> register flags in this mode.
 * <code>1</code> - Software TX Stretch Mode: When this target receives a READ address,
         it always stretches the clock and sets the <code>TARGET_EVENTS.TX_PENDING</code>
         flag. The software can:
          1. confirm the release and transmission of the TX FIFO data by
             writing a 1 to clear the <code>TARGET_EVENTS.TX_PENDING</code> flag; or
          2. reset the TX FIFO by writing 1 to <code>FIFO_CTRL.TXRST</code> and load in
             new data via the <code>TXDATA</code> register--useful whenthe READ address
             is targeting a different function of the target.
         In this mode, the target always sets the <code>TARGET_EVENTS</code> register
         flags.</p>

#### ACQ_START_STOP_EN field

<p>ACQ FIFO Start/Stop Enable (Target Mode only):
* <code>0</code> - Start/Stop symbols are NOT written into the ACQ FIFO. The firmware
        should rely on <code>TARGET_EVENTS.START_DETECT</code> and <code>TARGET_EVENTS.STOP_DETECT</code>
        flags to detect Start/Stop events.
* <code>1</code> - Start/Stop symbols ARE written into the ACQ FIFO (legacy behavior).
        When a START (or repeated START) is detected, an <code>AcqStart</code> or <code>AcqRestart</code>
        entry is written. When a STOP is detected, an <code>AcqStop</code> or <code>AcqNackStop</code>
        entry is written.</p>

### STATUS register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

<p>Status Register</p>

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|  0 |     FMTFULL    |   r  | 0x0 |  — |
|  1 |     RXFULL     |   r  | 0x0 |  — |
|  2 |    FMTEMPTY    |   r  | 0x1 |  — |
|  3 |    HOSTIDLE    |   r  | 0x1 |  — |
|  4 |   TARGETIDLE   |   r  | 0x1 |  — |
|  5 |     RXEMPTY    |   r  | 0x1 |  — |
|  6 |     TXFULL     |   r  | 0x0 |  — |
|  7 |     ACQFULL    |   r  | 0x0 |  — |
|  8 |     TXEMPTY    |   r  | 0x1 |  — |
|  9 |    ACQEMPTY    |   r  | 0x1 |  — |
| 10 |ACK_CTRL_STRETCH|   r  | 0x0 |  — |

#### FMTFULL field

<p>Controller Mode status: Controller TX FIFO Full.</p>

#### RXFULL field

<p>Controller Mode status: Controller RX FIFO Full.</p>

#### FMTEMPTY field

<p>Controller Mode status: Controller TX FIFO Empty.</p>

#### HOSTIDLE field

<p>Controller Mode status: Controller FSM idle.</p>

#### TARGETIDLE field

<p>Target Mode status: Target FSM idle.</p>

#### RXEMPTY field

<p>Controller Mode status: Controller RX FIFO empty.</p>

#### TXFULL field

<p>Target Mode status: Target TX FIFO full.</p>

#### ACQFULL field

<p>Target Mode status: Target RX FIFO full.</p>

#### TXEMPTY field

<p>Target Mode status: Target TX FIFO empty.</p>

#### ACQEMPTY field

<p>Target Mode status: Target RX FIFO empty.</p>

#### ACK_CTRL_STRETCH field

<p>Target Mode status: indicates that this target is stretching the clock due to
the Software ACK Control Mechanism. See <code>CTRL.ACK_CTRL_EN</code> for details.</p>

### RDATA register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

<p>Controller RX FIFO Access Register (Controller Mode only)</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |r, ruser| 0x0 |  — |

#### DATA field

<p>Reading this register pops the Controller RX FIFO.</p>

### FDATA register

- Absolute Address: 0x1C
- Base Offset: 0x1C
- Size: 0x4

<p>Controller TX FIFO Access Register (Controller Mode only)</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   FBYTE  |w, wuser| 0x0 |  — |
|  8 |   START  |    w   | 0x0 |  — |
|  9 |   STOP   |    w   | 0x0 |  — |
| 10 |   READB  |    w   | 0x0 |  — |
| 11 |   RCONT  |    w   | 0x0 |  — |
| 12 |   NAKOK  |    w   | 0x0 |  — |

#### FBYTE field

<p>Writing to this register pushes an entry into the Controller TX FIFO. The
meaning of this field depends on the value of the <code>READB</code> field:
 * <code>READB = 0</code> - This field is the WRITE data byte.
 * <code>READB = 1</code> - This field specifies the number of bytes to read from the
                 target. Setting this field to 0 reads 256 bytes.</p>

#### START field

<p>Generate a START condition on the bus before sending the byte.</p>

#### STOP field

<p>Generate a STOP condition on the bus after sending the byte.</p>

#### READB field

<p>Read/write:
* <code>0</code> - Issue WRITE transaction
* <code>1</code> - Issue READ transaction</p>

#### RCONT field

<p>Read continue/stop:
* <code>0</code> — Read Stop: The controller NACKs the last data byte. Use this if this
        is the last READ in a sequence.
* <code>1</code> — Read Continue: The controller ACKs the last data byte. Use this if
        this is an intermediate READ in a sequence.</p>

#### NAKOK field

<p>NACK OK. When set, this controller will not care if this byte is NACKed. It
will not halt, set the <code>CONTROLLER_EVENTS.NACK</code> flag, or assert the
<code>CONTROLLER_HALT</code> Interrupt. This behavior is useful for protocols like Serial
Camera Control Bus (SCCB).</p>

### FIFO_CTRL register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x4

<p>FIFO Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   RXRST  |   w  | 0x0 |  — |
|  1 |  FMTRST  |   w  | 0x0 |  — |
|  7 |  ACQRST  |   w  | 0x0 |  — |
|  8 |   TXRST  |   w  | 0x0 |  — |

#### RXRST field

<p>Controller Mode control: writing <code>1</code> resets the Controller RX FIFO.</p>

#### FMTRST field

<p>Controller Mode control: writing <code>1</code> resets the Controller TX FIFO.</p>

#### ACQRST field

<p>Target Mode control: writing <code>1</code> resets the Target RX FIFO.</p>

#### TXRST field

<p>Target Mode control: writing <code>1</code> resets the Target TX FIFO.</p>

### HOST_FIFO_CONFIG register

- Absolute Address: 0x24
- Base Offset: 0x24
- Size: 0x4

<p>Controller FIFO Configuration Register (Controller Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0| RX_THRESH|  rw  | 0x0 |  — |
|27:16|FMT_THRESH|  rw  | 0x0 |  — |

#### RX_THRESH field

<p>The <code>RX_THRESH</code> interrupt remains asserted while the Controller RX FIFO level
is greater than this setting.</p>

#### FMT_THRESH field

<p>The <code>FMT_THRESH</code> interrupt remains asserted while the Controller TX FIFO level
is less than this setting.</p>

### TARGET_FIFO_CONFIG register

- Absolute Address: 0x28
- Base Offset: 0x28
- Size: 0x4

<p>Target FIFOs Configuration Register (Target Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0| TX_THRESH|  rw  | 0x0 |  — |
|27:16|ACQ_THRESH|  rw  | 0x0 |  — |

#### TX_THRESH field

<p>The <code>TX_THRESH</code> interrupt remains asserted while the Target TX FIFO level is
less than this setting.</p>

#### ACQ_THRESH field

<p>The <code>ACQ_THRESH</code> interrupt remains asserted while the Target RX FIFO level is
greater than this setting.</p>

### HOST_FIFO_STATUS register

- Absolute Address: 0x2C
- Base Offset: 0x2C
- Size: 0x4

<p>Controller FIFOs Status Register (Controller Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0|  FMTLVL  |   r  |  —  |  — |
|27:16|   RXLVL  |   r  |  —  |  — |

#### FMTLVL field

<p>Controller TX FIFO fill level.</p>

#### RXLVL field

<p>Controller RX FIFO fill level.</p>

### TARGET_FIFO_STATUS register

- Absolute Address: 0x30
- Base Offset: 0x30
- Size: 0x4

<p>Target FIFOs Status Register (Target Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0|   TXLVL  |   r  | 0x0 |  — |
|27:16|  ACQLVL  |   r  | 0x0 |  — |

#### TXLVL field

<p>Target TX FIFO fill level.</p>

#### ACQLVL field

<p>Target RX FIFO fill level.</p>

### OVRD register

- Absolute Address: 0x34
- Base Offset: 0x34
- Size: 0x4

<p>Override Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 | TXOVRDEN |  rw  | 0x0 |  — |
|  1 |  SCLVAL  |  rw  | 0x0 |  — |
|  2 |  SDAVAL  |  rw  | 0x0 |  — |

#### TXOVRDEN field

<p>Global control: enables control of the SDA and SCL lines through the <code>SDA_VAL</code>
and <code>SCL_VAL</code> fields, respectively.</p>

#### SCLVAL field

<p>Global control: SCL override value:
* <code>0</code> - Pull the SCL line low
* <code>1</code> - Release the SCL line</p>

#### SDAVAL field

<p>Global control: SDA override value:
* <code>0</code> - Pull the SDA line low
* <code>1</code> - Release the SDA line</p>

### VAL register

- Absolute Address: 0x38
- Base Offset: 0x38
- Size: 0x4

<p>Bus Oversampled Values Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 15:0|  SCL_RX  |   r  | 0x0 |  — |
|31:16|  SDA_RX  |   r  | 0x0 |  — |

#### SCL_RX field

<p>Global status: contains the last 16 SCL over-sampled values. LSB is most
recent.</p>

#### SDA_RX field

<p>Global status: contains the last 16 SDA over-sampled values. LSB is most
recent.</p>

### TIMING0 register

- Absolute Address: 0x3C
- Base Offset: 0x3C
- Size: 0x4

<p>SCL LOW and HIGH Periods Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 12:0|   THIGH  |  rw  | 0x0 |  — |
|28:16|   TLOW   |  rw  | 0x0 |  — |

#### THIGH field

<p>Global control: specifies the HIGH period of SCL (<code>t_HIGH</code>) in system clock
cycles. Must be <code>≥ 2</code>. See Table 11 in the I²C Specification for details. This
field is sized to meet the I2C Standard-mode (100 kHz)'s minimum
<code>t_HIGH = 4.0 μs</code> requirement, assuming a 1 GHz system clock.</p>

#### TLOW field

<p>Global control: specifies the LOW period of SCL (<code>t_LOW</code>) in system clock
cycles. Must be <code>≥ 2</code>. See Table 11 in the I2C Specification for more details.
This field is sized to meet the I2C Standard-mode (100 kHz) minimum
<code>t_LOW = 4.7 μs</code> requirement, assuming a 1 GHz system clock.</p>

### TIMING1 register

- Absolute Address: 0x40
- Base Offset: 0x40
- Size: 0x4

<p>Bus Rise and Fall Times Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 9:0 |    T_R   |  rw  | 0x0 |  — |
|24:16|    T_F   |  rw  | 0x0 |  — |

#### T_R field

<p>Global control: specifies the rise time of SDA and SCL (<code>t_r</code>) in system clock
cycles. The rise time is measured from 30% to 70% of the signal swing. See
Table 11 in the I2C Specification for more details. This field is sized to meet
I2C Standard-mode (100 kHz)'s maximum <code>t_r = 1000 ns</code> requirement, assuming a 1
GHz system clock.</p>

#### T_F field

<p>Global control: specifies the fall time of SDA and SCL (<code>t_f</code>) in system clock
cycles. The fall time is measured from 70% to 30% of the signal swing. See
Table 11 in the I2C Specification for more details. This field is sized to meet
I2C Standard-mode (100 kHz)'s maximum <code>t_f = 300 ns</code> requirement, assuming a 1
GHz system clock.</p>

### TIMING2 register

- Absolute Address: 0x44
- Base Offset: 0x44
- Size: 0x4

<p>START Condition Setup and Hold Times Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 12:0|  TSU_STA |  rw  | 0x0 |  — |
|28:16|  THD_STA |  rw  | 0x0 |  — |

#### TSU_STA field

<p>Global control: specifies the setup time for a repeated START condition
(<code>t_SU;STA</code>) in system clock cycles. See Table 11 in the I2C Specification for
details. This field is sized to meet I2C Standard-mode (100 kHz)'s minimum
<code>t_SU;STA = 4.7 μs</code> requirement, assuming a 1 GHz system clock.</p>

#### THD_STA field

<p>Global control: specifies the setup time for a (repeated) START condition
(<code>t_HD;STA</code>) in system clock cycles. See Table 11 in the I2C Specification for
details. This field is sized to meet I2C Standard-mode (100 kHz)'s minimum
<code>t_HD;STA = 4.0 μs</code> requirement, assuming a 1 GHz system clock.</p>

### TIMING3 register

- Absolute Address: 0x48
- Base Offset: 0x48
- Size: 0x4

<p>Data Setup and Hold Times Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 8:0 |  TSU_DAT |  rw  | 0x0 |  — |
|28:16|  THD_DAT |  rw  | 0x0 |  — |

#### TSU_DAT field

<p>Global control: specifies the data setup time (<code>t_SU;DAT</code>) in system clock
cycles. See Table 11 in the I2C Specification for details. This field is sized
to meet the I2C Standard-mode (100 kHz)'s <code>t_SU;DAT = 250 ns</code> minimum
requirement, assuming a 1 GHz system clock.</p>

#### THD_DAT field

<p>Global control: specifies the data and (N)ACK bits hold time (<code>t_HD;DAT</code>) in
system clock cycles. See Table 11 in the I2C Specification for details. This
field is sized to meet the I2C Standard-mode (100 kHz)'s <code>t_HD;DAT = 5.0 μs</code>
minimum requirement, assuming a 1 GHz system clock.</p>

### TIMING4 register

- Absolute Address: 0x4C
- Base Offset: 0x4C
- Size: 0x4

<p>STOP Condition Setup Time and Bus Free Time Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 12:0|  TSU_STO |  rw  | 0x0 |  — |
|28:16|   T_BUF  |  rw  | 0x0 |  — |

#### TSU_STO field

<p>Global control: specifies the setup time for a STOP condition (<code>t_SU;STO</code>) in
system clock cycles. See Table 11 in the I²C Specification for details. This
field is sized to meet I2C Standard-mode (100 kHz)'s <code>t_SU;STO = 4.0 μs</code>
minimum requirement, assuming a 1 GHz system clock.</p>

#### T_BUF field

<p>Global control: specifies the time between a STOP and START condition (<code>t_BUF</code>)
in system clock cycles. See Table 11 in the I²C Specification for details. This
field is sized to meet I2C Standard-mode (100kHz)'s <code>t_BUF = 4.7 μs</code> minimum
requirement, assuming a 1 GHz system clock.</p>

### TIMEOUT_CTRL register

- Absolute Address: 0x50
- Base Offset: 0x50
- Size: 0x4

<p>Timeout Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|29:0|    VAL   |  rw  | 0x0 |  — |
| 30 |   MODE   |  rw  | 0x0 |  — |
| 31 |    EN    |  rw  | 0x0 |  — |

#### VAL field

<p>Global control: Specifies the timeout value in system clock cycles. The meaning
of this field depends on <code>MODE</code>.</p>

#### MODE field

<p>Global control: timeout mode.
* <code>0</code> - Stretch Timeout (Controller Mode only). If the target stretches the
        clock for more time than <code>TIMEOUT_CTRL.VAL</code>, the <code>STRETCH_TIMEOUT</code>
        interrupt will be asserted.
* <code>1</code> - Bus Timeout. If SCL is LOW for more time than <code>TIMEOUT_CTRL.VAL</code>:
         * In Controller Mode, the <code>CONTROLLER_EVENTS.BUS_TIMEOUT</code> flag will
           be asserted, triggering the <code>CONTROLLER_HALT</code> interrupt.
         * In Target Mode, the <code>TARGET_EVENTS.BUS_TIMEOUT</code> flag will be set,
           triggering the <code>TX_STRETCH</code> interrupt.</p>

#### EN field

<p>Timeout Enable.</p>

### TARGET_ID register

- Absolute Address: 0x54
- Base Offset: 0x54
- Size: 0x4

<p>Target ID Register (Target Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 6:0 | ADDRESS0 |  rw  | 0x0 |  — |
| 13:7|   MASK0  |  rw  | 0x0 |  — |
|20:14| ADDRESS1 |  rw  | 0x0 |  — |
|27:21|   MASK1  |  rw  | 0x0 |  — |

#### ADDRESS0 field

<p>Target Address 0. This target responds if the 7-bit address matches
<code>ADDRESS0 &amp; MASK0</code>. <code>MASK0 = 0x0</code> disables this address.</p>

#### MASK0 field

<p>ADDRESS0 mask.</p>

#### ADDRESS1 field

<p>Target Address 1. This target responds if the 7-bit address matches
<code>ADDRESS1 &amp; MASK1</code>. <code>MASK1 = 0x0</code> disables this address.</p>

#### MASK1 field

<p>ADDRESS1 mask.</p>

### ACQDATA register

- Absolute Address: 0x58
- Base Offset: 0x58
- Size: 0x4

<p>Target RX FIFO Access Register (Target Mode only)</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   ABYTE  |r, ruser| 0x0 |  — |
|10:8|  SIGNAL  |    r   | 0x0 |  — |

#### ABYTE field

<p>Reading this register pops the ACQ FIFO. The meaning of this field depends on
<code>SIGNAL</code>:
 * <code>SIGNAL = 0x0</code>, <code>0x1</code>, <code>0x3</code>, <code>0x4</code>, or <code>0x5</code> - This field contains an
   address or data byte sent by the controller.
 * <code>SIGNAL = 0x2</code>, <code>0x6</code> - This field is meaningless.</p>

#### SIGNAL field

<p>This field indicates if this FIFO entry represents/is associated with control
signal(s):
 * <code>0x0</code> - The entry is an ordinary data byte that has been ACKed.
 * <code>0x1</code> - The entry is an address byte preceded by a START.
 * <code>0x2</code> - The entry is a STOP condition following ACKed data bytes.
 * <code>0x3</code> - The entry is an address byte preceded by a repeated START.
 * <code>0x4</code> - The entry is a NACKed data byte.
 * <code>0x5</code> - The entry is an address byte preceded by a (repeated) START.
           However, the data bytes that followed this address byte were
           NACKed.
 * <code>0x6</code> - Error. A transaction preceding ended abnormally, for example, due to
           an unexpected STOP condition, a Bus or Stretch Timeout, a software
           NACK, or a lost arbitration.</p>
<p>If the FIFO does not have enough space to record a complete transaction, an
Error (<code>0x6</code>) entry may appear alone.</p>

### TXDATA register

- Absolute Address: 0x5C
- Base Offset: 0x5C
- Size: 0x4

<p>Target TX FIFO Access Register (Target Mode only).</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |w, wuser| 0x0 |  — |

#### DATA field

<p>Writing to this register pushes data into the Target TX FIFO. The controller
reads data from this FIFO during a READ transaction.</p>

### HOST_TIMEOUT_CTRL register

- Absolute Address: 0x60
- Base Offset: 0x60
- Size: 0x4

<p>Controller Timeout Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|30:0|    VAL   |  rw  | 0x0 |  — |

#### VAL field

<p>Target/Monitor Mode control: controller clock generation timeout value
specified in system clock cycles.
 * Target Mode - If the controller stops generating the clock for more time
   than this setting, this target asserts the Controller Timeout Interrupt.
 * Monitor Mode - this field is required to be nonzero for the Bus Monitor to
   transition out of the initial Busy state. Set this field to <code>0x0</code> to disable
   this behavior.</p>

### TARGET_TIMEOUT_CTRL register

- Absolute Address: 0x64
- Base Offset: 0x64
- Size: 0x4

<p>Target Timeout Control Register (Target Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|30:0|    VAL   |  rw  | 0x0 |  — |
| 31 |    EN    |  rw  | 0x0 |  — |

#### VAL field

<p>When this target has stretched the clock for more time than this setting, this
target will NACK incoming data bytes or release the SDA line for outgoing data
bytes. The count is cumulative over an entire transaction. In other words, this
is SMBus's cumulative target clock extension time.</p>
<p>The behavior for the address byte is configurable via
<code>CTRL.NACK_ADDR_AFTER_TIMEOUT</code>.</p>

#### EN field

<p>Enable Target Timeout.</p>

### TARGET_NACK_COUNT register

- Absolute Address: 0x68
- Base Offset: 0x68
- Size: 0x4

<p>Target NACK Count Register (Target Mode only)</p>

|Bits|    Identifier   | Access |Reset|Name|
|----|-----------------|--------|-----|----|
| 7:0|TARGET_NACK_COUNT|rw, rclr| 0x0 |  — |

#### TARGET_NACK_COUNT field

<p>Indicates the number of transactions NACKed by this target since the last read
of this register, saturating at 255. This field can be used to track how many
transactions were missed when the Target RX FIFO is full.</p>

### TARGET_ACK_CTRL register

- Absolute Address: 0x6C
- Base Offset: 0x6C
- Size: 0x4

<p>Target ACK Control Register (Target Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 8:0|  NBYTES  |  rw  | 0x0 |  — |
| 31 |   NACK   |   w  | 0x0 |  — |

#### NBYTES field

<p>When <code>STATUS.ACK_CTRL_STRETCH = 1</code>, writing to this register specifies the
number of bytes this target should ACK. The count decrements per byte ACKed.
Effective only when <code>CTRL.ACK_CTRL_EN = 1</code>. See <code>CTRL.ACK_CTRL_EN</code> for details.</p>
<p>This control field is used to implement SMBus's mid-transfer (N)ACK responses.</p>

#### NACK field

<p>When <code>STATUS.ACK_CTRL_STRETCH = 1</code>, writing <code>1</code> to this field causes this
target to NACK all bytes of the transaction. Effective only when
<code>CTRL.ACK_CTRL_EN = 1</code>.</p>

### ACQ_FIFO_NEXT_DATA register

- Absolute Address: 0x70
- Base Offset: 0x70
- Size: 0x4

<p>Target RX FIFO Next Byte Register (Target Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>This field contains the next byte to be pushed into the Target RX FIFO,
allowing software to decide whether to accept or reject it. Valid only when
<code>STATUS.ACK_CTRL_STRETCH = 1</code>. See <code>CTRL.ACK_CTRL_EN</code> for details.</p>

### HOST_NACK_HANDLER_TIMEOUT register

- Absolute Address: 0x74
- Base Offset: 0x74
- Size: 0x4

<p>Controller NACK Timeout Register (Controller Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|30:0|    VAL   |  rw  | 0x0 |  — |
| 31 |    EN    |  rw  | 0x0 |  — |

#### VAL field

<p>Timeout value (specified in system clock cycles) for this controller Mode to
automatically STOP a transaction when <code>CONTROLLER_EVENTS.NACK</code> is set.</p>

#### EN field

<p>Enables Controller NACK Timeout.</p>

### CONTROLLER_EVENTS register

- Absolute Address: 0x78
- Base Offset: 0x78
- Size: 0x4

<p>Controller Events Register (Controller Mode only)</p>

|Bits|      Identifier      |  Access |Reset|Name|
|----|----------------------|---------|-----|----|
|  0 |         NACK         |rw, woclr| 0x0 |  — |
|  1 |UNHANDLED_NACK_TIMEOUT|rw, woclr| 0x0 |  — |
|  2 |      BUS_TIMEOUT     |rw, woclr| 0x0 |  — |
|  3 |   ARBITRATION_LOST   |rw, woclr| 0x0 |  — |

#### NACK field

<p>Indicates that this controller has halted due to an unexpected NACK sent by
the target. This behavior can be disabled by writing <code>1</code> to <code>FDATA.NAKOK</code>. This
bit triggers the <code>CONTROLLER_HALT</code> interrupt. Writing <code>1</code> clears this bit.</p>

#### UNHANDLED_NACK_TIMEOUT field

<p>Indicates that this controller has halted due to a Controller NACK Timeout. See
<code>HOST_NACK_HANDLER_TIMEOUT</code> for details. This bit triggers the
<code>CONTROLLER_HALT</code> interrupt. Writing <code>1</code> clears this bit.</p>

#### BUS_TIMEOUT field

<p>Indicates that this controller has halted due to a Bus Timeout. See
<code>TIMEOUT_CTRL</code> for details. This bit triggers the <code>CONTROLLER_HALT</code> interrupt.
Writing <code>1</code> clears this bit.</p>

#### ARBITRATION_LOST field

<p>Indicates that the controller has halted due to it losing an arbitration
against another controller. This bit triggers the <code>CONTROLLER_HALT</code> interrupt.
Writing <code>1</code> clears this bit.</p>

### TARGET_EVENTS register

- Absolute Address: 0x7C
- Base Offset: 0x7C
- Size: 0x4

<p>Target Events Register (Target Mode)</p>

|Bits|   Identifier   |  Access |Reset|Name|
|----|----------------|---------|-----|----|
|  0 |   TX_PENDING   |rw, woclr| 0x0 |  — |
|  1 |   BUS_TIMEOUT  |rw, woclr| 0x0 |  — |
|  2 |ARBITRATION_LOST|rw, woclr| 0x0 |  — |
|  3 |  START_DETECT  |rw, woclr| 0x0 |  — |
|  4 |   STOP_DETECT  |rw, woclr| 0x0 |  — |

#### TX_PENDING field

<p>Indicates that the target is stretching the clock due to receiving a READ
address byte and waiting for software to confirm the release of the Target
TX FIFO data. Valid only if <code>CTRL.TX_STRETCH_CTRL_EN = 1</code>. See
<code>CTRL.TX_STRETCH_CTRL_EN</code> for details. This bit triggers the <code>TX_STRETCH</code>
interrupt. Writing <code>1</code> clears this bit.</p>

#### BUS_TIMEOUT field

<p>Indicates that this target has halted due a Bus Timeout terminating a READ
transaction. See <code>TIMEOUT_CTRL</code> for details. This bit triggers the <code>TX_STRETCH</code>
interrupt. Writing <code>1</code> clears this bit.</p>

#### ARBITRATION_LOST field

<p>Indicates that a controller has lost arbitration, causing a READ
transaction to end. This bit triggers the <code>TX_STRETCH</code> interrupt. Writing <code>1</code>
clears this bit.</p>

#### START_DETECT field

<p>Start Detect Flag (Target Mode only). Set to 1 by hardware when a START
(or repeated START) is detected while <code>CTRL.ENABLETARGET = 1</code>. Cleared when
software writes 1.</p>

#### STOP_DETECT field

<p>Stop Detect Flag (Target Mode only). Set to 1 by hardware when a STOP is
detected while <code>CTRL.ENABLETARGET = 1</code>. Cleared when software writes 1.</p>

### SMBUS_STATUS register

- Absolute Address: 0x80
- Base Offset: 0x80
- Size: 0x4

<p>SMBus Status Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  SMBSUS  |   r  | 0x0 |  — |
|  4 | SMBALERT |   r  | 0x0 |  — |

#### SMBSUS field

<p>Target Mode status: indicates that the <code>smbsus_ni</code> input is asserted.</p>

#### SMBALERT field

<p>Controller Mode status: indicates that the <code>smbalert_ni</code> input is asserted.</p>

## i2c address map

- Absolute Address: 0x200
- Base Offset: 0x0
- Size: 0x84
- Array Dimensions: [3]
- Array Stride: 0x200
- Total Size: 0x600

|Offset|        Identifier       |Name|
|------|-------------------------|----|
| 0x00 |        INTR_STATE       |  — |
| 0x04 |       INTR_ENABLE       |  — |
| 0x08 |        INTR_TEST        |  — |
| 0x0C |        SMBUS_CTRL       |  — |
| 0x10 |           CTRL          |  — |
| 0x14 |          STATUS         |  — |
| 0x18 |          RDATA          |  — |
| 0x1C |          FDATA          |  — |
| 0x20 |        FIFO_CTRL        |  — |
| 0x24 |     HOST_FIFO_CONFIG    |  — |
| 0x28 |    TARGET_FIFO_CONFIG   |  — |
| 0x2C |     HOST_FIFO_STATUS    |  — |
| 0x30 |    TARGET_FIFO_STATUS   |  — |
| 0x34 |           OVRD          |  — |
| 0x38 |           VAL           |  — |
| 0x3C |         TIMING0         |  — |
| 0x40 |         TIMING1         |  — |
| 0x44 |         TIMING2         |  — |
| 0x48 |         TIMING3         |  — |
| 0x4C |         TIMING4         |  — |
| 0x50 |       TIMEOUT_CTRL      |  — |
| 0x54 |        TARGET_ID        |  — |
| 0x58 |         ACQDATA         |  — |
| 0x5C |          TXDATA         |  — |
| 0x60 |    HOST_TIMEOUT_CTRL    |  — |
| 0x64 |   TARGET_TIMEOUT_CTRL   |  — |
| 0x68 |    TARGET_NACK_COUNT    |  — |
| 0x6C |     TARGET_ACK_CTRL     |  — |
| 0x70 |    ACQ_FIFO_NEXT_DATA   |  — |
| 0x74 |HOST_NACK_HANDLER_TIMEOUT|  — |
| 0x78 |    CONTROLLER_EVENTS    |  — |
| 0x7C |      TARGET_EVENTS      |  — |
| 0x80 |       SMBUS_STATUS      |  — |

### INTR_STATE register

- Absolute Address: 0x200
- Base Offset: 0x0
- Size: 0x4

<p>Interrupt Status Register</p>

|Bits|       Identifier       |  Access |Reset|Name|
|----|------------------------|---------|-----|----|
|  0 |      FMT_THRESHOLD     |    r    | 0x0 |  — |
|  1 |      RX_THRESHOLD      |    r    | 0x0 |  — |
|  2 |      ACQ_THRESHOLD     |    r    | 0x0 |  — |
|  3 |       RX_OVERFLOW      |rw, woclr| 0x0 |  — |
|  4 |     CONTROLLER_HALT    |    r    | 0x0 |  — |
|  5 |    SCL_INTERFERENCE    |rw, woclr| 0x0 |  — |
|  6 |    SDA_INTERFERENCE    |rw, woclr| 0x0 |  — |
|  7 |     STRETCH_TIMEOUT    |rw, woclr| 0x0 |  — |
|  8 |      SDA_UNSTABLE      |rw, woclr| 0x0 |  — |
|  9 |      CMD_COMPLETE      |rw, woclr| 0x0 |  — |
| 10 |       TX_STRETCH       |    r    | 0x0 |  — |
| 11 |      TX_THRESHOLD      |    r    | 0x0 |  — |
| 12 |       ACQ_STRETCH      |    r    | 0x0 |  — |
| 13 |       UNEXP_STOP       |rw, woclr| 0x0 |  — |
| 14 |      HOST_TIMEOUT      |rw, woclr| 0x0 |  — |
| 15 |        SMBALERT        |rw, woclr| 0x0 |  — |
| 16 |CONTROLLER_TX_FIFO_ERROR|rw, woclr| 0x0 |  — |
| 17 |CONTROLLER_RX_FIFO_ERROR|rw, woclr| 0x0 |  — |
| 18 |  TARGET_TX_FIFO_ERROR  |rw, woclr| 0x0 |  — |
| 19 |  TARGET_RX_FIFO_ERROR  |rw, woclr| 0x0 |  — |

#### FMT_THRESHOLD field

<p>Controller Mode interrupt: remains asserted while the Controller TX FIFO level
is less than <code>HOST_FIFO_CONFIG.FMT_THRESH</code>.</p>

#### RX_THRESHOLD field

<p>Controller Mode interrupt: remains asserted while the Controller RX FIFO level
is greater than <code>HOST_FIFO_CONFIG.RX_THRESH</code>.</p>

#### ACQ_THRESHOLD field

<p>Target Mode interrupt: remains asserted while the Target RX FIFO level is
greater than <code>TARGET_FIFO_CONFIG.ACQ_THRESH</code>.</p>

#### RX_OVERFLOW field

<p>Controller Mode interrupt: asserted when the Controller RX FIFO overflows.
Write <code>1</code> to clear.</p>

#### CONTROLLER_HALT field

<p>Controller Mode interrupt: remains asserted while this controller halts. The
flags in the <code>CONTROLLER_EVENTS</code> register explain the reason(s) for the
halting. Clearing the <code>CONTROLLER_EVENTS</code> flags clears this interrupt.</p>

#### SCL_INTERFERENCE field

<p>Controller Mode interrupt: asserted when SCL is unexpectedly pulled LOW by
another controller. Write <code>1</code> to clear.</p>

#### SDA_INTERFERENCE field

<p>Controller Mode interrupt: asserted when SDA is unexpectedly pulled LOW by
another controller. Write <code>1</code> to clear.</p>

#### STRETCH_TIMEOUT field

<p>Controller Mode interrupt: asserted when the target stretches the clock longer
than <code>TIMEOUT_CTRL.VAL</code> (valid only when <code>TIMEOUT_CTRL.MODE = 0</code>). Write <code>1</code> to
clear.</p>

#### SDA_UNSTABLE field

<p>Controller Mode interrupt: asserted when the target fails to keep SDA stable
during a transmission. Write <code>1</code> to clear.</p>

#### CMD_COMPLETE field

<p>Controller/Target Mode interrupt: asserted when this/the controller finishes
generating a STOP or repeated START. Write <code>1</code> to clear.</p>

#### TX_STRETCH field

<p>Target Mode interrupt: remains asserted while this target is stretching the
clock or has halted. The flags in the <code>TARGET_EVENTS</code> register explain the
reason(s) for clock stretching/halting. Clearing the <code>TARGET_EVENTS</code> flags
clears this interrupt.</p>

#### TX_THRESHOLD field

<p>Target Mode interrupt: remains asserted while the Target TX FIFO level is less
than <code>TARGET_FIFO_CONFIG.TX_THRESH</code>.</p>

#### ACQ_STRETCH field

<p>Target Mode interrupt: remains asserted while the target is stretching the clock
because 1) the Target RX FIFO is full or 2) the <code>TARGET_ACK_CTRL.NBYTES</code> count
has reached <code>0</code> (only if <code>CTRL.ACK_CTRL_EN = 1</code>).</p>

#### UNEXP_STOP field

<p>Target Mode interrupt: asserted when the controller sends this target a STOP
before this target NACKs. Write <code>1</code> to clear.</p>

#### HOST_TIMEOUT field

<p>Target Mode interrupt: asserted when the controller stops generating the clock
longer than <code>HOST_TIMEOUT_CTRL.VAL</code>. Write <code>1</code> to clear.</p>

#### SMBALERT field

<p>Controller Mode interrupt: asserted when <code>smbalert_ni</code> is asserted. Write <code>1</code>
to clear.</p>

#### CONTROLLER_TX_FIFO_ERROR field

<p>Controller Mode interrupt: asserted when the Controller TX FIFO has a parity
error. Write <code>1</code> to clear.</p>

#### CONTROLLER_RX_FIFO_ERROR field

<p>Controller Mode interrupt: asserted when the Controller RX FIFO has a parity
error. Write <code>1</code> to clear.</p>

#### TARGET_TX_FIFO_ERROR field

<p>Target Mode interrupt: asserted when the Target TX FIFO has a parity error.
Write <code>1</code> to clear.</p>

#### TARGET_RX_FIFO_ERROR field

<p>Target Mode interrupt: asserted when the Target RX FIFO has a parity error.
Write <code>1</code> to clear.</p>

### INTR_ENABLE register

- Absolute Address: 0x204
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|       Identifier       |Access|Reset|Name|
|----|------------------------|------|-----|----|
|  0 |      FMT_THRESHOLD     |  rw  | 0x0 |  — |
|  1 |      RX_THRESHOLD      |  rw  | 0x0 |  — |
|  2 |      ACQ_THRESHOLD     |  rw  | 0x0 |  — |
|  3 |       RX_OVERFLOW      |  rw  | 0x0 |  — |
|  4 |     CONTROLLER_HALT    |  rw  | 0x0 |  — |
|  5 |    SCL_INTERFERENCE    |  rw  | 0x0 |  — |
|  6 |    SDA_INTERFERENCE    |  rw  | 0x0 |  — |
|  7 |     STRETCH_TIMEOUT    |  rw  | 0x0 |  — |
|  8 |      SDA_UNSTABLE      |  rw  | 0x0 |  — |
|  9 |      CMD_COMPLETE      |  rw  | 0x0 |  — |
| 10 |       TX_STRETCH       |  rw  | 0x0 |  — |
| 11 |      TX_THRESHOLD      |  rw  | 0x0 |  — |
| 12 |       ACQ_STRETCH      |  rw  | 0x0 |  — |
| 13 |       UNEXP_STOP       |  rw  | 0x0 |  — |
| 14 |      HOST_TIMEOUT      |  rw  | 0x0 |  — |
| 15 |        SMBALERT        |  rw  | 0x0 |  — |
| 16 |CONTROLLER_TX_FIFO_ERROR|  rw  | 0x0 |  — |
| 17 |CONTROLLER_RX_FIFO_ERROR|  rw  | 0x0 |  — |
| 18 |  TARGET_TX_FIFO_ERROR  |  rw  | 0x0 |  — |
| 19 |  TARGET_RX_FIFO_ERROR  |  rw  | 0x0 |  — |

#### FMT_THRESHOLD field

<p>Enables the <code>FMT_THRESHOLD</code> interrupt.</p>

#### RX_THRESHOLD field

<p>Enables the <code>RX_THRESHOLD</code> interrupt.</p>

#### ACQ_THRESHOLD field

<p>Enables the <code>ACQ_THRESHOLD</code> interrupt.</p>

#### RX_OVERFLOW field

<p>Enables the <code>RX_OVERFLOW</code> interrupt.</p>

#### CONTROLLER_HALT field

<p>Enables the <code>CONTROLLER_HALT</code> interrupt.</p>

#### SCL_INTERFERENCE field

<p>Enables the <code>SCL_INTERFERENCE</code> interrupt.</p>

#### SDA_INTERFERENCE field

<p>Enables the <code>SDA_INTERFERENCE</code> interrupt.</p>

#### STRETCH_TIMEOUT field

<p>Enables the <code>STRETCH_TIMEOUT</code> interrupt.</p>

#### SDA_UNSTABLE field

<p>Enables the <code>SDA_UNSTABLE</code> interrupt.</p>

#### CMD_COMPLETE field

<p>Enables the <code>CMD_COMPLETE</code> interrupt.</p>

#### TX_STRETCH field

<p>Enables the <code>TX_STRETCH</code> interrupt.</p>

#### TX_THRESHOLD field

<p>Enables the <code>TX_THRESHOLD</code> interrupt.</p>

#### ACQ_STRETCH field

<p>Enables the <code>ACQ_STRETCH</code> interrupt.</p>

#### UNEXP_STOP field

<p>Enables the <code>UNEXP_STOP</code> interrupt.</p>

#### HOST_TIMEOUT field

<p>Enables the <code>HOST_TIMEOUT</code> interrupt.</p>

#### SMBALERT field

<p>Enables the <code>SMBALERT</code> interrupt.</p>

#### CONTROLLER_TX_FIFO_ERROR field

<p>Enables the <code>CONTROLLER_TX_FIFO_ERROR</code> interrupt.</p>

#### CONTROLLER_RX_FIFO_ERROR field

<p>Enables the <code>CONTROLLER_RX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_TX_FIFO_ERROR field

<p>Enables the <code>TARGET_TX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_RX_FIFO_ERROR field

<p>Enables the <code>TARGET_RX_FIFO_ERROR</code> interrupt.</p>

### INTR_TEST register

- Absolute Address: 0x208
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|       Identifier       |Access|Reset|Name|
|----|------------------------|------|-----|----|
|  0 |      FMT_THRESHOLD     |  rw  | 0x0 |  — |
|  1 |      RX_THRESHOLD      |  rw  | 0x0 |  — |
|  2 |      ACQ_THRESHOLD     |  rw  | 0x0 |  — |
|  3 |       RX_OVERFLOW      |   w  | 0x0 |  — |
|  4 |     CONTROLLER_HALT    |  rw  | 0x0 |  — |
|  5 |    SCL_INTERFERENCE    |   w  | 0x0 |  — |
|  6 |    SDA_INTERFERENCE    |   w  | 0x0 |  — |
|  7 |     STRETCH_TIMEOUT    |   w  | 0x0 |  — |
|  8 |      SDA_UNSTABLE      |   w  | 0x0 |  — |
|  9 |      CMD_COMPLETE      |   w  | 0x0 |  — |
| 10 |       TX_STRETCH       |  rw  | 0x0 |  — |
| 11 |      TX_THRESHOLD      |  rw  | 0x0 |  — |
| 12 |       ACQ_STRETCH      |  rw  | 0x0 |  — |
| 13 |       UNEXP_STOP       |   w  | 0x0 |  — |
| 14 |      HOST_TIMEOUT      |   w  | 0x0 |  — |
| 15 |        SMBALERT        |   w  | 0x0 |  — |
| 16 |CONTROLLER_TX_FIFO_ERROR|   w  | 0x0 |  — |
| 17 |CONTROLLER_RX_FIFO_ERROR|   w  | 0x0 |  — |
| 18 |  TARGET_TX_FIFO_ERROR  |   w  | 0x0 |  — |
| 19 |  TARGET_RX_FIFO_ERROR  |   w  | 0x0 |  — |

#### FMT_THRESHOLD field

<p>Writing <code>1</code> forces the <code>FMT_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### RX_THRESHOLD field

<p>Writing <code>1</code> forces the <code>RX_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### ACQ_THRESHOLD field

<p>Writing <code>1</code> forces the <code>ACQ_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### RX_OVERFLOW field

<p>Writing <code>1</code> forces the <code>RX_OVERFLOW</code> interrupt.</p>

#### CONTROLLER_HALT field

<p>Writing <code>1</code> forces the <code>CONTROLLER_HALT</code> interrupt. Writing <code>0</code> releases it.</p>

#### SCL_INTERFERENCE field

<p>Writing <code>1</code> forces the <code>SCL_INTERFERENCE</code> interrupt.</p>

#### SDA_INTERFERENCE field

<p>Writing <code>1</code> forces the <code>SDA_INTERFERENCE</code> interrupt.</p>

#### STRETCH_TIMEOUT field

<p>Writing <code>1</code> forces the <code>STRETCH_TIMEOUT</code> interrupt.</p>

#### SDA_UNSTABLE field

<p>Writing <code>1</code> forces the <code>SDA_UNSTABLE</code> interrupt.</p>

#### CMD_COMPLETE field

<p>Writing <code>1</code> forces the <code>CMD_COMPLETE</code> interrupt.</p>

#### TX_STRETCH field

<p>Writing <code>1</code> forces the <code>TX_STRETCH</code> interrupt. Writing a <code>0</code> releases it.</p>

#### TX_THRESHOLD field

<p>Writing <code>1</code> forces the <code>TX_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### ACQ_STRETCH field

<p>Writing <code>1</code> forces the <code>ACQ_STRETCH</code> interrupt. Writing <code>0</code> releases it.</p>

#### UNEXP_STOP field

<p>Writing <code>1</code> forces the <code>UNEXP_STOP</code> interrupt.</p>

#### HOST_TIMEOUT field

<p>Writing <code>1</code> forces the <code>HOST_TIMEOUT</code> interrupt.</p>

#### SMBALERT field

<p>Writing <code>1</code> forces the <code>SMBALERT</code> interrupt.</p>

#### CONTROLLER_TX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>CONTROLLER_TX_FIFO_ERROR</code> interrupt.</p>

#### CONTROLLER_RX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>CONTROLLER_RX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_TX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>TARGET_TX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_RX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>TARGET_RX_FIFO_ERROR</code> interrupt.</p>

### SMBUS_CTRL register

- Absolute Address: 0x20C
- Base Offset: 0xC
- Size: 0x4

<p>SMBus Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  SMBSUS  |  rw  | 0x0 |  — |
|  4 | SMBALERT |  rw  | 0x0 |  — |

#### SMBSUS field

<p>Controller Mode control: asserts the <code>smbsus_no</code> output.</p>

#### SMBALERT field

<p>Target Mode control: asserts the <code>smbalert_no</code> output. This bit clears itself
when the controller addresses this target.</p>

### CTRL register

- Absolute Address: 0x210
- Base Offset: 0x10
- Size: 0x4

<p>Control Register</p>

|Bits|         Identifier        |Access|Reset|Name|
|----|---------------------------|------|-----|----|
|  0 |         ENABLEHOST        |  rw  | 0x0 |  — |
|  1 |        ENABLETARGET       |  rw  | 0x0 |  — |
|  2 |           LLPBK           |  rw  | 0x0 |  — |
|  3 |  NACK_ADDR_AFTER_TIMEOUT  |  rw  | 0x0 |  — |
|  4 |        ACK_CTRL_EN        |  rw  | 0x0 |  — |
|  5 |MULTI_CONTROLLER_MONITOR_EN|  rw  | 0x0 |  — |
|  6 |     TX_STRETCH_CTRL_EN    |  rw  | 0x0 |  — |
|  7 |     ACQ_START_STOP_EN     |  rw  | 0x0 |  — |

#### ENABLEHOST field

<p>Global control: configures this device's operating mode.
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 0</code> — Controller Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 1</code> — Target Mode
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 1</code> — Hybrid Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 0</code> — Monitor Mode</p>

#### ENABLETARGET field

<p>Global control: configures this device's operating mode.
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 0</code> — Controller Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 1</code> — Target Mode
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 1</code> — Hybrid Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 0</code> — Monitor Mode</p>

#### LLPBK field

<p>Global control: enables line loop-back. In Controller Mode, the internal logic
sees the <code>smbalert_ni</code> input as deasserted. In Target Mode, this target sends
all received SDA data back out, and the internal logic sees received data as
all 1's.</p>

#### NACK_ADDR_AFTER_TIMEOUT field

<p>Target Mode control: NACK address after timeout. If this bit is:
* <code>0</code> - This target ACKs the address byte even if a Stretch Timeout occurs
        (useful for SMBus).
* <code>1</code> - This target NACKs the address byte when a Stretch Timeout occurs.</p>

#### ACK_CTRL_EN field

<p>Target Mode control: enables the Software ACK Control Mechanism. If this bit is:
* <code>0</code> - This target ACKs a data byte whenever the ACQ FIFO has space.
* <code>1</code> - This target ACKs the first <code>TARGET_ACK_CTRL.NBYTES</code> bytes. If another
        byte arrives, this target stretches the clock and awaits software
        intervention (and asserts <code>STATUS.ACK_CTRL_STRETCH</code>). The software can
         1. accept the new byte(s) by reloading the <code>TARGET_ACK_CTRL.NBYTES</code>
            counter; or
         2. reject the new byte(s) by writing <code>1</code> to <code>TARGET_ACK_CTRL.NACK</code>
            (useful for SMBus).</p>

#### MULTI_CONTROLLER_MONITOR_EN field

<p>Global control: enables the Bus Monitor. Set this bit to <code>1</code>
only in a multi-controller environment.</p>
<p>If a <code>0</code>-&gt;<code>1</code> transition happens while <code>ENABLEHOST</code> and <code>ENABLETARGET</code> are both
<code>0</code>, the Bus Monitor will enable and begin in the 'Bus Busy' state. To
transition to a 'Bus Free' state, <code>HOST_TIMEOUT_CTRL</code> must be nonzero so the
Bus Monitor may count out idle cycles to confirm the freedom to transmit. In
addition, the Bus Monitor will track whether the bus is free based on the
enabled timeouts and detected STOP symbols. For Multi-Controller Mode, ensure
<code>MULTI_CONTROLLER_MONITOR_EN</code> becomes <code>1</code> no later than <code>ENABLEHOST</code> or
<code>ENABLETARGET</code>. This bit can be set at the same time as either or both of the
other two, though.</p>
<p>Note that if <code>MULTI_CONTROLLER_MONITOR_EN</code> is set after <code>ENABLEHOST</code> or
<code>ENABLETARGET</code>, the Bus Monitor will begin in the 'Bus Free' state instead.
This would violate the proper protocol for a controller to join a multi-controller
environment. However, if this controller is known to be the first to join, this
ordering will enable skipping the idle wait.</p>
<p>When <code>0</code>, the bus monitor will report that the bus is always free, so the
Controller FSM is never blocked from transmitting.</p>

#### TX_STRETCH_CTRL_EN field

<p>Target mode control: enables the Software TX Stretch Control Mechanism. If this
bit is:
 * <code>0</code> - Automatic TX Stretch: When this target receives a READ address
         byte, it only stretches the clock if the TX FIFO is empty; otherwise,
         it pops the FIFO and transmits the data byte. The target never sets
         the <code>TARGET_EVENTS</code> register flags in this mode.
 * <code>1</code> - Software TX Stretch Mode: When this target receives a READ address,
         it always stretches the clock and sets the <code>TARGET_EVENTS.TX_PENDING</code>
         flag. The software can:
          1. confirm the release and transmission of the TX FIFO data by
             writing a 1 to clear the <code>TARGET_EVENTS.TX_PENDING</code> flag; or
          2. reset the TX FIFO by writing 1 to <code>FIFO_CTRL.TXRST</code> and load in
             new data via the <code>TXDATA</code> register--useful whenthe READ address
             is targeting a different function of the target.
         In this mode, the target always sets the <code>TARGET_EVENTS</code> register
         flags.</p>

#### ACQ_START_STOP_EN field

<p>ACQ FIFO Start/Stop Enable (Target Mode only):
* <code>0</code> - Start/Stop symbols are NOT written into the ACQ FIFO. The firmware
        should rely on <code>TARGET_EVENTS.START_DETECT</code> and <code>TARGET_EVENTS.STOP_DETECT</code>
        flags to detect Start/Stop events.
* <code>1</code> - Start/Stop symbols ARE written into the ACQ FIFO (legacy behavior).
        When a START (or repeated START) is detected, an <code>AcqStart</code> or <code>AcqRestart</code>
        entry is written. When a STOP is detected, an <code>AcqStop</code> or <code>AcqNackStop</code>
        entry is written.</p>

### STATUS register

- Absolute Address: 0x214
- Base Offset: 0x14
- Size: 0x4

<p>Status Register</p>

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|  0 |     FMTFULL    |   r  | 0x0 |  — |
|  1 |     RXFULL     |   r  | 0x0 |  — |
|  2 |    FMTEMPTY    |   r  | 0x1 |  — |
|  3 |    HOSTIDLE    |   r  | 0x1 |  — |
|  4 |   TARGETIDLE   |   r  | 0x1 |  — |
|  5 |     RXEMPTY    |   r  | 0x1 |  — |
|  6 |     TXFULL     |   r  | 0x0 |  — |
|  7 |     ACQFULL    |   r  | 0x0 |  — |
|  8 |     TXEMPTY    |   r  | 0x1 |  — |
|  9 |    ACQEMPTY    |   r  | 0x1 |  — |
| 10 |ACK_CTRL_STRETCH|   r  | 0x0 |  — |

#### FMTFULL field

<p>Controller Mode status: Controller TX FIFO Full.</p>

#### RXFULL field

<p>Controller Mode status: Controller RX FIFO Full.</p>

#### FMTEMPTY field

<p>Controller Mode status: Controller TX FIFO Empty.</p>

#### HOSTIDLE field

<p>Controller Mode status: Controller FSM idle.</p>

#### TARGETIDLE field

<p>Target Mode status: Target FSM idle.</p>

#### RXEMPTY field

<p>Controller Mode status: Controller RX FIFO empty.</p>

#### TXFULL field

<p>Target Mode status: Target TX FIFO full.</p>

#### ACQFULL field

<p>Target Mode status: Target RX FIFO full.</p>

#### TXEMPTY field

<p>Target Mode status: Target TX FIFO empty.</p>

#### ACQEMPTY field

<p>Target Mode status: Target RX FIFO empty.</p>

#### ACK_CTRL_STRETCH field

<p>Target Mode status: indicates that this target is stretching the clock due to
the Software ACK Control Mechanism. See <code>CTRL.ACK_CTRL_EN</code> for details.</p>

### RDATA register

- Absolute Address: 0x218
- Base Offset: 0x18
- Size: 0x4

<p>Controller RX FIFO Access Register (Controller Mode only)</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |r, ruser| 0x0 |  — |

#### DATA field

<p>Reading this register pops the Controller RX FIFO.</p>

### FDATA register

- Absolute Address: 0x21C
- Base Offset: 0x1C
- Size: 0x4

<p>Controller TX FIFO Access Register (Controller Mode only)</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   FBYTE  |w, wuser| 0x0 |  — |
|  8 |   START  |    w   | 0x0 |  — |
|  9 |   STOP   |    w   | 0x0 |  — |
| 10 |   READB  |    w   | 0x0 |  — |
| 11 |   RCONT  |    w   | 0x0 |  — |
| 12 |   NAKOK  |    w   | 0x0 |  — |

#### FBYTE field

<p>Writing to this register pushes an entry into the Controller TX FIFO. The
meaning of this field depends on the value of the <code>READB</code> field:
 * <code>READB = 0</code> - This field is the WRITE data byte.
 * <code>READB = 1</code> - This field specifies the number of bytes to read from the
                 target. Setting this field to 0 reads 256 bytes.</p>

#### START field

<p>Generate a START condition on the bus before sending the byte.</p>

#### STOP field

<p>Generate a STOP condition on the bus after sending the byte.</p>

#### READB field

<p>Read/write:
* <code>0</code> - Issue WRITE transaction
* <code>1</code> - Issue READ transaction</p>

#### RCONT field

<p>Read continue/stop:
* <code>0</code> — Read Stop: The controller NACKs the last data byte. Use this if this
        is the last READ in a sequence.
* <code>1</code> — Read Continue: The controller ACKs the last data byte. Use this if
        this is an intermediate READ in a sequence.</p>

#### NAKOK field

<p>NACK OK. When set, this controller will not care if this byte is NACKed. It
will not halt, set the <code>CONTROLLER_EVENTS.NACK</code> flag, or assert the
<code>CONTROLLER_HALT</code> Interrupt. This behavior is useful for protocols like Serial
Camera Control Bus (SCCB).</p>

### FIFO_CTRL register

- Absolute Address: 0x220
- Base Offset: 0x20
- Size: 0x4

<p>FIFO Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   RXRST  |   w  | 0x0 |  — |
|  1 |  FMTRST  |   w  | 0x0 |  — |
|  7 |  ACQRST  |   w  | 0x0 |  — |
|  8 |   TXRST  |   w  | 0x0 |  — |

#### RXRST field

<p>Controller Mode control: writing <code>1</code> resets the Controller RX FIFO.</p>

#### FMTRST field

<p>Controller Mode control: writing <code>1</code> resets the Controller TX FIFO.</p>

#### ACQRST field

<p>Target Mode control: writing <code>1</code> resets the Target RX FIFO.</p>

#### TXRST field

<p>Target Mode control: writing <code>1</code> resets the Target TX FIFO.</p>

### HOST_FIFO_CONFIG register

- Absolute Address: 0x224
- Base Offset: 0x24
- Size: 0x4

<p>Controller FIFO Configuration Register (Controller Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0| RX_THRESH|  rw  | 0x0 |  — |
|27:16|FMT_THRESH|  rw  | 0x0 |  — |

#### RX_THRESH field

<p>The <code>RX_THRESH</code> interrupt remains asserted while the Controller RX FIFO level
is greater than this setting.</p>

#### FMT_THRESH field

<p>The <code>FMT_THRESH</code> interrupt remains asserted while the Controller TX FIFO level
is less than this setting.</p>

### TARGET_FIFO_CONFIG register

- Absolute Address: 0x228
- Base Offset: 0x28
- Size: 0x4

<p>Target FIFOs Configuration Register (Target Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0| TX_THRESH|  rw  | 0x0 |  — |
|27:16|ACQ_THRESH|  rw  | 0x0 |  — |

#### TX_THRESH field

<p>The <code>TX_THRESH</code> interrupt remains asserted while the Target TX FIFO level is
less than this setting.</p>

#### ACQ_THRESH field

<p>The <code>ACQ_THRESH</code> interrupt remains asserted while the Target RX FIFO level is
greater than this setting.</p>

### HOST_FIFO_STATUS register

- Absolute Address: 0x22C
- Base Offset: 0x2C
- Size: 0x4

<p>Controller FIFOs Status Register (Controller Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0|  FMTLVL  |   r  |  —  |  — |
|27:16|   RXLVL  |   r  |  —  |  — |

#### FMTLVL field

<p>Controller TX FIFO fill level.</p>

#### RXLVL field

<p>Controller RX FIFO fill level.</p>

### TARGET_FIFO_STATUS register

- Absolute Address: 0x230
- Base Offset: 0x30
- Size: 0x4

<p>Target FIFOs Status Register (Target Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0|   TXLVL  |   r  | 0x0 |  — |
|27:16|  ACQLVL  |   r  | 0x0 |  — |

#### TXLVL field

<p>Target TX FIFO fill level.</p>

#### ACQLVL field

<p>Target RX FIFO fill level.</p>

### OVRD register

- Absolute Address: 0x234
- Base Offset: 0x34
- Size: 0x4

<p>Override Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 | TXOVRDEN |  rw  | 0x0 |  — |
|  1 |  SCLVAL  |  rw  | 0x0 |  — |
|  2 |  SDAVAL  |  rw  | 0x0 |  — |

#### TXOVRDEN field

<p>Global control: enables control of the SDA and SCL lines through the <code>SDA_VAL</code>
and <code>SCL_VAL</code> fields, respectively.</p>

#### SCLVAL field

<p>Global control: SCL override value:
* <code>0</code> - Pull the SCL line low
* <code>1</code> - Release the SCL line</p>

#### SDAVAL field

<p>Global control: SDA override value:
* <code>0</code> - Pull the SDA line low
* <code>1</code> - Release the SDA line</p>

### VAL register

- Absolute Address: 0x238
- Base Offset: 0x38
- Size: 0x4

<p>Bus Oversampled Values Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 15:0|  SCL_RX  |   r  | 0x0 |  — |
|31:16|  SDA_RX  |   r  | 0x0 |  — |

#### SCL_RX field

<p>Global status: contains the last 16 SCL over-sampled values. LSB is most
recent.</p>

#### SDA_RX field

<p>Global status: contains the last 16 SDA over-sampled values. LSB is most
recent.</p>

### TIMING0 register

- Absolute Address: 0x23C
- Base Offset: 0x3C
- Size: 0x4

<p>SCL LOW and HIGH Periods Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 12:0|   THIGH  |  rw  | 0x0 |  — |
|28:16|   TLOW   |  rw  | 0x0 |  — |

#### THIGH field

<p>Global control: specifies the HIGH period of SCL (<code>t_HIGH</code>) in system clock
cycles. Must be <code>≥ 2</code>. See Table 11 in the I²C Specification for details. This
field is sized to meet the I2C Standard-mode (100 kHz)'s minimum
<code>t_HIGH = 4.0 μs</code> requirement, assuming a 1 GHz system clock.</p>

#### TLOW field

<p>Global control: specifies the LOW period of SCL (<code>t_LOW</code>) in system clock
cycles. Must be <code>≥ 2</code>. See Table 11 in the I2C Specification for more details.
This field is sized to meet the I2C Standard-mode (100 kHz) minimum
<code>t_LOW = 4.7 μs</code> requirement, assuming a 1 GHz system clock.</p>

### TIMING1 register

- Absolute Address: 0x240
- Base Offset: 0x40
- Size: 0x4

<p>Bus Rise and Fall Times Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 9:0 |    T_R   |  rw  | 0x0 |  — |
|24:16|    T_F   |  rw  | 0x0 |  — |

#### T_R field

<p>Global control: specifies the rise time of SDA and SCL (<code>t_r</code>) in system clock
cycles. The rise time is measured from 30% to 70% of the signal swing. See
Table 11 in the I2C Specification for more details. This field is sized to meet
I2C Standard-mode (100 kHz)'s maximum <code>t_r = 1000 ns</code> requirement, assuming a 1
GHz system clock.</p>

#### T_F field

<p>Global control: specifies the fall time of SDA and SCL (<code>t_f</code>) in system clock
cycles. The fall time is measured from 70% to 30% of the signal swing. See
Table 11 in the I2C Specification for more details. This field is sized to meet
I2C Standard-mode (100 kHz)'s maximum <code>t_f = 300 ns</code> requirement, assuming a 1
GHz system clock.</p>

### TIMING2 register

- Absolute Address: 0x244
- Base Offset: 0x44
- Size: 0x4

<p>START Condition Setup and Hold Times Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 12:0|  TSU_STA |  rw  | 0x0 |  — |
|28:16|  THD_STA |  rw  | 0x0 |  — |

#### TSU_STA field

<p>Global control: specifies the setup time for a repeated START condition
(<code>t_SU;STA</code>) in system clock cycles. See Table 11 in the I2C Specification for
details. This field is sized to meet I2C Standard-mode (100 kHz)'s minimum
<code>t_SU;STA = 4.7 μs</code> requirement, assuming a 1 GHz system clock.</p>

#### THD_STA field

<p>Global control: specifies the setup time for a (repeated) START condition
(<code>t_HD;STA</code>) in system clock cycles. See Table 11 in the I2C Specification for
details. This field is sized to meet I2C Standard-mode (100 kHz)'s minimum
<code>t_HD;STA = 4.0 μs</code> requirement, assuming a 1 GHz system clock.</p>

### TIMING3 register

- Absolute Address: 0x248
- Base Offset: 0x48
- Size: 0x4

<p>Data Setup and Hold Times Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 8:0 |  TSU_DAT |  rw  | 0x0 |  — |
|28:16|  THD_DAT |  rw  | 0x0 |  — |

#### TSU_DAT field

<p>Global control: specifies the data setup time (<code>t_SU;DAT</code>) in system clock
cycles. See Table 11 in the I2C Specification for details. This field is sized
to meet the I2C Standard-mode (100 kHz)'s <code>t_SU;DAT = 250 ns</code> minimum
requirement, assuming a 1 GHz system clock.</p>

#### THD_DAT field

<p>Global control: specifies the data and (N)ACK bits hold time (<code>t_HD;DAT</code>) in
system clock cycles. See Table 11 in the I2C Specification for details. This
field is sized to meet the I2C Standard-mode (100 kHz)'s <code>t_HD;DAT = 5.0 μs</code>
minimum requirement, assuming a 1 GHz system clock.</p>

### TIMING4 register

- Absolute Address: 0x24C
- Base Offset: 0x4C
- Size: 0x4

<p>STOP Condition Setup Time and Bus Free Time Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 12:0|  TSU_STO |  rw  | 0x0 |  — |
|28:16|   T_BUF  |  rw  | 0x0 |  — |

#### TSU_STO field

<p>Global control: specifies the setup time for a STOP condition (<code>t_SU;STO</code>) in
system clock cycles. See Table 11 in the I²C Specification for details. This
field is sized to meet I2C Standard-mode (100 kHz)'s <code>t_SU;STO = 4.0 μs</code>
minimum requirement, assuming a 1 GHz system clock.</p>

#### T_BUF field

<p>Global control: specifies the time between a STOP and START condition (<code>t_BUF</code>)
in system clock cycles. See Table 11 in the I²C Specification for details. This
field is sized to meet I2C Standard-mode (100kHz)'s <code>t_BUF = 4.7 μs</code> minimum
requirement, assuming a 1 GHz system clock.</p>

### TIMEOUT_CTRL register

- Absolute Address: 0x250
- Base Offset: 0x50
- Size: 0x4

<p>Timeout Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|29:0|    VAL   |  rw  | 0x0 |  — |
| 30 |   MODE   |  rw  | 0x0 |  — |
| 31 |    EN    |  rw  | 0x0 |  — |

#### VAL field

<p>Global control: Specifies the timeout value in system clock cycles. The meaning
of this field depends on <code>MODE</code>.</p>

#### MODE field

<p>Global control: timeout mode.
* <code>0</code> - Stretch Timeout (Controller Mode only). If the target stretches the
        clock for more time than <code>TIMEOUT_CTRL.VAL</code>, the <code>STRETCH_TIMEOUT</code>
        interrupt will be asserted.
* <code>1</code> - Bus Timeout. If SCL is LOW for more time than <code>TIMEOUT_CTRL.VAL</code>:
         * In Controller Mode, the <code>CONTROLLER_EVENTS.BUS_TIMEOUT</code> flag will
           be asserted, triggering the <code>CONTROLLER_HALT</code> interrupt.
         * In Target Mode, the <code>TARGET_EVENTS.BUS_TIMEOUT</code> flag will be set,
           triggering the <code>TX_STRETCH</code> interrupt.</p>

#### EN field

<p>Timeout Enable.</p>

### TARGET_ID register

- Absolute Address: 0x254
- Base Offset: 0x54
- Size: 0x4

<p>Target ID Register (Target Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 6:0 | ADDRESS0 |  rw  | 0x0 |  — |
| 13:7|   MASK0  |  rw  | 0x0 |  — |
|20:14| ADDRESS1 |  rw  | 0x0 |  — |
|27:21|   MASK1  |  rw  | 0x0 |  — |

#### ADDRESS0 field

<p>Target Address 0. This target responds if the 7-bit address matches
<code>ADDRESS0 &amp; MASK0</code>. <code>MASK0 = 0x0</code> disables this address.</p>

#### MASK0 field

<p>ADDRESS0 mask.</p>

#### ADDRESS1 field

<p>Target Address 1. This target responds if the 7-bit address matches
<code>ADDRESS1 &amp; MASK1</code>. <code>MASK1 = 0x0</code> disables this address.</p>

#### MASK1 field

<p>ADDRESS1 mask.</p>

### ACQDATA register

- Absolute Address: 0x258
- Base Offset: 0x58
- Size: 0x4

<p>Target RX FIFO Access Register (Target Mode only)</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   ABYTE  |r, ruser| 0x0 |  — |
|10:8|  SIGNAL  |    r   | 0x0 |  — |

#### ABYTE field

<p>Reading this register pops the ACQ FIFO. The meaning of this field depends on
<code>SIGNAL</code>:
 * <code>SIGNAL = 0x0</code>, <code>0x1</code>, <code>0x3</code>, <code>0x4</code>, or <code>0x5</code> - This field contains an
   address or data byte sent by the controller.
 * <code>SIGNAL = 0x2</code>, <code>0x6</code> - This field is meaningless.</p>

#### SIGNAL field

<p>This field indicates if this FIFO entry represents/is associated with control
signal(s):
 * <code>0x0</code> - The entry is an ordinary data byte that has been ACKed.
 * <code>0x1</code> - The entry is an address byte preceded by a START.
 * <code>0x2</code> - The entry is a STOP condition following ACKed data bytes.
 * <code>0x3</code> - The entry is an address byte preceded by a repeated START.
 * <code>0x4</code> - The entry is a NACKed data byte.
 * <code>0x5</code> - The entry is an address byte preceded by a (repeated) START.
           However, the data bytes that followed this address byte were
           NACKed.
 * <code>0x6</code> - Error. A transaction preceding ended abnormally, for example, due to
           an unexpected STOP condition, a Bus or Stretch Timeout, a software
           NACK, or a lost arbitration.</p>
<p>If the FIFO does not have enough space to record a complete transaction, an
Error (<code>0x6</code>) entry may appear alone.</p>

### TXDATA register

- Absolute Address: 0x25C
- Base Offset: 0x5C
- Size: 0x4

<p>Target TX FIFO Access Register (Target Mode only).</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |w, wuser| 0x0 |  — |

#### DATA field

<p>Writing to this register pushes data into the Target TX FIFO. The controller
reads data from this FIFO during a READ transaction.</p>

### HOST_TIMEOUT_CTRL register

- Absolute Address: 0x260
- Base Offset: 0x60
- Size: 0x4

<p>Controller Timeout Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|30:0|    VAL   |  rw  | 0x0 |  — |

#### VAL field

<p>Target/Monitor Mode control: controller clock generation timeout value
specified in system clock cycles.
 * Target Mode - If the controller stops generating the clock for more time
   than this setting, this target asserts the Controller Timeout Interrupt.
 * Monitor Mode - this field is required to be nonzero for the Bus Monitor to
   transition out of the initial Busy state. Set this field to <code>0x0</code> to disable
   this behavior.</p>

### TARGET_TIMEOUT_CTRL register

- Absolute Address: 0x264
- Base Offset: 0x64
- Size: 0x4

<p>Target Timeout Control Register (Target Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|30:0|    VAL   |  rw  | 0x0 |  — |
| 31 |    EN    |  rw  | 0x0 |  — |

#### VAL field

<p>When this target has stretched the clock for more time than this setting, this
target will NACK incoming data bytes or release the SDA line for outgoing data
bytes. The count is cumulative over an entire transaction. In other words, this
is SMBus's cumulative target clock extension time.</p>
<p>The behavior for the address byte is configurable via
<code>CTRL.NACK_ADDR_AFTER_TIMEOUT</code>.</p>

#### EN field

<p>Enable Target Timeout.</p>

### TARGET_NACK_COUNT register

- Absolute Address: 0x268
- Base Offset: 0x68
- Size: 0x4

<p>Target NACK Count Register (Target Mode only)</p>

|Bits|    Identifier   | Access |Reset|Name|
|----|-----------------|--------|-----|----|
| 7:0|TARGET_NACK_COUNT|rw, rclr| 0x0 |  — |

#### TARGET_NACK_COUNT field

<p>Indicates the number of transactions NACKed by this target since the last read
of this register, saturating at 255. This field can be used to track how many
transactions were missed when the Target RX FIFO is full.</p>

### TARGET_ACK_CTRL register

- Absolute Address: 0x26C
- Base Offset: 0x6C
- Size: 0x4

<p>Target ACK Control Register (Target Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 8:0|  NBYTES  |  rw  | 0x0 |  — |
| 31 |   NACK   |   w  | 0x0 |  — |

#### NBYTES field

<p>When <code>STATUS.ACK_CTRL_STRETCH = 1</code>, writing to this register specifies the
number of bytes this target should ACK. The count decrements per byte ACKed.
Effective only when <code>CTRL.ACK_CTRL_EN = 1</code>. See <code>CTRL.ACK_CTRL_EN</code> for details.</p>
<p>This control field is used to implement SMBus's mid-transfer (N)ACK responses.</p>

#### NACK field

<p>When <code>STATUS.ACK_CTRL_STRETCH = 1</code>, writing <code>1</code> to this field causes this
target to NACK all bytes of the transaction. Effective only when
<code>CTRL.ACK_CTRL_EN = 1</code>.</p>

### ACQ_FIFO_NEXT_DATA register

- Absolute Address: 0x270
- Base Offset: 0x70
- Size: 0x4

<p>Target RX FIFO Next Byte Register (Target Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>This field contains the next byte to be pushed into the Target RX FIFO,
allowing software to decide whether to accept or reject it. Valid only when
<code>STATUS.ACK_CTRL_STRETCH = 1</code>. See <code>CTRL.ACK_CTRL_EN</code> for details.</p>

### HOST_NACK_HANDLER_TIMEOUT register

- Absolute Address: 0x274
- Base Offset: 0x74
- Size: 0x4

<p>Controller NACK Timeout Register (Controller Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|30:0|    VAL   |  rw  | 0x0 |  — |
| 31 |    EN    |  rw  | 0x0 |  — |

#### VAL field

<p>Timeout value (specified in system clock cycles) for this controller Mode to
automatically STOP a transaction when <code>CONTROLLER_EVENTS.NACK</code> is set.</p>

#### EN field

<p>Enables Controller NACK Timeout.</p>

### CONTROLLER_EVENTS register

- Absolute Address: 0x278
- Base Offset: 0x78
- Size: 0x4

<p>Controller Events Register (Controller Mode only)</p>

|Bits|      Identifier      |  Access |Reset|Name|
|----|----------------------|---------|-----|----|
|  0 |         NACK         |rw, woclr| 0x0 |  — |
|  1 |UNHANDLED_NACK_TIMEOUT|rw, woclr| 0x0 |  — |
|  2 |      BUS_TIMEOUT     |rw, woclr| 0x0 |  — |
|  3 |   ARBITRATION_LOST   |rw, woclr| 0x0 |  — |

#### NACK field

<p>Indicates that this controller has halted due to an unexpected NACK sent by
the target. This behavior can be disabled by writing <code>1</code> to <code>FDATA.NAKOK</code>. This
bit triggers the <code>CONTROLLER_HALT</code> interrupt. Writing <code>1</code> clears this bit.</p>

#### UNHANDLED_NACK_TIMEOUT field

<p>Indicates that this controller has halted due to a Controller NACK Timeout. See
<code>HOST_NACK_HANDLER_TIMEOUT</code> for details. This bit triggers the
<code>CONTROLLER_HALT</code> interrupt. Writing <code>1</code> clears this bit.</p>

#### BUS_TIMEOUT field

<p>Indicates that this controller has halted due to a Bus Timeout. See
<code>TIMEOUT_CTRL</code> for details. This bit triggers the <code>CONTROLLER_HALT</code> interrupt.
Writing <code>1</code> clears this bit.</p>

#### ARBITRATION_LOST field

<p>Indicates that the controller has halted due to it losing an arbitration
against another controller. This bit triggers the <code>CONTROLLER_HALT</code> interrupt.
Writing <code>1</code> clears this bit.</p>

### TARGET_EVENTS register

- Absolute Address: 0x27C
- Base Offset: 0x7C
- Size: 0x4

<p>Target Events Register (Target Mode)</p>

|Bits|   Identifier   |  Access |Reset|Name|
|----|----------------|---------|-----|----|
|  0 |   TX_PENDING   |rw, woclr| 0x0 |  — |
|  1 |   BUS_TIMEOUT  |rw, woclr| 0x0 |  — |
|  2 |ARBITRATION_LOST|rw, woclr| 0x0 |  — |
|  3 |  START_DETECT  |rw, woclr| 0x0 |  — |
|  4 |   STOP_DETECT  |rw, woclr| 0x0 |  — |

#### TX_PENDING field

<p>Indicates that the target is stretching the clock due to receiving a READ
address byte and waiting for software to confirm the release of the Target
TX FIFO data. Valid only if <code>CTRL.TX_STRETCH_CTRL_EN = 1</code>. See
<code>CTRL.TX_STRETCH_CTRL_EN</code> for details. This bit triggers the <code>TX_STRETCH</code>
interrupt. Writing <code>1</code> clears this bit.</p>

#### BUS_TIMEOUT field

<p>Indicates that this target has halted due a Bus Timeout terminating a READ
transaction. See <code>TIMEOUT_CTRL</code> for details. This bit triggers the <code>TX_STRETCH</code>
interrupt. Writing <code>1</code> clears this bit.</p>

#### ARBITRATION_LOST field

<p>Indicates that a controller has lost arbitration, causing a READ
transaction to end. This bit triggers the <code>TX_STRETCH</code> interrupt. Writing <code>1</code>
clears this bit.</p>

#### START_DETECT field

<p>Start Detect Flag (Target Mode only). Set to 1 by hardware when a START
(or repeated START) is detected while <code>CTRL.ENABLETARGET = 1</code>. Cleared when
software writes 1.</p>

#### STOP_DETECT field

<p>Stop Detect Flag (Target Mode only). Set to 1 by hardware when a STOP is
detected while <code>CTRL.ENABLETARGET = 1</code>. Cleared when software writes 1.</p>

### SMBUS_STATUS register

- Absolute Address: 0x280
- Base Offset: 0x80
- Size: 0x4

<p>SMBus Status Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  SMBSUS  |   r  | 0x0 |  — |
|  4 | SMBALERT |   r  | 0x0 |  — |

#### SMBSUS field

<p>Target Mode status: indicates that the <code>smbsus_ni</code> input is asserted.</p>

#### SMBALERT field

<p>Controller Mode status: indicates that the <code>smbalert_ni</code> input is asserted.</p>

## i2c address map

- Absolute Address: 0x400
- Base Offset: 0x0
- Size: 0x84
- Array Dimensions: [3]
- Array Stride: 0x200
- Total Size: 0x600

|Offset|        Identifier       |Name|
|------|-------------------------|----|
| 0x00 |        INTR_STATE       |  — |
| 0x04 |       INTR_ENABLE       |  — |
| 0x08 |        INTR_TEST        |  — |
| 0x0C |        SMBUS_CTRL       |  — |
| 0x10 |           CTRL          |  — |
| 0x14 |          STATUS         |  — |
| 0x18 |          RDATA          |  — |
| 0x1C |          FDATA          |  — |
| 0x20 |        FIFO_CTRL        |  — |
| 0x24 |     HOST_FIFO_CONFIG    |  — |
| 0x28 |    TARGET_FIFO_CONFIG   |  — |
| 0x2C |     HOST_FIFO_STATUS    |  — |
| 0x30 |    TARGET_FIFO_STATUS   |  — |
| 0x34 |           OVRD          |  — |
| 0x38 |           VAL           |  — |
| 0x3C |         TIMING0         |  — |
| 0x40 |         TIMING1         |  — |
| 0x44 |         TIMING2         |  — |
| 0x48 |         TIMING3         |  — |
| 0x4C |         TIMING4         |  — |
| 0x50 |       TIMEOUT_CTRL      |  — |
| 0x54 |        TARGET_ID        |  — |
| 0x58 |         ACQDATA         |  — |
| 0x5C |          TXDATA         |  — |
| 0x60 |    HOST_TIMEOUT_CTRL    |  — |
| 0x64 |   TARGET_TIMEOUT_CTRL   |  — |
| 0x68 |    TARGET_NACK_COUNT    |  — |
| 0x6C |     TARGET_ACK_CTRL     |  — |
| 0x70 |    ACQ_FIFO_NEXT_DATA   |  — |
| 0x74 |HOST_NACK_HANDLER_TIMEOUT|  — |
| 0x78 |    CONTROLLER_EVENTS    |  — |
| 0x7C |      TARGET_EVENTS      |  — |
| 0x80 |       SMBUS_STATUS      |  — |

### INTR_STATE register

- Absolute Address: 0x400
- Base Offset: 0x0
- Size: 0x4

<p>Interrupt Status Register</p>

|Bits|       Identifier       |  Access |Reset|Name|
|----|------------------------|---------|-----|----|
|  0 |      FMT_THRESHOLD     |    r    | 0x0 |  — |
|  1 |      RX_THRESHOLD      |    r    | 0x0 |  — |
|  2 |      ACQ_THRESHOLD     |    r    | 0x0 |  — |
|  3 |       RX_OVERFLOW      |rw, woclr| 0x0 |  — |
|  4 |     CONTROLLER_HALT    |    r    | 0x0 |  — |
|  5 |    SCL_INTERFERENCE    |rw, woclr| 0x0 |  — |
|  6 |    SDA_INTERFERENCE    |rw, woclr| 0x0 |  — |
|  7 |     STRETCH_TIMEOUT    |rw, woclr| 0x0 |  — |
|  8 |      SDA_UNSTABLE      |rw, woclr| 0x0 |  — |
|  9 |      CMD_COMPLETE      |rw, woclr| 0x0 |  — |
| 10 |       TX_STRETCH       |    r    | 0x0 |  — |
| 11 |      TX_THRESHOLD      |    r    | 0x0 |  — |
| 12 |       ACQ_STRETCH      |    r    | 0x0 |  — |
| 13 |       UNEXP_STOP       |rw, woclr| 0x0 |  — |
| 14 |      HOST_TIMEOUT      |rw, woclr| 0x0 |  — |
| 15 |        SMBALERT        |rw, woclr| 0x0 |  — |
| 16 |CONTROLLER_TX_FIFO_ERROR|rw, woclr| 0x0 |  — |
| 17 |CONTROLLER_RX_FIFO_ERROR|rw, woclr| 0x0 |  — |
| 18 |  TARGET_TX_FIFO_ERROR  |rw, woclr| 0x0 |  — |
| 19 |  TARGET_RX_FIFO_ERROR  |rw, woclr| 0x0 |  — |

#### FMT_THRESHOLD field

<p>Controller Mode interrupt: remains asserted while the Controller TX FIFO level
is less than <code>HOST_FIFO_CONFIG.FMT_THRESH</code>.</p>

#### RX_THRESHOLD field

<p>Controller Mode interrupt: remains asserted while the Controller RX FIFO level
is greater than <code>HOST_FIFO_CONFIG.RX_THRESH</code>.</p>

#### ACQ_THRESHOLD field

<p>Target Mode interrupt: remains asserted while the Target RX FIFO level is
greater than <code>TARGET_FIFO_CONFIG.ACQ_THRESH</code>.</p>

#### RX_OVERFLOW field

<p>Controller Mode interrupt: asserted when the Controller RX FIFO overflows.
Write <code>1</code> to clear.</p>

#### CONTROLLER_HALT field

<p>Controller Mode interrupt: remains asserted while this controller halts. The
flags in the <code>CONTROLLER_EVENTS</code> register explain the reason(s) for the
halting. Clearing the <code>CONTROLLER_EVENTS</code> flags clears this interrupt.</p>

#### SCL_INTERFERENCE field

<p>Controller Mode interrupt: asserted when SCL is unexpectedly pulled LOW by
another controller. Write <code>1</code> to clear.</p>

#### SDA_INTERFERENCE field

<p>Controller Mode interrupt: asserted when SDA is unexpectedly pulled LOW by
another controller. Write <code>1</code> to clear.</p>

#### STRETCH_TIMEOUT field

<p>Controller Mode interrupt: asserted when the target stretches the clock longer
than <code>TIMEOUT_CTRL.VAL</code> (valid only when <code>TIMEOUT_CTRL.MODE = 0</code>). Write <code>1</code> to
clear.</p>

#### SDA_UNSTABLE field

<p>Controller Mode interrupt: asserted when the target fails to keep SDA stable
during a transmission. Write <code>1</code> to clear.</p>

#### CMD_COMPLETE field

<p>Controller/Target Mode interrupt: asserted when this/the controller finishes
generating a STOP or repeated START. Write <code>1</code> to clear.</p>

#### TX_STRETCH field

<p>Target Mode interrupt: remains asserted while this target is stretching the
clock or has halted. The flags in the <code>TARGET_EVENTS</code> register explain the
reason(s) for clock stretching/halting. Clearing the <code>TARGET_EVENTS</code> flags
clears this interrupt.</p>

#### TX_THRESHOLD field

<p>Target Mode interrupt: remains asserted while the Target TX FIFO level is less
than <code>TARGET_FIFO_CONFIG.TX_THRESH</code>.</p>

#### ACQ_STRETCH field

<p>Target Mode interrupt: remains asserted while the target is stretching the clock
because 1) the Target RX FIFO is full or 2) the <code>TARGET_ACK_CTRL.NBYTES</code> count
has reached <code>0</code> (only if <code>CTRL.ACK_CTRL_EN = 1</code>).</p>

#### UNEXP_STOP field

<p>Target Mode interrupt: asserted when the controller sends this target a STOP
before this target NACKs. Write <code>1</code> to clear.</p>

#### HOST_TIMEOUT field

<p>Target Mode interrupt: asserted when the controller stops generating the clock
longer than <code>HOST_TIMEOUT_CTRL.VAL</code>. Write <code>1</code> to clear.</p>

#### SMBALERT field

<p>Controller Mode interrupt: asserted when <code>smbalert_ni</code> is asserted. Write <code>1</code>
to clear.</p>

#### CONTROLLER_TX_FIFO_ERROR field

<p>Controller Mode interrupt: asserted when the Controller TX FIFO has a parity
error. Write <code>1</code> to clear.</p>

#### CONTROLLER_RX_FIFO_ERROR field

<p>Controller Mode interrupt: asserted when the Controller RX FIFO has a parity
error. Write <code>1</code> to clear.</p>

#### TARGET_TX_FIFO_ERROR field

<p>Target Mode interrupt: asserted when the Target TX FIFO has a parity error.
Write <code>1</code> to clear.</p>

#### TARGET_RX_FIFO_ERROR field

<p>Target Mode interrupt: asserted when the Target RX FIFO has a parity error.
Write <code>1</code> to clear.</p>

### INTR_ENABLE register

- Absolute Address: 0x404
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|       Identifier       |Access|Reset|Name|
|----|------------------------|------|-----|----|
|  0 |      FMT_THRESHOLD     |  rw  | 0x0 |  — |
|  1 |      RX_THRESHOLD      |  rw  | 0x0 |  — |
|  2 |      ACQ_THRESHOLD     |  rw  | 0x0 |  — |
|  3 |       RX_OVERFLOW      |  rw  | 0x0 |  — |
|  4 |     CONTROLLER_HALT    |  rw  | 0x0 |  — |
|  5 |    SCL_INTERFERENCE    |  rw  | 0x0 |  — |
|  6 |    SDA_INTERFERENCE    |  rw  | 0x0 |  — |
|  7 |     STRETCH_TIMEOUT    |  rw  | 0x0 |  — |
|  8 |      SDA_UNSTABLE      |  rw  | 0x0 |  — |
|  9 |      CMD_COMPLETE      |  rw  | 0x0 |  — |
| 10 |       TX_STRETCH       |  rw  | 0x0 |  — |
| 11 |      TX_THRESHOLD      |  rw  | 0x0 |  — |
| 12 |       ACQ_STRETCH      |  rw  | 0x0 |  — |
| 13 |       UNEXP_STOP       |  rw  | 0x0 |  — |
| 14 |      HOST_TIMEOUT      |  rw  | 0x0 |  — |
| 15 |        SMBALERT        |  rw  | 0x0 |  — |
| 16 |CONTROLLER_TX_FIFO_ERROR|  rw  | 0x0 |  — |
| 17 |CONTROLLER_RX_FIFO_ERROR|  rw  | 0x0 |  — |
| 18 |  TARGET_TX_FIFO_ERROR  |  rw  | 0x0 |  — |
| 19 |  TARGET_RX_FIFO_ERROR  |  rw  | 0x0 |  — |

#### FMT_THRESHOLD field

<p>Enables the <code>FMT_THRESHOLD</code> interrupt.</p>

#### RX_THRESHOLD field

<p>Enables the <code>RX_THRESHOLD</code> interrupt.</p>

#### ACQ_THRESHOLD field

<p>Enables the <code>ACQ_THRESHOLD</code> interrupt.</p>

#### RX_OVERFLOW field

<p>Enables the <code>RX_OVERFLOW</code> interrupt.</p>

#### CONTROLLER_HALT field

<p>Enables the <code>CONTROLLER_HALT</code> interrupt.</p>

#### SCL_INTERFERENCE field

<p>Enables the <code>SCL_INTERFERENCE</code> interrupt.</p>

#### SDA_INTERFERENCE field

<p>Enables the <code>SDA_INTERFERENCE</code> interrupt.</p>

#### STRETCH_TIMEOUT field

<p>Enables the <code>STRETCH_TIMEOUT</code> interrupt.</p>

#### SDA_UNSTABLE field

<p>Enables the <code>SDA_UNSTABLE</code> interrupt.</p>

#### CMD_COMPLETE field

<p>Enables the <code>CMD_COMPLETE</code> interrupt.</p>

#### TX_STRETCH field

<p>Enables the <code>TX_STRETCH</code> interrupt.</p>

#### TX_THRESHOLD field

<p>Enables the <code>TX_THRESHOLD</code> interrupt.</p>

#### ACQ_STRETCH field

<p>Enables the <code>ACQ_STRETCH</code> interrupt.</p>

#### UNEXP_STOP field

<p>Enables the <code>UNEXP_STOP</code> interrupt.</p>

#### HOST_TIMEOUT field

<p>Enables the <code>HOST_TIMEOUT</code> interrupt.</p>

#### SMBALERT field

<p>Enables the <code>SMBALERT</code> interrupt.</p>

#### CONTROLLER_TX_FIFO_ERROR field

<p>Enables the <code>CONTROLLER_TX_FIFO_ERROR</code> interrupt.</p>

#### CONTROLLER_RX_FIFO_ERROR field

<p>Enables the <code>CONTROLLER_RX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_TX_FIFO_ERROR field

<p>Enables the <code>TARGET_TX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_RX_FIFO_ERROR field

<p>Enables the <code>TARGET_RX_FIFO_ERROR</code> interrupt.</p>

### INTR_TEST register

- Absolute Address: 0x408
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|       Identifier       |Access|Reset|Name|
|----|------------------------|------|-----|----|
|  0 |      FMT_THRESHOLD     |  rw  | 0x0 |  — |
|  1 |      RX_THRESHOLD      |  rw  | 0x0 |  — |
|  2 |      ACQ_THRESHOLD     |  rw  | 0x0 |  — |
|  3 |       RX_OVERFLOW      |   w  | 0x0 |  — |
|  4 |     CONTROLLER_HALT    |  rw  | 0x0 |  — |
|  5 |    SCL_INTERFERENCE    |   w  | 0x0 |  — |
|  6 |    SDA_INTERFERENCE    |   w  | 0x0 |  — |
|  7 |     STRETCH_TIMEOUT    |   w  | 0x0 |  — |
|  8 |      SDA_UNSTABLE      |   w  | 0x0 |  — |
|  9 |      CMD_COMPLETE      |   w  | 0x0 |  — |
| 10 |       TX_STRETCH       |  rw  | 0x0 |  — |
| 11 |      TX_THRESHOLD      |  rw  | 0x0 |  — |
| 12 |       ACQ_STRETCH      |  rw  | 0x0 |  — |
| 13 |       UNEXP_STOP       |   w  | 0x0 |  — |
| 14 |      HOST_TIMEOUT      |   w  | 0x0 |  — |
| 15 |        SMBALERT        |   w  | 0x0 |  — |
| 16 |CONTROLLER_TX_FIFO_ERROR|   w  | 0x0 |  — |
| 17 |CONTROLLER_RX_FIFO_ERROR|   w  | 0x0 |  — |
| 18 |  TARGET_TX_FIFO_ERROR  |   w  | 0x0 |  — |
| 19 |  TARGET_RX_FIFO_ERROR  |   w  | 0x0 |  — |

#### FMT_THRESHOLD field

<p>Writing <code>1</code> forces the <code>FMT_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### RX_THRESHOLD field

<p>Writing <code>1</code> forces the <code>RX_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### ACQ_THRESHOLD field

<p>Writing <code>1</code> forces the <code>ACQ_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### RX_OVERFLOW field

<p>Writing <code>1</code> forces the <code>RX_OVERFLOW</code> interrupt.</p>

#### CONTROLLER_HALT field

<p>Writing <code>1</code> forces the <code>CONTROLLER_HALT</code> interrupt. Writing <code>0</code> releases it.</p>

#### SCL_INTERFERENCE field

<p>Writing <code>1</code> forces the <code>SCL_INTERFERENCE</code> interrupt.</p>

#### SDA_INTERFERENCE field

<p>Writing <code>1</code> forces the <code>SDA_INTERFERENCE</code> interrupt.</p>

#### STRETCH_TIMEOUT field

<p>Writing <code>1</code> forces the <code>STRETCH_TIMEOUT</code> interrupt.</p>

#### SDA_UNSTABLE field

<p>Writing <code>1</code> forces the <code>SDA_UNSTABLE</code> interrupt.</p>

#### CMD_COMPLETE field

<p>Writing <code>1</code> forces the <code>CMD_COMPLETE</code> interrupt.</p>

#### TX_STRETCH field

<p>Writing <code>1</code> forces the <code>TX_STRETCH</code> interrupt. Writing a <code>0</code> releases it.</p>

#### TX_THRESHOLD field

<p>Writing <code>1</code> forces the <code>TX_THRESHOLD</code> interrupt. Writing <code>0</code> releases it.</p>

#### ACQ_STRETCH field

<p>Writing <code>1</code> forces the <code>ACQ_STRETCH</code> interrupt. Writing <code>0</code> releases it.</p>

#### UNEXP_STOP field

<p>Writing <code>1</code> forces the <code>UNEXP_STOP</code> interrupt.</p>

#### HOST_TIMEOUT field

<p>Writing <code>1</code> forces the <code>HOST_TIMEOUT</code> interrupt.</p>

#### SMBALERT field

<p>Writing <code>1</code> forces the <code>SMBALERT</code> interrupt.</p>

#### CONTROLLER_TX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>CONTROLLER_TX_FIFO_ERROR</code> interrupt.</p>

#### CONTROLLER_RX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>CONTROLLER_RX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_TX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>TARGET_TX_FIFO_ERROR</code> interrupt.</p>

#### TARGET_RX_FIFO_ERROR field

<p>Writing <code>1</code> forces the <code>TARGET_RX_FIFO_ERROR</code> interrupt.</p>

### SMBUS_CTRL register

- Absolute Address: 0x40C
- Base Offset: 0xC
- Size: 0x4

<p>SMBus Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  SMBSUS  |  rw  | 0x0 |  — |
|  4 | SMBALERT |  rw  | 0x0 |  — |

#### SMBSUS field

<p>Controller Mode control: asserts the <code>smbsus_no</code> output.</p>

#### SMBALERT field

<p>Target Mode control: asserts the <code>smbalert_no</code> output. This bit clears itself
when the controller addresses this target.</p>

### CTRL register

- Absolute Address: 0x410
- Base Offset: 0x10
- Size: 0x4

<p>Control Register</p>

|Bits|         Identifier        |Access|Reset|Name|
|----|---------------------------|------|-----|----|
|  0 |         ENABLEHOST        |  rw  | 0x0 |  — |
|  1 |        ENABLETARGET       |  rw  | 0x0 |  — |
|  2 |           LLPBK           |  rw  | 0x0 |  — |
|  3 |  NACK_ADDR_AFTER_TIMEOUT  |  rw  | 0x0 |  — |
|  4 |        ACK_CTRL_EN        |  rw  | 0x0 |  — |
|  5 |MULTI_CONTROLLER_MONITOR_EN|  rw  | 0x0 |  — |
|  6 |     TX_STRETCH_CTRL_EN    |  rw  | 0x0 |  — |
|  7 |     ACQ_START_STOP_EN     |  rw  | 0x0 |  — |

#### ENABLEHOST field

<p>Global control: configures this device's operating mode.
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 0</code> — Controller Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 1</code> — Target Mode
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 1</code> — Hybrid Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 0</code> — Monitor Mode</p>

#### ENABLETARGET field

<p>Global control: configures this device's operating mode.
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 0</code> — Controller Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 1</code> — Target Mode
* <code>ENABLEHOST = 1</code> and <code>ENABLETARGET = 1</code> — Hybrid Mode
* <code>ENABLEHOST = 0</code> and <code>ENABLETARGET = 0</code> — Monitor Mode</p>

#### LLPBK field

<p>Global control: enables line loop-back. In Controller Mode, the internal logic
sees the <code>smbalert_ni</code> input as deasserted. In Target Mode, this target sends
all received SDA data back out, and the internal logic sees received data as
all 1's.</p>

#### NACK_ADDR_AFTER_TIMEOUT field

<p>Target Mode control: NACK address after timeout. If this bit is:
* <code>0</code> - This target ACKs the address byte even if a Stretch Timeout occurs
        (useful for SMBus).
* <code>1</code> - This target NACKs the address byte when a Stretch Timeout occurs.</p>

#### ACK_CTRL_EN field

<p>Target Mode control: enables the Software ACK Control Mechanism. If this bit is:
* <code>0</code> - This target ACKs a data byte whenever the ACQ FIFO has space.
* <code>1</code> - This target ACKs the first <code>TARGET_ACK_CTRL.NBYTES</code> bytes. If another
        byte arrives, this target stretches the clock and awaits software
        intervention (and asserts <code>STATUS.ACK_CTRL_STRETCH</code>). The software can
         1. accept the new byte(s) by reloading the <code>TARGET_ACK_CTRL.NBYTES</code>
            counter; or
         2. reject the new byte(s) by writing <code>1</code> to <code>TARGET_ACK_CTRL.NACK</code>
            (useful for SMBus).</p>

#### MULTI_CONTROLLER_MONITOR_EN field

<p>Global control: enables the Bus Monitor. Set this bit to <code>1</code>
only in a multi-controller environment.</p>
<p>If a <code>0</code>-&gt;<code>1</code> transition happens while <code>ENABLEHOST</code> and <code>ENABLETARGET</code> are both
<code>0</code>, the Bus Monitor will enable and begin in the 'Bus Busy' state. To
transition to a 'Bus Free' state, <code>HOST_TIMEOUT_CTRL</code> must be nonzero so the
Bus Monitor may count out idle cycles to confirm the freedom to transmit. In
addition, the Bus Monitor will track whether the bus is free based on the
enabled timeouts and detected STOP symbols. For Multi-Controller Mode, ensure
<code>MULTI_CONTROLLER_MONITOR_EN</code> becomes <code>1</code> no later than <code>ENABLEHOST</code> or
<code>ENABLETARGET</code>. This bit can be set at the same time as either or both of the
other two, though.</p>
<p>Note that if <code>MULTI_CONTROLLER_MONITOR_EN</code> is set after <code>ENABLEHOST</code> or
<code>ENABLETARGET</code>, the Bus Monitor will begin in the 'Bus Free' state instead.
This would violate the proper protocol for a controller to join a multi-controller
environment. However, if this controller is known to be the first to join, this
ordering will enable skipping the idle wait.</p>
<p>When <code>0</code>, the bus monitor will report that the bus is always free, so the
Controller FSM is never blocked from transmitting.</p>

#### TX_STRETCH_CTRL_EN field

<p>Target mode control: enables the Software TX Stretch Control Mechanism. If this
bit is:
 * <code>0</code> - Automatic TX Stretch: When this target receives a READ address
         byte, it only stretches the clock if the TX FIFO is empty; otherwise,
         it pops the FIFO and transmits the data byte. The target never sets
         the <code>TARGET_EVENTS</code> register flags in this mode.
 * <code>1</code> - Software TX Stretch Mode: When this target receives a READ address,
         it always stretches the clock and sets the <code>TARGET_EVENTS.TX_PENDING</code>
         flag. The software can:
          1. confirm the release and transmission of the TX FIFO data by
             writing a 1 to clear the <code>TARGET_EVENTS.TX_PENDING</code> flag; or
          2. reset the TX FIFO by writing 1 to <code>FIFO_CTRL.TXRST</code> and load in
             new data via the <code>TXDATA</code> register--useful whenthe READ address
             is targeting a different function of the target.
         In this mode, the target always sets the <code>TARGET_EVENTS</code> register
         flags.</p>

#### ACQ_START_STOP_EN field

<p>ACQ FIFO Start/Stop Enable (Target Mode only):
* <code>0</code> - Start/Stop symbols are NOT written into the ACQ FIFO. The firmware
        should rely on <code>TARGET_EVENTS.START_DETECT</code> and <code>TARGET_EVENTS.STOP_DETECT</code>
        flags to detect Start/Stop events.
* <code>1</code> - Start/Stop symbols ARE written into the ACQ FIFO (legacy behavior).
        When a START (or repeated START) is detected, an <code>AcqStart</code> or <code>AcqRestart</code>
        entry is written. When a STOP is detected, an <code>AcqStop</code> or <code>AcqNackStop</code>
        entry is written.</p>

### STATUS register

- Absolute Address: 0x414
- Base Offset: 0x14
- Size: 0x4

<p>Status Register</p>

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|  0 |     FMTFULL    |   r  | 0x0 |  — |
|  1 |     RXFULL     |   r  | 0x0 |  — |
|  2 |    FMTEMPTY    |   r  | 0x1 |  — |
|  3 |    HOSTIDLE    |   r  | 0x1 |  — |
|  4 |   TARGETIDLE   |   r  | 0x1 |  — |
|  5 |     RXEMPTY    |   r  | 0x1 |  — |
|  6 |     TXFULL     |   r  | 0x0 |  — |
|  7 |     ACQFULL    |   r  | 0x0 |  — |
|  8 |     TXEMPTY    |   r  | 0x1 |  — |
|  9 |    ACQEMPTY    |   r  | 0x1 |  — |
| 10 |ACK_CTRL_STRETCH|   r  | 0x0 |  — |

#### FMTFULL field

<p>Controller Mode status: Controller TX FIFO Full.</p>

#### RXFULL field

<p>Controller Mode status: Controller RX FIFO Full.</p>

#### FMTEMPTY field

<p>Controller Mode status: Controller TX FIFO Empty.</p>

#### HOSTIDLE field

<p>Controller Mode status: Controller FSM idle.</p>

#### TARGETIDLE field

<p>Target Mode status: Target FSM idle.</p>

#### RXEMPTY field

<p>Controller Mode status: Controller RX FIFO empty.</p>

#### TXFULL field

<p>Target Mode status: Target TX FIFO full.</p>

#### ACQFULL field

<p>Target Mode status: Target RX FIFO full.</p>

#### TXEMPTY field

<p>Target Mode status: Target TX FIFO empty.</p>

#### ACQEMPTY field

<p>Target Mode status: Target RX FIFO empty.</p>

#### ACK_CTRL_STRETCH field

<p>Target Mode status: indicates that this target is stretching the clock due to
the Software ACK Control Mechanism. See <code>CTRL.ACK_CTRL_EN</code> for details.</p>

### RDATA register

- Absolute Address: 0x418
- Base Offset: 0x18
- Size: 0x4

<p>Controller RX FIFO Access Register (Controller Mode only)</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |r, ruser| 0x0 |  — |

#### DATA field

<p>Reading this register pops the Controller RX FIFO.</p>

### FDATA register

- Absolute Address: 0x41C
- Base Offset: 0x1C
- Size: 0x4

<p>Controller TX FIFO Access Register (Controller Mode only)</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   FBYTE  |w, wuser| 0x0 |  — |
|  8 |   START  |    w   | 0x0 |  — |
|  9 |   STOP   |    w   | 0x0 |  — |
| 10 |   READB  |    w   | 0x0 |  — |
| 11 |   RCONT  |    w   | 0x0 |  — |
| 12 |   NAKOK  |    w   | 0x0 |  — |

#### FBYTE field

<p>Writing to this register pushes an entry into the Controller TX FIFO. The
meaning of this field depends on the value of the <code>READB</code> field:
 * <code>READB = 0</code> - This field is the WRITE data byte.
 * <code>READB = 1</code> - This field specifies the number of bytes to read from the
                 target. Setting this field to 0 reads 256 bytes.</p>

#### START field

<p>Generate a START condition on the bus before sending the byte.</p>

#### STOP field

<p>Generate a STOP condition on the bus after sending the byte.</p>

#### READB field

<p>Read/write:
* <code>0</code> - Issue WRITE transaction
* <code>1</code> - Issue READ transaction</p>

#### RCONT field

<p>Read continue/stop:
* <code>0</code> — Read Stop: The controller NACKs the last data byte. Use this if this
        is the last READ in a sequence.
* <code>1</code> — Read Continue: The controller ACKs the last data byte. Use this if
        this is an intermediate READ in a sequence.</p>

#### NAKOK field

<p>NACK OK. When set, this controller will not care if this byte is NACKed. It
will not halt, set the <code>CONTROLLER_EVENTS.NACK</code> flag, or assert the
<code>CONTROLLER_HALT</code> Interrupt. This behavior is useful for protocols like Serial
Camera Control Bus (SCCB).</p>

### FIFO_CTRL register

- Absolute Address: 0x420
- Base Offset: 0x20
- Size: 0x4

<p>FIFO Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   RXRST  |   w  | 0x0 |  — |
|  1 |  FMTRST  |   w  | 0x0 |  — |
|  7 |  ACQRST  |   w  | 0x0 |  — |
|  8 |   TXRST  |   w  | 0x0 |  — |

#### RXRST field

<p>Controller Mode control: writing <code>1</code> resets the Controller RX FIFO.</p>

#### FMTRST field

<p>Controller Mode control: writing <code>1</code> resets the Controller TX FIFO.</p>

#### ACQRST field

<p>Target Mode control: writing <code>1</code> resets the Target RX FIFO.</p>

#### TXRST field

<p>Target Mode control: writing <code>1</code> resets the Target TX FIFO.</p>

### HOST_FIFO_CONFIG register

- Absolute Address: 0x424
- Base Offset: 0x24
- Size: 0x4

<p>Controller FIFO Configuration Register (Controller Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0| RX_THRESH|  rw  | 0x0 |  — |
|27:16|FMT_THRESH|  rw  | 0x0 |  — |

#### RX_THRESH field

<p>The <code>RX_THRESH</code> interrupt remains asserted while the Controller RX FIFO level
is greater than this setting.</p>

#### FMT_THRESH field

<p>The <code>FMT_THRESH</code> interrupt remains asserted while the Controller TX FIFO level
is less than this setting.</p>

### TARGET_FIFO_CONFIG register

- Absolute Address: 0x428
- Base Offset: 0x28
- Size: 0x4

<p>Target FIFOs Configuration Register (Target Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0| TX_THRESH|  rw  | 0x0 |  — |
|27:16|ACQ_THRESH|  rw  | 0x0 |  — |

#### TX_THRESH field

<p>The <code>TX_THRESH</code> interrupt remains asserted while the Target TX FIFO level is
less than this setting.</p>

#### ACQ_THRESH field

<p>The <code>ACQ_THRESH</code> interrupt remains asserted while the Target RX FIFO level is
greater than this setting.</p>

### HOST_FIFO_STATUS register

- Absolute Address: 0x42C
- Base Offset: 0x2C
- Size: 0x4

<p>Controller FIFOs Status Register (Controller Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0|  FMTLVL  |   r  |  —  |  — |
|27:16|   RXLVL  |   r  |  —  |  — |

#### FMTLVL field

<p>Controller TX FIFO fill level.</p>

#### RXLVL field

<p>Controller RX FIFO fill level.</p>

### TARGET_FIFO_STATUS register

- Absolute Address: 0x430
- Base Offset: 0x30
- Size: 0x4

<p>Target FIFOs Status Register (Target Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 11:0|   TXLVL  |   r  | 0x0 |  — |
|27:16|  ACQLVL  |   r  | 0x0 |  — |

#### TXLVL field

<p>Target TX FIFO fill level.</p>

#### ACQLVL field

<p>Target RX FIFO fill level.</p>

### OVRD register

- Absolute Address: 0x434
- Base Offset: 0x34
- Size: 0x4

<p>Override Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 | TXOVRDEN |  rw  | 0x0 |  — |
|  1 |  SCLVAL  |  rw  | 0x0 |  — |
|  2 |  SDAVAL  |  rw  | 0x0 |  — |

#### TXOVRDEN field

<p>Global control: enables control of the SDA and SCL lines through the <code>SDA_VAL</code>
and <code>SCL_VAL</code> fields, respectively.</p>

#### SCLVAL field

<p>Global control: SCL override value:
* <code>0</code> - Pull the SCL line low
* <code>1</code> - Release the SCL line</p>

#### SDAVAL field

<p>Global control: SDA override value:
* <code>0</code> - Pull the SDA line low
* <code>1</code> - Release the SDA line</p>

### VAL register

- Absolute Address: 0x438
- Base Offset: 0x38
- Size: 0x4

<p>Bus Oversampled Values Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 15:0|  SCL_RX  |   r  | 0x0 |  — |
|31:16|  SDA_RX  |   r  | 0x0 |  — |

#### SCL_RX field

<p>Global status: contains the last 16 SCL over-sampled values. LSB is most
recent.</p>

#### SDA_RX field

<p>Global status: contains the last 16 SDA over-sampled values. LSB is most
recent.</p>

### TIMING0 register

- Absolute Address: 0x43C
- Base Offset: 0x3C
- Size: 0x4

<p>SCL LOW and HIGH Periods Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 12:0|   THIGH  |  rw  | 0x0 |  — |
|28:16|   TLOW   |  rw  | 0x0 |  — |

#### THIGH field

<p>Global control: specifies the HIGH period of SCL (<code>t_HIGH</code>) in system clock
cycles. Must be <code>≥ 2</code>. See Table 11 in the I²C Specification for details. This
field is sized to meet the I2C Standard-mode (100 kHz)'s minimum
<code>t_HIGH = 4.0 μs</code> requirement, assuming a 1 GHz system clock.</p>

#### TLOW field

<p>Global control: specifies the LOW period of SCL (<code>t_LOW</code>) in system clock
cycles. Must be <code>≥ 2</code>. See Table 11 in the I2C Specification for more details.
This field is sized to meet the I2C Standard-mode (100 kHz) minimum
<code>t_LOW = 4.7 μs</code> requirement, assuming a 1 GHz system clock.</p>

### TIMING1 register

- Absolute Address: 0x440
- Base Offset: 0x40
- Size: 0x4

<p>Bus Rise and Fall Times Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 9:0 |    T_R   |  rw  | 0x0 |  — |
|24:16|    T_F   |  rw  | 0x0 |  — |

#### T_R field

<p>Global control: specifies the rise time of SDA and SCL (<code>t_r</code>) in system clock
cycles. The rise time is measured from 30% to 70% of the signal swing. See
Table 11 in the I2C Specification for more details. This field is sized to meet
I2C Standard-mode (100 kHz)'s maximum <code>t_r = 1000 ns</code> requirement, assuming a 1
GHz system clock.</p>

#### T_F field

<p>Global control: specifies the fall time of SDA and SCL (<code>t_f</code>) in system clock
cycles. The fall time is measured from 70% to 30% of the signal swing. See
Table 11 in the I2C Specification for more details. This field is sized to meet
I2C Standard-mode (100 kHz)'s maximum <code>t_f = 300 ns</code> requirement, assuming a 1
GHz system clock.</p>

### TIMING2 register

- Absolute Address: 0x444
- Base Offset: 0x44
- Size: 0x4

<p>START Condition Setup and Hold Times Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 12:0|  TSU_STA |  rw  | 0x0 |  — |
|28:16|  THD_STA |  rw  | 0x0 |  — |

#### TSU_STA field

<p>Global control: specifies the setup time for a repeated START condition
(<code>t_SU;STA</code>) in system clock cycles. See Table 11 in the I2C Specification for
details. This field is sized to meet I2C Standard-mode (100 kHz)'s minimum
<code>t_SU;STA = 4.7 μs</code> requirement, assuming a 1 GHz system clock.</p>

#### THD_STA field

<p>Global control: specifies the setup time for a (repeated) START condition
(<code>t_HD;STA</code>) in system clock cycles. See Table 11 in the I2C Specification for
details. This field is sized to meet I2C Standard-mode (100 kHz)'s minimum
<code>t_HD;STA = 4.0 μs</code> requirement, assuming a 1 GHz system clock.</p>

### TIMING3 register

- Absolute Address: 0x448
- Base Offset: 0x48
- Size: 0x4

<p>Data Setup and Hold Times Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 8:0 |  TSU_DAT |  rw  | 0x0 |  — |
|28:16|  THD_DAT |  rw  | 0x0 |  — |

#### TSU_DAT field

<p>Global control: specifies the data setup time (<code>t_SU;DAT</code>) in system clock
cycles. See Table 11 in the I2C Specification for details. This field is sized
to meet the I2C Standard-mode (100 kHz)'s <code>t_SU;DAT = 250 ns</code> minimum
requirement, assuming a 1 GHz system clock.</p>

#### THD_DAT field

<p>Global control: specifies the data and (N)ACK bits hold time (<code>t_HD;DAT</code>) in
system clock cycles. See Table 11 in the I2C Specification for details. This
field is sized to meet the I2C Standard-mode (100 kHz)'s <code>t_HD;DAT = 5.0 μs</code>
minimum requirement, assuming a 1 GHz system clock.</p>

### TIMING4 register

- Absolute Address: 0x44C
- Base Offset: 0x4C
- Size: 0x4

<p>STOP Condition Setup Time and Bus Free Time Register</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 12:0|  TSU_STO |  rw  | 0x0 |  — |
|28:16|   T_BUF  |  rw  | 0x0 |  — |

#### TSU_STO field

<p>Global control: specifies the setup time for a STOP condition (<code>t_SU;STO</code>) in
system clock cycles. See Table 11 in the I²C Specification for details. This
field is sized to meet I2C Standard-mode (100 kHz)'s <code>t_SU;STO = 4.0 μs</code>
minimum requirement, assuming a 1 GHz system clock.</p>

#### T_BUF field

<p>Global control: specifies the time between a STOP and START condition (<code>t_BUF</code>)
in system clock cycles. See Table 11 in the I²C Specification for details. This
field is sized to meet I2C Standard-mode (100kHz)'s <code>t_BUF = 4.7 μs</code> minimum
requirement, assuming a 1 GHz system clock.</p>

### TIMEOUT_CTRL register

- Absolute Address: 0x450
- Base Offset: 0x50
- Size: 0x4

<p>Timeout Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|29:0|    VAL   |  rw  | 0x0 |  — |
| 30 |   MODE   |  rw  | 0x0 |  — |
| 31 |    EN    |  rw  | 0x0 |  — |

#### VAL field

<p>Global control: Specifies the timeout value in system clock cycles. The meaning
of this field depends on <code>MODE</code>.</p>

#### MODE field

<p>Global control: timeout mode.
* <code>0</code> - Stretch Timeout (Controller Mode only). If the target stretches the
        clock for more time than <code>TIMEOUT_CTRL.VAL</code>, the <code>STRETCH_TIMEOUT</code>
        interrupt will be asserted.
* <code>1</code> - Bus Timeout. If SCL is LOW for more time than <code>TIMEOUT_CTRL.VAL</code>:
         * In Controller Mode, the <code>CONTROLLER_EVENTS.BUS_TIMEOUT</code> flag will
           be asserted, triggering the <code>CONTROLLER_HALT</code> interrupt.
         * In Target Mode, the <code>TARGET_EVENTS.BUS_TIMEOUT</code> flag will be set,
           triggering the <code>TX_STRETCH</code> interrupt.</p>

#### EN field

<p>Timeout Enable.</p>

### TARGET_ID register

- Absolute Address: 0x454
- Base Offset: 0x54
- Size: 0x4

<p>Target ID Register (Target Mode only)</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 6:0 | ADDRESS0 |  rw  | 0x0 |  — |
| 13:7|   MASK0  |  rw  | 0x0 |  — |
|20:14| ADDRESS1 |  rw  | 0x0 |  — |
|27:21|   MASK1  |  rw  | 0x0 |  — |

#### ADDRESS0 field

<p>Target Address 0. This target responds if the 7-bit address matches
<code>ADDRESS0 &amp; MASK0</code>. <code>MASK0 = 0x0</code> disables this address.</p>

#### MASK0 field

<p>ADDRESS0 mask.</p>

#### ADDRESS1 field

<p>Target Address 1. This target responds if the 7-bit address matches
<code>ADDRESS1 &amp; MASK1</code>. <code>MASK1 = 0x0</code> disables this address.</p>

#### MASK1 field

<p>ADDRESS1 mask.</p>

### ACQDATA register

- Absolute Address: 0x458
- Base Offset: 0x58
- Size: 0x4

<p>Target RX FIFO Access Register (Target Mode only)</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   ABYTE  |r, ruser| 0x0 |  — |
|10:8|  SIGNAL  |    r   | 0x0 |  — |

#### ABYTE field

<p>Reading this register pops the ACQ FIFO. The meaning of this field depends on
<code>SIGNAL</code>:
 * <code>SIGNAL = 0x0</code>, <code>0x1</code>, <code>0x3</code>, <code>0x4</code>, or <code>0x5</code> - This field contains an
   address or data byte sent by the controller.
 * <code>SIGNAL = 0x2</code>, <code>0x6</code> - This field is meaningless.</p>

#### SIGNAL field

<p>This field indicates if this FIFO entry represents/is associated with control
signal(s):
 * <code>0x0</code> - The entry is an ordinary data byte that has been ACKed.
 * <code>0x1</code> - The entry is an address byte preceded by a START.
 * <code>0x2</code> - The entry is a STOP condition following ACKed data bytes.
 * <code>0x3</code> - The entry is an address byte preceded by a repeated START.
 * <code>0x4</code> - The entry is a NACKed data byte.
 * <code>0x5</code> - The entry is an address byte preceded by a (repeated) START.
           However, the data bytes that followed this address byte were
           NACKed.
 * <code>0x6</code> - Error. A transaction preceding ended abnormally, for example, due to
           an unexpected STOP condition, a Bus or Stretch Timeout, a software
           NACK, or a lost arbitration.</p>
<p>If the FIFO does not have enough space to record a complete transaction, an
Error (<code>0x6</code>) entry may appear alone.</p>

### TXDATA register

- Absolute Address: 0x45C
- Base Offset: 0x5C
- Size: 0x4

<p>Target TX FIFO Access Register (Target Mode only).</p>

|Bits|Identifier| Access |Reset|Name|
|----|----------|--------|-----|----|
| 7:0|   DATA   |w, wuser| 0x0 |  — |

#### DATA field

<p>Writing to this register pushes data into the Target TX FIFO. The controller
reads data from this FIFO during a READ transaction.</p>

### HOST_TIMEOUT_CTRL register

- Absolute Address: 0x460
- Base Offset: 0x60
- Size: 0x4

<p>Controller Timeout Control Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|30:0|    VAL   |  rw  | 0x0 |  — |

#### VAL field

<p>Target/Monitor Mode control: controller clock generation timeout value
specified in system clock cycles.
 * Target Mode - If the controller stops generating the clock for more time
   than this setting, this target asserts the Controller Timeout Interrupt.
 * Monitor Mode - this field is required to be nonzero for the Bus Monitor to
   transition out of the initial Busy state. Set this field to <code>0x0</code> to disable
   this behavior.</p>

### TARGET_TIMEOUT_CTRL register

- Absolute Address: 0x464
- Base Offset: 0x64
- Size: 0x4

<p>Target Timeout Control Register (Target Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|30:0|    VAL   |  rw  | 0x0 |  — |
| 31 |    EN    |  rw  | 0x0 |  — |

#### VAL field

<p>When this target has stretched the clock for more time than this setting, this
target will NACK incoming data bytes or release the SDA line for outgoing data
bytes. The count is cumulative over an entire transaction. In other words, this
is SMBus's cumulative target clock extension time.</p>
<p>The behavior for the address byte is configurable via
<code>CTRL.NACK_ADDR_AFTER_TIMEOUT</code>.</p>

#### EN field

<p>Enable Target Timeout.</p>

### TARGET_NACK_COUNT register

- Absolute Address: 0x468
- Base Offset: 0x68
- Size: 0x4

<p>Target NACK Count Register (Target Mode only)</p>

|Bits|    Identifier   | Access |Reset|Name|
|----|-----------------|--------|-----|----|
| 7:0|TARGET_NACK_COUNT|rw, rclr| 0x0 |  — |

#### TARGET_NACK_COUNT field

<p>Indicates the number of transactions NACKed by this target since the last read
of this register, saturating at 255. This field can be used to track how many
transactions were missed when the Target RX FIFO is full.</p>

### TARGET_ACK_CTRL register

- Absolute Address: 0x46C
- Base Offset: 0x6C
- Size: 0x4

<p>Target ACK Control Register (Target Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 8:0|  NBYTES  |  rw  | 0x0 |  — |
| 31 |   NACK   |   w  | 0x0 |  — |

#### NBYTES field

<p>When <code>STATUS.ACK_CTRL_STRETCH = 1</code>, writing to this register specifies the
number of bytes this target should ACK. The count decrements per byte ACKed.
Effective only when <code>CTRL.ACK_CTRL_EN = 1</code>. See <code>CTRL.ACK_CTRL_EN</code> for details.</p>
<p>This control field is used to implement SMBus's mid-transfer (N)ACK responses.</p>

#### NACK field

<p>When <code>STATUS.ACK_CTRL_STRETCH = 1</code>, writing <code>1</code> to this field causes this
target to NACK all bytes of the transaction. Effective only when
<code>CTRL.ACK_CTRL_EN = 1</code>.</p>

### ACQ_FIFO_NEXT_DATA register

- Absolute Address: 0x470
- Base Offset: 0x70
- Size: 0x4

<p>Target RX FIFO Next Byte Register (Target Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>This field contains the next byte to be pushed into the Target RX FIFO,
allowing software to decide whether to accept or reject it. Valid only when
<code>STATUS.ACK_CTRL_STRETCH = 1</code>. See <code>CTRL.ACK_CTRL_EN</code> for details.</p>

### HOST_NACK_HANDLER_TIMEOUT register

- Absolute Address: 0x474
- Base Offset: 0x74
- Size: 0x4

<p>Controller NACK Timeout Register (Controller Mode only)</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|30:0|    VAL   |  rw  | 0x0 |  — |
| 31 |    EN    |  rw  | 0x0 |  — |

#### VAL field

<p>Timeout value (specified in system clock cycles) for this controller Mode to
automatically STOP a transaction when <code>CONTROLLER_EVENTS.NACK</code> is set.</p>

#### EN field

<p>Enables Controller NACK Timeout.</p>

### CONTROLLER_EVENTS register

- Absolute Address: 0x478
- Base Offset: 0x78
- Size: 0x4

<p>Controller Events Register (Controller Mode only)</p>

|Bits|      Identifier      |  Access |Reset|Name|
|----|----------------------|---------|-----|----|
|  0 |         NACK         |rw, woclr| 0x0 |  — |
|  1 |UNHANDLED_NACK_TIMEOUT|rw, woclr| 0x0 |  — |
|  2 |      BUS_TIMEOUT     |rw, woclr| 0x0 |  — |
|  3 |   ARBITRATION_LOST   |rw, woclr| 0x0 |  — |

#### NACK field

<p>Indicates that this controller has halted due to an unexpected NACK sent by
the target. This behavior can be disabled by writing <code>1</code> to <code>FDATA.NAKOK</code>. This
bit triggers the <code>CONTROLLER_HALT</code> interrupt. Writing <code>1</code> clears this bit.</p>

#### UNHANDLED_NACK_TIMEOUT field

<p>Indicates that this controller has halted due to a Controller NACK Timeout. See
<code>HOST_NACK_HANDLER_TIMEOUT</code> for details. This bit triggers the
<code>CONTROLLER_HALT</code> interrupt. Writing <code>1</code> clears this bit.</p>

#### BUS_TIMEOUT field

<p>Indicates that this controller has halted due to a Bus Timeout. See
<code>TIMEOUT_CTRL</code> for details. This bit triggers the <code>CONTROLLER_HALT</code> interrupt.
Writing <code>1</code> clears this bit.</p>

#### ARBITRATION_LOST field

<p>Indicates that the controller has halted due to it losing an arbitration
against another controller. This bit triggers the <code>CONTROLLER_HALT</code> interrupt.
Writing <code>1</code> clears this bit.</p>

### TARGET_EVENTS register

- Absolute Address: 0x47C
- Base Offset: 0x7C
- Size: 0x4

<p>Target Events Register (Target Mode)</p>

|Bits|   Identifier   |  Access |Reset|Name|
|----|----------------|---------|-----|----|
|  0 |   TX_PENDING   |rw, woclr| 0x0 |  — |
|  1 |   BUS_TIMEOUT  |rw, woclr| 0x0 |  — |
|  2 |ARBITRATION_LOST|rw, woclr| 0x0 |  — |
|  3 |  START_DETECT  |rw, woclr| 0x0 |  — |
|  4 |   STOP_DETECT  |rw, woclr| 0x0 |  — |

#### TX_PENDING field

<p>Indicates that the target is stretching the clock due to receiving a READ
address byte and waiting for software to confirm the release of the Target
TX FIFO data. Valid only if <code>CTRL.TX_STRETCH_CTRL_EN = 1</code>. See
<code>CTRL.TX_STRETCH_CTRL_EN</code> for details. This bit triggers the <code>TX_STRETCH</code>
interrupt. Writing <code>1</code> clears this bit.</p>

#### BUS_TIMEOUT field

<p>Indicates that this target has halted due a Bus Timeout terminating a READ
transaction. See <code>TIMEOUT_CTRL</code> for details. This bit triggers the <code>TX_STRETCH</code>
interrupt. Writing <code>1</code> clears this bit.</p>

#### ARBITRATION_LOST field

<p>Indicates that a controller has lost arbitration, causing a READ
transaction to end. This bit triggers the <code>TX_STRETCH</code> interrupt. Writing <code>1</code>
clears this bit.</p>

#### START_DETECT field

<p>Start Detect Flag (Target Mode only). Set to 1 by hardware when a START
(or repeated START) is detected while <code>CTRL.ENABLETARGET = 1</code>. Cleared when
software writes 1.</p>

#### STOP_DETECT field

<p>Stop Detect Flag (Target Mode only). Set to 1 by hardware when a STOP is
detected while <code>CTRL.ENABLETARGET = 1</code>. Cleared when software writes 1.</p>

### SMBUS_STATUS register

- Absolute Address: 0x480
- Base Offset: 0x80
- Size: 0x4

<p>SMBus Status Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  SMBSUS  |   r  | 0x0 |  — |
|  4 | SMBALERT |   r  | 0x0 |  — |

#### SMBSUS field

<p>Target Mode status: indicates that the <code>smbsus_ni</code> input is asserted.</p>

#### SMBALERT field

<p>Controller Mode status: indicates that the <code>smbalert_ni</code> input is asserted.</p>

## i2c_ctrl address map

- Absolute Address: 0xE00
- Base Offset: 0xE00
- Size: 0xC

|Offset| Identifier|Name|
|------|-----------|----|
|  0x0 |I2C_CTRL[0]|  — |
|  0x4 |I2C_CTRL[1]|  — |
|  0x8 |I2C_CTRL[2]|  — |

### I2C_CTRL register

- Absolute Address: 0xE00
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [3]
- Array Stride: 0x4
- Total Size: 0xC

<p>Control Register</p>

|Bits|      Identifier      |Access|Reset|Name|
|----|----------------------|------|-----|----|
|  0 |        I2C_EN        |  rw  | 0x0 |  — |
|  4 |I2C_CONTROLLER_MODE_EN|  rw  | 0x0 |  — |
|  8 |       SMBUS_EN       |  rw  | 0x0 |  — |

#### I2C_EN field

<p>I2C Enable.</p>

#### I2C_CONTROLLER_MODE_EN field

<p>I2C Controller Mode Enable.</p>

#### SMBUS_EN field

<p>SMBus Enable. Gates the SMBus Alert signal.</p>

### I2C_CTRL register

- Absolute Address: 0xE04
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [3]
- Array Stride: 0x4
- Total Size: 0xC

<p>Control Register</p>

|Bits|      Identifier      |Access|Reset|Name|
|----|----------------------|------|-----|----|
|  0 |        I2C_EN        |  rw  | 0x0 |  — |
|  4 |I2C_CONTROLLER_MODE_EN|  rw  | 0x0 |  — |
|  8 |       SMBUS_EN       |  rw  | 0x0 |  — |

#### I2C_EN field

<p>I2C Enable.</p>

#### I2C_CONTROLLER_MODE_EN field

<p>I2C Controller Mode Enable.</p>

#### SMBUS_EN field

<p>SMBus Enable. Gates the SMBus Alert signal.</p>

### I2C_CTRL register

- Absolute Address: 0xE08
- Base Offset: 0x0
- Size: 0x4
- Array Dimensions: [3]
- Array Stride: 0x4
- Total Size: 0xC

<p>Control Register</p>

|Bits|      Identifier      |Access|Reset|Name|
|----|----------------------|------|-----|----|
|  0 |        I2C_EN        |  rw  | 0x0 |  — |
|  4 |I2C_CONTROLLER_MODE_EN|  rw  | 0x0 |  — |
|  8 |       SMBUS_EN       |  rw  | 0x0 |  — |

#### I2C_EN field

<p>I2C Enable.</p>

#### I2C_CONTROLLER_MODE_EN field

<p>I2C Controller Mode Enable.</p>

#### SMBUS_EN field

<p>SMBus Enable. Gates the SMBus Alert signal.</p>
