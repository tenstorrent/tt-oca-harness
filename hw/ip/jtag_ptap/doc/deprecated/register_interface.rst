==================
Register Interface
==================

The JTAG PTAP contains multiple data registers (TDRs) accessed via the instruction register. This section documents each data register and its bit fields.

Data Register Overview
======================

The PTAP implements the following data registers:

.. list-table::
   :widths: 20 15 15 50
   :header-rows: 1

   * - Register
     - Width
     - Access
     - Description
   * - BYPASS
     - 1 bit
     - R/W
     - Standard IEEE 1149.1 bypass register
   * - INV_BYPASS
     - 1 bit
     - R/W
     - Inverted bypass register
   * - IDCODE
     - 32 bits
     - RO
     - Device identification code
   * - 3DCR
     - 2 bits
     - R/W
     - 3-Die Control Register (IEEE 1838)
   * - TMP_STATUS
     - 2 bits
     - R/RW
     - TMP status register
   * - IC_RESET
     - 2*N+1 bits
     - R/W
     - IC reset control register
   * - DEBUG_CTRL
     - 5 bits
     - RO/RW
     - Debug control register
   * - JTAG_CAPS
     - 40 bits
     - RO
     - JTAG capabilities register
   * - JTAG2AXI_CAPS
     - 14 bits
     - RO
     - JTAG2AXI capabilities register

BYPASS Register
===============

A 1-bit register providing minimum scan path length.

.. list-table::
   :widths: 15 15 15 55
   :header-rows: 1

   * - Bit
     - Name
     - Access
     - Description
   * - [0]
     - bypass
     - R/W
     - Bypass bit (captures ``0``)

**Behavior**:

* **Capture**: Loads ``0`` per IEEE 1149.1
* **Shift**: Shifts TDI through to TDO
* **Update**: No effect

**Selected by**: BYPASS (0x3F), BYPASS_ALT (0x00), CLAMP, HIGHZ, undefined instructions

INV_BYPASS Register
===================

A 1-bit inverted bypass register for chain detection.

.. list-table::
   :widths: 15 15 15 55
   :header-rows: 1

   * - Bit
     - Name
     - Access
     - Description
   * - [0]
     - inv_bypass
     - R/W
     - Inverted bypass bit (captures ``1``)

**Behavior**:

* **Capture**: Loads ``1`` (inverted from standard bypass)
* **Shift**: Shifts TDI through to TDO
* **Update**: No effect

**Selected by**: INV_BYPASS (0x3E)

IDCODE Register
===============

A 32-bit device identification register per IEEE 1149.1.

.. list-table::
   :widths: 15 15 15 55
   :header-rows: 1

   * - Bits
     - Name
     - Access
     - Description
   * - [31:28]
     - si_rev
     - RO
     - Silicon revision (4 bits)
   * - [27:12]
     - part_num
     - RO
     - Part number (16 bits)
   * - [11:1]
     - mfr_id
     - RO
     - Manufacturer ID (11 bits)
   * - [0]
     - fixed_1
     - RO
     - Always ``1`` per IEEE 1149.1

**Behavior**:

* **Capture**: Loads constant IDCODE value
* **Shift**: Shifts out IDCODE LSB first
* **Update**: No effect (read-only)

**Configuration Parameters**:

* ``IDCODE_SI_REV``: Silicon revision field value
* ``IDCODE_PART_NUM``: Part number field value
* ``IDCODE_MFR_ID``: Manufacturer ID field value

**Selected by**: IDCODE (0x01), default on reset

3DCR Register (IEEE 1838)
=========================

A 2-bit register for 3D test architecture control.

.. list-table::
   :widths: 15 15 15 55
   :header-rows: 1

   * - Bit
     - Name
     - Access
     - Description
   * - [1]
     - stap_sel
     - R/W
     - STAP selection enable
   * - [0]
     - config_hold
     - R/W
     - Configuration hold (prevents reset during TLR)

**Field Descriptions**:

**stap_sel (bit 1)**:

* ``0``: Local PTAP TDRs selected for scan path
* ``1``: STAP scan chain selected; STAP scan output routed to TDO

**config_hold (bit 0)**:

* ``0``: 3DCR resets on TRST or Test-Logic-Reset (TLR)
* ``1``: 3DCR maintains value during TLR; only TRST resets

**Behavior**:

* **Capture**: Captures current register value
* **Shift**: Shifts through register
* **Update**: Updates control outputs
* **Reset**: Controlled by ``trst_n && (config_hold || scan_ctrl.rst_n)``

**Selected by**: TAP_3DCR (0x0E)

TMP_STATUS Register
===================

A 2-bit TMP status register per IEEE 1149.1 Section 16.1.

.. list-table::
   :widths: 15 15 15 55
   :header-rows: 1

   * - Bit
     - Name
     - Access
     - Description
   * - [1]
     - tmp_status
     - RO
     - TMP controller state (closest to TDI)
   * - [0]
     - bypass_escape
     - R/W
     - Bypass-escape enable bit (closest to TDO)

**Field Descriptions**:

**tmp_status (bit 1)**:

* ``0``: TMP controller in Persistence-Off state
* ``1``: TMP controller in Persistence-On state

**bypass_escape (bit 0)**:

* ``0``: Bypass-escape disabled
* ``1``: Bypass-escape enabled; explicit BYPASS instruction exits persistence mode

**Behavior**:

* **Capture**: ``tmp_status`` captures current TMP state; ``bypass_escape`` retains value
* **Shift**: Shifts through register
* **Update**: Updates ``bypass_escape`` output

**Selected by**: TMP_STATUS (0x0C)

IC_RESET Register
=================

Reset control register per IEEE 1149.1 Section 17. Width depends on ``NUM_IC_RESET`` parameter.

Register Structure
------------------

Total width: ``2 * NUM_IC_RESET + 1`` bits

Scan order (TDI to TDO):

1. ``reset_control[N-1]`` (closest to TDI)
2. ``reset_enable[N-1]``
3. ...
4. ``reset_control[0]``
5. ``reset_enable[0]``
6. ``reset_hold`` (closest to TDO)

Bit Fields
----------

.. list-table::
   :widths: 20 20 15 45
   :header-rows: 1

   * - Bits
     - Name
     - Access
     - Description
   * - [0]
     - reset_hold
     - R/W
     - Holds reset configuration across TLR
   * - [2*i]
     - reset_enable[i]
     - R/W
     - Enables JTAG control over reset port i
   * - [2*i+1]
     - reset_control[i]
     - R/W
     - Reset value for port i when enabled

**Field Descriptions**:

**reset_hold (bit 0)**:

* ``0``: IC_RESET register resets on TLR
* ``1``: IC_RESET register (except reset_hold) maintains value during TLR

**reset_enable[i]**:

* ``0``: JTAG does not control reset port i
* ``1``: JTAG controls reset port i via reset_control[i]

**reset_control[i]**:

* Value driven to reset port i when reset_enable[i] is set
* Directly maps to ``ic_reset_ctrl_n_o[i]``

**Output Mappings**:

* ``ic_reset_ovrd_o[i] = !reset_enable[i]`` (inverted)
* ``ic_reset_ctrl_n_o[i] = reset_control[i]``

**Reset Values**: All bits reset to ``1`` (JTAG does not control resets)

**Selected by**: IC_RESET (0x0D)

DEBUG_CTRL Register
===================

A 5-bit debug control register.

.. list-table::
   :widths: 15 20 15 50
   :header-rows: 1

   * - Bit
     - Name
     - Access
     - Description
   * - [4]
     - cla_clock_stop
     - RO
     - CLA clock stop status (closest to TDI)
   * - [3]
     - jtag_clock_stop
     - R/W
     - JTAG stop clock control
   * - [2]
     - cla_clock_stop_en
     - R/W
     - CLA clock stop enable
   * - [1]
     - boot_stall_ovrd
     - R/W
     - Boot stall override enable
   * - [0]
     - boot_stall
     - R/W
     - Boot stall control value (closest to TDO)

**Field Descriptions**:

**cla_clock_stop (bit 4, read-only)**:

* Reflects current CLA clock stop status from ``cla_clock_stop_i`` input
* Captures on Capture-DR

**jtag_clock_stop (bit 3)**:

* ``0``: Clock running normally
* ``1``: Request clock stop

**cla_clock_stop_en (bit 2)**:

* ``0``: CLA clock stop disabled
* ``1``: CLA clock stop enabled

**boot_stall_ovrd (bit 1)**:

* ``0``: Boot stall controlled by normal logic
* ``1``: Boot stall controlled by JTAG via ``boot_stall`` bit

**boot_stall (bit 0)**:

* Value driven when ``boot_stall_ovrd`` is set

**Behavior**:

* **Capture**: ``cla_clock_stop`` captures input status; other bits retain values
* **Shift**: Shifts through register
* **Update**: Updates control outputs

**Reset Value**: ``5'b00000``

**Selected by**: DEBUG_CONTROL (0x18)

JTAG_CAPS Register
==================

A 40-bit read-only capabilities register reporting PTAP configuration.

.. list-table::
   :widths: 15 25 60
   :header-rows: 1

   * - Bits
     - Name
     - Description
   * - [39:34]
     - num_xtrig_int_ct
     - Number of internal cross triggers (6 bits)
   * - [33:28]
     - num_xtrig_ctp
     - Number of cross trigger ports (6 bits)
   * - [27:24]
     - num_xtra_stap
     - Number of additional STAPs (4 bits)
   * - [23]
     - stap_io_en
     - STAP I/O interface enabled
   * - [22]
     - sep_dbg_en
     - SEP debug interface enabled
   * - [21]
     - smc_dbg_en
     - SMC debug interface enabled
   * - [20:17]
     - num_ic_rst
     - Number of IC reset ports (4 bits)
   * - [16]
     - ic_rst_inst_en
     - IC_RESET instruction enabled
   * - [15]
     - tmp_inst_en
     - TMP instructions enabled
   * - [14]
     - runbist_inst_en
     - RUNBIST instruction enabled
   * - [13]
     - highz_inst_en
     - HIGHZ instruction enabled
   * - [12]
     - clamp_inst_en
     - CLAMP instruction enabled
   * - [11]
     - intest_inst_en
     - INTEST instruction enabled
   * - [10]
     - extest_pulse_en
     - EXTEST_PULSE instruction enabled
   * - [9]
     - extest_train_en
     - EXTEST_TRAIN instruction enabled
   * - [8]
     - bsr_inst_en
     - BSR instructions enabled
   * - [7:0]
     - och_ver
     - OCH/DTP IP version number (8 bits)

.. note::
   The ``jtag_caps_reg`` module includes compile-time assertions that verify all
   count parameters fit within their allocated bit fields:

   * ``NUM_XTRIG_CTP``: 0-63 (6 bits)
   * ``NUM_XTRIG_INT_CT``: 0-63 (6 bits)
   * ``NUM_IC_RESET``: 0-15 (4 bits)
   * ``NUM_EXTRA_STAPS``: 0-15 (4 bits)

   Exceeding these limits will cause an elaboration-time fatal error.

**Behavior**:

* **Capture**: Always captures constant capabilities value
* **Shift**: Shifts out capabilities LSB first
* **Update**: No effect (read-only)

**Selected by**: JTAG_CAPS (0x19)

JTAG2AXI_CAPS Registers
=======================

Three 14-bit read-only registers reporting JTAG2AXI bridge configurations.

.. list-table::
   :widths: 15 20 65
   :header-rows: 1

   * - Bits
     - Name
     - Description
   * - [13:12]
     - rd_pl_depth
     - Read pipeline/queue depth (2 bits)
   * - [11:10]
     - wr_pl_depth
     - Write pipeline/queue depth (2 bits)
   * - [9:7]
     - data_size
     - AXI data width encoding (3 bits, powers of 2 bytes)
   * - [6:1]
     - addr_size
     - AXI address width in bits (6 bits)
   * - [0]
     - bus_type
     - ``0`` = AXI4, ``1`` = AXI4-Lite

**data_size Encoding**:

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Value
     - Bytes
     - Data Width
   * - 0
     - 1 byte
     - 8 bits
   * - 1
     - 2 bytes
     - 16 bits
   * - 2
     - 4 bytes
     - 32 bits
   * - 3
     - 8 bytes
     - 64 bits
   * - 4
     - 16 bytes
     - 128 bits
   * - 5
     - 32 bytes
     - 256 bits
   * - 6
     - 64 bytes
     - 512 bits
   * - 7
     - 128 bytes
     - 1024 bits

**Instances**:

* **SMC_OTP_JTAG2AXI_CAPS**: Selected by instruction 0x1B
* **SEP_OTP_JTAG2AXI_CAPS**: Selected by instruction 0x21
* **SMC_JTAG2AXI_CAPS**: Selected by instruction 0x27

**Behavior**:

* **Capture**: Always captures constant capabilities value
* **Shift**: Shifts out capabilities LSB first
* **Update**: No effect (read-only)

Boundary Scan Register (BSR)
============================

The Boundary Scan Register is external to the PTAP and connected via the BSR interface signals:

* ``bsr_host_scan_ctrl_o``: Scan control to BSR chain
* ``bsr_host_scan_in_i``: Scan data from BSR chain
* ``bsr_host_scan_out_o``: Scan data to BSR chain

**Selected by**: EXTEST, SAMPLE_PRELOAD, EXTEST_TRAIN, EXTEST_PULSE, INTEST

iJTAG Network
=============

The iJTAG network is external to the PTAP and connected via the iJTAG interface signals:

* ``ijtag_host_scan_ctrl_o``: Scan control to iJTAG network
* ``ijtag_host_scan_in_i``: Scan data from iJTAG network
* ``ijtag_host_scan_out_o``: Scan data to iJTAG network

**Selected by**: SELECT_IJTAG, RUNBIST

Register Access Timing
======================

All PTAP data registers follow IEEE 1149.1 timing:

Capture Phase
-------------

* Occurs during Capture-DR state
* Parallel data loaded into shift register
* Read-only fields capture input values
* R/W fields capture current register value

Shift Phase
-----------

* Occurs during Shift-DR state
* Data shifts from TDI through register to TDO
* One bit per TCK rising edge
* LSB shifts out first

Update Phase
------------

* Occurs during Update-DR state
* Shift register contents loaded to output register
* Control outputs update on falling TCK edge
* Read-only registers have no update effect
