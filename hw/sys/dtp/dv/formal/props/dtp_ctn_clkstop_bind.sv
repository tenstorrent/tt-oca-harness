// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches dtp_ctn_clkstop_props to every ctn_clock_stop_ctrl instance under the formal top. Internal
// signals reach the property module through this port list only; the RTL carries no properties.

bind ctn_clock_stop_ctrl dtp_ctn_clkstop_props #(
  .NUM_CLK_STOP_REQ (NUM_CLK_STOP_REQ)
) u_dtp_ctn_clkstop_props (
  .clk_i             (clk_i),
  .rst_ni            (rst_ni),
  .clk_stop_req_i    (clk_stop_req_i),
  .jtag_clock_stop_i (jtag_clock_stop_i),
  .req_or_i          (clk_stop_req_async),
  .sync_stage1_i     (u_clk_stop_sync.intq),
  .sync_stage2_i     (clk_stop_req_synced),
  .stop_clks_i       (stop_clks_o),
  .cla_clock_stop_i  (cla_clock_stop_o)
);
