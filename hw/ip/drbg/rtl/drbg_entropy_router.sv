// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//----------------------------------------------------------
// Copyright 2026 Tenstorrent Inc.
// drbg_entropy_router
//
// Producer-driven entropy ingress router for the DRBG wrapper.
//----------------------------------------------------------

`default_nettype none


/**
 * @file drbg_entropy_router.sv
 * @brief Routes incoming entropy words into distribution and CSRNG FIFOs.
 *
 * @details Samples producer-driven `entropy_stream_*` inputs with no backpressure,
 *          then applies the required priority policy:
 *          1. route to the entropy-distribution FIFO when space is available
 *          2. otherwise route to the CSRNG-word FIFO when space is available
 *          3. otherwise drop the word
 *
 *          The distribution FIFO is exposed as a 32-bit AXI-Stream source, while
 *          the CSRNG FIFO is exposed as a 32-bit ready/valid stream consumed by
 *          the seed adapter.
 *
 * @param INGRESS_FIFO_DEPTH Shared depth for both ingress FIFOs.
 */
module drbg_entropy_router import drbg_pkg::*; #(
    parameter int unsigned INGRESS_FIFO_DEPTH = DRBG_DEFAULT_INGRESS_FIFO_DEPTH
) (
    input  wire logic   clk_i,
    input  wire logic   rst_ni,

    input  wire logic   entropy_stream_vld_i,
    input  wire logic [31:0] entropy_stream_data_i,

    output drbg_axis_req_t entropy_axis_o,
    input  wire drbg_axis_rsp_t entropy_axis_i,

    output logic        csrng_word_valid_o,
    output logic [31:0] csrng_word_data_o,
    input  wire logic   csrng_word_ready_i,

    output logic        distribution_accept_o,
    output logic        csrng_accept_o,
    output logic        entropy_drop_o,
    output logic        distribution_fifo_full_o,
    output logic        csrng_fifo_full_o,
    output logic [$clog2(INGRESS_FIFO_DEPTH + 1)-1:0] distribution_fifo_depth_o,
    output logic [$clog2(INGRESS_FIFO_DEPTH + 1)-1:0] csrng_fifo_depth_o
);

    `include "prim_assert.sv"

    localparam int unsigned FIFO_WIDTH = 32;

    logic        distribution_fifo_wready;
    logic [31:0] distribution_fifo_rdata;
    logic        distribution_fifo_rvalid;
    logic        distribution_fifo_err;

    logic        csrng_fifo_wready;
    logic        csrng_fifo_err;

    assign distribution_accept_o = entropy_stream_vld_i && !distribution_fifo_full_o;
    assign csrng_accept_o = entropy_stream_vld_i && distribution_fifo_full_o && !csrng_fifo_full_o;
    assign entropy_drop_o = entropy_stream_vld_i && distribution_fifo_full_o && csrng_fifo_full_o;

    prim_fifo_sync #(
        .Width            (FIFO_WIDTH),
        .Pass             (1'b0),
        .Depth            (INGRESS_FIFO_DEPTH),
        .OutputZeroIfEmpty(1'b1)
    ) u_distribution_fifo (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        .clr_i    (1'b0),
        .wvalid_i (distribution_accept_o),
        .wready_o (distribution_fifo_wready),
        .wdata_i  (entropy_stream_data_i),
        .rvalid_o (distribution_fifo_rvalid),
        .rready_i (entropy_axis_i.tready),
        .rdata_o  (distribution_fifo_rdata),
        .full_o   (distribution_fifo_full_o),
        .depth_o  (distribution_fifo_depth_o),
        .err_o    (distribution_fifo_err)
    );

    prim_fifo_sync #(
        .Width            (FIFO_WIDTH),
        .Pass             (1'b0),
        .Depth            (INGRESS_FIFO_DEPTH),
        .OutputZeroIfEmpty(1'b1)
    ) u_csrng_fifo (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        .clr_i    (1'b0),
        .wvalid_i (csrng_accept_o),
        .wready_o (csrng_fifo_wready),
        .wdata_i  (entropy_stream_data_i),
        .rvalid_o (csrng_word_valid_o),
        .rready_i (csrng_word_ready_i),
        .rdata_o  (csrng_word_data_o),
        .full_o   (csrng_fifo_full_o),
        .depth_o  (csrng_fifo_depth_o),
        .err_o    (csrng_fifo_err)
    );

    assign entropy_axis_o.tvalid = distribution_fifo_rvalid;
    assign entropy_axis_o.tdata = distribution_fifo_rdata;
    assign entropy_axis_o.tstrb = 4'hF;
    // Pre-CSRNG bypass path: whitened noise is NIST SP 800-90B conditioned but
    // not DRBG-generated. Expose FIPS=0 on this stream; a consumer that needs
    // FIPS provenance should take the post-CSRNG edn_axis_o path instead.
    assign entropy_axis_o.tuser = 1'b0;

    // =========================================================================
    // Assertions
    // =========================================================================

    `OCAH_OT_ASSERT_INIT(IngressDepthValid_A, INGRESS_FIFO_DEPTH > 0)
    `OCAH_OT_ASSERT(NoDualRoute_A, !(distribution_accept_o && csrng_accept_o))
    `OCAH_OT_ASSERT(DistributionPriority_A,
        entropy_stream_vld_i && !distribution_fifo_full_o |-> distribution_accept_o)
    `OCAH_OT_ASSERT(CsrngFallback_A,
        entropy_stream_vld_i && distribution_fifo_full_o && !csrng_fifo_full_o |-> csrng_accept_o)
    `OCAH_OT_ASSERT(DropOnlyDoubleFull_A,
        entropy_drop_o |-> entropy_stream_vld_i && distribution_fifo_full_o && csrng_fifo_full_o)
    `OCAH_OT_ASSERT(DistributionNoBackpressureAtIngress_A,
        distribution_accept_o |-> !distribution_fifo_full_o)
    `OCAH_OT_ASSERT(CsrngNoBackpressureAtIngress_A,
        csrng_accept_o |-> distribution_fifo_full_o && !csrng_fifo_full_o)

    `OCAH_OT_ASSERT_KNOWN(EntropyAxisTvalidKnown_A, entropy_axis_o.tvalid)
    `OCAH_OT_ASSERT_KNOWN_IF(EntropyAxisTdataKnown_A, entropy_axis_o.tdata, entropy_axis_o.tvalid)
    `OCAH_OT_ASSERT_KNOWN_IF(EntropyAxisTstrbKnown_A, entropy_axis_o.tstrb, entropy_axis_o.tvalid)
    `OCAH_OT_ASSERT_KNOWN(CsrngWordValidKnown_A, csrng_word_valid_o)
    `OCAH_OT_ASSERT_KNOWN_IF(CsrngWordDataKnown_A, csrng_word_data_o, csrng_word_valid_o)
    `OCAH_OT_ASSERT_KNOWN(RouteDistributionKnown_A, distribution_accept_o)
    `OCAH_OT_ASSERT_KNOWN(RouteCsrngKnown_A, csrng_accept_o)
    `OCAH_OT_ASSERT_KNOWN(RouteDropKnown_A, entropy_drop_o)
    `OCAH_OT_ASSERT_KNOWN(DistributionFullKnown_A, distribution_fifo_full_o)
    `OCAH_OT_ASSERT_KNOWN(CsrngFullKnown_A, csrng_fifo_full_o)
    `OCAH_OT_ASSERT_KNOWN(DistributionDepthKnown_A, distribution_fifo_depth_o)
    `OCAH_OT_ASSERT_KNOWN(CsrngDepthKnown_A, csrng_fifo_depth_o)
    `OCAH_OT_ASSERT(DistributionFifoHealthy_A, !distribution_fifo_err)
    `OCAH_OT_ASSERT(CsrngFifoHealthy_A, !csrng_fifo_err)

endmodule : drbg_entropy_router

`default_nettype wire
