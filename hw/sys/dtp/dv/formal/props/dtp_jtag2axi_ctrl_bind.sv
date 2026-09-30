// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches dtp_jtag2axi_ctrl_props to every jtag2axi instance under the formal top. Internal signals
// reach the property module through this port list only; the RTL carries no properties.

bind jtag2axi dtp_jtag2axi_ctrl_props #(
  .FIFO_DEPTH (FIFO_DEPTH),
  .SR_LEN     (SHARED_SR_LEN)
) u_dtp_jtag2axi_ctrl_props (
  .tck_i                  (tck_i),
  .trst_ni                (trst_ni),
  .aclk_i                 (aclk_i),
  .arst_ni                (arst_ni),
  .update_en_i            (update_en_i),
  .select_AXISeriesCtrl_i (select_AXISeriesCtrl_i),
  .security_disable_i     (security_disable_i),
  .state_i                (axi_state_q_tclk),
  .src_aw_valid_i         (src_req.aw_valid),
  .src_w_valid_i          (src_req.w_valid),
  .src_ar_valid_i         (src_req.ar_valid),
  .src_b_valid_i          (src_resp.b_valid),
  .src_r_valid_i          (src_resp.r_valid),
  .src_r_ready_i          (src_req.r_ready),
  .src_b_resp_i           (src_resp.b.resp),
  .src_r_resp_i           (src_resp.r.resp),
  .bresp_update_i         (fsm_updates_bresp_status_tclk_comb),
  .rdata_update_i         (fsm_updates_rdata_status_tclk_comb),
  .next_status_i          (next_status_tclk_comb),
  .sticky_status_i        (sticky_axi_status_tclk),
  .sticky_full_i          (sticky_axi_status_full_tclk),
  .ctrl_reset_bit_i       (update_register_q_tclk[AXISERIESCTRL_RESET_HIGH]),
  .current_op_i           (current_op_tclk),
  .single_tx_i            (current_tx_is_from_single_buffer_tclk),
  .single_valid_i         (single_tx_req_valid_tclk),
  .req_fifo_count_i       (series_request_fifo_count_tclk),
  .rsp_fifo_count_i       (series_rsp_fifo_count_tclk),
  .reads_in_flight_i      (series_reads_in_flight_tclk),
  .reads_pushed_i         (series_reads_pushed_tclk),
  .plain_reads_pending_i  (plain_reads_pending_tclk),
  .pipeline_depth_i       (series_ctrl_pipeline_depth_tclk_r),
  .update_register_i      (update_register_q_tclk),
  .write_outstanding_i    (write_outstanding_q),
  .read_outstanding_i     (read_outstanding_q),
  .dst_aw_ready_i         (dst_resp.aw_ready),
  .dst_w_ready_i          (dst_resp.w_ready),
  .dst_ar_ready_i         (dst_resp.ar_ready)
);
