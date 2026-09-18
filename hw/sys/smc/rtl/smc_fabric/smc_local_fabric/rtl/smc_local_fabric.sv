// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// System Management Controller Input Fabric

module smc_local_fabric (
  input logic                                         clk_i,
  input logic                                         rst_ni,
  input logic                                         test_en_i,

  input smc_pkg::smc_axi_addr_t                       local_base_addr_i,
  input logic [31:0]                                  region_size_i,

  // Input AXI
  input  smc_pkg::smc_local_32_64_6_12_axi_req_t      input_axi_req_i,
  output smc_pkg::smc_local_32_64_6_12_axi_resp_t     input_axi_rsp_o,
  input  smc_pkg::smc_local_32_64_6_12_axi_req_t      sep_in_axi_req_i,
  output smc_pkg::smc_local_32_64_6_12_axi_resp_t     sep_in_axi_rsp_o,
  input  smc_pkg::smc_local_32_64_6_12_axi_req_t      local_axi_req_i,
  output smc_pkg::smc_local_32_64_6_12_axi_resp_t     local_axi_rsp_o,

  // Output AXI
  output smc_pkg::smc_local_32_64_8_12_axi_req_t      axi_front_port_req_o,
  input  smc_pkg::smc_local_32_64_8_12_axi_resp_t     axi_front_port_rsp_i,
  output smc_pkg::smc_local_32_64_8_12_axi_req_t      axi_data_accel_ctrl_req_o,
  input  smc_pkg::smc_local_32_64_8_12_axi_resp_t     axi_data_accel_ctrl_rsp_i,

  // Peripheral AXI-Lite (32-bit)
  output smc_local_xbar_pkg::axi_lite32_req_t         periph_reg_req_o,
  input  smc_local_xbar_pkg::axi_lite32_resp_t        periph_reg_resp_i,

  // Internal AXI-Lite (64-bit)
  output smc_pkg::smc_axil_32_64_req_t                axil_aR_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t               axil_aR_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t                axil_mR_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t               axil_mR_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t                axil_xR_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t               axil_xR_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t                axil_inbound_filter_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t               axil_inbound_filter_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t                axil_outbound_filter_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t               axil_outbound_filter_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t                axil_mailbox_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t               axil_mailbox_resp_i,
  output smc_pkg::smc_axil_32_64_req_t                axil_smc_base_config_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t               axil_smc_base_config_resp_i,
  output smc_pkg::smc_axil_32_64_req_t                axil_dfx_csr_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t               axil_dfx_csr_resp_i,

  // DFD APB
  output smc_pkg::smc_dfd_apb_req_t                   apb_smc_dfd_reg_req_o,
  input  smc_pkg::smc_dfd_apb_resp_t                  apb_smc_dfd_reg_resp_i
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

`ifndef SYNTHESIS  // elaboration-time width checks; excluded from synthesis
  // AXI64 input types (6-bit ID, 32-bit addr, 64-bit data, 12-bit user)
  initial begin : gen_axi64_input_type_assertions
    // input_axi (system)
    assert ($bits(input_axi_req_i.aw.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "INPUT_AXI AW ID width mismatch");
    assert ($bits(input_axi_req_i.aw.addr) == $bits(smc_local_xbar_pkg::axi64_addr_t))
    else $fatal(1, "INPUT_AXI AW ADDR width mismatch");
    assert ($bits(input_axi_req_i.w.data) == $bits(smc_local_xbar_pkg::axi64_data_t))
    else $fatal(1, "INPUT_AXI W DATA width mismatch");
    assert ($bits(input_axi_req_i.ar.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "INPUT_AXI AR ID width mismatch");
    assert ($bits(input_axi_rsp_o.r.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "INPUT_AXI R ID width mismatch");
    assert ($bits(input_axi_rsp_o.b.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "INPUT_AXI B ID width mismatch");

    // sep_in_axi
    assert ($bits(sep_in_axi_req_i.aw.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "SEP_IN_AXI AW ID width mismatch");
    assert ($bits(sep_in_axi_req_i.aw.addr) == $bits(smc_local_xbar_pkg::axi64_addr_t))
    else $fatal(1, "SEP_IN_AXI AW ADDR width mismatch");
    assert ($bits(sep_in_axi_req_i.w.data) == $bits(smc_local_xbar_pkg::axi64_data_t))
    else $fatal(1, "SEP_IN_AXI W DATA width mismatch");
    assert ($bits(sep_in_axi_req_i.ar.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "SEP_IN_AXI AR ID width mismatch");
    assert ($bits(sep_in_axi_rsp_o.r.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "SEP_IN_AXI R ID width mismatch");
    assert ($bits(sep_in_axi_rsp_o.b.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "SEP_IN_AXI B ID width mismatch");

    // local_axi
    assert ($bits(local_axi_req_i.aw.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "LOCAL_AXI AW ID width mismatch");
    assert ($bits(local_axi_req_i.aw.addr) == $bits(smc_local_xbar_pkg::axi64_addr_t))
    else $fatal(1, "LOCAL_AXI AW ADDR width mismatch");
    assert ($bits(local_axi_req_i.w.data) == $bits(smc_local_xbar_pkg::axi64_data_t))
    else $fatal(1, "LOCAL_AXI W DATA width mismatch");
    assert ($bits(local_axi_req_i.ar.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "LOCAL_AXI AR ID width mismatch");
    assert ($bits(local_axi_rsp_o.r.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "LOCAL_AXI R ID width mismatch");
    assert ($bits(local_axi_rsp_o.b.id) == $bits(smc_local_xbar_pkg::axi64_id_t))
    else $fatal(1, "LOCAL_AXI B ID width mismatch");
  end

  // AXI64 output types (8-bit ID, 32-bit addr, 64-bit data, 12-bit user)
  initial begin : gen_axi64_output_type_assertions
    // front_port
    assert ($bits(axi_front_port_req_o.aw.id) == $bits(smc_local_xbar_pkg::axi_out_id_t))
    else $fatal(1, "FRONT_PORT AW ID width mismatch");
    assert ($bits(axi_front_port_req_o.aw.addr) == $bits(smc_local_xbar_pkg::axi_out_addr_t))
    else $fatal(1, "FRONT_PORT AW ADDR width mismatch");
    assert ($bits(axi_front_port_req_o.w.data) == $bits(smc_local_xbar_pkg::axi_out_data_t))
    else $fatal(1, "FRONT_PORT W DATA width mismatch");
    assert ($bits(axi_front_port_req_o.ar.id) == $bits(smc_local_xbar_pkg::axi_out_id_t))
    else $fatal(1, "FRONT_PORT AR ID width mismatch");
    assert ($bits(axi_front_port_rsp_i.r.id) == $bits(smc_local_xbar_pkg::axi_out_id_t))
    else $fatal(1, "FRONT_PORT R ID width mismatch");
    assert ($bits(axi_front_port_rsp_i.b.id) == $bits(smc_local_xbar_pkg::axi_out_id_t))
    else $fatal(1, "FRONT_PORT B ID width mismatch");

    // data_accel_ctrl
    assert ($bits(axi_data_accel_ctrl_req_o.aw.id) == $bits(smc_local_xbar_pkg::axi_out_id_t))
    else $fatal(1, "DATA_ACCEL_CTRL AW ID width mismatch");
    assert ($bits(axi_data_accel_ctrl_req_o.aw.addr) == $bits(smc_local_xbar_pkg::axi_out_addr_t))
    else $fatal(1, "DATA_ACCEL_CTRL AW ADDR width mismatch");
    assert ($bits(axi_data_accel_ctrl_req_o.w.data) == $bits(smc_local_xbar_pkg::axi_out_data_t))
    else $fatal(1, "DATA_ACCEL_CTRL W DATA width mismatch");
    assert ($bits(axi_data_accel_ctrl_req_o.ar.id) == $bits(smc_local_xbar_pkg::axi_out_id_t))
    else $fatal(1, "DATA_ACCEL_CTRL AR ID width mismatch");
    assert ($bits(axi_data_accel_ctrl_rsp_i.r.id) == $bits(smc_local_xbar_pkg::axi_out_id_t))
    else $fatal(1, "DATA_ACCEL_CTRL R ID width mismatch");
    assert ($bits(axi_data_accel_ctrl_rsp_i.b.id) == $bits(smc_local_xbar_pkg::axi_out_id_t))
    else $fatal(1, "DATA_ACCEL_CTRL B ID width mismatch");
  end

  // APB32 types
  initial begin : gen_apb32_type_assertions
    // smc_dfd_reg
    assert ($bits(apb_smc_dfd_reg_req_o.paddr) == $bits(smc_local_xbar_pkg::apb32_addr_t))
    else $fatal(1, "APB_SMC_DFD_REG PADDR width mismatch");
    assert ($bits(apb_smc_dfd_reg_req_o.pwdata) == $bits(smc_local_xbar_pkg::apb32_data_t))
    else $fatal(1, "APB_SMC_DFD_REG PWDATA width mismatch");
    assert ($bits(apb_smc_dfd_reg_resp_i.prdata) == $bits(smc_local_xbar_pkg::apb32_data_t))
    else $fatal(1, "APB_SMC_DFD_REG PRDATA width mismatch");
  end
`endif  // SYNTHESIS

endmodule
