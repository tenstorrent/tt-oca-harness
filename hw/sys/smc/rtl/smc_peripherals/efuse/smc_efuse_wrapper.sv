// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap the vendor eFuse controller for the SMC peripheral map.
//
// Presents the eFuse register page and the eFuse shim window on the peripheral AXI-Lite
// map. Bridges fuse sense, program, shadow-register, and DFT sidebands into the SMC
// peripheral domain.
// JTAG AXI-Lite accesses go to the eFuse controller inside the eFuse register page and to
// the shim inside the EFUSE_SHIM_SIZE bytes at the base of smc_external; they are muxed
// with the functional shim port onto fuse_bank_ctrl_req_o. Every other JTAG access
// receives DECERR with data 0xBADCAB1E, as does every JTAG access when the SEP lifecycle
// state is PROD or RMA_SiP or fails its integrity check, except reads of
// JTAG_PUBLIC_IDENTITY outside an integrity error.

`include "ocah_assert.svh"

module smc_efuse_wrapper #(
  parameter int unsigned EFUSE_SHIM_SIZE = 'h4  // Vendor eFuse shim CSR block at the base of
                                                // the smc_external window, in bytes.
) (
  input  logic                                       clk_i,  // SMC core clock for the
                                                             // eFuse controller and JTAG
                                                             // access filter.
  input  logic                                       rst_ni,  // Primary reset, active-low,
                                                              // synchronized to clk_i.
  input  logic                                       test_en_i,  // DFT test-mode enable,
                                                                 // active-high.
  input  logic                                       scan_rst_ni,  // DFT scan reset,
                                                                   // active-low, used while
                                                                   // test_en_i is high.

  input  smc_pkg::smc_axil_32_32_req_t               axil_req_i,  // Functional AXI4-Lite
                                                                  // slave (from SMC
                                                                  // peripherals xbar)
                                                                  // request.
  output smc_pkg::smc_axil_32_32_resp_t              axil_resp_o,  // Functional AXI4-Lite
                                                                   // slave (from SMC
                                                                   // peripherals xbar)
                                                                   // response.

  input  smc_pkg::smc_axil_32_32_req_t               axil_efuse_shim_req_i,  // Functional eFuse
                                                                             // shim AXI4-Lite
                                                                             // slave request.
  output smc_pkg::smc_axil_32_32_resp_t              axil_efuse_shim_resp_o,  // Functional eFuse
                                                                              // shim AXI4-Lite
                                                                              // slave response.

  input  smc_pkg::smc_axil_32_32_req_t               axil_smc_otp_jtag_req_i,  // JTAG AXI4-Lite slave
                                                                               // request.
  output smc_pkg::smc_axil_32_32_resp_t              axil_smc_otp_jtag_resp_o,  // JTAG AXI4-Lite slave
                                                                                // response.

  input  logic [2*smc_pkg::LcStateWidth-1:0]       lc_state_i,    // LC state from SEP
                                                                  // (differentially
                                                                  // encoded); PROD and
                                                                  // RMA_SiP restrict JTAG
                                                                  // access.
  output logic                                       lc_sigint_err_o,  // Integrity error from
                                                                       // the differential
                                                                       // decode of lc_state_i,
                                                                       // active-high; also
                                                                       // blocks JTAG access.

  output smc_pkg::smc_axil_32_32_req_t               fuse_bank_ctrl_req_o,  // eFuse SHIM CSR
                                                                            // AXI4-Lite request.
  input  smc_pkg::smc_axil_32_32_resp_t              fuse_bank_ctrl_resp_i,  // eFuse SHIM CSR
                                                                             // AXI4-Lite response.

  output smc_efuse_pkg::fuse_command_req_t           efuse_shim_command_req_o,  // Fuse sense and program
                                                                                // command request to the
                                                                                // SHIM state machine.
  input  smc_efuse_pkg::fuse_command_resp_t          efuse_shim_command_resp_i,  // Fuse command response
                                                                                 // from the SHIM state
                                                                                 // machine.

  input  logic                                       sep_security_disable_i,  // Security disable
                                                                              // from the SEP eFuse
                                                                              // controller,
                                                                              // active-high; skips
                                                                              // automatic fuse
                                                                              // sensing and releases
                                                                              // the shadow registers
                                                                              // without it.

  input  logic                                       ext_boot_seq_done_i,  // External boot
                                                                           // sequence done (gate
                                                                           // the released reset).

  output logic                                       reset_n_o,  // Active-low reset released
                                                                 // through a synchronizer
                                                                 // once fuse sensing and
                                                                 // ext_boot_seq_done_i are
                                                                 // both done.
  output logic                                       fuse_sense_done_o,  // High once
                                                                         // shadow-register loading
                                                                         // from the fuses
                                                                         // completes.

  output smc_efuse_pkg::efuse_map_t                  shadow_regs_o,  // Shadow-register contents;
                                                                     // zero until fuse sensing
                                                                     // completes unless
                                                                     // sep_security_disable_i is
                                                                     // set.

  output logic [9:0]                                 efuse_debug_o,  // eFuse controller status,
                                                                     // from bit 0: shadow-register
                                                                     // write and read locks,
                                                                     // program and read locks,
                                                                     // write-setup-only, LC-state
                                                                     // access, read and program
                                                                     // timeouts, request error and
                                                                     // secure-test-mode block.

  output logic                                       locked_field_access_interrupt_o  // High during an access
                                                                                      // to the eFuse map
                                                                                      // window that a field
                                                                                      // lock blocks.
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

  typedef enum logic [1:0] {
    JTAG_TARGET_REGS  = 2'd0,
    JTAG_TARGET_ERROR = 2'd1,
    JTAG_TARGET_SHIM  = 2'd2
  } jtag_target_e;

  localparam smc_pkg::smc_axi_lite_32_addr_t EfusePageBase =
      smc_pkg::smc_axi_lite_32_addr_t'(smc_top_addrmap_pkg::SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR);
  localparam smc_pkg::smc_axi_lite_32_addr_t EfusePageLast =
      EfusePageBase + smc_pkg::smc_axi_lite_32_addr_t'(smc_pkg::RegPageSize - 1);
  localparam smc_pkg::smc_axi_lite_32_addr_t EfuseShimBase =
      smc_pkg::smc_axi_lite_32_addr_t'(smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_BASE_ADDR);
  localparam smc_pkg::smc_axi_lite_32_addr_t EfuseShimLast =
      smc_pkg::smc_axi_lite_32_addr_t'(EfuseShimBase + EFUSE_SHIM_SIZE - 1);

  `OCAH_ASSERT_STATIC(EfusePageAligned_A,
                      EfusePageBase % smc_pkg::smc_axi_lite_32_addr_t'(smc_pkg::RegPageSize) == 0)

  function automatic jtag_target_e jtag_target(smc_pkg::smc_axi_lite_32_addr_t addr, logic blocked);
    if (blocked) return JTAG_TARGET_ERROR;
    if (addr inside {[EfusePageBase : EfusePageLast]}) return JTAG_TARGET_REGS;
    if (addr inside {[EfuseShimBase : EfuseShimLast]}) return JTAG_TARGET_SHIM;
    return JTAG_TARGET_ERROR;
  endfunction

  smc_pkg::smc_axil_32_32_req_t  [2:0] axil_smc_otp_jtag_req_filtered;
  smc_pkg::smc_axil_32_32_resp_t [2:0] axil_smc_otp_jtag_resp_filtered;

  logic is_rd_jtag_public_identity;
  logic is_prod_or_rma_sip;
  jtag_target_e jtag_aw_target;
  jtag_target_e jtag_ar_target;

  assign is_rd_jtag_public_identity = (axil_smc_otp_jtag_req_i.ar.addr inside
        {[smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR :
          (smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR + 'h1F)]});

  logic [smc_pkg::LcStateWidth-1:0]   lc_state_smc_raw;
  logic                               lc_sigint_err;

  prim_diff_decode_multi #(
    .WIDTH(smc_pkg::LcStateWidth)
  ) u_lc_state_smc_dec (
    .clk_i   (clk_i),
    .rst_ni  (rst_ni),
    .data_i  (lc_state_i),
    .data_o  (lc_state_smc_raw),
    .sigint_o(lc_sigint_err)
  );

  // On integrity error, restrict JTAG access (safe default)
  assign is_prod_or_rma_sip = (lc_state_smc_raw == 4'b0001) ||  // PROD
      (lc_state_smc_raw[smc_pkg::LcStateWidth-1:1] == 3'b001);  // RMA_SIP

  assign jtag_aw_target = jtag_target(axil_smc_otp_jtag_req_i.aw.addr,
                                      is_prod_or_rma_sip || lc_sigint_err);
  assign jtag_ar_target = jtag_target(axil_smc_otp_jtag_req_i.ar.addr,
      (is_prod_or_rma_sip && !is_rd_jtag_public_identity) || lc_sigint_err);

  axi_lite_demux #(
    .aw_chan_t  (smc_pkg::smc_axil_32_32_aw_chan_t),
    .w_chan_t   (smc_pkg::smc_axil_32_32_w_chan_t),
    .b_chan_t   (smc_pkg::smc_axil_32_32_b_chan_t),
    .ar_chan_t  (smc_pkg::smc_axil_32_32_ar_chan_t),
    .r_chan_t   (smc_pkg::smc_axil_32_32_r_chan_t),
    .axi_req_t  (smc_pkg::smc_axil_32_32_req_t),
    .axi_resp_t (smc_pkg::smc_axil_32_32_resp_t),
    .NoMstPorts (3),
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
    .slv_aw_select_i(jtag_aw_target),
    .slv_ar_select_i(jtag_ar_target),
    .slv_resp_o     (axil_smc_otp_jtag_resp_o),

    .mst_reqs_o (axil_smc_otp_jtag_req_filtered),
    .mst_resps_i(axil_smc_otp_jtag_resp_filtered)
  );

  // Blocked or unmapped path: return a DECERR with a tagged data pattern.
  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH(smc_pkg::SmcLocalAddrWidth),
    .AXI_DATA_WIDTH(smc_pkg::AxiLite32DataWidth),
    .axil_req_t    (smc_pkg::smc_axil_32_32_req_t),
    .axil_resp_t   (smc_pkg::smc_axil_32_32_resp_t),
    .RESP_WIDTH    (smc_pkg::AxiLite32DataWidth),
    .RESP_DATA     (32'hbadcab1e),
    .MAX_TRANS     (2)
  ) u_prim_axi_lite_err_slv_jtag_access_ctrl (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_en_i  (test_en_i),
    .axil_req_i (axil_smc_otp_jtag_req_filtered[JTAG_TARGET_ERROR]),
    .axil_resp_o(axil_smc_otp_jtag_resp_filtered[JTAG_TARGET_ERROR])
  );

  // Slave port 0 = functional shim port, slave port 1 = JTAG.
  axi_lite_mux #(
    .aw_chan_t  (smc_pkg::smc_axil_32_32_aw_chan_t),
    .w_chan_t   (smc_pkg::smc_axil_32_32_w_chan_t),
    .b_chan_t   (smc_pkg::smc_axil_32_32_b_chan_t),
    .ar_chan_t  (smc_pkg::smc_axil_32_32_ar_chan_t),
    .r_chan_t   (smc_pkg::smc_axil_32_32_r_chan_t),
    .axi_req_t  (smc_pkg::smc_axil_32_32_req_t),
    .axi_resp_t (smc_pkg::smc_axil_32_32_resp_t),
    .NoSlvPorts (2),
    .MaxTrans   (2),
    .FallThrough(1'b0),
    .SpillAw    (1'b1),
    .SpillW     (1'b1),
    .SpillB     (1'b1),
    .SpillAr    (1'b1),
    .SpillR     (1'b1)
  ) u_efuse_shim_axi_lite_mux (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_reqs_i ({axil_smc_otp_jtag_req_filtered[JTAG_TARGET_SHIM], axil_efuse_shim_req_i}),
    .slv_resps_o({axil_smc_otp_jtag_resp_filtered[JTAG_TARGET_SHIM], axil_efuse_shim_resp_o}),
    .mst_req_o  (fuse_bank_ctrl_req_o),
    .mst_resp_i (fuse_bank_ctrl_resp_i)
  );

  /////////////////////////////////////////////////////////////////////////
  // eFuse Interface Controller
  /////////////////////////////////////////////////////////////////////////

  efuse_interface_controller #(
    .ADDR_WIDTH                  (smc_pkg::SmcLocalAddrWidth),
    .DATA_WIDTH                  (smc_pkg::AxiLite32DataWidth),

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

    .SHADOW_REG_BITS             (smc_efuse_pkg::ShadowRegBits),
    .EFUSE_MACRO_WORD_WIDTH      (smc_efuse_pkg::NumFuseWordWidth),

    .EFUSE_FIELDS                (smc_efuse_pkg::NumEfuseFields),

    .HAS_LC_STATE                (1'b0), // SMC does not have LC state
    .CLASS1_SHADOW_RANGES        (smc_efuse_pkg::Class1ShadowRanges),
    .SECRET_SHADOW_RANGES        ('0),   // SMC has no shadow registers that should be blocked in secure_tm
    .LC_STATE_BIT_POSITION       (0),

    .efuse_map_t                 (smc_efuse_pkg::efuse_map_t)
  ) u_efuse_interface_controller (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),

    .test_en_i                          (test_en_i),
    .scan_rst_ni                        (scan_rst_ni),

    // Functional AXI4-Lite
    .axil_req_i                         (axil_req_i),
    .axil_resp_o                        (axil_resp_o),

    // JTAG AXI4-Lite Post-access-control demux
    .axil_jtag_req_i                    (axil_smc_otp_jtag_req_filtered[JTAG_TARGET_REGS]),
    .axil_jtag_resp_o                   (axil_smc_otp_jtag_resp_filtered[JTAG_TARGET_REGS]),

    // SHIM custom command interface
    .fuse_command_req_o                 (efuse_shim_command_req_o),
    .fuse_command_resp_i                (efuse_shim_command_resp_i),

    .secure_tm_i                        (1'b0),
    .security_disable_i                 (sep_security_disable_i),
    .efuse_field_map_i                  (smc_efuse_pkg::EfuseFieldMap),

    .reset_n_o                          (reset_n_o),
    .fuse_sense_done_o                  (fuse_sense_done_o),
    .security_disable_o                 (), // SEP only
    .shadow_regs_o                      (shadow_regs_o),

    .ext_boot_seq_done_i                (ext_boot_seq_done_i),

    .is_write_locked_shadow_regs_o      (efuse_debug_o[0]),
    .is_read_locked_shadow_regs_o       (efuse_debug_o[1]),
    .is_program_locked_o                (efuse_debug_o[2]),
    .is_read_locked_o                   (efuse_debug_o[3]),
    .is_write_setup_only_o              (efuse_debug_o[4]),
    .is_lc_state_access_o               (efuse_debug_o[5]),
    .is_read_timeout_debug_o            (efuse_debug_o[6]),
    .is_program_timeout_debug_o         (efuse_debug_o[7]),
    .is_efuse_req_err_o                 (efuse_debug_o[8]),
    .is_secure_tm_blocked_o             (efuse_debug_o[9]),
    .is_rma_sip_token_match_debug_o     (),
    .is_rma_chiplet_token_match_debug_o (),

    .token_match_fault_o                (),

    .locked_field_access_interrupt_o    (locked_field_access_interrupt_o)
  );

  assign lc_sigint_err_o = lc_sigint_err;

endmodule
