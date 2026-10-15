// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the control of the JTAG-to-AXI bridge: the request machine, the
// tck-side admit counters, the status encoder, and the disable gate with its flush. Attached to
// jtag2axi by dtp_jtag2axi_ctrl_bind.sv and checked with jtag2axi as the formal top; bound by
// module name, the same module serves the three DTP instances under the dtp top. Every property
// body is a boolean over current and one-cycle-past values
// (hw/common/dv/docs/formal-property-style.adoc). The data path is out of scope: the
// shift register, the byte lanes and the address increment are checked by simulation.
//
// The machine and its counters are tck posedge flops, so a value sampled at a posedge is the
// one the machine consumed at that edge. The disable input reaches the negedge update latches
// as the value present at the preceding posedge (dtp_jtag2axi_sby_env.sv).

`include "ocah_fv_macros.svh"

module dtp_jtag2axi_ctrl_props #(
  parameter int FIFO_DEPTH = 3,
  parameter int SR_LEN = 1,
  localparam int CntW  = $clog2(FIFO_DEPTH + 2),
  localparam int PdW = (FIFO_DEPTH == 0) ? 1 : $clog2(FIFO_DEPTH + 1)
) (
  input logic              tck_i,
  input logic              trst_ni,
  input logic              update_en_i,
  input logic              select_AXISeriesCtrl_i,
  input logic              security_disable_i,
  input logic [2:0]        state_i,                // axi_state_q_tclk
  input logic              src_aw_valid_i,         // src_req.aw_valid
  input logic              src_w_valid_i,          // src_req.w_valid
  input logic              src_ar_valid_i,         // src_req.ar_valid
  input logic              src_b_valid_i,          // src_resp.b_valid
  input logic              src_r_valid_i,          // src_resp.r_valid
  input logic              src_r_ready_i,          // src_req.r_ready
  input logic [1:0]        src_b_resp_i,           // src_resp.b.resp
  input logic [1:0]        src_r_resp_i,           // src_resp.r.resp
  input logic              bresp_update_i,         // fsm_updates_bresp_status_tclk_comb
  input logic              rdata_update_i,         // fsm_updates_rdata_status_tclk_comb
  input logic [1:0]        next_status_i,          // next_status_tclk_comb
  input logic [1:0]        sticky_status_i,        // sticky_axi_status_tclk
  input logic              sticky_full_i,          // sticky_axi_status_full_tclk
  input logic              ctrl_reset_bit_i,       // update_register_q_tclk[AxiSeriesCtrlResetHigh]
  input logic [1:0]        ctrl_op_i,              // update_register_q_tclk AXISeriesCtrl op field
  input logic [1:0]        current_op_i,           // current_op_tclk
  input logic              single_tx_i,            // current_tx_is_from_single_buffer_tclk
  input logic              single_valid_i,         // single_tx_req_valid_tclk
  input logic [CntW-1:0]   req_fifo_count_i,       // series_request_fifo_count_tclk
  input logic [CntW-1:0]   rsp_fifo_count_i,       // series_rsp_fifo_count_tclk
  input logic [CntW-1:0]   reads_in_flight_i,      // series_reads_in_flight_tclk
  input logic [CntW-1:0]   reads_pushed_i,         // series_reads_pushed_tclk
  input logic [CntW-1:0]   plain_reads_pending_i,  // plain_reads_pending_tclk
  input logic [PdW-1:0]    pipeline_depth_i,       // series_ctrl_pipeline_depth_tclk_r
  input logic [1:0]        series_op_mode_i,       // series_ctrl_op_mode_tclk_r
  input logic              req_fifo_push_i,        // series_request_fifo_push_tclk
  input logic [1:0]        req_fifo_push_op_i,     // series_request_fifo_din_tclk.op
  input logic [SR_LEN-1:0] update_register_i       // update_register_q_tclk
);

  // axi_state_e encodings of jtag2axi.
  localparam logic [2:0] Idle = 3'd0;
  localparam logic [2:0] SendAddrW = 3'd1;
  localparam logic [2:0] SendDataW = 3'd2;
  localparam logic [2:0] WaitBresp = 3'd3;
  localparam logic [2:0] SendAddrR = 3'd4;
  localparam logic [2:0] WaitRdata = 3'd5;
  localparam logic [2:0] UpdateStatus = 3'd6;

  localparam logic [1:0] OpRead = 2'b01;
  localparam logic [1:0] OpWrite = 2'b10;
  localparam logic [1:0] OpReserved = 2'b11;

  localparam logic [1:0] StatusSuccess = 2'b00;
  localparam logic [1:0] StatusSlverr = 2'b01;
  localparam logic [1:0] StatusDecerr = 2'b10;

  // OKAY maps to SUCCESS, SLVERR and DECERR to their own codes, EXOKAY to SLVERR.
  function automatic logic [1:0] status_of(input logic [1:0] resp);
    case (resp)
      2'b00:   return StatusSuccess;
      2'b10:   return StatusSlverr;
      2'b11:   return StatusDecerr;
      default: return StatusSlverr;
    endcase
  endfunction

  logic ctrl_reset_write;
  assign ctrl_reset_write = update_en_i && !security_disable_i && select_AXISeriesCtrl_i &&
                            ctrl_reset_bit_i;

  // The series status holds its first error until the SERIES_CTRL reset bit, and a completion
  // from the SINGLE_OP buffer does not reach it. A reset in the same cycle as a series
  // completion clears the status before the completion is merged.
  logic       series_done;
  logic [1:0] series_status_base;
  logic [1:0] series_status_next;
  assign series_done        = (bresp_update_i || rdata_update_i) && !single_tx_i;
  assign series_status_base = ctrl_reset_write ? StatusSuccess : sticky_status_i;
  assign series_status_next = (series_done && series_status_base == StatusSuccess) ?
                              next_status_i : series_status_base;

  logic ctrl_reserved_write;
  assign ctrl_reserved_write = update_en_i && !security_disable_i && select_AXISeriesCtrl_i &&
                               ctrl_op_i == OpReserved;

  logic [CntW-1:0] admit_limit;
  assign admit_limit = CntW'(pipeline_depth_i) + CntW'(1);

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(tck_i, trst_ni)

  // ---- Request machine ----------------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_j2a_state_valid, state_i <= UpdateStatus, tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_j2a_valid_only_in_send_states,
                  `OCAH_FV_IMPLIES(src_aw_valid_i, state_i == SendAddrW) &&
                  `OCAH_FV_IMPLIES(src_w_valid_i, state_i inside {SendAddrW, SendDataW}) &&
                  `OCAH_FV_IMPLIES(src_ar_valid_i, state_i == SendAddrR) &&
                  `OCAH_FV_IMPLIES(state_i == SendAddrW, src_aw_valid_i) &&
                  `OCAH_FV_IMPLIES(state_i == SendDataW, src_w_valid_i) &&
                  `OCAH_FV_IMPLIES(state_i == SendAddrR, src_ar_valid_i),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_j2a_idle_after_status,
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(state_i) == UpdateStatus,
                                   state_i == Idle) &&
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(state_i) != Idle && state_i == Idle,
                                   $past(state_i) == UpdateStatus),
                  tck_i, trst_ni)
  // The machine issues one request and consumes its response before the next, so a responder
  // that answers only an accepted request (the shared checker's rules, assumed on the CDC's
  // response side) presents a beat no earlier than the request's last handshake and no later
  // than the state that consumes it.
  `OCAH_FV_ASSERT(ast_j2a_resp_only_while_waiting,
                  `OCAH_FV_IMPLIES(src_b_valid_i,
                                   state_i inside {SendAddrW, SendDataW, WaitBresp}) &&
                  `OCAH_FV_IMPLIES(src_r_valid_i, state_i inside {SendAddrR, WaitRdata}),
                  tck_i, trst_ni)

  // ---- Status encoding and the sticky series status ----------------------------------------
  // An error code holds until a reset write (PTAP document, *_AXI_SERIES_CTRL op).
  `OCAH_FV_ASSERT(ast_j2a_status_encodes_resp,
                  `OCAH_FV_IMPLIES(bresp_update_i,
                                   state_i == WaitBresp && src_b_valid_i &&
                                   next_status_i == status_of(src_b_resp_i)) &&
                  `OCAH_FV_IMPLIES(rdata_update_i,
                                   state_i == WaitRdata && src_r_valid_i && src_r_ready_i &&
                                   next_status_i == status_of(src_r_resp_i)),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_j2a_series_status_sticky,
                  `OCAH_FV_IMPLIES($past(trst_ni), sticky_status_i == $past(series_status_next)) &&
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(sticky_full_i) &&
                                   !$past(ctrl_reset_write),
                                   sticky_full_i) &&
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(ctrl_reset_write) &&
                                   !$past(bresp_update_i || rdata_update_i),
                                   sticky_status_i == StatusSuccess && !sticky_full_i),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_j2a_series_error_holds,
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(sticky_status_i) != StatusSuccess &&
                                   !$past(ctrl_reset_write),
                                   sticky_status_i == $past(sticky_status_i)),
                  tck_i, trst_ni)

  // ---- Admission: the request FIFO and the read pipeline never exceed pipeline_depth + 1 -----
  `OCAH_FV_ASSERT(ast_j2a_one_read_in_flight,
                  reads_in_flight_i <= CntW'(1) &&
                  `OCAH_FV_IMPLIES(reads_in_flight_i != '0, state_i == WaitRdata),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_j2a_admit_bounded_by_depth,
                  pipeline_depth_i <= PdW'(FIFO_DEPTH) &&
                  req_fifo_count_i <= admit_limit &&
                  reads_in_flight_i <= admit_limit &&
                  reads_pushed_i <= admit_limit &&
                  rsp_fifo_count_i <= CntW'(FIFO_DEPTH + 1),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_j2a_series_ops_are_axi,
                  series_op_mode_i != OpReserved &&
                  `OCAH_FV_IMPLIES(req_fifo_push_i, req_fifo_push_op_i inside {OpRead, OpWrite}),
                  tck_i, trst_ni)

  // ---- Disable gate -------------------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_j2a_disable_holds_idle,
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(security_disable_i) &&
                                   $past(state_i) == Idle,
                                   state_i == Idle && !single_valid_i &&
                                   req_fifo_count_i == '0 && rsp_fifo_count_i == '0 &&
                                   reads_in_flight_i == '0 && reads_pushed_i == '0 &&
                                   plain_reads_pending_i == '0) &&
                  `OCAH_FV_IMPLIES($past(trst_ni) && security_disable_i && update_en_i,
                                   update_register_i == $past(update_register_i)),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_j2a_disable_inflight_completes,
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(security_disable_i) &&
                                   $past(state_i) == WaitBresp && $past(src_b_valid_i),
                                   state_i == UpdateStatus) &&
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(security_disable_i) &&
                                   $past(state_i) == WaitRdata &&
                                   $past(src_r_valid_i && src_r_ready_i),
                                   state_i == UpdateStatus) &&
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(security_disable_i) &&
                                   $past(state_i) inside {SendAddrW, SendDataW, SendAddrR},
                                   state_i != Idle),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_j2a_release_replays_nothing,
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(state_i) == Idle &&
                                   !$past(single_valid_i) && $past(req_fifo_count_i) == '0,
                                   state_i == Idle),
                  tck_i, trst_ni)

  // ---- Covers -------------------------------------------------------------------------------
  `OCAH_FV_COVER(cov_j2a_single_write_complete,
                 $past(state_i) == WaitBresp && state_i == UpdateStatus &&
                 current_op_i == OpWrite, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_j2a_single_read_complete,
                 $past(state_i) == WaitRdata && state_i == UpdateStatus &&
                 current_op_i == OpRead, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_j2a_series_reads_admitted,
                 reads_pushed_i == CntW'(FIFO_DEPTH + 1), tck_i, trst_ni)
  `OCAH_FV_COVER(cov_j2a_status_slverr, sticky_status_i == StatusSlverr, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_j2a_status_decerr, sticky_status_i == StatusDecerr, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_j2a_status_full, sticky_full_i && !ctrl_reset_write, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_j2a_series_reset_write,
                 ctrl_reset_write && !(bresp_update_i || rdata_update_i), tck_i, trst_ni)
  `OCAH_FV_COVER(cov_j2a_error_then_clean_completion,
                 $past(sticky_status_i) != StatusSuccess &&
                 $past(bresp_update_i || rdata_update_i) &&
                 $past(next_status_i) == StatusSuccess && !$past(ctrl_reset_write),
                 tck_i, trst_ni)
  `OCAH_FV_COVER(cov_j2a_series_error_held,
                 $past(series_done) && $past(next_status_i) == StatusSuccess &&
                 sticky_status_i != StatusSuccess, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_j2a_series_ctrl_reserved, ctrl_reserved_write, tck_i, trst_ni)
  for (genvar s = 1; s <= 6; s++) begin : gen_disable_in_state
    `OCAH_FV_COVER(cov_j2a_disable_in_state, security_disable_i && state_i == 3'(s),
                   tck_i, trst_ni)
  end
  // verilog_format: on

endmodule : dtp_jtag2axi_ctrl_props
