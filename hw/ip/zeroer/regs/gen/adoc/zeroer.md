<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: zeroer_ctrl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/zeroer/regs/zeroer.rdl
-->

## zeroer_ctrl address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x18

<p>AXI zeroer control register</p>

|Offset| Identifier|Name|
|------|-----------|----|
| 0x00 | DEST_ADDR |  — |
| 0x08 |    SIZE   |  — |
| 0x10 |CTRL_STATUS|  — |

### DEST_ADDR register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| DEST_ADDR|  rw  | 0x0 |  — |

#### DEST_ADDR field

<p>Byte address to write zeros to</p>

### SIZE register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|   SIZE   |  rw  | 0x0 |  — |

#### SIZE field

<p>Size in bytes of zeros to write</p>

### CTRL_STATUS register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x8

<p>Writing this register will trigger start of zeroer</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  INT_EN  |  rw  | 0x0 |  — |
| 32 |  STATUS  |   r  | 0x0 |  — |

#### INT_EN field

<p>If enabled, an interrupt will be outputted once zeroer completes.</p>

#### STATUS field

<p>Returns status of whether zeroer has completed.</p>
