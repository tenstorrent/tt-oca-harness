<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: axil_mailbox_smc_wrap
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/axil_mailbox/regs/axil_mailbox_smc_wrap.rdl
-->

## axil_mailbox_smc_wrap address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x1F850



| Offset|     Identifier    |Name|
|-------|-------------------|----|
|0x00000| outbound_mailbox_0|  — |
|0x00800| inbound_mailbox_0 |  — |
|0x01000| outbound_mailbox_1|  — |
|0x01800| inbound_mailbox_1 |  — |
|0x02000| outbound_mailbox_2|  — |
|0x02800| inbound_mailbox_2 |  — |
|0x03000| outbound_mailbox_3|  — |
|0x03800| inbound_mailbox_3 |  — |
|0x04000| outbound_mailbox_4|  — |
|0x04800| inbound_mailbox_4 |  — |
|0x05000| outbound_mailbox_5|  — |
|0x05800| inbound_mailbox_5 |  — |
|0x06000| outbound_mailbox_6|  — |
|0x06800| inbound_mailbox_6 |  — |
|0x07000| outbound_mailbox_7|  — |
|0x07800| inbound_mailbox_7 |  — |
|0x08000| outbound_mailbox_8|  — |
|0x08800| inbound_mailbox_8 |  — |
|0x09000| outbound_mailbox_9|  — |
|0x09800| inbound_mailbox_9 |  — |
|0x0A000|outbound_mailbox_10|  — |
|0x0A800| inbound_mailbox_10|  — |
|0x0B000|outbound_mailbox_11|  — |
|0x0B800| inbound_mailbox_11|  — |
|0x0C000|outbound_mailbox_12|  — |
|0x0C800| inbound_mailbox_12|  — |
|0x0D000|outbound_mailbox_13|  — |
|0x0D800| inbound_mailbox_13|  — |
|0x0E000|outbound_mailbox_14|  — |
|0x0E800| inbound_mailbox_14|  — |
|0x0F000|outbound_mailbox_15|  — |
|0x0F800| inbound_mailbox_15|  — |
|0x10000|outbound_mailbox_16|  — |
|0x10800| inbound_mailbox_16|  — |
|0x11000|outbound_mailbox_17|  — |
|0x11800| inbound_mailbox_17|  — |
|0x12000|outbound_mailbox_18|  — |
|0x12800| inbound_mailbox_18|  — |
|0x13000|outbound_mailbox_19|  — |
|0x13800| inbound_mailbox_19|  — |
|0x14000|outbound_mailbox_20|  — |
|0x14800| inbound_mailbox_20|  — |
|0x15000|outbound_mailbox_21|  — |
|0x15800| inbound_mailbox_21|  — |
|0x16000|outbound_mailbox_22|  — |
|0x16800| inbound_mailbox_22|  — |
|0x17000|outbound_mailbox_23|  — |
|0x17800| inbound_mailbox_23|  — |
|0x18000|outbound_mailbox_24|  — |
|0x18800| inbound_mailbox_24|  — |
|0x19000|outbound_mailbox_25|  — |
|0x19800| inbound_mailbox_25|  — |
|0x1A000|outbound_mailbox_26|  — |
|0x1A800| inbound_mailbox_26|  — |
|0x1B000|outbound_mailbox_27|  — |
|0x1B800| inbound_mailbox_27|  — |
|0x1C000|outbound_mailbox_28|  — |
|0x1C800| inbound_mailbox_28|  — |
|0x1D000|outbound_mailbox_29|  — |
|0x1D800| inbound_mailbox_29|  — |
|0x1E000|outbound_mailbox_30|  — |
|0x1E800| inbound_mailbox_30|  — |
|0x1F000|outbound_mailbox_31|  — |
|0x1F800| inbound_mailbox_31|  — |

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

## outbound_mailbox_8 address map

- Absolute Address: 0x8000
- Base Offset: 0x8000
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

- Absolute Address: 0x8000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x8008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x8010
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

- Absolute Address: 0x8018
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

- Absolute Address: 0x8020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x8028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x8030
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

- Absolute Address: 0x8038
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

- Absolute Address: 0x8040
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

- Absolute Address: 0x8048
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

## inbound_mailbox_8 address map

- Absolute Address: 0x8800
- Base Offset: 0x8800
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

- Absolute Address: 0x8800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x8808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x8810
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

- Absolute Address: 0x8818
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

- Absolute Address: 0x8820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x8828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x8830
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

- Absolute Address: 0x8838
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

- Absolute Address: 0x8840
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

- Absolute Address: 0x8848
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

## outbound_mailbox_9 address map

- Absolute Address: 0x9000
- Base Offset: 0x9000
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

- Absolute Address: 0x9000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x9008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x9010
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

- Absolute Address: 0x9018
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

- Absolute Address: 0x9020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x9028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x9030
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

- Absolute Address: 0x9038
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

- Absolute Address: 0x9040
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

- Absolute Address: 0x9048
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

## inbound_mailbox_9 address map

- Absolute Address: 0x9800
- Base Offset: 0x9800
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

- Absolute Address: 0x9800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x9808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x9810
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

- Absolute Address: 0x9818
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

- Absolute Address: 0x9820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x9828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x9830
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

- Absolute Address: 0x9838
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

- Absolute Address: 0x9840
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

- Absolute Address: 0x9848
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

## outbound_mailbox_10 address map

- Absolute Address: 0xA000
- Base Offset: 0xA000
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

- Absolute Address: 0xA000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xA008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xA010
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

- Absolute Address: 0xA018
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

- Absolute Address: 0xA020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xA028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xA030
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

- Absolute Address: 0xA038
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

- Absolute Address: 0xA040
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

- Absolute Address: 0xA048
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

## inbound_mailbox_10 address map

- Absolute Address: 0xA800
- Base Offset: 0xA800
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

- Absolute Address: 0xA800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xA808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xA810
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

- Absolute Address: 0xA818
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

- Absolute Address: 0xA820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xA828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xA830
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

- Absolute Address: 0xA838
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

- Absolute Address: 0xA840
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

- Absolute Address: 0xA848
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

## outbound_mailbox_11 address map

- Absolute Address: 0xB000
- Base Offset: 0xB000
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

- Absolute Address: 0xB000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xB008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xB010
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

- Absolute Address: 0xB018
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

- Absolute Address: 0xB020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xB028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xB030
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

- Absolute Address: 0xB038
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

- Absolute Address: 0xB040
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

- Absolute Address: 0xB048
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

## inbound_mailbox_11 address map

- Absolute Address: 0xB800
- Base Offset: 0xB800
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

- Absolute Address: 0xB800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xB808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xB810
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

- Absolute Address: 0xB818
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

- Absolute Address: 0xB820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xB828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xB830
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

- Absolute Address: 0xB838
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

- Absolute Address: 0xB840
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

- Absolute Address: 0xB848
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

## outbound_mailbox_12 address map

- Absolute Address: 0xC000
- Base Offset: 0xC000
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

- Absolute Address: 0xC000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xC008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xC010
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

- Absolute Address: 0xC018
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

- Absolute Address: 0xC020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xC028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xC030
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

- Absolute Address: 0xC038
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

- Absolute Address: 0xC040
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

- Absolute Address: 0xC048
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

## inbound_mailbox_12 address map

- Absolute Address: 0xC800
- Base Offset: 0xC800
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

- Absolute Address: 0xC800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xC808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xC810
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

- Absolute Address: 0xC818
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

- Absolute Address: 0xC820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xC828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xC830
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

- Absolute Address: 0xC838
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

- Absolute Address: 0xC840
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

- Absolute Address: 0xC848
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

## outbound_mailbox_13 address map

- Absolute Address: 0xD000
- Base Offset: 0xD000
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

- Absolute Address: 0xD000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xD008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xD010
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

- Absolute Address: 0xD018
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

- Absolute Address: 0xD020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xD028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xD030
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

- Absolute Address: 0xD038
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

- Absolute Address: 0xD040
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

- Absolute Address: 0xD048
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

## inbound_mailbox_13 address map

- Absolute Address: 0xD800
- Base Offset: 0xD800
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

- Absolute Address: 0xD800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xD808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xD810
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

- Absolute Address: 0xD818
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

- Absolute Address: 0xD820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xD828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xD830
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

- Absolute Address: 0xD838
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

- Absolute Address: 0xD840
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

- Absolute Address: 0xD848
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

## outbound_mailbox_14 address map

- Absolute Address: 0xE000
- Base Offset: 0xE000
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

- Absolute Address: 0xE000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xE008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xE010
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

- Absolute Address: 0xE018
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

- Absolute Address: 0xE020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xE028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xE030
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

- Absolute Address: 0xE038
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

- Absolute Address: 0xE040
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

- Absolute Address: 0xE048
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

## inbound_mailbox_14 address map

- Absolute Address: 0xE800
- Base Offset: 0xE800
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

- Absolute Address: 0xE800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xE808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xE810
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

- Absolute Address: 0xE818
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

- Absolute Address: 0xE820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xE828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xE830
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

- Absolute Address: 0xE838
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

- Absolute Address: 0xE840
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

- Absolute Address: 0xE848
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

## outbound_mailbox_15 address map

- Absolute Address: 0xF000
- Base Offset: 0xF000
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

- Absolute Address: 0xF000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xF008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xF010
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

- Absolute Address: 0xF018
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

- Absolute Address: 0xF020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xF028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xF030
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

- Absolute Address: 0xF038
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

- Absolute Address: 0xF040
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

- Absolute Address: 0xF048
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

## inbound_mailbox_15 address map

- Absolute Address: 0xF800
- Base Offset: 0xF800
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

- Absolute Address: 0xF800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0xF808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0xF810
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

- Absolute Address: 0xF818
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

- Absolute Address: 0xF820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0xF828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0xF830
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

- Absolute Address: 0xF838
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

- Absolute Address: 0xF840
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

- Absolute Address: 0xF848
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

## outbound_mailbox_16 address map

- Absolute Address: 0x10000
- Base Offset: 0x10000
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

- Absolute Address: 0x10000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x10008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x10010
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

- Absolute Address: 0x10018
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

- Absolute Address: 0x10020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x10028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x10030
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

- Absolute Address: 0x10038
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

- Absolute Address: 0x10040
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

- Absolute Address: 0x10048
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

## inbound_mailbox_16 address map

- Absolute Address: 0x10800
- Base Offset: 0x10800
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

- Absolute Address: 0x10800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x10808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x10810
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

- Absolute Address: 0x10818
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

- Absolute Address: 0x10820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x10828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x10830
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

- Absolute Address: 0x10838
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

- Absolute Address: 0x10840
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

- Absolute Address: 0x10848
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

## outbound_mailbox_17 address map

- Absolute Address: 0x11000
- Base Offset: 0x11000
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

- Absolute Address: 0x11000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x11008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x11010
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

- Absolute Address: 0x11018
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

- Absolute Address: 0x11020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x11028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x11030
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

- Absolute Address: 0x11038
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

- Absolute Address: 0x11040
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

- Absolute Address: 0x11048
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

## inbound_mailbox_17 address map

- Absolute Address: 0x11800
- Base Offset: 0x11800
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

- Absolute Address: 0x11800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x11808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x11810
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

- Absolute Address: 0x11818
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

- Absolute Address: 0x11820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x11828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x11830
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

- Absolute Address: 0x11838
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

- Absolute Address: 0x11840
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

- Absolute Address: 0x11848
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

## outbound_mailbox_18 address map

- Absolute Address: 0x12000
- Base Offset: 0x12000
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

- Absolute Address: 0x12000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x12008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x12010
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

- Absolute Address: 0x12018
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

- Absolute Address: 0x12020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x12028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x12030
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

- Absolute Address: 0x12038
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

- Absolute Address: 0x12040
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

- Absolute Address: 0x12048
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

## inbound_mailbox_18 address map

- Absolute Address: 0x12800
- Base Offset: 0x12800
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

- Absolute Address: 0x12800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x12808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x12810
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

- Absolute Address: 0x12818
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

- Absolute Address: 0x12820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x12828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x12830
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

- Absolute Address: 0x12838
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

- Absolute Address: 0x12840
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

- Absolute Address: 0x12848
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

## outbound_mailbox_19 address map

- Absolute Address: 0x13000
- Base Offset: 0x13000
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

- Absolute Address: 0x13000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x13008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x13010
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

- Absolute Address: 0x13018
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

- Absolute Address: 0x13020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x13028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x13030
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

- Absolute Address: 0x13038
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

- Absolute Address: 0x13040
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

- Absolute Address: 0x13048
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

## inbound_mailbox_19 address map

- Absolute Address: 0x13800
- Base Offset: 0x13800
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

- Absolute Address: 0x13800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x13808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x13810
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

- Absolute Address: 0x13818
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

- Absolute Address: 0x13820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x13828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x13830
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

- Absolute Address: 0x13838
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

- Absolute Address: 0x13840
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

- Absolute Address: 0x13848
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

## outbound_mailbox_20 address map

- Absolute Address: 0x14000
- Base Offset: 0x14000
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

- Absolute Address: 0x14000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x14008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x14010
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

- Absolute Address: 0x14018
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

- Absolute Address: 0x14020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x14028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x14030
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

- Absolute Address: 0x14038
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

- Absolute Address: 0x14040
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

- Absolute Address: 0x14048
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

## inbound_mailbox_20 address map

- Absolute Address: 0x14800
- Base Offset: 0x14800
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

- Absolute Address: 0x14800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x14808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x14810
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

- Absolute Address: 0x14818
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

- Absolute Address: 0x14820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x14828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x14830
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

- Absolute Address: 0x14838
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

- Absolute Address: 0x14840
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

- Absolute Address: 0x14848
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

## outbound_mailbox_21 address map

- Absolute Address: 0x15000
- Base Offset: 0x15000
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

- Absolute Address: 0x15000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x15008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x15010
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

- Absolute Address: 0x15018
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

- Absolute Address: 0x15020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x15028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x15030
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

- Absolute Address: 0x15038
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

- Absolute Address: 0x15040
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

- Absolute Address: 0x15048
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

## inbound_mailbox_21 address map

- Absolute Address: 0x15800
- Base Offset: 0x15800
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

- Absolute Address: 0x15800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x15808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x15810
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

- Absolute Address: 0x15818
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

- Absolute Address: 0x15820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x15828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x15830
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

- Absolute Address: 0x15838
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

- Absolute Address: 0x15840
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

- Absolute Address: 0x15848
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

## outbound_mailbox_22 address map

- Absolute Address: 0x16000
- Base Offset: 0x16000
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

- Absolute Address: 0x16000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x16008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x16010
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

- Absolute Address: 0x16018
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

- Absolute Address: 0x16020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x16028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x16030
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

- Absolute Address: 0x16038
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

- Absolute Address: 0x16040
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

- Absolute Address: 0x16048
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

## inbound_mailbox_22 address map

- Absolute Address: 0x16800
- Base Offset: 0x16800
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

- Absolute Address: 0x16800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x16808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x16810
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

- Absolute Address: 0x16818
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

- Absolute Address: 0x16820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x16828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x16830
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

- Absolute Address: 0x16838
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

- Absolute Address: 0x16840
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

- Absolute Address: 0x16848
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

## outbound_mailbox_23 address map

- Absolute Address: 0x17000
- Base Offset: 0x17000
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

- Absolute Address: 0x17000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x17008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x17010
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

- Absolute Address: 0x17018
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

- Absolute Address: 0x17020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x17028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x17030
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

- Absolute Address: 0x17038
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

- Absolute Address: 0x17040
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

- Absolute Address: 0x17048
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

## inbound_mailbox_23 address map

- Absolute Address: 0x17800
- Base Offset: 0x17800
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

- Absolute Address: 0x17800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x17808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x17810
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

- Absolute Address: 0x17818
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

- Absolute Address: 0x17820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x17828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x17830
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

- Absolute Address: 0x17838
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

- Absolute Address: 0x17840
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

- Absolute Address: 0x17848
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

## outbound_mailbox_24 address map

- Absolute Address: 0x18000
- Base Offset: 0x18000
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

- Absolute Address: 0x18000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x18008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x18010
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

- Absolute Address: 0x18018
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

- Absolute Address: 0x18020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x18028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x18030
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

- Absolute Address: 0x18038
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

- Absolute Address: 0x18040
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

- Absolute Address: 0x18048
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

## inbound_mailbox_24 address map

- Absolute Address: 0x18800
- Base Offset: 0x18800
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

- Absolute Address: 0x18800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x18808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x18810
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

- Absolute Address: 0x18818
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

- Absolute Address: 0x18820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x18828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x18830
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

- Absolute Address: 0x18838
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

- Absolute Address: 0x18840
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

- Absolute Address: 0x18848
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

## outbound_mailbox_25 address map

- Absolute Address: 0x19000
- Base Offset: 0x19000
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

- Absolute Address: 0x19000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x19008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x19010
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

- Absolute Address: 0x19018
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

- Absolute Address: 0x19020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x19028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x19030
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

- Absolute Address: 0x19038
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

- Absolute Address: 0x19040
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

- Absolute Address: 0x19048
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

## inbound_mailbox_25 address map

- Absolute Address: 0x19800
- Base Offset: 0x19800
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

- Absolute Address: 0x19800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x19808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x19810
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

- Absolute Address: 0x19818
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

- Absolute Address: 0x19820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x19828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x19830
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

- Absolute Address: 0x19838
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

- Absolute Address: 0x19840
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

- Absolute Address: 0x19848
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

## outbound_mailbox_26 address map

- Absolute Address: 0x1A000
- Base Offset: 0x1A000
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

- Absolute Address: 0x1A000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1A008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1A010
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

- Absolute Address: 0x1A018
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

- Absolute Address: 0x1A020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1A028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1A030
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

- Absolute Address: 0x1A038
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

- Absolute Address: 0x1A040
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

- Absolute Address: 0x1A048
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

## inbound_mailbox_26 address map

- Absolute Address: 0x1A800
- Base Offset: 0x1A800
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

- Absolute Address: 0x1A800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1A808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1A810
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

- Absolute Address: 0x1A818
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

- Absolute Address: 0x1A820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1A828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1A830
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

- Absolute Address: 0x1A838
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

- Absolute Address: 0x1A840
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

- Absolute Address: 0x1A848
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

## outbound_mailbox_27 address map

- Absolute Address: 0x1B000
- Base Offset: 0x1B000
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

- Absolute Address: 0x1B000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1B008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1B010
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

- Absolute Address: 0x1B018
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

- Absolute Address: 0x1B020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1B028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1B030
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

- Absolute Address: 0x1B038
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

- Absolute Address: 0x1B040
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

- Absolute Address: 0x1B048
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

## inbound_mailbox_27 address map

- Absolute Address: 0x1B800
- Base Offset: 0x1B800
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

- Absolute Address: 0x1B800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1B808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1B810
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

- Absolute Address: 0x1B818
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

- Absolute Address: 0x1B820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1B828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1B830
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

- Absolute Address: 0x1B838
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

- Absolute Address: 0x1B840
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

- Absolute Address: 0x1B848
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

## outbound_mailbox_28 address map

- Absolute Address: 0x1C000
- Base Offset: 0x1C000
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

- Absolute Address: 0x1C000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1C008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1C010
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

- Absolute Address: 0x1C018
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

- Absolute Address: 0x1C020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1C028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1C030
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

- Absolute Address: 0x1C038
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

- Absolute Address: 0x1C040
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

- Absolute Address: 0x1C048
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

## inbound_mailbox_28 address map

- Absolute Address: 0x1C800
- Base Offset: 0x1C800
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

- Absolute Address: 0x1C800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1C808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1C810
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

- Absolute Address: 0x1C818
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

- Absolute Address: 0x1C820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1C828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1C830
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

- Absolute Address: 0x1C838
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

- Absolute Address: 0x1C840
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

- Absolute Address: 0x1C848
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

## outbound_mailbox_29 address map

- Absolute Address: 0x1D000
- Base Offset: 0x1D000
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

- Absolute Address: 0x1D000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1D008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1D010
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

- Absolute Address: 0x1D018
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

- Absolute Address: 0x1D020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1D028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1D030
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

- Absolute Address: 0x1D038
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

- Absolute Address: 0x1D040
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

- Absolute Address: 0x1D048
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

## inbound_mailbox_29 address map

- Absolute Address: 0x1D800
- Base Offset: 0x1D800
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

- Absolute Address: 0x1D800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1D808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1D810
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

- Absolute Address: 0x1D818
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

- Absolute Address: 0x1D820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1D828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1D830
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

- Absolute Address: 0x1D838
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

- Absolute Address: 0x1D840
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

- Absolute Address: 0x1D848
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

## outbound_mailbox_30 address map

- Absolute Address: 0x1E000
- Base Offset: 0x1E000
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

- Absolute Address: 0x1E000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1E008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1E010
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

- Absolute Address: 0x1E018
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

- Absolute Address: 0x1E020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1E028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1E030
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

- Absolute Address: 0x1E038
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

- Absolute Address: 0x1E040
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

- Absolute Address: 0x1E048
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

## inbound_mailbox_30 address map

- Absolute Address: 0x1E800
- Base Offset: 0x1E800
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

- Absolute Address: 0x1E800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1E808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1E810
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

- Absolute Address: 0x1E818
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

- Absolute Address: 0x1E820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1E828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1E830
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

- Absolute Address: 0x1E838
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

- Absolute Address: 0x1E840
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

- Absolute Address: 0x1E848
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

## outbound_mailbox_31 address map

- Absolute Address: 0x1F000
- Base Offset: 0x1F000
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

- Absolute Address: 0x1F000
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1F008
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1F010
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

- Absolute Address: 0x1F018
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

- Absolute Address: 0x1F020
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1F028
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1F030
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

- Absolute Address: 0x1F038
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

- Absolute Address: 0x1F040
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

- Absolute Address: 0x1F048
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

## inbound_mailbox_31 address map

- Absolute Address: 0x1F800
- Base Offset: 0x1F800
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

- Absolute Address: 0x1F800
- Base Offset: 0x0
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0|write_data|   w  | 0x0 |  — |

#### write_data field

<p>Write data to mailbox fifo</p>

### READ_DATA register

- Absolute Address: 0x1F808
- Base Offset: 0x8
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|63:0| read_data|   r  | 0x0 |  — |

#### read_data field

<p>Read data from mailbox fifo</p>

### STATUS register

- Absolute Address: 0x1F810
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

- Absolute Address: 0x1F818
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

- Absolute Address: 0x1F820
- Base Offset: 0x20
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   wirqt  |  rw  | 0x0 |  — |

#### wirqt field

<p>When the usage pointer of the FIFO connected to the W channel exceeds this value, a write threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the write FIFO is full.</p>

### RIRQT register

- Absolute Address: 0x1F828
- Base Offset: 0x28
- Size: 0x8

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 7:0|   rirqt  |  rw  | 0x0 |  — |

#### rirqt field

<p>When the fill pointer of the FIFO connected to the R channel exceeds this value, a read threshold IRQ is triggered and the corresponding STATUS register bit is set. When a value larger than or equal to the MailboxDepth parameter is written to this register, it gets reduced to MailboxDepth - 1 to ensure an IRQ is triggered when the read FIFO is full.</p>

### IRQS register

- Absolute Address: 0x1F830
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

- Absolute Address: 0x1F838
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

- Absolute Address: 0x1F840
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

- Absolute Address: 0x1F848
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
