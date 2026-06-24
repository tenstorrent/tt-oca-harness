<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: log_engine
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/log_engine/regs/log_engine.rdl
-->

## log_engine address map

- Absolute Address: 0x0
- Base Offset: 0x0
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

- Absolute Address: 0x0
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

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>Log Region Size Register</p>

|Bits|   Identifier  |Access|Reset|Name|
|----|---------------|------|-----|----|
|19:0|LOG_REGION_SIZE|  rw  | 0x0 |  — |

#### LOG_REGION_SIZE field

<p>Log Region Size. Specified in bytes. Needs to be a multiple of 16.</p>

### LOG_REGION_ADDR register

- Absolute Address: 0x8
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

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

<p>Log Write Address Register</p>

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|31:0|LOG_WRITE_ADDR|  rw  | 0x0 |  — |

#### LOG_WRITE_ADDR field

<p>Log Write Address. This is the address where the log data is written to.</p>

### INTR_STATUS register

- Absolute Address: 0x14
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

- Absolute Address: 0x18
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

- Absolute Address: 0x1C
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

- Absolute Address: 0x40
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

- Absolute Address: 0x44
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

- Absolute Address: 0x48
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

- Absolute Address: 0x4C
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

- Absolute Address: 0x50
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

- Absolute Address: 0x54
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

- Absolute Address: 0x58
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

- Absolute Address: 0x5C
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

- Absolute Address: 0x60
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

- Absolute Address: 0x64
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

- Absolute Address: 0x68
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

- Absolute Address: 0x6C
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

- Absolute Address: 0x70
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

- Absolute Address: 0x74
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

- Absolute Address: 0x78
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

- Absolute Address: 0x7C
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
