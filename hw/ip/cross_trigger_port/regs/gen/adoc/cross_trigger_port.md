<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: cross_trigger_port
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/cross_trigger_port/regs/cross_trigger_port.rdl
-->

## cross_trigger_port address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0xC

<p>Configuration and status registers for the cross trigger port</p>

|Offset| Identifier |Name|
|------|------------|----|
|  0x0 |   CONFIG   |  — |
|  0x4 |   STATUS   |  — |
|  0x8 |STRETCH_MULT|  — |

### CONFIG register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>Cross Trigger Port Configuration</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   MODE   |  rw  | 0x0 |  — |
|  1 |  INVERT  |  rw  | 0x0 |  — |
|  2 |   RESET  |  rw  | 0x0 |  — |

#### MODE field

<p>Selects the operating mode of the CTP. 0 - Wire-OR, 1 - Point-to-Point</p>

#### INVERT field

<p>Inverts the sense of the incoming and outgoing GPIO signals. 0 - No inversion. Wire-OR mode uses active-low signaling with active or passive pull-ups. Point-to-point mode uses active-high signaling. 1 - All inputs and outputs of I/Os are inverted. Wire-OR mode uses active-high signaling with active or passive pull-downs. Point-to-point mode uses active-low signaling.</p>

#### RESET field

<p>Forcefully clears the request output signal of the point-to-point handshake logic. Primarily for debug and recovery of handshake deadlock.</p>

### STATUS register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>Cross Trigger Port Status</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   BUSY   |   r  | 0x0 |  — |
|  4 |  REQ_OUT |   r  | 0x0 |  — |
|  5 |  ACK_IN  |   r  | 0x0 |  — |
|  6 |  REQ_IN  |   r  | 0x0 |  — |
|  7 |  ACK_OUT |   r  | 0x0 |  — |

#### BUSY field

<p>Indicates whether a pulse assertion or handshake is currently in progress. 0 - Pulse or handshake is not in progress, 1 - Pulse or handshake is currently in progress</p>

#### REQ_OUT field

<p>Readout of the current CT_Req_out signal value.</p>

#### ACK_IN field

<p>Readout of the current synchronized CT_Ack_in signal value.</p>

#### REQ_IN field

<p>Readout of the current synchronized CT_Req_in signal value.</p>

#### ACK_OUT field

<p>Readout of the current CT_Ack_out signal value.</p>

### STRETCH_MULT register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>Pulse Stretch Multiplier</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
|15:0|STRETCH_MULT|  rw  | 0x0 |  — |

#### STRETCH_MULT field

<p>The number of clock cycles a core-side cross trigger pulse is stretched on the GPIO pin when in wire-OR mode. Whenever a core-side pulse is received, the generated GPIO pulse has a width of (STRETCH_MULT+1) clock cycles.</p>
