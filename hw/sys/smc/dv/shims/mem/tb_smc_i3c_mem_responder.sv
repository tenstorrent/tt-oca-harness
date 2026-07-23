// SPDX-License-Identifier: Apache-2.0
//
// Behavioral DAT/DCT/RLT memories for bare-smc OSS TB (I3C rebase #3934).
// Mirrors hw/oss-example/wrapper/smc/smc_ip_integration.sv gen_i3c_dat_dct_memory
// so smc.i3c_*_mem_* ports are not left floating (X) under CONTROLLER_SUPPORT=1.

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
    output dct_mem_src_t  [NUM_I3C-1:0] dct_mem_src_o,
    input  rlt_mem_sink_t [NUM_I3C-1:0] rlt_mem_sink_i,
    output rlt_mem_src_t  [NUM_I3C-1:0] rlt_mem_src_o
);

    for (genvar i3c_idx = 0; i3c_idx < NUM_I3C; i3c_idx++) begin : gen_i3c_mem
        prim_ram_1p #(
            .Depth(`DAT_DEPTH),
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
            .Depth(`DCT_DEPTH),
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

        prim_ram_2p #(
            .Depth(128),
            .Width(DatAw)
        ) u_rlt (
            .clk_a_i  (clk_i),
            .clk_b_i  (clk_i),
            .a_req_i  (rlt_mem_sink_i[i3c_idx].a_req),
            .a_write_i(rlt_mem_sink_i[i3c_idx].a_write),
            .a_addr_i (rlt_mem_sink_i[i3c_idx].a_addr),
            .a_wdata_i(rlt_mem_sink_i[i3c_idx].a_wdata),
            .a_wmask_i(rlt_mem_sink_i[i3c_idx].a_wmask),
            .a_rdata_o(rlt_mem_src_o[i3c_idx].a_rdata),
            .b_req_i  (rlt_mem_sink_i[i3c_idx].b_req),
            .b_write_i(rlt_mem_sink_i[i3c_idx].b_write),
            .b_addr_i (rlt_mem_sink_i[i3c_idx].b_addr),
            .b_wdata_i(rlt_mem_sink_i[i3c_idx].b_wdata),
            .b_wmask_i(rlt_mem_sink_i[i3c_idx].b_wmask),
            .b_rdata_o(rlt_mem_src_o[i3c_idx].b_rdata),
            .cfg_i    ('0),
            .cfg_rsp_o()
        );
    end

endmodule : tb_smc_i3c_mem_responder
