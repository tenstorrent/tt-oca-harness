// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Vendor generic enable-flop name. Instantiates prim_flop_en. rst_b is
// active-low, same polarity as rst_ni.
module abr_prim_generic_flop_en #(
  parameter int               WIDTH       = 1,
  parameter bit               EN_SEC_BUF  = 0,
  parameter logic [WIDTH-1:0] RESET_VALUE = 0
) (
  input                    clk_i,
  input                    rst_b,
  input                    en_i,
  input        [WIDTH-1:0] d_i,
  output logic [WIDTH-1:0] q_o
);

  prim_flop_en #(
    .Width     (WIDTH),
    .EnSecBuf  (EN_SEC_BUF),
    .ResetValue(RESET_VALUE)
  ) u_flop_en (
    .clk_i (clk_i),
    .rst_ni(rst_b),
    .en_i  (en_i),
    .d_i   (d_i),
    .q_o   (q_o)
  );

endmodule
