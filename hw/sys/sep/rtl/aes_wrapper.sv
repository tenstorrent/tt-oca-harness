// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2025 TT

// Wrap the OpenTitan AES core with an AXI-Lite CSR bridge and a Key Manager key CSR block.
//
// axi_lite_to_tlul bridges the 32-bit AXI-Lite CSR interface onto the AES TL-UL port. The
// AXI4-Lite key interface terminates in the generated aes_wrapper_key_reg block, whose
// two key shares and valid bit drive the AES keymgr_key_i sideload port.
// EDN supplies entropy for PRNG reseeding. Two alerts leave the block: index 0 is
// recoverable (recov_ctrl_update_err) and index 1 is fatal (fatal_fault).
// The shadow-register reset is tied to rst_ni, lifecycle escalation is tied off, and the
// EDN clock is clk_i.
// bus_err_o sticks on a TL-UL error response until bus_err_clr_i. idle_o reports AES
// idle.

`include "axi/assign.svh"
`include "axi/typedef.svh"

module aes_wrapper (
  input logic clk_i,                          // System clock.
  input logic rst_ni,                         // Active-low reset; also drives the AES
                                              // shadow-register reset.

  input  sep_pkg::sep_32_32_axil_req_t  aes_axil_req_i,  // AES CSR request, bridged to the AES
                                                         // TL-UL port.
  output sep_pkg::sep_32_32_axil_resp_t aes_axil_resp_o,  // AES CSR response from the TL-UL bridge.

  input  sep_pkg::sep_32_32_axil_req_t  aes_key_axil_req_i,  // Key Manager private-bus request to
                                                             // the AES key CSR block.
  output sep_pkg::sep_32_32_axil_resp_t aes_key_axil_resp_o,  // Response from the AES key CSR block
                                                              // to the Key Manager.

  output edn_pkg::edn_req_t edn_req_o,        // EDN request for PRNG reseeding entropy.
  input  edn_pkg::edn_rsp_t edn_rsp_i,        // EDN response for PRNG reseeding entropy.

  input  prim_alert_pkg::alert_rx_t [1:0] alert_rx_i,  // Alert receiver handshakes; index 0
                                                       // recoverable (recov_ctrl_update_err), index
                                                       // 1 fatal (fatal_fault).
  output prim_alert_pkg::alert_tx_t [1:0] alert_tx_o,  // Differential alert senders; index 0
                                                       // recoverable (recov_ctrl_update_err), index
                                                       // 1 fatal (fatal_fault).

  output logic bus_err_o,                     // Set by a TL-UL error response on the CSR bridge;
                                              // sticky until bus_err_clr_i.
  input  logic bus_err_clr_i,                 // Clears bus_err_o; a fault in the same cycle still
                                              // sets it.

  output logic idle_o                         // High when the AES core reports idle (mubi4 strictly
                                              // true).
);

  // ============================================================================
  // AXI-Lite to TL-UL conversion
  // ============================================================================

  tlul_pkg::tl_h2d_t tl_req;
  tlul_pkg::tl_d2h_t tl_resp;

  axi_lite_to_tlul #(
    .AXI_ADDR_WIDTH   (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AXI_DATA_WIDTH   (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AXI_ID_WIDTH     (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AXI_USER_WIDTH   (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .axi_lite_req_t   (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_rsp_t   (sep_pkg::sep_32_32_axil_resp_t)
  ) u_aes_axi_lite_to_tlul (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .axi_lite_req_i  (aes_axil_req_i),
    .axi_lite_rsp_o  (aes_axil_resp_o),
    .tl_o            (tl_req),
    .tl_i            (tl_resp),
    .err_o           (bus_err_o),
    .err_clr_i       (bus_err_clr_i)
  );

  // ============================================================================
  // AES Key CSR Register Block (AXI4-Lite slave for Key Manager key bus)
  //
  // Receives key shares and valid flag from the KM CPU, stores them in
  // write-only CSRs, and drives the keymgr_key_i sideload interface on the
  // OpenTitan AES core.
  // ============================================================================

  // HW interface wires for the generated CSR block
  aes_wrapper_key_reg_pkg::aes_wrapper_key__out_t key_csr_hwif_out;

  // Build the keymgr_pkg::hw_key_req_t struct from CSR outputs
  keymgr_pkg::hw_key_req_t aes_keymgr_key;

  assign aes_keymgr_key.valid = key_csr_hwif_out.KEY_CTRL.key_valid.value;

  // Map CSR key share words to the packed key vector
  // keymgr_key_i.key[share][word*32 +: 32]
  for (genvar i = 0; i < 8; i++) begin : gen_key_share_map
    assign aes_keymgr_key.key[0][i*32 +: 32] = key_csr_hwif_out.KEY_SHARE0[i].data.value;
    assign aes_keymgr_key.key[1][i*32 +: 32] = key_csr_hwif_out.KEY_SHARE1[i].data.value;
  end

  // Instantiate the PeakRDL-generated AES key CSR register block
  // (flat AXI4-Lite interface — we connect from the struct-based port)
  localparam int unsigned AES_KEY_CSR_ADDR_WIDTH = aes_wrapper_key_reg_pkg::AES_WRAPPER_KEY_REG_MIN_ADDR_WIDTH; // 7

  aes_wrapper_key_reg u_aes_wrapper_key_reg (
    .clk       (clk_i),
    .arst_n    (rst_ni),

    // AW channel
    .s_axil_awvalid (aes_key_axil_req_i.aw_valid),
    .s_axil_awaddr  (aes_key_axil_req_i.aw.addr[AES_KEY_CSR_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (aes_key_axil_req_i.aw.prot),
    .s_axil_awready (aes_key_axil_resp_o.aw_ready),

    // W channel
    .s_axil_wvalid  (aes_key_axil_req_i.w_valid),
    .s_axil_wdata   (aes_key_axil_req_i.w.data),
    .s_axil_wstrb   (aes_key_axil_req_i.w.strb),
    .s_axil_wready  (aes_key_axil_resp_o.w_ready),

    // B channel
    .s_axil_bready  (aes_key_axil_req_i.b_ready),
    .s_axil_bvalid  (aes_key_axil_resp_o.b_valid),
    .s_axil_bresp   (aes_key_axil_resp_o.b.resp),

    // AR channel
    .s_axil_arvalid (aes_key_axil_req_i.ar_valid),
    .s_axil_araddr  (aes_key_axil_req_i.ar.addr[AES_KEY_CSR_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (aes_key_axil_req_i.ar.prot),
    .s_axil_arready (aes_key_axil_resp_o.ar_ready),

    // R channel
    .s_axil_rready  (aes_key_axil_req_i.r_ready),
    .s_axil_rvalid  (aes_key_axil_resp_o.r_valid),
    .s_axil_rdata   (aes_key_axil_resp_o.r.data),
    .s_axil_rresp   (aes_key_axil_resp_o.r.resp),

    // HW interface
    .hwif_out (key_csr_hwif_out)
  );

  // ============================================================================
  // OpenTitan AES Core
  // ============================================================================

  prim_mubi_pkg::mubi4_t aes_idle;

  aes u_tt_aes (
    .clk_i (clk_i),
    .rst_ni(rst_ni),
    .rst_shadowed_ni(rst_ni),

    .tl_i(tl_req),
    .tl_o(tl_resp),

    .alert_rx_i(alert_rx_i),
    .alert_tx_o(alert_tx_o),

    .lc_escalate_en_i(lc_ctrl_pkg::Off),

    .clk_edn_i(clk_i),
    .rst_edn_ni(rst_ni),
    .edn_o(edn_req_o),
    .edn_i(edn_rsp_i),

    .keymgr_key_i(aes_keymgr_key),

    .idle_o(aes_idle)
  );

  assign idle_o = prim_mubi_pkg::mubi4_test_true_strict(aes_idle);

endmodule
