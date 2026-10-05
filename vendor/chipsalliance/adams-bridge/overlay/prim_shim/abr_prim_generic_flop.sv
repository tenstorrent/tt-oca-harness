// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Vendor generic flop name. Instantiates prim_flop so `-t synth` picks the
// foundry overlay. rst_b is active-low, same polarity as rst_ni.
module abr_prim_generic_flop #(
  parameter int               WIDTH       = 1,
  parameter logic [WIDTH-1:0] RESET_VALUE = 0
) (
  input                    clk_i,
  input                    rst_b,
  input        [WIDTH-1:0] d_i,
  output logic [WIDTH-1:0] q_o
);

  prim_flop #(
    .Width     (WIDTH),
    .ResetValue(RESET_VALUE)
  ) u_flop (
    .clk_i (clk_i),
    .rst_ni(rst_b),
    .d_i   (d_i),
    .q_o   (q_o)
  );

endmodule
