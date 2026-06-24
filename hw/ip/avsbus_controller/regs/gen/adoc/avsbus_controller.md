<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: avsbus_controller
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/avsbus_controller/regs/avsbus_controller.rdl
-->

## avsbus_controller address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x5C

<p>AVSBus V1.3.1 Registers</p>

|Offset|        Identifier       |Name|
|------|-------------------------|----|
| 0x00 |         AVS_CMD         |  — |
| 0x04 |       AVS_READBACK      |  — |
| 0x08 |    AVS_DEBUG_READBACK   |  — |
| 0x0C |AVS_LATEST_SLAVE_SUBFRAME|  — |
| 0x20 |    AVS_NORMAL_STATUS    |  — |
| 0x24 |     AVS_SLAVE_STATUS    |  — |
| 0x28 |     AVS_FIFOS_STATUS    |  — |
| 0x30 |      AVS_INTERRUPT      |  — |
| 0x34 |    AVS_INTERRUPT_MASK   |  — |
| 0x38 |   AVS_INTERRUPT_CLEAR   |  — |
| 0x50 |        AVS_CFG_0        |  — |
| 0x54 |        AVS_CFG_1        |  — |
| 0x58 |        AVS_CONFIG       |  — |

### AVS_CMD register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>The command+data to be transferred to the AVS bus</p>

| Bits|Identifier|Access|Reset|Name|
|-----|----------|------|-----|----|
| 18:3| CMD_DATA |   w  | 0x0 |  — |
|22:19| RAIL_SEL |   w  | 0x0 |  — |
|26:23| CMD_CODE |   w  | 0x0 |  — |
|  27 |  CMD_GRP |   w  | 0x0 |  — |
|29:28|  R_OR_W  |   w  | 0x0 |  — |

#### CMD_DATA field

<p>Write Cmd Data. Formats: <ul></p>
<li>Voltage (cmd_code 0x0): 16-bit unsigned int, 1LSB=1mV
</li>
<li>Transition Rate (cmd_code 0x1): <ul>
   <li>MSByte: Rise Rate, 8-bit unsigned int, 1LSB=1mV/us
   </li><li>LSByte: Fall Rate, 8-bit unsigned int, 1LSB=1mV/us </li></ul>
</li>
<li>Reset Voltage (cmd_code 0x4): 16-bits, all zeroes
</li>
<li>Power Mode (cmd_code 0x5): 3-bits, LSB aligned: <ul>
   <li>0x0 - Maximum Efficiency
   </li><li>0x3 - Maximum Power
   </li><li>0x4-0x7 - Manufacturer-specific  </li></ul>
</li>
<li>AVSBus Status (cmd_code 0xe): 16-bits, encoded per AVS Spec
</li>
<li>AVSBus Version (cmd_code 0xf): 4 bits encoded per AVS Spec, LSB-aligned
</li>
<li>For read cmd_code's, this is 0xffff
</li>
</ul>

#### RAIL_SEL field

<p>Rail Select:
0x0 - Rail 0
0x1 - Rail 1
0xf - Broadcast</p>

#### CMD_CODE field

<p>Command Code (For cmd_group=0. For cmd_group=1, this is manufacturer-specific): <ul></p>
<li>0x0 - Target Rail Voltage Read/Write
</li>
<li>0x1 - Vout Transition Rate Read/Write
</li>
<li>0x2 - Rail Current Read
</li>
<li>0x3 - Temperature Read
</li>
<li>0x4 - Force Voltage Reset (Requires wr_cmd_data=0x0)
</li>
<li>0x5 - Power Mode Read/Write
</li>
<li>0xe - AVSBus Status Read/Write
</li>
<li>0xf - AVSBus Version Read
</li>
</ul>

#### CMD_GRP field

<p>Command group:
Set to 1 for manufacturer-specific Command Code (cmd_code), otherwise 0</p>

#### R_OR_W field

<p>Read or write type: <ul></p>
<li>0x0 - Commit Write
</li>
<li>0x1 - Hold Write
</li>
<li>0x2 - Read
</li>
</ul>

### AVS_READBACK register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>Response data from AVS slave device (updated in response to both AVS read and write commands). Reading
this register causes the AVS response readback fifo pointer to advance.</p>

| Bits|   Identifier  | Access |Reset|Name|
|-----|---------------|--------|-----|----|
| 2:0 |      CRC      |r, ruser| 0x0 |  — |
| 23:8|    CMD_DATA   |r, ruser| 0x0 |  — |
|28:24|STATUS_RESPONSE|r, ruser| 0x0 |  — |
|  29 |     CONST0    |r, ruser| 0x0 |  — |
|31:30|   SLAVE_ACK   |r, ruser| 0x0 |  — |

#### CRC field

<p>The CRC-3 code received from slave</p>

#### CMD_DATA field

<p>Read Cmd Data. Format depends on cmd_code in previous master subframe:<ul></p>
<li>Voltage (cmd_code 0x0): 16-bit unsigned int, 1LSB=1mV
</li>
<li>Transition Rate (cmd_code 0x1): <ul>
   <li>MSByte: Rise Rate, 8-bit unsigned int, 1LSB=1mV/us
   </li><li>LSByte: Fall Rate, 8-bit unsigned int, 1LSB=1mV/us </li></ul>
</li>
<li>Current (cmd_mode 0x2): 16-bit unsigned, 1LSB=10mA
</li>
<li>Temperature (cmd_code 0x3): 16-bit signed, 1LSB=0.1degC
</li>
<li>Power Mode (cmd_code 0x5): 3-bits, LSB aligned: <ul>
   <li>0x0 - Maximum Efficiency
   </li><li>0x3 - Maximum Power
   </li><li>0x4-0x7 - Manufacturer-specific  </li></ul>
</li>
<li>AVSBus Status (cmd_code 0xe): 16-bits, encoded per AVS Spec
</li>
<li>AVSBus Version (cmd_code 0xf): 4 bits encoded per AVS Spec, LSB-aligned
</li>
<li>If master issued a write (rw!=0x2) in previous master subframe, this field is 0xffff
</li>
</ul>

#### STATUS_RESPONSE field

<p>5-bit field indicating general condition of the slave, per AVS spec StatusReponse field: <ul></p>
<li>bit 4: VDone - AND of all VDone bits of active rails
</li>
<li>bit 3: StatusAlert - Indicates potential status issue, requiring AVSBus Status read cmd for details
</li>
<li>bit 2: AVS_Control - 1 if ABSBus is controlling at least 1 device output, 0 otherwise.
</li>
<li>bit 1: MfrSpcfc_Stts1 - Manufacturer-specific
</li>
<li>bit 0: MfrSpcfc_Stts2 - Manufacturer-specific
</li>
</ul>

#### CONST0 field

<p>Always 0</p>

#### SLAVE_ACK field

<p>Indicates whether command executed or not - codes 0x1 and 0x2 trigger automatic retries by hardware:  <ul></p>
<li>0x0: Action Performed
</li>
<li>0x1: Good CRC received but resource unavailable - hardware will retry
</li>
<li>0x2: Bad CRC received - hardware will retry
</li>
<li>0x3: Good CRC received but bad data, data type or selector - no hardware retry
</li>
</ul>

### AVS_DEBUG_READBACK register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>This register mirrors the AVS_READBACK register, but reading it does NOT affect the
AVS readback fifo pointer. Provided for debug purposes.</p>

|Bits|    Identifier    |Access|   Reset  |Name|
|----|------------------|------|----------|----|
|31:0|AVS_SLAVE_SUBFRAME|   r  |0xFFFFFFFF|  — |

#### AVS_SLAVE_SUBFRAME field

<p>The current top-of-fifo AVS slave response sub-frame in the readback fifo</p>

### AVS_LATEST_SLAVE_SUBFRAME register

- Absolute Address: 0xC
- Base Offset: 0xC
- Size: 0x4

<p>This register contains the most recently received subframe from the AVS slave, by-passing the
AVS readback fifo. It is provided so that APB can see the current slave StatusResponse and SlaveAck
settings in a timely fashion, since the status data from the next entry in the readback fifo might
have considerable latency relative to when it was initially received from the AVS Slave.</p>

|Bits|    Identifier    |Access| Reset|Name|
|----|------------------|------|------|----|
|31:0|AVS_SLAVE_SUBFRAME|   r  |0xFFFF|  — |

#### AVS_SLAVE_SUBFRAME field

<p>The most recently received AVS slave response sub-frame</p>

### AVS_NORMAL_STATUS register

- Absolute Address: 0x20
- Base Offset: 0x20
- Size: 0x4

<p>Various Status bits indicating normal operating conditions for APB2AVS bridge block.
These all have corresponding maskable bits in the AVS_INTERRUPT register</p>

|Bits|      Identifier      |Access|Reset|Name|
|----|----------------------|------|-----|----|
|15:0|     TOTAL_RETRIES    |   r  | 0x0 |  — |
| 16 |AVS_MASTER_IS_RETRYING|   r  | 0x0 |  — |
| 17 |    CMD_FIFO_EMPTY    |   r  | 0x0 |  — |
| 18 |     CMD_FIFO_FULL    |   r  | 0x0 |  — |
| 19 |  READBACK_FIFO_FULL  |   r  | 0x0 |  — |
| 20 |   READBACK_HAS_DATA  |   r  | 0x0 |  — |
| 21 |    AVS_BUS_IS_IDLE   |   r  | 0x0 |  — |
| 22 |AVS_SLAVE_IS_IN_RESYNC|   r  | 0x0 |  — |

#### TOTAL_RETRIES field

<p>Total number of retries attempted by the AVS Master</p>

#### AVS_MASTER_IS_RETRYING field

<p>Master is currently in the middle of retrying a failed command</p>

#### CMD_FIFO_EMPTY field

<p>Indicates AVS_CMD fifo is empty</p>

#### CMD_FIFO_FULL field

<p>Indicates AVS_CMD fifo is full - any additional APB writes to AVS_CMD will be dropped until
the AVS bus can accept the next command, thus freeing space in the cmd fifo</p>

#### READBACK_FIFO_FULL field

<p>Indicates read-back fifo is full - no new AVS commands will be launched until
space is freed by an AVS_READBACK access</p>

#### READBACK_HAS_DATA field

<p>Indicates AVS_READBACK register has data ready to read on APB</p>

#### AVS_BUS_IS_IDLE field

<p>Indicates that neither AVS master nor slave is currently driving a transaction on the AVS bus</p>

#### AVS_SLAVE_IS_IN_RESYNC field

<p>Indicates that the AVS master is issuing a slave resync operation (34 clock cycles of holding mdata high)</p>

### AVS_SLAVE_STATUS register

- Absolute Address: 0x24
- Base Offset: 0x24
- Size: 0x4

<p>Contains the most recent status feedback from the AVS slave device</p>

| Bits|        Identifier       |Access|Reset|Name|
|-----|-------------------------|------|-----|----|
| 4:0 |AVS_SLAVE_STATUS_RESPONSE|   r  | 0x0 |  — |
|17:16|      AVS_SLAVE_ACK      |   r  | 0x0 |  — |

#### AVS_SLAVE_STATUS_RESPONSE field

<p>The 5-bit Slave StatusResponse of the most recent slave subframe received, indicating the
general condition of the slave, per AVS spec StatusReponse field: <ul>
 <br />
<li>bit 4: VDone - AND of all VDone bits of active rails
   </li></p>
<li>bit 3: StatusAlert - Indicates potential status issue, requiring AVSBus Status read cmd for details
   </li>
<li>bit 2: AVS_Control - 1 if ABSBus is controlling at least 1 device output, 0 otherwise.
   </li>
<li>bit 1: MfrSpcfc_Stts1 - Manufacturer-specific
   </li>
<li>bit 0: MfrSpcfc_Stts2 - Manufacturer-specific
   </li>
</ul>

#### AVS_SLAVE_ACK field

<p>The SlaveAck bits of the most recent slave subframe received: <ul>
      <li>00: Action Performed
      </li><li>01:Good CRC received by resource unavailable. No action performed (triggers retry)
      </li><li>10: Bad CRC received (triggers retry)
      </li><li>11: Good CRC received bit bad data, data type, or selector. No action performed
</li></ul></p>

### AVS_FIFOS_STATUS register

- Absolute Address: 0x28
- Base Offset: 0x28
- Size: 0x4

<p>Contains the number of occupied and vacant slots in the AVS master's command and readback FIFOs</p>

| Bits|         Identifier         |Access|Reset|Name|
|-----|----------------------------|------|-----|----|
| 3:0 |   CMD_FIFO_OCCUPIED_SLOTS  |   r  | 0x0 |  — |
| 11:8|    CMD_FIFO_VACANT_SLOTS   |   r  | 0x8 |  — |
|19:16|READBACK_FIFO_OCCUPIED_SLOTS|   r  | 0x0 |  — |
|27:24| READBACK_FIFO_VACANT_SLOTS |   r  | 0x8 |  — |

#### CMD_FIFO_OCCUPIED_SLOTS field

<p>Number of occupied slots in the command FIFO</p>

#### CMD_FIFO_VACANT_SLOTS field

<p>Number of vacant slots in the command FIFO</p>

#### READBACK_FIFO_OCCUPIED_SLOTS field

<p>Number of occupied slots in the readback FIFO</p>

#### READBACK_FIFO_VACANT_SLOTS field

<p>Number of vacant slots in the readback FIFO</p>

### AVS_INTERRUPT register

- Absolute Address: 0x30
- Base Offset: 0x30
- Size: 0x4

<p>Interrupt register - A '1' indicates an interrupt has occurred for that bit. To clear the
interrupt bit, write to the corresponding field in the AVS_INTERRUPT_CLEAR register.</p>

|Bits|        Identifier        |Access|Reset|Name|
|----|--------------------------|------|-----|----|
|  0 |AVS_SLAVE_ISSUED_INTERRUPT|   r  | 0x0 |  — |
|  1 |     CMD_FIFO_FULL_INT    |   r  | 0x0 |  — |
|  2 |  READBACK_FIFO_FULL_INT  |   r  | 0x0 |  — |
|  3 |   READBACK_HAS_DATA_INT  |   r  | 0x0 |  — |
|  4 |  SLAVE_UNRESPONSIVE_INT  |   r  | 0x0 |  — |
|  5 | MAX_RETRIES_ATTEMPTED_INT|   r  | 0x0 |  — |
|  6 |   CMD_FIFO_OVERFLOW_INT  |   r  | 0x0 |  — |
|  7 |  READBACK_UNDERFLOW_INT  |   r  | 0x0 |  — |
|  8 |   READBACK_OVERFLOW_INT  |   r  | 0x0 |  — |

#### AVS_SLAVE_ISSUED_INTERRUPT field

<p>Indicates the AVS slave has signaled an interrupt</p>

#### CMD_FIFO_FULL_INT field

<p>Indicates AVS_CMD fifo is full - any additional APB writes to AVS_CMD will be dropped until
the AVS bus can accept the next command, thus freeing space in the cmd fifo</p>

#### READBACK_FIFO_FULL_INT field

<p>Indicates read-back fifo is full - no new AVS commands will be launched until
space is freed by an AVS_READBACK access</p>

#### READBACK_HAS_DATA_INT field

<p>Indicates AVS_READBACK register has data ready to read on APB</p>

#### SLAVE_UNRESPONSIVE_INT field

<p>Indicates the AVS Slave device is not responding to command subframes from the Master</p>

#### MAX_RETRIES_ATTEMPTED_INT field

<p>Indicates that the AVS Master failed to receive a non-failure acknowledgement from the Slave after a command was retried the maximum allowable number of times (as determined by AVS_CFG_0:max_retries)</p>

#### CMD_FIFO_OVERFLOW_INT field

<p>Indicates that an APB write to AVS_CMD was attempted when the the command fifo was already
full - the command is dropped</p>

#### READBACK_UNDERFLOW_INT field

<p>Indicates that an APB read on the AVS_READBACK reg occurred when the readback fifo
was empty (AVS_NORMAL_STATUS:readback_has_data=0)</p>

#### READBACK_OVERFLOW_INT field

<p>Indicates that the response from AVS slave could not be written to readback FIFO due to it being
full =&gt; response was dropped</p>

### AVS_INTERRUPT_MASK register

- Absolute Address: 0x34
- Base Offset: 0x34
- Size: 0x4

<p>Interrupt mask register - Determines which AVS_INTERRUPT bits can trigger an interrupt</p>

|Bits|            Identifier            |Access|Reset|Name|
|----|----------------------------------|------|-----|----|
|  0 |DISABLE_AVS_SLAVE_ISSUED_INTERRUPT|  rw  | 0x1 |  — |
|  1 |     DISABLE_CMD_FIFO_FULL_INT    |  rw  | 0x1 |  — |
|  2 |  DISABLE_READBACK_FIFO_FULL_INT  |  rw  | 0x1 |  — |
|  3 |   DISABLE_READBACK_HAS_DATA_INT  |  rw  | 0x1 |  — |
|  4 |  DISABLE_SLAVE_UNRESPONSIVE_INT  |  rw  | 0x1 |  — |
|  5 | DISABLE_MAX_RETRIES_ATTEMPTED_INT|  rw  | 0x1 |  — |
|  6 |   DISABLE_CMD_FIFO_OVERFLOW_INT  |  rw  | 0x1 |  — |
|  7 |  DISABLE_READBACK_UNDERFLOW_INT  |  rw  | 0x1 |  — |
|  8 |   DISABLE_READBACK_OVERFLOW_INT  |  rw  | 0x1 |  — |

#### DISABLE_AVS_SLAVE_ISSUED_INTERRUPT field

<p>Disable notification of AVS slave interrupt</p>

#### DISABLE_CMD_FIFO_FULL_INT field

<p>Disable cmd_fifo_full interrupt</p>

#### DISABLE_READBACK_FIFO_FULL_INT field

<p>Disable readback_fifo_full interrupt</p>

#### DISABLE_READBACK_HAS_DATA_INT field

<p>Disable readback_has_data interrupt</p>

#### DISABLE_SLAVE_UNRESPONSIVE_INT field

<p>Disable slave_unresponsive interrupt</p>

#### DISABLE_MAX_RETRIES_ATTEMPTED_INT field

<p>Disable max_retries_attempted interrupt</p>

#### DISABLE_CMD_FIFO_OVERFLOW_INT field

<p>Disable cmd_fifo_overflow interrupt</p>

#### DISABLE_READBACK_UNDERFLOW_INT field

<p>Disable readback_underflow interrupt</p>

#### DISABLE_READBACK_OVERFLOW_INT field

<p>Disable readback_overflow interrupt</p>

### AVS_INTERRUPT_CLEAR register

- Absolute Address: 0x38
- Base Offset: 0x38
- Size: 0x4

<p>Write 1 to clear corresponding interrupt bit</p>

|Bits|           Identifier           |Access|Reset|Name|
|----|--------------------------------|------|-----|----|
|  0 |CLEAR_AVS_SLAVE_ISSUED_INTERRUPT|   w  | 0x0 |  — |
|  1 |     CLEAR_CMD_FIFO_FULL_INT    |   w  | 0x0 |  — |
|  2 |  CLEAR_READBACK_FIFO_FULL_INT  |   w  | 0x0 |  — |
|  3 |   CLEAR_READBACK_HAS_DATA_INT  |   w  | 0x0 |  — |
|  4 |  CLEAR_SLAVE_UNRESPONSIVE_INT  |   w  | 0x0 |  — |
|  5 | CLEAR_MAX_RETRIES_ATTEMPTED_INT|   w  | 0x0 |  — |
|  6 |   CLEAR_CMD_FIFO_OVERFLOW_INT  |   w  | 0x0 |  — |
|  7 |  CLEAR_READBACK_UNDERFLOW_INT  |   w  | 0x0 |  — |
|  8 |   CLEAR_READBACK_OVERFLOW_INT  |   w  | 0x0 |  — |

#### CLEAR_AVS_SLAVE_ISSUED_INTERRUPT field

<p>Clear avs_slave_issued_interrupt</p>

#### CLEAR_CMD_FIFO_FULL_INT field

<p>Clear cmd_fifo_full interrupt</p>

#### CLEAR_READBACK_FIFO_FULL_INT field

<p>Clear readback_fifo_full interrupt</p>

#### CLEAR_READBACK_HAS_DATA_INT field

<p>Clear readback_has_data interrupt</p>

#### CLEAR_SLAVE_UNRESPONSIVE_INT field

<p>Clear slave_unresponsive interrupt</p>

#### CLEAR_MAX_RETRIES_ATTEMPTED_INT field

<p>Clear max_retries_attempted interrupt</p>

#### CLEAR_CMD_FIFO_OVERFLOW_INT field

<p>Clear cmd_fifo_overflow interrupt</p>

#### CLEAR_READBACK_UNDERFLOW_INT field

<p>Clear readback_underflow interrupt</p>

#### CLEAR_READBACK_OVERFLOW_INT field

<p>Clear readback_overflow interrupt</p>

### AVS_CFG_0 register

- Absolute Address: 0x50
- Base Offset: 0x50
- Size: 0x4

<p>Configuration register for APB2AVS bridge block</p>

| Bits|   Identifier  |Access| Reset|Name|
|-----|---------------|------|------|----|
| 15:0|RESYNC_INTERVAL|  rw  |0x1000|  — |
|23:16|  MAX_RETRIES  |  rw  |  0x5 |  — |

#### RESYNC_INTERVAL field

<p>Max interval to issue slave resync operation on AVS bus, expressed in number of APB clock cycles. NOTE: there is a 3 cycle delay for the resync flag to be seen by the avs controller due to synchronization.</p>

#### MAX_RETRIES field

<p>Maximum number of times to attempt a retry if an AVS command returns a fail
status (either due to targetted resource being busy or CRC failure)</p>

### AVS_CFG_1 register

- Absolute Address: 0x54
- Base Offset: 0x54
- Size: 0x4

<p>Configuration register for APB2AVS bridge block</p>

| Bits|           Identifier           |Access|Reset|Name|
|-----|--------------------------------|------|-----|----|
| 1:0 |        AVS_CLOCK_SELECT        |  rw  | 0x3 |  — |
|  8  |     STOP_AVS_CLOCK_ON_IDLE     |  rw  | 0x0 |  — |
|  9  |  FORCE_SLAVE_RESYNC_OPERATION  |  rw  | 0x0 |  — |
|  10 |   TURN_OFF_ALL_PREMUX_CLOCKS   |  rw  | 0x0 |  — |
|23:16|        CLK_DIVIDER_VALUE       |  rw  | 0x0 |  — |
|31:24|CLK_DIVIDER_DUTY_CYCLE_NUMERATOR|  rw  | 0x0 |  — |

#### AVS_CLOCK_SELECT field

<p>Selects which clock to use for AVS Clock: <ul>
 <br />
<li> 00: Use the APB clock directly as the AVS clock
   </li></p>
<li> 01: Use a divided version of APB clock as the AVS Clock. The clock divider settings are determined by AVS_CFG_1:clk_divider_value and AVS_CFG_1:clk_divider_duty_cycle_numerator
   </li>
<li> 10: Use the refclk clock directly as the AVS clock
   </li>
<li> 11: Use a divided version of refclk clock as the AVS Clock. The clock divider settings are determined by AVS_CFG_1:clk_divider_value and AVS_CFG_1:clk_divider_duty_cycle_numerator
</li>
</ul>

#### STOP_AVS_CLOCK_ON_IDLE field

<p>When the AVS bus is idle, gate the avs_clock from running. Restart it when there are new commands to be run.
The master will always first issue 34 slave-resync cycles when the clock first restarts.</p>

#### FORCE_SLAVE_RESYNC_OPERATION field

<p>Force master to issue a slave resync (34 clock cycles of holding the mdata signal high) at the next possible opportunity. NOTE: there is a 3 cycle delay for the resync flag to be seen by the avs controller due to synchronization.</p>

#### TURN_OFF_ALL_PREMUX_CLOCKS field

<p>Gate off all clocks entering the AVS clock mux - do this before changing the mux selection or changing the clock divider settings, then turn back on afterwards</p>

#### CLK_DIVIDER_VALUE field

<p>Determines the divisor value used to generate the AVS clock (when avs_clock_select is set to select the divided APB clock or divided refclk clock).
The duty cycle of the divided clock depends both on the clk_divider_value together with the clk_divider_duty_cycle_numerator value. A 50%
duty cycle is only possible on even clk_divider_values with clk_divider_duty_cycle_numerator set to 128. This field requires a minimum value of
2 - for lower values, 2 will be assumed. This is set to 0 by default to trick the clock divider into maintaining the HW-default settings
(divider=0x4) by matching the FF default in the resynced version of the signal.</p>

#### CLK_DIVIDER_DUTY_CYCLE_NUMERATOR field

<p>Determines the desired duty cycle of the divided clock (when avs_clock_select is set to select the divided APB clock or refclk clock).
This value will be divided by 256 to determine the high-pulse percentage of the divided clock period. Depending on the clk_divider_value,
it may not be possible to precisely achieve the desired duty cycle - in that case, the closest possible fit is used. If this is set to 0,
a value of 1 will be assumed. This is set to 0 by default to trick the clock divider into maintaining the HW-default settings (numerator=0x80)
by matching the FF default in the resynced version of the signal.</p>

### AVS_CONFIG register

- Absolute Address: 0x58
- Base Offset: 0x58
- Size: 0x4

<p>AVS Configuration Register</p>

|Bits|   Identifier  |Access|Reset|Name|
|----|---------------|------|-----|----|
|  0 |AVS_GPIO_ENABLE|  rw  | 0x1 |  — |

#### AVS_GPIO_ENABLE field

<p>Enable AVSBus connection to GPIOs. The effective sets OE of the GPIOs dedicated to
avs_clock and avs_cdata to 1, sets IE of GPIO dedicated to avs_tdata to 1. By default,
this is enabled as the AVSBus state machine immediately starts after reset deassertion.</p>
