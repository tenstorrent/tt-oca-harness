// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Capture, shift, and update a JTAG scan register under scan_ctrl_i.
//
// While select is high, capture data_in_i or shift toward the LSB on the rising edge of TCK,
// and load the update register on the falling edge when update_en is high.
// LOCKUP retimes scan_out_o through a falling-edge TCK flop (lockup stage).
// The shift, update and lockup stages all reset to RESET_VAL from rst_n inside scan_ctrl_i, or
// from chrst_n when USE_CHRST is set for TMP-controlled reset.
// scan_out_o is the serial LSB of the shift flops.

module prim_jtag_scan_reg
    import prim_jtag_pkg::*;

    `include "prim_assert.sv"
#(
    parameter bit                LOCKUP = 0,  // Adds a falling-edge TCK lockup flop on scan_out_o.
                                 USE_CHRST = 0,  // Resets from chrst_n for TMP-controlled reset instead of rst_n.
    parameter int unsigned       WIDTH = 1,  // Parallel data width.
    parameter logic [WIDTH-1:0]  RESET_VAL = '0,  // Reset value of the shift and update registers.

    parameter type jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t  // Scan-control struct type.
) (
    /* verilator lint_off UNUSEDSIGNAL */
    input  jtag_scan_ctrl_t   scan_ctrl_i,  // TCK, select, capture/shift/update strobes and resets.
    /* verilator lint_on UNUSEDSIGNAL */
    input  logic              scan_in_i,  // Serial scan input; enters at the MSB.
    output logic              scan_out_o,  // Serial scan output.
    input  logic [WIDTH-1:0]  data_in_i,  // Parallel capture data.
    output logic [WIDTH-1:0]  data_out_o  // Parallel update data, held in the update register.
);

    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(WidthGtZero_A, WIDTH > 0)

    logic              capture_selected, shift_selected, update_selected;
    logic              scan_rst_n;
    logic [WIDTH-1:0]  scan_data, update_data;

    assign capture_selected = scan_ctrl_i.select && scan_ctrl_i.capture_en;
    assign shift_selected   = scan_ctrl_i.select && scan_ctrl_i.shift_en;
    assign update_selected  = scan_ctrl_i.select && scan_ctrl_i.update_en;

    if (USE_CHRST) begin : gen_chrst_n_reset
        assign scan_rst_n = scan_ctrl_i.chrst_n;
    end else begin : gen_rst_n_reset
        assign scan_rst_n = scan_ctrl_i.rst_n;
    end

    // Tie off unused signals to satisfy lint
    logic unused_scan_ctrl;
    assign unused_scan_ctrl = ^{scan_ctrl_i.runbist,
                                scan_ctrl_i.test_logic_reset,
                                scan_ctrl_i.run_test_idle,
                                scan_ctrl_i.chrst_n,
                                scan_ctrl_i.rst_n};

    // Compute the next shift value outside always_ff to avoid width issues when WIDTH=1.
    // When WIDTH=1: scan_data_shifted = scan_in_i (trivial passthrough).
    // When WIDTH>1: scan_data_shifted = {scan_in_i, scan_data[WIDTH-1:1]} (right-shift with serial-in).
    logic [WIDTH-1:0] scan_data_shifted;
    if (WIDTH > 1) begin : gen_shift_wide
        always_comb scan_data_shifted = {scan_in_i, scan_data[WIDTH-1:1]};
    end else begin : gen_shift_single
        always_comb scan_data_shifted = scan_in_i;
    end

    // Scan register
    prim_flop #(
        .Width(WIDTH),
        .ResetValue(RESET_VAL)
    ) u_scan_flop (
        .clk_i  (scan_ctrl_i.tck),
        .rst_ni (scan_rst_n),
        .d_i    (capture_selected ? data_in_i :
                 shift_selected   ? scan_data_shifted : scan_data),
        .q_o    (scan_data)
    );

    // Update register
    prim_flop #(
        .Width(WIDTH),
        .ResetValue(RESET_VAL),
        .Negedge(1'b1)
    ) u_update_flop (
        .clk_i  (scan_ctrl_i.tck),
        .rst_ni (scan_rst_n),
        .d_i    (update_selected ? scan_data : update_data),
        .q_o    (update_data)
    );

    // Output assignments
    assign data_out_o = update_data;

    if (LOCKUP) begin : gen_lockup_latch
        prim_flop #(
            .Width(1),
            .ResetValue(RESET_VAL[0]),
            .Negedge(1'b1)
        ) u_lockup_flop (
            .clk_i  (scan_ctrl_i.tck),
            .rst_ni (scan_rst_n),
            .d_i    (scan_data[0]),
            .q_o    (scan_out_o)
        );
    end else begin : gen_no_lockup_latch
        assign scan_out_o = scan_data[0];
    end

endmodule
