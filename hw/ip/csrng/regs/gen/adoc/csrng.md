<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: csrng
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/csrng/regs/csrng.rdl
-->

## csrng address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x60

<p>Takes entropy bits to produce cryptographically secure random numbers for consumption by hardware blocks and by software</p>

|Offset|         Identifier         |Name|
|------|----------------------------|----|
| 0x00 |         INTR_STATE         |  — |
| 0x04 |         INTR_ENABLE        |  — |
| 0x08 |          INTR_TEST         |  — |
| 0x0C |         ALERT_TEST         |  — |
| 0x10 |           REGWEN           |  — |
| 0x14 |            CTRL            |  — |
| 0x18 |           CMD_REQ          |  — |
| 0x1C |       RESEED_INTERVAL      |  — |
| 0x20 |      RESEED_COUNTER[0]     |  — |
| 0x24 |      RESEED_COUNTER[1]     |  — |
| 0x28 |      RESEED_COUNTER[2]     |  — |
| 0x2C |         SW_CMD_STS         |  — |
| 0x30 |         GENBITS_VLD        |  — |
| 0x34 |           GENBITS          |  — |
| 0x38 |    INT_STATE_READ_ENABLE   |  — |
| 0x3C |INT_STATE_READ_ENABLE_REGWEN|  — |
| 0x40 |        INT_STATE_NUM       |  — |
| 0x44 |        INT_STATE_VAL       |  — |
| 0x48 |         FIPS_FORCE         |  — |
| 0x4C |         HW_EXC_STS         |  — |
| 0x50 |       RECOV_ALERT_STS      |  — |
| 0x54 |          ERR_CODE          |  — |
| 0x58 |        ERR_CODE_TEST       |  — |
| 0x5C |        MAIN_SM_STATE       |  — |

### INTR_STATE register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

|Bits|   Identifier  |  Access |Reset|Name|
|----|---------------|---------|-----|----|
|  0 |cs_cmd_req_done|rw, woclr| 0x0 |  — |
|  1 | cs_entropy_req|rw, woclr| 0x0 |  — |
|  2 | cs_hw_inst_exc|rw, woclr| 0x0 |  — |
|  3 |  cs_fatal_err |rw, woclr| 0x0 |  — |

#### cs_cmd_req_done field

<p>Asserted when a command request is completed.</p>

#### cs_entropy_req field

<p>Asserted when a request for entropy has been made.</p>

#### cs_hw_inst_exc field

<p>Asserted when a hardware-attached CSRNG instance encounters a command exception</p>

#### cs_fatal_err field

<p>Asserted when a FIFO error or a fatal alert occurs. Check the !!ERR_CODE register to get more information.</p>

### INTR_ENABLE register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

|Bits|   Identifier  |Access|Reset|Name|
|----|---------------|------|-----|----|
|  0 |cs_cmd_req_done|  rw  | 0x0 |  — |
|  1 | cs_entropy_req|  rw  | 0x0 |  — |
|  2 | cs_hw_inst_exc|  rw  | 0x0 |  — |
|  3 |  cs_fatal_err |  rw  | 0x0 |  — |

#### cs_cmd_req_done field

<p>Enable interrupt when !!INTR_STATE.cs_cmd_req_done is set.</p>

#### cs_entropy_req field

<p>Enable interrupt when !!INTR_STATE.cs_entropy_req is set.</p>

#### cs_hw_inst_exc field

<p>Enable interrupt when !!INTR_STATE.cs_hw_inst_exc is set.</p>

#### cs_fatal_err field

<p>Enable interrupt when !!INTR_STATE.cs_fatal_err is set.</p>

### INTR_TEST register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

|Bits|   Identifier  |Access|Reset|Name|
|----|---------------|------|-----|----|
|  0 |cs_cmd_req_done|   w  | 0x0 |  — |
|  1 | cs_entropy_req|   w  | 0x0 |  — |
|  2 | cs_hw_inst_exc|   w  | 0x0 |  — |
|  3 |  cs_fatal_err |   w  | 0x0 |  — |

#### cs_cmd_req_done field

<p>Write 1 to force !!INTR_STATE.cs_cmd_req_done to 1.</p>

#### cs_entropy_req field

<p>Write 1 to force !!INTR_STATE.cs_entropy_req to 1.</p>

#### cs_hw_inst_exc field

<p>Write 1 to force !!INTR_STATE.cs_hw_inst_exc to 1.</p>

#### cs_fatal_err field

<p>Write 1 to force !!INTR_STATE.cs_fatal_err to 1.</p>

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

<p>When true, all writeable registers can be modified.
When false, they become read-only.</p>

### CTRL register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

| Bits|    Identifier   |Access|Reset|Name|
|-----|-----------------|------|-----|----|
| 3:0 |      ENABLE     |  rw  | 0x9 |  — |
| 7:4 |  SW_APP_ENABLE  |  rw  | 0x9 |  — |
| 11:8|  READ_INT_STATE |  rw  | 0x9 |  — |
|15:12|FIPS_FORCE_ENABLE|  rw  | 0x9 |  — |

#### ENABLE field

<p>Setting this field to kMultiBitBool4True will enable the CSRNG module. The modules
of the entropy complex may only be enabled and disabled in a specific order, see
Programmers Guide for details.</p>

#### SW_APP_ENABLE field

<p>Setting this field to kMultiBitBool4True will enable reading from the !!GENBITS register.
This application interface for software (register based) will be enabled
only if the otp_en_csrng_sw_app_read input vector is set to the enable encoding.</p>

#### READ_INT_STATE field

<p>Setting this field to kMultiBitBool4True will enable reading from the !!INT_STATE_VAL register.
Reading the internal state of the enable instances will be enabled
only if the otp_en_csrng_sw_app_read input vector is set to the enable encoding.
Also, the !!INT_STATE_READ_ENABLE bit of the selected instance needs to be set to true for this to work.</p>

#### FIPS_FORCE_ENABLE field

<p>Setting this field to kMultiBitBool4True enables forcing the FIPS/CC compliance flag to true via the !!FIPS_FORCE register.</p>

### CMD_REQ register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  CMD_REQ |   w  | 0x0 |  — |

#### CMD_REQ field

<p>Writing this request with defined CSRNG commands will initiate all
possible CSRNG actions. The application interface must wait for the
"ack" to return before issuing new commands.</p>

### RESEED_INTERVAL register

- Absolute Address: 0x1C
- Base Offset: 0x1C
- Size: 0x4

|Bits|   Identifier  |Access|   Reset  |Name|
|----|---------------|------|----------|----|
|31:0|RESEED_INTERVAL|  rw  |0xFFFFFFFF|  — |

#### RESEED_INTERVAL field

<p>Setting this field will set the number of generate requests that can be
made to CSRNG before a reseed request needs to be made.
This register supports a maximum of 2^32 requests between reseeds.
This register will be compared to a counter, which counts the number of
generate commands between reseed or instantiate commands.
If the counter reaches the value of this register, the violating command
will be acknowledged with a status error.
If the violating command was issued by a HW instance, an interrupt will
be triggered.</p>

### RESEED_COUNTER register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [3]
- Array Stride: 0x4
- Total Size: 0xC

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|31:0|RESEED_COUNTER_0|   r  | 0x0 |  — |

#### RESEED_COUNTER_0 field

<p>Reseed Counter indicating the number of completed Generate requests since the last Instantiate or Reseed command.</p>

### RESEED_COUNTER register

- Absolute Address: 0x24
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [3]
- Array Stride: 0x4
- Total Size: 0xC

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|31:0|RESEED_COUNTER_0|   r  | 0x0 |  — |

#### RESEED_COUNTER_0 field

<p>Reseed Counter indicating the number of completed Generate requests since the last Instantiate or Reseed command.</p>

### RESEED_COUNTER register

- Absolute Address: 0x28
- Base Offset: 0x20
- Size: 0x4
- Array Dimensions: [3]
- Array Stride: 0x4
- Total Size: 0xC

|Bits|   Identifier   |Access|Reset|Name|
|----|----------------|------|-----|----|
|31:0|RESEED_COUNTER_0|   r  | 0x0 |  — |

#### RESEED_COUNTER_0 field

<p>Reseed Counter indicating the number of completed Generate requests since the last Instantiate or Reseed command.</p>

### SW_CMD_STS register

- Absolute Address: 0x2C
- Base Offset: 0x2C
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|  1 |  CMD_RDY |   r  | 0x0 |  — |
|  2 |  CMD_ACK |   r  | 0x0 |  — |
| 5:3|  CMD_STS |   r  | 0x0 |  — |

#### CMD_RDY field

<p>This bit indicates when the command interface is ready to accept commands.
Before starting to write a new command to !!SW_CMD_REQ, this field needs to be polled.
0b0: CSRNG is not ready to accept commands or the last command hasn't been acked yet.
0b1: CSRNG is ready to accept the next command.</p>

#### CMD_ACK field

<p>This one bit field indicates when a SW command has been acknowledged by the CSRNG.
It is set to low each time a new command is written to !!CMD_REQ.
The field is set to high once a SW command request has been acknowledged by the CSRNG.
0b0: The last SW command has not been acknowledged yet.
0b1: The last SW command has been acknowledged.
In case of a generate command the acknowledgement goes high after all of the requested entropy is consumed.</p>

#### CMD_STS field

<p>This field represents the status code returned with the application command ack.
It is updated each time a command ack is asserted on the internal application
interface for software use.
To check whether a command was successful, wait for !!INTR_STATE.CS_CMD_REQ_DONE or
!!SW_CMD_STS.CMD_ACK to be high and then check the value of this field.</p>

### GENBITS_VLD register

- Absolute Address: 0x30
- Base Offset: 0x30
- Size: 0x4

|Bits| Identifier |Access|Reset|Name|
|----|------------|------|-----|----|
|  0 | GENBITS_VLD|   r  |  —  |  — |
|  1 |GENBITS_FIPS|   r  |  —  |  — |

#### GENBITS_VLD field

<p>This bit is set when genbits are available on this application interface after a generate command has been issued.</p>

#### GENBITS_FIPS field

<p>This bit is set when genbits are FIPS/CC compliant.</p>

### GENBITS register

- Absolute Address: 0x34
- Base Offset: 0x34
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|  GENBITS |   r  |  —  |  — |

#### GENBITS field

<p>Reading this register will get the generated bits that were requested with
the generate request. This register must be read four times for each request
made. For example, an application command generate request with
a <code>clen</code> value of 4 requires this register to be read 16 times to get all
of the data out of the FIFO path.
Note that for !!GENBITS to be able to deliver random numbers, also !!CTRL.SW_APP_ENABLE needs to be set to <code>kMultiBitBool4True</code>.
In addition, the otp_en_csrng_sw_app_read input needs to be set to <code>kMultiBitBool8True</code>.
Otherwise, the register reads as 0.</p>

### INT_STATE_READ_ENABLE register

- Absolute Address: 0x38
- Base Offset: 0x38
- Size: 0x4

|Bits|      Identifier     |Access|Reset|Name|
|----|---------------------|------|-----|----|
| 2:0|INT_STATE_READ_ENABLE|  rw  | 0x7 |  — |

#### INT_STATE_READ_ENABLE field

<p>Per-instance internal state read enable.
Defines whether the internal state of the corresponding instance is readable via !!INT_STATE_VAL.
Note that for !!INT_STATE_VAL to provide read access to the internal state, also !!CTRL.READ_INT_STATE needs to be set to <code>kMultiBitBool4True</code>.
In addition, the otp_en_csrng_sw_app_read input needs to be set to <code>kMultiBitBool8True</code>.</p>

### INT_STATE_READ_ENABLE_REGWEN register

- Absolute Address: 0x3C
- Base Offset: 0x3C
- Size: 0x4

|Bits|         Identifier         | Access|Reset|Name|
|----|----------------------------|-------|-----|----|
|  0 |INT_STATE_READ_ENABLE_REGWEN|rw, wzc| 0x1 |  — |

#### INT_STATE_READ_ENABLE_REGWEN field

<p>INT_STATE_READ_ENABLE register configuration enable bit.
If this is cleared to 0, the INT_STATE_READ_ENABLE register cannot be written anymore.</p>

### INT_STATE_NUM register

- Absolute Address: 0x40
- Base Offset: 0x40
- Size: 0x4

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
| 3:0|INT_STATE_NUM|  rw  | 0x0 |  — |

#### INT_STATE_NUM field

<p>Setting this field will set the number for which internal state can be
selected for a read access. Up to 16 internal state values can be chosen
from this register. The actual number of valid internal state fields
is set by parameter NumHwApps plus 1 software app. For those selections that point
to reserved locations (greater than NumHwApps plus 1), the returned value
will be zero. Writing this register will also reset the internal read
pointer for the !!INT_STATE_VAL register.
Note: This register should be read back after being written to ensure
that the !!INT_STATE_VAL read back is accurate.</p>

### INT_STATE_VAL register

- Absolute Address: 0x44
- Base Offset: 0x44
- Size: 0x4

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|31:0|INT_STATE_VAL|   r  |  —  |  — |

#### INT_STATE_VAL field

<p>Reading this register will dump out the contents of the selected internal state field.
Since the internal state field is 448 bits wide, it will require 14 reads from this
register to gather the entire field. Once 14 reads have been done, the internal read
pointer (selects 32 bits of the 448 bit field) will reset to zero. The !!INT_STATE_NUM
can be re-written at this time (internal read pointer is also reset), and then
another internal state field can be read.
Note that for !!INT_STATE_VAL to provide read access to the internal state, also !!CTRL.READ_INT_STATE needs to be set to <code>kMultiBitBool4True</code>.
In addition, the otp_en_csrng_sw_app_read input needs to be set to <code>kMultiBitBool8True</code>.
Also, the !!INT_STATE_READ_ENABLE bit of the selected instance needs to be set to true for this to work.
Otherwise, the register reads as 0.</p>

### FIPS_FORCE register

- Absolute Address: 0x48
- Base Offset: 0x48
- Size: 0x4

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
| 2:0|FIPS_FORCE|  rw  | 0x0 |  — |

#### FIPS_FORCE field

<p>Force the FIPS/CC compliance flag of individual instances to true.
This allows CSRNG to set the output FIPS/CC compliance flag to true despite running in fully deterministic mode (flag0 being true).
This can be useful e.g. for known-answer testing through entropy consumers accepting FIPS/CC compliant entropy only, or when firmware is used to derive FIPS/CC compliant entropy seeds.
After setting a particular bit to 1, the FIPS/CC compliance flag of the corresponding instance will be forced to true upon the next Instantiate or Reseed command.</p>
<p>Note that for this to work, !!CTRL.FIPS_FORCE_ENABLE needs to be set to kMultiBitBool4True.</p>

### HW_EXC_STS register

- Absolute Address: 0x4C
- Base Offset: 0x4C
- Size: 0x4

|Bits|Identifier| Access|Reset|Name|
|----|----------|-------|-----|----|
|15:0|HW_EXC_STS|rw, wzc| 0x0 |  — |

#### HW_EXC_STS field

<p>Reading this register indicates whether one of the CSRNG HW instances has
encountered an exception.  Each bit corresponds to a particular hardware
instance, with bit 0 corresponding to instance HW0, bit 1 corresponding
to instance HW1, and so forth. (To monitor the status of requests made
to the SW instance, check the !!SW_CMD_STS register). Writing a zero to this register
resets the status bits.</p>

### RECOV_ALERT_STS register

- Absolute Address: 0x50
- Base Offset: 0x50
- Size: 0x4

|Bits|           Identifier          | Access|Reset|Name|
|----|-------------------------------|-------|-----|----|
|  0 |       ENABLE_FIELD_ALERT      |rw, wzc| 0x0 |  — |
|  1 |   SW_APP_ENABLE_FIELD_ALERT   |rw, wzc| 0x0 |  — |
|  2 |   READ_INT_STATE_FIELD_ALERT  |rw, wzc| 0x0 |  — |
|  3 | FIPS_FORCE_ENABLE_FIELD_ALERT |rw, wzc| 0x0 |  — |
|  4 |     ACMD_FLAG0_FIELD_ALERT    |rw, wzc| 0x0 |  — |
| 12 |        CS_BUS_CMP_ALERT       |rw, wzc| 0x0 |  — |
| 13 |  CMD_STAGE_INVALID_ACMD_ALERT |rw, wzc| 0x0 |  — |
| 14 |CMD_STAGE_INVALID_CMD_SEQ_ALERT|rw, wzc| 0x0 |  — |
| 15 |   CMD_STAGE_RESEED_CNT_ALERT  |rw, wzc| 0x0 |  — |

#### ENABLE_FIELD_ALERT field

<p>This bit is set when the ENABLE field in the !!CTRL register is set to
a value other than kMultiBitBool4True or kMultiBitBool4False.
Writing a zero resets this status bit.</p>

#### SW_APP_ENABLE_FIELD_ALERT field

<p>This bit is set when the SW_APP_ENABLE field in the !!CTRL register is set to
a value other than kMultiBitBool4True or kMultiBitBool4False.
Writing a zero resets this status bit.</p>

#### READ_INT_STATE_FIELD_ALERT field

<p>This bit is set when the READ_INT_STATE field in the !!CTRL register is set to
a value other than kMultiBitBool4True or kMultiBitBool4False.
Writing a zero resets this status bit.</p>

#### FIPS_FORCE_ENABLE_FIELD_ALERT field

<p>This bit is set when the FIPS_FORCE_ENABLE field in the !!CTRL register is set to a value other than kMultiBitBool4True or kMultiBitBool4False.
Writing a zero resets this status bit.</p>

#### ACMD_FLAG0_FIELD_ALERT field

<p>This bit is set when the FLAG0 field in the Application Command is set to
a value other than kMultiBitBool4True or kMultiBitBool4False.
Writing a zero resets this status bit.</p>

#### CS_BUS_CMP_ALERT field

<p>This bit is set when the software application port genbits bus value is equal
to the prior valid value on the bus, indicating a possible attack.
Writing a zero resets this status bit.</p>

#### CMD_STAGE_INVALID_ACMD_ALERT field

<p>This bit is set when an unsupported/illegal CSRNG command is received by the
main state machine.
The invalid command is ignored and CSRNG continues to operate.
Writing a zero resets this status bit.</p>

#### CMD_STAGE_INVALID_CMD_SEQ_ALERT field

<p>This bit is set when an out of order command is received by the main state machine.
This happens when an instantiate command is sent for a state that was already
instantiated or when any command other than instantiate is sent for a state that
wasn't instantiated yet.
The invalid command is ignored and CSRNG continues to operate.
Writing a zero resets this status bit.</p>

#### CMD_STAGE_RESEED_CNT_ALERT field

<p>This bit is set when the maximum number of generate requests between reseeds is
exceeded.
The invalid generate command is ignored and CSRNG continues to operate.
Writing a zero resets this status bit.</p>

### ERR_CODE register

- Absolute Address: 0x54
- Base Offset: 0x54
- Size: 0x4

|Bits|    Identifier   |Access|Reset|Name|
|----|-----------------|------|-----|----|
|  0 |  SFIFO_CMD_ERR  |   r  | 0x0 |  — |
|  1 |SFIFO_GENBITS_ERR|   r  | 0x0 |  — |
| 20 | CMD_STAGE_SM_ERR|   r  | 0x0 |  — |
| 21 |   MAIN_SM_ERR   |   r  | 0x0 |  — |
| 22 | CTR_DRBG_SM_ERR |   r  | 0x0 |  — |
| 25 |AES_CIPHER_SM_ERR|   r  | 0x0 |  — |
| 26 |     CTR_ERR     |   r  | 0x0 |  — |
| 28 |  FIFO_WRITE_ERR |   r  | 0x0 |  — |
| 29 |  FIFO_READ_ERR  |   r  | 0x0 |  — |
| 30 |  FIFO_STATE_ERR |   r  | 0x0 |  — |

#### SFIFO_CMD_ERR field

<p>This bit will be set to one when an error has been detected for the
command stage command FIFO. The type of error is reflected in the type status
bits (bits 28 through 30 of this register).
This bit will stay set until the next reset.</p>

#### SFIFO_GENBITS_ERR field

<p>This bit will be set to one when an error has been detected for the
command stage genbits FIFO. The type of error is reflected in the type status
bits (bits 28 through 30 of this register).
This bit will stay set until the next reset.</p>

#### CMD_STAGE_SM_ERR field

<p>This bit will be set to one when an illegal state has been detected for the
command stage state machine. This error will signal a fatal alert, and also
an interrupt if enabled.
This bit will stay set until the next reset.</p>

#### MAIN_SM_ERR field

<p>This bit will be set to one when an illegal state has been detected for the
main state machine. This error will signal a fatal alert, and also
an interrupt if enabled.
This bit will stay set until the next reset.</p>

#### CTR_DRBG_SM_ERR field

<p>This bit will be set to one when an illegal state has been detected for the
ctr_drbg state machine. This error will signal a fatal alert, and also
an interrupt if enabled.
This bit will stay set until the next reset.</p>

#### AES_CIPHER_SM_ERR field

<p>This bit will be set to one when an AES fatal error has been detected.
This error will signal a fatal alert, and also an interrupt if enabled.
This bit will stay set until the next reset.</p>

#### CTR_ERR field

<p>This bit will be set to one when a mismatch in any of the hardened counters
has been detected.
This error will signal a fatal alert, and also an interrupt if enabled.
This bit will stay set until the next reset.</p>

#### FIFO_WRITE_ERR field

<p>This bit will be set to one when any of the source bits (bits 0 through 15 of this
this register) are asserted as a result of an error pulse generated from
any full FIFO that has been received a write pulse.
This bit will stay set until the next reset.</p>

#### FIFO_READ_ERR field

<p>This bit will be set to one when any of the source bits (bits 0 through 15 of this
this register) are asserted as a result of an error pulse generated from
any empty FIFO that has received a read pulse.
This bit will stay set until the next reset.</p>

#### FIFO_STATE_ERR field

<p>This bit will be set to one when any of the source bits (bits 0 through 15 of this
this register) are asserted as a result of an error pulse generated from
any FIFO where both the empty and full status bits are set.
This bit will stay set until the next reset.</p>

### ERR_CODE_TEST register

- Absolute Address: 0x58
- Base Offset: 0x58
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

- Absolute Address: 0x5C
- Base Offset: 0x5C
- Size: 0x4

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
| 5:0|MAIN_SM_STATE|   r  | 0x37|  — |

#### MAIN_SM_STATE field

<p>This is the state of the CSRNG main state machine.
See the RTL file <code>csrng_main_sm</code> for the meaning of the values.</p>
