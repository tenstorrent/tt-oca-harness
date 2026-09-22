// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// SEP Reset Controller
//
// Provides software-controllable reset for KM and crypto accelerators.
// Each bit in the SW_RESET register drives a sep_isolate_rst_seq FSM which
// requests isolation of that domain's AXI paths, waits for them to drain,
// and then asserts the domain's sequenced reset. Reset primitives combine the
// sequenced resets with the SEP reset and apply the JTAG IC_RESET overrides
// for KM, OTBN, AES, HMAC, KMAC, ABR, and the internal TRNG complex.
//
// Register map defined in hw/sys/sep/regs/blocks/sep_reset_ctrl/sep_reset_ctrl.rdl
//   Bit 0: km_sw_rst       - write 1 to release KM from reset (0=hold)
//   Bit 1: otbn_sw_rst     - write 1 to release OTBN from reset (0=hold)
//   Bit 2: aes_sw_rst      - write 1 to release AES from reset (0=hold)
//   Bit 3: hmac_sw_rst     - write 1 to release HMAC from reset (0=hold)
//   Bit 4: kmac_sw_rst     - write 1 to release KMAC from reset (0=hold)
//   Bit 5: trng_sw_rst      - write 1 to release internal TRNG (0=hold)
//   Bit 6: abr_sw_rst       - write 1 to release ABR from reset (0=hold)

`include "prim_assert.sv"

module sep_reset_ctrl (
  input  logic   clk_i,
  // Cold reset for the isolation sequencing FSMs
  input logic    rst_ni,

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
  output logic   sep_cpu_reset_no,

  // Isolation handshake with sep_crypto's AXI interconnect (one per IP)
  output sep_pkg::sep_crypto_isolate_t sep_crypto_isolate_req_o,
  input  sep_pkg::sep_crypto_isolate_t sep_crypto_isolated_i,

  // Isolation-sequenced resets to sep_crypto (active-low, one per IP)
  // Potentially overridden by JTAG overrides
  output sep_pkg::sep_sw_rst_t sep_crypto_gated_rst_no

);
  // Internal reset signal (after JTAG override) for efuse sensing being done
  logic sep_reset_n;
  // CPU reset = sep_reset_n gated with the Aggregated WDT Resets from SMC and SEP
  prim_and2 #(
    .Width(1)
  ) u_sep_cpu_rst_and (
    .in0_i (sep_reset_n),
    .in1_i (wdt_rst_ni),
    .out_o (sep_cpu_reset_no)
  );

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

  assign sw_reset_bits.abr    = hwif_out.SW_RESET_N.abr_sw_rst_n.value;
  assign sw_reset_bits.trng   = hwif_out.SW_RESET_N.trng_sw_rst_n.value;
  assign sw_reset_bits.kmac   = hwif_out.SW_RESET_N.kmac_sw_rst_n.value;
  assign sw_reset_bits.hmac   = hwif_out.SW_RESET_N.hmac_sw_rst_n.value;
  assign sw_reset_bits.aes    = hwif_out.SW_RESET_N.aes_sw_rst_n.value;
  assign sw_reset_bits.otbn   = hwif_out.SW_RESET_N.otbn_sw_rst_n.value;
  assign sw_reset_bits.km     = hwif_out.SW_RESET_N.km_sw_rst_n.value;

  // =========================================================================
  // Isolate/reset sequencing, one FSM per SW_RESET_N domain
  // =========================================================================
  // Each engine domain owns its host-path isolate and shares its KM-path
  // isolate with the KM domain: the KM path must be drained before either
  // side's reset may assert.

  logic abr_isolate_req, otbn_isolate_req, aes_isolate_req, hmac_isolate_req, kmac_isolate_req;
  logic km_isolate_req, trng_isolate_req;
  sep_pkg::sep_sw_rst_t isolated_rst_n;

  sep_isolate_rst_seq u_abr_isolate_seq (
    .clk_i        (clk_i),
    .rst_ni       (rst_ni),
    .sw_rst_req_ni(sw_reset_bits.abr),
    .isolated_i   (sep_crypto_isolated_i.host_abr & sep_crypto_isolated_i.km_abr),
    .isolate_req_o(abr_isolate_req),
    .gated_rst_no (isolated_rst_n.abr)
  );

  sep_isolate_rst_seq u_otbn_isolate_seq (
    .clk_i        (clk_i),
    .rst_ni       (rst_ni),
    .sw_rst_req_ni(sw_reset_bits.otbn),
    .isolated_i   (sep_crypto_isolated_i.host_otbn & sep_crypto_isolated_i.km_otbn),
    .isolate_req_o(otbn_isolate_req),
    .gated_rst_no (isolated_rst_n.otbn)
  );

  sep_isolate_rst_seq u_aes_isolate_seq (
    .clk_i        (clk_i),
    .rst_ni       (rst_ni),
    .sw_rst_req_ni(sw_reset_bits.aes),
    .isolated_i   (sep_crypto_isolated_i.host_aes & sep_crypto_isolated_i.km_aes),
    .isolate_req_o(aes_isolate_req),
    .gated_rst_no (isolated_rst_n.aes)
  );

  sep_isolate_rst_seq u_hmac_isolate_seq (
    .clk_i        (clk_i),
    .rst_ni       (rst_ni),
    .sw_rst_req_ni(sw_reset_bits.hmac),
    .isolated_i   (sep_crypto_isolated_i.host_hmac & sep_crypto_isolated_i.km_hmac),
    .isolate_req_o(hmac_isolate_req),
    .gated_rst_no (isolated_rst_n.hmac)
  );

  sep_isolate_rst_seq u_kmac_isolate_seq (
    .clk_i        (clk_i),
    .rst_ni       (rst_ni),
    .sw_rst_req_ni(sw_reset_bits.kmac),
    .isolated_i   (sep_crypto_isolated_i.host_kmac & sep_crypto_isolated_i.km_kmac),
    .isolate_req_o(kmac_isolate_req),
    .gated_rst_no (isolated_rst_n.kmac)
  );

  // KM reset waits for all of the KM's master paths to drain.
  sep_isolate_rst_seq u_km_isolate_seq (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .sw_rst_req_ni  (sw_reset_bits.km),
    .isolated_i     (sep_crypto_isolated_i.km_otbn & sep_crypto_isolated_i.km_aes &
                         sep_crypto_isolated_i.km_hmac & sep_crypto_isolated_i.km_kmac &
                         sep_crypto_isolated_i.km_abr  & sep_crypto_isolated_i.km_efuse),
    .isolate_req_o  (km_isolate_req),
    .gated_rst_no   (isolated_rst_n.km)
  );

  // The TRNG reset is shared by the entropy source, CSRNG, and EDN.
  sep_isolate_rst_seq u_trng_isolate_seq (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .sw_rst_req_ni  (sw_reset_bits.trng),
    .isolated_i     (sep_crypto_isolated_i.trng_entropy_source &
                         sep_crypto_isolated_i.trng_csrng &
                         sep_crypto_isolated_i.trng_edn),
    .isolate_req_o  (trng_isolate_req),
    .gated_rst_no   (isolated_rst_n.trng)
  );

  // Host-path isolates belong to their engine; KM-path isolates isolate when
  // either the engine or the KM is being reset.
  assign sep_crypto_isolate_req_o.trng_entropy_source = trng_isolate_req;
  assign sep_crypto_isolate_req_o.trng_csrng          = trng_isolate_req;
  assign sep_crypto_isolate_req_o.trng_edn            = trng_isolate_req;
  assign sep_crypto_isolate_req_o.host_otbn = otbn_isolate_req;
  assign sep_crypto_isolate_req_o.host_aes  = aes_isolate_req;
  assign sep_crypto_isolate_req_o.host_hmac = hmac_isolate_req;
  assign sep_crypto_isolate_req_o.host_kmac = kmac_isolate_req;
  assign sep_crypto_isolate_req_o.host_abr  = abr_isolate_req;
  assign sep_crypto_isolate_req_o.km_otbn   = otbn_isolate_req | km_isolate_req;
  assign sep_crypto_isolate_req_o.km_aes    = aes_isolate_req  | km_isolate_req;
  assign sep_crypto_isolate_req_o.km_hmac   = hmac_isolate_req | km_isolate_req;
  assign sep_crypto_isolate_req_o.km_kmac   = kmac_isolate_req | km_isolate_req;
  assign sep_crypto_isolate_req_o.km_abr    = abr_isolate_req  | km_isolate_req;
  assign sep_crypto_isolate_req_o.km_efuse  = km_isolate_req;

  // =========================================================================
  // Apply JTAG overrides to the sequenced resets
  // =========================================================================
  // sep_reset_n is a boot-level subsystem reset, so it forces the sequenced
  // resets unconditionally, bypassing the isolation sequencing. JTAG
  // overrides act last so debug can force a reset regardless of isolation.

  // Per-IP override bits cross from TCK into clk_i. rst_ni clears both
  // synchronizers asynchronously, so a hard reset drops a held override and
  // the mux follows the functional reset with no clock. The packing order
  // matches sep_sw_rst_t (abr, trng, kmac, hmac, aes, otbn, km).
  localparam int unsigned NUM_JTAG_IP_RST = $bits(sep_pkg::sep_sw_rst_t);

  logic [NUM_JTAG_IP_RST-1:0] jtag_ip_ovrd_tck;
  logic [NUM_JTAG_IP_RST-1:0] jtag_ip_val_tck;
  logic [NUM_JTAG_IP_RST-1:0] jtag_ip_ovrd_sync;
  logic [NUM_JTAG_IP_RST-1:0] jtag_ip_val_sync;

  assign jtag_ip_ovrd_tck = {
    jtag_sep_reset_ctrl_i.ovrd.abr_jtag_rst_n_ovrd,
    jtag_sep_reset_ctrl_i.ovrd.trng_jtag_rst_n_ovrd,
    jtag_sep_reset_ctrl_i.ovrd.kmac_jtag_rst_n_ovrd,
    jtag_sep_reset_ctrl_i.ovrd.hmac_jtag_rst_n_ovrd,
    jtag_sep_reset_ctrl_i.ovrd.aes_jtag_rst_n_ovrd,
    jtag_sep_reset_ctrl_i.ovrd.otbn_jtag_rst_n_ovrd,
    jtag_sep_reset_ctrl_i.ovrd.km_jtag_rst_n_ovrd
  };

  assign jtag_ip_val_tck = {
    jtag_sep_reset_ctrl_i.val.abr_jtag_rst_n_val,
    jtag_sep_reset_ctrl_i.val.trng_jtag_rst_n_val,
    jtag_sep_reset_ctrl_i.val.kmac_jtag_rst_n_val,
    jtag_sep_reset_ctrl_i.val.hmac_jtag_rst_n_val,
    jtag_sep_reset_ctrl_i.val.aes_jtag_rst_n_val,
    jtag_sep_reset_ctrl_i.val.otbn_jtag_rst_n_val,
    jtag_sep_reset_ctrl_i.val.km_jtag_rst_n_val
  };

  prim_sync2r #(
    .WIDTH(NUM_JTAG_IP_RST)
  ) u_jtag_ip_ovrd_sync (
    .clk_i (clk_i),
    .d_i   (jtag_ip_ovrd_tck),
    .rst_ni(rst_ni),
    .q_o   (jtag_ip_ovrd_sync)
  );

  prim_sync2r #(
    .WIDTH(NUM_JTAG_IP_RST)
  ) u_jtag_ip_val_sync (
    .clk_i (clk_i),
    .d_i   (jtag_ip_val_tck),
    .rst_ni(rst_ni),
    .q_o   (jtag_ip_val_sync)
  );

  sep_pkg::sep_sw_rst_t jtag_ip_ovrd;
  sep_pkg::sep_sw_rst_t jtag_ip_val;
  assign jtag_ip_ovrd = sep_pkg::sep_sw_rst_t'(jtag_ip_ovrd_sync);
  assign jtag_ip_val  = sep_pkg::sep_sw_rst_t'(jtag_ip_val_sync);

  sep_pkg::sep_sw_rst_t pre_jtag_rst_n;
  sep_pkg::sep_sw_rst_t jtag_ovrd_rst_n;

  prim_and2 #(
    .Width(1)
  ) u_abr_rst_and (
    .in0_i (isolated_rst_n.abr),
    .in1_i (sep_reset_n),
    .out_o (pre_jtag_rst_n.abr)
  );

  prim_and2 #(
    .Width(1)
  ) u_kmac_rst_and (
    .in0_i (isolated_rst_n.kmac),
    .in1_i (sep_reset_n),
    .out_o (pre_jtag_rst_n.kmac)
  );

  prim_and2 #(
    .Width(1)
  ) u_hmac_rst_and (
    .in0_i (isolated_rst_n.hmac),
    .in1_i (sep_reset_n),
    .out_o (pre_jtag_rst_n.hmac)
  );

  prim_and2 #(
    .Width(1)
  ) u_aes_rst_and (
    .in0_i (isolated_rst_n.aes),
    .in1_i (sep_reset_n),
    .out_o (pre_jtag_rst_n.aes)
  );

  prim_and2 #(
    .Width(1)
  ) u_otbn_rst_and (
    .in0_i (isolated_rst_n.otbn),
    .in1_i (sep_reset_n),
    .out_o (pre_jtag_rst_n.otbn)
  );

  prim_and2 #(
    .Width(1)
  ) u_km_rst_and (
    .in0_i (isolated_rst_n.km),
    .in1_i (sep_reset_n),
    .out_o (pre_jtag_rst_n.km)
  );

  prim_and2 #(
    .Width(1)
  ) u_trng_rst_and (
    .in0_i (isolated_rst_n.trng),
    .in1_i (sep_reset_n),
    .out_o (pre_jtag_rst_n.trng)
  );

  prim_rst_mux2_hf_n u_abr_rst_ovrd_mux (
    .rst0_ni (pre_jtag_rst_n.abr),
    .rst1_ni (jtag_ip_val.abr),
    .sel_i   (jtag_ip_ovrd.abr),
    .rst_no  (jtag_ovrd_rst_n.abr)
  );

  prim_rst_mux2_hf_n u_kmac_rst_ovrd_mux (
    .rst0_ni (pre_jtag_rst_n.kmac),
    .rst1_ni (jtag_ip_val.kmac),
    .sel_i   (jtag_ip_ovrd.kmac),
    .rst_no  (jtag_ovrd_rst_n.kmac)
  );

  prim_rst_mux2_hf_n u_hmac_rst_ovrd_mux (
    .rst0_ni (pre_jtag_rst_n.hmac),
    .rst1_ni (jtag_ip_val.hmac),
    .sel_i   (jtag_ip_ovrd.hmac),
    .rst_no  (jtag_ovrd_rst_n.hmac)
  );

  prim_rst_mux2_hf_n u_aes_rst_ovrd_mux (
    .rst0_ni (pre_jtag_rst_n.aes),
    .rst1_ni (jtag_ip_val.aes),
    .sel_i   (jtag_ip_ovrd.aes),
    .rst_no  (jtag_ovrd_rst_n.aes)
  );

  prim_rst_mux2_hf_n u_otbn_rst_ovrd_mux (
    .rst0_ni (pre_jtag_rst_n.otbn),
    .rst1_ni (jtag_ip_val.otbn),
    .sel_i   (jtag_ip_ovrd.otbn),
    .rst_no  (jtag_ovrd_rst_n.otbn)
  );

  prim_rst_mux2_hf_n u_km_rst_ovrd_mux (
    .rst0_ni (pre_jtag_rst_n.km),
    .rst1_ni (jtag_ip_val.km),
    .sel_i   (jtag_ip_ovrd.km),
    .rst_no  (jtag_ovrd_rst_n.km)
  );

  prim_rst_mux2_hf_n u_trng_rst_ovrd_mux (
    .rst0_ni (pre_jtag_rst_n.trng),
    .rst1_ni (jtag_ip_val.trng),
    .sel_i   (jtag_ip_ovrd.trng),
    .rst_no  (jtag_ovrd_rst_n.trng)
  );

  // sep_reset_n stays in the TCK domain. The override must assert while a
  // debug clock stop has gated clk_i.
  logic sep_reset_mux_n;
  prim_rst_mux2_hf_n u_sep_reset_ovrd_mux (
    .rst0_ni (sep_intermediate_reset_ni),
    .rst1_ni (jtag_sep_reset_ctrl_i.val.sep_reset_n_val),
    .sel_i   (jtag_sep_reset_ctrl_i.ovrd.sep_reset_n_ovrd),
    .rst_no  (sep_reset_mux_n)
  );

  // Test mode substitutes scan_rst_ni after each override mux, so scan reset
  // reaches the flops these outputs reset.
  prim_rstbypass_stdmux2 u_abr_rst_scan_bypass (
    .rst_ni     (jtag_ovrd_rst_n.abr),
    .test_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),
    .rst_no     (sep_crypto_gated_rst_no.abr)
  );

  prim_rstbypass_stdmux2 u_kmac_rst_scan_bypass (
    .rst_ni     (jtag_ovrd_rst_n.kmac),
    .test_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),
    .rst_no     (sep_crypto_gated_rst_no.kmac)
  );

  prim_rstbypass_stdmux2 u_hmac_rst_scan_bypass (
    .rst_ni     (jtag_ovrd_rst_n.hmac),
    .test_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),
    .rst_no     (sep_crypto_gated_rst_no.hmac)
  );

  prim_rstbypass_stdmux2 u_aes_rst_scan_bypass (
    .rst_ni     (jtag_ovrd_rst_n.aes),
    .test_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),
    .rst_no     (sep_crypto_gated_rst_no.aes)
  );

  prim_rstbypass_stdmux2 u_otbn_rst_scan_bypass (
    .rst_ni     (jtag_ovrd_rst_n.otbn),
    .test_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),
    .rst_no     (sep_crypto_gated_rst_no.otbn)
  );

  prim_rstbypass_stdmux2 u_km_rst_scan_bypass (
    .rst_ni     (jtag_ovrd_rst_n.km),
    .test_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),
    .rst_no     (sep_crypto_gated_rst_no.km)
  );

  prim_rstbypass_stdmux2 u_trng_rst_scan_bypass (
    .rst_ni     (jtag_ovrd_rst_n.trng),
    .test_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),
    .rst_no     (sep_crypto_gated_rst_no.trng)
  );

  prim_rstbypass_stdmux2 u_sep_reset_scan_bypass (
    .rst_ni     (sep_reset_mux_n),
    .test_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),
    .rst_no     (sep_reset_n)
  );

  assign sep_reset_no = sep_reset_n;

endmodule : sep_reset_ctrl
