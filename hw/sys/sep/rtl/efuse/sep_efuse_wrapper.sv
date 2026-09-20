// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP eFuse Wrapper
//
//-----------------------------------------------------------------------------
//
// Wraps the generic `efuse_interface_controller` for SEP and implements the
// SEP-specific data-path conversion, security policy, and secure test mode control:
//   * Downsizes the functional AXI4 slave from the local crossbar (64-bit) to
//     32-bit, then converts it to AXI4-Lite for the eFuse controller.
//   * Implements the SEP JTAG access-control policy: in a restricted state
//     (PROD / RMA_SiP, or an LC-state differential-decode integrity error)
//     block JTAG accesses to the eFuse except the MMR / token register space,
//     which stays accessible (e.g. for RMA_SiP token programming).
//   * Upon cold reset release, if secure test mode is enabled, latch the secure test mode signal.

`include "axi/assign.svh"
`include "axi/typedef.svh"

module sep_efuse_wrapper #(
  // During synthesis, to be replaced with the actual token digest embedded in the netlist
  parameter bit [255:0] SEP_SEC_DISABLE_TOKEN = 256'b0
) (
  input logic                                clk_i,
  input logic                                rst_ni,

  input  logic                               test_en_i,
  input  logic                               scan_rst_ni,

  input  logic                               secure_tm_req_i,
  input  logic                               ext_boot_seq_done_i,

  output logic                               security_disable_o,
  output logic [2*sep_pkg::LC_STATE_BIT_WIDTH-1:0] lc_state_o,
  output sep_efuse_pkg::efuse_map_t          shadow_regs_o,
  output logic                               fuse_sense_done_o,
  output logic                               secure_tm_o,

  // OTP debug AXI-Lite manager interface
  input  sep_efuse_pkg::efuse_axil_req_t     axil_sep_otp_jtag_req_i,
  output sep_efuse_pkg::efuse_axil_resp_t    axil_sep_otp_jtag_resp_o,

  // Key Manager AXI-Lite manager interface
  input  sep_efuse_pkg::efuse_axil_req_t     km_efuse_axil_req_i,
  output sep_efuse_pkg::efuse_axil_resp_t    km_efuse_axil_resp_o,

  // Full AXI4 slave from local crossbar
  input  sep_pkg::sep_crypto_axi_req_t       sep_efuse_axi_req_i,
  output sep_pkg::sep_crypto_axi_resp_t      sep_efuse_axi_resp_o,

  // Efuse Interface to SHIM
  output sep_efuse_pkg::efuse_axil_req_t     efuse_bank_ctrl_req_o,
  input  sep_efuse_pkg::efuse_axil_resp_t    efuse_bank_ctrl_resp_i,

  // Efuse Command Interface - custom interface for SHIM
  output sep_efuse_pkg::fuse_command_req_t   efuse_shim_command_req_o,
  input  sep_efuse_pkg::fuse_command_resp_t  efuse_shim_command_resp_i,

  // Efuse intermediate reset
  output logic                               sep_intermediate_reset_no,

  // Debug signals
  output logic [9:0]                         sep_efuse_debug_o,
  output logic [5:0]                         sep_efuse_token_match_sip_debug_o,
  output logic [5:0]                         sep_efuse_token_match_chiplet_debug_o,

  // Locked Field Access Interrupt
  output logic                               locked_field_access_interrupt_o,

  // Token Comparator Redundancy Fault Interrupt
  output logic                               token_match_fault_o
);

  // Intermediate 32-bit AXI (after data-width conversion)
  localparam int unsigned SEP_EFUSE_AXI32_DATA_WIDTH = 32;
  localparam int unsigned SEP_EFUSE_AXI32_STRB_WIDTH = SEP_EFUSE_AXI32_DATA_WIDTH / 8;
  typedef logic [SEP_EFUSE_AXI32_DATA_WIDTH-1:0] sep_efuse_axi32_data_t;
  typedef logic [SEP_EFUSE_AXI32_STRB_WIDTH-1:0] sep_efuse_axi32_strb_t;
  `AXI_TYPEDEF_ALL(sep_efuse_axi32, sep_pkg::sep_crypto_axi_addr_t, sep_pkg::sep_crypto_axi_id_t,
                   sep_efuse_axi32_data_t, sep_efuse_axi32_strb_t, sep_pkg::sep_crypto_axi_user_t)

  sep_efuse_axi32_req_t  sep_efuse_axi32_req;
  sep_efuse_axi32_resp_t sep_efuse_axi32_resp;

  // Intermediate AXI4-Lite (after data-width conversion)
  sep_efuse_pkg::efuse_axil_req_t efuse_axil_req_i;
  sep_efuse_pkg::efuse_axil_resp_t efuse_axil_resp_o;

  // JTAG AXI4-Lite Post-access-control demux
  sep_efuse_pkg::efuse_axil_req_t  [1:0] axil_sep_otp_jtag_req_filtered;
  sep_efuse_pkg::efuse_axil_resp_t [1:0] axil_sep_otp_jtag_resp_filtered;

  // AXI4-Lite after muxing the crossbar path with the Key Manager path
  sep_efuse_pkg::efuse_axil_req_t  efuse_axil_mux_req;
  sep_efuse_pkg::efuse_axil_resp_t efuse_axil_mux_resp;

  // JTAG access control policy signals
  logic is_wr_access_token;
  logic is_rd_access_token;
  logic [sep_pkg::LC_STATE_BIT_WIDTH-1:0] lc_state_local_raw;
  logic lc_sigint_err;
  logic lc_restricted_state;
  localparam sep_efuse_pkg::addr_t EFUSE_MMR_BASE_ADDR =
      sep_efuse_pkg::addr_t'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_EFUSE_MMR_BASE_ADDR);
  localparam sep_efuse_pkg::addr_t EFUSE_MMR_SIZE =
      sep_efuse_pkg::addr_t'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_EFUSE_MMR_SIZE);

  // Efuse signals
  logic fuse_sense_done;
  logic security_disable;

  // Secure Test Mode Control signals
  logic [1:0] reset_cycle_cnt;
  logic fuse_sense_done_1dly;
  logic fuse_sense_done_posedge;
  logic secure_tm_n0_scan;

  // First downsize AXI data width 64 -> 32, then convert to AXI-Lite
  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_CRYPTO_AXI_DATA_WIDTH),
    .AxiMstPortDataWidth (SEP_EFUSE_AXI32_DATA_WIDTH),
    .AxiAddrWidth        (sep_pkg::SEP_CRYPTO_AXI_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_CRYPTO_AXI_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_crypto_axi_aw_chan_t),
    .mst_w_chan_t        (sep_efuse_axi32_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_crypto_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_crypto_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_crypto_axi_ar_chan_t),
    .mst_r_chan_t        (sep_efuse_axi32_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_crypto_axi_r_chan_t),
    .axi_mst_req_t       (sep_efuse_axi32_req_t),
    .axi_mst_resp_t      (sep_efuse_axi32_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_crypto_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_crypto_axi_resp_t)
  ) u_sep_efuse_axi_dw_conv (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .slv_req_i (sep_efuse_axi_req_i),
    .slv_resp_o(sep_efuse_axi_resp_o),
    .mst_req_o (sep_efuse_axi32_req),
    .mst_resp_i(sep_efuse_axi32_resp)
  );

  // Convert downsized AXI4 to AXI4-Lite
  axi_to_axi_lite #(
    .AxiAddrWidth   (sep_pkg::SEP_CRYPTO_AXI_ADDR_WIDTH),
    .AxiDataWidth   (SEP_EFUSE_AXI32_DATA_WIDTH),
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
    .full_req_t     (sep_efuse_axi32_req_t),
    .full_resp_t    (sep_efuse_axi32_resp_t),
    .lite_req_t     (sep_efuse_pkg::efuse_axil_req_t),
    .lite_resp_t    (sep_efuse_pkg::efuse_axil_resp_t)
  ) sep_efuse_axi_to_axi_lite (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_i(test_en_i),
    // from AXI (32-bit after DW conversion)
    .slv_req_i (sep_efuse_axi32_req),
    .slv_resp_o(sep_efuse_axi32_resp),
    // to AXIL (32-bit)
    .mst_req_o (efuse_axil_req_i),
    .mst_resp_i(efuse_axil_resp_o)
  );

  /////////////////////////////////////////////////////////////
  // Secure Test Mode Control
  /////////////////////////////////////////////////////////////

  // Positive edge detection of fuse_sense_done
  always_ff @(posedge clk_i) begin
    if (!rst_ni) fuse_sense_done_1dly <= 1'b0;
    else fuse_sense_done_1dly <= fuse_sense_done;
  end
  assign fuse_sense_done_posedge = fuse_sense_done && !fuse_sense_done_1dly;

  // Reset cycle counter, measured from cold-reset (rst_ni) release. Saturates at 2.
  always_ff @(posedge clk_i) begin
    if (!rst_ni) reset_cycle_cnt <= 2'd0;
    else if (reset_cycle_cnt == 2'd2) reset_cycle_cnt <= reset_cycle_cnt;
    else reset_cycle_cnt <= reset_cycle_cnt + 2'd1;
  end

  // Secure Test Mode Flop
  //   - If security_disable is asserted, the test_en strap is latched on chiplet cold reset release.
  //   - If security_disable is NOT asserted, the test_en strap is latched when SEP fuse sense is done.
  always_ff @(posedge clk_i) begin
    if (!rst_ni) secure_tm_n0_scan <= 1'b0;
    else if (security_disable && (reset_cycle_cnt == 2'd1)) secure_tm_n0_scan <= secure_tm_req_i;
    else if (fuse_sense_done_posedge) secure_tm_n0_scan <= secure_tm_req_i;
  end

  /////////////////////////////////////////////////////////////
  // JTAG Access Control Policy
  ///////////////////////////////////////////////////////////////

  prim_diff_decode_multi #(
    .Width(sep_pkg::LC_STATE_BIT_WIDTH)
  ) u_lc_state_jtag_dec (
    .clk_i,
    .rst_ni,
    .data_i  (shadow_regs_o.fields.lc_state.lc_state[2*sep_pkg::LC_STATE_BIT_WIDTH-1:0]),
    .data_o  (lc_state_local_raw),
    .sigint_o(lc_sigint_err)
  );

  // Additional control shall be applied to the JTAG port, such that, in PROD and RMA_SIP states, it can only access the MMR registers.
  assign is_wr_access_token = axil_sep_otp_jtag_req_i.aw.addr inside
      {[EFUSE_MMR_BASE_ADDR:
        EFUSE_MMR_BASE_ADDR + EFUSE_MMR_SIZE - sep_efuse_pkg::addr_t'(1)]};
  assign is_rd_access_token = axil_sep_otp_jtag_req_i.ar.addr inside
      {[EFUSE_MMR_BASE_ADDR:
        EFUSE_MMR_BASE_ADDR + EFUSE_MMR_SIZE - sep_efuse_pkg::addr_t'(1)]};

  // A differential-decode integrity error (lc_sigint_err) is treated as a restricted state, exactly like PROD / RMA_SiP.
  assign lc_restricted_state = lc_sigint_err ||
                                 (lc_state_local_raw == 4'b0001) ||                               // PROD STATE
                                 (lc_state_local_raw[sep_pkg::LC_STATE_BIT_WIDTH-1:1] == 3'b001); // RMA_SIP STATE

  axi_lite_demux #(
    .aw_chan_t(sep_efuse_pkg::efuse_axil_aw_chan_t),
    .w_chan_t(sep_efuse_pkg::efuse_axil_w_chan_t),
    .b_chan_t(sep_efuse_pkg::efuse_axil_b_chan_t),
    .ar_chan_t(sep_efuse_pkg::efuse_axil_ar_chan_t),
    .r_chan_t(sep_efuse_pkg::efuse_axil_r_chan_t),
    .axi_req_t(sep_efuse_pkg::efuse_axil_req_t),
    .axi_resp_t(sep_efuse_pkg::efuse_axil_resp_t),
    .NoMstPorts(2),
    .MaxTrans(2),
    .FallThrough(1'b1),
    .SpillAw(1'b1),
    .SpillW(1'b1),
    .SpillB(1'b1),
    .SpillAr(1'b1),
    .SpillR(1'b1)
  ) u_axi_lite_demux_jtag_access_ctrl (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_i(test_en_i),
    .slv_req_i(axil_sep_otp_jtag_req_i),
    .slv_aw_select_i(lc_restricted_state && !is_wr_access_token),
    .slv_ar_select_i(lc_restricted_state && !is_rd_access_token),
    .slv_resp_o(axil_sep_otp_jtag_resp_o),
    .mst_reqs_o(axil_sep_otp_jtag_req_filtered),
    .mst_resps_i(axil_sep_otp_jtag_resp_filtered)
  );

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH(sep_efuse_pkg::ADDR_WIDTH),
    .AXI_DATA_WIDTH(sep_efuse_pkg::DATA_WIDTH),
    .axil_req_t    (sep_efuse_pkg::efuse_axil_req_t),
    .axil_resp_t   (sep_efuse_pkg::efuse_axil_resp_t),
    .RESP_WIDTH    (sep_efuse_pkg::DATA_WIDTH),
    .RESP_DATA     (32'hbadcab1e),
    .MAX_TRANS     (2)
  ) u_prim_axi_lite_err_slv_jtag_access_ctrl (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .axil_req_i (axil_sep_otp_jtag_req_filtered[1]),
    .axil_resp_o(axil_sep_otp_jtag_resp_filtered[1])
  );

  // Merge the crossbar-sourced AXI-Lite path with the Key Manager AXI-Lite
  // path. Slave port 0 = crossbar path, slave port 1 = Key Manager.
  axi_lite_mux #(
    .aw_chan_t   (sep_efuse_pkg::efuse_axil_aw_chan_t),
    .w_chan_t    (sep_efuse_pkg::efuse_axil_w_chan_t),
    .b_chan_t    (sep_efuse_pkg::efuse_axil_b_chan_t),
    .ar_chan_t   (sep_efuse_pkg::efuse_axil_ar_chan_t),
    .r_chan_t    (sep_efuse_pkg::efuse_axil_r_chan_t),
    .axi_req_t   (sep_efuse_pkg::efuse_axil_req_t),
    .axi_resp_t  (sep_efuse_pkg::efuse_axil_resp_t),
    .NoSlvPorts  (2),
    .MaxTrans    (2),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b1),
    .SpillB      (1'b1),
    .SpillAr     (1'b1),
    .SpillR      (1'b1)
  ) u_km_efuse_axi_lite_mux (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (test_en_i),
    .slv_reqs_i  ({km_efuse_axil_req_i,  efuse_axil_req_i}),
    .slv_resps_o ({km_efuse_axil_resp_o, efuse_axil_resp_o}),
    .mst_req_o   (efuse_axil_mux_req),
    .mst_resp_i  (efuse_axil_mux_resp)
  );

  /////////////////////////////////////////////////////////////
  // eFuse Interface Controller
  /////////////////////////////////////////////////////////////

  efuse_interface_controller #(
    .ADDR_WIDTH                 (sep_efuse_pkg::ADDR_WIDTH),
    .DATA_WIDTH                 (sep_efuse_pkg::DATA_WIDTH),

    .addr_t                     (sep_efuse_pkg::addr_t),
    .data_t                     (sep_efuse_pkg::data_t),
    .strb_t                     (sep_efuse_pkg::strb_t),
    .efuse_axil_req_t           (sep_efuse_pkg::efuse_axil_req_t),
    .efuse_axil_resp_t          (sep_efuse_pkg::efuse_axil_resp_t),

    .efuse_axil_aw_chan_t       (sep_efuse_pkg::efuse_axil_aw_chan_t),
    .efuse_axil_w_chan_t        (sep_efuse_pkg::efuse_axil_w_chan_t),
    .efuse_axil_b_chan_t        (sep_efuse_pkg::efuse_axil_b_chan_t),
    .efuse_axil_ar_chan_t       (sep_efuse_pkg::efuse_axil_ar_chan_t),
    .efuse_axil_r_chan_t        (sep_efuse_pkg::efuse_axil_r_chan_t),
    .efuse_apb_req_t            (sep_efuse_pkg::efuse_apb_req_t),
    .efuse_apb_resp_t           (sep_efuse_pkg::efuse_apb_resp_t),

    .efuse_addr_t               (sep_efuse_pkg::efuse_addr_bit_t),
    .efuse_data_t               (sep_efuse_pkg::efuse_data_t),
    .efuse_word_counter_t       (sep_efuse_pkg::efuse_word_counter_t),
    .fuse_command_req_t         (sep_efuse_pkg::fuse_command_req_t),
    .fuse_command_resp_t        (sep_efuse_pkg::fuse_command_resp_t),

    .SEP_SEC_DISABLE_TOKEN      (SEP_SEC_DISABLE_TOKEN),

    .EFUSE_MAP_REG_MAP_BASE_ADDR(32'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR)),
    .EFUSE_MAP_REG_MAP_SIZE     (32'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIZE)),

    .EFUSE_MMR_REG_MAP_BASE_ADDR(32'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_EFUSE_MMR_BASE_ADDR)),
    .EFUSE_MMR_REG_MAP_SIZE     (32'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_EFUSE_MMR_SIZE)),

    .EFUSE_CTRL_REG_MAP_BASE_ADDR(32'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR)),
    .EFUSE_CTRL_REG_MAP_SIZE     (32'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_EFUSE_INTERFACE_CTRL_SIZE)),

    .SHADOW_REG_BITS            (sep_efuse_pkg::SHADOW_REG_BITS),
    .EFUSE_MACRO_WORD_WIDTH     (sep_efuse_pkg::NumFuseWordWidth),

    .EFUSE_FIELDS               (sep_efuse_pkg::NUM_EFUSE_FIELDS),

    .HAS_LC_STATE               (1'b1), // SEP has LC state
    .CLASS1_SHADOW_RANGES       (sep_efuse_pkg::Class1ShadowRanges),
    .SECRET_SHADOW_RANGES       (sep_efuse_pkg::SecretShadowRanges),
    .LC_STATE_WIDTH             (sep_pkg::LC_STATE_BIT_WIDTH),
    .LC_STATE_BIT_POSITION      (sep_pkg::LC_STATE_BIT_POSITION),

    .efuse_map_t                (sep_efuse_pkg::efuse_map_t)

  ) u_efuse_interface_controller (
    // Global Interface
    .clk_i                      (clk_i),
    .rst_ni                     (rst_ni),

    .test_en_i                  (test_en_i),
    .scan_rst_ni                (scan_rst_ni),

    // AXI4-Lite Register Interface (muxed crossbar + Key Manager)
    .axil_req_i                 (efuse_axil_mux_req),
    .axil_resp_o                (efuse_axil_mux_resp),

    .axil_jtag_req_i            (axil_sep_otp_jtag_req_filtered[0]),
    .axil_jtag_resp_o           (axil_sep_otp_jtag_resp_filtered[0]),

    // AXI4-Lite Register Interface from Efuse Controller to shim CSR
    .fuse_bank_ctrl_req_o       (efuse_bank_ctrl_req_o),
    .fuse_bank_ctrl_resp_i      (efuse_bank_ctrl_resp_i),

    // eFuse Command Interface - custom interface for SHIM state machine
    .fuse_command_req_o         (efuse_shim_command_req_o),
    .fuse_command_resp_i        (efuse_shim_command_resp_i),

    .secure_tm_i                (secure_tm_n0_scan),
    .security_disable_i         (1'b0), // in SEP we use internal security disable and tie off the input to efuse_interface
    .efuse_field_map_i          (sep_efuse_pkg::EfuseFieldMap),

    .reset_n_o                  (sep_intermediate_reset_no),
    .fuse_sense_done_o          (fuse_sense_done),
    .security_disable_o         (security_disable), // Used for LC control, and secure_tm latch logic
    .shadow_regs_o              (shadow_regs_o),

    .ext_boot_seq_done_i        (ext_boot_seq_done_i), // Integration-defined boot-sequence-done indication (e.g. memory repair done and straps from SMC)

    // Debug signals
    .is_write_locked_shadow_regs_o(sep_efuse_debug_o[0]),
    .is_read_locked_shadow_regs_o (sep_efuse_debug_o[1]),
    .is_program_locked_o          (sep_efuse_debug_o[2]),
    .is_read_locked_o             (sep_efuse_debug_o[3]),
    .is_write_setup_only_o        (sep_efuse_debug_o[4]),
    .is_lc_state_access_o         (sep_efuse_debug_o[5]),
    .is_read_timeout_debug_o      (sep_efuse_debug_o[6]),
    .is_program_timeout_debug_o   (sep_efuse_debug_o[7]),
    .is_efuse_req_err_o           (sep_efuse_debug_o[8]),
    .is_secure_tm_blocked_o       (sep_efuse_debug_o[9]),
    .is_rma_sip_token_match_debug (sep_efuse_token_match_sip_debug_o),
    .is_rma_chiplet_token_match_debug (sep_efuse_token_match_chiplet_debug_o),

    .sec_disable_token_o          (),

    .locked_field_access_interrupt_o  (locked_field_access_interrupt_o),

    .token_match_fault_o              (token_match_fault_o)
  );



  // SEP LC state output
  assign lc_state_o = shadow_regs_o.fields.lc_state.lc_state;

  assign secure_tm_o = secure_tm_n0_scan;
  assign security_disable_o = security_disable;
  assign fuse_sense_done_o = fuse_sense_done;

endmodule
