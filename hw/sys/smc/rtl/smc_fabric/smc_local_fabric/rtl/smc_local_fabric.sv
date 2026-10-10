// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route SMC-window AXI traffic from the input fabric to the local SMC targets.
//
// Rebases system, SEP and local-port requests onto local_base_addr_i, then steers them
// through smc_local_xbar to the CPU front port, the data accelerator control port, the DFD
// APB port and the peripheral AXI-Lite port, and through smc_internal_axi_lite_xbar to the
// internal CSR blocks. CPU MMIO, JTAG, log and data accelerator traffic arrives on the local
// port.

`include "ocah_assert.svh"

module smc_local_fabric (
  input logic                                         clk_i,  // SMC core clock.
  input logic                                         rst_ni,  // Primary reset, active-low,
                                                               // synchronized to the SMC core
                                                               // clock.
  input logic                                         test_en_i,  // Scan test mode enable,
                                                                  // forwarded to the test inputs of
                                                                  // both crossbars.

  input smc_pkg::smc_axi_addr_t                       local_base_addr_i,  // Local base address of the SMC address
                                                                          // window; its bits above region_size_i
                                                                          // replace the upper address bits of every
                                                                          // incoming request.
  input logic [31:0]                                  region_size_i,  // Size in bytes of the SMC address window, a
                                                                      // power of two by software contract; selects
                                                                      // the low address bits that pass through
                                                                      // unchanged.

  input  smc_pkg::smc_local_32_64_6_12_axi_req_t      input_axi_req_i,  // System AXI request from the input fabric, after the
                                                                        // system inbound filter and the SMC-window check;
                                                                        // this module rebases its address onto local_base_addr_i.
  output smc_pkg::smc_local_32_64_6_12_axi_resp_t     input_axi_rsp_o,  // System AXI response to the input fabric.
  input  smc_pkg::smc_local_32_64_6_12_axi_req_t      sep_in_axi_req_i,  // SEP AXI request from the input fabric, after the
                                                                         // SMC-window check and truncation to the 32-bit local
                                                                         // address; this module rebases its address onto
                                                                         // local_base_addr_i.
  output smc_pkg::smc_local_32_64_6_12_axi_resp_t     sep_in_axi_rsp_o,  // SEP AXI response to the input fabric.
  input  smc_pkg::smc_local_32_64_6_12_axi_req_t      local_axi_req_i,  // Local AXI request from the input fabric's local output
                                                                        // port, carrying CPU MMIO, JTAG, log and data accelerator
                                                                        // accesses that hit the SMC window; this module rebases
                                                                        // its address onto local_base_addr_i.
  output smc_pkg::smc_local_32_64_6_12_axi_resp_t     local_axi_rsp_o,  // Local AXI response to the input fabric's local port.

  output smc_pkg::smc_local_32_64_8_12_axi_req_t      axi_front_port_req_o,  // AXI request from the local crossbar into the
                                                                             // CPU cluster's front port, smc_cpu_wrapper's
                                                                             // front port in smc.
  input  smc_pkg::smc_local_32_64_8_12_axi_resp_t     axi_front_port_rsp_i,  // AXI response from the CPU cluster's front port.
  output smc_pkg::smc_local_32_64_8_12_axi_req_t      axi_data_accel_ctrl_req_o,  // AXI request to the data accelerator's control port
                                                                                  // for its DMA and zeroer control windows.
  input  smc_pkg::smc_local_32_64_8_12_axi_resp_t     axi_data_accel_ctrl_rsp_i,  // AXI response from the data accelerator's control port.

  output smc_local_xbar_pkg::axi_lite32_req_t         periph_reg_req_o,  // 32-bit AXI-Lite request from the local crossbar
                                                                         // to the peripheral CSR crossbar.
  input  smc_local_xbar_pkg::axi_lite32_resp_t        periph_reg_resp_i,  // 32-bit AXI-Lite response from the peripheral
                                                                          // CSR crossbar.

  output smc_pkg::smc_axil_32_64_req_t                axil_aR_ctrl_req_o,  // 64-bit AXI-Lite request for the alias remap
                                                                           // control registers.
  input  smc_pkg::smc_axil_32_64_resp_t               axil_aR_ctrl_resp_i,  // 64-bit AXI-Lite response from the alias remap
                                                                            // control registers.
  output smc_pkg::smc_axil_32_64_req_t                axil_mR_ctrl_req_o,  // 64-bit AXI-Lite request for the M-mode output
                                                                           // remap control registers.
  input  smc_pkg::smc_axil_32_64_resp_t               axil_mR_ctrl_resp_i,  // 64-bit AXI-Lite response from the M-mode output
                                                                            // remap control registers.
  output smc_pkg::smc_axil_32_64_req_t                axil_xR_ctrl_req_o,  // 64-bit AXI-Lite request for the Xvisor output
                                                                           // remap control registers.
  input  smc_pkg::smc_axil_32_64_resp_t               axil_xR_ctrl_resp_i,  // 64-bit AXI-Lite response from the Xvisor output
                                                                            // remap control registers.
  output smc_pkg::smc_axil_32_64_req_t                axil_inbound_filter_ctrl_req_o,  // 64-bit AXI-Lite request for the inbound
                                                                                       // filter control registers.
  input  smc_pkg::smc_axil_32_64_resp_t               axil_inbound_filter_ctrl_resp_i,  // 64-bit AXI-Lite response from the inbound
                                                                                        // filter control registers.
  output smc_pkg::smc_axil_32_64_req_t                axil_outbound_filter_ctrl_req_o,  // 64-bit AXI-Lite request for the outbound
                                                                                        // filter control registers.
  input  smc_pkg::smc_axil_32_64_resp_t               axil_outbound_filter_ctrl_resp_i,  // 64-bit AXI-Lite response from the
                                                                                         // outbound filter control registers.
  output smc_pkg::smc_axil_32_64_req_t                axil_mailbox_req_o,  // 64-bit AXI-Lite request for the SMC mailbox
                                                                           // window.
  input  smc_pkg::smc_axil_32_64_resp_t               axil_mailbox_resp_i,  // 64-bit AXI-Lite response from the SMC mailbox.
  output smc_pkg::smc_axil_32_64_req_t                axil_smc_base_config_req_o,  // 64-bit AXI-Lite request for the SMC base
                                                                                   // configuration registers.
  input  smc_pkg::smc_axil_32_64_resp_t               axil_smc_base_config_resp_i,  // 64-bit AXI-Lite response from the SMC base
                                                                                    // configuration registers.
  output smc_pkg::smc_axil_32_64_req_t                axil_dfx_csr_req_o,  // 64-bit AXI-Lite request for the DFX control
                                                                           // register window.
  input  smc_pkg::smc_axil_32_64_resp_t               axil_dfx_csr_resp_i,  // 64-bit AXI-Lite response from the DFX control
                                                                            // registers.

  output smc_pkg::smc_dfd_apb_req_t                   apb_smc_dfd_reg_req_o,  // APB request from the local crossbar for the
                                                                              // SMC CLA (DFD) register window.
  input  smc_pkg::smc_dfd_apb_resp_t                  apb_smc_dfd_reg_resp_i  // APB response from the SMC CLA (DFD)
                                                                              // registers.
);

  // ===========================================================================
  // Intermediate Signals for Downstream Crossbars
  // ===========================================================================
  smc_local_xbar_pkg::axi_lite64_req_t   local_reg_req;
  smc_local_xbar_pkg::axi_lite64_resp_t  local_reg_resp;

  // Address-modified input requests for local_base_addr masking
  smc_local_xbar_pkg::axi64_req_t system_req_masked;
  smc_local_xbar_pkg::axi64_req_t sep_in_req_masked;
  smc_local_xbar_pkg::axi64_req_t local_req_masked;

  // Offset bits covered by the region size come from the incoming address, the rest
  // from local_base_addr_i, so an access arriving on a global base lands on the same
  // offset inside the local aperture. region_size_i is a power of two by SW contract
  // (see the RDL), which is what makes the subtract below a contiguous low-bit mask.
  logic [31:0] local_addr_mask;
  logic [31:0] local_addr_base;

  assign local_addr_mask = region_size_i - 32'd1;
  assign local_addr_base = local_base_addr_i[31:0] & ~local_addr_mask;

  // Apply address masking to input ports
  always_comb begin
    system_req_masked = input_axi_req_i;
    system_req_masked.aw.addr = local_addr_base | (input_axi_req_i.aw.addr & local_addr_mask);
    system_req_masked.ar.addr = local_addr_base | (input_axi_req_i.ar.addr & local_addr_mask);

    sep_in_req_masked = sep_in_axi_req_i;
    sep_in_req_masked.aw.addr = local_addr_base | (sep_in_axi_req_i.aw.addr & local_addr_mask);
    sep_in_req_masked.ar.addr = local_addr_base | (sep_in_axi_req_i.ar.addr & local_addr_mask);

    local_req_masked = local_axi_req_i;
    local_req_masked.aw.addr = local_addr_base | (local_axi_req_i.aw.addr & local_addr_mask);
    local_req_masked.ar.addr = local_addr_base | (local_axi_req_i.ar.addr & local_addr_mask);
  end

  //------------------------//
  // SMC LOCAL AXI CROSSBAR //
  //------------------------//

  smc_local_xbar u_smc_local_xbar (
    .clk_i                    (clk_i),
    .rst_ni                   (rst_ni),
    .test_i                   (test_en_i),

    // Input ports
    .system_req_i             (system_req_masked),
    .system_resp_o            (input_axi_rsp_o),
    .sep_in_req_i             (sep_in_req_masked),
    .sep_in_resp_o            (sep_in_axi_rsp_o),
    .local_in_req_i           (local_req_masked),
    .local_in_resp_o          (local_axi_rsp_o),

    // Output ports
    .front_port_req_o         (axi_front_port_req_o),
    .front_port_resp_i        (axi_front_port_rsp_i),
    .data_accel_ctrl_req_o    (axi_data_accel_ctrl_req_o),
    .data_accel_ctrl_resp_i   (axi_data_accel_ctrl_rsp_i),
    .local_reg_req_o          (local_reg_req),
    .local_reg_resp_i         (local_reg_resp),
    .periph_reg_req_o         (periph_reg_req_o),
    .periph_reg_resp_i        (periph_reg_resp_i),
    .smc_dfd_reg_req_o        (apb_smc_dfd_reg_req_o),
    .smc_dfd_reg_resp_i       (apb_smc_dfd_reg_resp_i)
  );

  //------------------------------------//
  // SMC INTERNAL REG AXI LITE CROSSBAR //
  //------------------------------------//

  smc_internal_axi_lite_xbar u_smc_internal_axi_lite_xbar (
    .clk_i                            (clk_i),
    .rst_ni                           (rst_ni),
    .test_i                           (test_en_i),

    // Input from smc_local_xbar
    .local_in_req_i                   (local_reg_req),
    .local_in_resp_o                  (local_reg_resp),

    // Output ports
    .smc_base_config_req_o            (axil_smc_base_config_req_o),
    .smc_base_config_resp_i           (axil_smc_base_config_resp_i),
    .aR_ctrl_req_o                    (axil_aR_ctrl_req_o),
    .aR_ctrl_resp_i                   (axil_aR_ctrl_resp_i),
    .mR_ctrl_req_o                    (axil_mR_ctrl_req_o),
    .mR_ctrl_resp_i                   (axil_mR_ctrl_resp_i),
    .xR_ctrl_req_o                    (axil_xR_ctrl_req_o),
    .xR_ctrl_resp_i                   (axil_xR_ctrl_resp_i),
    .inbound_filter_ctrl_req_o        (axil_inbound_filter_ctrl_req_o),
    .inbound_filter_ctrl_resp_i       (axil_inbound_filter_ctrl_resp_i),
    .outbound_filter_ctrl_req_o       (axil_outbound_filter_ctrl_req_o),
    .outbound_filter_ctrl_resp_i      (axil_outbound_filter_ctrl_resp_i),
    .mailbox_req_o                    (axil_mailbox_req_o),
    .mailbox_resp_i                   (axil_mailbox_resp_i),
    .dfx_csr_req_o                    (axil_dfx_csr_req_o),
    .dfx_csr_resp_i                   (axil_dfx_csr_resp_i)
  );

  // ===========================================================================
  // Type Width Assertions
  // Verify smc_pkg types match crossbar package types
  // ===========================================================================

  // AXI64 input types (6-bit ID, 32-bit addr, 64-bit data, 12-bit user)
  // input_axi (system)
  `OCAH_ASSERT_STATIC(InputAxiAwIdWidth_A, $bits(input_axi_req_i.aw.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "INPUT_AXI AW ID width mismatch")
  `OCAH_ASSERT_STATIC(InputAxiAwAddrWidth_A, $bits(input_axi_req_i.aw.addr) == $bits
                      (smc_local_xbar_pkg::axi64_addr_t), "INPUT_AXI AW ADDR width mismatch")
  `OCAH_ASSERT_STATIC(InputAxiWDataWidth_A, $bits(input_axi_req_i.w.data) == $bits
                      (smc_local_xbar_pkg::axi64_data_t), "INPUT_AXI W DATA width mismatch")
  `OCAH_ASSERT_STATIC(InputAxiArIdWidth_A, $bits(input_axi_req_i.ar.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "INPUT_AXI AR ID width mismatch")
  `OCAH_ASSERT_STATIC(InputAxiRIdWidth_A, $bits(input_axi_rsp_o.r.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "INPUT_AXI R ID width mismatch")
  `OCAH_ASSERT_STATIC(InputAxiBIdWidth_A, $bits(input_axi_rsp_o.b.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "INPUT_AXI B ID width mismatch")

  // sep_in_axi
  `OCAH_ASSERT_STATIC(SepInAxiAwIdWidth_A, $bits(sep_in_axi_req_i.aw.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "SEP_IN_AXI AW ID width mismatch")
  `OCAH_ASSERT_STATIC(SepInAxiAwAddrWidth_A, $bits(sep_in_axi_req_i.aw.addr) == $bits
                      (smc_local_xbar_pkg::axi64_addr_t), "SEP_IN_AXI AW ADDR width mismatch")
  `OCAH_ASSERT_STATIC(SepInAxiWDataWidth_A, $bits(sep_in_axi_req_i.w.data) == $bits
                      (smc_local_xbar_pkg::axi64_data_t), "SEP_IN_AXI W DATA width mismatch")
  `OCAH_ASSERT_STATIC(SepInAxiArIdWidth_A, $bits(sep_in_axi_req_i.ar.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "SEP_IN_AXI AR ID width mismatch")
  `OCAH_ASSERT_STATIC(SepInAxiRIdWidth_A, $bits(sep_in_axi_rsp_o.r.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "SEP_IN_AXI R ID width mismatch")
  `OCAH_ASSERT_STATIC(SepInAxiBIdWidth_A, $bits(sep_in_axi_rsp_o.b.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "SEP_IN_AXI B ID width mismatch")

  // local_axi
  `OCAH_ASSERT_STATIC(LocalAxiAwIdWidth_A, $bits(local_axi_req_i.aw.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "LOCAL_AXI AW ID width mismatch")
  `OCAH_ASSERT_STATIC(LocalAxiAwAddrWidth_A, $bits(local_axi_req_i.aw.addr) == $bits
                      (smc_local_xbar_pkg::axi64_addr_t), "LOCAL_AXI AW ADDR width mismatch")
  `OCAH_ASSERT_STATIC(LocalAxiWDataWidth_A, $bits(local_axi_req_i.w.data) == $bits
                      (smc_local_xbar_pkg::axi64_data_t), "LOCAL_AXI W DATA width mismatch")
  `OCAH_ASSERT_STATIC(LocalAxiArIdWidth_A, $bits(local_axi_req_i.ar.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "LOCAL_AXI AR ID width mismatch")
  `OCAH_ASSERT_STATIC(LocalAxiRIdWidth_A, $bits(local_axi_rsp_o.r.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "LOCAL_AXI R ID width mismatch")
  `OCAH_ASSERT_STATIC(LocalAxiBIdWidth_A, $bits(local_axi_rsp_o.b.id) == $bits
                      (smc_local_xbar_pkg::axi64_id_t), "LOCAL_AXI B ID width mismatch")

  // AXI64 output types (8-bit ID, 32-bit addr, 64-bit data, 12-bit user)
  // front_port
  `OCAH_ASSERT_STATIC(FrontPortAwIdWidth_A, $bits(axi_front_port_req_o.aw.id) == $bits
                      (smc_local_xbar_pkg::axi_out_id_t), "FRONT_PORT AW ID width mismatch")
  `OCAH_ASSERT_STATIC(FrontPortAwAddrWidth_A, $bits(axi_front_port_req_o.aw.addr) == $bits
                      (smc_local_xbar_pkg::axi_out_addr_t), "FRONT_PORT AW ADDR width mismatch")
  `OCAH_ASSERT_STATIC(FrontPortWDataWidth_A, $bits(axi_front_port_req_o.w.data) == $bits
                      (smc_local_xbar_pkg::axi_out_data_t), "FRONT_PORT W DATA width mismatch")
  `OCAH_ASSERT_STATIC(FrontPortArIdWidth_A, $bits(axi_front_port_req_o.ar.id) == $bits
                      (smc_local_xbar_pkg::axi_out_id_t), "FRONT_PORT AR ID width mismatch")
  `OCAH_ASSERT_STATIC(FrontPortRIdWidth_A, $bits(axi_front_port_rsp_i.r.id) == $bits
                      (smc_local_xbar_pkg::axi_out_id_t), "FRONT_PORT R ID width mismatch")
  `OCAH_ASSERT_STATIC(FrontPortBIdWidth_A, $bits(axi_front_port_rsp_i.b.id) == $bits
                      (smc_local_xbar_pkg::axi_out_id_t), "FRONT_PORT B ID width mismatch")

  // data_accel_ctrl
  `OCAH_ASSERT_STATIC(DataAccelCtrlAwIdWidth_A, $bits(axi_data_accel_ctrl_req_o.aw.id) == $bits
                      (smc_local_xbar_pkg::axi_out_id_t), "DATA_ACCEL_CTRL AW ID width mismatch")
  `OCAH_ASSERT_STATIC(DataAccelCtrlAwAddrWidth_A, $bits(axi_data_accel_ctrl_req_o.aw.addr) == $bits
                      (smc_local_xbar_pkg::axi_out_addr_t),
                      "DATA_ACCEL_CTRL AW ADDR width mismatch")
  `OCAH_ASSERT_STATIC(DataAccelCtrlWDataWidth_A, $bits(axi_data_accel_ctrl_req_o.w.data) == $bits
                      (smc_local_xbar_pkg::axi_out_data_t), "DATA_ACCEL_CTRL W DATA width mismatch")
  `OCAH_ASSERT_STATIC(DataAccelCtrlArIdWidth_A, $bits(axi_data_accel_ctrl_req_o.ar.id) == $bits
                      (smc_local_xbar_pkg::axi_out_id_t), "DATA_ACCEL_CTRL AR ID width mismatch")
  `OCAH_ASSERT_STATIC(DataAccelCtrlRIdWidth_A, $bits(axi_data_accel_ctrl_rsp_i.r.id) == $bits
                      (smc_local_xbar_pkg::axi_out_id_t), "DATA_ACCEL_CTRL R ID width mismatch")
  `OCAH_ASSERT_STATIC(DataAccelCtrlBIdWidth_A, $bits(axi_data_accel_ctrl_rsp_i.b.id) == $bits
                      (smc_local_xbar_pkg::axi_out_id_t), "DATA_ACCEL_CTRL B ID width mismatch")

  // APB32 types
  // smc_dfd_reg
  `OCAH_ASSERT_STATIC(ApbSmcDfdRegPaddrWidth_A, $bits(apb_smc_dfd_reg_req_o.paddr) == $bits
                      (smc_local_xbar_pkg::apb32_addr_t), "APB_SMC_DFD_REG PADDR width mismatch")
  `OCAH_ASSERT_STATIC(ApbSmcDfdRegPwdataWidth_A, $bits(apb_smc_dfd_reg_req_o.pwdata) == $bits
                      (smc_local_xbar_pkg::apb32_data_t), "APB_SMC_DFD_REG PWDATA width mismatch")
  `OCAH_ASSERT_STATIC(ApbSmcDfdRegPrdataWidth_A, $bits(apb_smc_dfd_reg_resp_i.prdata) == $bits
                      (smc_local_xbar_pkg::apb32_data_t), "APB_SMC_DFD_REG PRDATA width mismatch")

endmodule
