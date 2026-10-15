// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Count up or down with saturation, clear, set, and commit.
//
// RESET_VALUE can be nonzero so a down-counter need not start at 0.
// incr_en_i and decr_en_i together do not count; either alone steps by step_i.
// clear_i takes priority over set_i, which takes priority over counting.
// commit_i freezes cnt_after_commit_o into count_o; without it the next value stays
// speculative, so clear_i and set_i also take effect only with commit_i.

`include "ocah_registers.svh"

module prim_updown_counter #(
  parameter int               WIDTH       = 16,  // Counter width.
  parameter logic [WIDTH-1:0] RESET_VALUE = '0,  // Value loaded on reset or clear_i;
                                                 // may be nonzero when the counter is used
                                                 // as a down-counter.

  localparam type ctr_t = logic [WIDTH-1:0]  // Counter type alias.
) (
  input        clk_i,  // Counter clock.
  input        rst_ni,  // Active-low reset, sampled synchronously; loads RESET_VALUE.
  input        clear_i,  // Loads RESET_VALUE when committed.
  input        set_i,  // Loads set_cnt_i when committed.
  input  ctr_t set_cnt_i,  // Value loaded when set_i is high.
  input        incr_en_i,  // Counts up by step_i.
  input        decr_en_i,  // Counts down by step_i.
  input  ctr_t step_i,  // Increment or decrement step when enabled.
  input        commit_i,  // Commits the pending next value.
  output ctr_t count_o,  // Current committed counter state.
  output ctr_t cnt_after_commit_o,  // Next counter state if commit_i is taken.
  output logic err_o  // Hardening error output; tied to 0.
);

  ///////////////////
  // Counter logic //
  ///////////////////

  logic [WIDTH-1:0] cnt_d, cnt_d_committed, cnt_q;

  // Main counter logic
  logic [WIDTH:0] ext_cnt;
  assign ext_cnt = (decr_en_i) ? {1'b0, cnt_q} - {1'b0, step_i} :
    (incr_en_i) ? {1'b0, cnt_q} + {1'b0, step_i} : {1'b0, cnt_q};

  // Saturation logic
  logic uflow, oflow;
  assign oflow = incr_en_i && ext_cnt[WIDTH];
  assign uflow = decr_en_i && ext_cnt[WIDTH];
  ctr_t cnt_sat;
  assign cnt_sat = (uflow) ? '0 : (oflow) ? {WIDTH{1'b1}} : ext_cnt[WIDTH-1:0];

  // Clock gate flops when in saturation, and do not
  // count if both incr_en_i and decr_en_i are asserted.
  logic cnt_en;
  assign cnt_en = (incr_en_i ^ decr_en_i) &&
    ((incr_en_i && !(&cnt_q)) ||
      (decr_en_i && !(cnt_q == '0)));

  // Counter muxes
  assign cnt_d = clear_i ? RESET_VALUE : (set_i) ? set_cnt_i : (cnt_en) ? cnt_sat : cnt_q;

  assign cnt_d_committed = commit_i ? cnt_d : cnt_q;

  logic [WIDTH-1:0] cnt_unforced_q;
  `OCAH_FFSRN(cnt_unforced_q, cnt_d_committed, RESET_VALUE, clk_i, rst_ni)

  assign cnt_q = cnt_unforced_q;

  assign err_o              = 1'b0;

  // Output count values
  assign count_o            = cnt_q;
  assign cnt_after_commit_o = cnt_d;



endmodule
