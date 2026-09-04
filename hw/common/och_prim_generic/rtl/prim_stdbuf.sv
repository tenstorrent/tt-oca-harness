// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Standard Buffer
//
//--------------------------------------------------
`timescale 1ns / 1ps

module prim_stdbuf #(
  parameter bit DONT_TOUCH = 1,
  parameter bit SIM_DELAY  = 0
) (
  input  i_A,
  output o_Y
);

`ifndef SYNTHESIS
  if (SIM_DELAY) begin : gen_sim_delay
    assign #1 o_Y = i_A;
  end else
`endif
  begin : gen_no_delay
    assign o_Y = i_A;
  end
endmodule
