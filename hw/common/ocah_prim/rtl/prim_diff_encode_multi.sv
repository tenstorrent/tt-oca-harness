// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Encode WIDTH bits onto differential {diff_n, diff_p} pairs.
//
// Pack data_o as {diff_n[W-1:0], diff_p[W-1:0]} for each bit of data_i.
// OUTPUT_FLOP registers the pairs on clk_i when set; rst_ni resets each registered pair to the
// encoding of 0, diff_p low and diff_n high. Without OUTPUT_FLOP the encode is combinational.

module prim_diff_encode_multi #(
  parameter int unsigned WIDTH = 4,  // Number of bits to encode.
  parameter bit OUTPUT_FLOP = 1'b0  // Registers data_o on clk_i when set.
) (
  input  logic             clk_i,  // Encode clock when OUTPUT_FLOP is set.
  input  logic             rst_ni,  // Async reset, active-low; used only when OUTPUT_FLOP is set.
  input  logic [WIDTH-1:0]   data_i,  // Single-ended bits to encode.
  output logic [2*WIDTH-1:0] data_o  // Packed {diff_n[W-1:0], diff_p[W-1:0]}.
);

  `include "prim_assert.sv"

  if (OUTPUT_FLOP) begin : gen_output_flop
    for (genvar i = 0; i < WIDTH; i++) begin : gen_enc
      prim_diff_encode u_enc (
        .clk_i,
        .rst_ni,
        .req_i  (data_i[i]),
        .diff_po(data_o[i]),
        .diff_no(data_o[WIDTH + i])
      );
    end
  end else begin : gen_comb
    logic [WIDTH-1:0] data_buf;
    logic [WIDTH-1:0] diff_p, diff_n;
    logic [WIDTH-1:0] diff_p_buf, diff_n_buf;

    prim_sec_anchor_buf #(
      .Width(WIDTH)
    ) u_buf_in (
      .in_i  (data_i),
      .out_o (data_buf)
    );

    assign diff_p = data_buf;
    assign diff_n = ~data_buf;

    prim_sec_anchor_buf #(
      .Width(2 * WIDTH)
    ) u_buf_diff (
      .in_i  ({diff_n,     diff_p}),
      .out_o ({diff_n_buf, diff_p_buf})
    );

    assign data_o = {diff_n_buf, diff_p_buf};
  end

  `OCAH_OT_ASSERT_INIT(WidthPositive_A, WIDTH > 0)

endmodule : prim_diff_encode_multi
