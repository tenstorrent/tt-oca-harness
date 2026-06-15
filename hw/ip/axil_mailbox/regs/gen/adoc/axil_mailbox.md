<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: axil_mailbox
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/axil_mailbox/regs/axil_mailbox.rdl
-->

## axil_mailbox address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x50



|Offset| Identifier|Name|
|------|-----------|----|
| 0x00 | WRITE_DATA|  — |
| 0x08 | READ_DATA |  — |
| 0x10 |   STATUS  |  — |
| 0x18 |ERROR_FLAGS|  — |
| 0x20 |   WIRQT   |  — |
| 0x28 |   RIRQT   |  — |
| 0x30 |    IRQS   |  — |
| 0x38 |   IRQEN   |  — |
| 0x40 |    IRQP   |  — |
| 0x48 |    CTRL   |  — |

### WRITE_DATA register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x8

|Bits|       Identifier       |Access|Reset|Name|
|----|------------------------|------|-----|----|
|  0 |          empty         |   r  | 0x0 |  — |
|  1 |          full          |   r  | 0x0 |  — |
|  2 |write_level_above_thresh|   r  | 0x0 |  — |
|  3 | read_level_above_thresh|   r  | 0x0 |  — |

#### empty field

<p>0: Data is available to read, 1: Data is not available to read</p>

#### full field

<p>0: Space is available to write, 1: Space is not available to write</p>

#### write_level_above_thresh field

<p>If set, write fifo level is higher than threshhold set in WIRQT</p>

#### read_level_above_thresh field

<p>If set, read fifo level is higher than threshhold set in RIRQT</p>

### ERROR_FLAGS register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x8

|Bits| Identifier|Access|Reset|Name|
|----|-----------|------|-----|----|
|  0 | read_error|   r  | 0x0 |  — |
|  1 |write_error|   r  | 0x0 |  — |

#### read_error field

<p>Attempted read from an empty mailbox</p>

#### write_error field

<p>Attempted write to a full mailbox</p>

### WIRQT register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x28
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x30
- Base Offset: 0x30
- Size: 0x8

<p>This register is used to read and clear interrupt requests, regardless of IRQEN register and whether the interrupt is enabled or disabled.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   wtirq  |  rw  | 0x0 |  — |
|  1 |   rtirq  |  rw  | 0x0 |  — |
|  2 |   eirq   |  rw  | 0x0 |  — |

#### wtirq field

<p>On read:
[0]: No interrupt request
[1]: Usage level threshold in write mailbox exceeded
On write:
[0]: No acknowledge
[1]: Acknowledge and clear interrupt request</p>

#### rtirq field

<p>On read:
[0]: No interrupt request
[1]: Usage level threshold in read mailbox exceeded
On write:
[0]: No acknowledge
[1]: Acknowledge and clear interrupt request</p>

#### eirq field

<p>On read:
[0]: No interrupt request
[1]: Error on mailbox access
On write:
[0]: No acknowledge
[1]: Acknowledge and clear interrupt request</p>

### IRQEN register

- Absolute Address: 0x38
- Base Offset: 0x38
- Size: 0x8

<p>This register is used to enable and disable which interrupts are sent to the CPU.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   wtirq  |  rw  | 0x0 |  — |
|  1 |   rtirq  |  rw  | 0x0 |  — |
|  2 |   eirq   |  rw  | 0x0 |  — |

#### wtirq field

<p>[0]: Write threshold IRQ disabled
[1]: Write threshold IRQ enabled</p>

#### rtirq field

<p>[0]: Read threshold IRQ disabled
[1]: Read threshold IRQ enabled</p>

#### eirq field

<p>[0]: Error IRQ disabled
[1]: Error IRQ enabled</p>

### IRQP register

- Absolute Address: 0x40
- Base Offset: 0x40
- Size: 0x8

<p>This register is used to read the current status of the interrupts sent to the CPU.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |   wtirq  |   r  | 0x0 |  — |
|  1 |   rtirq  |   r  | 0x0 |  — |
|  2 |   eirq   |   r  | 0x0 |  — |

#### wtirq field

<p>[0]: No write threshold IRQ pending
[1]: Write threshold IRQ pending</p>

#### rtirq field

<p>[0]: No read threshold IRQ pending
[1]: Read threshold IRQ pending</p>

#### eirq field

<p>[0]: No error IRQ pending
[1]: Error IRQ pending</p>

### CTRL register

- Absolute Address: 0x48
- Base Offset: 0x48
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 |  wflush  |   w  | 0x0 |  — |
|  1 |  rflush  |   w  | 0x0 |  — |

#### wflush field

<p>Flush the write FIFO for this port</p>

#### rflush field

<p>Flush the read FIFO for this port</p>
