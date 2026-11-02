// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches smc_filter_lock_props to every smc_internal_regs instance under the formal top, on the
// outbound filter-control port. Entry 0 stands for the sixteen outbound entries. Internal signals
// reach the property module through this port list only; the RTL carries no properties.

bind smc_internal_regs smc_filter_lock_props #(
  .ENTRY (0)
) u_smc_filter_lock_props (
  .clk_i     (clk_smc_i),
  .rst_ni    (rst_primary_smc_clk_ni),
  .test_en_i (test_en_i),
  .req_i     (axil_outbound_filter_ctrl_req_i),
  .resp_i    (axil_outbound_filter_ctrl_resp_o),
  .cfg_i     (outbound_filter_ctrl_o[0])
);
