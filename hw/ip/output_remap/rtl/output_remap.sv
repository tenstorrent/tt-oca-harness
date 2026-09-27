// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// System Management Controller Output Remap

module output_remap #(
  parameter type          axi_req_t        = logic,
  parameter type          axi_resp_t       = logic,
  parameter type          remap_addr_t     = logic,
  parameter type          user_ovrd_t      = logic,
  parameter int unsigned  NumRegions       = 8,
  parameter int unsigned  RegionBase       = 0,
  parameter int unsigned  IdxStart         = 20,
  parameter bit           UserOverrideEn   = 1'b1,
  parameter user_ovrd_t   UserOverrideVal  = '0,

  localparam int unsigned RemapIndexW      = $clog2(NumRegions)
) (
  input  logic                                       clk_i,
  input  logic                                       rst_ni,
  input  logic                                       test_en_i,

  // CSR structs for remap configuration
  input  output_remap_reg_pkg::output_remap__out_t   remap_ctrl_i [NumRegions-1:0],

  // Main data AXI interface
  input  axi_req_t           axi_req_i,
  output axi_resp_t          axi_resp_o,

  output axi_req_t           axi_remapped_req_o,
  input  axi_resp_t          axi_remapped_resp_i
);

  /////////////////////////
  // Signal declarations //
  /////////////////////////

  remap_addr_t adjusted_aw_addr, adjusted_ar_addr;
  logic [RemapIndexW-1:0] remap_aw_idx, remap_ar_idx;
  remap_addr_t remapped_aw_addr, remapped_ar_addr;

  /////
  // Convert struct to array
  /////

  typedef struct packed {logic [55:0] offset;} remap_attrs_t;
  remap_attrs_t remap_table[NumRegions];


  // Connect register outputs to remap_table array
  for (genvar i = 0; i < NumRegions; i++) begin : gen_remap_table
    assign remap_table[i].offset = remap_ctrl_i[i].REGION.region_attrs.offset.value;
  end

  /////////////////////////////
  // Address Remapping Logic //
  /////////////////////////////

  assign adjusted_aw_addr = axi_req_i.aw.addr - remap_addr_t'(RegionBase);
  assign adjusted_ar_addr = axi_req_i.ar.addr - remap_addr_t'(RegionBase);

  always_comb begin
    // Extract remap table index from relevant bits of adjusted address
    remap_aw_idx = adjusted_aw_addr[IdxStart+:RemapIndexW];
    remap_ar_idx = adjusted_ar_addr[IdxStart+:RemapIndexW];

    // Remap address: replace upper bits with table offset, preserve lower bits
    remapped_aw_addr = {
            remap_table[remap_aw_idx].offset[55:IdxStart], adjusted_aw_addr[IdxStart-1:0]
        };

    remapped_ar_addr = {
            remap_table[remap_ar_idx].offset[55:IdxStart], adjusted_ar_addr[IdxStart-1:0]
        };
  end

  /////////////////////
  // AXI Translation //
  /////////////////////

  // Apply the address remap; user-bit override and full req/resp passthrough
  // are handled by prim_axi_user_override_struct below.
  axi_req_t axi_req_remapped;
  always_comb begin
    axi_req_remapped         = axi_req_i;
    axi_req_remapped.aw.addr = remapped_aw_addr;
    axi_req_remapped.ar.addr = remapped_ar_addr;
  end

  if (UserOverrideEn) begin : gen_user_override
    prim_axi_user_override_struct #(
      .AxiAddrWidth   ($bits(axi_req_i.aw.addr)),
      .AxiDataWidth   ($bits(axi_req_i.w.data)),
      .AxiIdWidth     ($bits(axi_req_i.aw.id)),
      .AxiUserWidth   ($bits(axi_req_i.aw.user)),
      .AxiUserOverride(UserOverrideVal),
      .axi_req_t      (axi_req_t),
      .axi_resp_t     (axi_resp_t)
    ) u_user_override (
      .axi_in_req_i   (axi_req_remapped),
      .axi_in_resp_o  (axi_resp_o),
      .axi_out_req_o  (axi_remapped_req_o),
      .axi_out_resp_i (axi_remapped_resp_i)
    );
  end else begin : gen_no_user_override
    assign axi_remapped_req_o = axi_req_remapped;
    assign axi_resp_o         = axi_remapped_resp_i;
  end

endmodule
