// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Standard 2:1 Mux
//
//--------------------------------------------------
`timescale 1ns / 1ps

module prim_stdmux2 #(
  parameter bit SIM_DELAY = 0
) (
  input  i_I0,
  input  i_I1,
  input  i_SEL,
  output o_Y
);

`ifndef SYNTHESIS
  if (SIM_DELAY) begin : gen_sim_delay
    assign #1 o_Y = i_SEL ? i_I1 : i_I0;
  end else
`endif
  begin : gen_no_delay
    assign o_Y = i_SEL ? i_I1 : i_I0;
  end
endmodule
