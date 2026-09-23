// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SMC eFuse Wrapper
//
//-----------------------------------------------------------------------------
//
// Wraps the generic `efuse_interface_controller` for SMC and implements the
// SMC-specific JTAG access-control policy:
//   * Block JTAG accesses to the eFuse when the SMC LC state (received from
//     SEP, differentially encoded) is PROD or RMA_SiP.
//   * Always allow JTAG reads of the JTAG_PUBLIC_IDENTITY register, so a part
//     can still be identified in the field once the rest of the map is closed off.
//   * On a differential-decode integrity error, restrict JTAG access.
//
// JTAG transactions that fail the policy are routed to a `prim_axi_lite_err_slv`
// which returns `32'hbadcab1e` with a slave error response.

module smc_efuse_wrapper
  import smc_pkg::*;
  import smc_efuse_pkg::*;
(
  input  logic                                       clk_i,
  input  logic                                       rst_ni,
  input  logic                                       test_en_i,
  input  logic                                       scan_rst_ni,

  // Functional AXI4-Lite slave (from SMC peripherals xbar)
  input  smc_pkg::smc_axil_32_32_req_t               axil_req_i,
  output smc_pkg::smc_axil_32_32_resp_t              axil_resp_o,

  // JTAG AXI4-Lite slave
  input  smc_pkg::smc_axil_32_32_req_t               axil_smc_otp_jtag_req_i,
  output smc_pkg::smc_axil_32_32_resp_t              axil_smc_otp_jtag_resp_o,

  // LC state from SEP (differentially encoded) and sigint error output
  input  logic [2*smc_pkg::LC_STATE_WIDTH-1:0]       lc_state_i,
  output logic                                       lc_sigint_err_o,

  // eFuse SHIM CSR AXI4-Lite
  output smc_pkg::smc_axil_32_32_req_t               fuse_bank_ctrl_req_o,
  input  smc_pkg::smc_axil_32_32_resp_t              fuse_bank_ctrl_resp_i,

  // eFuse Command Interface - custom interface for SHIM state machine
  output smc_efuse_pkg::fuse_command_req_t           efuse_shim_command_req_o,
  input  smc_efuse_pkg::fuse_command_resp_t          efuse_shim_command_resp_i,

  // SEP security disable
  input  logic                                       sep_security_disable_i,

  // External boot sequence done (gate the released reset)
  input  logic                                       ext_boot_seq_done_i,

  // Released reset and fuse sense done
  output logic                                       reset_n_o,
  output logic                                       fuse_sense_done_o,

  // Shadow registers
  output smc_efuse_pkg::efuse_map_t                  shadow_regs_o,

  // Debug
  output logic [9:0]                                 efuse_debug_o,

  // Locked Field Access Interrupt
  output logic                                       locked_field_access_interrupt_o
);

  /////////////////////////////////////////////////////////////////////////
  // JTAG access control
  /////////////////////////////////////////////////////////////////////////

  // SMC variant: no local LC state input. Restrict JTAG access when SMC's
  // LC state (from SEP) is PROD or RMA_SiP, except for reads of the
  // JTAG_PUBLIC_IDENTITY register which remains accessible.
  //
  // JTAG_PUBLIC_IDENTITY is 256 bits (8 x 32-bit words = 32 bytes), so its
  // byte-address range spans BASE .. BASE + 'h1F (inclusive).

  smc_pkg::smc_axil_32_32_req_t  [1:0] axil_smc_otp_jtag_req_filtered;
  smc_pkg::smc_axil_32_32_resp_t [1:0] axil_smc_otp_jtag_resp_filtered;

  logic is_rd_jtag_public_identity;
  logic is_prod_or_rma_sip;

  assign is_rd_jtag_public_identity = (axil_smc_otp_jtag_req_i.ar.addr inside
        {[smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR :
          (smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR + 'h1F)]});

  logic [smc_pkg::LC_STATE_WIDTH-1:0] lc_state_smc_raw;
  logic                               lc_sigint_err;

  prim_diff_decode_multi #(
    .Width(smc_pkg::LC_STATE_WIDTH)
  ) u_lc_state_smc_dec (
    .clk_i   (clk_i),
    .rst_ni  (rst_ni),
    .data_i  (lc_state_i),
    .data_o  (lc_state_smc_raw),
    .sigint_o(lc_sigint_err)
  );

  // On integrity error, restrict JTAG access (safe default)
  assign is_prod_or_rma_sip = (lc_state_smc_raw == 4'b0001) ||  // PROD
      (lc_state_smc_raw[smc_pkg::LC_STATE_WIDTH-1:1] == 3'b001);  // RMA_SIP

  axi_lite_demux #(
    .aw_chan_t  (smc_pkg::smc_axil_32_32_aw_chan_t),
    .w_chan_t   (smc_pkg::smc_axil_32_32_w_chan_t),
    .b_chan_t   (smc_pkg::smc_axil_32_32_b_chan_t),
    .ar_chan_t  (smc_pkg::smc_axil_32_32_ar_chan_t),
    .r_chan_t   (smc_pkg::smc_axil_32_32_r_chan_t),
    .axi_req_t  (smc_pkg::smc_axil_32_32_req_t),
    .axi_resp_t (smc_pkg::smc_axil_32_32_resp_t),
    .NoMstPorts (2),
    .MaxTrans   (2),
    .FallThrough(1'b1),
    .SpillAw    (1'b1),
    .SpillW     (1'b1),
    .SpillB     (1'b1),
    .SpillAr    (1'b1),
    .SpillR     (1'b1)
  ) u_axi_lite_demux_jtag_access_ctrl (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .test_i (test_en_i),

    .slv_req_i      (axil_smc_otp_jtag_req_i),
    .slv_aw_select_i(is_prod_or_rma_sip || lc_sigint_err),
    .slv_ar_select_i((is_prod_or_rma_sip && !is_rd_jtag_public_identity) || lc_sigint_err),
    .slv_resp_o     (axil_smc_otp_jtag_resp_o),

    .mst_reqs_o (axil_smc_otp_jtag_req_filtered),
    .mst_resps_i(axil_smc_otp_jtag_resp_filtered)
  );

  // Blocked path: return a slverr with a tagged data pattern.
  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH(smc_pkg::SMC_LOCAL_ADDR_WIDTH),
    .AXI_DATA_WIDTH(smc_pkg::AXI_LITE_32_DATA_WIDTH),
    .axil_req_t    (smc_pkg::smc_axil_32_32_req_t),
    .axil_resp_t   (smc_pkg::smc_axil_32_32_resp_t),
    .RESP_WIDTH    (smc_pkg::AXI_LITE_32_DATA_WIDTH),
    .RESP_DATA     (32'hbadcab1e),
    .MAX_TRANS     (2)
  ) u_prim_axi_lite_err_slv_jtag_access_ctrl (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .axil_req_i (axil_smc_otp_jtag_req_filtered[1]),
    .axil_resp_o(axil_smc_otp_jtag_resp_filtered[1])
  );

  /////////////////////////////////////////////////////////////////////////
  // eFuse Interface Controller
  /////////////////////////////////////////////////////////////////////////

  efuse_interface_controller #(
    .ADDR_WIDTH                  (smc_pkg::SMC_LOCAL_ADDR_WIDTH),
    .DATA_WIDTH                  (smc_pkg::AXI_LITE_32_DATA_WIDTH),

    .addr_t                      (smc_pkg::smc_axi_lite_32_addr_t),
    .data_t                      (smc_pkg::smc_axi_lite_32_data_t),
    .strb_t                      (smc_pkg::smc_axi_lite_32_strb_t),
    .efuse_axil_req_t            (smc_pkg::smc_axil_32_32_req_t),
    .efuse_axil_resp_t           (smc_pkg::smc_axil_32_32_resp_t),

    .efuse_axil_aw_chan_t        (smc_pkg::smc_axil_32_32_aw_chan_t),
    .efuse_axil_w_chan_t         (smc_pkg::smc_axil_32_32_w_chan_t),
    .efuse_axil_b_chan_t         (smc_pkg::smc_axil_32_32_b_chan_t),
    .efuse_axil_ar_chan_t        (smc_pkg::smc_axil_32_32_ar_chan_t),
    .efuse_axil_r_chan_t         (smc_pkg::smc_axil_32_32_r_chan_t),
    .efuse_apb_req_t             (smc_pkg::smc_efuse_apb_req_t),
    .efuse_apb_resp_t            (smc_pkg::smc_efuse_apb_resp_t),

    .efuse_addr_t                (smc_efuse_pkg::efuse_addr_bit_t),
    .efuse_data_t                (smc_efuse_pkg::efuse_data_t),
    .efuse_word_counter_t        (smc_efuse_pkg::efuse_word_counter_t),
    .fuse_command_req_t          (smc_efuse_pkg::fuse_command_req_t),
    .fuse_command_resp_t         (smc_efuse_pkg::fuse_command_resp_t),

    .SEP_SEC_DISABLE_TOKEN       ('0), // Embedded in RTL (SEP only)

    .EFUSE_MAP_REG_MAP_BASE_ADDR (32'(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR)),
    .EFUSE_MAP_REG_MAP_SIZE      (32'(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SIZE)),

    .EFUSE_MMR_REG_MAP_BASE_ADDR ('0),
    .EFUSE_MMR_REG_MAP_SIZE      ('0),

    .EFUSE_CTRL_REG_MAP_BASE_ADDR(32'(smc_top_addrmap_pkg::SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR)),
    .EFUSE_CTRL_REG_MAP_SIZE     (32'(smc_top_addrmap_pkg::SMC_TOP_EFUSE_INTERFACE_CTRL_SIZE)),

    .SHADOW_REG_BITS             (smc_efuse_pkg::SHADOW_REG_BITS),
    .EFUSE_MACRO_WORD_WIDTH      (smc_efuse_pkg::NumFuseWordWidth),

    .EFUSE_FIELDS                (smc_efuse_pkg::NUM_EFUSE_FIELDS),

    .HAS_LC_STATE                (1'b0), // SMC does not have LC state
    .CLASS1_SHADOW_RANGES        (smc_efuse_pkg::Class1ShadowRanges),
    .SECRET_SHADOW_RANGES        ('0),   // SMC has no shadow registers that should be blocked in secure_tm
    .LC_STATE_WIDTH              (smc_pkg::LC_STATE_WIDTH),
    .LC_STATE_BIT_POSITION       (0),

    .efuse_map_t                 (smc_efuse_pkg::efuse_map_t)
  ) u_efuse_interface_controller (
    .clk_i                            (clk_i),
    .rst_ni                           (rst_ni),

    .test_en_i                        (test_en_i),
    .scan_rst_ni                      (scan_rst_ni),

    // Functional AXI4-Lite
    .axil_req_i                       (axil_req_i),
    .axil_resp_o                      (axil_resp_o),

    // JTAG AXI4-Lite Post-access-control demux
    .axil_jtag_req_i                  (axil_smc_otp_jtag_req_filtered[0]),
    .axil_jtag_resp_o                 (axil_smc_otp_jtag_resp_filtered[0]),

    // SHIM CSR
    .fuse_bank_ctrl_req_o             (fuse_bank_ctrl_req_o),
    .fuse_bank_ctrl_resp_i            (fuse_bank_ctrl_resp_i),

    // SHIM custom command interface
    .fuse_command_req_o               (efuse_shim_command_req_o),
    .fuse_command_resp_i              (efuse_shim_command_resp_i),

    .secure_tm_i                      (1'b0),
    .security_disable_i               (sep_security_disable_i),
    .efuse_field_map_i                (smc_efuse_pkg::EfuseFieldMap),

    .reset_n_o                        (reset_n_o),
    .fuse_sense_done_o                (fuse_sense_done_o),
    .security_disable_o               (), // SEP only
    .shadow_regs_o                    (shadow_regs_o),

    .ext_boot_seq_done_i              (ext_boot_seq_done_i),

    .is_write_locked_shadow_regs_o    (efuse_debug_o[0]),
    .is_read_locked_shadow_regs_o     (efuse_debug_o[1]),
    .is_program_locked_o              (efuse_debug_o[2]),
    .is_read_locked_o                 (efuse_debug_o[3]),
    .is_write_setup_only_o            (efuse_debug_o[4]),
    .is_lc_state_access_o             (efuse_debug_o[5]),
    .is_read_timeout_debug_o          (efuse_debug_o[6]),
    .is_program_timeout_debug_o       (efuse_debug_o[7]),
    .is_efuse_req_err_o               (efuse_debug_o[8]),
    .is_secure_tm_blocked_o           (efuse_debug_o[9]),
    .is_rma_sip_token_match_debug     (),
    .is_rma_chiplet_token_match_debug (),

    .sec_disable_token_o              (),
    .token_match_fault_o              (),

    .locked_field_access_interrupt_o  (locked_field_access_interrupt_o)
  );

  assign lc_sigint_err_o = lc_sigint_err;

endmodule
