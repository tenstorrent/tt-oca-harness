<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: gpio
  - hw/ip/gpio/rdl/gpio.rdl
-->

## gpio address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x8

<p>Sample GPIO register block</p>

|Offset|Identifier|Name|
|------|----------|----|
|  0x0 | DATA_CTRL|  — |
|  0x4 |  CONTROL |  — |

### DATA_CTRL register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|  0 |    core2pad    |  rw  | 0x0 |  — |
| 16 |interface_enable|  rw  | 0x0 |  — |
| 31 |    pad2core    |   r  | 0x0 |  — |

#### core2pad field

<p>Register-driven data to send to the pad.</p>

#### interface_enable field

<p>Register interface enable.</p>

#### pad2core field

<p>PAD2SOC value.</p>

### CONTROL register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

|Bits|     Identifier    |Access|Reset|Name|
|----|-------------------|------|-----|----|
| 2:0|   drive_strength  |  rw  | 0x2 |  — |
|  8 |pull_enable_n0_scan|  rw  | 0x0 |  — |
|  9 |    pull_select    |  rw  | 0x0 |  — |

#### drive_strength field

<p>Register-driven drive strength.</p>

#### pull_enable_n0_scan field

<p>Register-driven pull enable.</p>

#### pull_select field

<p>Register-driven pull select.</p>
