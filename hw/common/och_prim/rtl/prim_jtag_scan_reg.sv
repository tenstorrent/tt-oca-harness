// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// JTAG Scan Register
//
//--------------------------------------------------

module prim_jtag_scan_reg
    import prim_jtag_pkg::*;

    `include "prim_assert.sv"
#(
    parameter bit                LOCKUP = 0,     // Adds a lockup latch to the output of the scan register
                                 USE_CHRST = 0,  // Use the chrst_n signal for TMP controlled reset instead of rst_n
    parameter int unsigned       WIDTH = 1,
    parameter logic [WIDTH-1:0]  RESET_VAL = '0,

    parameter type jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t
) (
    /* verilator lint_off UNUSEDSIGNAL */
    input  jtag_scan_ctrl_t   scan_ctrl_i,
    /* verilator lint_on UNUSEDSIGNAL */
    input  logic              scan_in_i,
    output logic              scan_out_o,
    input  logic [WIDTH-1:0]  data_in_i,
    output logic [WIDTH-1:0]  data_out_o
);

    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(WidthGtZero_A, WIDTH > 0)

    logic              capture_selected, shift_selected, update_selected;
    logic [WIDTH-1:0]  scan_data, update_data;

    assign capture_selected = scan_ctrl_i.select && scan_ctrl_i.capture_en;
    assign shift_selected   = scan_ctrl_i.select && scan_ctrl_i.shift_en;
    assign update_selected  = scan_ctrl_i.select && scan_ctrl_i.update_en;

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
    always_ff @(posedge scan_ctrl_i.tck) begin
        if (capture_selected) begin
            scan_data <= data_in_i;
        end else if (shift_selected) begin
            scan_data <= scan_data_shifted;
        end
    end

    // Update register
    if (USE_CHRST) begin : gen_chrst_n_reset
        prim_flop #(
            .Width(WIDTH),
            .ResetValue(RESET_VAL),
            .Negedge(1'b1)
        ) u_update_flop (
            .clk_i  (scan_ctrl_i.tck),
            .rst_ni (scan_ctrl_i.chrst_n),
            .d_i    (update_selected ? scan_data : update_data),
            .q_o    (update_data)
        );
    end else begin : gen_rst_n_reset
        prim_flop #(
            .Width(WIDTH),
            .ResetValue(RESET_VAL),
            .Negedge(1'b1)
        ) u_update_flop (
            .clk_i  (scan_ctrl_i.tck),
            .rst_ni (scan_ctrl_i.rst_n),
            .d_i    (update_selected ? scan_data : update_data),
            .q_o    (update_data)
        );
    end

    // Output assignments
    assign data_out_o = update_data;

    if (LOCKUP) begin : gen_lockup_latch
        always_ff @(negedge scan_ctrl_i.tck) begin
            scan_out_o <= scan_data[0];
        end
    end else begin : gen_no_lockup_latch
        assign scan_out_o = scan_data[0];
    end

endmodule
