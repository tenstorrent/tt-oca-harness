===========
Integration
===========

This section describes how to integrate the JTAG PTAP IP into a system.

Clock and Reset
===============

Clock Domains
-------------

The PTAP operates in two clock domains:

**TCK Domain**:

* All JTAG logic operates on TCK (Test Clock)
* TDO is retimed on falling TCK edge
* Scan registers capture on rising TCK edge

**System Clock Domain** (``clk_i``):

* JTAG2AXI bridges use system clock for AXI transactions
* Clock domain crossing handled internally by jtag2axi

Reset Sources
-------------

**TRST_n (Test Reset)**:

* Asynchronous active-low reset
* Resets TAP controller to TEST_LOGIC_RESET
* Resets all data registers (except config_hold protected registers)
* Optional per IEEE 1149.1 but recommended

**System Reset** (``rst_n_i``):

* Active-low synchronous reset for JTAG2AXI modules
* Does not affect TAP controller or scan registers
* Used for AXI interface initialization

**Power-On Reset** (``pwr_on_rst_ni``):

* Asynchronous active-low power-on reset
* Combined internally with TRST_n to reset JTAG logic during power-on
* Ensures JTAG state machine is in a known state after power-up
* Connect to system cold reset or power-on reset signal

**Test-Logic-Reset (TLR)**:

* TAP state machine enters TLR via TMS sequence (5+ cycles high)
* Resets instruction register to IDCODE
* Resets data registers unless protected by config_hold bit

JTAG Interface
==============

Pin Connections
---------------

.. list-table::
   :widths: 20 15 65
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - TCK
     - Input
     - Test clock (typically 10-50 MHz)
   * - TMS
     - Input
     - Test mode select (controls TAP state)
   * - TDI
     - Input
     - Test data input (serial data in)
   * - TDO
     - Output
     - Test data output (serial data out)
   * - TDO_OEN
     - Output
     - TDO output enable (active high)
   * - TRST_n
     - Input
     - Test reset (active low, optional)

Timing Requirements
-------------------

Per IEEE 1149.1:

* TDI and TMS sampled on rising TCK edge
* TDO changes on falling TCK edge
* TRST_n is asynchronous

.. code-block:: text

   TCK     ____/‾‾‾‾\____/‾‾‾‾\____/‾‾‾‾\____
   TMS/TDI ____|‾‾‾‾|____|‾‾‾‾|____|‾‾‾‾|____
                ↑ Setup      ↑ Sample
   TDO     ______|‾‾‾‾‾‾‾‾‾‾|________________
                      ↓ Launch (falling edge)

Build Integration
=================

RTL Files
---------

Add the following RTL files to your build:

**PTAP Core Files** (``hw/ip/jtag_ptap/rtl/``):

* ``jtag_ptap.sv`` - Top module
* ``jtag_tap_ctrlr.sv`` - TAP controller
* ``jtag_tap_pkg.sv`` - TAP state definitions
* ``jtag_inst_reg.sv`` - Instruction register
* ``jtag_inst_reg_pkg.sv`` - Instruction definitions
* ``jtag_byp_reg.sv`` - Bypass register
* ``jtag_inv_byp_reg.sv`` - Inverted bypass register
* ``jtag_idcode_reg.sv`` - IDCODE register
* ``jtag_3dcr_reg.sv`` - 3DCR register
* ``jtag_tmp.sv`` - TMP controller
* ``jtag_tmp_pkg.sv`` - TMP definitions
* ``jtag_tmp_status_reg.sv`` - TMP status register
* ``jtag_ic_reset_reg.sv`` - IC reset register
* ``jtag_debug_ctrl_reg.sv`` - Debug control register
* ``jtag_caps_reg.sv`` - Capabilities register
* ``jtag_jtag2axi_caps_reg.sv`` - JTAG2AXI capabilities register

**Primitive Files** (``hw/common/och_prim/rtl/``):

* ``prim_jtag_pkg.sv`` - JTAG primitive types
* ``prim_jtag_scan_reg.sv`` - Scan register primitive
* ``prim_stdmux2.sv`` - 2-input mux primitive
* ``jtag2axi.sv`` - JTAG-to-AXI bridge

**Dependencies**:

* AXI package with type definition macros

File List Example
-----------------

.. code-block:: text

   # JTAG PTAP IP
   hw/common/och_prim/rtl/prim_jtag_pkg.sv
   hw/common/och_prim/rtl/prim_jtag_scan_reg.sv
   hw/common/och_prim/rtl/prim_stdmux2.sv
   hw/ip/jtag2axi/rtl/jtag2axi.sv
   hw/ip/jtag_ptap/rtl/jtag_tap_pkg.sv
   hw/ip/jtag_ptap/rtl/jtag_inst_reg_pkg.sv
   hw/ip/jtag_ptap/rtl/jtag_tmp_pkg.sv
   hw/ip/jtag_ptap/rtl/jtag_tap_ctrlr.sv
   hw/ip/jtag_ptap/rtl/jtag_inst_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_byp_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_inv_byp_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_idcode_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_3dcr_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_tmp.sv
   hw/ip/jtag_ptap/rtl/jtag_tmp_status_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_ic_reset_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_debug_ctrl_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_caps_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_jtag2axi_caps_reg.sv
   hw/ip/jtag_ptap/rtl/jtag_ptap.sv

Instantiation Example
=====================

Basic Instantiation
-------------------

.. code-block:: systemverilog

   jtag_ptap #(
       // Feature enables
       .BSR_ENABLE          (1),
       .EXTEST_TRAIN_ENABLE (1),
       .EXTEST_PULSE_ENABLE (1),
       .INTEST_ENABLE       (1),
       .CLAMP_ENABLE        (1),
       .HIGHZ_ENABLE        (1),
       .RUNBIST_ENABLE      (1),
       .TMP_ENABLE          (1),
       .IC_RESET_ENABLE     (1),
       .SMC_DBG_ENABLE      (1),
       .SEP_DBG_ENABLE      (1),
       .STAP_IO_ENABLE      (1),

       // Configuration
       .NUM_IC_RESET        (3),
       .NUM_EXTRA_STAPS     (0),
       .IDCODE_MFR_ID       (11'h49E),  // Tenstorrent
       .IDCODE_PART_NUM     (16'h1234),
       .IDCODE_SI_REV       (4'h1),

       // Cross trigger configuration
       .NUM_XTRIG_CTP       (8),
       .NUM_XTRIG_INT_CT    (1),
       .OCH_VER             (8'h01),

       // AXI type parameters
       .smc_jtag_axi_req_t  (smc_axi_req_t),
       .smc_jtag_axi_resp_t (smc_axi_resp_t),
       .smc_otp_axil_req_t  (smc_otp_axil_req_t),
       .smc_otp_axil_resp_t (smc_otp_axil_resp_t),
       .sep_otp_axil_req_t  (sep_otp_axil_req_t),
       .sep_otp_axil_resp_t (sep_otp_axil_resp_t),

       // Pipeline depth parameters
       .SMC_OTP_RD_PL_DEPTH (2'h3),
       .SMC_OTP_WR_PL_DEPTH (2'h3),
       .SEP_OTP_RD_PL_DEPTH (2'h3),
       .SEP_OTP_WR_PL_DEPTH (2'h3),
       .SMC_RD_PL_DEPTH     (2'h3),
       .SMC_WR_PL_DEPTH     (2'h3)
   ) u_jtag_ptap (
       // Power-on reset
       .pwr_on_rst_ni       (pwr_on_rst_n),

       // JTAG interface
       .client_tap_ctrl_i   (jtag_tap_ctrl),
       .client_tdi_i        (jtag_tdi),
       .client_tdo_o        (jtag_tdo),
       .client_tdo_oen_o    (jtag_tdo_oen),

       // Internal TAP control
       .host_tap_ctrl_o     (internal_tap_ctrl),

       // Boundary scan interface
       .bsr_host_scan_ctrl_o  (bsr_scan_ctrl),
       .bsr_host_scan_in_i    (bsr_scan_out),
       .bsr_host_scan_out_o   (bsr_scan_in),

       // iJTAG interface
       .ijtag_host_scan_ctrl_o  (ijtag_scan_ctrl),
       .ijtag_host_scan_in_i    (ijtag_scan_out),
       .ijtag_host_scan_out_o   (ijtag_scan_in),

       // STAP interface
       .stap_host_scan_ctrl_o   (stap_scan_ctrl),
       .stap_host_scan_in_i     (stap_scan_out),
       .stap_host_scan_out_o    (stap_scan_in),

       // Status outputs
       .inst_decoded_o      (inst_decoded),
       .current_state_o     (tap_state),

       // IC reset control
       .ic_reset_ovrd_o     (ic_reset_ovrd),
       .ic_reset_ctrl_n_o   (ic_reset_ctrl_n),

       // Debug control
       .cla_clock_stop_i    (cla_clock_stop),
       .jtag_clock_stop_o   (jtag_clock_stop),
       .cla_clock_stop_en_o (cla_clock_stop_en),
       .boot_stall_ovrd_o   (boot_stall_ovrd),
       .boot_stall_o        (boot_stall),

       // System clock and reset
       .clk_i               (clk_sys),
       .rst_n_i             (rst_n_sys),

       // AXI interfaces
       .axi_smc_dbg_req_o        (axi_smc_dbg_req),
       .axi_smc_dbg_resp_i       (axi_smc_dbg_resp),
       .axil_smc_otp_jtag_req_o  (axil_smc_otp_req),
       .axil_smc_otp_jtag_resp_i (axil_smc_otp_resp),
       .axil_sep_otp_jtag_req_o  (axil_sep_otp_req),
       .axil_sep_otp_jtag_resp_i (axil_sep_otp_resp)
   );

.. note::
   The ``jtag_caps_reg`` module includes compile-time assertions that verify all
   count parameters fit within their allocated bit fields:

   * ``NUM_XTRIG_CTP``: 0-63 (6 bits)
   * ``NUM_XTRIG_INT_CT``: 0-63 (6 bits)
   * ``NUM_IC_RESET``: 0-15 (4 bits)
   * ``NUM_EXTRA_STAPS``: 0-15 (4 bits)

   Exceeding these limits will cause an elaboration-time fatal error.

Minimal Configuration
---------------------

For a minimal PTAP without optional features:

.. code-block:: systemverilog

   jtag_ptap #(
       .BSR_ENABLE          (0),
       .EXTEST_TRAIN_ENABLE (0),
       .EXTEST_PULSE_ENABLE (0),
       .INTEST_ENABLE       (0),
       .CLAMP_ENABLE        (0),
       .HIGHZ_ENABLE        (0),
       .RUNBIST_ENABLE      (0),
       .TMP_ENABLE          (0),
       .IC_RESET_ENABLE     (0),
       .SMC_DBG_ENABLE      (0),
       .SEP_DBG_ENABLE      (0),
       .STAP_IO_ENABLE      (0),
       .IDCODE_MFR_ID       (11'h49E),
       .IDCODE_PART_NUM     (16'h0001),
       .IDCODE_SI_REV       (4'h0)
   ) u_jtag_ptap (
       // ... port connections
   );

Interface Connections
=====================

Boundary Scan Register
----------------------

Connect the BSR chain to the PTAP:

.. code-block:: systemverilog

   // BSR chain connection
   assign bsr_scan_ctrl = ptap.bsr_host_scan_ctrl_o;
   assign bsr_chain_input = ptap.bsr_host_scan_out_o;  // TDI to BSR
   assign ptap_bsr_scan_in = bsr_chain_output;          // BSR to TDO

iJTAG Network
-------------

Connect the iJTAG SIB network:

.. code-block:: systemverilog

   // iJTAG network connection
   assign ijtag_network_scan_ctrl = ptap.ijtag_host_scan_ctrl_o;
   assign ijtag_network_input = ptap.ijtag_host_scan_out_o;
   assign ptap_ijtag_scan_in = ijtag_network_output;

STAP Interface
--------------

Connect Secondary TAPs via the STAP interface:

.. code-block:: systemverilog

   // STAP connection
   assign stap_scan_ctrl = ptap.stap_host_scan_ctrl_o;
   assign stap_tdi = ptap.stap_host_scan_out_o;
   assign ptap_stap_scan_in = stap_tdo;

IC Reset Integration
--------------------

Connect IC reset controls:

.. code-block:: systemverilog

   // IC reset control
   assign reset_from_jtag = ptap.ic_reset_ovrd_o & ~ptap.ic_reset_ctrl_n_o;
   assign system_reset_n = external_reset_n &
                           (ptap.ic_reset_ovrd_o[0] ? ptap.ic_reset_ctrl_n_o[0] : 1'b1);

Debug Control Integration
-------------------------

Connect debug control signals:

.. code-block:: systemverilog

   // Clock control
   assign clock_enable = ~(ptap.jtag_clock_stop_o |
                           (ptap.cla_clock_stop_en_o & cla_clock_stop_req));

   // Boot stall
   assign boot_stall_active = ptap.boot_stall_ovrd_o ?
                              ptap.boot_stall_o : normal_boot_stall;

Synthesis Constraints
=====================

Clock Definitions
-----------------

.. code-block:: tcl

   # Define TCK as asynchronous to system clock
   create_clock -name TCK -period 100.0 [get_ports TCK]

   # Set TCK as asynchronous to system clock
   set_clock_groups -asynchronous -group [get_clocks TCK] -group [get_clocks clk_sys]

Input/Output Delays
-------------------

.. code-block:: tcl

   # JTAG input delays (relative to TCK)
   set_input_delay -clock TCK -max 10.0 [get_ports {TDI TMS}]
   set_input_delay -clock TCK -min 2.0  [get_ports {TDI TMS}]

   # TDO output delay (falling edge launch)
   set_output_delay -clock TCK -max 10.0 -clock_fall [get_ports TDO]
   set_output_delay -clock TCK -min 2.0  -clock_fall [get_ports TDO]

False Paths
-----------

.. code-block:: tcl

   # TRST is asynchronous
   set_false_path -from [get_ports TRST_n]

   # Static configuration (if parameters don't change)
   set_false_path -from [get_pins u_jtag_caps_reg/CAPS_VALUE*]

Parameter Selection Guidelines
==============================

Feature Selection
-----------------

Choose appropriate features based on requirements:

* **BSR_ENABLE**: Enable for boundary scan test capability
* **TMP_ENABLE**: Enable for hot-swap or power management scenarios
* **IC_RESET_ENABLE**: Enable for JTAG-controlled chip reset
* **SMC_DBG_ENABLE**: Enable for AXI bus debug access
* **STAP_IO_ENABLE**: Enable for multi-die configurations

IDCODE Selection
----------------

Follow IEEE 1149.1 IDCODE format:

* **Manufacturer ID**: Obtain from JEDEC (11 bits)
* **Part Number**: Assign unique value per device (16 bits)
* **Silicon Revision**: Increment for each silicon revision (4 bits)

Pipeline Depth
--------------

Set JTAG2AXI pipeline depths based on:

* Higher depth = more outstanding transactions
* Lower depth = simpler implementation
* ``2'h3`` (maximum) recommended for best throughput

Verification Checklist
======================

Pre-Silicon Verification
------------------------

1. ☐ BYPASS instruction scans single bit
2. ☐ IDCODE returns expected value
3. ☐ All instructions select correct TDR
4. ☐ TDO timing meets IEEE 1149.1 requirements
5. ☐ TRST resets to TEST_LOGIC_RESET
6. ☐ TLR state reached via 5 TMS=1 cycles
7. ☐ 3DCR config_hold prevents TLR reset
8. ☐ IC_RESET controls resets correctly
9. ☐ JTAG2AXI transactions complete successfully

Post-Silicon Validation
-----------------------

1. ☐ TCK frequency meets specification
2. ☐ Setup/hold margins adequate
3. ☐ TDO drive strength sufficient
4. ☐ JTAG chain integrity verified
5. ☐ IDCODE readable by debug tools
