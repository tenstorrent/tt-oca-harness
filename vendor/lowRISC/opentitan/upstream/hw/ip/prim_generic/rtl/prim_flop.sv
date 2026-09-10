// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

`include "prim_assert.sv"

module prim_flop #(
  parameter int               Width      = 1,
  parameter logic [Width-1:0] ResetValue = 0,
  parameter bit               Negedge    = 0
) (
  input                    clk_i,
  input                    rst_ni,
  input        [Width-1:0] d_i,
  output logic [Width-1:0] q_o
);

  if (Negedge) begin : gen_negedge
    always_ff @(negedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        q_o <= ResetValue;
      end else begin
        q_o <= d_i;
      end
    end
  end else begin : gen_posedge
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        q_o <= ResetValue;
      end else begin
        q_o <= d_i;
      end
    end
  end

endmodule
