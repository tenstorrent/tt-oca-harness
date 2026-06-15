<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: efuse_shim_ctrl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/efuse/dv/shims/regs/efuse_shim_ctrl.rdl
-->

## efuse_shim_ctrl address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

|Offset|     Identifier     |Name|
|------|--------------------|----|
|  0x0 |EFUSE_BANK_INIT_TIME|  — |

### EFUSE_BANK_INIT_TIME register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>eFuse bank initialization time. Number of cycles to wait for the OTP macro to initialize before sensing can begin.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0| init_time|  rw  | 0x20|  — |

#### init_time field

<p>Most OTP have a initalization time before sensing can be done</p>
