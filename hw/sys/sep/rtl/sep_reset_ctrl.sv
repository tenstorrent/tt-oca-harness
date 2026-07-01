// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Copyright 2026 Tenstorrent Inc.
//
// SEP Reset Controller
//
// Provides software-controllable reset for KM and crypto accelerators.
// Each bit in the SW_RESET register drives a prim_rst_sync synchronizer
// whose output is able to be overridden by JTAG overrides.
//
// Register map defined in hw/sys/sep/regs/blocks/sep_reset_ctrl/sep_reset_ctrl.rdl
//   Bit 0: km_sw_rst       - write 1 to release KM from reset (0=hold)
//   Bit 1: otbn_sw_rst     - write 1 to release OTBN from reset (0=hold)
//   Bit 2: aes_sw_rst      - write 1 to release AES from reset (0=hold)
//   Bit 3: hmac_sw_rst     - write 1 to release HMAC from reset (0=hold)
//   Bit 4: kmac_sw_rst     - write 1 to release KMAC from reset (0=hold)
//------------------------------------------------------------------------------

`default_nettype none

`include "prim_assert.sv"

module sep_reset_ctrl
    import sep_pkg::*;
    import sep_reset_ctrl_reg_pkg::*;
    (
        input  wire logic   clk_i,

        // Aggregated WDT Resets from SMC and SEP
        input  wire logic   wdt_rst_ni,

        // JTAG SEP Reset Control
        input wire sep_pkg::jtag_sep_reset_ctrl_t jtag_sep_reset_ctrl_i,

        // Intermediate reset signal (before JTAG override) for efuse sensing being done
        input  wire logic   sep_intermediate_reset_ni,
        // Reset signal (after JTAG override) for efuse sensing being done
        output logic        sep_reset_no,

        // AXI4 slave (full AXI from top-level SEP local xbar). An internal
        // axi_to_axi_lite converter feeds the AXI-Lite reg block
        input  wire sep_pkg::sep_32_64_6_12_axi_req_t sep_reset_ctrl_axi_req_i,
        output sep_pkg::sep_32_64_6_12_axi_resp_t  sep_reset_ctrl_axi_resp_o,

        // DFT
        input  wire logic   test_en_i,
        input  wire logic   scan_rst_ni,

        // sep_reset_n AND wdt_rst_ni
        output logic        sep_cpu_reset_no,

        // Reset outputs (active-low, one per IP)
        // Potentially overridden by JTAG overrides
        output sep_pkg::sep_sw_rst_t sep_sw_rst_no

    );
    // Internal reset signal (after JTAG override) for efuse sensing being done
    logic                   sep_reset_n;
    // CPU reset = sep_reset_n gated with the Aggregated WDT Resets from SMC and SEP
    assign sep_cpu_reset_no = sep_reset_n & wdt_rst_ni;

    // =========================================================================
    // AXI4 -> AXI-Lite conversion for the generated reg block
    // =========================================================================
    sep_pkg::sep_32_64_axil_req_t  axil_req;
    sep_pkg::sep_32_64_axil_resp_t axil_resp;

    axi_to_axi_lite #(
        .AxiAddrWidth    (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AxiDataWidth    (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .AxiIdWidth      (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .AxiUserWidth    (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
        .AxiMaxWriteTxns (2),
        .AxiMaxReadTxns  (2),
        .FallThrough     (1'b1),
        .full_req_t      (sep_pkg::sep_32_64_6_12_axi_req_t),
        .full_resp_t     (sep_pkg::sep_32_64_6_12_axi_resp_t),
        .lite_req_t      (sep_pkg::sep_32_64_axil_req_t),
        .lite_resp_t     (sep_pkg::sep_32_64_axil_resp_t)
    ) u_axi_to_axi_lite (
        .clk_i      (clk_i),
        .rst_ni     (sep_reset_n),
        .test_i     (test_en_i),
        .slv_req_i  (sep_reset_ctrl_axi_req_i),
        .slv_resp_o (sep_reset_ctrl_axi_resp_o),
        .mst_req_o  (axil_req),
        .mst_resp_i (axil_resp)
    );

    // =========================================================================
    // Generated register block
    // =========================================================================
    sep_reset_ctrl__out_t hwif_out;

    sep_reset_ctrl_reg u_reg (
        .clk            (clk_i),
        .arst_n         (sep_reset_n),
        .s_axil_awready (axil_resp.aw_ready),
        .s_axil_awvalid (axil_req.aw_valid),
        .s_axil_awaddr  (axil_req.aw.addr[SEP_RESET_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
        .s_axil_awprot  (axil_req.aw.prot),
        .s_axil_wready  (axil_resp.w_ready),
        .s_axil_wvalid  (axil_req.w_valid),
        .s_axil_wdata   (axil_req.w.data),
        .s_axil_wstrb   (axil_req.w.strb),
        .s_axil_bready  (axil_req.b_ready),
        .s_axil_bvalid  (axil_resp.b_valid),
        .s_axil_bresp   (axil_resp.b.resp),
        .s_axil_arready (axil_resp.ar_ready),
        .s_axil_arvalid (axil_req.ar_valid),
        .s_axil_araddr  (axil_req.ar.addr[SEP_RESET_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
        .s_axil_arprot  (axil_req.ar.prot),
        .s_axil_rready  (axil_req.r_ready),
        .s_axil_rvalid  (axil_resp.r_valid),
        .s_axil_rdata   (axil_resp.r.data),
        .s_axil_rresp   (axil_resp.r.resp),
        .hwif_out       (hwif_out)
    );

    // =========================================================================
    // Extract per-IP reset bits from the generated register hwif
    // =========================================================================
    sep_pkg::sep_sw_rst_t sw_reset_bits;

    assign sw_reset_bits.kmac   = hwif_out.SW_RESET_N.kmac_sw_rst_n.value;
    assign sw_reset_bits.hmac   = hwif_out.SW_RESET_N.hmac_sw_rst_n.value;
    assign sw_reset_bits.aes    = hwif_out.SW_RESET_N.aes_sw_rst_n.value;
    assign sw_reset_bits.otbn   = hwif_out.SW_RESET_N.otbn_sw_rst_n.value;
    assign sw_reset_bits.km     = hwif_out.SW_RESET_N.km_sw_rst_n.value;

    // =========================================================================
    // Apply JTAG overrides to the reset bits
    // =========================================================================

    // jtag_sep_reset_ctrl_i val and ovrd are on the TCK clock domain.
    // This creates a known CDC for the reset bits under normal operation.

    // If syncronized to clk_i, this would create a dependecny on clk_i being functional during TCK operations. This is not always the case.
    // If stop clock propagation is used, there might not be a clock and the jtag_sep_reset_ctrl_i value can't propagate.

    assign sep_sw_rst_no.kmac = jtag_sep_reset_ctrl_i.ovrd.kmac_jtag_rst_n_ovrd ? jtag_sep_reset_ctrl_i.val.kmac_jtag_rst_n_val : (sw_reset_bits.kmac & sep_reset_n);
    assign sep_sw_rst_no.hmac = jtag_sep_reset_ctrl_i.ovrd.hmac_jtag_rst_n_ovrd ? jtag_sep_reset_ctrl_i.val.hmac_jtag_rst_n_val : (sw_reset_bits.hmac & sep_reset_n);
    assign sep_sw_rst_no.aes  = jtag_sep_reset_ctrl_i.ovrd.aes_jtag_rst_n_ovrd  ? jtag_sep_reset_ctrl_i.val.aes_jtag_rst_n_val  : (sw_reset_bits.aes  & sep_reset_n);
    assign sep_sw_rst_no.otbn = jtag_sep_reset_ctrl_i.ovrd.otbn_jtag_rst_n_ovrd ? jtag_sep_reset_ctrl_i.val.otbn_jtag_rst_n_val : (sw_reset_bits.otbn & sep_reset_n);
    assign sep_sw_rst_no.km   = jtag_sep_reset_ctrl_i.ovrd.km_jtag_rst_n_ovrd   ? jtag_sep_reset_ctrl_i.val.km_jtag_rst_n_val   : (sw_reset_bits.km   & sep_reset_n);

    // JTAG override to efuse reset
    assign sep_reset_n        = jtag_sep_reset_ctrl_i.ovrd.sep_reset_n_ovrd ? jtag_sep_reset_ctrl_i.val.sep_reset_n_val : sep_intermediate_reset_ni;
    assign sep_reset_no       = sep_reset_n;

endmodule : sep_reset_ctrl

`default_nettype wire
