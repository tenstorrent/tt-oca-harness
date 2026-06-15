<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: dma_ctrl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/perf_dma/regs/perf_dma.rdl
-->

## dma_ctrl address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x138

|Offset|    Identifier    |Name|
|------|------------------|----|
| 0x000|      CONFIG      |  — |
| 0x004|     STATUS_0     |  — |
| 0x008|     STATUS_1     |  — |
| 0x00C|     STATUS_2     |  — |
| 0x010|     STATUS_3     |  — |
| 0x014|     STATUS_4     |  — |
| 0x018|     STATUS_5     |  — |
| 0x01C|     STATUS_6     |  — |
| 0x020|     STATUS_7     |  — |
| 0x024|     STATUS_8     |  — |
| 0x028|     STATUS_9     |  — |
| 0x02C|     STATUS_10    |  — |
| 0x030|     STATUS_11    |  — |
| 0x034|     STATUS_12    |  — |
| 0x038|     STATUS_13    |  — |
| 0x03C|     STATUS_14    |  — |
| 0x040|     STATUS_15    |  — |
| 0x048|     NEXT_ID_0    |  — |
| 0x050|     NEXT_ID_1    |  — |
| 0x058|     NEXT_ID_2    |  — |
| 0x060|     NEXT_ID_3    |  — |
| 0x068|     NEXT_ID_4    |  — |
| 0x070|     NEXT_ID_5    |  — |
| 0x078|     NEXT_ID_6    |  — |
| 0x080|     NEXT_ID_7    |  — |
| 0x088|     NEXT_ID_8    |  — |
| 0x090|     NEXT_ID_9    |  — |
| 0x098|    NEXT_ID_10    |  — |
| 0x0A0|    NEXT_ID_11    |  — |
| 0x0A8|    NEXT_ID_12    |  — |
| 0x0B0|    NEXT_ID_13    |  — |
| 0x0B8|    NEXT_ID_14    |  — |
| 0x0C0|    NEXT_ID_15    |  — |
| 0x0C8|      DONE_0      |  — |
| 0x0CC|      DONE_1      |  — |
| 0x0D0|      DONE_2      |  — |
| 0x0D4|      DONE_3      |  — |
| 0x0D8|      DONE_4      |  — |
| 0x0DC|      DONE_5      |  — |
| 0x0E0|      DONE_6      |  — |
| 0x0E4|      DONE_7      |  — |
| 0x0E8|      DONE_8      |  — |
| 0x0EC|      DONE_9      |  — |
| 0x0F0|      DONE_10     |  — |
| 0x0F4|      DONE_11     |  — |
| 0x0F8|      DONE_12     |  — |
| 0x0FC|      DONE_13     |  — |
| 0x100|      DONE_14     |  — |
| 0x104|      DONE_15     |  — |
| 0x108|  DST_ADDRESS_LO  |  — |
| 0x10C|  DST_ADDRESS_HI  |  — |
| 0x110|  SRC_ADDRESS_LO  |  — |
| 0x114|  SRC_ADDRESS_HI  |  — |
| 0x118|     LENGTH_LO    |  — |
| 0x11C|     LENGTH_HI    |  — |
| 0x120|   DST_STRIDE_LO  |  — |
| 0x124|   DST_STRIDE_HI  |  — |
| 0x128|   SRC_STRIDE_LO  |  — |
| 0x12C|   SRC_STRIDE_HI  |  — |
| 0x130|NUM_REPETITIONS_LO|  — |
| 0x134|NUM_REPETITIONS_HI|  — |

### CONFIG register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

|Bits|  Identifier  |Access|Reset|Name|
|----|--------------|------|-----|----|
|  0 |  DECOUPLE_AW |  rw  | 0x0 |  — |
|  1 |  DECOUPLE_RW |  rw  | 0x0 |  — |
|  2 |SRC_REDUCE_LEN|  rw  | 0x0 |  — |
|  3 |DST_REDUCE_LEN|  rw  | 0x0 |  — |
| 6:4| SRC_MAX_LLEN |  rw  | 0x0 |  — |
| 9:7| DST_MAX_LLEN |  rw  | 0x0 |  — |
| 10 |  ENABLED_ND  |  rw  | 0x0 |  — |

#### DECOUPLE_AW field

<p>Not used</p>

#### DECOUPLE_RW field

<p>Not used</p>

#### SRC_REDUCE_LEN field

<p>Not used</p>

#### DST_REDUCE_LEN field

<p>Not used</p>

#### SRC_MAX_LLEN field

<p>Not used</p>

#### DST_MAX_LLEN field

<p>Not used</p>

#### ENABLED_ND field

<p>Not used</p>

### STATUS_0 register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_1 register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_2 register

- Absolute Address: 0xC
- Base Offset: 0xC
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_3 register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_4 register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_5 register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_6 register

- Absolute Address: 0x1C
- Base Offset: 0x1C
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_7 register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_8 register

- Absolute Address: 0x24
- Base Offset: 0x24
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_9 register

- Absolute Address: 0x28
- Base Offset: 0x28
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_10 register

- Absolute Address: 0x2C
- Base Offset: 0x2C
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_11 register

- Absolute Address: 0x30
- Base Offset: 0x30
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_12 register

- Absolute Address: 0x34
- Base Offset: 0x34
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_13 register

- Absolute Address: 0x38
- Base Offset: 0x38
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_14 register

- Absolute Address: 0x3C
- Base Offset: 0x3C
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### STATUS_15 register

- Absolute Address: 0x40
- Base Offset: 0x40
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 9:0|   BUSY   |   r  | 0x0 |  — |

#### BUSY field

<p>DMA busy bits. Reading 0 means the DMA has written the last data beat but not necessarily seen the last response</p>

### NEXT_ID_0 register

- Absolute Address: 0x48
- Base Offset: 0x48
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_1 register

- Absolute Address: 0x50
- Base Offset: 0x50
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_2 register

- Absolute Address: 0x58
- Base Offset: 0x58
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_3 register

- Absolute Address: 0x60
- Base Offset: 0x60
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_4 register

- Absolute Address: 0x68
- Base Offset: 0x68
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_5 register

- Absolute Address: 0x70
- Base Offset: 0x70
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_6 register

- Absolute Address: 0x78
- Base Offset: 0x78
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_7 register

- Absolute Address: 0x80
- Base Offset: 0x80
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_8 register

- Absolute Address: 0x88
- Base Offset: 0x88
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_9 register

- Absolute Address: 0x90
- Base Offset: 0x90
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_10 register

- Absolute Address: 0x98
- Base Offset: 0x98
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_11 register

- Absolute Address: 0xA0
- Base Offset: 0xA0
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_12 register

- Absolute Address: 0xA8
- Base Offset: 0xA8
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_13 register

- Absolute Address: 0xB0
- Base Offset: 0xB0
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_14 register

- Absolute Address: 0xB8
- Base Offset: 0xB8
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### NEXT_ID_15 register

- Absolute Address: 0xC0
- Base Offset: 0xC0
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Reading this register starts the DMA transfer. Returns an ID value for the cumulative number of transfers. Returns 0 if command was not set up correctly</p>

### DONE_0 register

- Absolute Address: 0xC8
- Base Offset: 0xC8
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_1 register

- Absolute Address: 0xCC
- Base Offset: 0xCC
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_2 register

- Absolute Address: 0xD0
- Base Offset: 0xD0
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_3 register

- Absolute Address: 0xD4
- Base Offset: 0xD4
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_4 register

- Absolute Address: 0xD8
- Base Offset: 0xD8
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_5 register

- Absolute Address: 0xDC
- Base Offset: 0xDC
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_6 register

- Absolute Address: 0xE0
- Base Offset: 0xE0
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_7 register

- Absolute Address: 0xE4
- Base Offset: 0xE4
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_8 register

- Absolute Address: 0xE8
- Base Offset: 0xE8
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_9 register

- Absolute Address: 0xEC
- Base Offset: 0xEC
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_10 register

- Absolute Address: 0xF0
- Base Offset: 0xF0
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_11 register

- Absolute Address: 0xF4
- Base Offset: 0xF4
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_12 register

- Absolute Address: 0xF8
- Base Offset: 0xF8
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_13 register

- Absolute Address: 0xFC
- Base Offset: 0xFC
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_14 register

- Absolute Address: 0x100
- Base Offset: 0x100
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DONE_15 register

- Absolute Address: 0x104
- Base Offset: 0x104
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |   r  | 0x0 |  — |

#### DATA field

<p>Holds the cumulative number of completed transfers. Only accumulates when response is seen</p>

### DST_ADDRESS_LO register

- Absolute Address: 0x108
- Base Offset: 0x108
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Destination address for DMA to write to, lower 32 bits</p>

### DST_ADDRESS_HI register

- Absolute Address: 0x10C
- Base Offset: 0x10C
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Destination address for DMA to write to, upper 32 bits</p>

### SRC_ADDRESS_LO register

- Absolute Address: 0x110
- Base Offset: 0x110
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Source address for DMA to read from, lower 32 bits.</p>

### SRC_ADDRESS_HI register

- Absolute Address: 0x114
- Base Offset: 0x114
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Source address for DMA to read from, upper 32 bits.</p>

### LENGTH_LO register

- Absolute Address: 0x118
- Base Offset: 0x118
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Number of bytes to move, lower 32 bits.</p>

### LENGTH_HI register

- Absolute Address: 0x11C
- Base Offset: 0x11C
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Number of bytes to move, upper 32 bits.</p>

### DST_STRIDE_LO register

- Absolute Address: 0x120
- Base Offset: 0x120
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Stride amount on destination address side, lower 32 bits</p>

### DST_STRIDE_HI register

- Absolute Address: 0x124
- Base Offset: 0x124
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Stride amount on destination address side, upper 32 bits</p>

### SRC_STRIDE_LO register

- Absolute Address: 0x128
- Base Offset: 0x128
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Stride amount on source address side, lower 32 bits</p>

### SRC_STRIDE_HI register

- Absolute Address: 0x12C
- Base Offset: 0x12C
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Stride amount on source address side, upper 32 bits</p>

### NUM_REPETITIONS_LO register

- Absolute Address: 0x130
- Base Offset: 0x130
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Number of times transfer should be repeated, lower 32 bits. If stride is set, stride will be added to address after every repetition</p>

### NUM_REPETITIONS_HI register

- Absolute Address: 0x134
- Base Offset: 0x134
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   DATA   |  rw  | 0x0 |  — |

#### DATA field

<p>Number of times transfer should be repeated, upper 32 bits. If stride is set, stride will be added to address after every repetition</p>
