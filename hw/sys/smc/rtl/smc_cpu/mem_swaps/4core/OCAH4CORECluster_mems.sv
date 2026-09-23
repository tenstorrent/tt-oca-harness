// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMC CPU cluster memories
//
//-----------------------------------------------------------------------------

module OCAH4CORECluster_mems #(
  parameter int MEM_CFG_WIDTH = 11
) (
  input  chipyard_4core_mem_pkg::scratch_ram_req_t    scratch_ram_req[chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0],
  output chipyard_4core_mem_pkg::scratch_ram_rsp_t    scratch_ram_rsp[chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0],
  input  chipyard_4core_mem_pkg::l1_icache_tag_req_t  l1_icache_tag_req[chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0],
  output chipyard_4core_mem_pkg::l1_icache_tag_rsp_t  l1_icache_tag_rsp[chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0],
  input  chipyard_4core_mem_pkg::l1_icache_data_req_t l1_icache_data_req[chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0],
  output chipyard_4core_mem_pkg::l1_icache_data_rsp_t l1_icache_data_rsp[chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0],
  input  chipyard_4core_mem_pkg::l1_dcache_tag_req_t  l1_dcache_tag_req[chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0],
  output chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t  l1_dcache_tag_rsp[chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0],
  input  chipyard_4core_mem_pkg::l1_dcache_data_req_t l1_dcache_data_req[chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0],
  output chipyard_4core_mem_pkg::l1_dcache_data_rsp_t l1_dcache_data_rsp[chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0],
  input  chipyard_4core_mem_pkg::rom_req_t            rom_req,
  output chipyard_4core_mem_pkg::rom_rsp_t            rom_rsp,

  input logic [MEM_CFG_WIDTH-1:0] scratch_ram_cfg_i[chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0],
  input logic [MEM_CFG_WIDTH-1:0] icache_tag_cfg_i[chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0],
  input logic [MEM_CFG_WIDTH-1:0] icache_data_cfg_i[chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0],
  input logic [MEM_CFG_WIDTH-1:0] dcache_tag_cfg_i[chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0],
  input logic [MEM_CFG_WIDTH-1:0] dcache_data_cfg_i[chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0],
  input logic [MEM_CFG_WIDTH-1:0] rom_cfg_i
);

  // ICache tags
  for (
      genvar i = 0; i < chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS; i++
  ) begin : gen_icache_tag_rams
    OCAH4CORECluster_rockettile_icache_tag_array_ext #(
      .MEM_CFG_WIDTH(MEM_CFG_WIDTH)
    ) u_icache_tag_array (
      .RW0_addr (l1_icache_tag_req[i].addr),
      .RW0_clk  (l1_icache_tag_req[i].clk),
      .RW0_wdata(l1_icache_tag_req[i].wdata),
      .RW0_rdata(l1_icache_tag_rsp[i].rdata),
      .RW0_en   (l1_icache_tag_req[i].en),
      .RW0_wmode(l1_icache_tag_req[i].wmode),
      .RW0_wmask(l1_icache_tag_req[i].wmask),

      .mem_cfg_i(icache_tag_cfg_i[i])
    );
  end

  // ICache data
  for (
      genvar i = 0; i < chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS; i++
  ) begin : gen_icache_data_rams
    OCAH4CORECluster_rockettile_icache_data_arrays_0_ext #(
      .MEM_CFG_WIDTH(MEM_CFG_WIDTH)
    ) u_icache_data_arrays (
      .RW0_addr (l1_icache_data_req[i].addr),
      .RW0_clk  (l1_icache_data_req[i].clk),
      .RW0_wdata(l1_icache_data_req[i].wdata),
      .RW0_rdata(l1_icache_data_rsp[i].rdata),
      .RW0_en   (l1_icache_data_req[i].en),
      .RW0_wmode(l1_icache_data_req[i].wmode),
      .RW0_wmask(l1_icache_data_req[i].wmask),

      .mem_cfg_i(icache_data_cfg_i[i])
    );
  end

  // DCache tag
  for (
      genvar i = 0; i < chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS; i++
  ) begin : gen_dcache_tag_rams
    OCAH4CORECluster_rockettile_dcache_tag_array_ext #(
      .MEM_CFG_WIDTH(MEM_CFG_WIDTH)
    ) u_dcache_tag_array (
      .RW0_addr (l1_dcache_tag_req[i].addr),
      .RW0_clk  (l1_dcache_tag_req[i].clk),
      .RW0_wdata(l1_dcache_tag_req[i].wdata),
      .RW0_rdata(l1_dcache_tag_rsp[i].rdata),
      .RW0_en   (l1_dcache_tag_req[i].en),
      .RW0_wmode(l1_dcache_tag_req[i].wmode),
      .RW0_wmask(l1_dcache_tag_req[i].wmask),

      .mem_cfg_i(dcache_tag_cfg_i[i])
    );
  end

  // DCache data
  for (
      genvar i = 0; i < chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS; i++
  ) begin : gen_dcache_data_rams
    OCAH4CORECluster_rockettile_dcache_data_arrays_0_ext #(
      .MEM_CFG_WIDTH(MEM_CFG_WIDTH)
    ) u_dcache_data_arrays (
      .RW0_addr (l1_dcache_data_req[i].addr),
      .RW0_clk  (l1_dcache_data_req[i].clk),
      .RW0_wdata(l1_dcache_data_req[i].wdata),
      .RW0_rdata(l1_dcache_data_rsp[i].rdata),
      .RW0_en   (l1_dcache_data_req[i].en),
      .RW0_wmode(l1_dcache_data_req[i].wmode),
      .RW0_wmask(l1_dcache_data_req[i].wmask),

      .mem_cfg_i(dcache_data_cfg_i[i])
    );
  end


  for (genvar i = 0; i < chipyard_4core_mem_pkg::NUM_SRAM_BANKS; i++) begin : gen_scratch_rams
    // Memory instantiation
    OCAH4CORECluster_mem_0_ext #(
      .MEM_CFG_WIDTH(MEM_CFG_WIDTH)
    ) u_mem (
      .RW0_addr (scratch_ram_req[i].addr),
      .RW0_clk  (scratch_ram_req[i].clk),
      .RW0_wdata(scratch_ram_req[i].wdata),
      .RW0_rdata(scratch_ram_rsp[i].rdata),
      .RW0_en   (scratch_ram_req[i].en),
      .RW0_wmode(scratch_ram_req[i].wmode),

      .mem_cfg_i(scratch_ram_cfg_i[i])
    );
  end

  // ROM
  OCAH4CORECluster_rom_ext #(
    .MEM_CFG_WIDTH(MEM_CFG_WIDTH)
  ) u_rom_mem (
    .R0_addr (rom_req.addr),
    .R0_clk  (rom_req.clk),
    .R0_rdata(rom_rsp.rdata),
    .R0_en   (rom_req.en),

    .mem_cfg_i(rom_cfg_i)
  );

endmodule
