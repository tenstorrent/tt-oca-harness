// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches smu_axi_xbar_props to every smu_axi_xbar instance under the formal top. The crossbar's
// ports reach the property module through this port list only; the RTL carries no properties.

bind smu_axi_xbar smu_axi_xbar_props #(
  .MAX_OUTSTANDING(8)
) u_smu_axi_xbar_props (
  .clk_i                  (clk_i),
  .rst_ni                 (rst_ni),
  .sep_global_base_addr_i (sep_global_base_addr_i),
  .sep_region_size_i      (sep_region_size_i),
  .smc_global_base_addr_i (smc_global_base_addr_i),
  .smc_region_size_i      (smc_region_size_i),
  .sep_out_req_i          (sep_out_req_i),
  .sep_out_resp_i         (sep_out_resp_o),
  .smc_out_req_i          (smc_out_req_i),
  .smc_out_resp_i         (smc_out_resp_o),
  .ext_in_req_i           (ext_in_req_i),
  .ext_in_resp_i          (ext_in_resp_o),
  .sep_in_req_i           (sep_in_req_o),
  .sep_in_resp_i          (sep_in_resp_i),
  .smc_in_req_i           (smc_in_req_o),
  .smc_in_resp_i          (smc_in_resp_i),
  .ext_out_req_i          (ext_out_req_o),
  .ext_out_resp_i         (ext_out_resp_i)
);
