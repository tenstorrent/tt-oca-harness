// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Reset Synchronizer
//
//--------------------------------------------------
module prim_sync_reset #(
  parameter int unsigned WIDTH = 16  // Reset width in clock cycles
) (
  input logic clk,
  input logic rst_n,  // asynchronous reset input, active low
  input logic test_mode,  // test mode, active high
  input logic scan_rst_n,  //scan reset to be used in test mode

  output logic sync_rst_n  // synchronized reset output, active low

);

  logic [WIDTH-1:0] sync_reg;

  prim_rstbypass_stdmux2 sync_rst_n_bypass (
    .i_reset_n(sync_reg[WIDTH-1]),
    .i_test_reset_n(scan_rst_n),
    .i_test_mode(test_mode),
    .o_reset_n(sync_rst_n)
  );

  prim_metastab_hardened_dffr sync_dffr (
    .i_CK(clk),
    .i_RN(rst_n),       // Asynch Reset
    .i_D (1'b1),
    .o_Q (sync_reg[0])
  );

  generate
    for (genvar stage = 1; stage < WIDTH; stage = stage + 1) begin : gen_rst_sync_stage

      prim_metastab_hardened_dffr sync_dffr (
        .i_CK(clk),
        .i_RN(rst_n),              // Asynch Reset
        .i_D (sync_reg[stage-1]),
        .o_Q (sync_reg[stage])
      );

    end
  endgenerate


endmodule
