<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: edn
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/edn/regs/edn.rdl
-->

## edn address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x48

<p>Distributes random numbers produced by CSRNG to hardware blocks</p>

|Offset|         Identifier         |Name|
|------|----------------------------|----|
| 0x00 |         INTR_STATE         |  — |
| 0x04 |         INTR_ENABLE        |  — |
| 0x08 |          INTR_TEST         |  — |
| 0x0C |         ALERT_TEST         |  — |
| 0x10 |           REGWEN           |  — |
| 0x14 |            CTRL            |  — |
| 0x18 |        BOOT_INS_CMD        |  — |
| 0x1C |        BOOT_GEN_CMD        |  — |
| 0x20 |         SW_CMD_REQ         |  — |
| 0x24 |         SW_CMD_STS         |  — |
| 0x28 |         HW_CMD_STS         |  — |
| 0x2C |         RESEED_CMD         |  — |
| 0x30 |        GENERATE_CMD        |  — |
| 0x34 |MAX_NUM_REQS_BETWEEN_RESEEDS|  — |
| 0x38 |       RECOV_ALERT_STS      |  — |
| 0x3C |          ERR_CODE          |  — |
| 0x40 |        ERR_CODE_TEST       |  — |
| 0x44 |        MAIN_SM_STATE       |  — |

### INTR_STATE register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

|Bits|   Identifier   |  Access |Reset|Name|
|----|----------------|---------|-----|----|
|  0 |edn_cmd_req_done|rw, woclr| 0x0 |  — |
|  1 |  edn_fatal_err |rw, woclr| 0x0 |  — |

#### edn_cmd_req_done field

<p>Asserted when a software CSRNG request has completed.</p>

#### edn_fatal_err field

<p>Asserted when a FIFO error occurs.</p>

### INTR_ENABLE register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|  0 |edn_cmd_req_done|  rw  | 0x0 |  — |
|  1 |  edn_fatal_err |  rw  | 0x0 |  — |

#### edn_cmd_req_done field

<p>Enable interrupt when !!INTR_STATE.edn_cmd_req_done is set.</p>

#### edn_fatal_err field

<p>Enable interrupt when !!INTR_STATE.edn_fatal_err is set.</p>

### INTR_TEST register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|  0 |edn_cmd_req_done|   w  | 0x0 |  — |
|  1 |  edn_fatal_err |   w  | 0x0 |  — |

#### edn_cmd_req_done field

<p>Write 1 to force !!INTR_STATE.edn_cmd_req_done to 1.</p>

#### edn_fatal_err field

<p>Write 1 to force !!INTR_STATE.edn_fatal_err to 1.</p>

### ALERT_TEST register

- Absolute Address: 0xC
- Base Offset: 0xC
- Size: 0x4

|Bits| Identifier|Access|Reset|Name|
|----|-----------|------|-----|----|
|  0 |recov_alert|   w  | 0x0 |  — |
|  1 |fatal_alert|   w  | 0x0 |  — |

#### recov_alert field

<p>Write 1 to trigger one alert event of this kind.</p>

#### fatal_alert field

<p>Write 1 to trigger one alert event of this kind.</p>

### REGWEN register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

|Bits|Identifier| Access|Reset|Name|
|----|----------|-------|-----|----|
|  0 |  REGWEN  |rw, wzc| 0x1 |  — |

#### REGWEN field

<p>When true, the CTRL can be written by software.
When false, this field read-only. Defaults true, write zero to clear.
Note that this needs to be cleared after initial configuration at boot in order to
lock in the listed register settings.</p>

### CTRL register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

| Bits|  Identifier |Access|Reset|Name|
|-----|-------------|------|-----|----|
| 3:0 |  EDN_ENABLE |  rw  | 0x9 |  — |
| 7:4 |BOOT_REQ_MODE|  rw  | 0x9 |  — |
| 11:8|AUTO_REQ_MODE|  rw  | 0x9 |  — |
|15:12| CMD_FIFO_RST|  rw  | 0x9 |  — |

#### EDN_ENABLE field

<p>Setting this field to kMultiBitBool4True enables the EDN module. The modules of the
entropy complex may only be enabled and disabled in a specific order, see
Programmers Guide for details.</p>

#### BOOT_REQ_MODE field

<p>Setting this field to kMultiBitBool4True enables the boot-time request mode.
In this mode, EDN automatically sends a boot-time request to the CSRNG application interface.
The purpose of this mode is to request entropy as fast as possible after reset, and during chip boot time.</p>
<p>Note that this takes precedence over the AUTO_REQ_MODE field: If both fields are set, EDN enters boot-time request mode.
If none of the fields are set, EDN enters Software Port Mode upon enabling.</p>

#### AUTO_REQ_MODE field

<p>Setting this field to kMultiBitBool4True enables auto request mode.
In this mode, EDN automatically sends <code>generate</code> and <code>reseed</code> command requests to the CSRNG application interface.
The purpose of this mode is to continuously deliver entropy to endpoints without firmware intervention.</p>
<p>For this to work, firmware has to 1) configure the !!GENERATE_CMD, !!RESEED_CMD, and !!MAX_NUM_REQS_BETWEEN_RESEEDS registers, and 2) to issue the first <code>instantiate</code> command via the !!SW_CMD_REQ register.
Once this command has been acknowledged by CSRNG, the first <code>generate</code> command is sent out automatically, and a <code>reseed</code> command is sent after every MAX_NUM_REQS_BETWEEN_RESEEDS number of <code>generate</code> commands.</p>
<p>Note that the BOOT_REQ_MODE field takes precedence over this field: If both fields are set, EDN enters boot-time request mode.
If none of the fields are set, EDN enters Software Port Mode upon enabling.</p>

#### CMD_FIFO_RST field

<p>Setting this field to kMultiBitBool4True clears the two command FIFOs: the
RESEED_CMD FIFO and the GENERATE_CMD FIFO. This field must be
set to the reset state by software before any further commands can be issued to
these FIFOs.</p>

### BOOT_INS_CMD register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
|31:0|BOOT_INS_CMD|  rw  |0x901|  — |

#### BOOT_INS_CMD field

<p>This field is used as the value for the <code>instantiate</code> command at boot time.</p>
<p>See <a href="../../csrng/doc/theory_of_operation.md#command-header">Command Header</a> for the meaning of the individual bits.
Note that the hardware only supports a value of 0 for the <code>clen</code> field.
If <code>clen</code> has a different value, EDN will hang.
Fixing this requires disabling and restarting both EDN and CSRNG.</p>

### BOOT_GEN_CMD register

- Absolute Address: 0x1C
- Base Offset: 0x1C
- Size: 0x4

|Bits| Identifier |Access|  Reset |Name|
|----|------------|------|--------|----|
|31:0|BOOT_GEN_CMD|  rw  |0xFFF003|  — |

#### BOOT_GEN_CMD field

<p>This field is used as the value for the <code>generate</code> command at boot time.</p>
<p>See <a href="../../csrng/doc/theory_of_operation.md#command-header">Command Header</a> for the meaning of the individual bits.
Note that the hardware only supports a value of 0 for the <code>clen</code> field.
If <code>clen</code> has a different value, EDN will hang.
Fixing this requires disabling and restarting both EDN and CSRNG.</p>

### SW_CMD_REQ register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|SW_CMD_REQ|   w  |  —  |  — |

#### SW_CMD_REQ field

<p>Any CSRNG action can be initiated by writing a CSRNG command to this register.
Before any write operation to this register, firmware must read !!SW_CMD_STS to check whether EDN is ready to receive a new command or the next word of a previously started command.</p>
<p>While !!CTRL.AUTO_REQ_MODE is set, only the first instantiate command has any effect.
After that command has been processed, writes to this register will have no effect on operation, until !!CTRL.AUTO_REQ_MODE is de-asserted and the state machine of EDN enters the <code>SwPortMode</code> state.</p>
<p>Refer to the <a href="../../csrng/doc/theory_of_operation.md#general-command-format">CSRNG documentation</a> for details on the command format.</p>

### SW_CMD_STS register

- Absolute Address: 0x24
- Base Offset: 0x24
- Size: 0x4

|Bits| Identifier|Access|Reset|Name|
|----|-----------|------|-----|----|
|  0 |CMD_REG_RDY|   r  | 0x0 |  — |
|  1 |  CMD_RDY  |   r  | 0x0 |  — |
|  2 |  CMD_ACK  |   r  | 0x0 |  — |
| 5:3|  CMD_STS  |   r  | 0x0 |  — |

#### CMD_REG_RDY field

<p>This bit indicates when !!SW_CMD_REQ is ready to accept the next word.
This bit has to be polled before each word of a command is written to !!SW_CMD_REQ.
0b0: The EDN is not ready to accept the next word yet.
0b1: The EDN is ready to accept the next word.</p>

#### CMD_RDY field

<p>This bit indicates when the EDN is ready to accept the next command.
Before starting to write a new command to !!SW_CMD_REQ, this field needs to be polled.
0b0: The EDN is not ready to accept commands or the last command hasn't been acked yet.
0b1: The EDN is ready to accept the next command.</p>

#### CMD_ACK field

<p>This one bit field indicates when a SW command has been acknowledged by the CSRNG.
It is set to low each time a new command is written to !!SW_CMD_REQ.
The field is set to high once a SW command request has been acknowledged by the CSRNG.
0b0: The last SW command has not been acknowledged yet.
0b1: The last SW command has been acknowledged.</p>

#### CMD_STS field

<p>This field represents the status code returned with the CSRNG application command ack.
It is updated each time a SW command is acknowledged by CSRNG.
To check whether a command was successful, wait for !!INTR_STATE.EDN_CMD_REQ_DONE or
!!SW_CMD_STS.CMD_ACK to be high and then check the value of this field.
A description of the command status types can be found <a href="../../csrng/doc/registers.md#sw_cmd_sts--cmd_sts">here</a>.</p>

### HW_CMD_STS register

- Absolute Address: 0x28
- Base Offset: 0x28
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  0 | BOOT_MODE|   r  | 0x0 |  — |
|  1 | AUTO_MODE|   r  | 0x0 |  — |
| 5:2| CMD_TYPE |   r  | 0x0 |  — |
|  6 |  CMD_ACK |   r  | 0x0 |  — |
| 9:7|  CMD_STS |   r  | 0x0 |  — |

#### BOOT_MODE field

<p>This one bit field indicates whether the EDN is in the hardware controlled boot mode.
0b0: The EDN is not in boot mode.
0b1: The EDN is in boot mode.</p>

#### AUTO_MODE field

<p>This one bit field indicates whether the EDN is in the hardware controlled part of auto mode.
The instantiate command is issued via SW interface and is thus not part of the hardware controlled part of auto mode.
0b0: The EDN is not in the hardware controlled part of auto mode.
0b1: The EDN is in the hardware controlled part of auto mode.</p>

#### CMD_TYPE field

<p>This field contains the application command type of the hardware controlled command issued last.
The application command selects one of five operations to perform.
A description of the application command types can be found <a href="../../csrng/doc/theory_of_operation.md#command-description">here</a>.</p>

#### CMD_ACK field

<p>This one bit field indicates when a HW command has been acknowledged by the CSRNG.
It is set to low each time a new command is sent to the CSRNG.
The field is set to high once a HW command request has been acknowledged by the CSRNG.
0b0: The last HW command has not been acknowledged yet.
0b1: The last HW command has been acknowledged.</p>

#### CMD_STS field

<p>This field represents the status code returned with the CSRNG application command ack.
It is updated each time a HW command is acknowledged by CSRNG.
A description of the command status types can be found <a href="../../csrng/doc/registers.md#sw_cmd_sts--cmd_sts">here</a>.</p>

### RESEED_CMD register

- Absolute Address: 0x2C
- Base Offset: 0x2C
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|RESEED_CMD|   w  |  —  |  — |

#### RESEED_CMD field

<p>Writing this register will fill a FIFO with up to 13 command words (32b words).
When running in auto request mode, this FIFO is used to automatically send out a <code>reseed</code> command to the CSRNG application interface after every MAX_NUM_REQS_BETWEEN_RESEEDS number of <code>generate</code> commands.</p>
<p>See <a href="../../csrng/doc/theory_of_operation.md#general-command-format">General Command Format</a> for details about the command format.</p>
<p>Note that the number of additional data words provided must match the value of the <code>clen</code> field of the first word.
Otherwise, undefined behavior may result.
If more than 13 entries are written to the FIFO, they are ignored and EDN signals an <code>edn_fatal_err</code> interrupt as well as a fatal alert.</p>

### GENERATE_CMD register

- Absolute Address: 0x30
- Base Offset: 0x30
- Size: 0x4

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
|31:0|GENERATE_CMD|   w  |  —  |  — |

#### GENERATE_CMD field

<p>Writing this register will fill a FIFO with up to 13 command words (32b words).
When running auto request mode, this FIFO is used to automatically send out <code>generate</code> commands to the CSRNG
application interface.</p>
<p>See <a href="../../csrng/doc/theory_of_operation.md#general-command-format">General Command Format</a> for details about the command format.</p>
<p>Note that the number of additional data words provided must match the value of the <code>clen</code> field of the first word.
Otherwise, undefined behavior may result.
If more than 13 entries are written to the FIFO, they are ignored and EDN signals an <code>edn_fatal_err</code> interrupt as well as a fatal alert.</p>

### MAX_NUM_REQS_BETWEEN_RESEEDS register

- Absolute Address: 0x34
- Base Offset: 0x34
- Size: 0x4

|Bits|         Identifier         |Access|Reset|Name|
|----|----------------------------|------|-----|----|
|31:0|MAX_NUM_REQS_BETWEEN_RESEEDS|  rw  | 0x0 |  — |

#### MAX_NUM_REQS_BETWEEN_RESEEDS field

<p>Setting this field will set the number of <code>generate</code> command requests that are made
to CSRNG before a reseed request is made.
This value only has meaning when running in auto request mode.
This register supports a maximum of 2^32 <code>generate</code> requests between reseeds.
This register will be used by a counter that counts down, triggering an automatic <code>reseed</code> request when it reaches zero.</p>
<p>Note that this value must be chosen smaller than or equal to the value configured in the <a href="../../csrng/doc/registers.md#reseed-interval"><code>RESEED_INTERVAL</code> register of CSRNG</a>.</p>

### RECOV_ALERT_STS register

- Absolute Address: 0x38
- Base Offset: 0x38
- Size: 0x4

|Bits|        Identifier       | Access|Reset|Name|
|----|-------------------------|-------|-----|----|
|  0 |  EDN_ENABLE_FIELD_ALERT |rw, wzc| 0x0 |  — |
|  1 |BOOT_REQ_MODE_FIELD_ALERT|rw, wzc| 0x0 |  — |
|  2 |AUTO_REQ_MODE_FIELD_ALERT|rw, wzc| 0x0 |  — |
|  3 | CMD_FIFO_RST_FIELD_ALERT|rw, wzc| 0x0 |  — |
| 12 |    EDN_BUS_CMP_ALERT    |rw, wzc| 0x0 |  — |
| 13 |      CSRNG_ACK_ERR      |rw, wzc| 0x0 |  — |

#### EDN_ENABLE_FIELD_ALERT field

<p>This bit is set when the EDN_ENABLE field is set to an illegal value,
something other than kMultiBitBool4True or kMultiBitBool4False.
Writing a zero resets this status bit.</p>

#### BOOT_REQ_MODE_FIELD_ALERT field

<p>This bit is set when the BOOT_REQ_MODE field is set to an illegal value,
something other than kMultiBitBool4True or kMultiBitBool4False.
Writing a zero resets this status bit.</p>

#### AUTO_REQ_MODE_FIELD_ALERT field

<p>This bit is set when the !!CTRL.AUTO_REQ_MODE field is set to an illegal value,
something other than kMultiBitBool4True or kMultiBitBool4False.
Writing a zero resets this status bit.</p>

#### CMD_FIFO_RST_FIELD_ALERT field

<p>This bit is set when the CMD_FIFO_RST field is set to an illegal value,
something other than kMultiBitBool4True or kMultiBitBool4False.
Writing a zero resets this status bit.</p>

#### EDN_BUS_CMP_ALERT field

<p>This bit is set when the interal entropy bus value is equal to the prior
valid value on the bus, indicating a possible attack.
Writing a zero resets this status bit.</p>

#### CSRNG_ACK_ERR field

<p>This bit is set when the CSRNG returns an acknowledgement where the status signal is non-zero.
Writing a zero resets this status bit.</p>

### ERR_CODE register

- Absolute Address: 0x3C
- Base Offset: 0x3C
- Size: 0x4

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|  0 |SFIFO_RESCMD_ERR|   r  | 0x0 |  — |
|  1 |SFIFO_GENCMD_ERR|   r  | 0x0 |  — |
| 20 | EDN_ACK_SM_ERR |   r  | 0x0 |  — |
| 21 | EDN_MAIN_SM_ERR|   r  | 0x0 |  — |
| 22 |  EDN_CNTR_ERR  |   r  | 0x0 |  — |
| 28 | FIFO_WRITE_ERR |   r  | 0x0 |  — |
| 29 |  FIFO_READ_ERR |   r  | 0x0 |  — |
| 30 | FIFO_STATE_ERR |   r  | 0x0 |  — |

#### SFIFO_RESCMD_ERR field

<p>This bit will be set to one when an error has been detected for the
reseed command FIFO. The type of error is reflected in the type status
bits (bits 28 through 30 of this register).
When this bit is set, a fatal error condition will result.</p>

#### SFIFO_GENCMD_ERR field

<p>This bit will be set to one when an error has been detected for the
generate command FIFO. The type of error is reflected in the type status
bits (bits 28 through 30 of this register).
When this bit is set, a fatal error condition will result.
This bit will stay set until the next reset.</p>

#### EDN_ACK_SM_ERR field

<p>This bit will be set to one when an illegal state has been detected for the
EDN ack stage state machine. This error will signal a fatal alert.
This bit will stay set until the next reset.</p>

#### EDN_MAIN_SM_ERR field

<p>This bit will be set to one when an illegal state has been detected for the
EDN main stage state machine. This error will signal a fatal alert.
This bit will stay set until the next reset.</p>

#### EDN_CNTR_ERR field

<p>This bit will be set to one when a hardened counter has detected an error
condition. This error will signal a fatal alert.
This bit will stay set until the next reset.</p>

#### FIFO_WRITE_ERR field

<p>This bit will be set to one when any of the source bits (bits 0 through 1 of this register) are asserted as a result of an error pulse generated from any full FIFO that has received a write pulse.
This bit will stay set until the next reset.</p>

#### FIFO_READ_ERR field

<p>This bit will be set to one when any of the source bits (bits 0 through 1 of this register) are asserted as a result of an error pulse generated from any empty FIFO that has received a read pulse.
This bit will stay set until the next reset.</p>

#### FIFO_STATE_ERR field

<p>This bit will be set to one when any of the source bits (bits 0 through 1 of this register) are asserted as a result of an error pulse generated from any FIFO where both the empty and full status bits are set or in case of error conditions inside the hardened counters.
This bit will stay set until the next reset.</p>

### ERR_CODE_TEST register

- Absolute Address: 0x40
- Base Offset: 0x40
- Size: 0x4

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
| 4:0|ERR_CODE_TEST|  rw  | 0x0 |  — |

#### ERR_CODE_TEST field

<p>Setting this field will set the bit number for which an error
will be forced in the hardware. This bit number is that same one
found in the !!ERR_CODE register. The action of writing this
register will force an error pulse. The sole purpose of this
register is to test that any error properly propagates to either
an interrupt or an alert.</p>

### MAIN_SM_STATE register

- Absolute Address: 0x44
- Base Offset: 0x44
- Size: 0x4

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
| 8:0|MAIN_SM_STATE|   r  | 0xC1|  — |

#### MAIN_SM_STATE field

<p>This is the state of the EDN main state machine.
See the RTL file <code>edn_main_sm</code> for the meaning of the values.</p>
