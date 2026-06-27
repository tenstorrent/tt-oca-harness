===========
Integration
===========

This section describes how to integrate the JTAG Interface Unit into a system.

Clock and Reset
===============

Clock Domains
-------------

The JTAG Interface Unit operates in two clock domains:

**TCK Domain**:

* All JTAG logic (PTAP, STAPs, SIBs) operates on TCK
* TDO is retimed on falling TCK edge
* Scan registers capture on rising TCK edge

**System Clock Domain** (``clk_i``):

* JTAG2AXI bridges use system clock for AXI transactions
* Clock domain crossing handled internally by ``jtag2axi``

Reset Sources
-------------

**TRST_n (Test Reset)**:

* Asynchronous active-low reset
* Resets PTAP TAP controller to TEST_LOGIC_RESET
* Resets all data registers and STAP 3DCRs (except config_hold protected)

**System Reset** (``rst_n_i``):

* Active-low synchronous reset for JTAG2AXI modules
* Does not affect TAP controller or scan registers

**Power-On Reset** (``pwr_on_rst_ni``):

* Asynchronous active-low power-on reset
* Combined internally with TRST_n to reset JTAG logic during power-on
* Ensures JTAG state machine is in a known state after power-up
* Connect to system cold reset or power-on reset signal

**Test-Logic-Reset (TLR)**:

* TAP state machine enters TLR via TMS sequence (5+ cycles high)
* Resets instruction register to IDCODE
* Resets STAP 3DCRs unless ``config_hold`` bit is set

Build Integration
=================

RTL Files
---------

Add the following RTL files to your build:

**JTAG Interface Unit** (``hw/comp/jtag_intf_unit/rtl/``):

* ``jtag_intf_unit.sv`` - Top module

**PTAP Files** (``hw/ip/jtag_ptap/rtl/``):

* ``jtag_ptap.sv`` - Primary TAP top module
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

**STAP Files** (``hw/ip/jtag_stap/rtl/``):

* ``jtag_stap.sv`` - Secondary TAP module

**Primitive Files** (``hw/common/och_prim/rtl/``):

* ``prim_jtag_pkg.sv`` - JTAG primitive types
* ``prim_jtag_scan_reg.sv`` - Scan register primitive
* ``prim_jtag_sib_mux_pre.sv`` - SIB with mux before register
* ``prim_jtag_sib_mux_post.sv`` - SIB with mux after register
* ``prim_stdmux2.sv`` - 2-input mux primitive
* ``jtag2axi.sv`` - JTAG-to-AXI bridge

**Dependencies**:

* AXI package with type definition macros

Instantiation Example
=====================

Basic Instantiation
-------------------

.. code-block:: systemverilog

   jtag_intf_unit #(
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
       .NUM_EXTRA_STAPS     (2),       // Two additional local STAPs
       .IDCODE_MFR_ID       (11'h49E), // Tenstorrent
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
   ) u_jtag_intf_unit (
       // System clock and reset
       .clk_i                      (clk_sys),
       .rst_n_i                    (rst_n_sys),
       .pwr_on_rst_ni              (pwr_on_rst_n),

       // Primary JTAG interface
       .ptap_client_tap_ctrl_i     (jtag_tap_ctrl),
       .ptap_client_tdi_i          (jtag_tdi),
       .ptap_client_tdo_o          (jtag_tdo),
       .ptap_client_tdo_oen_o      (jtag_tdo_oen),

       // Boundary scan interface
       .bsr_host_scan_ctrl_o       (bsr_scan_ctrl),
       .bsr_host_scan_in_i         (bsr_chain_out),
       .bsr_host_scan_out_o        (bsr_chain_in),

       // I/O STAP interface (chiplet-to-chiplet)
       .stap_io_host_tap_ctrl_o    (remote_tap_ctrl),
       .stap_io_host_tdi_i         (remote_tdo),
       .stap_io_host_tdo_o         (remote_tdi),
       .stap_io_host_tdo_oen_o     (remote_tdo_oen),

       // SEP Debug STAP interface
       .stap_sep_host_tap_ctrl_o   (sep_tap_ctrl),
       .stap_sep_host_tdi_i        (sep_tdo),
       .stap_sep_host_tdo_o        (sep_tdi),
       .stap_sep_host_tdo_oen_o    (sep_tdo_oen),

       // Extra STAP interfaces
       .stap_extra_host_tap_ctrl_o (extra_tap_ctrl),
       .stap_extra_host_tdi_i      (extra_tdo),
       .stap_extra_host_tdo_o      (extra_tdi),
       .stap_extra_host_tdo_oen_o  (extra_tdo_oen),

       // Extended STAP scan interface
       .stap_host_scan_ctrl_o      (ext_stap_scan_ctrl),
       .stap_host_scan_in_i        (ext_stap_scan_out),
       .stap_host_scan_out_o       (ext_stap_scan_in),

       // iJTAG DFT interface
       .dft_host_scan_ctrl_o       (dft_scan_ctrl),
       .dft_host_scan_in_i         (dft_scan_out),
       .dft_host_scan_out_o        (dft_scan_in),

       // iJTAG DFD interface
       .dfd_host_scan_ctrl_o       (dfd_scan_ctrl),
       .dfd_host_scan_in_i         (dfd_scan_out),
       .dfd_host_scan_out_o        (dfd_scan_in),

       // AXI interfaces
       .axi_smc_dbg_req_o          (axi_smc_dbg_req),
       .axi_smc_dbg_resp_i         (axi_smc_dbg_resp),
       .axil_smc_otp_jtag_req_o    (axil_smc_otp_req),
       .axil_smc_otp_jtag_resp_i   (axil_smc_otp_resp),
       .axil_sep_otp_jtag_req_o    (axil_sep_otp_req),
       .axil_sep_otp_jtag_resp_i   (axil_sep_otp_resp),

       // Clock control
       .jtag_clock_stop_o          (jtag_clock_stop),
       .cla_clock_stop_i           (cla_clock_stop),
       .cla_clock_stop_en_o        (cla_clock_stop_en),

       // Boot stall control
       .boot_stall_ovrd_o          (boot_stall_ovrd),
       .boot_stall_o               (boot_stall),

       // Reset control
       .ic_reset_ovrd_o            (ic_reset_ovrd),
       .ic_reset_ctrl_n_o          (ic_reset_ctrl_n),

       // TAP internal state
       .ptap_state_o               (tap_state),
       .ptap_inst_decoded_o        (inst_decoded)
   );

Minimal Configuration
---------------------

For a minimal configuration without optional features:

.. code-block:: systemverilog

   jtag_intf_unit #(
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
       .NUM_EXTRA_STAPS     (0),
       .IDCODE_MFR_ID       (11'h49E),
       .IDCODE_PART_NUM     (16'h0001),
       .IDCODE_SI_REV       (4'h0)
   ) u_jtag_intf_unit (
       // ... minimal port connections
   );

Interface Connections
=====================

STAP Chain Connection
---------------------

The STAP chain automatically connects internally. External connections are only needed for:

* **I/O STAP Host**: Connect to chiplet I/O pads for remote PTAP access
* **SEP STAP Host**: Connect to SEP debug interface
* **Extra STAP Hosts**: Connect to local on-chip TAPs
* **Extended STAP Scan**: Connect to additional external STAP chains

.. code-block:: systemverilog

   // I/O STAP to chiplet I/O pads
   assign chiplet_tms_o  = stap_io_host_tap_ctrl.tms;
   assign chiplet_tck_o  = stap_io_host_tap_ctrl.tck;
   assign chiplet_trst_n_o = stap_io_host_tap_ctrl.trst_n;
   assign chiplet_tdi_o  = stap_io_host_tdo;
   assign stap_io_host_tdi = chiplet_tdo_i;

   // SEP debug connection
   assign sep_debug_tap_ctrl = stap_sep_host_tap_ctrl;
   assign sep_debug_tdi = stap_sep_host_tdo;
   assign stap_sep_host_tdi = sep_debug_tdo;

iJTAG Network Connection
------------------------

Connect DFT and DFD instrument networks to the SIB interfaces:

.. code-block:: systemverilog

   // DFT instrument network
   assign dft_network_scan_ctrl = dft_host_scan_ctrl;
   assign dft_network_scan_in = dft_host_scan_out;
   assign dft_host_scan_in = dft_network_scan_out;

   // DFD instrument network
   assign dfd_network_scan_ctrl = dfd_host_scan_ctrl;
   assign dfd_network_scan_in = dfd_host_scan_out;
   assign dfd_host_scan_in = dfd_network_scan_out;

Boundary Scan Connection
------------------------

Connect the BSR chain:

.. code-block:: systemverilog

   // BSR chain connection
   assign bsr_scan_ctrl = bsr_host_scan_ctrl;
   assign bsr_chain_tdi = bsr_host_scan_out;  // TDI to BSR chain
   assign bsr_host_scan_in = bsr_chain_tdo;   // BSR chain to PTAP

AXI Interface Connection
------------------------

Connect AXI debug interfaces:

.. code-block:: systemverilog

   // SMC fabric debug
   assign smc_axi_req = axi_smc_dbg_req;
   assign axi_smc_dbg_resp = smc_axi_resp;

   // SMC OTP debug
   assign smc_otp_req = axil_smc_otp_jtag_req;
   assign axil_smc_otp_jtag_resp = smc_otp_resp;

   // SEP OTP debug
   assign sep_otp_req = axil_sep_otp_jtag_req;
   assign axil_sep_otp_jtag_resp = sep_otp_resp;

Synthesis Constraints
=====================

Clock Definitions
-----------------

.. code-block:: tcl

   # Define TCK as asynchronous to system clock
   create_clock -name TCK -period 100.0 [get_ports TCK]

   # Set TCK as asynchronous to system clock
   set_clock_groups -asynchronous \
       -group [get_clocks TCK] \
       -group [get_clocks clk_sys]

Input/Output Delays
-------------------

.. code-block:: tcl

   # JTAG input delays (relative to TCK)
   set_input_delay -clock TCK -max 10.0 [get_ports {TDI TMS}]
   set_input_delay -clock TCK -min 2.0  [get_ports {TDI TMS}]

   # TDO output delay (falling edge launch)
   set_output_delay -clock TCK -max 10.0 -clock_fall [get_ports TDO]
   set_output_delay -clock TCK -min 2.0  -clock_fall [get_ports TDO]

   # STAP host interface delays (for chiplet I/O)
   set_output_delay -clock TCK -max 15.0 -clock_fall [get_ports stap_io_host_tdo_o]
   set_input_delay -clock TCK -max 15.0 [get_ports stap_io_host_tdi_i]

False Paths
-----------

.. code-block:: tcl

   # TRST is asynchronous
   set_false_path -from [get_ports TRST_n]

   # Static configuration parameters
   set_false_path -from [get_pins u_jtag_intf_unit/u_jtag_ptap/u_jtag_caps_reg/CAPS_VALUE*]

Multi-Die Timing
----------------

For chiplet-to-chiplet connections via I/O STAP:

.. code-block:: tcl

   # Allow extra delay for die-to-die signals
   set_multicycle_path -setup 2 -from [get_clocks TCK] \
       -to [get_ports stap_io_host_tdo_o]
   set_multicycle_path -hold 1 -from [get_clocks TCK] \
       -to [get_ports stap_io_host_tdo_o]

Parameter Selection Guidelines
==============================

Feature Selection
-----------------

Select features based on system requirements:

* **STAP_IO_ENABLE**: Enable for multi-chiplet configurations
* **SEP_DBG_ENABLE**: Enable if SEP debug access is required
* **NUM_EXTRA_STAPS**: Set based on number of local TAPs to connect
* **SMC_DBG_ENABLE**: Enable for AXI bus debug access
* **TMP_ENABLE**: Enable for hot-swap or power management
* **IC_RESET_ENABLE**: Enable for JTAG-controlled chip reset

STAP Configuration
------------------

Configure STAPs based on connectivity requirements:

* **I/O STAP**: Always uses ``TDI_LOCKUP=1`` for die boundary crossing
* **SEP STAP**: Uses ``TDI_LOCKUP=0`` for on-chip connection
* **Extra STAPs**: Use ``TDI_LOCKUP=0`` for on-chip, ``SCAN_OUT_LOCKUP`` on last STAP

Verification Checklist
======================

Pre-Silicon Verification
------------------------

PTAP Verification:

1. ☐ BYPASS instruction scans single bit
2. ☐ IDCODE returns expected value
3. ☐ All instructions select correct TDR
4. ☐ TDO timing meets IEEE 1149.1 requirements

STAP Chain Verification:

5. ☐ I/O STAP enables host interface when stap_sel=1
6. ☐ SEP STAP enables host interface when stap_sel=1
7. ☐ Extra STAPs chain correctly
8. ☐ TMS parking works correctly (tms_hold)
9. ☐ config_hold prevents TLR reset of 3DCR
10. ☐ Extended STAP scan interface functional

iJTAG Network Verification:

11. ☐ DFT SIB enables/bypasses correctly
12. ☐ DFD SIB enables/bypasses correctly
13. ☐ SIB chain order is correct (DFT first, then DFD)
14. ☐ Instrument networks accessible when SIB enabled

Multi-Die Verification:

15. ☐ Remote chiplet accessible via I/O STAP
16. ☐ TDI lockup latch meets timing requirements
17. ☐ Die-to-die scan chain functional

Post-Silicon Validation
-----------------------

1. ☐ TCK frequency meets specification
2. ☐ Setup/hold margins adequate for all interfaces
3. ☐ TDO drive strength sufficient
4. ☐ JTAG chain integrity verified
5. ☐ Multi-chiplet connectivity functional
6. ☐ iJTAG instruments accessible
