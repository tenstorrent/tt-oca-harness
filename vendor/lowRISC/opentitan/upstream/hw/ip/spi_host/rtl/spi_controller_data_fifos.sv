//-----------------------------------------------------------------------------
// SPI Controller Data FIFOs
//
// Copyright 2025 Tenstorrent Inc.
//-----------------------------------------------------------------------------

// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0
//
// Module for SPI_HOST RX and TX queues
//

module spi_controller_data_fifos #(
    parameter int   TxDepth   = 72,
    parameter int   RxDepth   = 64,
    parameter logic SwapBytes = 0
) (
    input  logic        clk_i,
    input  logic        rst_ni,

    input  logic [31:0] tx_data_i,
    input  logic [3:0]  tx_be_i,
    input  logic        tx_valid_i,
    output logic        tx_ready_o,
    input  logic [7:0]  tx_watermark_i,

    output logic [31:0] core_tx_data_o,
    output logic [3:0]  core_tx_be_o,
    output logic        core_tx_valid_o,
    input  logic        core_tx_ready_i,
    input  logic        core_tx_byte_select_full_i,

    input  logic [31:0] core_rx_data_i,
    input  logic        core_rx_valid_i,
    output logic        core_rx_ready_o,

    output logic [31:0] rx_data_o,
    output logic        rx_valid_o,
    input  logic        rx_ready_i,
    input  logic [7:0]  rx_watermark_i,

    input  logic        sw_rst_i,

    output logic        tx_empty_o,
    output logic        tx_full_o,
    output logic [7:0]  tx_qd_o,
    output logic        tx_wm_o,
    output logic        rx_empty_o,
    output logic        rx_full_o,
    output logic [7:0]  rx_qd_o,
    output logic        rx_wm_o
);

    localparam int RxDepthW = prim_util_pkg::vbits(RxDepth+1);
    localparam int TxDepthW = prim_util_pkg::vbits(TxDepth+1);

    logic [31:0] tx_data_ordered;
    logic [3:0]  tx_be_ordered;
    logic [31:0] rx_data_unordered;

    if (SwapBytes) begin : gen_swap
        assign tx_data_ordered = { << 8 {tx_data_i} };
        assign tx_be_ordered   = { << { tx_be_i} };
        assign rx_data_o       = { << 8 { rx_data_unordered } };
    end else begin : gen_do_not_swap
        assign tx_data_ordered = tx_data_i;
        assign tx_be_ordered   = tx_be_i;
        assign rx_data_o       = rx_data_unordered;
    end

    logic [35:0]         tx_data_be;
    logic [35:0]         core_tx_data_be;

    logic [TxDepthW-1:0] tx_depth;

    // The byte_select module greedily pops data from the TX FIFO, so
    // the FIFO should be observed as having an effective depth of N+1.
    assign tx_qd_o = 8'(tx_depth) + {7'b0, core_tx_byte_select_full_i};

    assign tx_data_be = {tx_data_ordered, tx_be_ordered};
    assign {core_tx_data_o, core_tx_be_o} = core_tx_data_be;

    prim_fifo_sync #(
        .Width    (36),
        .Pass     (1'b1),
        .Depth    (TxDepth)
    ) tx_fifo (
        .clk_i,
        .rst_ni,
        .clr_i    (sw_rst_i),
        .wvalid_i (tx_valid_i),
        .wready_o (tx_ready_o),
        .wdata_i  (tx_data_be),
        .rvalid_o (core_tx_valid_o),
        .rready_i (core_tx_ready_i),
        .rdata_o  (core_tx_data_be),
        .full_o   (/* UNUSED */),
        .depth_o  (tx_depth),
        .err_o    (/* UNUSED */)
    );

    logic [RxDepthW-1:0] rx_depth;

    assign rx_qd_o = 8'(rx_depth);

    prim_fifo_sync #(
        .Width    (32),
        .Pass     (1'b1),
        .Depth    (RxDepth)
    ) rx_fifo (
        .clk_i,
        .rst_ni,
        .clr_i    (sw_rst_i),
        .wvalid_i (core_rx_valid_i),
        .wready_o (core_rx_ready_o),
        .wdata_i  (core_rx_data_i),
        .rvalid_o (rx_valid_o),
        .rready_i (rx_ready_i),
        .rdata_o  (rx_data_unordered),
        .full_o   (/* UNUSED */),
        .depth_o  (rx_depth),
        .err_o    (/* UNUSED */)
    );

    // Create the status outputs
    // - Include the 1-word storage in byte_select for the TX datapath
    assign tx_empty_o = tx_qd_o == 8'd0;
    assign rx_empty_o = rx_qd_o == 8'd0;
    assign tx_full_o  = tx_qd_o >= 8'(TxDepth) + 1; // inc. byte_sel
    assign rx_full_o  = rx_qd_o >= 8'(RxDepth);
    assign tx_wm_o    = tx_qd_o <  tx_watermark_i;
    assign rx_wm_o    = rx_qd_o >= rx_watermark_i;

    // Due to the addition of the byte_sel as a N+1'th fifo stage, ensure
    // we have adequate resolution in our counter (tx_qd_o) to represent this.
    `OCAH_OT_ASSERT_INIT(TxDepth_A, TxDepth < 2 ** $size(tx_qd_o) - 1)

endmodule
