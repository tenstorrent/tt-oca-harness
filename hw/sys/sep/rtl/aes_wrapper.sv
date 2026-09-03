// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2025 TT

// AES Wrapper - AXI to TL-UL Bridge using axi_to_tlul
// Includes AXI4-Lite key interface CSR that drives the AES sideload port.

`include "axi/assign.svh"
`include "axi/typedef.svh"

module aes_wrapper #(
  parameter int unsigned ADDR_WIDTH = 32,
  parameter int unsigned DATA_WIDTH = 32
) (
  input logic clk_i,
  input logic rst_ni,

  // AXI struct interface (64-bit from demux) — data/control path
  input  sep_pkg::sep_32_64_6_12_axi_req_t  aes_axi_req_i,
  output sep_pkg::sep_32_64_6_12_axi_resp_t aes_axi_resp_o,

  // AXI4-Lite key interface (32-bit from Key Manager private bus)
  input  sep_pkg::sep_32_32_axil_req_t  aes_key_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t aes_key_axil_resp_o,

  // EDN interface (entropy for PRNG reseeding)
  output edn_pkg::edn_req_t edn_req_o,
  input  edn_pkg::edn_rsp_t edn_rsp_i,

  // Alert interface (2 alerts: recoverable, fatal)
  input  prim_alert_pkg::alert_rx_t [1:0] alert_rx_i,
  output prim_alert_pkg::alert_tx_t [1:0] alert_tx_o,

  // Register bridge fault (sticky, held until bus_err_clr_i)
  output logic bus_err_o,
  input  logic bus_err_clr_i,

  // Idle output
  output logic idle_o
);

  // ============================================================================
  // 32-bit AXI type definitions for axi_to_tlul bridge
  // (Following WDT/efuse pattern - axi_to_tlul requires 32-bit data width)
  // ============================================================================

  localparam int unsigned AES_AXI32_DATA_WIDTH = 32;
  localparam int unsigned AES_AXI32_STRB_WIDTH = AES_AXI32_DATA_WIDTH / 8;

  typedef logic [AES_AXI32_DATA_WIDTH-1:0] aes_axi32_data_t;
  typedef logic [AES_AXI32_STRB_WIDTH-1:0] aes_axi32_strb_t;

  // Generate all 32-bit AXI channel types using the macro
  `AXI_TYPEDEF_ALL(aes_axi32, sep_pkg::sep_32_64_6_12_axi_addr_t, sep_pkg::sep_32_64_6_12_axi_id_t,
                   aes_axi32_data_t, aes_axi32_strb_t, sep_pkg::sep_32_64_6_12_axi_user_t)

  // 32-bit AXI signals (after width conversion)
  aes_axi32_req_t  aes_axi32_req;
  aes_axi32_resp_t aes_axi32_resp;

  // ============================================================================
  // AXI Data Width Converter: 64-bit -> 32-bit (struct-based)
  // ============================================================================

  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),  // 64-bit input
    .AxiMstPortDataWidth (AES_AXI32_DATA_WIDTH),               // 32-bit output
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (aes_axi32_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (aes_axi32_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_mst_req_t       (aes_axi32_req_t),
    .axi_mst_resp_t      (aes_axi32_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_aes_axi_dw_converter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .slv_req_i (aes_axi_req_i),
    .slv_resp_o(aes_axi_resp_o),
    .mst_req_o (aes_axi32_req),
    .mst_resp_i(aes_axi32_resp)
  );

  // ============================================================================
  // AXI to TileLink Converter (two-stage: AXI -> AXI-Lite -> TL-UL)
  // Stage 1: axi_to_axi_lite - Converts full AXI4 to AXI4-Lite
  // Stage 2: axi_lite_to_tlul - Converts AXI4-Lite to TileLink UL
  // ============================================================================

  tlul_pkg::tl_h2d_t tl_req;
  tlul_pkg::tl_d2h_t tl_resp;

  // AXI-Lite intermediate signals
  sep_pkg::sep_32_32_axil_req_t  axi_lite_req;
  sep_pkg::sep_32_32_axil_resp_t axi_lite_resp;

  // Stage 1: AXI to AXI-Lite conversion
  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (4),
    .AxiMaxReadTxns  (4),
    .full_req_t      (aes_axi32_req_t),
    .full_resp_t     (aes_axi32_resp_t),
    .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
    .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
  ) u_aes_axi_to_axi_lite (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (1'b0),
    .slv_req_i   (aes_axi32_req),
    .slv_resp_o  (aes_axi32_resp),
    .mst_req_o   (axi_lite_req),
    .mst_resp_i  (axi_lite_resp)
  );

  // Stage 2: AXI-Lite to TL-UL conversion
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
    .axi_lite_req_i  (axi_lite_req),
    .axi_lite_rsp_o  (axi_lite_resp),
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

  aes tt_aes (
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
