// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Register a vector with an asynchronous active-low reset.
//
// One flop per bit: sg13g2_dfrbpq_1 for a reset value of 0, sg13g2_sdfbbp_1 with its set
// input for 1. Negedge inverts the clock with one sg13g2_inv_1.
module prim_flop #(
  parameter int               Width      = 1,  // Bit width of the register.
  parameter logic [Width-1:0] ResetValue = 0,  // Value taken while rst_ni is low.
  parameter bit               Negedge    = 0  // Capture on the falling edge of clk_i.
) (
  input  logic             clk_i,  // Capture clock.
  input  logic             rst_ni,  // Asynchronous active-low reset.
  input  logic [Width-1:0] d_i,  // Next value.
  output logic [Width-1:0] q_o  // Registered value.
);
  logic clk;

  if (Negedge) begin : gen_negedge
    (* dont_touch = "true" *)
    sg13g2_inv_1 u_clk_inv (
      .A       (clk_i),
      .Y       (clk)
    );
  end else begin : gen_posedge
    assign clk = clk_i;
  end

  for (genvar i = 0; i < Width; i++) begin : gen_bit
    if (ResetValue[i]) begin : gen_set
      (* dont_touch = "true" *)
      sg13g2_sdfbbp_1 u_cell (
        .CLK     (clk),
        .D       (d_i[i]),
        .SCD     (1'b0),
        .SCE     (1'b0),
        .RESET_B (1'b1),
        .SET_B   (rst_ni),
        .Q       (q_o[i]),
        .Q_N     ()
      );
    end else begin : gen_rst
      (* dont_touch = "true" *)
      sg13g2_dfrbpq_1 u_cell (
        .CLK     (clk),
        .D       (d_i[i]),
        .RESET_B (rst_ni),
        .Q       (q_o[i])
      );
    end
  end
endmodule
