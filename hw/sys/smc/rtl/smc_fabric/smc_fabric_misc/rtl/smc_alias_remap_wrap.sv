// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// System Management Controller Alias Remap Wrap
//
//-----------------------------------------------------------------------------

module smc_alias_remap_wrap (
  // JTAG AXI Input
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_in_jtag_req_i,
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_in_jtag_resp_o,

  // Data Accelerator AXI Input
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_in_data_accel_req_i,
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_in_data_accel_resp_o,

  // MMIO AXI Input
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_in_mmio_req_i,
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_in_mmio_resp_o,

  // Log AXI Input
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_in_log_req_i,
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_in_log_resp_o,

  // Remapped JTAG AXI Output
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_out_remapped_jtag_req_o,
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_out_remapped_jtag_resp_i,

  // Remapped Data Accelerator AXI Output
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_out_remapped_data_accel_req_o,
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_out_remapped_data_accel_resp_i,

  // Remapped MMIO AXI Output
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_out_remapped_mmio_req_o,
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_out_remapped_mmio_resp_i,

  // Remapped Log AXI Output
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_out_remapped_log_req_o,
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_out_remapped_log_resp_i,

  // Config struct from register block -- alias remap
  input  alias_remap_reg_pkg::alias_remap__out_t aR_ctrl_i [smc_pkg::NUM_ALIAS_REMAP_REGIONS-1:0],

  // debug structs
  output smc_pkg::remap_debug_t remap_debug_mmio_o,
  output smc_pkg::remap_debug_t remap_debug_jtag_o,
  output smc_pkg::remap_debug_t remap_debug_log_o,
  output smc_pkg::remap_debug_t remap_debug_dma_o
);

  smc_pkg::remap_region_t remap_table[smc_pkg::NUM_ALIAS_REMAP_REGIONS-1:0];

  // Connect hwif_out to remap_table array
  for (genvar i = 0; i < smc_pkg::NUM_ALIAS_REMAP_REGIONS; i++) begin : gen_remap_table
    assign remap_table[i].region_start[smc_pkg::AXI_ADDR_WIDTH-1:smc_pkg::ALIAS_REMAP_IDX_START]    = aR_ctrl_i[i].REGION.region_start.start_addr.value;
    assign remap_table[i].region_end[smc_pkg::AXI_ADDR_WIDTH-1:smc_pkg::ALIAS_REMAP_IDX_START]      = aR_ctrl_i[i].REGION.region_end.end_addr.value;
    assign remap_table[i].offset[smc_pkg::AXI_ADDR_WIDTH-1:smc_pkg::ALIAS_REMAP_IDX_START]          = aR_ctrl_i[i].REGION.region_attrs.offset.value;
    assign remap_table[i].cacheable                                                                 = aR_ctrl_i[i].REGION.region_attrs.cacheable.value;
    assign remap_table[i].region_valid                                                              = aR_ctrl_i[i].REGION.region_attrs.valid.value;
  end

  // tie off unused bits of remap addresses to 0
  for (genvar i = 0; i < smc_pkg::NUM_ALIAS_REMAP_REGIONS; i++) begin : gen_tie_off_remap_bits
    assign remap_table[i].region_start[smc_pkg::ALIAS_REMAP_IDX_START-1:0]  = {smc_pkg::ALIAS_REMAP_IDX_START{1'b0}};
    assign remap_table[i].region_end[smc_pkg::ALIAS_REMAP_IDX_START-1:0]    = {smc_pkg::ALIAS_REMAP_IDX_START{1'b0}};
    assign remap_table[i].offset[smc_pkg::ALIAS_REMAP_IDX_START-1:0]        = {smc_pkg::ALIAS_REMAP_IDX_START{1'b0}};
  end

  axi_alias_remap #(
    .axi_req_t                     (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .axi_resp_t                    (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t),
    .remap_region_t                (smc_pkg::remap_region_t),
    .remap_debug_t                 (smc_pkg::remap_debug_t),
    .NUM_REGIONS                   (smc_pkg::NUM_ALIAS_REMAP_REGIONS),
    .DEBUG_OUTPUT                  (1),
    .ALIAS_REMAP_IDX_START         (smc_pkg::ALIAS_REMAP_IDX_START),
    .AXI_ADDR_WIDTH                (smc_pkg::AXI_ADDR_WIDTH),
    .NUM_CHUNKS_CARRY_SELECT_ADDER (smc_pkg::NUM_CHUNKS_ALIAS_REMAP_CARRY_SELECT_ADDER)
  ) smc_mmio_alias_remap (
    .remap_regions_i    (remap_table),
    .remap_debug_o      (remap_debug_mmio_o),
    .axi_in_req_i       (axi_in_mmio_req_i),
    .axi_in_resp_o      (axi_in_mmio_resp_o),
    .axi_out_req_o      (axi_out_remapped_mmio_req_o),
    .axi_out_resp_i     (axi_out_remapped_mmio_resp_i)
  );

  axi_alias_remap #(
    .axi_req_t                     (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .axi_resp_t                    (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t),
    .remap_region_t                (smc_pkg::remap_region_t),
    .remap_debug_t                 (smc_pkg::remap_debug_t),
    .NUM_REGIONS                   (smc_pkg::NUM_ALIAS_REMAP_REGIONS),
    .DEBUG_OUTPUT                  (1),
    .ALIAS_REMAP_IDX_START         (smc_pkg::ALIAS_REMAP_IDX_START),
    .AXI_ADDR_WIDTH                (smc_pkg::AXI_ADDR_WIDTH),
    .NUM_CHUNKS_CARRY_SELECT_ADDER (smc_pkg::NUM_CHUNKS_ALIAS_REMAP_CARRY_SELECT_ADDER)
  ) smc_jtag_alias_remap (
    .remap_regions_i    (remap_table),
    .remap_debug_o      (remap_debug_jtag_o),
    .axi_in_req_i       (axi_in_jtag_req_i),
    .axi_in_resp_o      (axi_in_jtag_resp_o),
    .axi_out_req_o      (axi_out_remapped_jtag_req_o),
    .axi_out_resp_i     (axi_out_remapped_jtag_resp_i)
  );

  axi_alias_remap #(
    .axi_req_t                     (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .axi_resp_t                    (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t),
    .remap_region_t                (smc_pkg::remap_region_t),
    .remap_debug_t                 (smc_pkg::remap_debug_t),
    .NUM_REGIONS                   (smc_pkg::NUM_ALIAS_REMAP_REGIONS),
    .DEBUG_OUTPUT                  (1),
    .ALIAS_REMAP_IDX_START         (smc_pkg::ALIAS_REMAP_IDX_START),
    .AXI_ADDR_WIDTH                (smc_pkg::AXI_ADDR_WIDTH),
    .NUM_CHUNKS_CARRY_SELECT_ADDER (smc_pkg::NUM_CHUNKS_ALIAS_REMAP_CARRY_SELECT_ADDER)
  ) smc_log_alias_remap (
    .remap_regions_i    (remap_table),
    .remap_debug_o      (remap_debug_log_o),
    .axi_in_req_i       (axi_in_log_req_i),
    .axi_in_resp_o      (axi_in_log_resp_o),
    .axi_out_req_o      (axi_out_remapped_log_req_o),
    .axi_out_resp_i     (axi_out_remapped_log_resp_i)
  );

  axi_alias_remap #(
    .axi_req_t                     (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .axi_resp_t                    (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t),
    .remap_region_t                (smc_pkg::remap_region_t),
    .remap_debug_t                 (smc_pkg::remap_debug_t),
    .NUM_REGIONS                   (smc_pkg::NUM_ALIAS_REMAP_REGIONS),
    .DEBUG_OUTPUT                  (1),
    .ALIAS_REMAP_IDX_START         (smc_pkg::ALIAS_REMAP_IDX_START),
    .AXI_ADDR_WIDTH                (smc_pkg::AXI_ADDR_WIDTH),
    .NUM_CHUNKS_CARRY_SELECT_ADDER (smc_pkg::NUM_CHUNKS_ALIAS_REMAP_CARRY_SELECT_ADDER)
  ) smc_dma_alias_remap (
    .remap_regions_i    (remap_table),
    .remap_debug_o      (remap_debug_dma_o),
    .axi_in_req_i       (axi_in_data_accel_req_i),
    .axi_in_resp_o      (axi_in_data_accel_resp_o),
    .axi_out_req_o      (axi_out_remapped_data_accel_req_o),
    .axi_out_resp_i     (axi_out_remapped_data_accel_resp_i)
  );

endmodule
