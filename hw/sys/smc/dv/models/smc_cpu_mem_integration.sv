// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMC CPU memory integration -- OSS reference macros for the CPU memories
//
// Absorbs the Chipyard CPU ROM / scratch / L1$ ports using the same prim_rom /
// prim_ram_1p macros as SEP (via OCAH4CORECluster_mems / mem_swaps). This is
// the macro set only: no counters, no fault injection, no image loading. All
// DV behaviour lives outside it -- see smc_cpu_mem_dv.sv, which the testbench
// instantiates alongside this module.
//
// Instantiated by the SMC and SMU testbenches on the wrapper passthrough
// ports; an adopter replaces it with their own vendor macros.
//-----------------------------------------------------------------------------

`timescale 1ps/1fs

module smc_cpu_mem_integration
    import chipyard_4core_mem_pkg::*;
(
    input  rom_req_t            rom_req_i,
    output rom_rsp_t            rom_rsp_o,

    input  scratch_ram_req_t    scratch_ram_req_i     [NUM_SRAM_BANKS-1:0],
    output scratch_ram_rsp_t    scratch_ram_rsp_o     [NUM_SRAM_BANKS-1:0],

    input  l1_icache_tag_req_t  l1_icache_tag_req_i   [NUM_ICACHE_TAG_BANKS-1:0],
    output l1_icache_tag_rsp_t  l1_icache_tag_rsp_o   [NUM_ICACHE_TAG_BANKS-1:0],

    input  l1_icache_data_req_t l1_icache_data_req_i  [NUM_ICACHE_DATA_BANKS-1:0],
    output l1_icache_data_rsp_t l1_icache_data_rsp_o  [NUM_ICACHE_DATA_BANKS-1:0],

    input  l1_dcache_tag_req_t  l1_dcache_tag_req_i   [NUM_DCACHE_TAG_BANKS-1:0],
    output l1_dcache_tag_rsp_t  l1_dcache_tag_rsp_o   [NUM_DCACHE_TAG_BANKS-1:0],

    input  l1_dcache_data_req_t l1_dcache_data_req_i  [NUM_DCACHE_DATA_BANKS-1:0],
    output l1_dcache_data_rsp_t l1_dcache_data_rsp_o  [NUM_DCACHE_DATA_BANKS-1:0]
);

    localparam int unsigned MEM_CFG_WIDTH = 11;

    logic [MEM_CFG_WIDTH-1:0] scratch_ram_cfg [NUM_SRAM_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] icache_tag_cfg  [NUM_ICACHE_TAG_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] icache_data_cfg [NUM_ICACHE_DATA_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] dcache_tag_cfg  [NUM_DCACHE_TAG_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] dcache_data_cfg [NUM_DCACHE_DATA_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] rom_cfg;

    // Unused cfg pins (match mem_swaps defaults).
    for (genvar i = 0; i < NUM_SRAM_BANKS; i++) begin : gen_scratch_cfg
        assign scratch_ram_cfg[i] = '0;
    end
    for (genvar i = 0; i < NUM_ICACHE_TAG_BANKS; i++) begin : gen_itag_cfg
        assign icache_tag_cfg[i] = '0;
    end
    for (genvar i = 0; i < NUM_ICACHE_DATA_BANKS; i++) begin : gen_idata_cfg
        assign icache_data_cfg[i] = '0;
    end
    for (genvar i = 0; i < NUM_DCACHE_TAG_BANKS; i++) begin : gen_dtag_cfg
        assign dcache_tag_cfg[i] = '0;
    end
    for (genvar i = 0; i < NUM_DCACHE_DATA_BANKS; i++) begin : gen_ddata_cfg
        assign dcache_data_cfg[i] = '0;
    end
    assign rom_cfg = '0;

    // ------------------------------------------------------------------
    // SEP-aligned macros: prim_rom / prim_ram_1p via Chipyard mems wrapper
    // ------------------------------------------------------------------
    OCAH4CORECluster_mems #(
        .MEM_CFG_WIDTH (MEM_CFG_WIDTH)
    ) u_mems (
        .scratch_ram_req   (scratch_ram_req_i),
        .scratch_ram_rsp   (scratch_ram_rsp_o),
        .l1_icache_tag_req (l1_icache_tag_req_i),
        .l1_icache_tag_rsp (l1_icache_tag_rsp_o),
        .l1_icache_data_req(l1_icache_data_req_i),
        .l1_icache_data_rsp(l1_icache_data_rsp_o),
        .l1_dcache_tag_req (l1_dcache_tag_req_i),
        .l1_dcache_tag_rsp (l1_dcache_tag_rsp_o),
        .l1_dcache_data_req(l1_dcache_data_req_i),
        .l1_dcache_data_rsp(l1_dcache_data_rsp_o),
        .rom_req           (rom_req_i),
        .rom_rsp           (rom_rsp_o),
        .scratch_ram_cfg_i (scratch_ram_cfg),
        .icache_tag_cfg_i  (icache_tag_cfg),
        .icache_data_cfg_i (icache_data_cfg),
        .dcache_tag_cfg_i  (dcache_tag_cfg),
        .dcache_data_cfg_i (dcache_data_cfg),
        .rom_cfg_i         (rom_cfg)
    );

endmodule
