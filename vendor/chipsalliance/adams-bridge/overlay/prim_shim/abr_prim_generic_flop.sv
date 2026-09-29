// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Vendor generic flop name. Instantiates prim_flop so `-t synth` picks the
// foundry overlay. rst_b is active-low, same polarity as rst_ni.
module abr_prim_generic_flop #(
  parameter int               Width      = 1,
  parameter logic [Width-1:0] ResetValue = 0
) (
  input                    clk_i,
  input                    rst_b,
  input        [Width-1:0] d_i,
  output logic [Width-1:0] q_o
);

  prim_flop #(
    .Width     (Width),
    .ResetValue(ResetValue)
  ) u_flop (
    .clk_i (clk_i),
    .rst_ni(rst_b),
    .d_i   (d_i),
    .q_o   (q_o)
  );

endmodule
