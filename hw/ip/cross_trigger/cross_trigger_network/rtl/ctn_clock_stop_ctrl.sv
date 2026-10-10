// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OR clock-stop requests and register a glitch-free chiplet halt.
//
// clk_stop_req_i are CLA (or other) requests in the ck_feedthru domain; jtag_clock_stop_i
// is quasi-static from JTAG_TCK.
// cla_clock_stop_o is the combinational OR of CLA requests for JTAG status; stop_clks_o
// passes the OR of those and the JTAG request through a two-flop synchronizer and an output
// register in clk_i, so it follows the requests after three clk_i cycles.

`include "ocah_registers.svh"

module ctn_clock_stop_ctrl #(
  parameter int unsigned NUM_CLK_STOP_REQ = 1  // Number of clock stop request inputs.
) (
  input  wire logic                          clk_i,  // System clock.
  input  wire logic                          rst_ni,  // Active-low asynchronous reset; clears
                                                      // stop_clks_o.

  input  wire logic [NUM_CLK_STOP_REQ-1:0]   clk_stop_req_i,  // Clock-stop requests from individual
                                                              // CLAs or other on-chip sources,
                                                              // active-high and asynchronous to
                                                              // clk_i.

  input  wire logic                          jtag_clock_stop_i,  // Clock stop from the JTAG
                                                                 // DEBUG_CONTROL register,
                                                                 // active-high.

  output logic                          stop_clks_o,  // Registered functional halt in the clk_i
                                                      // domain: the OR of the JTAG and CLA
                                                      // requests, after a two-flop synchronizer.
                                                      // Drives chiplet clock gating.

  output logic                          cla_clock_stop_o  // OR of the clk_stop_req_i requests only,
                                                          // for JTAG DEBUG_CONTROL status readback.
);

  // CLA clock stop status for JTAG readback (CLA requests only, no sync needed —
  // the JTAG scan register captures it asynchronously in Capture-DR by design).
  assign cla_clock_stop_o = |clk_stop_req_i;

  // OR all async stop requests before synchronization.
  // clk_stop_req_i is in the ck_feedthru domain; jtag_clock_stop_i is in the
  // JTAG_TCK domain (quasi-static once TCK quiesces). We only need the OR-reduction
  // ("is any stop requested?"), so a single synchronizer on the combined signal is
  // sufficient and avoids NUM_CLK_STOP_REQ separate synchronizer instances.
  logic clk_stop_req_async;
  assign clk_stop_req_async = jtag_clock_stop_i | (|clk_stop_req_i);

  // Two-stage synchronizer: resolves metastability on the combined async request
  // before it reaches the clock gate. The synchronizer completes two full clk_i
  // cycles before stop_clks_o asserts, so the clock is not gated until the
  // output is stable.
  logic clk_stop_req_synced;
  prim_flop_2sync #(
    .Width(1)
  ) u_clk_stop_sync (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .d_i    (clk_stop_req_async),
    .q_o    (clk_stop_req_synced)
  );

  // Register the synchronized request with an explicit reset so stop_clks_o
  // defaults to 0 at power-up before the synchronizer flops settle.
  `OCAH_FF(stop_clks_o, clk_stop_req_synced, 1'b0, clk_i, rst_ni)

endmodule : ctn_clock_stop_ctrl
