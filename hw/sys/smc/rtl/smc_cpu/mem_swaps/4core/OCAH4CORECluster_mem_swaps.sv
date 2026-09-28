// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Replace Chipyard memory black boxes for the four-core cluster.
//
// Maps generated *_ext memory modules onto prim_ram_1p and prim_rom.
// MEM_CFG_WIDTH sizes the foundry config bus threaded to each macro.
// In simulation the ROM is zero-filled and then loaded from the +rom_bin64 or +rom_hex plusarg.

module OCAH4CORECluster_rockettile_dcache_data_arrays_0_ext #(
  parameter int MEM_CFG_WIDTH = 11  // Foundry memory config bus width.
) (
  input  [7:0]   RW0_addr,              // Word address of the access.
  input          RW0_clk,               // Memory clock, supplied by the cluster with the request.
  input  [143:0] RW0_wdata,             // Data stored at RW0_addr on a write access.
  output [143:0] RW0_rdata,             // Read data from RW0_addr, valid one cycle after a read.
  input          RW0_en,                // Access enable; starts a read or write in this cycle.
  input          RW0_wmode,             // Access type while RW0_en is high: 1 writes, 0 reads.
  input  [1:0]   RW0_wmask,             // Write enable per half-word; bit 1 covers the upper half
                                        // of RW0_wdata, bit 0 the lower half.

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i  // Foundry memory configuration for the RAM primitive.
);

  prim_ram_1p #(
    .Width(144),
    .Depth(256),
    .DataBitsPerMask(72)
  ) u_mem (
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

module OCAH4CORECluster_rockettile_dcache_tag_array_ext #(
  parameter int MEM_CFG_WIDTH = 11  // Foundry memory config bus width.
) (
  input  [4:0]   RW0_addr,              // Word address of the access.
  input          RW0_clk,               // Memory clock, supplied by the cluster with the request.
  input  [107:0] RW0_wdata,             // Data stored at RW0_addr on a write access.
  output [107:0] RW0_rdata,             // Read data from RW0_addr, valid one cycle after a read.
  input          RW0_en,                // Access enable; starts a read or write in this cycle.
  input          RW0_wmode,             // Access type while RW0_en is high: 1 writes, 0 reads.
  input  [1:0]   RW0_wmask,             // Write enable per half-word; bit 1 covers the upper half
                                        // of RW0_wdata, bit 0 the lower half.

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i  // Foundry memory configuration for the RAM primitive.
);

  prim_ram_1p #(
    .Width(108),
    .Depth(32),
    .DataBitsPerMask(54)
  ) u_mem (
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

module OCAH4CORECluster_rockettile_icache_tag_array_ext #(
  parameter int MEM_CFG_WIDTH = 11  // Foundry memory config bus width.
) (
  input  [4:0]   RW0_addr,              // Word address of the access.
  input          RW0_clk,               // Memory clock, supplied by the cluster with the request.
  input  [93:0]  RW0_wdata,             // Data stored at RW0_addr on a write access.
  output [93:0]  RW0_rdata,             // Read data from RW0_addr, valid one cycle after a read.
  input          RW0_en,                // Access enable; starts a read or write in this cycle.
  input          RW0_wmode,             // Access type while RW0_en is high: 1 writes, 0 reads.
  input  [1:0]   RW0_wmask,             // Write enable per half-word; bit 1 covers the upper half
                                        // of RW0_wdata, bit 0 the lower half.

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i  // Foundry memory configuration for the RAM primitive.
);

  prim_ram_1p #(
    .Width(94),
    .Depth(32),
    .DataBitsPerMask(47)
  ) u_mem (
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

module OCAH4CORECluster_rockettile_icache_data_arrays_0_ext #(
  parameter int MEM_CFG_WIDTH = 11  // Foundry memory config bus width.
) (
  input  [7:0]  RW0_addr,               // Word address of the access.
  input         RW0_clk,                // Memory clock, supplied by the cluster with the request.
  input  [65:0] RW0_wdata,              // Data stored at RW0_addr on a write access.
  output [65:0] RW0_rdata,              // Read data from RW0_addr, valid one cycle after a read.
  input         RW0_en,                 // Access enable; starts a read or write in this cycle.
  input         RW0_wmode,              // Access type while RW0_en is high: 1 writes, 0 reads.
  input  [1:0]  RW0_wmask,              // Write enable per half-word; bit 1 covers the upper half
                                        // of RW0_wdata, bit 0 the lower half.

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i  // Foundry memory configuration for the RAM primitive.
);

  prim_ram_1p #(
    .Width(66),
    .Depth(256),
    .DataBitsPerMask(33)
  ) u_mem (
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

module OCAH4CORECluster_mem_0_ext #(
  parameter int MEM_CFG_WIDTH = 11  // Foundry memory config bus width.
) (
  input  [11:0] RW0_addr,               // Word address of the access.
  input         RW0_clk,                // Memory clock, supplied by the cluster with the request.
  input  [71:0] RW0_wdata,              // Data stored at RW0_addr on a write access.
  output [71:0] RW0_rdata,              // Read data from RW0_addr, valid one cycle after a read.
  input         RW0_en,                 // Access enable; starts a read or write in this cycle.
  input         RW0_wmode,              // Access type while RW0_en is high: 1 writes, 0 reads.

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i  // Foundry memory configuration for the RAM primitive.
);

  prim_ram_1p #(
    .Width(72),
    .Depth(4096),
    .DataBitsPerMask(72)
  ) u_mem (
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

module OCAH4CORECluster_rom_ext #(
  parameter int MEM_CFG_WIDTH = 11  // Foundry memory config bus width.
) (
  input  [13:0] R0_addr,                // Word address of the read access.
  input         R0_clk,                 // ROM clock, supplied by the cluster with the request.
  input         R0_en,                  // Read enable; starts a read of R0_addr in this cycle.
  output [63:0] R0_rdata,               // Read data from R0_addr, valid one cycle after a read.

  input  [MEM_CFG_WIDTH-1:0] mem_cfg_i  // Foundry memory configuration for the ROM primitive.
);

  prim_rom #(
    .Width(64),
    .Depth(16384),
    .MemInitFile("")
  ) u_mem (
    .clk_i(R0_clk),
    .rst_ni(1'b1),  // unused
    .req_i(R0_en),
    .addr_i(R0_addr),
    .rdata_o(R0_rdata),
    .cfg_i(prim_rom_pkg::rom_cfg_t'(mem_cfg_i))
  );

`ifdef SIMULATION
  // Load ROM from +rom_bin64 or +rom_hex plusarg (set by YAML test configs)
  // Priority: rom_bin64 (binary format) > rom_hex (hexadecimal format)
  // Note: For ROM tests, the file may be generated by cocotb after simulation starts,
  // so we wait a short time before trying to read it (matching reference behavior).
  initial begin
    string rom_mem_path;
    int file_handle;
    int file_loaded = 0;

    // Wait a short time to allow cocotb to generate the ROM file (matching reference)
    $display("INFO: [OCAH4CORECluster_rom_ext] Waiting for ROM file generation...");
    #0.1;
    $display("INFO: [OCAH4CORECluster_rom_ext] Waiting complete, attempting to load ROM");

    // Zero-fill entire ROM before loading firmware image.
    // $readmemb/$readmemh only populate entries covered by the file;
    // remaining entries stay X and cause X-propagation when the ICache
    // speculatively fetches beyond the loaded firmware range.
    for (int i = 0; i < 16384; i++) begin
      u_mem.mem[i] = '0;
    end

    // Check for rom_bin64 first (binary format, 64-bit-per-line)
    if ($value$plusargs("rom_bin64=%s", rom_mem_path)) begin
      $display("INFO: [OCAH4CORECluster_rom_ext] Loading ROM from +rom_bin64 plusarg: %s",
               rom_mem_path);

      // Check if file exists before trying to load
      file_handle = $fopen(rom_mem_path, "r");
      if (file_handle) begin
        $fclose(file_handle);
        $readmemb(rom_mem_path, u_mem.mem);
        file_loaded = 1;
        $display("INFO: [OCAH4CORECluster_rom_ext] Successfully loaded ROM from bin64 file: %s",
                 rom_mem_path);
      end else begin
        $error("ERROR: [OCAH4CORECluster_rom_ext] ROM file not found: %s", rom_mem_path);
      end
      // Fall back to rom_hex (hexadecimal format)
    end else if ($value$plusargs("rom_hex=%s", rom_mem_path)) begin
      $display("INFO: [OCAH4CORECluster_rom_ext] Loading ROM from +rom_hex plusarg: %s",
               rom_mem_path);

      // Check if file exists before trying to load
      file_handle = $fopen(rom_mem_path, "r");
      if (file_handle) begin
        $fclose(file_handle);
        $readmemh(rom_mem_path, u_mem.mem);
        file_loaded = 1;
        $display("INFO: [OCAH4CORECluster_rom_ext] Successfully loaded ROM from hex file: %s",
                 rom_mem_path);
      end else begin
        $error("ERROR: [OCAH4CORECluster_rom_ext] ROM file not found: %s", rom_mem_path);
      end
    end else begin
      $error(
          "ERROR: [OCAH4CORECluster_rom_ext] No +rom_bin64 or +rom_hex plusarg provided - ROM will contain X's");
    end

    if (!file_loaded) begin
      $error("ERROR: [OCAH4CORECluster_rom_ext] Failed to load ROM file - ROM will contain X's");
    end

  end

`endif

endmodule
