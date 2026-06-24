<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: output_remap
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/output_remap/regs/output_remap.rdl
-->

## output_remap address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x8

<p>TLB Registers for address remapping and attribute tagging</p>

|Offset|Identifier|Name|
|------|----------|----|
|  0x0 |  REGION  |  — |

## REGION register file

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x8

|Offset| Identifier |Name|
|------|------------|----|
|  0x0 |region_attrs|  — |

### region_attrs register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|55:0|  offset  |  rw  | 0x0 |  — |

#### offset field

<p>Address translation for remap region. RTL will use the number of bits appropriate for region granulaity.
e.g. SMC: 8 * 1MB regions --&gt; 20 bits of address space per region, 36 MSBs from this register used
    SEP: 16 * 512KB regions --&gt; 19 bits of address space per region, 37 MSBs from this register used</p>
