<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: gpio_wrap
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/gpio_wrap/regs/gpio_wrap.rdl
-->

## gpio_wrap address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x14

<p>Top-level addrmap for gpio_intf and gpio_shim</p>

|Offset|Identifier|Name|
|------|----------|----|
| 0x00 | gpio_intf|  — |
| 0x10 | gpio_ctrl|  — |

## gpio_intf address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0xC

<p>GPIO Interface CSR</p>

|Offset|  Identifier |Name|
|------|-------------|----|
|  0x0 |  DATA_CTRL  |  — |
|  0x8 |ACCESS_FILTER|  — |

### DATA_CTRL register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

| Bits|   Identifier   |Access|Reset|Name|
|-----|----------------|------|-----|----|
|  0  |    core2pad    |  rw  | 0x0 |  — |
| 5:4 |  enable_rx_tx  |  rw  | 0x0 |  — |
|  16 |interface_enable|  rw  | 0x0 |  — |
|  17 |   lsio_select  |  rw  | 0x0 |  — |
|  18 |interrupt_enable|  rw  | 0x0 |  — |
|  19 |  lsio_disable  |  rw  | 0x0 |  — |
|21:20| interrupt_type |  rw  | 0x0 |  — |
|  25 |   lsio_enable  |   r  | 0x0 |  — |
|  31 |    pad2core    |   r  | 0x0 |  — |

#### core2pad field

<p>Register-driven data to send to the pad.</p>

#### enable_rx_tx field

<p>2'b00: Neither RX nor TX enabled. 2'b01: TX enabled. 2'b10: RX enabled. 2'b11: Neither RX nor TX enabled.</p>

#### interface_enable field

<p>Register Interface Enable. Setting this chooses register values to drive the PAD. This includes chip2pad, enable_rx_tx, and pad2soc</p>

#### lsio_select field

<p>Force LSIO interface to be used. interface_enable has higher priority over this</p>

#### interrupt_enable field

<p>Interrupt Enable.</p>

#### lsio_disable field

<p>When set, LSIO acceses will be blocked from the GPIO interface</p>

#### interrupt_type field

<p>Interrupt type - 0: active-high level, 1: active-low level, 2: rising edge, 3: falling edge</p>

#### lsio_enable field

<p>When set, this bit indicates that the pad being driving by the LSIO</p>

#### pad2core field

<p>PAD2SOC Value</p>

### ACCESS_FILTER register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>GPIO Access Filter Register. WARNING: please read back this register to ensure the filter was written correctly. If you do not do so
the filter may not update before your next transaction, causing unexpected behavior.</p>

| Bits|     Identifier    |Access|Reset|Name|
|-----|-------------------|------|-----|----|
|  0  |write_filter_enable|  rw  | 0x0 |  — |
|  1  | read_filter_enable|  rw  | 0x0 |  — |
| 10:8| awprot_requirement|  rw  | 0x1 |  — |
|18:16| arprot_requirement|  rw  | 0x1 |  — |

#### write_filter_enable field

<p>Filter Enable - when set, only SEP may access the GPIO register interface. This effectivley makes the GPIO a SEP-only interface.
WARNING: please read back this register to ensure the filter was written correctly. If you do not do so
the filter may not update before your next transaction, causing unexpected behavior.</p>

#### read_filter_enable field

<p>Filter Value - the value that must be written to the filter register to allow access to the GPIO register interface.
WARNING: please read back this register to ensure the filter was written correctly. If you do not do so
the filter may not update before your next transaction, causing unexpected behavior.</p>

#### awprot_requirement field

<p>When write_filter_enable is set, only allow write accesses with this prot value
WARNING: please read back this register to ensure the filter was written correctly. If you do not do so
the filter may not update before your next transaction, causing unexpected behavior.</p>

#### arprot_requirement field

<p>When read_filter_enable is set, only allow read accesses with this prot value
WARNING: please read back this register to ensure the filter was written correctly. If you do not do so
the filter may not update before your next transaction, causing unexpected behavior.</p>

## gpio_ctrl address map

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

<p>GPIO Control CSR</p>

|Offset|Identifier|Name|
|------|----------|----|
|  0x0 |  CONTROL |  — |

### CONTROL register

- Absolute Address: 0x10
- Base Offset: 0x0
- Size: 0x4

|Bits|     Identifier    |Access|Reset|Name|
|----|-------------------|------|-----|----|
| 2:0|   drive_strength  |  rw  | 0x2 |  — |
|  8 |pull_enable_n0_scan|  rw  | 0x0 |  — |
|  9 |    pull_select    |  rw  | 0x0 |  — |
| 10 |   schmitt_select  |  rw  | 0x0 |  — |
| 16 |   config_enable   |  rw  | 0x0 |  — |
| 20 |    strap_valid    |   r  | 0x1 |  — |
| 21 |    strap_value    |   r  | 0x0 |  — |
| 24 |      hw2_ovrd     |  rw  | 0x0 |  — |

#### drive_strength field

<p>Register-driven drive-strength.</p>

#### pull_enable_n0_scan field

<p>Register-driven pull enable. Default is disabled</p>

#### pull_select field

<p>Register-driven pull select - by default we pull down</p>

#### schmitt_select field

<p>Register-driven schmitt select.</p>

#### config_enable field

<p>Setting this choosing the register values for PAD settings. This includes pull_enable, pull_select, and schmitt_select</p>

#### strap_valid field

<p>When set, this bit indicates that the strap value is valid. This field is not set if the GPIO is not an input by default</p>

#### strap_value field

<p>This register holds the captured value that was applied to the pad when reset was de-asserted.</p>

#### hw2_ovrd field

<p>Setting this register will enable the secondary HW function to override the GPIO enable and data lines.</p>
