// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Remap AXI transactions onto target addresses selected by a per-region offset table.
//
// remap_ctrl_i carries per-region PeakRDL outs. REGION_BASE is subtracted from every AW and AR
// address, and bits [IDX_START +: RemapIndexW] of the result select a region. If that region is
// valid, the address becomes its offset bits [55:IDX_START] above the base-relative bits below
// IDX_START; otherwise the original address passes through unchanged. The module is
// combinational.
// When USER_OVERRIDE_EN is set, USER_OVERRIDE_VAL replaces the AW, AR and W user fields of every
// transaction.

module output_remap #(
  parameter type          axi_req_t         = logic,        // AXI request type.
  parameter type          axi_resp_t        = logic,        // AXI response type.
  parameter type          remap_addr_t      = logic,        // Remapped address type, built from the
                                                            // 56-bit offset field.
  parameter type          user_ovrd_t       = logic,        // AxUSER override type.
  parameter int unsigned  NUM_REGIONS       = 8,            // Number of remap regions.
  parameter int unsigned  REGION_BASE       = 0,            // Byte address subtracted from AW and
                                                            // AR addresses before indexing.
  parameter int unsigned  IDX_START         = 20,           // Address bit where the region index
                                                            // begins; each region spans
                                                            // 2**IDX_START bytes.
  parameter bit           USER_OVERRIDE_EN  = 1'b1,         // Replace the AW, AR and W user fields
                                                            // on every transaction.
  parameter user_ovrd_t   USER_OVERRIDE_VAL = '0,           // AxUSER value when overriding.

  localparam int unsigned RemapIndexW       = $clog2(NUM_REGIONS) // Region-index width.
) (
  input  logic                                       clk_i, // System clock; unused.
  input  logic                                       rst_ni, // Async reset, active-low; unused.
  input  logic                                       test_en_i, // DFT test enable; unused.

  input  output_remap_reg_pkg::output_remap__out_t   remap_ctrl_i [NUM_REGIONS-1:0], // Per-region PeakRDL configuration; only
                                                                                     // REGION.region_attrs.offset and
                                                                                     // .valid are used.

  input  axi_req_t           axi_req_i,                     // Pre-remap AXI request.
  output axi_resp_t          axi_resp_o,                    // Pre-remap AXI response.

  output axi_req_t           axi_remapped_req_o,            // Post-remap AXI request.
  input  axi_resp_t          axi_remapped_resp_i            // Post-remap AXI response.
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

  typedef struct packed {
    logic        valid;
    logic [55:0] offset;
  } remap_attrs_t;
  remap_attrs_t remap_table[NUM_REGIONS];


  // Connect register outputs to remap_table array
  for (genvar i = 0; i < NUM_REGIONS; i++) begin : gen_remap_table
    assign remap_table[i].valid  = remap_ctrl_i[i].REGION.region_attrs.valid.value;
    assign remap_table[i].offset = remap_ctrl_i[i].REGION.region_attrs.offset.value;
  end

  /////////////////////////////
  // Address Remapping Logic //
  /////////////////////////////

  assign adjusted_aw_addr = axi_req_i.aw.addr - remap_addr_t'(REGION_BASE);
  assign adjusted_ar_addr = axi_req_i.ar.addr - remap_addr_t'(REGION_BASE);

  always_comb begin
    // Extract remap table index from relevant bits of adjusted address
    remap_aw_idx = adjusted_aw_addr[IDX_START+:RemapIndexW];
    remap_ar_idx = adjusted_ar_addr[IDX_START+:RemapIndexW];

    // Remap address: replace upper bits with table offset, preserve lower bits
    remapped_aw_addr = axi_req_i.aw.addr;
    if (remap_table[remap_aw_idx].valid) begin
      remapped_aw_addr = {
        remap_table[remap_aw_idx].offset[55:IDX_START], adjusted_aw_addr[IDX_START-1:0]
      };
    end

    remapped_ar_addr = axi_req_i.ar.addr;
    if (remap_table[remap_ar_idx].valid) begin
      remapped_ar_addr = {
        remap_table[remap_ar_idx].offset[55:IDX_START], adjusted_ar_addr[IDX_START-1:0]
      };
    end
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

  if (USER_OVERRIDE_EN) begin : gen_user_override
    prim_axi_user_override_struct #(
      .AXI_ADDR_WIDTH   ($bits(axi_req_i.aw.addr)),
      .AXI_DATA_WIDTH   ($bits(axi_req_i.w.data)),
      .AXI_ID_WIDTH     ($bits(axi_req_i.aw.id)),
      .AXI_USER_WIDTH   ($bits(axi_req_i.aw.user)),
      .AXI_USER_OVERRIDE(USER_OVERRIDE_VAL),
      .axi_req_t        (axi_req_t),
      .axi_resp_t       (axi_resp_t)
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
