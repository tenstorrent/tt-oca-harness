// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Remap AXI addresses that hit configured alias regions onto their target bases.
//
// Each remap_regions_i entry supplies a valid bit, a region_start and exclusive region_end
// bound, an offset, and a cacheable field. The module is combinational. When AW or AR hits
// valid regions, the lowest-numbered one applies: a carry-select adder adds its offset to the
// address bits from ALIAS_REMAP_IDX_START upward, modulo their width, the bits below pass
// through, and AxCACHE is replaced by the region's cacheable value, bit for bit. Misses pass
// through unchanged, and all other channels are wired straight through.

module axi_alias_remap #(
  parameter type          axi_req_t                       = logic, // AXI request channel type.
  parameter type          axi_resp_t                      = logic, // AXI response channel type.
  parameter type          remap_region_t                  = logic, // Per-region configuration with
                                                                   // region_valid, region_start,
                                                                   // region_end, offset and
                                                                   // cacheable fields.
  parameter type          remap_debug_t                   = logic, // Debug type with
                                                                   // aw_remap_hit_debug and
                                                                   // ar_remap_hit_debug
                                                                   // region-index fields.
  parameter int unsigned  NUM_REGIONS                     = 4, // Number of alias regions.
  parameter int unsigned  DEBUG_OUTPUT                    = 0, // remap_debug_o is driven when 1 and
                                                               // tied to zero otherwise.

  parameter int unsigned  ALIAS_REMAP_IDX_START           = 12, // Lowest remapped address bit;
                                                                // lower bits pass through
                                                                // unchanged.
  parameter int unsigned  AXI_ADDR_WIDTH                  = 64, // AXI address width.

  parameter int unsigned  NUM_CHUNKS_CARRY_SELECT_ADDER   = 2, // Carry-select adder chunk count.

  localparam int unsigned AliasRemapOffsetWidth        = AXI_ADDR_WIDTH - ALIAS_REMAP_IDX_START // Width of the remapped upper address field.
) (
  input   remap_region_t                      remap_regions_i [NUM_REGIONS-1:0], // Per-region remap configuration.
  output  remap_debug_t                       remap_debug_o, // Index of the lowest-numbered region
                                                             // hit by the current AW and AR
                                                             // addresses; zero when neither hits.

  input   axi_req_t                           axi_in_req_i, // Pre-remap AXI request.
  output  axi_resp_t                          axi_in_resp_o, // Pre-remap AXI response.

  output  axi_req_t                           axi_out_req_o, // Post-remap AXI request.
  input   axi_resp_t                          axi_out_resp_i // Post-remap AXI response.
);

  localparam int unsigned RemapIndexW = $clog2(NUM_REGIONS);
  typedef logic [RemapIndexW-1:0] remap_idx_t;
  typedef logic [NUM_REGIONS-1:0] remap_vector_t;
  // we do addition/subtraction with remapped addr, need one extra bit in case of overflow
  typedef logic [AliasRemapOffsetWidth:0] remap_addr_t;
  typedef logic [AXI_ADDR_WIDTH-1:0] addr_t;

  remap_vector_t aw_remap_hit, ar_remap_hit;
  remap_idx_t aw_remap_idx, ar_remap_idx;
  logic no_write_hit, no_read_hit;

  remap_addr_t aw_addr_modified, ar_addr_modified;
  addr_t aw_remapped_addr, ar_remapped_addr;
  axi_pkg::cache_t aw_remapped_cacheable, ar_remapped_cacheable;

  // Check if access is within a valid remap region
  always_comb begin
    for (int r = 0; r < NUM_REGIONS; r++) begin
      aw_remap_hit[r] = remap_regions_i[r].region_valid && (axi_in_req_i.aw.addr >= remap_regions_i[r].region_start && axi_in_req_i.aw.addr < remap_regions_i[r].region_end);
      ar_remap_hit[r] = remap_regions_i[r].region_valid && (axi_in_req_i.ar.addr >= remap_regions_i[r].region_start && axi_in_req_i.ar.addr < remap_regions_i[r].region_end);
    end
  end

  lzc #(
    .WIDTH  (NUM_REGIONS),
    .MODE   (1'b0)  // Count leading zeros to find the index of the first remap region that contains the request address
  ) u_write_remap_hit (
    .in_i   (aw_remap_hit),
    .cnt_o  (aw_remap_idx),
    .empty_o(no_write_hit)
  );

  lzc #(
    .WIDTH  (NUM_REGIONS),
    .MODE   (1'b0)  // Count leading zeros to find the index of the first remap region that contains the request address
  ) u_read_remap_hit (
    .in_i   (ar_remap_hit),
    .cnt_o  (ar_remap_idx),
    .empty_o(no_read_hit)
  );

  if (DEBUG_OUTPUT == 1) begin : gen_remap_debug
    assign remap_debug_o.aw_remap_hit_debug = aw_remap_idx;
    assign remap_debug_o.ar_remap_hit_debug = ar_remap_idx;
  end else begin : gen_no_remap_debug
    assign remap_debug_o = '0;
  end

  prim_carry_select_adder #(
    .DATA_WIDTH (AliasRemapOffsetWidth+1),
    .NUM_CHUNKS (NUM_CHUNKS_CARRY_SELECT_ADDER)
  ) u_aw_addr_adder (
    .a_i   ({1'b0, remap_regions_i[aw_remap_idx].offset[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]}),
    .b_i   ({1'b0, axi_in_req_i.aw.addr[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]}),
    .sum_o (aw_addr_modified),
    .c_o   ()
  );

  prim_carry_select_adder #(
    .DATA_WIDTH (AliasRemapOffsetWidth+1),
    .NUM_CHUNKS (NUM_CHUNKS_CARRY_SELECT_ADDER)
  ) u_ar_addr_adder (
    .a_i   ({1'b0, remap_regions_i[ar_remap_idx].offset[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]}),
    .b_i   ({1'b0, axi_in_req_i.ar.addr[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]}),
    .sum_o (ar_addr_modified),
    .c_o   ()
  );

  assign aw_remapped_addr = {
        aw_addr_modified[AliasRemapOffsetWidth-1:0], axi_in_req_i.aw.addr[ALIAS_REMAP_IDX_START-1:0]
    };
  assign aw_remapped_cacheable = remap_regions_i[aw_remap_idx].cacheable;

  assign ar_remapped_addr = {
        ar_addr_modified[AliasRemapOffsetWidth-1:0], axi_in_req_i.ar.addr[ALIAS_REMAP_IDX_START-1:0]
    };
  assign ar_remapped_cacheable = remap_regions_i[ar_remap_idx].cacheable;

  // AW Channel - Write Address
  assign axi_out_req_o.aw_valid   = axi_in_req_i.aw_valid;
  assign axi_out_req_o.aw.id      = axi_in_req_i.aw.id;
  assign axi_out_req_o.aw.addr    = no_write_hit ? axi_in_req_i.aw.addr : aw_remapped_addr;
  assign axi_out_req_o.aw.len     = axi_in_req_i.aw.len;
  assign axi_out_req_o.aw.size    = axi_in_req_i.aw.size;
  assign axi_out_req_o.aw.burst   = axi_in_req_i.aw.burst;
  assign axi_out_req_o.aw.lock    = axi_in_req_i.aw.lock;
  assign axi_out_req_o.aw.cache   = no_write_hit ? axi_in_req_i.aw.cache : aw_remapped_cacheable;
  assign axi_out_req_o.aw.prot    = axi_in_req_i.aw.prot;
  assign axi_out_req_o.aw.qos     = axi_in_req_i.aw.qos;
  assign axi_out_req_o.aw.region  = axi_in_req_i.aw.region;
  assign axi_out_req_o.aw.user    = axi_in_req_i.aw.user;
  assign axi_out_req_o.aw.atop    = axi_in_req_i.aw.atop;

  // W Channel - Write Data
  assign axi_out_req_o.w_valid    = axi_in_req_i.w_valid;
  assign axi_out_req_o.w.data     = axi_in_req_i.w.data;
  assign axi_out_req_o.w.strb     = axi_in_req_i.w.strb;
  assign axi_out_req_o.w.last     = axi_in_req_i.w.last;
  assign axi_out_req_o.w.user     = axi_in_req_i.w.user;

  // B Channel - Write Response
  assign axi_out_req_o.b_ready    = axi_in_req_i.b_ready;

  // AR Channel - Read Address
  assign axi_out_req_o.ar_valid   = axi_in_req_i.ar_valid;
  assign axi_out_req_o.ar.id      = axi_in_req_i.ar.id;
  assign axi_out_req_o.ar.addr    = no_read_hit ? axi_in_req_i.ar.addr : ar_remapped_addr;
  assign axi_out_req_o.ar.len     = axi_in_req_i.ar.len;
  assign axi_out_req_o.ar.size    = axi_in_req_i.ar.size;
  assign axi_out_req_o.ar.burst   = axi_in_req_i.ar.burst;
  assign axi_out_req_o.ar.lock    = axi_in_req_i.ar.lock;
  assign axi_out_req_o.ar.cache   = no_read_hit ? axi_in_req_i.ar.cache : ar_remapped_cacheable;
  assign axi_out_req_o.ar.prot    = axi_in_req_i.ar.prot;
  assign axi_out_req_o.ar.qos     = axi_in_req_i.ar.qos;
  assign axi_out_req_o.ar.region  = axi_in_req_i.ar.region;
  assign axi_out_req_o.ar.user    = axi_in_req_i.ar.user;

  // R Channel - Read Data
  assign axi_out_req_o.r_ready    = axi_in_req_i.r_ready;

  // Response mapping from output back to input
  assign axi_in_resp_o.aw_ready   = axi_out_resp_i.aw_ready;
  assign axi_in_resp_o.w_ready    = axi_out_resp_i.w_ready;
  assign axi_in_resp_o.b_valid    = axi_out_resp_i.b_valid;
  assign axi_in_resp_o.b.id       = axi_out_resp_i.b.id;
  assign axi_in_resp_o.b.resp     = axi_out_resp_i.b.resp;
  assign axi_in_resp_o.b.user     = axi_out_resp_i.b.user;
  assign axi_in_resp_o.ar_ready   = axi_out_resp_i.ar_ready;
  assign axi_in_resp_o.r_valid    = axi_out_resp_i.r_valid;
  assign axi_in_resp_o.r.id       = axi_out_resp_i.r.id;
  assign axi_in_resp_o.r.data     = axi_out_resp_i.r.data;
  assign axi_in_resp_o.r.resp     = axi_out_resp_i.r.resp;
  assign axi_in_resp_o.r.last     = axi_out_resp_i.r.last;
  assign axi_in_resp_o.r.user     = axi_out_resp_i.r.user;

endmodule
