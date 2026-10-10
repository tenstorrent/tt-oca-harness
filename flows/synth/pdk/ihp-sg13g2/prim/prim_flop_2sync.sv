// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize a vector into the clk_i domain through two flop stages.
//
// Both stages are prim_flop instances reset to ResetValue. The simulation-only random CDC
// delay of the generic model has no cell equivalent and is absent.
module prim_flop_2sync #(
  parameter int               Width             = 16,  // Bit width of the synchronized vector.
  parameter logic [Width-1:0] ResetValue        = '0,  // Value of both stages while rst_ni is
                                                       // low.
  parameter bit               EnablePrimCdcRand = 1  // Unused: no random CDC delay in cells.
) (
  input  logic             clk_i,  // Destination clock.
  input  logic             rst_ni,  // Asynchronous active-low reset.
  input  logic [Width-1:0] d_i,  // Asynchronous input.
  output logic [Width-1:0] q_o  // Synchronized output.
);
  logic [Width-1:0] intq;
  logic unused_cdc_rand;

  assign unused_cdc_rand = EnablePrimCdcRand;

  prim_flop #(
    .Width     (Width),
    .ResetValue(ResetValue)
  ) u_sync_1 (
    .clk_i,
    .rst_ni,
    .d_i,
    .q_o(intq)
  );

  prim_flop #(
    .Width     (Width),
    .ResetValue(ResetValue)
  ) u_sync_2 (
    .clk_i,
    .rst_ni,
    .d_i(intq),
    .q_o
  );
endmodule
