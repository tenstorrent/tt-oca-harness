// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI / OTP-bridge functional coverage (jtag2axi_single_op_cg,
// jtag2axi_response_cg, jtag2axi_robustness_cg, otp_jtag2axi_cg).
//
// One instance in the shared tb_top serves both flows. The completed-response
// boundary comes straight from each bridge's own TCK-domain bookkeeping
// (status/pending/launched-op registers), connected by tb_top through
// hierarchical references — the cocotb Verilator build compiles with
// --public-flat-rw and VCS resolves them natively. Bus-timing bins (channel
// skew, reset timing, CDC recovery) sample the flattened per-bridge AXI
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
  input wire        trst_ni,
  input wire        clk_i,
  input wire        rst_ni,
  input wire [15:0] tap_state_i,
  input wire [63:0] inst_decoded_i,
  input wire sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_i,

  // SMC fabric bridge (AXI4): TCK-domain bridge state + launched-op fields
  input wire [1:0]  smc_axi_status_i,
  input wire        smc_axi_pending_i,
  input wire [1:0]  smc_axi_op_i,
  input wire [55:0] smc_axi_addr_i,
  input wire [2:0]  smc_axi_size_i,
  input wire [7:0]  smc_axi_wstrb_i,
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
  // Bridge encodings (jtag2axi.sv) and per-target TDR decode masks
  // (jtag_inst_reg_pkg one-hot bit positions).
  // ------------------------------------------------------------------
  localparam logic [1:0] StSuccess = 2'b00;
  localparam logic [1:0] StSlverr = 2'b01;
  localparam logic [1:0] StDecerr = 2'b10;
  localparam logic [1:0] OpRead = 2'b01;
  localparam logic [1:0] OpWrite = 2'b10;

  localparam logic [63:0] SmcAxiSingleOp = 64'h1 << 6'h28;
  localparam logic [63:0] SmcAxiSeriesIncr = 64'h1 << 6'h2A;
  localparam logic [63:0] SmcAxiSeriesNoIncr = 64'h1 << 6'h2B;
  localparam logic [63:0] SmcAxiSeriesStat = 64'h1 << 6'h2C;
  localparam logic [63:0] SmcOtpSingleOp = 64'h1 << 6'h1C;
  localparam logic [63:0] SmcOtpSeriesIncr = 64'h1 << 6'h1E;
  localparam logic [63:0] SmcOtpSeriesNoIncr = 64'h1 << 6'h1F;
  localparam logic [63:0] SmcOtpSeriesStat = 64'h1 << 6'h20;
  localparam logic [63:0] SepOtpSingleOp = 64'h1 << 6'h22;
  localparam logic [63:0] SepOtpSeriesIncr = 64'h1 << 6'h24;
  localparam logic [63:0] SepOtpSeriesNoIncr = 64'h1 << 6'h25;
  localparam logic [63:0] SepOtpSeriesStat = 64'h1 << 6'h26;

  // TB memory window per target (tb_top RAM responders).
  localparam int unsigned MemBytes = 'h10000;

  // ------------------------------------------------------------------
  // Common TCK-domain scan decode (same shape as dtp_fcov).
  // ------------------------------------------------------------------
  wire in_reset = (trst_ni !== 1'b1);
  logic [15:0] tap_state_q;
  always_ff @(posedge tck_i) tap_state_q <= tap_state_i;
  wire [15:0] tap_state_prev = tap_state_q;
  wire dr_committed = (tap_state_prev == jtag_tap_pkg::UPDATE_DR) && !in_reset;
  wire cap_dr = (tap_state_i == jtag_tap_pkg::CAPTURE_DR) && !in_reset;

  // ------------------------------------------------------------------
  // Common system-clock reset bookkeeping: reset-assertion events and the
  // back-to-back spacing counter. Sampled values at the rst_fell edge are
  // preponed, so the per-target phase flops below still show the pre-reset
  // state on that edge.
  // ------------------------------------------------------------------
  wire clk_in_reset = (rst_ni !== 1'b1);
  logic rst_nq;
  logic [7:0] rst_gap_q;
  logic [3:0] rst_events_q;
  logic rst_seen_any_q;
  always_ff @(posedge clk_i) rst_nq <= rst_ni;
  wire rst_fell_e = rst_nq && !rst_ni;

  always_ff @(posedge clk_i) begin
    if (rst_fell_e) begin
      rst_gap_q <= '0;
      rst_events_q <= rst_events_q + 4'd1;
      rst_seen_any_q <= 1'b1;
    end else if (rst_gap_q != 8'hFF) begin
      rst_gap_q <= rst_gap_q + 8'd1;
    end
  end

  wire reset_back_to_back_e = rst_fell_e && rst_seen_any_q && (rst_gap_q < 8'd64);
  `OCAH_FCOV_COVER(c_reset_back_to_back, reset_back_to_back_e, clk_i, 1'b0)

  // ------------------------------------------------------------------
  // Per-target TCK-domain section: completed responses, statuses, polls,
  // series modes, debug-gating, and error/reset recovery. The launched wstrb
  // is the bus WSTRB of the beat holding the address, so the strobe bins
  // count the lanes of the transfer from the address's lane on.
  // ------------------------------------------------------------------
  `define DTP_J2A_TCK_FCOV(__t, __dis, __single, __sincr, __snoincr, __sstat)               \
    wire __t``_tdr_sel = |(inst_decoded_i & (__single));                              \
    logic __t``_pending_q;                                                                  \
    logic __t``_dis_q;                                                                      \
    logic __t``_had_gated_q;                                                                \
    logic __t``_had_err_q;                                                                  \
    logic __t``_inflight_q;                                                                 \
    logic [2:0] __t``_polls_q;                                                              \
    logic [3:0] __t``_rst_seen_q;                                                           \
    wire __t``_launch_e = __t``_pending_i && !__t``_pending_q;                        \
    wire __t``_poll_e = cap_dr && __t``_tdr_sel;                                      \
    wire __t``_settled_poll_e = __t``_poll_e && !__t``_pending_i && __t``_inflight_q; \
    wire __t``_comp_e = __t``_pending_q && !__t``_pending_i && !in_reset;             \
    wire __t``_success_e = __t``_comp_e && (__t``_status_i == StSuccess);             \
    wire __t``_gated_attempt_e = dr_committed && __t``_tdr_sel && (__dis);            \
    always_ff @(posedge tck_i) begin                                                        \
      __t``_pending_q <= __t``_pending_i;                                                   \
      __t``_dis_q <= (__dis);                                                               \
      if (__t``_launch_e) begin                                                             \
        __t``_inflight_q <= 1'b1;                                                           \
        __t``_polls_q <= '0;                                                                \
      end else if (__t``_settled_poll_e) begin                                              \
        __t``_inflight_q <= 1'b0;                                                           \
      end else if (__t``_poll_e && __t``_inflight_q && (__t``_polls_q != 3'd7)) begin       \
        __t``_polls_q <= __t``_polls_q + 3'd1;                                              \
      end                                                                                   \
      if (__t``_gated_attempt_e) __t``_had_gated_q <= 1'b1;                                 \
      else if (__t``_success_e) __t``_had_gated_q <= 1'b0;                                  \
      if (__t``_comp_e && (__t``_status_i != StSuccess)) __t``_had_err_q <= 1'b1;           \
      else if (__t``_success_e) __t``_had_err_q <= 1'b0;                                    \
      if (__t``_success_e) __t``_rst_seen_q <= rst_events_q;                                \
    end                                                                                     \
    wire __t``_op_write_e = __t``_comp_e && (__t``_op_i == OpWrite);                  \
    wire __t``_op_read_e = __t``_comp_e && (__t``_op_i == OpRead);                    \
    wire __t``_op_nop_e = __t``_poll_e && !__t``_pending_i && !__t``_inflight_q;      \
    wire __t``_status_success_e = __t``_success_e;                                    \
    wire __t``_status_slverr_e = __t``_comp_e && (__t``_status_i == StSlverr);        \
    wire __t``_status_decerr_e = __t``_comp_e && (__t``_status_i == StDecerr);        \
    wire __t``_status_busy_e = __t``_poll_e && __t``_pending_i;                       \
    wire __t``_poll_immediate_e = __t``_settled_poll_e && (__t``_polls_q == 3'd0);    \
    wire __t``_poll_short_e =                                                         \
        __t``_settled_poll_e && (__t``_polls_q inside {3'd1, 3'd2, 3'd3});                  \
    wire __t``_poll_long_e = __t``_settled_poll_e && (__t``_polls_q >= 3'd4);         \
    wire __t``_series_incr_e = dr_committed && (|(inst_decoded_i & (__sincr)));       \
    wire __t``_series_no_incr_e = dr_committed && (|(inst_decoded_i & (__snoincr)));  \
    wire __t``_series_stat_e = dr_committed && (|(inst_decoded_i & (__sstat)));       \
    wire __t``_gating_release_e = !(__dis) && __t``_dis_q && __t``_had_gated_q;       \
    wire __t``_gating_recovery_e = __t``_success_e && __t``_had_gated_q;              \
    wire __t``_recovery_rw_after_error_e = __t``_success_e && __t``_had_err_q;        \
    wire __t``_recovery_next_nop_e = __t``_settled_poll_e && __t``_had_err_q;         \
    wire __t``_recovery_reset_abort_e =                                               \
        __t``_success_e && (__t``_rst_seen_q != rst_events_q);                              \
    wire [3:0] __t``_lanes =                                                          \
        4'($countones((__t``_wstrb_i >> (__t``_addr_i % $bits(__t``_wstrb_i)))              \
                      & ((1 << (1 << __t``_size_i)) - 1)));                                 \
    wire __t``_wstrb_none_e = __t``_op_write_e && (__t``_lanes == 4'd0);              \
    wire __t``_wstrb_single_e = __t``_op_write_e && (__t``_lanes == 4'd1);            \
    wire __t``_wstrb_all_e =                                                          \
        __t``_op_write_e && (__t``_lanes == 4'((1 << __t``_size_i)));                       \
    wire __t``_wstrb_partial_e = __t``_op_write_e && (__t``_lanes != 4'd0)            \
        && (__t``_lanes != 4'd1) && (__t``_lanes != 4'((1 << __t``_size_i)));               \
    wire __t``_addr_aligned_e = __t``_comp_e                                          \
        && ((__t``_addr_i & ((1 << __t``_size_i) - 1)) == '0);                              \
    wire __t``_addr_boundary_e = __t``_comp_e                                         \
        && ((32'(__t``_addr_i) + (32'h1 << __t``_size_i)) == 32'(MemBytes));                \
    `OCAH_FCOV_COVER(c_``__t``_op_write, __t``_op_write_e, tck_i, in_reset)                 \
    `OCAH_FCOV_COVER(c_``__t``_op_read, __t``_op_read_e, tck_i, in_reset)                   \
    `OCAH_FCOV_COVER(c_``__t``_op_nop, __t``_op_nop_e, tck_i, in_reset)                     \
    `OCAH_FCOV_COVER(c_``__t``_status_success, __t``_status_success_e, tck_i, in_reset)     \
    `OCAH_FCOV_COVER(c_``__t``_status_slverr, __t``_status_slverr_e, tck_i, in_reset)       \
    `OCAH_FCOV_COVER(c_``__t``_status_decerr, __t``_status_decerr_e, tck_i, in_reset)       \
    `OCAH_FCOV_COVER(c_``__t``_status_busy_or_full, __t``_status_busy_e, tck_i, in_reset)   \
    `OCAH_FCOV_COVER(c_``__t``_poll_immediate, __t``_poll_immediate_e, tck_i, in_reset)     \
    `OCAH_FCOV_COVER(c_``__t``_poll_short_wait, __t``_poll_short_e, tck_i, in_reset)        \
    `OCAH_FCOV_COVER(c_``__t``_poll_long_wait, __t``_poll_long_e, tck_i, in_reset)          \
    `OCAH_FCOV_COVER(c_``__t``_series_incr, __t``_series_incr_e, tck_i, in_reset)           \
    `OCAH_FCOV_COVER(c_``__t``_series_no_incr, __t``_series_no_incr_e, tck_i, in_reset)     \
    `OCAH_FCOV_COVER(c_``__t``_series_with_error_status, __t``_series_stat_e,               \
                     tck_i, in_reset)                                                       \
    `OCAH_FCOV_COVER(c_``__t``_gated_attempt, __t``_gated_attempt_e, tck_i, in_reset)       \
    `OCAH_FCOV_COVER(c_``__t``_gating_release_no_replay, __t``_gating_release_e,            \
                     tck_i, in_reset)                                                       \
    `OCAH_FCOV_COVER(c_``__t``_gating_recovery, __t``_gating_recovery_e, tck_i, in_reset)   \
    `OCAH_FCOV_COVER(c_``__t``_recovery_next_rw_after_error,                                \
                     __t``_recovery_rw_after_error_e, tck_i, in_reset)                      \
    `OCAH_FCOV_COVER(c_``__t``_recovery_next_nop, __t``_recovery_next_nop_e,                \
                     tck_i, in_reset)                                                       \
    `OCAH_FCOV_COVER(c_``__t``_recovery_reset_abort, __t``_recovery_reset_abort_e,          \
                     tck_i, in_reset)                                                       \
    `OCAH_FCOV_COVER(c_``__t``_wstrb_none, __t``_wstrb_none_e, tck_i, in_reset)             \
    `OCAH_FCOV_COVER(c_``__t``_wstrb_single_byte, __t``_wstrb_single_e, tck_i, in_reset)    \
    `OCAH_FCOV_COVER(c_``__t``_wstrb_partial, __t``_wstrb_partial_e, tck_i, in_reset)       \
    `OCAH_FCOV_COVER(c_``__t``_wstrb_all_bytes, __t``_wstrb_all_e, tck_i, in_reset)         \
    `OCAH_FCOV_COVER(c_``__t``_addr_aligned, __t``_addr_aligned_e, tck_i, in_reset)         \
    `OCAH_FCOV_COVER(c_``__t``_addr_boundary, __t``_addr_boundary_e, tck_i, in_reset)

  `DTP_J2A_TCK_FCOV(smc_axi, dbg_disable_i.smc_jtag2axi, SmcAxiSingleOp, SmcAxiSeriesIncr,
                    SmcAxiSeriesNoIncr, SmcAxiSeriesStat)
  `DTP_J2A_TCK_FCOV(smc_otp, dbg_disable_i.smc_otp_jtag2axi, SmcOtpSingleOp, SmcOtpSeriesIncr,
                    SmcOtpSeriesNoIncr, SmcOtpSeriesStat)
  `DTP_J2A_TCK_FCOV(sep_otp, dbg_disable_i.sep_otp_jtag2axi, SepOtpSingleOp, SepOtpSeriesIncr,
                    SepOtpSeriesNoIncr, SepOtpSeriesStat)
  `undef DTP_J2A_TCK_FCOV

  // Transfer-size bins (byte widths supported by the target): the SMC fabric
  // bridge carries 1/2/4/8-byte sizes; the OTP AXI-Lite bridges are fixed
  // 4-byte, so only their supported width is declared.
  wire smc_axi_size_1b_e = smc_axi_comp_e && (smc_axi_size_i == 3'd0);
  wire smc_axi_size_2b_e = smc_axi_comp_e && (smc_axi_size_i == 3'd1);
  wire smc_axi_size_4b_e = smc_axi_comp_e && (smc_axi_size_i == 3'd2);
  wire smc_axi_size_8b_e = smc_axi_comp_e && (smc_axi_size_i == 3'd3);
  wire smc_otp_size_4b_e = smc_otp_comp_e && (smc_otp_size_i == 3'd2);
  wire sep_otp_size_4b_e = sep_otp_comp_e && (sep_otp_size_i == 3'd2);
  `OCAH_FCOV_COVER(c_smc_axi_size_1b, smc_axi_size_1b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_axi_size_2b, smc_axi_size_2b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_axi_size_4b, smc_axi_size_4b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_axi_size_8b, smc_axi_size_8b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_otp_size_4b, smc_otp_size_4b_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_otp_size_4b, sep_otp_size_4b_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // Per-target system-clock section: channel skew, reset timing, and CDC
  // recovery classes. The write-phase flops clear through B or reset; their
  // preponed values at rst_fell_e describe the aborted transaction.
  // ------------------------------------------------------------------
  `define DTP_J2A_CLK_FCOV(__t)                                                             \
    logic __t``_aw_done_q;                                                                  \
    logic __t``_w_done_q;                                                                   \
    logic __t``_rd_out_q;                                                                   \
    wire __t``_aw_hs = __t``_awvalid_i && __t``_awready_i;                            \
    wire __t``_w_hs = __t``_wvalid_i && __t``_wready_i;                               \
    wire __t``_b_hs = __t``_bvalid_i && __t``_bready_i;                               \
    wire __t``_ar_hs = __t``_arvalid_i && __t``_arready_i;                            \
    wire __t``_r_hs = __t``_rvalid_i && __t``_rready_i;                               \
    always_ff @(posedge clk_i) begin                                                        \
      if (!rst_ni) begin                                                                    \
        __t``_aw_done_q <= 1'b0;                                                            \
        __t``_w_done_q <= 1'b0;                                                             \
        __t``_rd_out_q <= 1'b0;                                                             \
      end else begin                                                                        \
        if (__t``_b_hs) begin                                                               \
          __t``_aw_done_q <= 1'b0;                                                          \
          __t``_w_done_q <= 1'b0;                                                           \
        end else begin                                                                      \
          if (__t``_aw_hs) __t``_aw_done_q <= 1'b1;                                         \
          if (__t``_w_hs) __t``_w_done_q <= 1'b1;                                           \
        end                                                                                 \
        if (__t``_ar_hs) __t``_rd_out_q <= 1'b1;                                            \
        else if (__t``_r_hs) __t``_rd_out_q <= 1'b0;                                        \
      end                                                                                   \
    end                                                                                     \
    wire __t``_skew_aw_before_w_e = __t``_aw_hs && !__t``_wvalid_i;                   \
    wire __t``_skew_w_before_aw_e =                                                   \
        __t``_wvalid_i && __t``_awvalid_i && !__t``_awready_i;                              \
    wire __t``_read_held_e = __t``_arvalid_i && !__t``_arready_i;                     \
    wire __t``_reset_idle_e = rst_fell_e && !__t``_aw_done_q && !__t``_rd_out_q       \
        && !__t``_awvalid_i && !__t``_wvalid_i && !__t``_arvalid_i;                         \
    wire __t``_reset_request_e = rst_fell_e && ((__t``_awvalid_i                      \
        && !__t``_aw_done_q) || (__t``_arvalid_i && !__t``_rd_out_q));                      \
    wire __t``_reset_data_e = rst_fell_e                                              \
        && ((__t``_aw_done_q && !__t``_w_done_q) || (__t``_wvalid_i && !__t``_w_done_q));   \
    wire __t``_reset_response_e = rst_fell_e                                          \
        && ((__t``_aw_done_q && __t``_w_done_q) || __t``_rd_out_q);                         \
    `OCAH_FCOV_COVER(c_``__t``_skew_aw_before_w, __t``_skew_aw_before_w_e, clk_i, clk_in_reset)  \
    `OCAH_FCOV_COVER(c_``__t``_skew_w_before_aw, __t``_skew_w_before_aw_e, clk_i, clk_in_reset)  \
    `OCAH_FCOV_COVER(c_``__t``_skew_read_response_held, __t``_read_held_e, clk_i, clk_in_reset)  \
    `OCAH_FCOV_COVER(c_``__t``_reset_timing_idle, __t``_reset_idle_e, clk_i, 1'b0)          \
    `OCAH_FCOV_COVER(c_``__t``_reset_timing_request_issued, __t``_reset_request_e,          \
                     clk_i, 1'b0)                                                           \
    `OCAH_FCOV_COVER(c_``__t``_reset_timing_data_phase, __t``_reset_data_e, clk_i, 1'b0)    \
    `OCAH_FCOV_COVER(c_``__t``_reset_timing_response_wait, __t``_reset_response_e,          \
                     clk_i, 1'b0)                                                           \
    `OCAH_FCOV_COVER(c_``__t``_cdc_clear, __t``_reset_request_e, clk_i, 1'b0)               \
    `OCAH_FCOV_COVER(c_``__t``_cdc_isolate, __t``_reset_data_e, clk_i, 1'b0)

  `DTP_J2A_CLK_FCOV(smc_axi)
  `DTP_J2A_CLK_FCOV(smc_otp)
  `DTP_J2A_CLK_FCOV(sep_otp)
  `undef DTP_J2A_CLK_FCOV

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups mirroring the cover-property bins.
  // Target encoding: 0 = smc_axi, 1 = smc_otp, 2 = sep_otp.
  // ------------------------------------------------------------------
  covergroup cg_jtag2axi_single_op with function sample (
      logic [1:0] tgt,
      logic [1:0] op,
      logic [2:0] size,
      logic [3:0] lanes,
      logic aligned,
      logic boundary
  );
    option.per_instance = 1;
    cp_target: coverpoint tgt {bins smc_axi = {2'd0}; bins smc_otp = {2'd1}; bins sep_otp = {2'd2};}
    cp_op: coverpoint op {bins read_op = {OpRead}; bins write_op = {OpWrite};}
    cp_size: coverpoint size {bins size_bytes[] = {[0 : 3]};}
    cp_wstrb: coverpoint lanes {
      bins none = {4'd0};
      bins single_byte = {4'd1};
      bins partial = {[4'd2 : 4'd7]};
      bins all_bytes = {4'd8};
    }
    cp_addr: coverpoint {
      aligned, boundary
    } {
      bins aligned_bin = {2'b10}; bins boundary_bin = {2'b11};
    }
  endgroup

  covergroup cg_jtag2axi_response with function sample (
      logic [1:0] tgt, logic [1:0] status, logic [2:0] polls
  );
    option.per_instance = 1;
    cp_target: coverpoint tgt {bins smc_axi = {2'd0}; bins smc_otp = {2'd1}; bins sep_otp = {2'd2};}
    cp_status: coverpoint status {
      bins success = {StSuccess}; bins slverr = {StSlverr}; bins decerr = {StDecerr};
    }
    cp_poll: coverpoint polls {
      bins immediate = {3'd0}; bins short_wait = {[3'd1 : 3'd3]}; bins long_wait = {[3'd4 : 3'd7]};
    }
  endgroup

  cg_jtag2axi_single_op u_cg_single_op = new();
  cg_jtag2axi_response u_cg_response = new();

  `define DTP_J2A_CG_SAMPLE(__t, __id)                                                     \
    always_ff @(posedge tck_i) begin                                                       \
      if (__t``_comp_e) begin                                                              \
        u_cg_single_op.sample(__id, __t``_op_i, __t``_size_i, __t``_lanes,                 \
                              __t``_addr_aligned_e, __t``_addr_boundary_e);                \
        u_cg_response.sample(__id, __t``_status_i, __t``_polls_q);                         \
      end                                                                                  \
    end

  `DTP_J2A_CG_SAMPLE(smc_axi, 2'd0)
  `DTP_J2A_CG_SAMPLE(smc_otp, 2'd1)
  `DTP_J2A_CG_SAMPLE(sep_otp, 2'd2)
  `undef DTP_J2A_CG_SAMPLE
`endif

endmodule : dtp_jtag2axi_fcov
