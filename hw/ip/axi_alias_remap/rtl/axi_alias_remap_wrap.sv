// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Pack PeakRDL register outs into remap_region_t and drive axi_alias_remap.
//
// Converts the generated register outputs to the remap_table format expected by
// axi_alias_remap.
// reg_ctrl_i is one generated out-struct per region; AXI and debug ports pass through to
// the remapper.

module axi_alias_remap_wrap #(
  parameter type         axi_req_t                     = logic, // AXI request channel type.
  parameter type         axi_resp_t                    = logic, // AXI response channel type.
  parameter type         remap_region_t                = logic, // Per-region remap configuration type.
  parameter type         remap_debug_t                 = logic, // Remap hit debug type.
  parameter int unsigned NUM_REGIONS                   = 8, // Number of alias regions.
  parameter int unsigned DEBUG_OUTPUT                  = 0, // Enables remap_debug_o.
  parameter int unsigned ALIAS_REMAP_IDX_START         = 12, // Address bit where the remap index begins.
  parameter int unsigned AXI_ADDR_WIDTH                = 64, // AXI address width.
  parameter int unsigned NUM_CHUNKS_CARRY_SELECT_ADDER = 2  // Carry-select adder chunk count.
) (
  input  alias_remap_reg_pkg::alias_remap__out_t reg_ctrl_i [NUM_REGIONS-1:0], // PeakRDL outs for each remap region.

  output remap_debug_t remap_debug_o,                       // Remap hit debug.

  input  axi_req_t  axi_in_req_i,                           // Pre-remap AXI request.
  output axi_resp_t axi_in_resp_o,                          // Pre-remap AXI response.

  output axi_req_t  axi_out_req_o,                          // Post-remap AXI request.
  input  axi_resp_t axi_out_resp_i                          // Post-remap AXI response.
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
