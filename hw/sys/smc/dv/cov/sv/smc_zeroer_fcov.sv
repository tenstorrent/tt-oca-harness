// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC zeroer functional coverage: the command registers, the write-only FSM
// walk from idle through address and data phases and back, the zero payload,
// and the two clock gates the zeroer chapter describes term by term.
//
// The FSM encoding is one-hot-ish with a fail-closed ST_ERROR at 3'b000, so
// the state points compare against the named encodings rather than a range.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_zeroer_fcov (
  input wire clk_smc_i,
  input wire rst_cold_ni,
  // The zeroer's own reset, which is one of the terms of its AXI clock enable.
  input wire rst_primary_smc_clk_ni,

  // Command registers and their register-block strobes.
  input wire [63:0] dest_addr_i,
  input wire [63:0] size_i,
  input wire strb_dest_i,
  input wire strb_size_i,
  input wire req_is_wr_i,
  input wire trigger_i,
  input wire status_read_i,

  // FSM and busy.
  input wire [2:0] state_i,
  input wire busy_i,
  input wire intp_i,
  input wire [31:0] outstanding_i,

  // AXI master write path.
  input wire awvalid_i,
  input wire awready_i,
  input wire [55:0] awaddr_i,
  input wire [7:0] awlen_i,
  input wire wvalid_i,
  input wire wready_i,
  input wire wlast_i,
  input wire [7:0] wstrb_i,
  input wire [63:0] wdata_i,
  input wire bvalid_i,

  // Clock gating.
  input wire disable_cg_i,
  input wire axi_clk_enable_i,
  input wire gated_axi_clk_i,
  input wire gated_reg_clk_i,
  input wire bus_active_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  localparam logic [2:0] StIdle = 3'b001;
  localparam logic [2:0] StIssueAddr = 3'b010;
  localparam logic [2:0] StIssueData = 3'b100;

  // ------------------------------------------------------------------
  // Command registers. A read of DEST_ADDR / SIZE is the register-block
  // strobe with the write flag clear, qualified by the field holding a
  // programmed value so a read of the reset value proves nothing.
  // ------------------------------------------------------------------
  wire reg_read = (req_is_wr_i === 1'b0);
  wire dest_addr_readback_e = (strb_dest_i === 1'b1) && reg_read && (dest_addr_i !== 64'd0)
      && (^dest_addr_i !== 1'bx);
  wire size_readback_e = (strb_size_i === 1'b1) && reg_read && (size_i !== 64'd0)
      && (^size_i !== 1'bx);
  `OCAH_FCOV_COVER(c_dest_addr_readback, dest_addr_readback_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_size_readback, size_readback_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // FSM walk. Every state point is an edge or is qualified by the engine
  // having left idle once, so none of them is true at reset release.
  // ------------------------------------------------------------------
  logic [2:0] state_q;
  logic busy_q;
  logic left_idle_seen_q;
  // The trigger is consumed in ST_IDLE and the state register moves on the
  // next edge, so the trigger is held for the comparison rather than paired
  // with the transition in the same sample.
  logic trigger_pending_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      state_q <= StIdle;
      busy_q <= 1'b0;
      left_idle_seen_q <= 1'b0;
      trigger_pending_q <= 1'b0;
    end else begin
      state_q <= state_i;
      busy_q <= busy_i;
      if (state_i === StIssueAddr) left_idle_seen_q <= 1'b1;
      if (trigger_i === 1'b1) trigger_pending_q <= 1'b1;
      else if (state_i !== StIdle) trigger_pending_q <= 1'b0;
    end
  end

  wire aw_acc = (awvalid_i === 1'b1) && (awready_i === 1'b1);
  wire w_acc = (wvalid_i === 1'b1) && (wready_i === 1'b1);
  wire w_last_acc = w_acc && (wlast_i === 1'b1);

  wire trigger_starts_e = trigger_pending_q && (state_q === StIdle)
      && (state_i === StIssueAddr);
  wire busy_set_e = (busy_i === 1'b1) && (busy_q === 1'b0);
  wire busy_cleared_e = (busy_i === 1'b0) && (busy_q === 1'b1) && (outstanding_i === 32'd0);
  `OCAH_FCOV_COVER(c_trigger_write_starts_operation, trigger_starts_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_busy_set_on_start, busy_set_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_busy_cleared_on_completion, busy_cleared_e, clk_smc_i, in_reset)

  wire idle_no_axi_e = left_idle_seen_q && (state_i === StIdle) && (awvalid_i === 1'b0)
      && (wvalid_i === 1'b0);
  wire addr_phase_issues_aw_e = (state_i === StIssueAddr) && aw_acc;
  `OCAH_FCOV_COVER(c_idle_state_no_axi_activity, idle_no_axi_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_address_phase_issues_aw, addr_phase_issues_aw_e, clk_smc_i, in_reset)

  // Beat count against address count over one operation. Both counters
  // restart in the trigger sample, which is also the sample of the first
  // address beat, so the comparison spans exactly one programmed operation.
  logic [15:0] aw_count_q, wlast_count_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      aw_count_q <= '0;
      wlast_count_q <= '0;
    end else if (trigger_starts_e) begin
      aw_count_q <= 16'(aw_acc);
      wlast_count_q <= 16'(w_last_acc);
    end else begin
      if (aw_acc) aw_count_q <= aw_count_q + 16'd1;
      if (w_last_acc) wlast_count_q <= wlast_count_q + 16'd1;
    end
  end

  wire return_to_idle_e = (state_q === StIssueData) && (state_i === StIdle);
  // The final WLAST is accepted in the same sample as the return to idle, so
  // it is added to the registered count before the comparison.
  wire [15:0] wlast_count_now = wlast_count_q + 16'(w_last_acc);
  wire beat_count_matches_e = return_to_idle_e && (aw_count_q !== 16'd0)
      && (wlast_count_now === aw_count_q);

  // Busy stays asserted at the return to idle until the outstanding write
  // responses drain, so the status update is the drain completing after that
  // return rather than a value read in the same sample.
  logic returned_to_idle_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) returned_to_idle_q <= 1'b0;
    else if (return_to_idle_e) returned_to_idle_q <= 1'b1;
    else if (state_i !== StIdle) returned_to_idle_q <= 1'b0;
  end

  wire completion_status_e = returned_to_idle_q && (state_i === StIdle)
      && ((intp_i === 1'b1) || ((busy_i === 1'b0) && (busy_q === 1'b1)));
  `OCAH_FCOV_COVER(c_data_phase_beat_count_matches_addresses, beat_count_matches_e, clk_smc_i,
                   in_reset)
  `OCAH_FCOV_COVER(c_return_to_idle, return_to_idle_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_completion_status_updated, completion_status_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Payload. The point is an accepted beat carrying zero on every enabled
  // lane while no non-zero beat has ever been seen, so one non-zero beat
  // anywhere in the run permanently retires it.
  // ------------------------------------------------------------------
  logic nonzero_beat_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) nonzero_beat_seen_q <= 1'b0;
    else if (w_acc && (wdata_i !== 64'd0)) nonzero_beat_seen_q <= 1'b1;
  end

  wire every_beat_is_zero_e = w_acc && !nonzero_beat_seen_q && (wdata_i === 64'd0)
      && (wstrb_i !== 8'd0);
  `OCAH_FCOV_COVER(c_every_beat_is_zero, every_beat_is_zero_e, clk_smc_i, in_reset)

  // The first address of an operation equalling the programmed destination,
  // and a burst longer than one beat: the two shapes the FSM emits.
  wire first_aw_of_op = trigger_starts_e || (aw_count_q === 16'd0);
  wire first_aw_at_dest_e = aw_acc && first_aw_of_op && (awaddr_i === 56'(dest_addr_i))
      && (dest_addr_i !== 64'd0);
  wire multi_beat_burst_e = aw_acc && (awlen_i !== 8'd0) && (^awlen_i !== 1'bx);
  `OCAH_FCOV_COVER(c_zeroer_first_aw_at_dest, first_aw_at_dest_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_multi_beat_burst, multi_beat_burst_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Clock gates, term by term. The AXI clock enable is
  // disable_cg | busy | ~rst_ni; the register clock is kicked by disable_cg
  // alone and otherwise follows the AXI-Lite snoop.
  // ------------------------------------------------------------------
  logic axi_clk_q, reg_clk_q;
  logic axi_clk_moved_q, reg_clk_moved_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      axi_clk_q <= 1'b0;
      reg_clk_q <= 1'b0;
      axi_clk_moved_q <= 1'b0;
      reg_clk_moved_q <= 1'b0;
    end else begin
      axi_clk_q <= gated_axi_clk_i;
      reg_clk_q <= gated_reg_clk_i;
      if (gated_axi_clk_i !== axi_clk_q) axi_clk_moved_q <= 1'b1;
      if (gated_reg_clk_i !== reg_clk_q) reg_clk_moved_q <= 1'b1;
    end
  end

  wire axi_clk_toggling = (gated_axi_clk_i !== axi_clk_q);
  wire reg_clk_toggling = (gated_reg_clk_i !== reg_clk_q);
  wire zeroer_in_reset = (rst_primary_smc_clk_ni === 1'b0);
  wire disable_cg = (disable_cg_i === 1'b1);
  wire busy = (busy_i === 1'b1);

  wire axi_clk_on_disable_cg_e = disable_cg && !busy && !zeroer_in_reset && axi_clk_toggling;
  wire axi_clk_on_busy_e = busy && !disable_cg && axi_clk_toggling;
  wire axi_clk_on_reset_e = zeroer_in_reset && (axi_clk_enable_i === 1'b1);
  wire axi_clk_gated_idle_e = axi_clk_moved_q && !disable_cg && !busy && !zeroer_in_reset
      && !axi_clk_toggling;
  `OCAH_FCOV_COVER(c_axi_clk_on_disable_cg, axi_clk_on_disable_cg_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_clk_on_busy, axi_clk_on_busy_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_clk_on_reset, axi_clk_on_reset_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_clk_gated_when_idle, axi_clk_gated_idle_e, clk_smc_i, in_reset)

  wire bus_active = (bus_active_i === 1'b1);
  wire reg_clk_on_disable_cg_e = disable_cg && !bus_active && !zeroer_in_reset && reg_clk_toggling;
  wire reg_clk_on_activity_e = bus_active && !disable_cg && reg_clk_toggling;
  wire reg_clk_on_reset_e = zeroer_in_reset && reg_clk_toggling;
  wire reg_clk_gated_idle_e = reg_clk_moved_q && !disable_cg && !bus_active && !zeroer_in_reset
      && !reg_clk_toggling;
  `OCAH_FCOV_COVER(c_reg_clk_on_disable_cg, reg_clk_on_disable_cg_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_reg_clk_on_activity, reg_clk_on_activity_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_reg_clk_on_reset, reg_clk_on_reset_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_reg_clk_gated_when_idle, reg_clk_gated_idle_e, clk_smc_i, in_reset)

  // Status readback and the response channel, kept so a silent operation is
  // distinguishable from one whose writes were never answered.
  wire status_read_e = (status_read_i === 1'b1);
  wire b_response_e = (bvalid_i === 1'b1);
  `OCAH_FCOV_COVER(c_zeroer_status_read, status_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_write_response, b_response_e, clk_smc_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups: the FSM transition table and the
  // gate-term crosses, neither of which a flat point list can express.
  // ------------------------------------------------------------------
  covergroup cg_zeroer_fsm with function sample (logic [2:0] prev, logic [2:0] cur);
    option.per_instance = 1;
    cp_prev: coverpoint prev {
      bins error_s = {3'b000};
      bins idle = {3'b001};
      bins issue_addr = {3'b010};
      bins issue_data = {3'b100};
      bins other = default;
    }
    cp_cur: coverpoint cur {
      bins error_s = {3'b000};
      bins idle = {3'b001};
      bins issue_addr = {3'b010};
      bins issue_data = {3'b100};
      bins other = default;
    }
    // The FSM leaves ST_IDLE only for ST_ISSUE_ADDR and ST_ISSUE_ADDR only
    // for ST_ISSUE_DATA; ST_ERROR is entered only from an encoding outside the
    // enum and is never left. The remaining pairs are not transitions the
    // FSM can make.
    x_transition: cross cp_prev, cp_cur{
      ignore_bins from_idle = binsof(cp_prev.idle) &&
          (binsof(cp_cur.issue_data) || binsof(cp_cur.error_s));
      ignore_bins from_issue_addr = binsof(cp_prev.issue_addr) &&
          (binsof(cp_cur.idle) || binsof(cp_cur.error_s));
      ignore_bins from_issue_data = binsof (cp_prev.issue_data) && binsof (cp_cur.error_s);
      ignore_bins leaving_error = binsof (cp_prev.error_s) && !binsof (cp_cur.error_s);
    }
  endgroup

  covergroup cg_zeroer_gates with function sample (
      logic dis_cg, logic busy_s, logic rst_s, logic bus_act, logic axi_moving, logic reg_moving
  );
    option.per_instance = 1;
    cp_dis_cg: coverpoint dis_cg;
    cp_busy: coverpoint busy_s;
    cp_rst: coverpoint rst_s;
    cp_bus: coverpoint bus_act;
    cp_axi_clk: coverpoint axi_moving;
    cp_reg_clk: coverpoint reg_moving;
    x_axi_terms: cross cp_dis_cg, cp_busy, cp_axi_clk;
    x_reg_terms: cross cp_dis_cg, cp_bus, cp_reg_clk;
  endgroup

  cg_zeroer_fsm u_cg_zeroer_fsm = new();
  cg_zeroer_gates u_cg_zeroer_gates = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      u_cg_zeroer_fsm.sample(state_q, state_i);
      u_cg_zeroer_gates.sample(disable_cg_i, busy_i, zeroer_in_reset, bus_active_i,
                               axi_clk_toggling, reg_clk_toggling);
    end
  end
`endif

endmodule : smc_zeroer_fcov
