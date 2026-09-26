// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Multi-bit Differential Encoder
//
//--------------------------------------------------

module prim_diff_encode_multi #(
  parameter int unsigned Width = 4,
  parameter bit OutputFlop = 1'b0
) (
  input  logic             clk_i,
  input  logic             rst_ni,
  input  logic [Width-1:0]   data_i,
  output logic [2*Width-1:0] data_o   // {diff_n[W-1:0], diff_p[W-1:0]}
);

  `include "prim_assert.sv"

  if (OutputFlop) begin : gen_output_flop
    for (genvar i = 0; i < Width; i++) begin : gen_enc
      prim_diff_encode u_enc (
        .clk_i,
        .rst_ni,
        .req_i  (data_i[i]),
        .diff_po(data_o[i]),
        .diff_no(data_o[Width + i])
      );
    end
  end else begin : gen_comb
    logic [Width-1:0] data_buf;
    logic [Width-1:0] diff_p, diff_n;
    logic [Width-1:0] diff_p_buf, diff_n_buf;

    prim_sec_anchor_buf #(
      .Width(Width)
    ) u_buf_in (
      .in_i  (data_i),
      .out_o (data_buf)
    );

    assign diff_p = data_buf;
    assign diff_n = ~data_buf;

    prim_sec_anchor_buf #(
      .Width(2 * Width)
    ) u_buf_diff (
      .in_i  ({diff_n,     diff_p}),
      .out_o ({diff_n_buf, diff_p_buf})
    );

    assign data_o = {diff_n_buf, diff_p_buf};
  end

  `OCAH_OT_ASSERT_INIT(WidthPositive_A, Width > 0)

endmodule : prim_diff_encode_multi
