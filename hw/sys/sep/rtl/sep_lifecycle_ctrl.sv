// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Derive feature, debug, and DFT disables from eFuse shadow lifecycle state.
//
// Consumes shadow_regs_i and security_disable_i. Publishes feat_ctrl, dbg_disable, SEP/SMC
// fuse DFT disables, demote state, and LC integrity error.
// security_disable_i takes precedence: while it is high every feature enable is 1, even on
// an LC-state integrity error. The FEAT_CTRL, DEMOTE_1 and DEMOTE_2 registers sit behind a
// 64-bit AXI4 slave; each DEMOTE bit is writable only while its lock bit is 0.

module sep_lifecycle_ctrl #(
  parameter int unsigned LC_STATE_WIDTH    = 4,  // Lifecycle state encoding width; the state decode
                                                 // is written for 4.
  localparam int unsigned DEMOTE_WIDTH     = 1,  // Demote field width.
  localparam int unsigned DEMOTE_OUT_WIDTH = 2 * DEMOTE_WIDTH  // Duplicated demote output width.
) (
  input logic clk_i,                          // System clock.
  input logic rst_ni,                         // Active-low reset.

  input logic test_en_i,                      // DFT test-enable (scan-enable).

  input logic security_disable_i,             // Security-disable status from the eFuse wrapper;
                                              // forces every feature enable on.

  input sep_efuse_pkg::efuse_map_t shadow_regs_i,  // eFuse shadow registers; supply the LC state
                                                   // and the SiP and system disable fields.

  output sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t feat_ctrl_o,  // Per-feature enable vector (1 = enabled) derived from the LC state, the SiP and
                                                                     // system disable fuses, and the DEMOTE registers; all ones while security is
                                                                     // disabled, otherwise all zeros on an LC-state integrity error.
  output sep_lifecycle_ctrl_pkg::dbg_disable_t         dbg_disable_o,  // Per-interface debug disables for the DTP, active-high (1 = disabled); the SEP
                                                                       // and SMC OTP JTAG-to-AXI disables are tied to 0.
  output logic sep_fuse_dft_disable_o,        // Disables the SEP fuse DFT access path, active-high;
                                              // no functional consumer, provided for DFT insertion.
  output logic smc_fuse_dft_disable_o,        // Disables the SMC fuse DFT access path, active-high;
                                              // no functional consumer, provided for DFT insertion.
  output logic [DEMOTE_OUT_WIDTH-1:0] lcc_demote_state_1_o,  // Differentially encoded
                                                             // DEMOTE_1.demote register bit, which
                                                             // re-opens debug feature bits [23:0]
                                                             // in TEST_DEV and PROD.
  output logic [DEMOTE_OUT_WIDTH-1:0] lcc_demote_state_2_o,  // Differentially encoded
                                                             // DEMOTE_2.demote register bit, which
                                                             // re-opens debug feature bits [47:24]
                                                             // in TEST_DEV and PROD.
  output logic lc_sigint_err_o,               // Integrity error on the differentially encoded LC
                                              // state; forces every feature enable off unless
                                              // security is disabled.

  input sep_pkg::sep_32_64_6_12_axi_req_t lifecycle_axi_req_i,  // AXI4 request to the lifecycle
                                                                // registers, converted to 64-bit
                                                                // AXI-Lite; offset bits [4:0] are
                                                                // decoded.
  output sep_pkg::sep_32_64_6_12_axi_resp_t lifecycle_axi_resp_o  // AXI4 response from the
                                                                  // lifecycle registers.
);

  // debug/test/func feature control
  typedef struct packed {
    logic demote;
    logic lock;
    logic [63:2] rsvd;
  } demote_reg_t;

  demote_reg_t demote_reg_1;
  demote_reg_t demote_reg_2;

  logic [LC_STATE_WIDTH-1:0] lc_state_raw;

  // Differential encode/decode for DEMOTE_1
  prim_diff_encode_multi #(
    .Width(DEMOTE_WIDTH)
  ) u_demote_1_diff_enc (
    .clk_i,
    .rst_ni  (rst_ni),
    .data_i  (demote_reg_1.demote),
    .data_o  (lcc_demote_state_1_o)
  );

  // Differential encode/decode for DEMOTE_2
  prim_diff_encode_multi #(
    .Width(DEMOTE_WIDTH)
  ) u_demote_2_diff_enc (
    .clk_i,
    .rst_ni  (rst_ni),
    .data_i  (demote_reg_2.demote),
    .data_o  (lcc_demote_state_2_o)
  );

  // Differential decode for LC_STATE
  prim_diff_decode_multi #(
    .Width(LC_STATE_WIDTH)
  ) u_lc_state_dec (
    .clk_i,
    .rst_ni  (rst_ni),
    .data_i  (shadow_regs_i.fields.lc_state.lc_state[2*LC_STATE_WIDTH-1:0]),
    .data_o  (lc_state_raw),
    .sigint_o(lc_sigint_err_o)
  );

  // Demotion debug disable vector sub-groups
  localparam int unsigned DBG_1_LSB = 0;
  localparam int unsigned DBG_1_MSB = 23;
  localparam int unsigned DBG_2_LSB = 24;
  localparam int unsigned DBG_2_MSB = 47;

  sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t feat_ctrl;
  sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t feat_ctrl_sec_dis_ovrd;

  // Security-disable feature control
  assign feat_ctrl_sec_dis_ovrd = security_disable_i ? 64'hffff_ffff_ffff_ffff : feat_ctrl;

  // Logic follows 'Table 50. Per-LC-state feature control profile'
  always_comb begin
    if (lc_sigint_err_o) begin
      feat_ctrl = 64'd0;
    end else
      unique case (lc_state_raw) inside

        4'b0000: begin  // TEST_DEV state
          feat_ctrl = ~(shadow_regs_i.fields.sip_dis | shadow_regs_i.fields.sys_dis);
          if (demote_reg_1.demote) begin
            feat_ctrl[DBG_1_MSB:DBG_1_LSB] = '1;
          end
          if (demote_reg_2.demote) begin
            feat_ctrl[DBG_2_MSB:DBG_2_LSB] = '1;
          end
        end

        4'b0001: begin  // PROD state
          feat_ctrl = 64'h0;
          feat_ctrl.func_reserved = ~(shadow_regs_i.fields.sip_dis.func_reserved |
                                    shadow_regs_i.fields.sys_dis.func_reserved);
          if (demote_reg_1.demote) begin
            feat_ctrl[DBG_1_MSB:DBG_1_LSB] = ~(shadow_regs_i.fields.sip_dis[DBG_1_MSB:DBG_1_LSB] |
                                               shadow_regs_i.fields.sys_dis[DBG_1_MSB:DBG_1_LSB]);
          end
          if (demote_reg_2.demote) begin
            feat_ctrl[DBG_2_MSB:DBG_2_LSB] = ~(shadow_regs_i.fields.sip_dis[DBG_2_MSB:DBG_2_LSB] |
                                               shadow_regs_i.fields.sys_dis[DBG_2_MSB:DBG_2_LSB]);
          end
        end

        4'b1000: begin  // PROD_END state
          feat_ctrl = 64'h0;
          feat_ctrl.func_reserved  = ~(shadow_regs_i.fields.sip_dis.func_reserved | shadow_regs_i.fields.sys_dis.func_reserved);
        end

        4'b001?: begin  // RMA_SiP state
          feat_ctrl = ~(shadow_regs_i.fields.sip_dis);
        end

        4'b011?: begin  // RMA_CHIPLET state
          feat_ctrl = 64'hffff_ffff_ffff_ffff;
        end

        default: begin  // INVALID/others
          feat_ctrl = 64'd0;
        end

      endcase
  end

  // AXI-Lite interface signals between AXI-to-AXIL converter and register block
  sep_pkg::sep_32_64_axil_req_t  lifecycle_axil_req;
  sep_pkg::sep_32_64_axil_resp_t lifecycle_axil_resp;

  axi_to_axi_lite #(
    .AxiAddrWidth   (sep_pkg::SEP_CRYPTO_AXI_ADDR_WIDTH),
    .AxiDataWidth   (64),
    .AxiIdWidth     (sep_pkg::SEP_CRYPTO_AXI_ID_WIDTH),
    .AxiUserWidth   (sep_pkg::SEP_CRYPTO_AXI_USER_WIDTH),
    .AxiMaxWriteTxns(16),
    .AxiMaxReadTxns (16),
    .FullBW         (1'b0), // ID Queue in Full BW mode in axi_burst_splitter
    .FallThrough    (1'b0), // FIFOs in Fall through mode in ID reflect
    .SpillAw        (1'b0), // Spill register control
    .SpillW         (1'b0),
    .SpillB         (1'b0),
    .SpillAr        (1'b0),
    .SpillR         (1'b0),
    .full_req_t     (sep_pkg::sep_32_64_6_12_axi_req_t),
    .full_resp_t    (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .lite_req_t     (sep_pkg::sep_32_64_axil_req_t),
    .lite_resp_t    (sep_pkg::sep_32_64_axil_resp_t)
  ) u_lifecycle_axi_to_axi_lite (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_i(test_en_i),
    // from AXI (32-bit after DW conversion)
    .slv_req_i (lifecycle_axi_req_i),
    .slv_resp_o(lifecycle_axi_resp_o),
    // to AXIL (32-bit)
    .mst_req_o (lifecycle_axil_req),
    .mst_resp_i(lifecycle_axil_resp)
  );

  logic demote_wen_1;
  logic demote_wen_2;
  assign demote_wen_1 = ~demote_reg_1.lock; // When DEMOTE_1.lock is 0, firmware can assert DEMOTE_1.demote
  assign demote_wen_2 = ~demote_reg_2.lock; // When DEMOTE_2.lock is 0, firmware can assert DEMOTE_2.demote

  sep_lifecycle_ctrl_reg_pkg::sep_lifecycle_ctrl__in_t lifecycle_ctrl_hwif_in;
  sep_lifecycle_ctrl_reg_pkg::sep_lifecycle_ctrl__out_t lifecycle_ctrl_hwif_out;

  assign lifecycle_ctrl_hwif_in.FEAT_CTRL.feature_control.next = feat_ctrl_sec_dis_ovrd;
  assign lifecycle_ctrl_hwif_in.DEMOTE_1.demote.swwe = demote_wen_1;
  assign lifecycle_ctrl_hwif_in.DEMOTE_2.demote.swwe     = demote_wen_2;

  assign demote_reg_1.demote = lifecycle_ctrl_hwif_out.DEMOTE_1.demote.value;
  assign demote_reg_1.lock   = lifecycle_ctrl_hwif_out.DEMOTE_1.lock.value;
  assign demote_reg_1.rsvd   = lifecycle_ctrl_hwif_out.DEMOTE_1.rsvd.value;
  assign demote_reg_2.demote = lifecycle_ctrl_hwif_out.DEMOTE_2.demote.value;
  assign demote_reg_2.lock   = lifecycle_ctrl_hwif_out.DEMOTE_2.lock.value;
  assign demote_reg_2.rsvd   = lifecycle_ctrl_hwif_out.DEMOTE_2.rsvd.value;

  sep_lifecycle_ctrl_reg u_sep_lifecycle_ctrl_reg (
    .clk(clk_i),
    .arst_n(rst_ni),
    .s_axil_awready(lifecycle_axil_resp.aw_ready),
    .s_axil_awvalid(lifecycle_axil_req.aw_valid),
    .s_axil_awaddr(lifecycle_axil_req.aw.addr[4:0]),
    .s_axil_awprot(lifecycle_axil_req.aw.prot),
    .s_axil_wready(lifecycle_axil_resp.w_ready),
    .s_axil_wvalid(lifecycle_axil_req.w_valid),
    .s_axil_wdata(lifecycle_axil_req.w.data),
    .s_axil_wstrb(lifecycle_axil_req.w.strb),
    .s_axil_bready(lifecycle_axil_req.b_ready),
    .s_axil_bvalid(lifecycle_axil_resp.b_valid),
    .s_axil_bresp(lifecycle_axil_resp.b.resp),
    .s_axil_arready(lifecycle_axil_resp.ar_ready),
    .s_axil_arvalid(lifecycle_axil_req.ar_valid),
    .s_axil_araddr(lifecycle_axil_req.ar.addr[4:0]),
    .s_axil_arprot(lifecycle_axil_req.ar.prot),
    .s_axil_rready(lifecycle_axil_req.r_ready),
    .s_axil_rvalid(lifecycle_axil_resp.r_valid),
    .s_axil_rdata(lifecycle_axil_resp.r.data),
    .s_axil_rresp(lifecycle_axil_resp.r.resp),
    .hwif_in(lifecycle_ctrl_hwif_in),
    .hwif_out(lifecycle_ctrl_hwif_out)
  );

  // The three nested reachability cases of 'Debug and Test Port Path Gating'.
  // Disable-polarity: a case is disabled when any bit it requires is closed, and a
  // granular bit is an additional term rather than a substitute.
  logic case_1_dis;
  logic case_2_dis;
  logic case_3_dis;

  assign case_1_dis = !feat_ctrl_sec_dis_ovrd.sip_debug;
  assign case_2_dis = case_1_dis || !feat_ctrl_sec_dis_ovrd.chiplet_dbg;
  assign case_3_dis = case_2_dis || !feat_ctrl_sec_dis_ovrd.sep_debug;

  // Debug-disable derivations (active-high; 1 = disabled).
  assign dbg_disable_o.stap_io          = case_1_dis;
  assign dbg_disable_o.dfd              = case_1_dis;
  assign dbg_disable_o.stap_host        = case_1_dis;
  assign dbg_disable_o.stap_smc         = case_2_dis;
  assign dbg_disable_o.stap_extra       = case_2_dis;
  assign dbg_disable_o.dft_nonsecure    = case_2_dis;
  assign dbg_disable_o.smc_jtag2axi     = case_2_dis;
  assign dbg_disable_o.dft_secure       = case_3_dis;
  assign dbg_disable_o.stap_sep         = case_3_dis;
  assign dbg_disable_o.smc_otp_jtag2axi = 1'b0;
  assign dbg_disable_o.sep_otp_jtag2axi = 1'b0;

  // DFT-inserted fuse access paths. No functional logic consumes these;
  // They exist for an adopter's DFT insertion to connect to
  assign sep_fuse_dft_disable_o = case_3_dis || !feat_ctrl_sec_dis_ovrd.sep_fuse_dbg;
  assign smc_fuse_dft_disable_o = case_2_dis || !feat_ctrl_sec_dis_ovrd.smc_fuse_dbg;

  assign feat_ctrl_o = feat_ctrl_sec_dis_ovrd;
endmodule
