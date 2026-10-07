// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI bridge functional coverage (cg_jtag2axi_single_op,
// cg_jtag2axi_response, cg_jtag2axi_recovery, cg_jtag2axi_poll,
// cg_jtag2axi_series, cg_jtag2axi_backpressure, cg_jtag2axi_reset,
// cg_jtag2axi_cdc, cg_jtag2axi_gating, cg_dbg_disable_jtag2axi).
//
// One instance in the shared tb_top serves both flows. The TCK-domain points
// come straight from each bridge's own bookkeeping, connected by tb_top
// through hierarchical references: the single-op status, pending and
// launched-operation registers; the transaction the AXI state machine
// completes and the series status it completes against; the bridge's
// SINGLE_OP Update-DR, scanned op field and synchronized disable; its CDC's
// TCK-side clear. The bus-timing points sample the flattened per-bridge AXI
// handshake pins in the system-clock domain.
//
// The three targets are stamped by macros into ONE module with per-target
// labels: Verilator's default coverage write merges points across instances
// of a module (hierarchies collapse to `*`), so a per-target submodule would
// lose the target dimension.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body is a single
// continuous-assign wire, and always_ff-driven variables carry no
// declaration initializers.

`include "ocah_fcov_macros.svh"

module dtp_jtag2axi_fcov (
  input wire        tck_i,
  input wire        tap_rst_ni,
  input wire        clk_i,
  input wire        rst_ni,
  input wire [15:0] tap_state_i,
  input wire [63:0] inst_decoded_i,
  input wire sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_i,

  // SMC fabric bridge (AXI4): TCK-domain single-op state + launched-op fields
  input wire [1:0]  smc_axi_status_i,
  input wire        smc_axi_pending_i,
  input wire [1:0]  smc_axi_op_i,
  input wire [55:0] smc_axi_addr_i,
  input wire [2:0]  smc_axi_size_i,
  input wire [7:0]  smc_axi_wstrb_i,
  // SMC fabric bridge: the transaction the AXI state machine completes
  // (mode = {from the single-op buffer, with-error-status, increment}), the
  // series status before it, the CDC's TCK-side clear and what it discards
  // (abort = {single or with-error-status operation, series operation}), the
  // SINGLE_OP Update-DR with the scanned op field, the synchronized disable,
  // and idle
  input wire        smc_axi_beat_done_i,
  input wire [1:0]  smc_axi_beat_resp_i,
  input wire [2:0]  smc_axi_beat_mode_i,
  input wire [1:0]  smc_axi_beat_op_i,
  input wire [2:0]  smc_axi_beat_size_i,
  input wire [2:0]  smc_axi_beat_req_size_i,
  input wire [2:0]  smc_axi_beat_offset_i,
  input wire [1:0]  smc_axi_sticky_i,
  input wire        smc_axi_clear_pending_i,
  input wire [1:0]  smc_axi_abort_i,
  input wire        smc_axi_single_upd_i,
  input wire [1:0]  smc_axi_scan_op_i,
  input wire        smc_axi_sec_dis_i,
  input wire        smc_axi_fsm_idle_i,
  // SMC fabric bus handshakes (system-clock domain)
  input wire        smc_axi_awvalid_i,
  input wire        smc_axi_awready_i,
  input wire        smc_axi_wvalid_i,
  input wire        smc_axi_wready_i,
  input wire        smc_axi_bvalid_i,
  input wire        smc_axi_bready_i,
  input wire        smc_axi_arvalid_i,
  input wire        smc_axi_arready_i,
  input wire        smc_axi_rvalid_i,
  input wire        smc_axi_rready_i,

  // SMC OTP bridge (AXI4-Lite)
  input wire [1:0]  smc_otp_status_i,
  input wire        smc_otp_pending_i,
  input wire [1:0]  smc_otp_op_i,
  input wire [31:0] smc_otp_addr_i,
  input wire [2:0]  smc_otp_size_i,
  input wire [3:0]  smc_otp_wstrb_i,
  input wire        smc_otp_beat_done_i,
  input wire [1:0]  smc_otp_beat_resp_i,
  input wire [2:0]  smc_otp_beat_mode_i,
  input wire [1:0]  smc_otp_beat_op_i,
  input wire [2:0]  smc_otp_beat_size_i,
  input wire [2:0]  smc_otp_beat_req_size_i,
  input wire [2:0]  smc_otp_beat_offset_i,
  input wire [1:0]  smc_otp_sticky_i,
  input wire        smc_otp_clear_pending_i,
  input wire [1:0]  smc_otp_abort_i,
  input wire        smc_otp_single_upd_i,
  input wire [1:0]  smc_otp_scan_op_i,
  input wire        smc_otp_sec_dis_i,
  input wire        smc_otp_fsm_idle_i,
  input wire        smc_otp_awvalid_i,
  input wire        smc_otp_awready_i,
  input wire        smc_otp_wvalid_i,
  input wire        smc_otp_wready_i,
  input wire        smc_otp_bvalid_i,
  input wire        smc_otp_bready_i,
  input wire        smc_otp_arvalid_i,
  input wire        smc_otp_arready_i,
  input wire        smc_otp_rvalid_i,
  input wire        smc_otp_rready_i,

  // SEP OTP bridge (AXI4-Lite)
  input wire [1:0]  sep_otp_status_i,
  input wire        sep_otp_pending_i,
  input wire [1:0]  sep_otp_op_i,
  input wire [31:0] sep_otp_addr_i,
  input wire [2:0]  sep_otp_size_i,
  input wire [3:0]  sep_otp_wstrb_i,
  input wire        sep_otp_beat_done_i,
  input wire [1:0]  sep_otp_beat_resp_i,
  input wire [2:0]  sep_otp_beat_mode_i,
  input wire [1:0]  sep_otp_beat_op_i,
  input wire [2:0]  sep_otp_beat_size_i,
  input wire [2:0]  sep_otp_beat_req_size_i,
  input wire [2:0]  sep_otp_beat_offset_i,
  input wire [1:0]  sep_otp_sticky_i,
  input wire        sep_otp_clear_pending_i,
  input wire [1:0]  sep_otp_abort_i,
  input wire        sep_otp_single_upd_i,
  input wire [1:0]  sep_otp_scan_op_i,
  input wire        sep_otp_sec_dis_i,
  input wire        sep_otp_fsm_idle_i,
  input wire        sep_otp_awvalid_i,
  input wire        sep_otp_awready_i,
  input wire        sep_otp_wvalid_i,
  input wire        sep_otp_wready_i,
  input wire        sep_otp_bvalid_i,
  input wire        sep_otp_bready_i,
  input wire        sep_otp_arvalid_i,
  input wire        sep_otp_arready_i,
  input wire        sep_otp_rvalid_i,
  input wire        sep_otp_rready_i
);

  // ------------------------------------------------------------------
  // Bridge encodings (jtag2axi.sv), per-target SINGLE_OP decode masks
  // (jtag_inst_reg_pkg one-hot bit positions), and the class encodings the
  // covergroups sample.
  // ------------------------------------------------------------------
  localparam logic [1:0] StSuccess = 2'b00;
  localparam logic [1:0] StSlverr = 2'b01;
  localparam logic [1:0] StDecerr = 2'b10;
  localparam logic [1:0] StBusy = 2'b11;
  localparam logic [1:0] OpRead = 2'b01;
  localparam logic [1:0] OpWrite = 2'b10;

  localparam logic [63:0] SmcAxiSingleOp = 64'h1 << 6'h28;
  localparam logic [63:0] SmcOtpSingleOp = 64'h1 << 6'h1C;
  localparam logic [63:0] SepOtpSingleOp = 64'h1 << 6'h22;

  // AxSIZE of one full data beat: the SMC fabric bus and the OTP AXI4-Lite
  // buses.
  localparam logic [2:0] SmcAxiBeatSize = 3'($clog2(dtp_dv_cfg_pkg::SmcAxiDataWidth / 8));
  localparam logic [2:0] OtpBeatSize = 3'($clog2(dtp_dv_cfg_pkg::OtpAxilDataWidth / 8));

  // Responder memory window per target: each JTAG2AXI responder, the env's
  // slave agent or the cocotb RAM, wraps its address at this size.
  localparam int unsigned MemBytes = 'h10000;

  localparam logic [1:0] TgtSmcAxi = 2'd0;
  localparam logic [1:0] TgtSmcOtp = 2'd1;
  localparam logic [1:0] TgtSepOtp = 2'd2;

  // Single-operation outcome: the AXI response, or the system reset that
  // discarded the operation.
  localparam logic [1:0] OutSuccess = 2'd0;
  localparam logic [1:0] OutSlverr = 2'd1;
  localparam logic [1:0] OutDecerr = 2'd2;
  localparam logic [1:0] OutDiscard = 2'd3;

  // Write-strobe class over the beat the operation addresses; a read drives
  // no strobes.
  localparam logic [2:0] StbNone = 3'd0;
  localparam logic [2:0] StbSingle = 3'd1;
  localparam logic [2:0] StbPartial = 3'd2;
  localparam logic [2:0] StbAll = 3'd3;
  localparam logic [2:0] StbRead = 3'd4;

  // SINGLE_OP capture: an operation in flight, the first capture after one
  // finished, or any other capture.
  localparam logic [1:0] CapBusy = 2'd0;
  localparam logic [1:0] CapSettled = 2'd1;
  localparam logic [1:0] CapIdle = 2'd2;

  localparam logic [1:0] SerIncr = 2'd0;
  localparam logic [1:0] SerNoIncr = 2'd1;
  localparam logic [1:0] SerStatus = 2'd2;

  // Series beat against the series status it completes on: OKAY with no
  // earlier error held, non-OKAY, or OKAY while an earlier error is held.
  localparam logic [1:0] BeatClean = 2'd0;
  localparam logic [1:0] BeatFault = 2'd1;
  localparam logic [1:0] BeatAfterFault = 2'd2;

  localparam logic [1:0] ShapeFull = 2'd0;
  localparam logic [1:0] ShapeNarrowLane0 = 2'd1;
  localparam logic [1:0] ShapeNarrowOffset = 2'd2;
  localparam logic [1:0] ShapeOversize = 2'd3;

  localparam logic [1:0] BpAwBeforeW = 2'd0;
  localparam logic [1:0] BpWBeforeAw = 2'd1;
  localparam logic [1:0] BpArHeld = 2'd2;

  // What the CDC's TCK-side clear discards.
  localparam logic [1:0] ClrIdle = 2'd0;
  localparam logic [1:0] ClrSingle = 2'd1;
  localparam logic [1:0] ClrSeries = 2'd2;

  localparam logic [1:0] PhIdle = 2'd0;
  localparam logic [1:0] PhRequest = 2'd1;
  localparam logic [1:0] PhData = 2'd2;
  localparam logic [1:0] PhResponse = 2'd3;

  localparam logic [1:0] MaskAllClear = 2'd0;
  localparam logic [1:0] MaskOneHot = 2'd1;
  localparam logic [1:0] MaskMultiHot = 2'd2;
  localparam logic [1:0] MaskAllSet = 2'd3;

  // ------------------------------------------------------------------
  // Common TCK-domain scan decode. The TAP reset is TRST AND power-on reset,
  // as the PTAP combines them.
  // ------------------------------------------------------------------
  wire in_reset = (tap_rst_ni !== 1'b1);
  wire cap_dr = (tap_state_i == jtag_tap_pkg::CAPTURE_DR) && !in_reset;

  // Debug-disable mask class over the three bridge fields, and the count of
  // all set fields for the unrelated-field check of each bridge's cells.
  wire [2:0] bridge_dis = {
    dbg_disable_i.sep_otp_jtag2axi, dbg_disable_i.smc_otp_jtag2axi, dbg_disable_i.smc_jtag2axi
  };
  wire [1:0] bridge_mask = 2'($countones(bridge_dis));
  wire [3:0] dis_count = 4'($countones(dbg_disable_i));

  // ------------------------------------------------------------------
  // Common system-clock reset bookkeeping: reset-assertion events and the
  // back-to-back spacing counter. Sampled values at the rst_fell edge are
  // preponed, so on that edge the per-target phase flops below show the
  // pre-reset state.
  // ------------------------------------------------------------------
  wire clk_in_reset = (rst_ni !== 1'b1);
  logic rst_nq;
  logic [7:0] rst_gap_q;
  logic rst_seen_any_q;
  always_ff @(posedge clk_i) rst_nq <= rst_ni;
  wire rst_fell_e = rst_nq && !rst_ni;

  always_ff @(posedge clk_i) begin
    if (rst_fell_e) begin
      rst_gap_q <= '0;
      rst_seen_any_q <= 1'b1;
    end else begin
      if (rst_gap_q != 8'hFF) rst_gap_q <= rst_gap_q + 8'd1;
      if (rst_seen_any_q !== 1'b1) rst_seen_any_q <= 1'b0;
    end
  end

  wire reset_back_to_back = rst_seen_any_q && (rst_gap_q < 8'd64);
  wire reset_back_to_back_e = rst_fell_e && reset_back_to_back;
  wire reset_isolated_e = rst_fell_e && !reset_back_to_back;
  `OCAH_FCOV_COVER(c_reset_back_to_back, reset_back_to_back_e, clk_i, 1'b0)
  `OCAH_FCOV_COVER(c_reset_isolated, reset_isolated_e, clk_i, 1'b0)

  // ------------------------------------------------------------------
  // Per-target TCK-domain section.
  //
  // Single operations: an operation completes when the pending flag falls
  // with an AXI response, or is discarded when the CDC's TCK-side clear
  // starts while it is pending (the bridge then reports DECERR); a fall that
  // leaves BUSY_OR_FULL rejects a second operation and completes nothing.
  // The launched wstrb is the bus WSTRB of the beat holding the address: on
  // the fabric bus the strobe class counts the lanes of the transfer from the
  // address's lane on, on an AXI4-Lite bus every lane of the 4-byte beat.
  //
  // Debug-disable cells: the bridge registers its SINGLE_OP Update-DR, the
  // scanned op field and its synchronized disable on the update edge; one
  // TCK later a READ or WRITE that found the bridge idle has launched (the
  // pending flag rose) or has been blocked.
  //
  // Series beats: the state machine completes a transaction that did not
  // come from the single-op buffer; its response and the series status
  // before it give the beat class, the with-error-status and increment flags
  // its mode.
  // ------------------------------------------------------------------
  `define DTP_J2A_TCK_FCOV(__t, __single, __beat, __lite)                                  \
    wire __t``_tdr_sel = |(inst_decoded_i & (__single));                                 \
    logic __t``_pending_q;                                                               \
    logic __t``_inflight_q;                                                              \
    logic [2:0] __t``_polls_q;                                                           \
    logic __t``_clear_q;                                                                 \
    logic __t``_discard_q;                                                               \
    logic __t``_abn_q;                                                                   \
    logic [1:0] __t``_abn_out_q;                                                         \
    logic __t``_upd_q;                                                                   \
    logic [1:0] __t``_upd_op_q;                                                          \
    logic __t``_dis_q;                                                                   \
    logic __t``_idle_q;                                                                  \
    logic __t``_gated_q;                                                                 \
    logic __t``_released_q;                                                              \
    wire __t``_launch_e = __t``_pending_i && !__t``_pending_q;                           \
    wire __t``_poll_e = cap_dr && __t``_tdr_sel;                                         \
    wire __t``_settled_poll_e = __t``_poll_e && !__t``_pending_i && __t``_inflight_q;    \
    wire __t``_clear_rise_e = __t``_clear_pending_i && !__t``_clear_q && !in_reset;      \
    wire __t``_comp_e = __t``_pending_q && !__t``_pending_i && !in_reset                 \
        && (__t``_discard_q || (__t``_status_i != StBusy));                              \
    wire [1:0] __t``_outcome = __t``_discard_q ? OutDiscard                              \
        : (__t``_status_i == StSlverr) ? OutSlverr                                       \
        : (__t``_status_i == StDecerr) ? OutDecerr : OutSuccess;                         \
    wire __t``_axi_done_e = __t``_comp_e && !__t``_discard_q;                            \
    wire __t``_success_e = __t``_comp_e && (__t``_outcome == OutSuccess);                \
    wire __t``_rw_commit_e = __t``_upd_q && __t``_idle_q && !in_reset                    \
        && ((__t``_upd_op_q == OpRead) || (__t``_upd_op_q == OpWrite));                  \
    wire __t``_release_e = !__t``_sec_dis_i && __t``_dis_q && __t``_gated_q;             \
    wire __t``_series_beat_e = __t``_beat_done_i && !__t``_beat_mode_i[2] && !in_reset;  \
    always_ff @(posedge tck_i) begin                                                     \
      __t``_pending_q <= __t``_pending_i;                                                \
      __t``_clear_q <= __t``_clear_pending_i;                                            \
      __t``_discard_q <= __t``_clear_rise_e && __t``_pending_i;                          \
      __t``_upd_q <= __t``_single_upd_i;                                                 \
      __t``_upd_op_q <= __t``_scan_op_i;                                                 \
      __t``_dis_q <= __t``_sec_dis_i;                                                    \
      __t``_idle_q <= __t``_fsm_idle_i && !__t``_pending_i;                              \
      if (__t``_launch_e) begin                                                          \
        __t``_inflight_q <= 1'b1;                                                        \
        __t``_polls_q <= '0;                                                             \
      end else if (__t``_settled_poll_e) begin                                           \
        __t``_inflight_q <= 1'b0;                                                        \
      end else if (__t``_poll_e && __t``_inflight_q && (__t``_polls_q != 3'd7)) begin    \
        __t``_polls_q <= __t``_polls_q + 3'd1;                                           \
      end                                                                                \
      if (__t``_comp_e && (__t``_outcome != OutSuccess)) begin                           \
        __t``_abn_q <= 1'b1;                                                             \
        __t``_abn_out_q <= __t``_outcome;                                                \
      end else if (__t``_success_e) begin                                                \
        __t``_abn_q <= 1'b0;                                                             \
      end                                                                                \
      if (__t``_rw_commit_e && __t``_dis_q && !__t``_launch_e) __t``_gated_q <= 1'b1;    \
      else if (__t``_release_e) __t``_gated_q <= 1'b0;                                   \
      if (__t``_release_e) __t``_released_q <= 1'b1;                                     \
      else if (__t``_success_e) __t``_released_q <= 1'b0;                               \
    end                                                                                  \
    wire [2:0] __t``_beat = (__lite || (__t``_size_i > __beat)) ? __beat : __t``_size_i; \
    wire [7:0] __t``_lane_mask = 8'((9'h1 << (4'h1 << __t``_beat)) - 9'h1);              \
    wire [3:0] __t``_lanes = __lite ? 4'($countones(__t``_wstrb_i))                      \
        : 4'($countones(8'(__t``_wstrb_i >> (__t``_addr_i % $bits(__t``_wstrb_i)))      \
                        & __t``_lane_mask));                                             \
    wire [2:0] __t``_strobe = (__t``_op_i == OpRead) ? StbRead                           \
        : (__t``_lanes == 4'd0) ? StbNone                                                \
        : (__t``_lanes == 4'(4'h1 << __t``_beat)) ? StbAll                               \
        : (__t``_lanes == 4'd1) ? StbSingle : StbPartial;                                \
    wire __t``_boundary = (32'(__t``_addr_i) + (32'h1 << __t``_beat)) == 32'(MemBytes);  \
    wire [1:0] __t``_cap = __t``_pending_i ? CapBusy                                     \
        : __t``_inflight_q ? CapSettled : CapIdle;                                       \
    wire [1:0] __t``_beat_mode = __t``_beat_mode_i[1] ? SerStatus                        \
        : (__t``_beat_mode_i[0] ? SerIncr : SerNoIncr);                                  \
    wire [1:0] __t``_beat_class = (__t``_beat_resp_i != StSuccess) ? BeatFault           \
        : (__t``_sticky_i != StSuccess) ? BeatAfterFault : BeatClean;                    \
    wire [1:0] __t``_beat_shape = (__t``_beat_req_size_i > __t``_beat_size_i)           \
        ? ShapeOversize : (__t``_beat_size_i == __beat) ? ShapeFull                      \
        : (__t``_beat_offset_i != 3'd0) ? ShapeNarrowOffset : ShapeNarrowLane0;          \
    wire __t``_op_write_e = __t``_axi_done_e && (__t``_op_i == OpWrite);                 \
    wire __t``_op_read_e = __t``_axi_done_e && (__t``_op_i == OpRead);                   \
    wire __t``_op_nop_e = __t``_poll_e && (__t``_cap == CapIdle);                        \
    wire __t``_status_success_e = __t``_comp_e && (__t``_outcome == OutSuccess);         \
    wire __t``_status_slverr_e = __t``_comp_e && (__t``_outcome == OutSlverr);           \
    wire __t``_status_decerr_e = __t``_comp_e && (__t``_outcome == OutDecerr);           \
    wire __t``_status_discard_e = __t``_comp_e && (__t``_outcome == OutDiscard);         \
    wire __t``_status_busy_e = __t``_poll_e && (__t``_cap == CapBusy);                   \
    wire __t``_poll_immediate_e = __t``_settled_poll_e && (__t``_polls_q == 3'd0);       \
    wire __t``_poll_short_e =                                                            \
        __t``_settled_poll_e && (__t``_polls_q inside {3'd1, 3'd2, 3'd3});               \
    wire __t``_poll_long_e = __t``_settled_poll_e && (__t``_polls_q >= 3'd4);            \
    wire __t``_recovery_next_nop_e = __t``_settled_poll_e && __t``_abn_q;                \
    wire __t``_recovery_rw_after_error_e = __t``_success_e && __t``_abn_q                \
        && (__t``_abn_out_q != OutDiscard);                                              \
    wire __t``_recovery_reset_abort_e = __t``_success_e && __t``_abn_q                   \
        && (__t``_abn_out_q == OutDiscard);                                              \
    wire __t``_wstrb_none_e = __t``_op_write_e && (__t``_strobe == StbNone);             \
    wire __t``_wstrb_single_e = __t``_op_write_e && (__t``_strobe == StbSingle);         \
    wire __t``_wstrb_partial_e = __t``_op_write_e && (__t``_strobe == StbPartial);       \
    wire __t``_wstrb_all_e = __t``_op_write_e && (__t``_strobe == StbAll);               \
    wire __t``_addr_aligned_e = __t``_axi_done_e && !__t``_boundary;                     \
    wire __t``_addr_boundary_e = __t``_axi_done_e && __t``_boundary;                     \
    wire __t``_series_incr_e = __t``_series_beat_e && (__t``_beat_mode == SerIncr);      \
    wire __t``_series_no_incr_e = __t``_series_beat_e && (__t``_beat_mode == SerNoIncr); \
    wire __t``_series_stat_e = __t``_series_beat_e && (__t``_beat_mode == SerStatus);    \
    wire __t``_series_read_e = __t``_series_beat_e && (__t``_beat_op_i == OpRead);       \
    wire __t``_series_write_e = __t``_series_beat_e && (__t``_beat_op_i == OpWrite);     \
    wire __t``_series_clean_e = __t``_series_beat_e && (__t``_beat_class == BeatClean);  \
    wire __t``_series_fault_e = __t``_series_beat_e && (__t``_beat_class == BeatFault);  \
    wire __t``_series_after_fault_e =                                                    \
        __t``_series_beat_e && (__t``_beat_class == BeatAfterFault);                     \
    wire __t``_series_stat_incr_e = __t``_series_stat_e && __t``_beat_mode_i[0];         \
    wire __t``_series_stat_hold_e = __t``_series_stat_e && !__t``_beat_mode_i[0];        \
    wire __t``_dbg_clear_allowed_e = __t``_rw_commit_e && !__t``_dis_q && __t``_launch_e; \
    wire __t``_dbg_set_blocked_e = __t``_rw_commit_e && __t``_dis_q && !__t``_launch_e;  \
    wire __t``_dbg_isolation_e = __t``_dbg_clear_allowed_e && (dis_count != 4'd0);       \
    wire __t``_gating_recovery_e = __t``_success_e && __t``_released_q;                  \
    wire [1:0] __t``_clear_class = __t``_abort_i[1] ? ClrSingle                          \
        : __t``_abort_i[0] ? ClrSeries : ClrIdle;                                        \
    wire __t``_cdc_clear_idle_e = __t``_clear_rise_e && (__t``_clear_class == ClrIdle);  \
    wire __t``_cdc_clear_single_e = __t``_clear_rise_e && (__t``_clear_class == ClrSingle); \
    wire __t``_cdc_clear_series_e = __t``_clear_rise_e && (__t``_clear_class == ClrSeries); \
    `OCAH_FCOV_COVER(c_``__t``_op_write, __t``_op_write_e, tck_i, in_reset)                \
    `OCAH_FCOV_COVER(c_``__t``_op_read, __t``_op_read_e, tck_i, in_reset)                  \
    `OCAH_FCOV_COVER(c_``__t``_op_nop, __t``_op_nop_e, tck_i, in_reset)                    \
    `OCAH_FCOV_COVER(c_``__t``_status_success, __t``_status_success_e, tck_i, in_reset)    \
    `OCAH_FCOV_COVER(c_``__t``_status_slverr, __t``_status_slverr_e, tck_i, in_reset)      \
    `OCAH_FCOV_COVER(c_``__t``_status_decerr, __t``_status_decerr_e, tck_i, in_reset)      \
    `OCAH_FCOV_COVER(c_``__t``_status_reset_discard, __t``_status_discard_e,               \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_status_busy_or_full, __t``_status_busy_e, tck_i, in_reset)  \
    `OCAH_FCOV_COVER(c_``__t``_poll_immediate, __t``_poll_immediate_e, tck_i, in_reset)    \
    `OCAH_FCOV_COVER(c_``__t``_poll_short_wait, __t``_poll_short_e, tck_i, in_reset)       \
    `OCAH_FCOV_COVER(c_``__t``_poll_long_wait, __t``_poll_long_e, tck_i, in_reset)         \
    `OCAH_FCOV_COVER(c_``__t``_recovery_next_nop, __t``_recovery_next_nop_e,               \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_recovery_next_rw_after_error,                               \
                     __t``_recovery_rw_after_error_e, tck_i, in_reset)                     \
    `OCAH_FCOV_COVER(c_``__t``_recovery_reset_abort, __t``_recovery_reset_abort_e,         \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_wstrb_none, __t``_wstrb_none_e, tck_i, in_reset)            \
    `OCAH_FCOV_COVER(c_``__t``_wstrb_single_byte, __t``_wstrb_single_e, tck_i, in_reset)   \
    `OCAH_FCOV_COVER(c_``__t``_wstrb_partial, __t``_wstrb_partial_e, tck_i, in_reset)      \
    `OCAH_FCOV_COVER(c_``__t``_wstrb_all_bytes, __t``_wstrb_all_e, tck_i, in_reset)        \
    `OCAH_FCOV_COVER(c_``__t``_addr_aligned, __t``_addr_aligned_e, tck_i, in_reset)        \
    `OCAH_FCOV_COVER(c_``__t``_addr_boundary, __t``_addr_boundary_e, tck_i, in_reset)      \
    `OCAH_FCOV_COVER(c_``__t``_series_incr, __t``_series_incr_e, tck_i, in_reset)          \
    `OCAH_FCOV_COVER(c_``__t``_series_no_incr, __t``_series_no_incr_e, tck_i, in_reset)    \
    `OCAH_FCOV_COVER(c_``__t``_series_with_error_status, __t``_series_stat_e,              \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_series_read, __t``_series_read_e, tck_i, in_reset)          \
    `OCAH_FCOV_COVER(c_``__t``_series_write, __t``_series_write_e, tck_i, in_reset)        \
    `OCAH_FCOV_COVER(c_``__t``_series_clean, __t``_series_clean_e, tck_i, in_reset)        \
    `OCAH_FCOV_COVER(c_``__t``_series_fault, __t``_series_fault_e, tck_i, in_reset)        \
    `OCAH_FCOV_COVER(c_``__t``_series_after_fault, __t``_series_after_fault_e,             \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_series_status_increment, __t``_series_stat_incr_e,          \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_series_status_hold, __t``_series_stat_hold_e,               \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_dbg_disable_clear_allowed, __t``_dbg_clear_allowed_e,       \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_dbg_disable_set_blocked, __t``_dbg_set_blocked_e,           \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_dbg_disable_isolation, __t``_dbg_isolation_e,               \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_gating_release_no_replay, __t``_release_e,                  \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_gating_recovery, __t``_gating_recovery_e, tck_i, in_reset)  \
    `OCAH_FCOV_COVER(c_``__t``_cdc_clear_idle, __t``_cdc_clear_idle_e, tck_i, in_reset)    \
    `OCAH_FCOV_COVER(c_``__t``_cdc_clear_single_discard, __t``_cdc_clear_single_e,         \
                     tck_i, in_reset)                                                      \
    `OCAH_FCOV_COVER(c_``__t``_cdc_clear_series_discard, __t``_cdc_clear_series_e,         \
                     tck_i, in_reset)

  `DTP_J2A_TCK_FCOV(smc_axi, SmcAxiSingleOp, SmcAxiBeatSize, 1'b0)
  `DTP_J2A_TCK_FCOV(smc_otp, SmcOtpSingleOp, OtpBeatSize, 1'b1)
  `DTP_J2A_TCK_FCOV(sep_otp, SepOtpSingleOp, OtpBeatSize, 1'b1)
  `undef DTP_J2A_TCK_FCOV

  // Transfer size: the SMC fabric bridge carries 1/2/4/8-byte beats; an
  // AXI4-Lite beat is 4 bytes whatever the SINGLE_OP size field holds.
  wire smc_axi_size_1b_e = smc_axi_axi_done_e && (smc_axi_beat == 3'd0);
  wire smc_axi_size_2b_e = smc_axi_axi_done_e && (smc_axi_beat == 3'd1);
  wire smc_axi_size_4b_e = smc_axi_axi_done_e && (smc_axi_beat == 3'd2);
  wire smc_axi_size_8b_e = smc_axi_axi_done_e && (smc_axi_beat == 3'd3);
  wire smc_otp_size_4b_e = smc_otp_axi_done_e;
  wire sep_otp_size_4b_e = sep_otp_axi_done_e;
  `OCAH_FCOV_COVER(c_smc_axi_size_1b, smc_axi_size_1b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_axi_size_2b, smc_axi_size_2b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_axi_size_4b, smc_axi_size_4b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_axi_size_8b, smc_axi_size_8b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_otp_size_4b, smc_otp_size_4b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_otp_size_4b, sep_otp_size_4b_e, tck_i, in_reset)

  // Series beat shape over the three bridges: a full beat, a narrow beat on
  // lane 0 or at a non-zero lane offset (the fabric bus), and a size field
  // wider than the bus (the OTP buses).
  wire series_shape_full_e = (smc_axi_series_beat_e && (smc_axi_beat_shape == ShapeFull))
      || (smc_otp_series_beat_e && (smc_otp_beat_shape == ShapeFull))
      || (sep_otp_series_beat_e && (sep_otp_beat_shape == ShapeFull));
  wire series_shape_narrow_lane0_e =
      (smc_axi_series_beat_e && (smc_axi_beat_shape == ShapeNarrowLane0))
      || (smc_otp_series_beat_e && (smc_otp_beat_shape == ShapeNarrowLane0))
      || (sep_otp_series_beat_e && (sep_otp_beat_shape == ShapeNarrowLane0));
  wire series_shape_narrow_offset_e =
      (smc_axi_series_beat_e && (smc_axi_beat_shape == ShapeNarrowOffset))
      || (smc_otp_series_beat_e && (smc_otp_beat_shape == ShapeNarrowOffset))
      || (sep_otp_series_beat_e && (sep_otp_beat_shape == ShapeNarrowOffset));
  wire series_shape_oversize_e =
      (smc_axi_series_beat_e && (smc_axi_beat_shape == ShapeOversize))
      || (smc_otp_series_beat_e && (smc_otp_beat_shape == ShapeOversize))
      || (sep_otp_series_beat_e && (sep_otp_beat_shape == ShapeOversize));
  `OCAH_FCOV_COVER(c_series_shape_full, series_shape_full_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_series_shape_narrow_lane0, series_shape_narrow_lane0_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_series_shape_narrow_offset, series_shape_narrow_offset_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_series_shape_oversize, series_shape_oversize_e, tck_i, in_reset)

  // Debug-disable mask class of the bridge fields at any bridge's cell.
  wire dbg_cell_e = smc_axi_rw_commit_e || smc_otp_rw_commit_e || sep_otp_rw_commit_e;
  wire dbg_mask_all_clear_e = dbg_cell_e && (bridge_mask == 2'd0);
  wire dbg_mask_one_hot_e = dbg_cell_e && (bridge_mask == 2'd1);
  wire dbg_mask_multi_hot_e = dbg_cell_e && (bridge_mask == 2'd2);
  wire dbg_mask_all_set_e = dbg_cell_e && (bridge_mask == 2'd3);
  `OCAH_FCOV_COVER(c_dbg_disable_jtag2axi_all_clear, dbg_mask_all_clear_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_dbg_disable_jtag2axi_one_hot, dbg_mask_one_hot_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_dbg_disable_jtag2axi_multi_hot, dbg_mask_multi_hot_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_dbg_disable_jtag2axi_all_set, dbg_mask_all_set_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // Per-target system-clock section: handshake order, reset timing. The
  // phase flops clear through B, R or reset; their preponed values at
  // rst_fell_e describe the transaction the reset aborts. The bridge's
  // output stage resets asynchronously, so at rst_fell_e a request that was
  // waiting shows in the flops, not on the VALID pins.
  // ------------------------------------------------------------------
  `define DTP_J2A_CLK_FCOV(__t)                                                            \
    logic __t``_aw_done_q;                                                                 \
    logic __t``_w_done_q;                                                                  \
    logic __t``_rd_out_q;                                                                  \
    logic __t``_aw_wait_q;                                                                 \
    logic __t``_ar_wait_q;                                                                 \
    wire __t``_aw_hs = __t``_awvalid_i && __t``_awready_i;                                 \
    wire __t``_w_hs = __t``_wvalid_i && __t``_wready_i;                                    \
    wire __t``_b_hs = __t``_bvalid_i && __t``_bready_i;                                    \
    wire __t``_ar_hs = __t``_arvalid_i && __t``_arready_i;                                 \
    wire __t``_r_hs = __t``_rvalid_i && __t``_rready_i;                                    \
    always_ff @(posedge clk_i) begin                                                       \
      if (!rst_ni) begin                                                                   \
        __t``_aw_done_q <= 1'b0;                                                           \
        __t``_w_done_q <= 1'b0;                                                            \
        __t``_rd_out_q <= 1'b0;                                                            \
        __t``_aw_wait_q <= 1'b0;                                                           \
        __t``_ar_wait_q <= 1'b0;                                                           \
      end else begin                                                                       \
        if (__t``_b_hs) begin                                                              \
          __t``_aw_done_q <= 1'b0;                                                         \
          __t``_w_done_q <= 1'b0;                                                          \
        end else begin                                                                     \
          if (__t``_aw_hs) __t``_aw_done_q <= 1'b1;                                        \
          if (__t``_w_hs) __t``_w_done_q <= 1'b1;                                          \
        end                                                                                \
        if (__t``_ar_hs) __t``_rd_out_q <= 1'b1;                                           \
        else if (__t``_r_hs) __t``_rd_out_q <= 1'b0;                                       \
        __t``_aw_wait_q <= __t``_awvalid_i && !__t``_awready_i;                            \
        __t``_ar_wait_q <= __t``_arvalid_i && !__t``_arready_i;                            \
      end                                                                                  \
    end                                                                                    \
    wire __t``_skew_aw_before_w_e = __t``_w_hs && __t``_aw_done_q && !__t``_w_done_q;      \
    wire __t``_skew_w_before_aw_e = __t``_aw_hs && __t``_w_done_q && !__t``_aw_done_q;     \
    wire __t``_skew_ar_held_e = __t``_ar_hs && __t``_ar_wait_q;                            \
    wire [1:0] __t``_rst_phase =                                                           \
        ((__t``_aw_done_q && __t``_w_done_q) || __t``_rd_out_q) ? PhResponse               \
        : (__t``_aw_done_q && !__t``_w_done_q) ? PhData                                    \
        : ((__t``_aw_wait_q && !__t``_aw_done_q) || __t``_ar_wait_q) ? PhRequest : PhIdle; \
    wire __t``_reset_idle_e = rst_fell_e && (__t``_rst_phase == PhIdle);                   \
    wire __t``_reset_request_e = rst_fell_e && (__t``_rst_phase == PhRequest);             \
    wire __t``_reset_data_e = rst_fell_e && (__t``_rst_phase == PhData);                   \
    wire __t``_reset_response_e = rst_fell_e && (__t``_rst_phase == PhResponse);           \
    `OCAH_FCOV_COVER(c_``__t``_skew_aw_before_w, __t``_skew_aw_before_w_e, clk_i, clk_in_reset)  \
    `OCAH_FCOV_COVER(c_``__t``_skew_w_before_aw, __t``_skew_w_before_aw_e, clk_i, clk_in_reset)  \
    `OCAH_FCOV_COVER(c_``__t``_skew_ar_held, __t``_skew_ar_held_e, clk_i, clk_in_reset)          \
    `OCAH_FCOV_COVER(c_``__t``_reset_timing_idle, __t``_reset_idle_e, clk_i, 1'b0)         \
    `OCAH_FCOV_COVER(c_``__t``_reset_timing_request_issued, __t``_reset_request_e,         \
                     clk_i, 1'b0)                                                          \
    `OCAH_FCOV_COVER(c_``__t``_reset_timing_data_phase, __t``_reset_data_e, clk_i, 1'b0)   \
    `OCAH_FCOV_COVER(c_``__t``_reset_timing_response_wait, __t``_reset_response_e,         \
                     clk_i, 1'b0)

  `DTP_J2A_CLK_FCOV(smc_axi)
  `DTP_J2A_CLK_FCOV(smc_otp)
  `DTP_J2A_CLK_FCOV(sep_otp)
  `undef DTP_J2A_CLK_FCOV

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups: the cover-property bins above, per
  // target, and the crosses where the features interact.
  // ------------------------------------------------------------------
  covergroup cg_jtag2axi_single_op with function sample (
      logic [1:0] tgt, logic [1:0] op, logic [2:0] beat, logic [2:0] strobe, logic boundary
  );
    option.per_instance = 1;
    cp_target: coverpoint tgt {
      bins smc_axi = {TgtSmcAxi}; bins smc_otp = {TgtSmcOtp}; bins sep_otp = {TgtSepOtp};
    }
    cp_op: coverpoint op {bins read = {OpRead}; bins write = {OpWrite};}
    cp_size: coverpoint beat {
      bins b1 = {3'd0}; bins b2 = {3'd1}; bins b4 = {3'd2}; bins b8 = {3'd3};
    }
    cp_strobe: coverpoint strobe {
      bins none = {StbNone};
      bins single = {StbSingle};
      bins partial = {StbPartial};
      bins all = {StbAll};
      bins no_strobe = {StbRead};
    }
    cp_addr: coverpoint boundary {bins aligned = {1'b0}; bins window_boundary = {1'b1};}
    x_op_shape: cross cp_target, cp_op, cp_size, cp_strobe{
      // An AXI4-Lite beat is 4 bytes whatever the SINGLE_OP size field holds.
      ignore_bins otp_beat = (binsof(cp_target.smc_otp) || binsof(cp_target.sep_otp))
          && !binsof(cp_size.b4);
      // A read drives no strobes; a write always has a strobe class.
      ignore_bins read_strobe = binsof (cp_op.read) && !binsof (cp_strobe.no_strobe);
      ignore_bins write_no_strobe = binsof (cp_op.write) && binsof (cp_strobe.no_strobe);
      // A 1-byte beat has one lane and a 2-byte beat two.
      ignore_bins one_lane = binsof(cp_size.b1)
          && (binsof(cp_strobe.single) || binsof(cp_strobe.partial));
      ignore_bins two_lanes = binsof (cp_size.b2) && binsof (cp_strobe.partial);
    }
    x_target_addr: cross cp_target, cp_addr;
  endgroup

  covergroup cg_jtag2axi_response with function sample (logic [1:0] tgt, logic [1:0] outcome);
    option.per_instance = 1;
    cp_target: coverpoint tgt {
      bins smc_axi = {TgtSmcAxi}; bins smc_otp = {TgtSmcOtp}; bins sep_otp = {TgtSepOtp};
    }
    cp_outcome: coverpoint outcome {
      bins success = {OutSuccess};
      bins slverr = {OutSlverr};
      bins decerr = {OutDecerr};
      bins reset_discard = {OutDiscard};
    }
    x_target_outcome: cross cp_target, cp_outcome;
  endgroup

  covergroup cg_jtag2axi_recovery with function sample (
      logic [1:0] tgt, logic [1:0] prior, logic next_success
  );
    option.per_instance = 1;
    cp_target: coverpoint tgt {
      bins smc_axi = {TgtSmcAxi}; bins smc_otp = {TgtSmcOtp}; bins sep_otp = {TgtSepOtp};
    }
    cp_prior: coverpoint prior {
      bins slverr = {OutSlverr}; bins decerr = {OutDecerr}; bins reset_discard = {OutDiscard};
    }
    cp_path: coverpoint next_success {bins next_poll = {1'b0}; bins next_success = {1'b1};}
    x_target_prior_path: cross cp_target, cp_prior, cp_path;
  endgroup

  covergroup cg_jtag2axi_poll with function sample (
      logic [1:0] tgt, logic [1:0] cap, logic [2:0] polls
  );
    option.per_instance = 1;
    cp_target: coverpoint tgt {
      bins smc_axi = {TgtSmcAxi}; bins smc_otp = {TgtSmcOtp}; bins sep_otp = {TgtSepOtp};
    }
    cp_capture: coverpoint cap {
      bins busy_or_full = {CapBusy}; bins settled = {CapSettled}; bins idle_nop = {CapIdle};
    }
    cp_wait: coverpoint polls iff (cap == CapSettled) {
      bins immediate = {3'd0}; bins short_wait = {[3'd1 : 3'd3]}; bins long_wait = {[3'd4 : 3'd7]};
    }
    x_target_capture: cross cp_target, cp_capture;
    x_target_wait: cross cp_target, cp_wait;
  endgroup

  covergroup cg_jtag2axi_series with function sample (
      logic [1:0] tgt,
      logic [1:0] mode,
      logic is_read,
      logic [1:0] beat_class,
      logic incr,
      logic [1:0] shape
  );
    option.per_instance = 1;
    cp_target: coverpoint tgt {
      bins smc_axi = {TgtSmcAxi}; bins smc_otp = {TgtSmcOtp}; bins sep_otp = {TgtSepOtp};
    }
    cp_mode: coverpoint mode {
      bins incr = {SerIncr}; bins no_incr = {SerNoIncr}; bins with_error_status = {SerStatus};
    }
    cp_dir: coverpoint is_read {bins write = {1'b0}; bins read = {1'b1};}
    cp_beat: coverpoint beat_class {
      bins clean = {BeatClean}; bins fault = {BeatFault}; bins after_fault = {BeatAfterFault};
    }
    cp_status_step: coverpoint incr iff (mode == SerStatus) {
      bins hold = {1'b0}; bins increment = {1'b1};
    }
    cp_shape: coverpoint shape {
      bins full = {ShapeFull};
      bins narrow_lane0 = {ShapeNarrowLane0};
      bins narrow_offset = {ShapeNarrowOffset};
      bins oversize = {ShapeOversize};
    }
    x_mode_dir: cross cp_target, cp_mode, cp_dir;
    x_mode_beat: cross cp_target, cp_mode, cp_beat;
    x_target_status_step: cross cp_target, cp_status_step;
  endgroup

  covergroup cg_jtag2axi_backpressure with function sample (logic [1:0] tgt, logic [1:0] kind);
    option.per_instance = 1;
    cp_target: coverpoint tgt {
      bins smc_axi = {TgtSmcAxi}; bins smc_otp = {TgtSmcOtp}; bins sep_otp = {TgtSepOtp};
    }
    cp_handshake: coverpoint kind {
      bins aw_before_w = {BpAwBeforeW}; bins w_before_aw = {BpWBeforeAw}; bins ar_held = {BpArHeld};
    }
    x_target_handshake: cross cp_target, cp_handshake;
  endgroup

  covergroup cg_jtag2axi_reset with function sample (
      logic [1:0] tgt, logic [1:0] phase, logic back_to_back
  );
    option.per_instance = 1;
    cp_target: coverpoint tgt {
      bins smc_axi = {TgtSmcAxi}; bins smc_otp = {TgtSmcOtp}; bins sep_otp = {TgtSepOtp};
    }
    cp_phase: coverpoint phase {
      bins idle = {PhIdle};
      bins request_issued = {PhRequest};
      bins data_phase = {PhData};
      bins response_wait = {PhResponse};
    }
    cp_spacing: coverpoint back_to_back {bins isolated = {1'b0}; bins back_to_back = {1'b1};}
    x_target_phase: cross cp_target, cp_phase;
  endgroup

  covergroup cg_jtag2axi_cdc with function sample (logic [1:0] tgt, logic [1:0] clear_class);
    option.per_instance = 1;
    cp_target: coverpoint tgt {
      bins smc_axi = {TgtSmcAxi}; bins smc_otp = {TgtSmcOtp}; bins sep_otp = {TgtSepOtp};
    }
    cp_clear: coverpoint clear_class {
      bins clear_idle = {ClrIdle};
      bins single_discard = {ClrSingle};
      bins series_discard = {ClrSeries};
    }
    x_target_clear: cross cp_target, cp_clear;
  endgroup

  covergroup cg_jtag2axi_gating with function sample (logic [1:0] tgt, logic recovery);
    option.per_instance = 1;
    cp_target: coverpoint tgt {
      bins smc_axi = {TgtSmcAxi}; bins smc_otp = {TgtSmcOtp}; bins sep_otp = {TgtSepOtp};
    }
    cp_event: coverpoint recovery {bins release_no_replay = {1'b0}; bins recovery = {1'b1};}
    x_target_event: cross cp_target, cp_event;
  endgroup

  // The bridge half of the 22-cell debug-disable contract, sampled at every
  // SINGLE_OP READ or WRITE update that finds its bridge idle.
  covergroup cg_dbg_disable_jtag2axi with function sample (
      logic [1:0] field, logic disabled, logic blocked, logic [1:0] mask, logic other_set
  );
    option.per_instance = 1;
    cp_field: coverpoint field {
      bins smc_jtag2axi = {TgtSmcAxi};
      bins smc_otp_jtag2axi = {TgtSmcOtp};
      bins sep_otp_jtag2axi = {TgtSepOtp};
    }
    cp_value: coverpoint disabled {bins clear = {1'b0}; bins set = {1'b1};}
    cp_outcome: coverpoint blocked {bins allowed = {1'b0}; bins blocked = {1'b1};}
    cp_mask: coverpoint mask {
      bins all_clear = {MaskAllClear};
      bins one_hot = {MaskOneHot};
      bins multi_hot = {MaskMultiHot};
      bins all_set = {MaskAllSet};
    }
    cp_isolation: coverpoint other_set iff (!disabled && !blocked) {
      bins alone = {1'b0}; bins other_field_set = {1'b1};
    }
    x_cell: cross cp_field, cp_value, cp_outcome{
      // A clear field never blocks its bridge and a set one never lets an
      // operation through: either tuple is a gating failure.
      illegal_bins blocked_while_clear = binsof (cp_value.clear) && binsof (cp_outcome.blocked);
      illegal_bins allowed_while_set = binsof (cp_value.set) && binsof (cp_outcome.allowed);
    }
    x_field_isolation: cross cp_field, cp_isolation;
  endgroup

  cg_jtag2axi_single_op u_cg_single_op = new();
  cg_jtag2axi_response u_cg_response = new();
  cg_jtag2axi_recovery u_cg_recovery = new();
  cg_jtag2axi_poll u_cg_poll = new();
  cg_jtag2axi_series u_cg_series = new();
  cg_jtag2axi_backpressure u_cg_backpressure = new();
  cg_jtag2axi_reset u_cg_reset = new();
  cg_jtag2axi_cdc u_cg_cdc = new();
  cg_jtag2axi_gating u_cg_gating = new();
  cg_dbg_disable_jtag2axi u_cg_dbg_disable = new();

  `define DTP_J2A_CG_SAMPLE(__t, __id)                                                    \
    always_ff @(posedge tck_i) begin                                                      \
      if (__t``_axi_done_e)                                                               \
        u_cg_single_op.sample(__id, __t``_op_i, __t``_beat, __t``_strobe, __t``_boundary); \
      if (__t``_comp_e) u_cg_response.sample(__id, __t``_outcome);                        \
      if (__t``_recovery_next_nop_e) u_cg_recovery.sample(__id, __t``_abn_out_q, 1'b0);   \
      if (__t``_success_e && __t``_abn_q)                                                 \
        u_cg_recovery.sample(__id, __t``_abn_out_q, 1'b1);                                \
      if (__t``_poll_e) u_cg_poll.sample(__id, __t``_cap, __t``_polls_q);                 \
      if (__t``_series_beat_e)                                                            \
        u_cg_series.sample(__id, __t``_beat_mode, __t``_beat_op_i == OpRead,              \
                           __t``_beat_class, __t``_beat_mode_i[0], __t``_beat_shape);     \
      if (__t``_clear_rise_e) u_cg_cdc.sample(__id, __t``_clear_class);                   \
      if (__t``_release_e) u_cg_gating.sample(__id, 1'b0);                                \
      if (__t``_gating_recovery_e) u_cg_gating.sample(__id, 1'b1);                        \
      if (__t``_rw_commit_e)                                                              \
        u_cg_dbg_disable.sample(__id, __t``_dis_q, !__t``_launch_e, bridge_mask,          \
                                dis_count != 4'd0);                                       \
    end                                                                                   \
    always_ff @(posedge clk_i) begin                                                      \
      if (!clk_in_reset && __t``_skew_aw_before_w_e)                                      \
        u_cg_backpressure.sample(__id, BpAwBeforeW);                                      \
      if (!clk_in_reset && __t``_skew_w_before_aw_e)                                      \
        u_cg_backpressure.sample(__id, BpWBeforeAw);                                      \
      if (!clk_in_reset && __t``_skew_ar_held_e) u_cg_backpressure.sample(__id, BpArHeld); \
      if (rst_fell_e) u_cg_reset.sample(__id, __t``_rst_phase, reset_back_to_back);       \
    end

  `DTP_J2A_CG_SAMPLE(smc_axi, TgtSmcAxi)
  `DTP_J2A_CG_SAMPLE(smc_otp, TgtSmcOtp)
  `DTP_J2A_CG_SAMPLE(sep_otp, TgtSepOtp)
  `undef DTP_J2A_CG_SAMPLE
`endif

endmodule : dtp_jtag2axi_fcov
