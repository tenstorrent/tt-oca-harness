// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Environment of the bmc and cover tasks on the jtag2axi formal top, read by those tasks beside
// dtp_jtag2axi_sby_env.sv. Those tasks cut the CDC's clear-pending flag toward the request
// machine together with its response side. The CDC clears only after an asynchronous reset, and
// the environment asserts the resets before the first edge alone, so the flag is high for a prefix
// of the trace, possibly empty, and low from its first fall on. Bound to jtag2axi by the
// statement at the end of this file.

`include "ocah_fv_macros.svh"

module dtp_jtag2axi_free_resp_sby_env (
  input logic tck_i,
  input logic trst_ni,
  input logic src_clear_pending_i  // src_clear_pending_tclk
);

`ifdef FORMAL
  logic clear_done_q;
  always_ff @(posedge tck_i or negedge trst_ni) begin
    if (!trst_ni) clear_done_q <= 1'b0;
    else if (!src_clear_pending_i) clear_done_q <= 1'b1;
  end

  // verilog_format: off
  // The CDC clears once, after the resets that precede the first edge.
  `OCAH_FV_ASSUME(asm_env_cdc_clear_once, `OCAH_FV_IMPLIES(clear_done_q, !src_clear_pending_i),
                  tck_i, trst_ni)
  // verilog_format: on
`endif

endmodule : dtp_jtag2axi_free_resp_sby_env

bind jtag2axi dtp_jtag2axi_free_resp_sby_env u_dtp_jtag2axi_free_resp_sby_env (
  .tck_i               (tck_i),
  .trst_ni             (trst_ni),
  .src_clear_pending_i (src_clear_pending_tclk)
);
