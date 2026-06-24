<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: system_timer_octs
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/system_timer_octs/regs/system_timer_octs.rdl
-->

## system_timer_octs address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x24

<p>Open Chiplet Time Synchronization (OCTS) System Timer Registers</p>

|Offset|    Identifier   |Name|
|------|-----------------|----|
| 0x00 |   TIMER_START   |  — |
| 0x04 |       CTRL      |  — |
| 0x08 |      STATUS     |  — |
| 0x0C | TIMER_PRESET_LO |  — |
| 0x10 | TIMER_PRESET_HI |  — |
| 0x14 |  TIMER_COUNT_LO |  — |
| 0x18 |  TIMER_COUNT_HI |  — |
| 0x1C |  CREDIT_EXPIRED |  — |
| 0x20 |TIMER_GPIO_ENABLE|  — |

### TIMER_START register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>System Timer Start Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   START  |  rw  | 0x0 |  — |

#### START field

<p>Start the system timer. Asserts the sync_load signal to start synchronization (only does anything if primary mode). Ensure
both primary and secondary are out of reset.</p>

### CTRL register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>System Timer Control Register</p>

| Bits| Identifier|Access|Reset|Name|
|-----|-----------|------|-----|----|
| 7:0 | CREDIT_VAL|  rw  | 0xA |  — |
| 15:8|PULSE_WIDTH|  rw  | 0x2 |  — |
|23:16|    STEP   |  rw  | 0x1 |  — |

#### CREDIT_VAL field

<p>Credit value factor. WARNING: This value must be greater than PULSE_WIDTH</p>

#### PULSE_WIDTH field

<p>Pulse width for sync load and credit signals. A value of 0 will be rounded up to 1. WARNING: This value must be less than CREDIT_VAL</p>

#### STEP field

<p>Step amount for secondary timer</p>

### STATUS register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>System Timer Status Register</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   MODE   |   r  | 0x0 |  — |
|  4 |  RUNNING |   r  | 0x0 |  — |

#### MODE field

<p>Timer mode: 0=PRIMARY, 1=SECONDARY (set by module parameter)</p>

#### RUNNING field

<p>Timer is currently enabled and running</p>

### TIMER_PRESET_LO register

- Absolute Address: 0xC
- Base Offset: 0xC
- Size: 0x4

<p>System Timer Preset Value [31:0]</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0| PRESET_LO|  rw  | 0x0 |  — |

#### PRESET_LO field

<p>Lower 32 bits of preset value</p>

### TIMER_PRESET_HI register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

<p>System Timer Preset Value [63:32]</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0| PRESET_HI|  rw  | 0x0 |  — |

#### PRESET_HI field

<p>Upper 32 bits of preset value</p>

### TIMER_COUNT_LO register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

<p>Current System Timer Count [31:0]</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0| COUNT_LO |   r  | 0x0 |  — |

#### COUNT_LO field

<p>Lower 32 bits of current timer count</p>

### TIMER_COUNT_HI register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

<p>Current System Timer Count [63:32]</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0| COUNT_HI |   r  | 0x0 |  — |

#### COUNT_HI field

<p>Upper 32 bits of current timer count</p>

### CREDIT_EXPIRED register

- Absolute Address: 0x1C
- Base Offset: 0x1C
- Size: 0x4

<p>Credit Expired Register</p>

|Bits|    Identifier    |Access|Reset|Name|
|----|------------------|------|-----|----|
|31:0|MAX_CYCLES_EXPIRED|  rw  | 0x0 |  — |

#### MAX_CYCLES_EXPIRED field

<p>Maximum number of clock cycles since a count credit expired (SECONDARY only). To reset the value of this register, write anything to it.
If this number is very high (exact value depends on clock speed and credit value), this indicates that the secondary has not recieved a count credit pulse in a while, and is likely not syncing properly with the primary.
This register can also be used to determine the clock skew between the primary and secondary.
If PRIMARY, this field is always 0.</p>

### TIMER_GPIO_ENABLE register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x4

<p>System Timer GPIO Enable Register</p>

|Bits| Identifier|Access|Reset|Name|
|----|-----------|------|-----|----|
|  0 |GPIO_ENABLE|  rw  | 0x0 |  — |

#### GPIO_ENABLE field

<p>Enable the GPIO pad lsio interface for the system timer. This is done to prevent X-prop on reset into the secondary timer, which can cause the secondary timer to start counting early.</p>
