// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// SEP Reset Controller
//
// Provides software-controllable reset for KM and crypto accelerators.
// Each bit in the SW_RESET register gates the SEP reset for one IP, and the
// JTAG IC_RESET slice can override the result. AXI-aware reset sequencing
// lives next to the target ports: sep_crypto for the accelerators, sep_trng
// for the entropy complex.
//
// Register map defined in meta/registers/rdl/sep_reset_ctrl.rdl
//   Bit 0: km_sw_rst       - write 1 to release KM from reset (0=hold)
//   Bit 1: otbn_sw_rst     - write 1 to release OTBN from reset (0=hold)
//   Bit 2: aes_sw_rst      - write 1 to release AES from reset (0=hold)
//   Bit 3: hmac_sw_rst     - write 1 to release HMAC from reset (0=hold)
//   Bit 4: kmac_sw_rst     - write 1 to release KMAC from reset (0=hold)
//   Bit 5: trng_sw_rst      - write 1 to release internal TRNG (0=hold)

`include "prim_assert.sv"

module sep_reset_ctrl
    (
        input  logic   clk_i,

        // Aggregated WDT Resets from SMC and SEP
        input  logic   wdt_rst_ni,

        // JTAG SEP Reset Control
        input sep_pkg::jtag_sep_reset_ctrl_t jtag_sep_reset_ctrl_i,

        // Intermediate reset signal (before JTAG override) for efuse sensing being done
        input  logic   sep_intermediate_reset_ni,
        // Reset signal (after JTAG override) for efuse sensing being done
        output logic        sep_reset_no,

        // AXI4 slave (full AXI from top-level SEP local xbar). An internal
        // axi_to_axi_lite converter feeds the AXI-Lite reg block
        input  sep_pkg::sep_32_64_6_12_axi_req_t sep_reset_ctrl_axi_req_i,
        output sep_pkg::sep_32_64_6_12_axi_resp_t  sep_reset_ctrl_axi_resp_o,

        // DFT
        input  logic   test_en_i,
        input  logic   scan_rst_ni,

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
    sep_reset_ctrl_reg_pkg::sep_reset_ctrl__out_t hwif_out;

    sep_reset_ctrl_reg u_reg (
        .clk            (clk_i),
        .arst_n         (sep_reset_n),
        .s_axil_awready (axil_resp.aw_ready),
        .s_axil_awvalid (axil_req.aw_valid),
        .s_axil_awaddr  (axil_req.aw.addr[sep_reset_ctrl_reg_pkg::SEP_RESET_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
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
        .s_axil_araddr  (axil_req.ar.addr[sep_reset_ctrl_reg_pkg::SEP_RESET_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
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

    assign sw_reset_bits.trng   = hwif_out.SW_RESET_N.trng_sw_rst_n.value;
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

    logic kmac_gated_rst_n, hmac_gated_rst_n, aes_gated_rst_n, otbn_gated_rst_n, km_gated_rst_n;
    logic trng_gated_rst_n;
    logic kmac_rst_n, hmac_rst_n, aes_rst_n, otbn_rst_n, km_rst_n;
    logic trng_rst_n;

    prim_and2 #(.Width(1)) u_kmac_rst_and (
        .in0_i (sw_reset_bits.kmac),
        .in1_i (sep_reset_n),
        .out_o (kmac_gated_rst_n)
    );

    prim_and2 #(.Width(1)) u_hmac_rst_and (
        .in0_i (sw_reset_bits.hmac),
        .in1_i (sep_reset_n),
        .out_o (hmac_gated_rst_n)
    );

    prim_and2 #(.Width(1)) u_aes_rst_and (
        .in0_i (sw_reset_bits.aes),
        .in1_i (sep_reset_n),
        .out_o (aes_gated_rst_n)
    );

    prim_and2 #(.Width(1)) u_otbn_rst_and (
        .in0_i (sw_reset_bits.otbn),
        .in1_i (sep_reset_n),
        .out_o (otbn_gated_rst_n)
    );

    prim_and2 #(.Width(1)) u_km_rst_and (
        .in0_i (sw_reset_bits.km),
        .in1_i (sep_reset_n),
        .out_o (km_gated_rst_n)
    );

    prim_and2 #(.Width(1)) u_trng_rst_and (
        .in0_i (sw_reset_bits.trng),
        .in1_i (sep_reset_n),
        .out_o (trng_gated_rst_n)
    );

    prim_rst_mux2_hf_n u_kmac_rst_ovrd_mux (
        .rst0_ni (kmac_gated_rst_n),
        .rst1_ni (jtag_sep_reset_ctrl_i.val.kmac_jtag_rst_n_val),
        .sel_i   (jtag_sep_reset_ctrl_i.ovrd.kmac_jtag_rst_n_ovrd),
        .rst_no  (kmac_rst_n)
    );

    prim_rst_mux2_hf_n u_hmac_rst_ovrd_mux (
        .rst0_ni (hmac_gated_rst_n),
        .rst1_ni (jtag_sep_reset_ctrl_i.val.hmac_jtag_rst_n_val),
        .sel_i   (jtag_sep_reset_ctrl_i.ovrd.hmac_jtag_rst_n_ovrd),
        .rst_no  (hmac_rst_n)
    );

    prim_rst_mux2_hf_n u_aes_rst_ovrd_mux (
        .rst0_ni (aes_gated_rst_n),
        .rst1_ni (jtag_sep_reset_ctrl_i.val.aes_jtag_rst_n_val),
        .sel_i   (jtag_sep_reset_ctrl_i.ovrd.aes_jtag_rst_n_ovrd),
        .rst_no  (aes_rst_n)
    );

    prim_rst_mux2_hf_n u_otbn_rst_ovrd_mux (
        .rst0_ni (otbn_gated_rst_n),
        .rst1_ni (jtag_sep_reset_ctrl_i.val.otbn_jtag_rst_n_val),
        .sel_i   (jtag_sep_reset_ctrl_i.ovrd.otbn_jtag_rst_n_ovrd),
        .rst_no  (otbn_rst_n)
    );

    prim_rst_mux2_hf_n u_km_rst_ovrd_mux (
        .rst0_ni (km_gated_rst_n),
        .rst1_ni (jtag_sep_reset_ctrl_i.val.km_jtag_rst_n_val),
        .sel_i   (jtag_sep_reset_ctrl_i.ovrd.km_jtag_rst_n_ovrd),
        .rst_no  (km_rst_n)
    );

    prim_rst_mux2_hf_n u_trng_rst_ovrd_mux (
        .rst0_ni (trng_gated_rst_n),
        .rst1_ni (jtag_sep_reset_ctrl_i.val.trng_jtag_rst_n_val),
        .sel_i   (jtag_sep_reset_ctrl_i.ovrd.trng_jtag_rst_n_ovrd),
        .rst_no  (trng_rst_n)
    );

    assign sep_sw_rst_no.kmac = kmac_rst_n;
    assign sep_sw_rst_no.hmac = hmac_rst_n;
    assign sep_sw_rst_no.aes  = aes_rst_n;
    assign sep_sw_rst_no.otbn = otbn_rst_n;
    assign sep_sw_rst_no.km   = km_rst_n;
    assign sep_sw_rst_no.trng = trng_rst_n;

    // JTAG override to efuse reset
    prim_rst_mux2_hf_n u_sep_reset_ovrd_mux (
        .rst0_ni (sep_intermediate_reset_ni),
        .rst1_ni (jtag_sep_reset_ctrl_i.val.sep_reset_n_val),
        .sel_i   (jtag_sep_reset_ctrl_i.ovrd.sep_reset_n_ovrd),
        .rst_no  (sep_reset_n)
    );

    assign sep_reset_no       = sep_reset_n;

endmodule : sep_reset_ctrl

