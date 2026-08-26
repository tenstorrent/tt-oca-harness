// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP-local TB interface for the SV-UVM flow: system/power-on resets
// (sequenced by the test) and the DUT-produced one-hot IEEE 1149.1 TAP state
// used by the FSM reference-model checks. Deliberately separate from the
// shared ocah_jtag_if, which carries generic JTAG pins only.
//
// The JTAG2AXI additions (issue #3295) carry the test-drivable lifecycle
// debug disables, AXI responder error controls, the SVA suppress knob, and
// mirrors of the tb_top request-activity pulse counters, so sequences never
// reach into tb_top hierarchy directly.

interface dtp_tb_if;

    // Driven by the TB (reset sequencing owned by the test/sequence).
    logic por_rst_n;
    logic sys_rst_n;

    // Driven by the DUT top (jtag_tap_pkg::tap_state_e, one-hot).
    logic [15:0] tap_state;

    // Lifecycle debug disables (sep_lifecycle_ctrl_pkg::dbg_disable_t,
    // active-high: 1 = interface disabled). Init '1 = fail-closed, matching
    // the DUT synchronizers' reset value; JTAG2AXI sequences must clear the
    // target's disable first.
    sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable = '1;

    // Runtime enable for the shared AXI protocol SVA checkers.
    logic axi_sva_en = 1'b1;

    // Runtime enable for the shared JTAG protocol SVA checker.
    logic jtag_sva_en = 1'b1;

    // SMC fabric AXI4 responder error controls (beat-aligned address match).
    // The SMC OTP AXI-Lite port has no error ports here: its responder is the
    // ocah_axi_vip UVM slave agent, programmed via ocah_axi_slave_sequence.
    logic        smc_axi_err_arm      = 1'b0;
    logic [55:0] smc_axi_err_addr     = '0;
    logic [1:0]  smc_axi_err_resp     = 2'b00;
    logic        smc_axi_err_on_read  = 1'b0;
    logic        smc_axi_err_on_write = 1'b0;

    // Request-activity pulse-counter mirrors (driven by tb_top).
    logic [31:0] smc_axi_awvalid_count;
    logic [31:0] smc_axi_wvalid_count;
    logic [31:0] smc_axi_arvalid_count;
    logic [31:0] smc_otp_axil_awvalid_count;
    logic [31:0] smc_otp_axil_wvalid_count;
    logic [31:0] smc_otp_axil_arvalid_count;

endinterface : dtp_tb_if
