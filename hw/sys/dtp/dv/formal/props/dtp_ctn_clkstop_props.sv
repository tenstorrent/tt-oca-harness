// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the clock-stop controller of the cross-trigger network: the OR of the
// JTAG stop and every CLA request reaches stop_clks_o three clk_i cycles later through a two-flop
// synchronizer and an output flop, and the CLA status output is the OR of the requests alone.
// Attached to ctn_clock_stop_ctrl by dtp_ctn_clkstop_bind.sv and checked with cross_trigger_network as
// the formal top. Every property body is a boolean over current and one-cycle-past values
// (hw/common/dv/docs/formal-property-style.adoc); the three-cycle latency is stated as three
// one-cycle steps over the synchronizer's own stages.

`include "ocah_fv_macros.svh"

module dtp_ctn_clkstop_props #(
  parameter int unsigned NUM_CLK_STOP_REQ = 9
) (
  input logic                        clk_i,
  input logic                        rst_ni,
  input logic [NUM_CLK_STOP_REQ-1:0] clk_stop_req_i,
  input logic                        jtag_clock_stop_i,
  input logic                        req_or_i,       // clk_stop_req_async
  input logic                        sync_stage1_i,  // u_clk_stop_sync.intq
  input logic                        sync_stage2_i,  // clk_stop_req_synced
  input logic                        stop_clks_i,    // stop_clks_o
  input logic                        cla_clock_stop_i // cla_clock_stop_o
);

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(clk_i, rst_ni)

  `OCAH_FV_ASSERT(ast_clkstop_or_after_three,
                  req_or_i == (jtag_clock_stop_i || (|clk_stop_req_i)) &&
                  `OCAH_FV_IMPLIES($past(rst_ni),
                                   sync_stage1_i == $past(req_or_i) &&
                                   sync_stage2_i == $past(sync_stage1_i) &&
                                   stop_clks_i == $past(sync_stage2_i)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_cla_status_excludes_jtag,
                  cla_clock_stop_i == (|clk_stop_req_i), clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_clkstop_low_in_reset,
                  `OCAH_FV_IMPLIES(!rst_ni, !stop_clks_i && !sync_stage1_i && !sync_stage2_i),
                  clk_i, 1'b1)

  `OCAH_FV_COVER(cov_clkstop_jtag_only,
                 stop_clks_i && jtag_clock_stop_i && !(|clk_stop_req_i), clk_i, rst_ni)
  `OCAH_FV_COVER(cov_clkstop_cla_only,
                 stop_clks_i && !jtag_clock_stop_i && (|clk_stop_req_i), clk_i, rst_ni)
  `OCAH_FV_COVER(cov_clkstop_releases, `OCAH_FV_FELL(stop_clks_i), clk_i, rst_ni)
  // verilog_format: on

endmodule : dtp_ctn_clkstop_props
