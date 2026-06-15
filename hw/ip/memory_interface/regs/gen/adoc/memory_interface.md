<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: example_sram_wrap
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/memory_interface/regs/memory_interface.rdl
-->

## example_sram_wrap address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x200C

<p>Example SRAM Wrap</p>

|Offset|      Identifier      |Name|
|------|----------------------|----|
|0x0000|     example_sram     |  — |
|0x2000|example_sram_macro_csr|  — |

## example_sram memory

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x1000

<p>Example SRAM Memory</p>

|Offset| Identifier |Name|
|------|------------|----|
|  0x0 |mem_array[0]|  — |

### mem_array register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x1000
- Array Dimensions: [1024]
- Array Stride: 0x4
- Total Size: 0x1000

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   data   |  rw  |  —  |  — |

## example_sram_macro_csr address map

- Absolute Address: 0x2000
- Base Offset: 0x2000
- Size: 0xC

<p>Example SRAM Macro CSRs</p>

|Offset|   Identifier   |Name|
|------|----------------|----|
|  0x0 |   STATUS_INTR  |  — |
|  0x4 |STATUS_INTR_MASK|  — |
|  0x8 |    TEST_REG    |  — |

### STATUS_INTR register

- Absolute Address: 0x2000
- Base Offset: 0x0
- Size: 0x4

<p>Status Register with level interrupts</p>

|Bits|Identifier|  Access |Reset|Name|
|----|----------|---------|-----|----|
|  0 |   busy   |rw, woclr| 0x0 |  — |
| 5:4|   error  |rw, woclr| 0x0 |  — |
|  8 |   alert  |rw, woclr| 0x0 |  — |

#### busy field

<p>Macro is busy</p>

#### error field

<p>Error occurred during operation. Bit 0 - Single bit error, Bit 1 - Double bit error</p>

#### alert field

<p>Alert occurred, due to control signal corruption</p>

### STATUS_INTR_MASK register

- Absolute Address: 0x2004
- Base Offset: 0x4
- Size: 0x4

<p>Interrupt Mask Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  busy_en |  rw  | 0x0 |  — |
| 5:4| error_en |  rw  | 0x3 |  — |
|  8 | alert_en |  rw  | 0x1 |  — |

#### busy_en field

<p>Busy Interrupt Enable. Disabled by default.</p>

#### error_en field

<p>Error Interrupt Enable. Enabled by default.</p>

#### alert_en field

<p>Alert Interrupt Enable. Enabled by default.</p>

### TEST_REG register

- Absolute Address: 0x2008
- Base Offset: 0x8
- Size: 0x4

<p>Test Register for checking reg writes</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   test   |  rw  | 0x0 |  — |

#### test field

<p>Test Register</p>
