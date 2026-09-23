// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2024 TT

// HMAC Wrapper - AXI-Lite to TL-UL Bridge using axi_lite_to_tlul

`include "axi/assign.svh"
`include "axi/typedef.svh"

module hmac_wrapper (
  input logic clk_i,
  input logic rst_ni,

  // 32-bit AXI-Lite CSR interface
  input  sep_pkg::sep_32_32_axil_req_t  hmac_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t hmac_axil_resp_o,

  // AXI4-Lite key interface (32-bit from Key Manager private bus)
  input  sep_pkg::sep_32_32_axil_req_t  hmac_key_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t hmac_key_axil_resp_o,

  // Interrupt outputs
  output logic intr_hmac_done_o,
  output logic intr_fifo_empty_o,
  output logic intr_hmac_err_o,

  // Alert interface (1 alert: fatal)
  input  prim_alert_pkg::alert_rx_t [0:0] alert_rx_i,
  output prim_alert_pkg::alert_tx_t [0:0] alert_tx_o,

  // Register bridge fault (sticky, held until bus_err_clr_i)
  output logic bus_err_o,
  input  logic bus_err_clr_i,

  // Idle output
  output logic idle_o
);

  // 32-bit AXI-Lite signals with address masking applied
  // HMAC has BlockAw=13 (8KB address space, addr[12:0])
  // System base 0x10921000 has 0x1000 in lower 13 bits
  // Must subtract offset then mask so HMAC decoder sees correct offsets
  sep_pkg::sep_32_32_axil_req_t hmac_axil_req_masked;

  // ============================================================================
  // Address Masking: Adjust addresses for HMAC internal decoder
  // HMAC has BlockAw=13 (8KB space, 0x0000-0x1FFF internally, fixed by OpenTitan IP)
  // System base from register map has 0x1000 in lower 13 bits, colliding with
  // HMAC's internal FIFO window (0x1000-0x1FFF). Subtract base offset
  // then mask to 13 bits so register decoder sees correct offsets.
  // ============================================================================

  // OpenTitan HMAC has fixed BlockAw=13 (8KB internal address space)
  localparam logic [31:0] HMAC_ADDR_MASK = 32'h0000_1FFF;  // 13 bits for AW=13
  // Extract lower 13 bits of system base address (from och_sep_top_reg.svh via sep_pkg)
  localparam logic [31:0] HMAC_BASE_LOWER = och_sep_top_addrmap_pkg::OCH_SEP_TOP_HMAC_BASE_ADDR & HMAC_ADDR_MASK;

  always_comb begin
    hmac_axil_req_masked = hmac_axil_req_i;
    hmac_axil_req_masked.aw.addr = (hmac_axil_req_i.aw.addr - HMAC_BASE_LOWER) & HMAC_ADDR_MASK;
    hmac_axil_req_masked.ar.addr = (hmac_axil_req_i.ar.addr - HMAC_BASE_LOWER) & HMAC_ADDR_MASK;
  end

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
  ) u_hmac_axi_lite_to_tlul (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .axi_lite_req_i  (hmac_axil_req_masked),
    .axi_lite_rsp_o  (hmac_axil_resp_o),
    .tl_o            (tl_req),
    .tl_i            (tl_resp),
    .err_o           (bus_err_o),
    .err_clr_i       (bus_err_clr_i)
  );

  // ============================================================================
  // HMAC Key CSR Register Block (AXI4-Lite slave for Key Manager key bus)
  //
  // Receives key shares and valid flag from the KM CPU, stores them in
  // write-only CSRs, and drives the keymgr_key_i sideload interface on the
  // OpenTitan HMAC core.
  // ============================================================================

  // HW interface wires for the generated CSR block
  hmac_wrapper_key_reg_pkg::hmac_wrapper_key__out_t key_csr_hwif_out;

  // Build the keymgr_pkg::hw_key_req_t struct from CSR outputs
  keymgr_pkg::hw_key_req_t hmac_keymgr_key;

  assign hmac_keymgr_key.valid = key_csr_hwif_out.KEY_CTRL.key_valid.value;

  // Map CSR key share words to the packed key vector
  for (genvar i = 0; i < 8; i++) begin : gen_key_share_map
    assign hmac_keymgr_key.key[0][i*32 +: 32] = key_csr_hwif_out.KEY_SHARE0[i].data.value;
    assign hmac_keymgr_key.key[1][i*32 +: 32] = key_csr_hwif_out.KEY_SHARE1[i].data.value;
  end

  // Instantiate the PeakRDL-generated HMAC key CSR register block
  localparam int unsigned HMAC_KEY_CSR_ADDR_WIDTH = hmac_wrapper_key_reg_pkg::HMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH; // 7

  hmac_wrapper_key_reg u_hmac_wrapper_key_reg (
    .clk       (clk_i),
    .arst_n    (rst_ni),

    // AW channel
    .s_axil_awvalid (hmac_key_axil_req_i.aw_valid),
    .s_axil_awaddr  (hmac_key_axil_req_i.aw.addr[HMAC_KEY_CSR_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (hmac_key_axil_req_i.aw.prot),
    .s_axil_awready (hmac_key_axil_resp_o.aw_ready),

    // W channel
    .s_axil_wvalid  (hmac_key_axil_req_i.w_valid),
    .s_axil_wdata   (hmac_key_axil_req_i.w.data),
    .s_axil_wstrb   (hmac_key_axil_req_i.w.strb),
    .s_axil_wready  (hmac_key_axil_resp_o.w_ready),

    // B channel
    .s_axil_bready  (hmac_key_axil_req_i.b_ready),
    .s_axil_bvalid  (hmac_key_axil_resp_o.b_valid),
    .s_axil_bresp   (hmac_key_axil_resp_o.b.resp),

    // AR channel
    .s_axil_arvalid (hmac_key_axil_req_i.ar_valid),
    .s_axil_araddr  (hmac_key_axil_req_i.ar.addr[HMAC_KEY_CSR_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (hmac_key_axil_req_i.ar.prot),
    .s_axil_arready (hmac_key_axil_resp_o.ar_ready),

    // R channel
    .s_axil_rready  (hmac_key_axil_req_i.r_ready),
    .s_axil_rvalid  (hmac_key_axil_resp_o.r_valid),
    .s_axil_rdata   (hmac_key_axil_resp_o.r.data),
    .s_axil_rresp   (hmac_key_axil_resp_o.r.resp),

    // HW interface
    .hwif_out (key_csr_hwif_out)
  );

  // ============================================================================
  // OpenTitan HMAC Core
  // ============================================================================

  prim_mubi_pkg::mubi4_t hmac_idle;

  hmac u_tt_hmac (
    .clk_i (clk_i),
    .rst_ni(rst_ni),

    .tl_i(tl_req),
    .tl_o(tl_resp),

    .alert_rx_i(alert_rx_i),
    .alert_tx_o(alert_tx_o),

    .intr_hmac_done_o,
    .intr_fifo_empty_o,
    .intr_hmac_err_o,

    // Key manager sideload interface (driven by hmac_wrapper_key_reg)
    .keymgr_key_i(hmac_keymgr_key),

    .idle_o(hmac_idle)
  );

  // Convert mubi4 to logic
  assign idle_o = prim_mubi_pkg::mubi4_test_true_strict(hmac_idle);

endmodule
