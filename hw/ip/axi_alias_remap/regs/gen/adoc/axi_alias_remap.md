<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: alias_remap
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/axi_alias_remap/regs/axi_alias_remap.rdl
-->

## alias_remap address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x18

<p>TLB Registers for address remapping and attribute tagging</p>

|Offset|Identifier|Name|
|------|----------|----|
|  0x0 |  REGION  |  — |

## REGION register file

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x18

|Offset| Identifier |Name|
|------|------------|----|
| 0x00 |region_start|  — |
| 0x08 | region_end |  — |
| 0x10 |region_attrs|  — |

### region_start register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x8

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
|55:12|start_addr|  rw  | 0x0 |  — |

#### start_addr field

<p>Start of remap region</p>

### region_end register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x8

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
|55:12| end_addr |  rw  | 0x0 |  — |

#### end_addr field

<p>End of remap region (non-inclusive).</p>

### region_attrs register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x8

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
|55:12|  offset  |  rw  | 0x0 |  — |
|  62 | cacheable|  rw  | 0x0 |  — |
|  63 |   valid  |  rw  | 0x0 |  — |

#### offset field

<p>The value of this field is added to bits [55:12] of the input address when it falls within the remap region. The lower 12 bits of the address are preserved unchanged.</p>

#### cacheable field

<p>If set, top two bits of a*cache will be tied high</p>

#### valid field

<p>If set, this remap will be active</p>
