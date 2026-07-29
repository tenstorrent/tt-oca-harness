// SPDX-License-Identifier: Apache-2.0
//
// DAT/DCT memories for SMC OSS TB (I3C rebase #3934).
// Uses prim_ram_1p (SEP-aligned macros). RLT is obsolete on the current SMC
// boundary and is intentionally not modeled here.

`timescale 1ps/1fs

module tb_smc_i3c_mem_responder
    import i3c_pkg::*;
#(
    parameter int unsigned NUM_I3C = smc_config_pkg::NUM_I3C
) (
    input  wire logic clk_i,
    input  wire logic rst_ni,

    input  dat_mem_sink_t [NUM_I3C-1:0] dat_mem_sink_i,
    output dat_mem_src_t  [NUM_I3C-1:0] dat_mem_src_o,
    input  dct_mem_sink_t [NUM_I3C-1:0] dct_mem_sink_i,
    output dct_mem_src_t  [NUM_I3C-1:0] dct_mem_src_o
);

    // Depth follows i3c_pkg address widths (same as hw/ip/i3ccore_wrap DV TB).
    localparam int unsigned DAT_DEPTH = 1 << DatAw;
    localparam int unsigned DCT_DEPTH = 1 << DctAw;

    for (genvar i3c_idx = 0; i3c_idx < NUM_I3C; i3c_idx++) begin : gen_i3c_mem
        prim_ram_1p #(
            .Depth(DAT_DEPTH),
            .Width(64),
            .DataBitsPerMask(32)
        ) u_dat (
            .clk_i,
            .rst_ni,
            .req_i    (dat_mem_sink_i[i3c_idx].req),
            .write_i  (dat_mem_sink_i[i3c_idx].write),
            .addr_i   (dat_mem_sink_i[i3c_idx].addr),
            .wdata_i  (dat_mem_sink_i[i3c_idx].wdata),
            .wmask_i  (dat_mem_sink_i[i3c_idx].wmask),
            .rdata_o  (dat_mem_src_o[i3c_idx].rdata),
            .cfg_i    ('0),
            .cfg_rsp_o()
        );
        assign dat_mem_src_o[i3c_idx].rvalid = 1'b0;
        assign dat_mem_src_o[i3c_idx].rerror = '0;

        prim_ram_1p #(
            .Depth(DCT_DEPTH),
            .Width(128),
            .DataBitsPerMask(32)
        ) u_dct (
            .clk_i,
            .rst_ni,
            .req_i    (dct_mem_sink_i[i3c_idx].req),
            .write_i  (dct_mem_sink_i[i3c_idx].write),
            .addr_i   (dct_mem_sink_i[i3c_idx].addr),
            .wdata_i  (dct_mem_sink_i[i3c_idx].wdata),
            .wmask_i  (dct_mem_sink_i[i3c_idx].wmask),
            .rdata_o  (dct_mem_src_o[i3c_idx].rdata),
            .cfg_i    ('0),
            .cfg_rsp_o()
        );
        assign dct_mem_src_o[i3c_idx].rvalid = 1'b0;
        assign dct_mem_src_o[i3c_idx].rerror = '0;
    end

endmodule : tb_smc_i3c_mem_responder
