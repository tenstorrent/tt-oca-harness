// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// CTN Clock Stop Control Module
//
// Description:
// Aggregates multiple clock stop request signals using an OR tree.
// The OR-reduced CLA status is exported directly and also registered
// for a glitch-free chiplet clock stop output.
//------------------------------------------------------------------------------


module ctn_clock_stop_ctrl #(
  parameter int unsigned NUM_CLK_STOP_REQ = 1  // Number of clock stop request inputs
) (
  // Global Interface
  input  wire logic                          clk_i,
  input  wire logic                          rst_ni,

  // Clock stop request inputs (from CLAs or other devices, ck_feedthru domain)
  input  wire logic [NUM_CLK_STOP_REQ-1:0]   clk_stop_req_i,

  // JTAG DEBUG_CONTROL direct clock stop (JTAG_TCK domain, quasi-static)
  input  wire logic                          jtag_clock_stop_i,

  // Clock stop output (registered, clk_i domain)
  output logic                          stop_clks_o,

  // CLA clock stop status output (for JTAG status reporting, combinational)
  output logic                          cla_clock_stop_o
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
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      stop_clks_o <= 1'b0;
    end else begin
      stop_clks_o <= clk_stop_req_synced;
    end
  end

endmodule : ctn_clock_stop_ctrl
