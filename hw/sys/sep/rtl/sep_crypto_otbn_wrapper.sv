// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap the OpenTitan OTBN core with an AXI-Lite CSR bridge and a Key Manager key CSR block.
//
// axi_lite_to_tlul bridges the 32-bit AXI-Lite CSR interface onto the OTBN TL-UL port. The
// AXI4-Lite key interface terminates in the generated otbn_wrapper_key_reg block, whose two
// 384-bit key shares and valid bit drive the OTBN keymgr_key_i sideload port.
// AXCACHE forcing and the AXI 64 to AXI 32 to AXI-Lite 32 conversion chain live in
// sep_crypto_axi_interconnect.
// OTBN is built with the flip-flop register file and the MAI stubbed. Its OTP scrambling-key
// request is answered locally with a fixed key and nonce, acknowledged one cycle after the
// request; lifecycle escalation and RMA requests are tied off.
// Exposes RND and URND EDN clients, the done interrupt, two alerts (index 0 fatal, index 1
// recoverable), and external IMEM/DMEM SRAM structs from prim_ram_1p_scr_ext.
// bus_err_o sticks on a TL-UL error response until bus_err_clr_i.

`include "axi/assign.svh"
`include "axi/typedef.svh"
`include "ocah_registers.svh"

module sep_crypto_otbn_wrapper (
  input  logic clk_i,                         // System clock.
  input  logic rst_ni,                        // Active-low reset.

  input  sep_pkg::sep_32_32_axil_req_t  otbn_axil_req_i,  // OTBN CSR request, bridged to the OTBN
                                                          // TL-UL port; the isolated interconnect
                                                          // leg in sep_crypto.
  output sep_pkg::sep_32_32_axil_resp_t otbn_axil_resp_o,  // OTBN CSR response from the TL-UL
                                                           // bridge.

  input  sep_pkg::sep_32_32_axil_req_t  otbn_key_axil_req_i,  // Key Manager private-bus request to
                                                              // the OTBN key CSR block, which
                                                              // drives the OTBN key sideload
                                                              // interface.
  output sep_pkg::sep_32_32_axil_resp_t otbn_key_axil_resp_o,  // Response from the OTBN key CSR
                                                               // block to the Key Manager.

  output edn_pkg::edn_req_t edn_rnd_req_o,    // OTBN RND entropy request; in sep_crypto, a native
                                              // EDN client of the crypto EDN adapter.
  input  edn_pkg::edn_rsp_t edn_rnd_rsp_i,    // Entropy response for the OTBN RND request.
  output edn_pkg::edn_req_t edn_urnd_req_o,   // OTBN URND reseed request; in sep_crypto, a native
                                              // EDN client of the crypto EDN adapter.
  input  edn_pkg::edn_rsp_t edn_urnd_rsp_i,   // Entropy response for the OTBN URND reseed request.

  output logic intr_done_o,                   // OTBN done interrupt.

  input  prim_alert_pkg::alert_rx_t [1:0] alert_rx_i,  // Alert receiver handshakes; index 0 fatal
                                                       // (fatal), index 1 recoverable (recov).
  output prim_alert_pkg::alert_tx_t [1:0] alert_tx_o,  // Differential alert senders; index 0 fatal
                                                       // (fatal), index 1 recoverable (recov).

  output sep_crypto_pkg::sep_crypto_pka_imem_sram_req_t imem_sram_req_o,  // OTBN instruction-memory request to the external IMEM SRAM, from the scrambled
                                                                          // RAM (prim_ram_1p_scr_ext) inside OTBN.
  input  sep_crypto_pkg::sep_crypto_pka_imem_sram_rsp_t imem_sram_rsp_i,  // Read data from the external IMEM SRAM.
  output sep_crypto_pkg::sep_crypto_pka_dmem_sram_req_t dmem_sram_req_o,  // OTBN data-memory request to the external DMEM SRAM, from the scrambled RAM
                                                                          // inside OTBN.
  input  sep_crypto_pkg::sep_crypto_pka_dmem_sram_rsp_t dmem_sram_rsp_i,  // Read data from the external DMEM SRAM.

  output logic bus_err_o,                     // Set by a TL-UL error response on the CSR bridge;
                                              // sticky until bus_err_clr_i.
  input  logic bus_err_clr_i                  // Clears bus_err_o; a fault in the same cycle still
                                              // sets it. Pulsed by PERIPH_BUS_ERR_CLEAR.otbn in
                                              // sep.
);

  // ========================================================================
  // AXI-Lite (32-bit) -> TL-UL
  // ========================================================================

  tlul_pkg::tl_h2d_t tl_req;
  tlul_pkg::tl_d2h_t tl_resp;

  axi_lite_to_tlul #(
    .AXI_ADDR_WIDTH (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AXI_DATA_WIDTH (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AXI_ID_WIDTH   (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AXI_USER_WIDTH (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .axi_lite_req_t (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_rsp_t (sep_pkg::sep_32_32_axil_resp_t)
  ) u_axi_lite_to_tlul (
    .clk_i,
    .rst_ni,
    .axi_lite_req_i (otbn_axil_req_i),
    .axi_lite_rsp_o (otbn_axil_resp_o),
    .tl_o           (tl_req),
    .tl_i           (tl_resp),
    .err_o          (bus_err_o),
    .err_clr_i      (bus_err_clr_i)
  );

  // ========================================================================
  // OTBN Key CSR Register Block (AXI4-Lite slave for Key Manager key bus)
  //
  // Receives key shares and valid flag from the KM CPU, stores them in
  // write-only CSRs, and drives the keymgr_key_i sideload interface on the
  // OpenTitan OTBN core.
  // ========================================================================

  otbn_wrapper_key_reg_pkg::otbn_wrapper_key__out_t key_csr_hwif_out;

  keymgr_pkg::otbn_key_req_t otbn_keymgr_key;

  assign otbn_keymgr_key.valid = key_csr_hwif_out.KEY_CTRL.key_valid.value;

  for (genvar i = 0; i < 12; i++) begin : gen_key_share_map
    assign otbn_keymgr_key.key[0][i*32 +: 32] = key_csr_hwif_out.KEY_SHARE0[i].data.value;
    assign otbn_keymgr_key.key[1][i*32 +: 32] = key_csr_hwif_out.KEY_SHARE1[i].data.value;
  end

  localparam int unsigned OtbnKeyCsrAddrWidth = otbn_wrapper_key_reg_pkg::OTBN_WRAPPER_KEY_REG_MIN_ADDR_WIDTH;

  otbn_wrapper_key_reg u_otbn_wrapper_key_reg (
    .clk       (clk_i),
    .arst_n    (rst_ni),

    .s_axil_awvalid (otbn_key_axil_req_i.aw_valid),
    .s_axil_awaddr  (otbn_key_axil_req_i.aw.addr[OtbnKeyCsrAddrWidth-1:0]),
    .s_axil_awprot  (otbn_key_axil_req_i.aw.prot),
    .s_axil_awready (otbn_key_axil_resp_o.aw_ready),

    .s_axil_wvalid  (otbn_key_axil_req_i.w_valid),
    .s_axil_wdata   (otbn_key_axil_req_i.w.data),
    .s_axil_wstrb   (otbn_key_axil_req_i.w.strb),
    .s_axil_wready  (otbn_key_axil_resp_o.w_ready),

    .s_axil_bready  (otbn_key_axil_req_i.b_ready),
    .s_axil_bvalid  (otbn_key_axil_resp_o.b_valid),
    .s_axil_bresp   (otbn_key_axil_resp_o.b.resp),

    .s_axil_arvalid (otbn_key_axil_req_i.ar_valid),
    .s_axil_araddr  (otbn_key_axil_req_i.ar.addr[OtbnKeyCsrAddrWidth-1:0]),
    .s_axil_arprot  (otbn_key_axil_req_i.ar.prot),
    .s_axil_arready (otbn_key_axil_resp_o.ar_ready),

    .s_axil_rready  (otbn_key_axil_req_i.r_ready),
    .s_axil_rvalid  (otbn_key_axil_resp_o.r_valid),
    .s_axil_rdata   (otbn_key_axil_resp_o.r.data),
    .s_axil_rresp   (otbn_key_axil_resp_o.r.resp),

    .hwif_out (key_csr_hwif_out)
  );

  // ========================================================================
  // Mock OTP key interface
  // ========================================================================

  otp_ctrl_pkg::otbn_otp_key_req_t otbn_otp_key_req;
  otp_ctrl_pkg::otbn_otp_key_rsp_t otbn_otp_key_rsp;

  logic otbn_otp_key_req_delay;

  `OCAH_FF(otbn_otp_key_req_delay, otbn_otp_key_req.req, 1'b0, clk_i, rst_ni)

  assign otbn_otp_key_rsp.ack        = otbn_otp_key_req_delay;
  assign otbn_otp_key_rsp.key        = 128'h48ecf6c738f0f108a5b08620695ffd4d;
  assign otbn_otp_key_rsp.nonce      = 64'hf88c2578fa4cd123;
  assign otbn_otp_key_rsp.seed_valid = 1'b1;

  // ========================================================================
  // Alert interface
  // ========================================================================

  prim_alert_pkg::alert_rx_t [otbn_reg_pkg::NumAlerts-1:0] otbn_alert_rx;
  prim_alert_pkg::alert_tx_t [otbn_reg_pkg::NumAlerts-1:0] otbn_alert_tx;
  assign otbn_alert_rx = alert_rx_i;
  assign alert_tx_o    = otbn_alert_tx;

  lc_ctrl_pkg::lc_tx_t otbn_lc_rma_ack;

  // ========================================================================
  // Upstream OpenTitan OTBN instance (TileLink interface)
  // ========================================================================

  otbn #(
    .Stub        (1'b0),
    .FeatStubMai (1'b1),
    .RegFile     (otbn_pkg::RegFileFF)
  ) u_otbn (
    .clk_i,
    .rst_ni,

    .tl_i (tl_req),
    .tl_o (tl_resp),

    .idle_o          (/* unused */),
    .intr_done_o     (intr_done_o),

    .alert_rx_i      (otbn_alert_rx),
    .alert_tx_o      (otbn_alert_tx),

    .lc_escalate_en_i(lc_ctrl_pkg::Off),
    .lc_rma_req_i    (lc_ctrl_pkg::Off),
    .lc_rma_ack_o    (otbn_lc_rma_ack),

    .ram_cfg_imem_i    ('0),
    .ram_cfg_dmem_i    ('0),
    .ram_cfg_rsp_imem_o(/* unused */),
    .ram_cfg_rsp_dmem_o(/* unused */),

    .imem_sram_req_o (imem_sram_req_o),
    .imem_sram_rsp_i (imem_sram_rsp_i),
    .dmem_sram_req_o (dmem_sram_req_o),
    .dmem_sram_rsp_i (dmem_sram_rsp_i),

    .clk_edn_i  (clk_i),
    .rst_edn_ni (rst_ni),
    .edn_rnd_o  (edn_rnd_req_o),
    .edn_rnd_i  (edn_rnd_rsp_i),
    .edn_urnd_o (edn_urnd_req_o),
    .edn_urnd_i (edn_urnd_rsp_i),

    .clk_otp_i     (clk_i),
    .rst_otp_ni    (rst_ni),
    .otbn_otp_key_o(otbn_otp_key_req),
    .otbn_otp_key_i(otbn_otp_key_rsp),

    .keymgr_key_i  (otbn_keymgr_key)
  );

endmodule
