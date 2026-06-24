<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: telemetry_receiver
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/telemetry_receiver/regs/telemetry_receiver.rdl
-->

## telemetry_receiver address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x100

<p>Telemetry Receiver</p>

|Offset|      Identifier      |Name|
|------|----------------------|----|
| 0x00 |         CTRL         |  — |
| 0x04 |        STATUS        |  — |
| 0x08 |      INTR_STATUS     |  — |
| 0x0C |      INTR_ENABLE     |  — |
| 0x10 |       INTR_TEST      |  — |
| 0x14 |  TELEMETRY_PROBE_ID  |  — |
| 0x18 |TELEMETRY_COUNTER_VLDS|  — |
| 0x80 | TELEMETRY_COUNTER[0] |  — |
| 0x84 | TELEMETRY_COUNTER[1] |  — |
| 0x88 | TELEMETRY_COUNTER[2] |  — |
| 0x8C | TELEMETRY_COUNTER[3] |  — |
| 0x90 | TELEMETRY_COUNTER[4] |  — |
| 0x94 | TELEMETRY_COUNTER[5] |  — |
| 0x98 | TELEMETRY_COUNTER[6] |  — |
| 0x9C | TELEMETRY_COUNTER[7] |  — |
| 0xA0 | TELEMETRY_COUNTER[8] |  — |
| 0xA4 | TELEMETRY_COUNTER[9] |  — |
| 0xA8 | TELEMETRY_COUNTER[10]|  — |
| 0xAC | TELEMETRY_COUNTER[11]|  — |
| 0xB0 | TELEMETRY_COUNTER[12]|  — |
| 0xB4 | TELEMETRY_COUNTER[13]|  — |
| 0xB8 | TELEMETRY_COUNTER[14]|  — |
| 0xBC | TELEMETRY_COUNTER[15]|  — |
| 0xC0 | TELEMETRY_COUNTER[16]|  — |
| 0xC4 | TELEMETRY_COUNTER[17]|  — |
| 0xC8 | TELEMETRY_COUNTER[18]|  — |
| 0xCC | TELEMETRY_COUNTER[19]|  — |
| 0xD0 | TELEMETRY_COUNTER[20]|  — |
| 0xD4 | TELEMETRY_COUNTER[21]|  — |
| 0xD8 | TELEMETRY_COUNTER[22]|  — |
| 0xDC | TELEMETRY_COUNTER[23]|  — |
| 0xE0 | TELEMETRY_COUNTER[24]|  — |
| 0xE4 | TELEMETRY_COUNTER[25]|  — |
| 0xE8 | TELEMETRY_COUNTER[26]|  — |
| 0xEC | TELEMETRY_COUNTER[27]|  — |
| 0xF0 | TELEMETRY_COUNTER[28]|  — |
| 0xF4 | TELEMETRY_COUNTER[29]|  — |
| 0xF8 | TELEMETRY_COUNTER[30]|  — |
| 0xFC | TELEMETRY_COUNTER[31]|  — |

### CTRL register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>Control Register</p>

| Bits|    Identifier    |Access|Reset|Name|
|-----|------------------|------|-----|----|
|  0  |    BUFFER_POP    |   w  | 0x0 |  — |
|  4  |TELEMETRY_RX_FLUSH|   w  | 0x0 |  — |
|  8  |TELEMETRY_TX_FLUSH|  rw  | 0x0 |  — |
|23:12| BUFFER_THRESHOLD |  rw  | 0x0 |  — |

#### BUFFER_POP field

<p>Telemetry Message Buffer Pop. Effective only if <code>STATUS.BUFFER_EMPTY = 0</code>.
Writing <code>1</code> pops the buffer and thus updates the data in the
<code>TELEMETRY_PROBE_ID</code>, <code>TELEMETRY_COUNTER_VLDS</code>, and <code>TELEMETRY_COUNTER[32]</code>
registers.</p>

#### TELEMETRY_RX_FLUSH field

<p>Telemetry Receiver Flush. Writing <code>1</code> flushes the Telemetry Receiver Buffer and
all other storage elements in the Telemetry Receiver.</p>

#### TELEMETRY_TX_FLUSH field

<p>Telemetry Transmitter Flush. Writing <code>1</code> flushes all FIFOs in the telemetry
transmitter. The flushing is done via the ATB AF interface. This bit clears
itself after the flush completes.</p>

#### BUFFER_THRESHOLD field

<p>Telemetry Message Buffer Threshold. The Telemetry Buffer Threshold Interrupt is
asserted when the number of entries in the buffer is greater than this value.</p>

### STATUS register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>Status Register</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
|  0 |BUFFER_EMPTY|   r  | 0x1 |  — |
|  4 | BUFFER_FULL|   r  | 0x0 |  — |

#### BUFFER_EMPTY field

<p>Telemetry Message Buffer Empty.</p>

#### BUFFER_FULL field

<p>Telemetry Message Buffer Full.</p>

### INTR_STATUS register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>Interrupt Status Register</p>

|Bits|   Identifier   |  Access |Reset|Name|
|----|----------------|---------|-----|----|
|  0 |  MISSING_LAST  |rw, woclr| 0x0 |  — |
|  4 |BUFFER_THRESHOLD|    r    | 0x0 |  — |

#### MISSING_LAST field

<p>Last Packet Missing Interrupt. Asserted when the Telemetry Receiver has not
received a Last Packet flag when the maximum number of packets a message can
consist of has been received.</p>

#### BUFFER_THRESHOLD field

<p>Telemetry Message Buffer Threshold Interrupt. Asserted when the number of
telemetry messages in the Telemetry Message Buffer is greater than
<code>CTRL.BUFFER_THRESHOLD</code>.</p>

### INTR_ENABLE register

- Absolute Address: 0xC
- Base Offset: 0xC
- Size: 0x4

<p>Interrupt Enable Register</p>

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|  0 |  MISSING_LAST  |  rw  | 0x0 |  — |
|  4 |BUFFER_THRESHOLD|  rw  | 0x0 |  — |

#### MISSING_LAST field

<p>Last Packet Missing Interrupt Enable.</p>

#### BUFFER_THRESHOLD field

<p>Telemetry Message Buffer Threshold Interrupt Enable.</p>

### INTR_TEST register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

<p>Interrupt Test Register</p>

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|  0 |  MISSING_LAST  |   w  | 0x0 |  — |
|  4 |BUFFER_THRESHOLD|  rw  | 0x0 |  — |

#### MISSING_LAST field

<p>Last Packet Missing Interrupt Test. Writing <code>1</code> forces the interrupt.</p>

#### BUFFER_THRESHOLD field

<p>Telemetry Message Buffer Threshold Interrupt Test. Writing <code>1</code> forces the
interrupt and writing <code>0</code> releases it.</p>

### TELEMETRY_PROBE_ID register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

<p>Telemetry Probe ID Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 4:0| PROBE_ID |   r  | 0x0 |  — |

#### PROBE_ID field

<p>Probe ID. Contains the Probe ID field of the telemetry message at the bottom of
the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER_VLDS register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

<p>Telemetry Counter Valid Bits Register</p>

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
|31:0|COUNTER_VLDS|   r  | 0x0 |  — |

#### COUNTER_VLDS field

<p>Counter Valid Bits. Indicates which of the counter values in the telemetry
message at the bottom of the Telemetry Message Buffer are valid. Bit <code>i</code> is for
the <code>i</code>-th counter.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0x80
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0x84
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0x88
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0x8C
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0x90
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0x94
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0x98
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0x9C
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xA0
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xA4
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xA8
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xAC
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xB0
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xB4
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xB8
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xBC
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xC0
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xC4
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xC8
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xCC
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xD0
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xD4
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xD8
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xDC
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xE0
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xE4
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xE8
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xEC
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xF0
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xF4
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xF8
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>

### TELEMETRY_COUNTER register

- Absolute Address: 0xFC
- Base Offset: 0x80
- Size: 0x4
- Array Dimensions: [32]
- Array Stride: 0x4
- Total Size: 0x80

<p>Telemetry Counter Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  COUNTER |   r  | 0x0 |  — |

#### COUNTER field

<p>Counter Value. Contains one of the 32 counter values in the telemetry message
at the bottom of the Telemetry Message Buffer.</p>
