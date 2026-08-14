// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP-local TB interface for the SV-UVM flow: system/power-on resets
// (sequenced by the test) and the DUT-produced one-hot IEEE 1149.1 TAP state
// used by the FSM reference-model checks. Deliberately separate from the
// shared ocah_jtag_if, which carries generic JTAG pins only.
//
// The JTAG2AXI additions (issue #3295) carry test-drivable lifecycle enables,
// AXI responder error controls, the SVA suppress knob, and mirrors of the
// tb_top request-activity pulse counters, so sequences never reach into
// tb_top hierarchy directly.

interface dtp_tb_if;

    // Driven by the TB (reset sequencing owned by the test/sequence).
    logic por_rst_n;
    logic sys_rst_n;

    // Driven by the DUT top (jtag_tap_pkg::tap_state_e, one-hot).
    logic [15:0] tap_state;

    // Lifecycle feature enables (init 0 = the historical UVM-mode tie-off;
    // JTAG2AXI sequences must enable the target's required bits first).
    logic feat_ctrl_sip_debug = 1'b0;
    logic feat_ctrl_soc_debug = 1'b0;
    logic feat_ctrl_ap_debug  = 1'b0;
    logic feat_ctrl_sep_debug = 1'b0;
    logic feat_ctrl_fuse_test = 1'b0;

    // Runtime enable for the shared AXI protocol SVA checkers.
    logic axi_sva_en = 1'b1;

    // SMC OTP AXI-Lite responder error controls (beat-aligned address match).
    logic        smc_otp_err_arm      = 1'b0;
    logic [31:0] smc_otp_err_addr     = '0;
    logic [1:0]  smc_otp_err_resp     = 2'b00;
    logic        smc_otp_err_on_read  = 1'b0;
    logic        smc_otp_err_on_write = 1'b0;

    // SMC fabric AXI4 responder error controls.
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
