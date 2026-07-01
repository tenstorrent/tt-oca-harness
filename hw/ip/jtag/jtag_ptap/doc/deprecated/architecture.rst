=============
Architecture
=============

The JTAG Primary TAP (PTAP) architecture implements a comprehensive test access port compliant with IEEE 1149.1, IEEE 1687, and IEEE 1838 standards. This section describes the detailed architecture and signal flow.

Module Hierarchy
================

The PTAP top module (``jtag_ptap``) instantiates the following sub-modules:

* **jtag_tap_ctrlr**: TAP controller state machine with TMP integration
* **jtag_inst_reg**: 6-bit instruction register with decoder
* **jtag_byp_reg**: 1-bit bypass register (IEEE 1149.1)
* **jtag_inv_byp_reg**: 1-bit inverted bypass register
* **jtag_idcode_reg**: 32-bit IDCODE register
* **jtag_3dcr_reg**: 2-bit 3-Die Control Register (IEEE 1838)
* **jtag_tmp**: Test Mode Persistence controller (IEEE 1149.1 Section 16)
* **jtag_tmp_status_reg**: 2-bit TMP status register
* **jtag_ic_reset_reg**: IC reset control register (IEEE 1149.1 Section 17)
* **jtag_debug_ctrl_reg**: 5-bit debug control register
* **jtag_caps_reg**: 40-bit capabilities register
* **jtag_jtag2axi_caps_reg**: 14-bit JTAG2AXI capabilities (x3 instances)
* **jtag2axi**: JTAG-to-AXI bridge (x3 instances)

TAP Controller
==============

State Machine
-------------

The TAP controller implements the IEEE 1149.1 16-state machine with one-hot encoding.

State Transition Table
~~~~~~~~~~~~~~~~~~~~~~

The following table defines all TAP state transitions based on the TMS input value:

.. list-table::
   :widths: 25 25 25 25
   :header-rows: 1

   * - Current State
     - TMS=0 Next State
     - TMS=1 Next State
     - Description
   * - TEST_LOGIC_RESET
     - RUN_TEST_IDLE
     - TEST_LOGIC_RESET
     - Reset state; stays in reset while TMS=1
   * - RUN_TEST_IDLE
     - RUN_TEST_IDLE
     - SELECT_DR_SCAN
     - Idle state; can run BIST or wait
   * - SELECT_DR_SCAN
     - CAPTURE_DR
     - SELECT_IR_SCAN
     - Select Data Register scan path
   * - CAPTURE_DR
     - SHIFT_DR
     - EXIT1_DR
     - Capture parallel data into DR shift register
   * - SHIFT_DR
     - SHIFT_DR
     - EXIT1_DR
     - Shift data through DR (TDI→DR→TDO)
   * - EXIT1_DR
     - PAUSE_DR
     - UPDATE_DR
     - Exit shift to pause or update
   * - PAUSE_DR
     - PAUSE_DR
     - EXIT2_DR
     - Pause DR shifting; holds data
   * - EXIT2_DR
     - SHIFT_DR
     - UPDATE_DR
     - Return to shift or proceed to update
   * - UPDATE_DR
     - RUN_TEST_IDLE
     - SELECT_DR_SCAN
     - Load DR shift register to output register
   * - SELECT_IR_SCAN
     - CAPTURE_IR
     - TEST_LOGIC_RESET
     - Select Instruction Register scan path
   * - CAPTURE_IR
     - SHIFT_IR
     - EXIT1_IR
     - Capture status into IR shift register
   * - SHIFT_IR
     - SHIFT_IR
     - EXIT1_IR
     - Shift instruction (TDI→IR→TDO)
   * - EXIT1_IR
     - PAUSE_IR
     - UPDATE_IR
     - Exit shift to pause or update
   * - PAUSE_IR
     - PAUSE_IR
     - EXIT2_IR
     - Pause IR shifting; holds data
   * - EXIT2_IR
     - SHIFT_IR
     - UPDATE_IR
     - Return to shift or proceed to update
   * - UPDATE_IR
     - RUN_TEST_IDLE
     - SELECT_DR_SCAN
     - Load new instruction from shift register

.. note::
   The TAP controller enters TEST_LOGIC_RESET after 5 consecutive TMS=1 cycles from any state.
   This provides a reliable reset mechanism without requiring the optional TRST_n signal.

State Encoding
--------------

States are one-hot encoded for error detection:

.. list-table::
   :widths: 30 20 50
   :header-rows: 1

   * - State
     - Encoding
     - Description
   * - TEST_LOGIC_RESET
     - 16'h0001
     - Test logic reset state
   * - RUN_TEST_IDLE
     - 16'h0002
     - Idle state
   * - SELECT_DR_SCAN
     - 16'h0004
     - DR scan path selection
   * - CAPTURE_DR
     - 16'h0008
     - Capture DR data
   * - SHIFT_DR
     - 16'h0010
     - Shift DR data
   * - EXIT1_DR
     - 16'h0020
     - Exit DR shift (to pause or update)
   * - PAUSE_DR
     - 16'h0040
     - Pause DR shift
   * - EXIT2_DR
     - 16'h0080
     - Exit DR pause
   * - UPDATE_DR
     - 16'h0100
     - Update DR outputs
   * - SELECT_IR_SCAN
     - 16'h0200
     - IR scan path selection
   * - CAPTURE_IR
     - 16'h0400
     - Capture IR data
   * - SHIFT_IR
     - 16'h0800
     - Shift IR data
   * - EXIT1_IR
     - 16'h1000
     - Exit IR shift
   * - PAUSE_IR
     - 16'h2000
     - Pause IR shift
   * - EXIT2_IR
     - 16'h4000
     - Exit IR pause
   * - UPDATE_IR
     - 16'h8000
     - Update IR outputs

Scan Control Generation
-----------------------

The TAP controller generates scan control signals used by all data registers:

* **select**: Asserted during DR or IR scan paths
* **capture_en**: Asserted during CAPTURE_DR or CAPTURE_IR
* **shift_en**: Asserted during SHIFT_DR or SHIFT_IR
* **update_en**: Asserted during UPDATE_DR or UPDATE_IR
* **rst_n**: Derived from TRST_n and TEST_LOGIC_RESET state

Instruction Register
====================

The 6-bit instruction register supports 64 unique instructions:

Register Structure
------------------

* **Width**: 6 bits
* **Capture Value**: ``6'b000001`` (IDCODE encoding)
* **Default After Reset**: IDCODE instruction
* **Shift Direction**: LSB first (TDI → MSB, LSB → TDO)

Instruction Decode
------------------

Instructions are decoded to one-hot signals for efficient data register selection:

.. code-block:: systemverilog

   typedef enum logic [DECODED_IR_WIDTH-1:0] {
       BYPASS_ALT_INSTR_DECODED = 64'd1 << BYPASS_ALT_INSTR,
       IDCODE_INSTR_DECODED     = 64'd1 << IDCODE_INSTR,
       // ... additional instructions
   } jtag_instruction_decoded_e;

Data Register Architecture
==========================

TDR Selection Logic
-------------------

The TDR multiplexer selects the appropriate data register based on the current instruction:

.. code-block:: text

   client_tdi_i ────────────────────┐
                                    │
                          ┌─────────┴─────────┐
                          │                   │
                          ▼                   ▼
   ┌──────────────────────────────────────────────────────┐
   │                   Data Registers                     │
   │                                                      │
   │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
   │  │ BYPASS  │  │ IDCODE  │  │  3DCR   │  │IC_RESET │  │
   │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  │
   │       │            │            │            │       │
   │  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐  │
   │  │  CAPS   │  │DBG_CTRL │  │ TMP_STS │  │ JTAG2AXI│  │
   │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  │
   │       │            │            │            │       │
   │       └────────────┴────────────┴────────────┘       │
   │                         │                            │
   │                         ▼                            │
   │                   TDR Multiplexer                    │
   │              (instruction decoded select)            │
   └──────────────────────┬───────────────────────────────┘
                          │
                          ▼
                    ┌───────────┐
                    │Zero-Length│
                    │Bypass Mux │
                    └─────┬─────┘
                          │
                          ▼
                    ┌───────────┐
                    │ STAP Mux  │
                    └─────┬─────┘
                          │
                          ▼
                    ┌───────────┐
                    │TDO Retimer│
                    └─────┬─────┘
                          │
                          ▼
                     client_tdo_o

Bypass Register
---------------

* **Width**: 1 bit
* **Purpose**: Provides minimal scan path for uninteresting TAPs in chain
* **Instruction**: BYPASS (``6'h3F``) or BYPASS_ALT (``6'h00``)
* **Also selected by**: CLAMP, HIGHZ, and undefined instructions

IDCODE Register
---------------

* **Width**: 32 bits
* **Fields**:
  - Bit [0]: Always ``1`` (mandatory)
  - Bits [11:1]: Manufacturer ID (11 bits)
  - Bits [27:12]: Part Number (16 bits)
  - Bits [31:28]: Silicon Revision (4 bits)
* **Behavior**: Captures constant IDCODE value on capture

3DCR Register (IEEE 1838)
-------------------------

* **Width**: 2 bits
* **Purpose**: Controls STAP selection for multi-die architectures
* **Fields**:
  - Bit [1]: ``stap_sel`` - Selects STAP scan path
  - Bit [0]: ``config_hold`` - Prevents reset during TLR

TDO Output Path
===============

Zero-Length Bypass
------------------

The ZERO_LENGTH_BYPASS instruction (``6'h3D``) provides direct TDI-to-TDO connection:

* Bypasses TDO retimer during data shift
* Uses explicit mux cells to avoid glitches
* Enables minimum-latency bypass mode

TDO Retiming
------------

Per IEEE 1149.1 Section 4.5.2, TDO is retimed on falling TCK edge:

.. code-block:: systemverilog

   always_ff @(negedge client_tap_ctrl_i.tck or negedge client_tap_ctrl_i.trst_n) begin
       if (!client_tap_ctrl_i.trst_n) begin
           tdo_retimed <= 1'b0;
       end else begin
           tdo_retimed <= tdo_mux;
       end
   end

STAP Interface (IEEE 1838)
==========================

The PTAP provides a STAP interface for connecting to Secondary TAPs:

Scan Control
------------

STAP scan control combines IR and DR paths:

.. code-block:: systemverilog

   stap_host_scan_ctrl_o.select     = dr_scan_ctrl.select     | ir_scan_ctrl.select;
   stap_host_scan_ctrl_o.capture_en = dr_scan_ctrl.capture_en | ir_scan_ctrl.capture_en;
   stap_host_scan_ctrl_o.shift_en   = dr_scan_ctrl.shift_en   | ir_scan_ctrl.shift_en;
   stap_host_scan_ctrl_o.update_en  = dr_scan_ctrl.update_en  | ir_scan_ctrl.update_en;

STAP Selection
--------------

When ``stap_sel`` is set in 3DCR:

* STAP scan input is routed to TDO output
* STAP receives merged IR/DR scan control
* Local TDRs are bypassed

Test Mode Persistence
=====================

The TMP controller implements IEEE 1149.1 Section 16:

State Machine
-------------

.. code-block:: text

                    ┌─────────────────────┐
                    │  TMP_PERSISTENCE_OFF│◄──── TRST/Power-on
                    │      (Normal)       │
                    └──────────┬──────────┘
                               │
                               │ CLAMP_HOLD instruction
                               ▼
                    ┌─────────────────────┐
                    │  TMP_PERSISTENCE_ON │
                    │   (Persistence)     │
                    └──────────┬──────────┘
                               │
                               │ CLAMP_RELEASE or
                               │ Bypass-Escape condition
                               ▼
                    ┌─────────────────────┐
                    │  TMP_PERSISTENCE_OFF│
                    │      (Normal)       │
                    └─────────────────────┘

Bypass-Escape Condition
-----------------------

Per IEEE 1149.1 Section 6.2.1.1, bypass-escape occurs when:

* TAP is in Update-IR state
* Explicit BYPASS instruction is loaded
* ``bypass_escape_enable`` bit is set in TMP status register

JTAG2AXI Architecture
=====================

Three JTAG2AXI bridge instances provide bus access:

Bridge Instances
----------------

1. **SMC OTP JTAG2AXI**: AXI4-Lite access to SMC OTP controller
2. **SEP OTP JTAG2AXI**: AXI4-Lite access to SEP OTP controller
3. **SMC Fabric JTAG2AXI**: Full AXI4 access to SMC fabric

Operating Modes
---------------

Each bridge supports multiple scan chains:

* **AXISingleOp**: Single read/write transaction
* **AXISeriesCtrl**: Configure series operations
* **AXISeriesDataIncr**: Series data with address increment
* **AXISeriesDataNoIncr**: Series data without address increment
* **AXISeriesDataWithErrorStatus**: Series data with error reporting

Clock Domain Crossing
---------------------

The JTAG2AXI bridges handle CDC between TCK and system clock:

* Scan registers operate in TCK domain
* AXI transactions execute in system clock domain
* Handshake-based synchronization ensures data integrity

Parameter Summary
=================

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Parameter
     - Default
     - Description
   * - BSR_ENABLE
     - 1
     - Enable boundary scan instructions
   * - EXTEST_TRAIN_ENABLE
     - 1
     - Enable EXTEST_TRAIN instruction
   * - EXTEST_PULSE_ENABLE
     - 1
     - Enable EXTEST_PULSE instruction
   * - INTEST_ENABLE
     - 1
     - Enable INTEST instruction
   * - CLAMP_ENABLE
     - 1
     - Enable CLAMP instruction
   * - HIGHZ_ENABLE
     - 1
     - Enable HIGHZ instruction
   * - RUNBIST_ENABLE
     - 1
     - Enable RUNBIST instruction
   * - TMP_ENABLE
     - 1
     - Enable TMP controller
   * - IC_RESET_ENABLE
     - 1
     - Enable IC_RESET instruction
   * - SMC_DBG_ENABLE
     - 1
     - Enable SMC debug interfaces
   * - SEP_DBG_ENABLE
     - 1
     - Enable SEP debug interface
   * - STAP_IO_ENABLE
     - 1
     - Enable STAP for chiplet connectivity
   * - NUM_IC_RESET
     - 3
     - Number of IC_RESET control bits
   * - NUM_EXTRA_STAPS
     - 0
     - Number of additional STAPs
   * - IDCODE_MFR_ID
     - 11'h000
     - IDCODE manufacturer ID
   * - IDCODE_PART_NUM
     - 16'h0000
     - IDCODE part number
   * - IDCODE_SI_REV
     - 4'h0
     - IDCODE silicon revision
   * - NUM_XTRIG_CTP
     - 8
     - Number of cross trigger ports reported in ``JTAG_CAPS`` (6-bit field, values 0-63)
   * - NUM_XTRIG_INT_CT
     - 1
     - Number of internal cross triggers reported in ``JTAG_CAPS`` (6-bit field, values 0-63)
   * - OCH_VER
     - 8'h00
     - OCH/PTAP major version encoded in ``JTAG_CAPS``
   * - smc_jtag_axi_req_t
     - logic
     - Type describing the SMC fabric AXI manager request channel
   * - smc_jtag_axi_resp_t
     - logic
     - Type describing the SMC fabric AXI manager response channel
   * - smc_otp_axil_req_t
     - logic
     - Type describing the SMC OTP AXI-Lite manager request channel
   * - smc_otp_axil_resp_t
     - logic
     - Type describing the SMC OTP AXI-Lite manager response channel
   * - sep_otp_axil_req_t
     - logic
     - Type describing the SEP OTP AXI-Lite manager request channel
   * - sep_otp_axil_resp_t
     - logic
     - Type describing the SEP OTP AXI-Lite manager response channel
   * - SMC_OTP_RD_PL_DEPTH / SMC_OTP_WR_PL_DEPTH
     - 2'h3
     - FIFO depth encoding (0-3) for SMC OTP read/write queues inside ``jtag2axi``
   * - SEP_OTP_RD_PL_DEPTH / SEP_OTP_WR_PL_DEPTH
     - 2'h3
     - FIFO depth encoding (0-3) for SEP OTP read/write queues inside ``jtag2axi``
   * - SMC_RD_PL_DEPTH / SMC_WR_PL_DEPTH
     - 2'h3
     - FIFO depth encoding (0-3) for SMC fabric read/write queues inside ``jtag2axi``

AXI Type Parameters
-------------------

The ``*_req_t`` and ``*_resp_t`` type parameters must match the structs emitted by the
``AXI_TYPEDEF_ALL`` or ``AXI_LITE_TYPEDEF_ALL`` macros used elsewhere in the design. The
PTAP introspects these types (see ``jtag_jtag2axi_caps_reg.sv``) to determine address/data
widths, so mismatched typedefs will lead to incorrect capability reporting.
