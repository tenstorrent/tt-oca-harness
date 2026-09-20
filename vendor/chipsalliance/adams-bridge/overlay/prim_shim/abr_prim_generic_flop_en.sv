// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Vendor generic enable-flop name. Instantiates prim_flop_en. rst_b is
// active-low, same polarity as rst_ni.
module abr_prim_generic_flop_en #(
  parameter int               Width      = 1,
  parameter bit               EnSecBuf   = 0,
  parameter logic [Width-1:0] ResetValue = 0
) (
  input                    clk_i,
  input                    rst_b,
  input                    en_i,
  input        [Width-1:0] d_i,
  output logic [Width-1:0] q_o
);

  prim_flop_en #(
    .Width     (Width),
    .EnSecBuf  (EnSecBuf),
    .ResetValue(ResetValue)
  ) u_flop_en (
    .clk_i (clk_i),
    .rst_ni(rst_b),
    .en_i  (en_i),
    .d_i   (d_i),
    .q_o   (q_o)
  );

endmodule
