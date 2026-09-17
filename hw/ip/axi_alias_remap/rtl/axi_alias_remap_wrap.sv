// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Alias Remap Wrapper - Connects register interface to axi_alias_remap
//
// This module provides an easy-to-use wrapper that converts the generated
// register outputs to the remap_table format expected by axi_alias_remap.
//
//-----------------------------------------------------------------------------

module axi_alias_remap_wrap #(
  parameter type         axi_req_t                     = logic,
  parameter type         axi_resp_t                    = logic,
  parameter type         remap_region_t                = logic,
  parameter type         remap_debug_t                 = logic,
  parameter int unsigned NUM_REGIONS                   = 8,
  parameter int unsigned DEBUG_OUTPUT                  = 0,
  parameter int unsigned ALIAS_REMAP_IDX_START         = 12,
  parameter int unsigned AXI_ADDR_WIDTH                = 64,
  parameter int unsigned NUM_CHUNKS_CARRY_SELECT_ADDER = 2
) (
  // Register interface from generated register block
  input  alias_remap_reg_pkg::alias_remap__out_t reg_ctrl_i [NUM_REGIONS-1:0],

  // Debug output
  output remap_debug_t remap_debug_o,

  // AXI Input Interface
  input  axi_req_t  axi_in_req_i,
  output axi_resp_t axi_in_resp_o,

  // AXI Output Interface (remapped)
  output axi_req_t  axi_out_req_o,
  input  axi_resp_t axi_out_resp_i
);

  remap_region_t remap_table[NUM_REGIONS-1:0];

  // Connect register outputs to remap_table array
  for (genvar i = 0; i < NUM_REGIONS; i++) begin : gen_remap_table
    assign remap_table[i].region_start[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START] = reg_ctrl_i[i].REGION.region_start.start_addr.value;
    assign remap_table[i].region_end[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]   = reg_ctrl_i[i].REGION.region_end.end_addr.value;
    assign remap_table[i].offset[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]       = reg_ctrl_i[i].REGION.region_attrs.offset.value;
    assign remap_table[i].cacheable                                            = reg_ctrl_i[i].REGION.region_attrs.cacheable.value;
    assign remap_table[i].region_valid                                         = reg_ctrl_i[i].REGION.region_attrs.valid.value;

    // Tie off unused bits of remap addresses to 0
    assign remap_table[i].region_start[ALIAS_REMAP_IDX_START-1:0] = {ALIAS_REMAP_IDX_START{1'b0}};
    assign remap_table[i].region_end[ALIAS_REMAP_IDX_START-1:0]   = {ALIAS_REMAP_IDX_START{1'b0}};
    assign remap_table[i].offset[ALIAS_REMAP_IDX_START-1:0]       = {ALIAS_REMAP_IDX_START{1'b0}};
  end

  axi_alias_remap #(
    .axi_req_t                    (axi_req_t),
    .axi_resp_t                   (axi_resp_t),
    .remap_region_t               (remap_region_t),
    .remap_debug_t                (remap_debug_t),
    .NUM_REGIONS                  (NUM_REGIONS),
    .DEBUG_OUTPUT                 (DEBUG_OUTPUT),
    .ALIAS_REMAP_IDX_START        (ALIAS_REMAP_IDX_START),
    .AXI_ADDR_WIDTH               (AXI_ADDR_WIDTH),
    .NUM_CHUNKS_CARRY_SELECT_ADDER(NUM_CHUNKS_CARRY_SELECT_ADDER)
  ) u_axi_alias_remap (
    .remap_regions_i (remap_table),
    .remap_debug_o   (remap_debug_o),
    .axi_in_req_i    (axi_in_req_i),
    .axi_in_resp_o   (axi_in_resp_o),
    .axi_out_req_o   (axi_out_req_o),
    .axi_out_resp_i  (axi_out_resp_i)
  );

endmodule
