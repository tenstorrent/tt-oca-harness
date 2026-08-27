// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMC I3C DAT/DCT/RLT memory integration -- OSS reference macros
//
// smc.sv / smu.sv export the I3C controller's three table memories as macro
// interfaces rather than instantiating them, so an adopter can drop in vendor
// SRAMs. This module is the open-source reference integration for those three,
// built from the same OpenTitan prim_ram_* macros the rest of hw/top uses:
//
//   DAT  Device Address Table              64 b x 2**DatAw, single port
//   DCT  Device Characteristic Table      128 b x 2**DctAw, single port
//   RLT  dynamic address -> DAT index      DatAw b x 128,   dual port
//
// Sizing and the DataBitsPerMask=32 write granularity mirror the I3C core's own
// bring-up testbench (hw/ip/i3ccore_wrap/dv/tb/tb_i3ccore.sv), which drives the
// identical interface. Depths come from i3c_pkg's own address widths so the
// arrays can never be narrower than the address the core presents; RLT's depth
// is fixed at 128 by the core (one entry per 7-bit I3C address, see
// vendor/chipsalliance/i3c-core/upstream/src/ctrl/flow_active.sv).
//
// Clocking: these sit in the gated I3C peripheral clock domain
// (smc_peripherals.sv `gated_clk_periph_i3c`, exported as
// gated_clk_periph_i3c_o), NOT clk_smc. The core reads combinationally one
// cycle after asserting req, which is exactly prim_ram_*'s latency.
//
// rvalid/rerror are outputs of the macro interface that the vendored I3C core
// never reads (only .rdata is consumed -- see hci/dxt.sv and ctrl/flow_active.sv).
// They are still driven honestly here (rvalid = read acknowledged last cycle,
// rerror = no ECC in this reference macro) rather than tied to zero, so a
// waveform or a future consumer sees a truthful interface.
//
// This is a reference integration example, provided for adopters to substitute
// with their own vendor IP/macros.
//-----------------------------------------------------------------------------

module smc_i3c_mem_integration #(
    parameter int unsigned NumI3c = smc_config_pkg::NUM_I3C
) (
    // Gated I3C peripheral clock + peripheral-domain reset (same domain as
    // i3ccore_wrapper inside smc.sv / smu.sv).
    input logic clk_i,
    input logic rst_ni,

    output i3c_pkg::dat_mem_src_t  [NumI3c-1:0] dat_mem_src_o,
    input  i3c_pkg::dat_mem_sink_t [NumI3c-1:0] dat_mem_sink_i,

    output i3c_pkg::dct_mem_src_t  [NumI3c-1:0] dct_mem_src_o,
    input  i3c_pkg::dct_mem_sink_t [NumI3c-1:0] dct_mem_sink_i,

    output i3c_pkg::rlt_mem_src_t  [NumI3c-1:0] rlt_mem_src_o,
    input  i3c_pkg::rlt_mem_sink_t [NumI3c-1:0] rlt_mem_sink_i
);

    // Address widths are the core's; depths follow from them so the arrays
    // always cover every address the core can present.
    localparam int unsigned DatDepth = 1 << i3c_pkg::DatAw;
    localparam int unsigned DctDepth = 1 << i3c_pkg::DctAw;
    // Fixed by the core: RLT is indexed by the 7-bit dynamic address.
    localparam int unsigned RltDepth = 128;
    localparam int unsigned RltWidth = i3c_pkg::DatAw;

    // CSR writes reach DAT/DCT one 32-bit word at a time, so the macros need
    // 32-bit write granularity (dxt.sv builds {32{1'b1}}/{32{1'b0}} masks).
    localparam int unsigned MaskGranularity = 32;

    for (genvar i = 0; i < NumI3c; i++) begin : gen_i3c_mem

        ///////////
        // DAT   //
        ///////////

        logic dat_rvalid_q;

        prim_ram_1p #(
            .Width           (64),
            .Depth           (DatDepth),
            .DataBitsPerMask (MaskGranularity)
        ) u_dat_mem (
            .clk_i     (clk_i),
            .rst_ni    (rst_ni),
            .req_i     (dat_mem_sink_i[i].req),
            .write_i   (dat_mem_sink_i[i].write),
            .addr_i    (dat_mem_sink_i[i].addr),
            .wdata_i   (dat_mem_sink_i[i].wdata),
            .wmask_i   (dat_mem_sink_i[i].wmask),
            .rdata_o   (dat_mem_src_o[i].rdata),
            .cfg_i     ('0),
            .cfg_rsp_o ()
        );

        always_ff @(posedge clk_i or negedge rst_ni) begin
            if (!rst_ni) begin
                dat_rvalid_q <= 1'b0;
            end else begin
                dat_rvalid_q <= dat_mem_sink_i[i].req & ~dat_mem_sink_i[i].write;
            end
        end

        assign dat_mem_src_o[i].rvalid = dat_rvalid_q;
        assign dat_mem_src_o[i].rerror = '0;

        ///////////
        // DCT   //
        ///////////

        logic dct_rvalid_q;

        prim_ram_1p #(
            .Width           (128),
            .Depth           (DctDepth),
            .DataBitsPerMask (MaskGranularity)
        ) u_dct_mem (
            .clk_i     (clk_i),
            .rst_ni    (rst_ni),
            .req_i     (dct_mem_sink_i[i].req),
            .write_i   (dct_mem_sink_i[i].write),
            .addr_i    (dct_mem_sink_i[i].addr),
            .wdata_i   (dct_mem_sink_i[i].wdata),
            .wmask_i   (dct_mem_sink_i[i].wmask),
            .rdata_o   (dct_mem_src_o[i].rdata),
            .cfg_i     ('0),
            .cfg_rsp_o ()
        );

        always_ff @(posedge clk_i or negedge rst_ni) begin
            if (!rst_ni) begin
                dct_rvalid_q <= 1'b0;
            end else begin
                dct_rvalid_q <= dct_mem_sink_i[i].req & ~dct_mem_sink_i[i].write;
            end
        end

        assign dct_mem_src_o[i].rvalid = dct_rvalid_q;
        assign dct_mem_src_o[i].rerror = '0;

        ///////////
        // RLT   //
        ///////////

        // Port A is write-only (ENTDAA installs dynamic address -> DAT index),
        // port B is read-only (reverse lookup). Both live on the same clock.
        prim_ram_2p #(
            .Width           (RltWidth),
            .Depth           (RltDepth),
            .DataBitsPerMask (1)
        ) u_rlt_mem (
            .clk_a_i   (clk_i),
            .clk_b_i   (clk_i),

            .a_req_i   (rlt_mem_sink_i[i].a_req),
            .a_write_i (rlt_mem_sink_i[i].a_write),
            .a_addr_i  (rlt_mem_sink_i[i].a_addr),
            .a_wdata_i (rlt_mem_sink_i[i].a_wdata),
            .a_wmask_i (rlt_mem_sink_i[i].a_wmask),
            .a_rdata_o (rlt_mem_src_o[i].a_rdata),

            .b_req_i   (rlt_mem_sink_i[i].b_req),
            .b_write_i (rlt_mem_sink_i[i].b_write),
            .b_addr_i  (rlt_mem_sink_i[i].b_addr),
            .b_wdata_i (rlt_mem_sink_i[i].b_wdata),
            .b_wmask_i (rlt_mem_sink_i[i].b_wmask),
            .b_rdata_o (rlt_mem_src_o[i].b_rdata),

            .cfg_i     ('0),
            .cfg_rsp_o ()
        );

    end : gen_i3c_mem

endmodule
