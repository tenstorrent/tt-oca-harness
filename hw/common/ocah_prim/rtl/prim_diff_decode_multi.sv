// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Decode Width differential pairs into single-ended data_o.
//
// Pack data_i as {diff_n[W-1:0], diff_p[W-1:0]}; matching levels assert a per-bit integrity
// fault.
// OR every per-bit integrity fault onto sigint_o.
// AsyncOn inserts synchronizers on the differential inputs into clk_i.

module prim_diff_decode_multi #(
  parameter int unsigned Width = 4,  // Number of differential pairs.
  parameter bit AsyncOn = 1'b0  // Synchronizes data_i into clk_i when set.
) (
  input  logic               clk_i,  // Decode clock.
  input  logic               rst_ni,  // Async reset, active-low.
  input  logic [2*Width-1:0] data_i,  // Packed {diff_n[W-1:0], diff_p[W-1:0]}.
  output logic [Width-1:0]   data_o,  // Decoded single-ended levels.
  output logic               sigint_o  // OR of all per-bit integrity errors.
);

  `include "prim_assert.sv"

  if (AsyncOn) begin : gen_async
    logic [Width-1:0] sigint_per_bit;

    for (genvar i = 0; i < Width; i++) begin : gen_dec
      prim_diff_decode #(
        .AsyncOn(1'b1)
      ) u_dec (
        .clk_i,
        .rst_ni,
        .diff_pi (data_i[i]),
        .diff_ni (data_i[Width + i]),
        .level_o (data_o[i]),
        .rise_o  (),
        .fall_o  (),
        .event_o (),
        .sigint_o(sigint_per_bit[i])
      );
    end

    assign sigint_o = |sigint_per_bit;
  end else begin : gen_sync
    logic [Width-1:0] diff_p_buf, diff_n_buf;
    logic [Width-1:0] sigint_per_bit;

    prim_sec_anchor_buf #(
      .Width(Width)
    ) u_buf_p (
      .in_i  (data_i[Width-1:0]),
      .out_o (diff_p_buf)
    );

    prim_sec_anchor_buf #(
      .Width(Width)
    ) u_buf_n (
      .in_i  (data_i[2*Width-1:Width]),
      .out_o (diff_n_buf)
    );

    prim_xnor2 #(
      .Width(Width)
    ) u_sigint (
      .in0_i (diff_p_buf),
      .in1_i (diff_n_buf),
      .out_o (sigint_per_bit)
    );

    assign sigint_o = |sigint_per_bit;
    assign data_o   = diff_p_buf;
  end

  `OCAH_OT_ASSERT_INIT(WidthPositive_A, Width > 0)

endmodule : prim_diff_decode_multi
