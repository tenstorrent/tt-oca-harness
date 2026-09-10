// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------
// AXI Alias Remap Interface
//
//------------------------------------------------------------

module axi_alias_remap #(
  parameter type          axi_req_t                       = logic,
  parameter type          axi_resp_t                      = logic,
  parameter type          remap_region_t                  = logic,
  parameter type          remap_debug_t                   = logic,
  parameter int unsigned  NUM_REGIONS                     = 4,
  parameter int unsigned  DEBUG_OUTPUT                    = 0,

  parameter int unsigned  ALIAS_REMAP_IDX_START           = 12,
  parameter int unsigned  AXI_ADDR_WIDTH                  = 64,

  parameter int unsigned  NUM_CHUNKS_CARRY_SELECT_ADDER   = 2,

  localparam int unsigned ALIAS_REMAP_OFFSET_WIDTH        = AXI_ADDR_WIDTH - ALIAS_REMAP_IDX_START
) (
  input   remap_region_t                      i_remap_regions [NUM_REGIONS-1:0],
  output  remap_debug_t                       o_remap_debug,

  // AXI Input Interface
  input   axi_req_t                           axi_in_req_i,
  output  axi_resp_t                          axi_in_resp_o,

  // AXI Output Interface (remapped)
  output  axi_req_t                           axi_out_req_o,
  input   axi_resp_t                          axi_out_resp_i
);

  localparam int unsigned RemapIndexW = $clog2(NUM_REGIONS);
  typedef logic [RemapIndexW-1:0] remap_idx_t;
  typedef logic [NUM_REGIONS-1:0] remap_vector_t;
  // we do addition/subtraction with remapped addr, need one extra bit in case of overflow
  typedef logic [ALIAS_REMAP_OFFSET_WIDTH:0] remap_addr_t;
  typedef logic [AXI_ADDR_WIDTH-1:0] addr_t;

  remap_vector_t aw_remap_hit, ar_remap_hit;
  remap_idx_t aw_remap_idx, ar_remap_idx;
  logic no_write_hit, no_read_hit;

  remap_addr_t aw_addr_modified, ar_addr_modified;
  addr_t aw_remapped_addr, ar_remapped_addr;
  logic aw_remapped_cacheable, ar_remapped_cacheable;

  // Check if access is within a valid remap region
  always_comb begin
    for (int r = 0; r < NUM_REGIONS; r++) begin
      aw_remap_hit[r] = i_remap_regions[r].region_valid && (axi_in_req_i.aw.addr >= i_remap_regions[r].region_start && axi_in_req_i.aw.addr < i_remap_regions[r].region_end);
      ar_remap_hit[r] = i_remap_regions[r].region_valid && (axi_in_req_i.ar.addr >= i_remap_regions[r].region_start && axi_in_req_i.ar.addr < i_remap_regions[r].region_end);
    end
  end

  lzc #(
    .WIDTH  (NUM_REGIONS),
    .MODE   (1'b0)  // Count leading zeros to find the index of the first remap region that contains the request address
  ) write_remap_hit (
    .in_i   (aw_remap_hit),
    .cnt_o  (aw_remap_idx),
    .empty_o(no_write_hit)
  );

  lzc #(
    .WIDTH  (NUM_REGIONS),
    .MODE   (1'b0)  // Count leading zeros to find the index of the first remap region that contains the request address
  ) read_remap_hit (
    .in_i   (ar_remap_hit),
    .cnt_o  (ar_remap_idx),
    .empty_o(no_read_hit)
  );

  generate
    if (DEBUG_OUTPUT == 1) begin : gen_remap_debug
      assign o_remap_debug.aw_remap_hit_debug = aw_remap_idx;
      assign o_remap_debug.ar_remap_hit_debug = ar_remap_idx;
    end else begin : gen_no_remap_debug
      assign o_remap_debug = '0;
    end
  endgenerate

  prim_carry_select_adder #(
    .DATA_WIDTH (ALIAS_REMAP_OFFSET_WIDTH+1),
    .NUM_CHUNKS (NUM_CHUNKS_CARRY_SELECT_ADDER)
  ) u_aw_addr_adder (
    .a_i    ({1'b0, i_remap_regions[aw_remap_idx].offset[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]}),
    .b_i    ({1'b0, axi_in_req_i.aw.addr[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]}),
    .sum_o  (aw_addr_modified),
    .cout_o ()
  );

  prim_carry_select_adder #(
    .DATA_WIDTH (ALIAS_REMAP_OFFSET_WIDTH+1),
    .NUM_CHUNKS (NUM_CHUNKS_CARRY_SELECT_ADDER)
  ) u_ar_addr_adder (
    .a_i    ({1'b0, i_remap_regions[ar_remap_idx].offset[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]}),
    .b_i    ({1'b0, axi_in_req_i.ar.addr[AXI_ADDR_WIDTH-1:ALIAS_REMAP_IDX_START]}),
    .sum_o  (ar_addr_modified),
    .cout_o ()
  );

  assign aw_remapped_addr = {
        aw_addr_modified[ALIAS_REMAP_OFFSET_WIDTH-1:0], axi_in_req_i.aw.addr[ALIAS_REMAP_IDX_START-1:0]
    };
  assign aw_remapped_cacheable = i_remap_regions[aw_remap_idx].cacheable;

  assign ar_remapped_addr = {
        ar_addr_modified[ALIAS_REMAP_OFFSET_WIDTH-1:0], axi_in_req_i.ar.addr[ALIAS_REMAP_IDX_START-1:0]
    };
  assign ar_remapped_cacheable = i_remap_regions[ar_remap_idx].cacheable;

  // AW Channel - Write Address
  assign axi_out_req_o.aw_valid   = axi_in_req_i.aw_valid;
  assign axi_out_req_o.aw.id      = axi_in_req_i.aw.id;
  assign axi_out_req_o.aw.addr    = no_write_hit ? axi_in_req_i.aw.addr : aw_remapped_addr;
  assign axi_out_req_o.aw.len     = axi_in_req_i.aw.len;
  assign axi_out_req_o.aw.size    = axi_in_req_i.aw.size;
  assign axi_out_req_o.aw.burst   = axi_in_req_i.aw.burst;
  assign axi_out_req_o.aw.lock    = axi_in_req_i.aw.lock;
  assign axi_out_req_o.aw.cache   = no_write_hit ? axi_in_req_i.aw.cache : {(axi_pkg::CacheWidth){aw_remapped_cacheable}};
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
  assign axi_out_req_o.ar.cache   = no_read_hit ? axi_in_req_i.ar.cache : {(axi_pkg::CacheWidth){ar_remapped_cacheable}};
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
