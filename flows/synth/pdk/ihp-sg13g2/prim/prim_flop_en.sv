// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Register a vector with a load enable and an asynchronous active-low reset.
//
// One sg13g2_mux2_1 per bit holds the value while the enable is low and feeds a flop chosen
// as in prim_flop. EnSecBuf routes en_i through prim_sec_anchor_buf.
module prim_flop_en #(
  parameter int               Width      = 1,  // Bit width of the register.
  parameter bit               EnSecBuf   = 0,  // Buffer en_i through prim_sec_anchor_buf.
  parameter logic [Width-1:0] ResetValue = 0  // Value taken while rst_ni is low.
) (
  input  logic             clk_i,  // Capture clock.
  input  logic             rst_ni,  // Asynchronous active-low reset.
  input  logic             en_i,  // Load enable.
  input  logic [Width-1:0] d_i,  // Next value, loaded while en_i is high.
  output logic [Width-1:0] q_o  // Registered value.
);
  logic en;

  if (EnSecBuf) begin : gen_en_sec_buf
    prim_sec_anchor_buf #(
      .Width(1)
    ) u_en_buf (
      .in_i (en_i),
      .out_o(en)
    );
  end else begin : gen_en_no_sec_buf
    assign en = en_i;
  end

  for (genvar i = 0; i < Width; i++) begin : gen_bit
    logic d;

    (* dont_touch = "true" *)
    sg13g2_mux2_1 u_mux (
      .A0      (q_o[i]),
      .A1      (d_i[i]),
      .S       (en),
      .X       (d)
    );
    if (ResetValue[i]) begin : gen_set
      (* dont_touch = "true" *)
      sg13g2_sdfbbp_1 u_cell (
        .CLK     (clk_i),
        .D       (d),
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
        .CLK     (clk_i),
        .D       (d),
        .RESET_B (rst_ni),
        .Q       (q_o[i])
      );
    end
  end
endmodule
