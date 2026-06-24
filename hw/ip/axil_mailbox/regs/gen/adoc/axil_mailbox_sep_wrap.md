<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: axil_mailbox_sep_wrap
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/axil_mailbox/regs/axil_mailbox_sep_wrap.rdl
-->

## axil_mailbox_sep_wrap address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x7850



|Offset|    Identifier    |Name|
|------|------------------|----|
|0x0000|outbound_mailbox_0|  — |
|0x0800| inbound_mailbox_0|  — |
|0x1000|outbound_mailbox_1|  — |
|0x1800| inbound_mailbox_1|  — |
|0x2000|outbound_mailbox_2|  — |
|0x2800| inbound_mailbox_2|  — |
|0x3000|outbound_mailbox_3|  — |
|0x3800| inbound_mailbox_3|  — |
|0x4000|outbound_mailbox_4|  — |
|0x4800| inbound_mailbox_4|  — |
|0x5000|outbound_mailbox_5|  — |
|0x5800| inbound_mailbox_5|  — |
|0x6000|outbound_mailbox_6|  — |
|0x6800| inbound_mailbox_6|  — |
|0x7000|outbound_mailbox_7|  — |
|0x7800| inbound_mailbox_7|  — |

## outbound_mailbox_0 address map

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

## inbound_mailbox_0 address map

- Absolute Address: 0x800
- Base Offset: 0x800
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

- Absolute Address: 0x800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x810
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

- Absolute Address: 0x818
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

- Absolute Address: 0x820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x830
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

- Absolute Address: 0x838
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

- Absolute Address: 0x840
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

- Absolute Address: 0x848
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

## outbound_mailbox_1 address map

- Absolute Address: 0x1000
- Base Offset: 0x1000
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

- Absolute Address: 0x1000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1010
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

- Absolute Address: 0x1018
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

- Absolute Address: 0x1020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1030
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

- Absolute Address: 0x1038
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

- Absolute Address: 0x1040
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

- Absolute Address: 0x1048
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

## inbound_mailbox_1 address map

- Absolute Address: 0x1800
- Base Offset: 0x1800
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

- Absolute Address: 0x1800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1810
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

- Absolute Address: 0x1818
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

- Absolute Address: 0x1820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1830
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

- Absolute Address: 0x1838
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

- Absolute Address: 0x1840
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

- Absolute Address: 0x1848
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

## outbound_mailbox_2 address map

- Absolute Address: 0x2000
- Base Offset: 0x2000
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

- Absolute Address: 0x2000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x2008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x2010
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

- Absolute Address: 0x2018
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

- Absolute Address: 0x2020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x2028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x2030
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

- Absolute Address: 0x2038
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

- Absolute Address: 0x2040
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

- Absolute Address: 0x2048
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

## inbound_mailbox_2 address map

- Absolute Address: 0x2800
- Base Offset: 0x2800
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

- Absolute Address: 0x2800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x2808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x2810
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

- Absolute Address: 0x2818
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

- Absolute Address: 0x2820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x2828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x2830
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

- Absolute Address: 0x2838
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

- Absolute Address: 0x2840
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

- Absolute Address: 0x2848
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

## outbound_mailbox_3 address map

- Absolute Address: 0x3000
- Base Offset: 0x3000
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

- Absolute Address: 0x3000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x3008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x3010
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

- Absolute Address: 0x3018
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

- Absolute Address: 0x3020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x3028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x3030
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

- Absolute Address: 0x3038
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

- Absolute Address: 0x3040
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

- Absolute Address: 0x3048
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

## inbound_mailbox_3 address map

- Absolute Address: 0x3800
- Base Offset: 0x3800
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

- Absolute Address: 0x3800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x3808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x3810
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

- Absolute Address: 0x3818
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

- Absolute Address: 0x3820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x3828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x3830
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

- Absolute Address: 0x3838
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

- Absolute Address: 0x3840
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

- Absolute Address: 0x3848
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

## outbound_mailbox_4 address map

- Absolute Address: 0x4000
- Base Offset: 0x4000
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

- Absolute Address: 0x4000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x4008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x4010
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

- Absolute Address: 0x4018
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

- Absolute Address: 0x4020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x4028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x4030
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

- Absolute Address: 0x4038
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

- Absolute Address: 0x4040
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

- Absolute Address: 0x4048
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

## inbound_mailbox_4 address map

- Absolute Address: 0x4800
- Base Offset: 0x4800
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

- Absolute Address: 0x4800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x4808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x4810
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

- Absolute Address: 0x4818
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

- Absolute Address: 0x4820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x4828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x4830
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

- Absolute Address: 0x4838
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

- Absolute Address: 0x4840
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

- Absolute Address: 0x4848
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

## outbound_mailbox_5 address map

- Absolute Address: 0x5000
- Base Offset: 0x5000
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

- Absolute Address: 0x5000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x5008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x5010
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

- Absolute Address: 0x5018
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

- Absolute Address: 0x5020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x5028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x5030
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

- Absolute Address: 0x5038
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

- Absolute Address: 0x5040
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

- Absolute Address: 0x5048
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

## inbound_mailbox_5 address map

- Absolute Address: 0x5800
- Base Offset: 0x5800
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

- Absolute Address: 0x5800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x5808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x5810
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

- Absolute Address: 0x5818
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

- Absolute Address: 0x5820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x5828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x5830
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

- Absolute Address: 0x5838
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

- Absolute Address: 0x5840
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

- Absolute Address: 0x5848
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

## outbound_mailbox_6 address map

- Absolute Address: 0x6000
- Base Offset: 0x6000
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

- Absolute Address: 0x6000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x6008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x6010
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

- Absolute Address: 0x6018
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

- Absolute Address: 0x6020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x6028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x6030
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

- Absolute Address: 0x6038
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

- Absolute Address: 0x6040
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

- Absolute Address: 0x6048
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

## inbound_mailbox_6 address map

- Absolute Address: 0x6800
- Base Offset: 0x6800
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

- Absolute Address: 0x6800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x6808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x6810
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

- Absolute Address: 0x6818
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

- Absolute Address: 0x6820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x6828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x6830
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

- Absolute Address: 0x6838
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

- Absolute Address: 0x6840
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

- Absolute Address: 0x6848
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

## outbound_mailbox_7 address map

- Absolute Address: 0x7000
- Base Offset: 0x7000
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

- Absolute Address: 0x7000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x7008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x7010
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

- Absolute Address: 0x7018
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

- Absolute Address: 0x7020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x7028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x7030
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

- Absolute Address: 0x7038
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

- Absolute Address: 0x7040
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

- Absolute Address: 0x7048
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

## inbound_mailbox_7 address map

- Absolute Address: 0x7800
- Base Offset: 0x7800
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

- Absolute Address: 0x7800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x7808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x7810
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

- Absolute Address: 0x7818
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

- Absolute Address: 0x7820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x7828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x7830
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

- Absolute Address: 0x7838
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

- Absolute Address: 0x7840
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

- Absolute Address: 0x7848
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
