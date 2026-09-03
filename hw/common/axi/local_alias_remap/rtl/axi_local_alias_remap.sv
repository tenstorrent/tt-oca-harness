// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// AXI Window Remap
//
// Generic single-window address translation: conditionally remaps addresses
// in a specified window to a target region. Addresses outside the window pass
// through unchanged. Used for both local-alias and global-to-local remapping.
//
// Example: If local_alias_base=0xC000_0000, target_base=0x1000_0000, region_size=0x50000
//   - Address 0xC000_1234 -> remapped to 0x1000_1234
//   - Address 0x2000_0000 -> unchanged (outside alias region)

module axi_window_remap #(
  parameter type axi_req_t  = logic,
  parameter type axi_resp_t = logic,
  parameter int unsigned AXI_ADDR_WIDTH = 32
) (
  // Slave side (from CPU)
  input  axi_req_t                   slv_req_i,
  output axi_resp_t                  slv_resp_o,

  // Master side (to fabric)
  output axi_req_t                   mst_req_o,
  input  axi_resp_t                  mst_resp_i,

  // Configuration - all runtime inputs for flexibility
  input  logic [AXI_ADDR_WIDTH-1:0]  local_alias_base_i,  // Start of alias region (e.g., 0xC000_0000)
  input  logic [AXI_ADDR_WIDTH-1:0]  region_size_i,       // Size of alias region
  input  logic [AXI_ADDR_WIDTH-1:0]  target_base_i        // Where to remap to (e.g., 0x1000_0000)
);

  // Calculate region bounds and adjustment
  // Use AXI_ADDR_WIDTH+1 bits for local_alias_end to handle overflow
  // (e.g., 0xC000_0000 + 0x4000_0000 = 0x1_0000_0000 needs 33 bits)
  wire [AXI_ADDR_WIDTH:0] local_alias_end = {1'b0, local_alias_base_i} + {1'b0, region_size_i};
  wire [AXI_ADDR_WIDTH-1:0] adjust_amount = local_alias_base_i - target_base_i;

  // Determine if addresses are in local alias region
  // Extend addresses to AXI_ADDR_WIDTH+1 bits for correct comparison with local_alias_end
  wire aw_in_alias = (slv_req_i.aw.addr >= local_alias_base_i) &&
                       ({1'b0, slv_req_i.aw.addr} < local_alias_end);
  wire ar_in_alias = (slv_req_i.ar.addr >= local_alias_base_i) &&
                       ({1'b0, slv_req_i.ar.addr} < local_alias_end);

  // Calculate adjusted addresses
  wire [AXI_ADDR_WIDTH-1:0] aw_addr_adjusted = slv_req_i.aw.addr - adjust_amount;
  wire [AXI_ADDR_WIDTH-1:0] ar_addr_adjusted = slv_req_i.ar.addr - adjust_amount;

  // Mux addresses - use adjusted if in alias region, otherwise passthrough
  assign mst_req_o.aw.addr = aw_in_alias ? aw_addr_adjusted : slv_req_i.aw.addr;
  assign mst_req_o.ar.addr = ar_in_alias ? ar_addr_adjusted : slv_req_i.ar.addr;

  // Pass through all other request signals unchanged
  assign mst_req_o.aw_valid  = slv_req_i.aw_valid;
  assign mst_req_o.aw.id     = slv_req_i.aw.id;
  assign mst_req_o.aw.len    = slv_req_i.aw.len;
  assign mst_req_o.aw.size   = slv_req_i.aw.size;
  assign mst_req_o.aw.burst  = slv_req_i.aw.burst;
  assign mst_req_o.aw.lock   = slv_req_i.aw.lock;
  assign mst_req_o.aw.cache  = slv_req_i.aw.cache;
  assign mst_req_o.aw.prot   = slv_req_i.aw.prot;
  assign mst_req_o.aw.qos    = slv_req_i.aw.qos;
  assign mst_req_o.aw.region = slv_req_i.aw.region;
  assign mst_req_o.aw.atop   = slv_req_i.aw.atop;
  assign mst_req_o.aw.user   = slv_req_i.aw.user;

  assign mst_req_o.w_valid = slv_req_i.w_valid;
  assign mst_req_o.w       = slv_req_i.w;

  assign mst_req_o.b_ready = slv_req_i.b_ready;

  assign mst_req_o.ar_valid  = slv_req_i.ar_valid;
  assign mst_req_o.ar.id     = slv_req_i.ar.id;
  assign mst_req_o.ar.len    = slv_req_i.ar.len;
  assign mst_req_o.ar.size   = slv_req_i.ar.size;
  assign mst_req_o.ar.burst  = slv_req_i.ar.burst;
  assign mst_req_o.ar.lock   = slv_req_i.ar.lock;
  assign mst_req_o.ar.cache  = slv_req_i.ar.cache;
  assign mst_req_o.ar.prot   = slv_req_i.ar.prot;
  assign mst_req_o.ar.qos    = slv_req_i.ar.qos;
  assign mst_req_o.ar.region = slv_req_i.ar.region;
  assign mst_req_o.ar.user   = slv_req_i.ar.user;

  assign mst_req_o.r_ready = slv_req_i.r_ready;

  // Response path - direct passthrough
  assign slv_resp_o = mst_resp_i;

endmodule
