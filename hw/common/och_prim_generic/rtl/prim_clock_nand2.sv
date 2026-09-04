// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock NAND2 Gate
//
//--------------------------------------------------
`timescale 1ns / 1ps

module prim_clock_nand2 #(
  parameter bit SIM_DELAY = 0
) (
  input  i_A1,
  input  i_A2,
  output o_Y
);

`ifndef SYNTHESIS
  if (SIM_DELAY) begin : gen_sim_delay
    assign #1 o_Y = ~(i_A2 & i_A1);
  end else
`endif
  begin : gen_no_delay
    assign o_Y = ~(i_A2 & i_A1);
  end

endmodule


