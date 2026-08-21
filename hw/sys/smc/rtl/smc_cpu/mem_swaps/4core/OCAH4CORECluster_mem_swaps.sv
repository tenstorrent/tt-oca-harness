// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module OCAH4CORECluster_rockettile_dcache_data_arrays_0_ext
#(
  parameter int MEM_CFG_WIDTH = 11
)(
  input  [7:0]   RW0_addr,
  input          RW0_clk,
  input  [143:0] RW0_wdata,
  output [143:0] RW0_rdata,
  input          RW0_en,
  input          RW0_wmode,
  input  [1:0]   RW0_wmask,

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i
);

  prim_ram_1p #(
    .Width(144),
    .Depth(256),
    .DataBitsPerMask(72)
  ) mem (
    .clk_i(RW0_clk),
    .rst_ni(1'b1),  // unused

    .req_i(RW0_en),
    .write_i(RW0_wmode),
    .addr_i(RW0_addr),
    .wdata_i(RW0_wdata),
    .wmask_i({{72{RW0_wmask[1]}}, {72{RW0_wmask[0]}}}),
    .rdata_o(RW0_rdata),

    .cfg_i(prim_ram_1p_pkg::ram_1p_cfg_t'(mem_cfg_i)),
    .cfg_rsp_o()  // unused
  );

endmodule

module OCAH4CORECluster_rockettile_dcache_tag_array_ext
#(
  parameter int MEM_CFG_WIDTH = 11
)(
  input  [4:0]   RW0_addr,
  input          RW0_clk,
  input  [107:0] RW0_wdata,
  output [107:0] RW0_rdata,
  input          RW0_en,
  input          RW0_wmode,
  input  [1:0]   RW0_wmask,

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i
);

  prim_ram_1p #(
    .Width(108),
    .Depth(32),
    .DataBitsPerMask(54)
  ) mem (
    .clk_i(RW0_clk),
    .rst_ni(1'b1),  // unused

    .req_i(RW0_en),
    .write_i(RW0_wmode),
    .addr_i(RW0_addr),
    .wdata_i(RW0_wdata),
    .wmask_i({{54{RW0_wmask[1]}}, {54{RW0_wmask[0]}}}),
    .rdata_o(RW0_rdata),

    .cfg_i(prim_ram_1p_pkg::ram_1p_cfg_t'(mem_cfg_i)),
    .cfg_rsp_o()  // unused
  );

endmodule

module OCAH4CORECluster_rockettile_icache_tag_array_ext
#(
  parameter int MEM_CFG_WIDTH = 11
)(
  input  [4:0]   RW0_addr,
  input          RW0_clk,
  input  [93:0]  RW0_wdata,
  output [93:0]  RW0_rdata,
  input          RW0_en,
  input          RW0_wmode,
  input  [1:0]   RW0_wmask,

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i
);

  prim_ram_1p #(
    .Width(94),
    .Depth(32),
    .DataBitsPerMask(47)
  ) mem (
    .clk_i(RW0_clk),
    .rst_ni(1'b1),  // unused

    .req_i(RW0_en),
    .write_i(RW0_wmode),
    .addr_i(RW0_addr),
    .wdata_i(RW0_wdata),
    .wmask_i({{47{RW0_wmask[1]}}, {47{RW0_wmask[0]}}}),
    .rdata_o(RW0_rdata),

    .cfg_i(prim_ram_1p_pkg::ram_1p_cfg_t'(mem_cfg_i)),
    .cfg_rsp_o()  // unused
  );

endmodule

module OCAH4CORECluster_rockettile_icache_data_arrays_0_ext
#(
  parameter int MEM_CFG_WIDTH = 11
)(
  input  [7:0]  RW0_addr,
  input         RW0_clk,
  input  [65:0] RW0_wdata,
  output [65:0] RW0_rdata,
  input         RW0_en,
  input         RW0_wmode,
  input  [1:0]  RW0_wmask,

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i
);

  prim_ram_1p #(
    .Width(66),
    .Depth(256),
    .DataBitsPerMask(33)
  ) mem (
    .clk_i(RW0_clk),
    .rst_ni(1'b1),  // unused

    .req_i(RW0_en),
    .write_i(RW0_wmode),
    .addr_i(RW0_addr),
    .wdata_i(RW0_wdata),
    .wmask_i({{33{RW0_wmask[1]}}, {33{RW0_wmask[0]}}}),
    .rdata_o(RW0_rdata),

    .cfg_i(prim_ram_1p_pkg::ram_1p_cfg_t'(mem_cfg_i)),
    .cfg_rsp_o()  // unused
  );

endmodule

module OCAH4CORECluster_mem_0_ext
#(
  parameter int MEM_CFG_WIDTH = 11
)(
  input  [11:0] RW0_addr,
  input         RW0_clk,
  input  [71:0] RW0_wdata,
  output [71:0] RW0_rdata,
  input         RW0_en,
  input         RW0_wmode,

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i
);

  prim_ram_1p #(
    .Width(72),
    .Depth(4096),
    .DataBitsPerMask(72)
  ) mem (
    .clk_i(RW0_clk),
    .rst_ni(1'b1),  // unused

    .req_i(RW0_en),
    .write_i(RW0_wmode),
    .addr_i(RW0_addr),
    .wdata_i(RW0_wdata),
    .wmask_i({72{1'b1}}),  // No wmask input, enable all bits
    .rdata_o(RW0_rdata),

    .cfg_i(prim_ram_1p_pkg::ram_1p_cfg_t'(mem_cfg_i)),
    .cfg_rsp_o()  // unused
  );

endmodule

module OCAH4CORECluster_rom_ext
#(
  parameter int MEM_CFG_WIDTH = 11
)(
  input  [13:0] R0_addr,
  input         R0_clk,
  input         R0_en,
  output [63:0] R0_rdata,

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i
);

`ifdef SIMULATION
  prim_rom #(
    .Width(64),
    .Depth(16384),
    .MemInitFile("")  // Empty - will load via plusarg or fallback path
  ) mem (
    .clk_i(R0_clk),
    .rst_ni(1'b1),  // unused
    .req_i(R0_en),
    .addr_i(R0_addr),
    .rdata_o(R0_rdata),
    .cfg_i(prim_rom_pkg::rom_cfg_t'(mem_cfg_i))
  );

  // Unloaded words stay 0 so ICache speculative fetches past the image do not
  // see X. smc_cpu_mem_integration may overlay +smc_rom_hex / +rom_hex after this.
  initial begin
    string rom_mem_path;
    int    file_handle;

    for (int i = 0; i < 16384; i++) begin
      mem.mem[i] = '0;
    end

    if ($value$plusargs("rom_bin64=%s", rom_mem_path)) begin
      file_handle = $fopen(rom_mem_path, "r");
      if (file_handle) begin
        $fclose(file_handle);
        $readmemb(rom_mem_path, mem.mem);
      end
    end else if ($value$plusargs("rom_hex=%s", rom_mem_path)) begin
      file_handle = $fopen(rom_mem_path, "r");
      if (file_handle) begin
        $fclose(file_handle);
        $readmemh(rom_mem_path, mem.mem);
      end
    end
  end

`else

  prim_rom #(
    .Width(64),
    .Depth(16384),
    .MemInitFile("")  // Synthesis: no file loading
  ) mem (
    .clk_i(R0_clk),
    .rst_ni(1'b1),  // unused
    .req_i(R0_en),
    .addr_i(R0_addr),
    .rdata_o(R0_rdata),
    .cfg_i(prim_rom_pkg::rom_cfg_t'(mem_cfg_i))
  );

`endif

endmodule