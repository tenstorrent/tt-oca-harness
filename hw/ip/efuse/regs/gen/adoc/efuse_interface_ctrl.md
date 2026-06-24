<!---
Markdown description for SystemRDL register map.

Don't override. Generated from: efuse_interface_ctrl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/common/regs/regblock_udps.rdl
  - /proj_soc/user_dev/aottaviano/ocah/oshw/tt-oca/hw/ip/efuse/regs/efuse_interface_ctrl.rdl
-->

## efuse_interface_ctrl address map

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x1C

|Offset|            Identifier           |Name|
|------|---------------------------------|----|
| 0x00 |   EFUSE_INTERFACE_CTRL_STATUS   |  — |
| 0x04 |        EFUSE_PROGRAM_CTRL       |  — |
| 0x08 |         EFUSE_READ_CTRL         |  — |
| 0x0C |EFUSE_PROGRAM_INTERFACE_READ_DATA|  — |
| 0x10 |  EFUSE_READ_INTERFACE_READ_DATA |  — |
| 0x14 |      EFUSE_READ_REQ_TIMEOUT     |  — |
| 0x18 |    EFUSE_PROGRAM_REQ_TIMEOUT    |  — |

### EFUSE_INTERFACE_CTRL_STATUS register

- Absolute Address: 0x0
- Base Offset: 0x0
- Size: 0x4

<p>eFuse interface status and error-clear register. Reports the sense-done flag and request/address error conditions, and provides write-1 strobes to clear those errors.</p>

|Bits|          Identifier          |Access|Reset|Name|
|----|------------------------------|------|-----|----|
|  0 |       efuse_sense_done       |   r  |  —  |  — |
|  4 |        efuse_req_error       |   r  | 0x0 |  — |
|  5 |   efuse_program_addr_error   |   r  | 0x0 |  — |
|  6 |     efuse_read_addr_error    |   r  | 0x0 |  — |
|  8 |     efuse_req_error_clear    |   w  | 0x0 |  — |
|  9 |efuse_program_addr_error_clear|   w  | 0x0 |  — |
| 10 |  efuse_read_addr_error_clear |   w  | 0x0 |  — |

#### efuse_sense_done field

<p>Indicates if the eFuse state machine has completed</p>

#### efuse_req_error field

<p>Indicates that the eFuse was blocked because of either read or a program lock.  The error must be cleared by writing 1 to efuse_req_error_clear to this register</p>

#### efuse_program_addr_error field

<p>Indicates that an invalid eFuse program address was used (address exceeds the implemented eFuse size). The error must be cleared by writing 1 to efuse_program_addr_error_clear.</p>

#### efuse_read_addr_error field

<p>Indicates that an invalid eFuse read address was used (address exceeds the implemented eFuse size). The error must be cleared by writing 1 to efuse_read_addr_error_clear.</p>

#### efuse_req_error_clear field

<p>Clears the blocked request error bit in efuse_ctrl_status</p>

#### efuse_program_addr_error_clear field

<p>Clears the program out of bounds error bit (efuse_program_addr_error) in efuse_ctrl_status</p>

#### efuse_read_addr_error_clear field

<p>Clears the read out of bounds error bit (efuse_read_addr_error) in efuse_ctrl_status</p>

### EFUSE_PROGRAM_CTRL register

- Absolute Address: 0x4
- Base Offset: 0x4
- Size: 0x4

<p>eFuse program control and status. Configures the program address and data, triggers a program (optionally with read-back), and reports program progress and completion status.</p>

|Bits|       Identifier      |Access|Reset|Name|
|----|-----------------------|------|-----|----|
|15:0|       efuse_addr      |  rw  | 0x0 |  — |
| 16 |       efuse_data      |  rw  | 0x0 |  — |
| 17 |    efuse_program_go   |  rw  | 0x0 |  — |
| 18 |efuse_program_read_back|  rw  | 0x0 |  — |
| 24 |      program_busy     |   r  | 0x0 |  — |
| 25 |      program_done     |   r  | 0x0 |  — |
| 26 |     program_status    |   r  | 0x0 |  — |
| 27 |     program_enable    |  rw  | 0x0 |  — |

#### efuse_addr field

<p>Bit address to program</p>

#### efuse_data field

<p>Data to program to eFuse.  If this bit is 0, the program request will be ignored</p>

#### efuse_program_go field

<p>When set, triggers a program to the eFuse.  This will be ignored if the lock bit is set</p>

#### efuse_program_read_back field

<p>When set, trigger a read back after a program</p>

#### program_busy field

<p>When set, the program is in progress</p>

#### program_done field

<p>When set, the program has completed, the status of which is in program_status</p>

#### program_status field

<p>0: No Error.  1: Error</p>

#### program_enable field

<p>When set, enables the program request</p>

### EFUSE_READ_CTRL register

- Absolute Address: 0x8
- Base Offset: 0x8
- Size: 0x4

<p>eFuse read control and status. Configures the read address, triggers a read, and reports read progress and completion status.</p>

|Bits|  Identifier |Access|Reset|Name|
|----|-------------|------|-----|----|
|15:0|  efuse_addr |  rw  | 0x0 |  — |
| 16 |efuse_read_go|  rw  | 0x0 |  — |
| 24 |  read_busy  |   r  | 0x0 |  — |
| 25 |  read_done  |   r  | 0x0 |  — |
| 26 | read_status |   r  | 0x0 |  — |
| 28 | read_enable |  rw  | 0x0 |  — |

#### efuse_addr field

<p>Bit address to read</p>

#### efuse_read_go field

<p>When set, triggers a read to efuse.</p>

#### read_busy field

<p>When set, the read is in progress</p>

#### read_done field

<p>When set, the read has completed, the status of which is in read_status</p>

#### read_status field

<p>0: No Error.  1: Logic error, assert read_go when read is not enabled</p>

#### read_enable field

<p>When set, enables the read request</p>

### EFUSE_PROGRAM_INTERFACE_READ_DATA register

- Absolute Address: 0xC
- Base Offset: 0xC
- Size: 0x4

<p>Read data captured through the program interface. Hardware debug only; valid only while the program interface state machine is in its capture-data state.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   dout   |   r  | 0x0 |  — |

#### dout field

<p>Read Data from eFuse through program interface. This field is only valid when the efuse programming interface is utilized to burn the efuse IP and only when the state machine is during ST_CAPTUER_DATA state. Hardware debug only</p>

### EFUSE_READ_INTERFACE_READ_DATA register

- Absolute Address: 0x10
- Base Offset: 0x10
- Size: 0x4

<p>Read data returned through the eFuse read interface.</p>

|Bits|Identifier|Access|Reset|Name|
|----|----------|------|-----|----|
|31:0|   dout   |   r  | 0x0 |  — |

#### dout field

<p>Read Data from eFuse through READ interface.</p>

### EFUSE_READ_REQ_TIMEOUT register

- Absolute Address: 0x14
- Base Offset: 0x14
- Size: 0x4

<p>Read interface timeout configuration. Sets the number of cycles the read interface waits for a SHIM response and enables the read timeout.</p>

|Bits|       Identifier      |Access|  Reset |Name|
|----|-----------------------|------|--------|----|
|27:0|read_req_timeout_cycles|  rw  |0x800000|  — |
| 28 | read_req_timout_enable|  rw  |   0x0  |  — |

#### read_req_timeout_cycles field

<p>Number of cycles the read interface will wait for a response from the shim. At 100MHz this can count ~= 2.5 seconds.</p>

#### read_req_timout_enable field

<p>Enable timeout on read interface</p>

### EFUSE_PROGRAM_REQ_TIMEOUT register

- Absolute Address: 0x18
- Base Offset: 0x18
- Size: 0x4

<p>Program interface timeout configuration. Sets the number of cycles the program interface waits for a SHIM response and enables the program timeout.</p>

|Bits|        Identifier        |Access|  Reset |Name|
|----|--------------------------|------|--------|----|
|27:0|program_req_timeout_cycles|  rw  |0x800000|  — |
| 28 |program_req_timeout_enable|  rw  |   0x0  |  — |

#### program_req_timeout_cycles field

<p>Number of cycles the program interface will wait for a response from the shim. At 100MHz this can count ~= 2.5 seconds.</p>

#### program_req_timeout_enable field

<p>Enable timeout on program interface.</p>
