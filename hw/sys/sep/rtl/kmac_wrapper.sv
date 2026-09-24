// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2025 TT

// KMAC Wrapper - AXI-Lite to TL-UL Bridge using axi_lite_to_tlul

`include "axi/assign.svh"
`include "axi/typedef.svh"

module kmac_wrapper (
  input logic clk_i,
  input logic rst_ni,

  // 32-bit AXI-Lite CSR interface
  input  sep_pkg::sep_32_32_axil_req_t  kmac_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t kmac_axil_resp_o,

  // AXI4-Lite key interface (32-bit from Key Manager private bus)
  input  sep_pkg::sep_32_32_axil_req_t  kmac_key_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t kmac_key_axil_resp_o,

  // EDN interface (entropy for PRNG)
  output edn_pkg::edn_req_t edn_req_o,
  input  edn_pkg::edn_rsp_t edn_rsp_i,

  // Interrupts
  output logic intr_kmac_done_o,
  output logic intr_fifo_empty_o,
  output logic intr_kmac_err_o,

  // Alert interface (2 alerts: recoverable, fatal)
  input  prim_alert_pkg::alert_rx_t [1:0] alert_rx_i,
  output prim_alert_pkg::alert_tx_t [1:0] alert_tx_o,

  // Register bridge fault (sticky, held until bus_err_clr_i)
  output logic bus_err_o,
  input  logic bus_err_clr_i,

  // Idle output
  output logic idle_o
);

  // 32-bit AXI-Lite signals with address masking applied
  // KMAC has BlockAw=12 (4KB address space, addr[11:0])
  // System base 0x10923000 has 0x000 in lower 12 bits (clean!)
  // Just mask to 12 bits so KMAC decoder sees correct offsets
  sep_pkg::sep_32_32_axil_req_t kmac_axil_req_masked;

  // ============================================================================
  // Address Masking: Adjust addresses for KMAC internal decoder
  // KMAC has BlockAw=12 (4KB space, 0x000-0xFFF internally, fixed by OpenTitan IP)
  // System base from register map has clean lower 12 bits (0x000), but upper
  // bits beyond bit 11 must be masked off so decoder sees valid range
  // ============================================================================

  // OpenTitan KMAC has fixed BlockAw=12 (4KB internal address space)
  localparam logic [31:0] KMAC_ADDR_MASK = 32'h0000_0FFF;  // 12 bits for AW=12
  // Extract lower 12 bits of system base address (from sep_top_reg.svh via sep_pkg)
  localparam logic [31:0] KMAC_BASE_LOWER = sep_top_addrmap_pkg::SEP_TOP_KMAC_BASE_ADDR & KMAC_ADDR_MASK;

  always_comb begin
    kmac_axil_req_masked = kmac_axil_req_i;
    // Subtract offset (0x000 for KMAC) then mask to 12 bits
    kmac_axil_req_masked.aw.addr = (kmac_axil_req_i.aw.addr - KMAC_BASE_LOWER) & KMAC_ADDR_MASK;
    kmac_axil_req_masked.ar.addr = (kmac_axil_req_i.ar.addr - KMAC_BASE_LOWER) & KMAC_ADDR_MASK;
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
  ) u_kmac_axi_lite_to_tlul (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .axi_lite_req_i  (kmac_axil_req_masked),
    .axi_lite_rsp_o  (kmac_axil_resp_o),
    .tl_o            (tl_req),
    .tl_i            (tl_resp),
    .err_o           (bus_err_o),
    .err_clr_i       (bus_err_clr_i)
  );

  // ============================================================================
  // KMAC Key CSR Register Block (AXI4-Lite slave for Key Manager key bus)
  //
  // Receives key shares and valid flag from the KM CPU, stores them in
  // write-only CSRs, and drives the keymgr_key_i sideload interface on the
  // OpenTitan KMAC core.
  // ============================================================================

  // HW interface wires for the generated CSR block
  kmac_wrapper_key_reg_pkg::kmac_wrapper_key__out_t key_csr_hwif_out;

  // Build the keymgr_pkg::hw_key_req_t struct from CSR outputs
  keymgr_pkg::hw_key_req_t kmac_keymgr_key;

  assign kmac_keymgr_key.valid = key_csr_hwif_out.KEY_CTRL.key_valid.value;

  // Map CSR key share words to the packed key vector
  for (genvar i = 0; i < 8; i++) begin : gen_key_share_map
    assign kmac_keymgr_key.key[0][i*32 +: 32] = key_csr_hwif_out.KEY_SHARE0[i].data.value;
    assign kmac_keymgr_key.key[1][i*32 +: 32] = key_csr_hwif_out.KEY_SHARE1[i].data.value;
  end

  // Instantiate the PeakRDL-generated KMAC key CSR register block
  localparam int unsigned KMAC_KEY_CSR_ADDR_WIDTH = kmac_wrapper_key_reg_pkg::KMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH; // 7

  kmac_wrapper_key_reg u_kmac_wrapper_key_reg (
    .clk       (clk_i),
    .arst_n    (rst_ni),

    // AW channel
    .s_axil_awvalid (kmac_key_axil_req_i.aw_valid),
    .s_axil_awaddr  (kmac_key_axil_req_i.aw.addr[KMAC_KEY_CSR_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (kmac_key_axil_req_i.aw.prot),
    .s_axil_awready (kmac_key_axil_resp_o.aw_ready),

    // W channel
    .s_axil_wvalid  (kmac_key_axil_req_i.w_valid),
    .s_axil_wdata   (kmac_key_axil_req_i.w.data),
    .s_axil_wstrb   (kmac_key_axil_req_i.w.strb),
    .s_axil_wready  (kmac_key_axil_resp_o.w_ready),

    // B channel
    .s_axil_bready  (kmac_key_axil_req_i.b_ready),
    .s_axil_bvalid  (kmac_key_axil_resp_o.b_valid),
    .s_axil_bresp   (kmac_key_axil_resp_o.b.resp),

    // AR channel
    .s_axil_arvalid (kmac_key_axil_req_i.ar_valid),
    .s_axil_araddr  (kmac_key_axil_req_i.ar.addr[KMAC_KEY_CSR_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (kmac_key_axil_req_i.ar.prot),
    .s_axil_arready (kmac_key_axil_resp_o.ar_ready),

    // R channel
    .s_axil_rready  (kmac_key_axil_req_i.r_ready),
    .s_axil_rvalid  (kmac_key_axil_resp_o.r_valid),
    .s_axil_rdata   (kmac_key_axil_resp_o.r.data),
    .s_axil_rresp   (kmac_key_axil_resp_o.r.resp),

    // HW interface
    .hwif_out (key_csr_hwif_out)
  );

  // ============================================================================
  // OpenTitan KMAC Core
  // ============================================================================

  prim_mubi_pkg::mubi4_t kmac_idle;

  kmac u_tt_kmac (
    .clk_i (clk_i),
    .rst_ni(rst_ni),
    .rst_shadowed_ni(rst_ni),

    .tl_i(tl_req),
    .tl_o(tl_resp),

    .alert_rx_i(alert_rx_i),
    .alert_tx_o(alert_tx_o),

    .intr_kmac_done_o  (intr_kmac_done_o),
    .intr_fifo_empty_o (intr_fifo_empty_o),
    .intr_kmac_err_o   (intr_kmac_err_o),

    .lc_escalate_en_i(lc_ctrl_pkg::Off),

    .clk_edn_i(clk_i),
    .rst_edn_ni(rst_ni),
    .entropy_o(edn_req_o),
    .entropy_i(edn_rsp_i),

    // Application interfaces (hardware-to-hardware)
    // [0]: KeyMgr, [1]: LC_CTRL, [2]: ROM_CTRL
    // Tied off for initial integration
    .app_i('0),                // No incoming requests from hardware blocks
    .app_o(/* UNUSED */),      // Outgoing responses (not used since no requests)

    // Key manager sideload interface (driven by kmac_wrapper_key_reg)
    .keymgr_key_i(kmac_keymgr_key),

    // Masking enable output (indicates EnMasking parameter value)
    .en_masking_o(/* UNUSED */),

    // Idle output
    .idle_o(kmac_idle)
  );

  // Convert mubi4 to logic
  assign idle_o = prim_mubi_pkg::mubi4_test_true_strict(kmac_idle);

endmodule
