// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches dtp_ctn_csr_props to every cross_trigger_network instance under the formal top. Port 0
// stands for the sixteen port register blocks. Internal signals reach the property module through
// this port list only; the RTL carries no properties.

bind cross_trigger_network dtp_ctn_csr_props #(
  .NUM_CTP (NUM_CTP),
  .NUM_MST (NUM_XBAR_MST_PORTS)
) u_dtp_ctn_csr_props (
  .clk_i            (clk_i),
  .rst_ni           (rst_ni),
  .req_i            (axil_req_i),
  .resp_i           (axil_resp_o),
  .mst_req_i        (xbar_mst_req),
  .ctp0_regs_i      (gen_ext_ctp[0].u_ctp.reg_out),
  .ctp0_status_i    (gen_ext_ctp[0].u_ctp.reg_in),
  .ctp0_req_i       (gen_ext_ctp[0].u_ctp.u_reg.cpuif_req_masked),
  .ctp0_req_is_wr_i (gen_ext_ctp[0].u_ctp.u_reg.cpuif_req_is_wr),
  .ctp0_addr_i      (gen_ext_ctp[0].u_ctp.u_reg.cpuif_addr),
  .ctp0_wr_data_i   (gen_ext_ctp[0].u_ctp.u_reg.cpuif_wr_data),
  .ctp0_wr_biten_i  (gen_ext_ctp[0].u_ctp.u_reg.cpuif_wr_biten),
  .ctp0_rd_data_i   (gen_ext_ctp[0].u_ctp.u_reg.cpuif_rd_data),
  .ctm_regs_i       (u_ctm.reg_out),
  .ctm_req_i        (u_ctm.u_reg.cpuif_req_masked),
  .ctm_req_is_wr_i  (u_ctm.u_reg.cpuif_req_is_wr),
  .ctm_addr_i       (u_ctm.u_reg.cpuif_addr),
  .ctm_rd_data_i    (u_ctm.u_reg.cpuif_rd_data)
);
