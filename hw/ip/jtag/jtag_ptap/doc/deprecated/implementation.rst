==============
Implementation
==============

This section describes the implementation details of each module in the JTAG PTAP IP.

Top Module: jtag_ptap
=====================

The top module integrates all sub-modules and implements the data path multiplexing.

**File**: ``rtl/jtag_ptap.sv``

**Key Features**:

* Parameterized feature enables
* Instruction-based TDR selection
* STAP interface for multi-die connectivity
* JTAG2AXI bridge integration
* IEEE 1149.1 compliant TDO retiming

Port Interface
--------------

**JTAG Interface (Primary)**:

* ``client_tap_ctrl_i``: TAP control inputs (TMS, TRST_n, TCK)
* ``client_tdi_i``: Test data input
* ``client_tdo_o``: Test data output
* ``client_tdo_oen_o``: TDO output enable

**Internal JTAG Interface**:

* ``host_tap_ctrl_o``: TAP control outputs to internal logic

**Boundary Scan Interface**:

* ``bsr_host_scan_ctrl_o``: BSR scan control
* ``bsr_host_scan_in_i``: BSR scan data in
* ``bsr_host_scan_out_o``: BSR scan data out

**iJTAG Interface**:

* ``ijtag_host_scan_ctrl_o``: iJTAG scan control
* ``ijtag_host_scan_in_i``: iJTAG scan data in
* ``ijtag_host_scan_out_o``: iJTAG scan data out

**STAP Interface**:

* ``stap_host_scan_ctrl_o``: STAP scan control
* ``stap_host_scan_in_i``: STAP scan data in
* ``stap_host_scan_out_o``: STAP scan data out

**Debug Control Interface**:

* ``ic_reset_ovrd_o``: IC reset override enables
* ``ic_reset_ctrl_n_o``: IC reset control values
* ``jtag_clock_stop_o``: Clock stop request
* ``cla_clock_stop_en_o``: CLA clock stop enable
* ``boot_stall_ovrd_o``: Boot stall override
* ``boot_stall_o``: Boot stall value

**AXI Interfaces**:

* ``axi_smc_dbg_req_o/resp_i``: SMC fabric AXI4 interface
* ``axil_smc_otp_jtag_req_o/resp_i``: SMC OTP AXI4-Lite interface
* ``axil_sep_otp_jtag_req_o/resp_i``: SEP OTP AXI4-Lite interface

TAP Controller: jtag_tap_ctrlr
==============================

Implements the IEEE 1149.1 TAP state machine with TMP extensions.

**File**: ``rtl/jtag_tap_ctrlr.sv``

**Key Features**:

* 16-state IEEE 1149.1 state machine
* One-hot state encoding
* TMP controller integration
* RUNBIST pause support
* Generates all scan control signals

State Machine Implementation
----------------------------

.. code-block:: systemverilog

   // State transitions on positive TCK edge
   always_ff @(posedge tap_ctrl_i.tck or negedge tap_ctrl_i.trst_n) begin
       if (!tap_ctrl_i.trst_n) begin
           current_state <= TEST_LOGIC_RESET;
       end else begin
           current_state <= next_state;
       end
   end

TMP Integration
---------------

When TMP persistence mode is active:

* TAP controller is held in Run-Test/Idle
* TMS transitions are ignored
* Exit requires CLAMP_RELEASE or bypass-escape

Instruction Register: jtag_inst_reg
===================================

Implements the 6-bit instruction register and decoder.

**File**: ``rtl/jtag_inst_reg.sv``

**Package**: ``rtl/jtag_inst_reg_pkg.sv``

**Key Features**:

* 6-bit shift register
* Captures ``6'b000001`` (IDCODE) on capture
* One-hot decoded outputs
* Default instruction: IDCODE

Instruction Decoding
--------------------

.. code-block:: systemverilog

   // One-hot decode using shift operator
   assign inst_decoded_o =
       jtag_instruction_decoded_e'(DECODED_IR_WIDTH'(1'b1) << ir_reg_q);

BYPASS Register: jtag_byp_reg
=============================

Implements the standard 1-bit bypass register.

**File**: ``rtl/jtag_byp_reg.sv``

**Key Features**:

* 1-bit shift register
* Captures ``0`` on capture
* Uses ``prim_jtag_scan_reg`` primitive

IDCODE Register: jtag_idcode_reg
================================

Implements the 32-bit IDCODE register.

**File**: ``rtl/jtag_idcode_reg.sv``

**Key Features**:

* 32-bit read-only register
* Parameterized ID fields
* Bit[0] always ``1`` per IEEE 1149.1

Configuration Parameters
------------------------

.. code-block:: systemverilog

   parameter logic [10:0]  IDCODE_MFR_ID   = 11'h000,
   parameter logic [15:0]  IDCODE_PART_NUM = 16'h0000,
   parameter logic [3:0]   IDCODE_SI_REV   = 4'h0

3DCR Register: jtag_3dcr_reg
============================

Implements the IEEE 1838 3-Die Control Register.

**File**: ``rtl/jtag_3dcr_reg.sv``

**Key Features**:

* 2-bit control register
* Config hold prevents TLR reset
* Controls STAP selection

Reset Control
-------------

.. code-block:: systemverilog

   // 3DCR reset controlled by config_hold
   reg_scan_ctrl.rst_n = tap_ctrl_i.trst_n &&
                         (config_hold || scan_ctrl_i.rst_n);

TMP Controller: jtag_tmp
========================

Implements the IEEE 1149.1 Section 16 Test Mode Persistence controller.

**File**: ``rtl/jtag_tmp.sv``

**Package**: ``rtl/jtag_tmp_pkg.sv``

**Key Features**:

* Two-state machine (Persistence-On/Off)
* CLAMP_HOLD enters persistence
* CLAMP_RELEASE exits persistence
* Bypass-escape condition support

State Machine
-------------

.. code-block:: systemverilog

   typedef enum logic {
       TMP_PERSISTENCE_OFF = 1'b0,
       TMP_PERSISTENCE_ON  = 1'b1
   } tmp_state_e;

Bypass-Escape Condition
-----------------------

.. code-block:: systemverilog

   assign bypass_escape_condition =
       update_ir_i & bypass_selected_i & bypass_escape_enable_i;

TMP Status Register: jtag_tmp_status_reg
========================================

Implements the TMP status register per IEEE 1149.1 Section 16.1.

**File**: ``rtl/jtag_tmp_status_reg.sv``

**Key Features**:

* 2-bit register
* TMP status (read-only, reflects controller state)
* Bypass-escape enable (read/write)

IC_RESET Register: jtag_ic_reset_reg
====================================

Implements the IC reset control register per IEEE 1149.1 Section 17.

**File**: ``rtl/jtag_ic_reset_reg.sv``

**Key Features**:

* Parameterized number of reset ports
* Reset hold bit (TRST-only reset)
* Per-port enable and control bits

Register Structure
------------------

The register consists of two scan registers:

1. ``reset_enable_control_scan_reg``: 2*NUM_IC_RESET bits (closer to TDI)
2. ``reset_hold_scan_reg``: 1 bit (closer to TDO)

Debug Control Register: jtag_debug_ctrl_reg
===========================================

Implements the debug control register.

**File**: ``rtl/jtag_debug_ctrl_reg.sv``

**Key Features**:

* 5-bit register
* Clock stop control
* Boot stall override
* CLA status capture (read-only)

Capabilities Register: jtag_caps_reg
====================================

Implements the read-only JTAG capabilities register.

**File**: ``rtl/jtag_caps_reg.sv``

**Key Features**:

* 40-bit read-only register
* Reports all PTAP configuration options
* Parameterized based on feature enables
* Compile-time assertions validate parameter ranges

Capabilities Value Construction
-------------------------------

.. code-block:: systemverilog

   localparam logic [REG_WIDTH-1:0] CAPS_VALUE = {
       u6_t'(NUM_XTRIG_INT_CT),  // Bits [39:34]
       u6_t'(NUM_XTRIG_CTP),     // Bits [33:28]
       u4_t'(NUM_EXTRA_STAPS),   // Bits [27:24]
       STAP_IO_ENABLE,           // Bit  [23]
       SEP_DBG_ENABLE,           // Bit  [22]
       SMC_DBG_ENABLE,           // Bit  [21]
       u4_t'(NUM_IC_RESET),      // Bits [20:17]
       IC_RESET_ENABLE,          // Bit  [16]
       TMP_ENABLE,               // Bit  [15]
       RUNBIST_ENABLE,           // Bit  [14]
       HIGHZ_ENABLE,             // Bit  [13]
       CLAMP_ENABLE,             // Bit  [12]
       INTEST_ENABLE,            // Bit  [11]
       EXTEST_PULSE_ENABLE,      // Bit  [10]
       EXTEST_TRAIN_ENABLE,      // Bit  [9]
       BSR_ENABLE,               // Bit  [8]
       OCH_VER                   // Bits [7:0]
   };

JTAG2AXI Capabilities Register: jtag_jtag2axi_caps_reg
======================================================

Implements the read-only JTAG2AXI capabilities register.

**File**: ``rtl/jtag_jtag2axi_caps_reg.sv``

**Key Features**:

* 14-bit read-only register
* Reports AXI interface characteristics
* Derived from AXI type parameter

Type Introspection
------------------

AXI parameters are extracted from the type parameter:

.. code-block:: systemverilog

   axi_req_t dummy_req;
   localparam int unsigned AXI_ADDR_WIDTH = $bits(dummy_req.aw.addr);
   localparam int unsigned AXI_DATA_WIDTH = $bits(dummy_req.w.data);

JTAG2AXI Bridge: jtag2axi
==============================

JTAG-to-AXI bridge module from ``hw/ip/jtag2axi/``.

**File**: ``hw/ip/jtag2axi/rtl/jtag2axi.sv``

**Key Features**:

* Multiple scan chain modes
* Single and series operation support
* Clock domain crossing
* Pipeline depth configuration

Operating Modes
---------------

* **AXISingleOp**: Single read/write transaction per scan
* **AXISeriesCtrl**: Configure base address and options
* **AXISeriesDataIncr**: Data with auto-incrementing address
* **AXISeriesDataNoIncr**: Data without address increment
* **AXISeriesDataWithErrorStatus**: Data with error reporting

TDR Multiplexer Implementation
==============================

The TDR multiplexer selects the active data register based on instruction:

.. code-block:: systemverilog

   always_comb begin
       if (ir_scan_ctrl.select) begin
           tdr_mux = inst_reg_scan_out;
       end else begin
           unique case (1'b1)
               inst_decoded_o[BYPASS_INSTR],
               inst_decoded_o[BYPASS_ALT_INSTR]:
                   tdr_mux = byp_reg_scan_out;
               inst_decoded_o[IDCODE_INSTR]:
                   tdr_mux = idcode_reg_scan_out;
               // ... additional cases
               default:
                   tdr_mux = byp_reg_scan_out;
           endcase
       end
   end

STAP Selection Mux
==================

The STAP selection uses explicit mux cells to avoid glitches:

.. code-block:: systemverilog

   // Zero-length bypass mux
   prim_stdmux2 u_zlb_tdr_mux (
       .i_I0  (tdr_mux),
       .i_I1  (client_tdi_i),
       .i_SEL (inst_decoded_o[ZERO_LENGTH_BYPASS_INSTR] && dr_scan_select_reg),
       .o_Y   (zlb_tdr_mux)
   );

   // STAP selection mux
   prim_stdmux2 u_tdo_mux (
       .i_I0  (zlb_tdr_mux),
       .i_I1  (stap_host_scan_in_i),
       .i_SEL (stap_select),
       .o_Y   (tdo_mux)
   );

TDO Retiming Implementation
===========================

TDO is retimed on falling TCK edge per IEEE 1149.1:

.. code-block:: systemverilog

   always_ff @(negedge client_tap_ctrl_i.tck or negedge client_tap_ctrl_i.trst_n) begin
       if (!client_tap_ctrl_i.trst_n) begin
           tdo_retimed <= 1'b0;
           dr_scan_select_reg <= 1'b0;
       end else begin
           tdo_retimed <= tdo_mux;
           dr_scan_select_reg <= dr_scan_ctrl.select;
       end
   end

Zero-Length Bypass Exception
----------------------------

ZERO_LENGTH_BYPASS bypasses the retimer for minimum latency:

.. code-block:: systemverilog

   prim_stdmux2 u_tdo_bypass_mux (
       .i_I0  (tdo_retimed),
       .i_I1  (tdo_mux),
       .i_SEL (inst_decoded_o[ZERO_LENGTH_BYPASS_INSTR] && dr_scan_select_reg),
       .o_Y   (client_tdo_o)
   );

Conditional Generation
======================

Features are conditionally generated based on parameters:

.. code-block:: systemverilog

   // 3DCR register only when STAPs are enabled
   localparam bit PTAP_3DCR_ENABLE =
       (STAP_IO_ENABLE != 0 || SEP_DBG_ENABLE != 0 || NUM_EXTRA_STAPS != 0);

   if (PTAP_3DCR_ENABLE) begin : gen_tap_3dcr_reg
       jtag_3dcr_reg u_jtag_3dcr_reg (...);
   end else begin : gen_tap_3dcr_tie_off
       assign stap_select = 1'b0;
       assign tap_3dcr_reg_scan_out = 1'b0;
   end

Common Primitives
=================

The PTAP uses primitives from ``hw/ip/jtag2axi/``:

* ``prim_jtag_scan_reg``: Standard JTAG scan register
* ``prim_stdmux2``: 2-input multiplexer for glitch-free switching
* ``jtag2axi``: JTAG-to-AXI bridge

Package Dependencies
====================

* ``prim_jtag_pkg``: JTAG primitive type definitions
* ``jtag_tap_pkg``: TAP state machine types
* ``jtag_inst_reg_pkg``: Instruction register definitions
* ``jtag_tmp_pkg``: TMP controller types
