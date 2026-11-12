// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC reset functional coverage: the `reset_op` and `reset_state` intent of
// SMC_FCOV.adoc expressed as native cover-property points, so the public
// flow records them in the `user` metric family (--coverage-user) instead
// of only as scoreboard log text. It also hosts smc_reset_kind_inflight_cg,
// the reset kind against the operation it interrupts and the register class
// it clears.
//
// NOTE: a `//` comment must not open with the word "verilator" -- the
// lexer reads it as a pragma and BADVLTPRAGMA fails the build.
//
// One instance in the shared tb_top serves both the cocotb/PyUVM and SV-UVM
// flows. Every port is a smc_tb_signal_list.svh signal, so the module needs
// no hierarchical reference and no `smc_public_scope.vlt` change.
//
// DISABLE CONVENTION, unlike the rest of the SMC cov/sv modules: the gate is
// powergood, not reset. A reset-assertion point behind `disable iff (in
// reset)` can never fire. Once power is good the signals are driven and reset
// assertion itself stays observable. smc_powergood_glitch_cg is the one
// exception: its stimulus is the powergood_i low run, so its trackers are
// qualified by tb_fcov_gate alone and clear only when the gate rises, and its
// glitch-length sample is taken when the gate falls.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_reset_fcov #(
  parameter int unsigned CPU_CLUSTER_COUNT = 4
) (
  input wire clk_ref_i,
  input wire clk_smc_i,

  // Reset stimulus (TB -> DUT).
  input wire powergood_i,
  input wire rst_cold_ni,
  input wire rst_cool_ni,
  input wire sep_wdt_reset_ni,
  input wire cfg_flr_pf_active_i,
  input wire [CPU_CLUSTER_COUNT-1:0] ndmreset_request_i,

  // Reset observables (DUT -> TB).
  input wire powergood_stable_i,
  input wire rst_cold_stable_ref_clk_ni,
  input wire rst_primary_ref_clk_ni,
  input wire rst_primary_smc_clk_ni,
  input wire rst_wdt_smc_clk_ni,
  input wire rst_warm_smc_clk_ni,
  input wire rst_cool_from_flr_ni,
  input wire fuse_reset_ni,
  input wire ss0_warm_reset_ni,
  input wire [CPU_CLUSTER_COUNT-1:0] ndmreset_process_i,
  input wire ndmreset_irq_i,

  // The interrupt aggregates the power-good glitch owner grades.
  input wire sync_irq_i,
  input wire gpio_irq_any_i,
  input wire uart_irq_any_i,

  // SEP_IN channels: the SPM burst in flight and the register read-back.
  input wire sep_awvalid_i,
  input wire sep_awready_i,
  input wire [55:0] sep_awaddr_i,
  input wire sep_wvalid_i,
  input wire sep_wready_i,
  input wire sep_wlast_i,
  input wire [63:0] sep_wdata_i,
  input wire sep_bvalid_i,
  input wire sep_bready_i,
  input wire [1:0] sep_bresp_i,
  input wire sep_arvalid_i,
  input wire sep_arready_i,
  input wire [55:0] sep_araddr_i,
  input wire sep_rvalid_i,
  input wire sep_rready_i,
  input wire sep_rlast_i,
  input wire [1:0] sep_rresp_i,
  input wire [63:0] sep_rdata_i,

  // Engine activity and the SYS_OUT channels the engines move data on.
  input wire dma_busy_i,
  input wire zeroer_busy_i,
  input wire out_awvalid_i,
  input wire out_awready_i,
  input wire out_wvalid_i,
  input wire out_wready_i,
  input wire out_wlast_i,
  input wire out_bvalid_i,
  input wire out_bready_i,
  input wire out_arvalid_i,
  input wire out_arready_i,
  input wire out_rvalid_i,
  input wire out_rready_i,
  input wire out_rlast_i,

  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire fcov_gate_i
);

  import smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_SIZE;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR;

  // Powergood-only gate; see the DISABLE CONVENTION note in the header.
  wire not_powered = (powergood_i !== 1'b1);

  // ------------------------------------------------------------------
  // reset_op — each reset source seen asserted, one point per source so a
  // source with no stimulus stays a named, individually reportable hole.
  // ------------------------------------------------------------------
  wire cold_asserted_e = (rst_cold_ni === 1'b0);
  wire cool_asserted_e = (rst_cool_ni === 1'b0);
  wire sep_wdt_asserted_e = (sep_wdt_reset_ni === 1'b0);
  wire flr_pf_active_e = (cfg_flr_pf_active_i === 1'b1);
  wire cool_from_flr_asserted_e = (rst_cool_from_flr_ni === 1'b0);
  `OCAH_FCOV_COVER(c_reset_op_cold_asserted, cold_asserted_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_op_cool_asserted, cool_asserted_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_op_sep_wdt_asserted, sep_wdt_asserted_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_op_flr_pf_active, flr_pf_active_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_op_cool_from_flr, cool_from_flr_asserted_e, clk_ref_i, not_powered)

  wire wdt_asserted_e = (rst_wdt_smc_clk_ni === 1'b0);
  wire warm_asserted_e = (rst_warm_smc_clk_ni === 1'b0);
  wire ss0_warm_asserted_e = (ss0_warm_reset_ni === 1'b0);
  wire ndm_requested_e = (ndmreset_request_i !== '0);
  wire ndm_processed_e = (ndmreset_process_i !== '0);
  wire ndm_irq_e = (ndmreset_irq_i === 1'b1);
  `OCAH_FCOV_COVER(c_reset_op_wdt_asserted, wdt_asserted_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_op_warm_asserted, warm_asserted_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_op_ss0_warm_asserted, ss0_warm_asserted_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_op_ndm_requested, ndm_requested_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_op_ndm_processed, ndm_processed_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_op_ndm_irq, ndm_irq_e, clk_smc_i, not_powered)

  // ------------------------------------------------------------------
  // Release edges — the ordered bring-up the reset tests walk. A rising
  // edge is a strictly stronger observation than the released level: the
  // level is true for the whole run once bring-up completes.
  // ------------------------------------------------------------------
  logic powergood_stable_q, cold_stable_q, primary_ref_q;
  always_ff @(posedge clk_ref_i) begin
    powergood_stable_q <= powergood_stable_i;
    cold_stable_q <= rst_cold_stable_ref_clk_ni;
    primary_ref_q <= rst_primary_ref_clk_ni;
  end

  wire release_powergood_stable_e = (powergood_stable_i === 1'b1) && (powergood_stable_q === 1'b0);
  wire release_cold_stable_e =
      (rst_cold_stable_ref_clk_ni === 1'b1) && (cold_stable_q === 1'b0);
  wire release_primary_ref_e = (rst_primary_ref_clk_ni === 1'b1) && (primary_ref_q === 1'b0);
  `OCAH_FCOV_COVER(c_release_powergood_stable, release_powergood_stable_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_release_cold_stable_ref, release_cold_stable_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_release_primary_ref, release_primary_ref_e, clk_ref_i, not_powered)

  logic primary_smc_q, fuse_reset_q, warm_smc_q;
  always_ff @(posedge clk_smc_i) begin
    primary_smc_q <= rst_primary_smc_clk_ni;
    fuse_reset_q <= fuse_reset_ni;
    warm_smc_q <= rst_warm_smc_clk_ni;
  end

  wire release_primary_smc_e = (rst_primary_smc_clk_ni === 1'b1) && (primary_smc_q === 1'b0);
  wire release_fuse_reset_e = (fuse_reset_ni === 1'b1) && (fuse_reset_q === 1'b0);
  wire release_warm_smc_e = (rst_warm_smc_clk_ni === 1'b1) && (warm_smc_q === 1'b0);
  `OCAH_FCOV_COVER(c_release_primary_smc, release_primary_smc_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_release_fuse_reset, release_fuse_reset_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_release_warm_smc, release_warm_smc_e, clk_smc_i, not_powered)

  // Re-assertion after a completed release: proof a reset test drove a
  // second reset rather than only observing the power-on one.
  wire reassert_cold_e = (rst_cold_stable_ref_clk_ni === 1'b0) && (cold_stable_q === 1'b1);
  wire reassert_primary_smc_e = (rst_primary_smc_clk_ni === 1'b0) && (primary_smc_q === 1'b1);
  `OCAH_FCOV_COVER(c_reassert_cold_after_release, reassert_cold_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reassert_primary_smc_after_release, reassert_primary_smc_e, clk_smc_i,
                   not_powered)

  // ------------------------------------------------------------------
  // reset_state — the post-reset 4-tuple as all-held / partial /
  // all-released, so the partially-released window (the mid-glitch state
  // RAW_SAMPLE observes) is its own point.
  // ------------------------------------------------------------------
  wire [3:0] reset_state_v = {powergood_stable_i, rst_cold_stable_ref_clk_ni,
                              rst_primary_ref_clk_ni, rst_primary_smc_clk_ni};
  wire reset_state_all_held_e = (reset_state_v === 4'b0000);
  wire reset_state_all_released_e = (reset_state_v === 4'b1111);
  wire reset_state_partial_e = !reset_state_all_held_e && !reset_state_all_released_e
      && (^reset_state_v !== 1'bx);
  `OCAH_FCOV_COVER(c_reset_state_all_held, reset_state_all_held_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_state_partial_release, reset_state_partial_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_state_all_released, reset_state_all_released_e, clk_ref_i, not_powered)

  // ------------------------------------------------------------------
  // Covergroups mirroring the points above. The cross of reset source
  // against release state is the part a flat list of cover properties cannot
  // express.
  // ------------------------------------------------------------------
  covergroup cg_reset_state with function sample (logic [3:0] state);
    option.per_instance = 1;
    cp_state: coverpoint state {
      bins all_held = {4'b0000};
      bins all_released = {4'b1111};
      // The partial bins list only the states the ignore_bins below leave:
      // on Verilator, a value that a bin and an ignore_bins both list counts
      // in the bin.
      bins partial[] = {4'b1000, 4'b1001, 4'b1100, 4'b1101};
      // The vector is {powergood, cold_stable_ref, primary_ref, primary_smc}.
      // powergood low holds the cold-stable reset and every primary derives
      // from it, so no lower bit rises while powergood is low.
      ignore_bins powergood_low = {[4'b0001 : 4'b0111]};
      // The ref-domain primary derives from the ref-domain cold-stable reset.
      ignore_bins primary_ref_before_cold = {4'b1010, 4'b1011};
      // Both primaries synchronise one request; the ref-domain copy, on the
      // slower clock, releases after the smc-domain copy.
      ignore_bins primary_ref_before_smc = {4'b1110};
    }
  endgroup

  covergroup cg_reset_op with function sample (
      logic cold, logic cool, logic wdt, logic warm, logic ndm, logic flr
  );
    option.per_instance = 1;
    cp_cold: coverpoint cold {bins released = {1'b0}; bins asserted = {1'b1};}
    cp_cool: coverpoint cool;
    cp_wdt: coverpoint wdt;
    cp_warm: coverpoint warm {bins released = {1'b0}; bins asserted = {1'b1};}
    cp_ndm: coverpoint ndm;
    cp_flr: coverpoint flr;
    x_cold_warm: cross cp_cold, cp_warm;
  endgroup

  cg_reset_state u_cg_reset_state = new();
  cg_reset_op u_cg_reset_op = new();

  always_ff @(posedge clk_ref_i) begin
    if (!not_powered) u_cg_reset_state.sample(reset_state_v);
  end

  always_ff @(posedge clk_smc_i) begin
    if (!not_powered) begin
      u_cg_reset_op.sample(cold_asserted_e, cool_asserted_e, wdt_asserted_e, warm_asserted_e,
                           ndm_requested_e, flr_pf_active_e);
    end
  end

  // ------------------------------------------------------------------
  // smc_reset_kind_inflight_cg (SMC_FCOV.adoc, smc_reset_kind_inflight_cg):
  // the reset kind against the operation in flight and its phase at the
  // assertion, and the register class the reset clears, inside the owner's
  // graded window. Every flop here is free of rst_cold_ni: the cold kind is
  // sampled at its own assertion and its read-back after it. clk_rst.adoc
  // does not state whether clk_smc_i runs through a cold reset, so the kind
  // is sampled on clk_ref_i, the bench-driven clock every reset leaves running.
  // ------------------------------------------------------------------
  localparam logic [1:0] KindCold = 2'd0;
  localparam logic [1:0] KindCool = 2'd1;
  localparam logic [1:0] KindFlr = 2'd2;
  localparam logic [1:0] KindWdt = 2'd3;
  localparam logic [2:0] OpSpmWr = 3'd0;
  localparam logic [2:0] OpSpmRd = 3'd1;
  localparam logic [2:0] OpDma = 3'd2;
  localparam logic [2:0] OpZeroer = 3'd3;
  localparam logic [2:0] OpNone = 3'd7;
  localparam logic [1:0] PhBefore = 2'd0;
  localparam logic [1:0] PhData = 2'd1;
  localparam logic [1:0] PhAwaiting = 2'd2;
  localparam logic [1:0] PhCompleted = 2'd3;
  localparam logic [1:0] ClsColdOnly = 2'd0;
  localparam logic [1:0] ClsPrimary = 2'd1;
  localparam logic [1:0] ClsWarmScratch = 2'd2;
  localparam logic [1:0] ClsNone = 2'd3;

  localparam logic [55:0] SpmLo = 56'(SMC_TOP_SPM_MEMORY_BASE_ADDR);
  localparam logic [55:0] SpmHi = SpmLo + 56'(SMC_TOP_SPM_MEMORY_SIZE) - 56'd1;

  function automatic logic in_spm(input logic [55:0] addr);
    return (addr >= SpmLo) && (addr <= SpmHi);
  endfunction

  wire sep_aw_acc = (sep_awvalid_i === 1'b1) && (sep_awready_i === 1'b1);
  wire sep_w_last_acc = (sep_wvalid_i === 1'b1) && (sep_wready_i === 1'b1)
      && (sep_wlast_i === 1'b1);
  wire sep_b_acc = (sep_bvalid_i === 1'b1) && (sep_bready_i === 1'b1);
  wire sep_ar_acc = (sep_arvalid_i === 1'b1) && (sep_arready_i === 1'b1);
  wire sep_r_acc = (sep_rvalid_i === 1'b1) && (sep_rready_i === 1'b1);
  wire sep_r_last_acc = sep_r_acc && (sep_rlast_i === 1'b1);

  // The in-flight trackers clear while the primary or the warm reset is
  // asserted: the interrupted transfer does not complete, and the SYS_OUT
  // responder follows the primary reset and drops its responses.
  wire trk_rst_n = (rst_primary_smc_clk_ni === 1'b1) && (rst_warm_smc_clk_ni === 1'b1);

  wire gate_on = (fcov_gate_i === 1'b1);
  logic gate_smc_q;
  always_ff @(posedge clk_smc_i) gate_smc_q <= gate_on;
  wire gate_rise_smc = gate_on && (gate_smc_q !== 1'b1);

  // SPM burst over SEP_IN, one burst at a time. Phase of a write: AW not yet
  // accepted (before), AW accepted and WLAST not (data), WLAST accepted and B
  // not returned (awaiting). Phase of a read: AR not yet accepted (before),
  // AR accepted and no R beat yet (awaiting, the R beats are the response),
  // R beats under way and RLAST not returned (data). A burst whose response
  // returned is completed until the next SPM burst starts or tb_fcov_gate
  // rises, so a completed burst is always the window's own.
  wire spm_aw_pend = (sep_awvalid_i === 1'b1) && in_spm(sep_awaddr_i);
  wire spm_ar_pend = (sep_arvalid_i === 1'b1) && in_spm(sep_araddr_i);
  logic spm_wr_act_q, spm_wr_wdone_q, spm_wr_cmpl_q;
  logic spm_rd_act_q, spm_rd_beat_q, spm_rd_cmpl_q;
  always_ff @(posedge clk_smc_i or negedge trk_rst_n) begin
    if (!trk_rst_n) begin
      spm_wr_act_q <= 1'b0;
      spm_wr_wdone_q <= 1'b0;
      spm_wr_cmpl_q <= 1'b0;
      spm_rd_act_q <= 1'b0;
      spm_rd_beat_q <= 1'b0;
      spm_rd_cmpl_q <= 1'b0;
    end else begin
      if (spm_aw_pend) spm_wr_cmpl_q <= 1'b0;
      if (spm_aw_pend && sep_aw_acc) spm_wr_act_q <= 1'b1;
      if (sep_w_last_acc && (spm_wr_act_q || spm_aw_pend)) spm_wr_wdone_q <= 1'b1;
      if (sep_b_acc && spm_wr_act_q) begin
        spm_wr_act_q <= 1'b0;
        spm_wr_wdone_q <= 1'b0;
        spm_wr_cmpl_q <= 1'b1;
      end
      if (spm_ar_pend) spm_rd_cmpl_q <= 1'b0;
      if (spm_ar_pend && sep_ar_acc) begin
        spm_rd_act_q <= 1'b1;
        spm_rd_beat_q <= 1'b0;
      end
      if (sep_r_acc && spm_rd_act_q) spm_rd_beat_q <= 1'b1;
      if (sep_r_last_acc && spm_rd_act_q) begin
        spm_rd_act_q <= 1'b0;
        spm_rd_beat_q <= 1'b0;
        spm_rd_cmpl_q <= 1'b1;
      end
      if (gate_rise_smc) begin
        spm_wr_cmpl_q <= 1'b0;
        spm_rd_cmpl_q <= 1'b0;
      end
    end
  end

  // The tracker state the current clk_smc_i edge leaves, from the handshakes
  // visible on it: a handshake accepted at an edge counts at that edge.
  wire spm_aw_new = spm_aw_pend && sep_aw_acc;
  wire spm_b_end = sep_b_acc && spm_wr_act_q;
  wire spm_wr_act_nx = (spm_wr_act_q && !spm_b_end) || spm_aw_new;
  wire spm_wr_wdone_nx = !spm_b_end
      && (spm_wr_wdone_q || (sep_w_last_acc && (spm_wr_act_q || spm_aw_pend)));
  wire spm_wr_cmpl_nx = !gate_rise_smc && (spm_b_end || (spm_wr_cmpl_q && !spm_aw_pend));
  wire spm_ar_new = spm_ar_pend && sep_ar_acc;
  wire spm_r_end = sep_r_last_acc && spm_rd_act_q;
  wire spm_rd_act_nx = (spm_rd_act_q && !spm_r_end) || spm_ar_new;
  wire spm_rd_beat_nx = !spm_r_end
      && ((sep_r_acc && spm_rd_act_q) || (spm_rd_beat_q && !spm_ar_new));
  wire spm_rd_cmpl_nx = !gate_rise_smc && (spm_r_end || (spm_rd_cmpl_q && !spm_ar_pend));

  // Engine (DMA, zeroer) traffic on SYS_OUT, counted per channel. Data: write
  // data owed after an AW or a burst of W or R beats under way. Awaiting: a
  // read address accepted with no R beat yet, or a write response owed.
  // Before: nothing outstanding, ahead of the next address handshake.
  wire out_aw_acc = (out_awvalid_i === 1'b1) && (out_awready_i === 1'b1);
  wire out_w_acc = (out_wvalid_i === 1'b1) && (out_wready_i === 1'b1);
  wire out_w_last_acc = out_w_acc && (out_wlast_i === 1'b1);
  wire out_b_acc = (out_bvalid_i === 1'b1) && (out_bready_i === 1'b1);
  wire out_ar_acc = (out_arvalid_i === 1'b1) && (out_arready_i === 1'b1);
  wire out_r_acc = (out_rvalid_i === 1'b1) && (out_rready_i === 1'b1);
  wire out_r_last_acc = out_r_acc && (out_rlast_i === 1'b1);

  // Saturating count: a response of a transfer that began before the last
  // clear does not take the count below zero.
  function automatic logic [7:0] count_step(input logic [7:0] cnt, input logic inc,
                                            input logic dec);
    logic [8:0] next;
    next = {1'b0, cnt} + {8'd0, inc};
    if (dec && (next != 9'd0)) next = next - 9'd1;
    return (next > 9'd255) ? 8'd255 : next[7:0];
  endfunction

  logic [7:0] out_ar_q, out_w_owed_q, out_b_q;
  logic out_r_mid_q, out_w_mid_q;
  wire [7:0] out_ar_nx = count_step(out_ar_q, out_ar_acc, out_r_last_acc);
  wire [7:0] out_w_owed_nx = count_step(out_w_owed_q, out_aw_acc, out_w_last_acc);
  wire [7:0] out_b_nx = count_step(out_b_q, out_w_last_acc, out_b_acc);
  wire out_r_mid_nx = out_r_acc ? !out_r_last_acc : out_r_mid_q;
  wire out_w_mid_nx = out_w_acc ? !out_w_last_acc : out_w_mid_q;
  always_ff @(posedge clk_smc_i or negedge trk_rst_n) begin
    if (!trk_rst_n) begin
      out_ar_q <= '0;
      out_w_owed_q <= '0;
      out_b_q <= '0;
      out_r_mid_q <= 1'b0;
      out_w_mid_q <= 1'b0;
    end else begin
      out_ar_q <= out_ar_nx;
      out_w_owed_q <= out_w_owed_nx;
      out_b_q <= out_b_nx;
      out_r_mid_q <= out_r_mid_nx;
      out_w_mid_q <= out_w_mid_nx;
    end
  end

  wire eng_data = out_w_mid_nx || (out_w_owed_nx != 8'd0) || out_r_mid_nx;
  wire eng_awaiting = (out_ar_nx != 8'd0) || (out_b_nx != 8'd0);
  wire [1:0] eng_phase = eng_data ? PhData : (eng_awaiting ? PhAwaiting : PhBefore);

  logic [2:0] op_now;
  logic [1:0] ph_now;
  always_comb begin
    op_now = OpNone;
    ph_now = PhBefore;
    if (spm_wr_act_nx) begin
      op_now = OpSpmWr;
      ph_now = spm_wr_wdone_nx ? PhAwaiting : PhData;
    end else if (spm_aw_pend) begin
      op_now = OpSpmWr;
    end else if (spm_rd_act_nx) begin
      op_now = OpSpmRd;
      ph_now = spm_rd_beat_nx ? PhData : PhAwaiting;
    end else if (spm_ar_pend) begin
      op_now = OpSpmRd;
    end else if (dma_busy_i === 1'b1) begin
      op_now = OpDma;
      ph_now = eng_phase;
    end else if (zeroer_busy_i === 1'b1) begin
      op_now = OpZeroer;
      ph_now = eng_phase;
    end else if (spm_wr_cmpl_nx) begin
      op_now = OpSpmWr;
      ph_now = PhCompleted;
    end else if (spm_rd_cmpl_nx) begin
      op_now = OpSpmRd;
      ph_now = PhCompleted;
    end
  end
  wire op_busy = (op_now != OpNone);

  // The state the last clk_smc_i edge before the assertion leaves, the
  // handshakes accepted at that edge included: the snapshot freezes at the
  // first clk_smc_i edge at which any of the four sources the
  // kind is read from (rst_cold_ni, the cool pin, the FLR cool reset, the SEP
  // watchdog reset) is seen low, and once the primary or the warm reset
  // asserts. The clk_ref_i sample below reads the frozen value, so a handshake
  // between the source's fall and that clk_ref_i edge does not move it.
  wire src_all_high = (rst_cold_ni === 1'b1) && (rst_cool_ni === 1'b1)
      && (rst_cool_from_flr_ni === 1'b1) && (sep_wdt_reset_ni === 1'b1);
  logic [2:0] op_snap_q;
  logic [1:0] ph_snap_q;
  always_ff @(posedge clk_smc_i) begin
    if (trk_rst_n && src_all_high) begin
      op_snap_q <= op_now;
      ph_snap_q <= ph_now;
    end
  end

  // Assertion edge of each kind, as the owner drives it: the falls of
  // rst_cold_ni, of the cool pin, of the FLR cool reset (not the FLR request)
  // and of the SEP watchdog reset. The first edge after tb_fcov_gate rises is
  // the pass's sample; a reset another source causes inside the same window
  // adds none.
  logic cold_q, cool_q, flr_q, wdt_q;
  always_ff @(posedge clk_ref_i) begin
    cold_q <= rst_cold_ni;
    cool_q <= rst_cool_ni;
    flr_q <= rst_cool_from_flr_ni;
    wdt_q <= sep_wdt_reset_ni;
  end

  wire cold_fall = (cold_q === 1'b1) && (rst_cold_ni === 1'b0);
  wire cool_fall = (cool_q === 1'b1) && (rst_cool_ni === 1'b0);
  wire flr_fall = (flr_q === 1'b1) && (rst_cool_from_flr_ni === 1'b0);
  wire wdt_fall = (wdt_q === 1'b1) && (sep_wdt_reset_ni === 1'b0);
  wire any_fall = cold_fall || cool_fall || flr_fall || wdt_fall;
  wire [1:0] fall_kind = cold_fall ? KindCold
                       : cool_fall ? KindCool
                       : flr_fall  ? KindFlr : KindWdt;

  logic armed_q;
  always_ff @(posedge clk_ref_i) begin
    if (not_powered || !gate_on) armed_q <= 1'b1;
    else if (any_fall) armed_q <= 1'b0;
  end
  wire kind_e = gate_on && (armed_q === 1'b1) && any_fall;
  // An assertion with no operation in flight is no pass of the in-flight
  // group.
  wire kind_sample_e = kind_e && (op_snap_q != OpNone);

  // A fall with no operation at the snapshot counts its twin when the
  // window's operation appears: the kind waits until the first clk_ref_i
  // edge at which an operation is presented or busy, while the gate stays
  // high and no other source falls. A window with no operation counts none,
  // and an assertion after the window's engine operation has finished counts
  // no twin.
  logic pend_q;
  logic [1:0] pend_kind_q;
  wire pend_set_e = kind_e && (op_snap_q == OpNone);
  wire pend_fire_e = gate_on && (pend_q === 1'b1) && !any_fall && op_busy;
  always_ff @(posedge clk_ref_i) begin
    if (not_powered || !gate_on) begin
      pend_q <= 1'b0;
    end else if (pend_set_e) begin
      pend_q <= 1'b1;
      pend_kind_q <= fall_kind;
    end else if (any_fall || pend_fire_e) begin
      pend_q <= 1'b0;
    end
  end

  // One user point per reset kind: each assertion of the owner's graded
  // window, once. The c_reset_op_* points above record any assertion of any
  // leaf.
  wire kind_cold_graded_e = (kind_sample_e && (fall_kind == KindCold))
      || (pend_fire_e && (pend_kind_q == KindCold));
  wire kind_cool_graded_e = (kind_sample_e && (fall_kind == KindCool))
      || (pend_fire_e && (pend_kind_q == KindCool));
  wire kind_flr_graded_e = (kind_sample_e && (fall_kind == KindFlr))
      || (pend_fire_e && (pend_kind_q == KindFlr));
  wire kind_wdt_graded_e = (kind_sample_e && (fall_kind == KindWdt))
      || (pend_fire_e && (pend_kind_q == KindWdt));
  `OCAH_FCOV_COVER(c_reset_kind_cold_graded, kind_cold_graded_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_kind_cool_pin_graded, kind_cool_graded_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_kind_flr_graded, kind_flr_graded_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_kind_wdt_graded, kind_wdt_graded_e, clk_ref_i, not_powered)

  // Register read-back. The kind of the window's sampled assertion holds
  // until tb_fcov_gate falls; each register class is sampled once per window,
  // at the OKAY read that completes the class, when every member of the class
  // has been read in the window and each read OKAY with the stated function of
  // the kind: the RDL reset value where the kind clears the class, the pattern
  // last written over SEP_IN where it keeps it. The warm scratch cells are
  // recorded: any OKAY read counts.
  localparam logic [55:0] AddrSsColdResetN = 56'(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR);
  localparam logic [55:0] AddrResetVector0 = 56'(SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR(0));
  localparam logic [55:0] AddrScratch0 = 56'(SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0));
  localparam logic [55:0] AddrSmcen = 56'(SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR);
  localparam logic [55:0] AddrFlrDelay =
      56'(SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR);
  localparam logic [55:0] AddrFlrHold =
      56'(SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR);
  localparam logic [55:0] AddrScratchCw0 =
      56'(SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR(
      0
  ));
  // CPU_CTRL.RESET_VECTOR: a 56-bit field reset to 0xC004_0000 (cpu_ctrl.rdl;
  // CPU_CTRL__RESET_VECTOR__VECTOR_bm and _reset of the generated cpu_ctrl.h);
  // every other register here is a 32-bit field reset to 0.
  localparam logic [63:0] ResetVectorMask = 64'h00FF_FFFF_FFFF_FFFF;
  localparam logic [63:0] ResetVectorReset = 64'hC004_0000;
  localparam int unsigned NumRegs = 7;
  localparam logic [2:0] RegNone = 3'd7;

  function automatic logic [2:0] reg_index(input logic [55:0] addr);
    case (addr)
      AddrSsColdResetN: return 3'd0;
      AddrResetVector0: return 3'd1;
      AddrScratch0: return 3'd2;
      AddrSmcen: return 3'd3;
      AddrFlrDelay: return 3'd4;
      AddrFlrHold: return 3'd5;
      AddrScratchCw0: return 3'd6;
      default: return RegNone;
    endcase
  endfunction

  function automatic logic [1:0] reg_class(input logic [2:0] idx);
    if (idx <= 3'd2) return ClsPrimary;
    if (idx <= 3'd5) return ClsColdOnly;
    if (idx == 3'd6) return ClsWarmScratch;
    return ClsNone;
  endfunction

  // The registers of a class, one bit per reg_index.
  function automatic logic [NumRegs-1:0] cls_members(input logic [1:0] cls);
    case (cls)
      ClsPrimary: return 7'b000_0111;
      ClsColdOnly: return 7'b011_1000;
      ClsWarmScratch: return 7'b100_0000;
      default: return '0;
    endcase
  endfunction

  // The field value of a beat: RESET_VECTOR is an 8-byte access, the others
  // are 4-byte accesses in the 32-bit lane the address selects.
  function automatic logic [63:0] reg_value(input logic [2:0] idx, input logic [55:0] addr,
                                            input logic [63:0] data);
    if (idx == 3'd1) return data & ResetVectorMask;
    return {32'd0, (addr[2] ? data[63:32] : data[31:0])};
  endfunction

  logic [55:0] rb_addr_q, pat_addr_q;
  logic [63:0] pat_data_q;
  logic [63:0] pattern_q [NumRegs];
  always_ff @(posedge clk_smc_i) begin
    if (!not_powered) begin
      if (sep_ar_acc) rb_addr_q <= sep_araddr_i;
      if (sep_aw_acc) pat_addr_q <= sep_awaddr_i;
      if (sep_w_last_acc) pat_data_q <= sep_wdata_i;
      if (sep_b_acc && (sep_bresp_i === 2'b00) && (reg_index(pat_addr_q) != RegNone)) begin
        pattern_q[reg_index(pat_addr_q)] <=
            reg_value(reg_index(pat_addr_q), pat_addr_q, pat_data_q);
      end
    end
  end

  logic [1:0] dom_kind_q;
  logic dom_valid_q, dom_pass_q;
  always_ff @(posedge clk_ref_i) begin
    if (not_powered || !gate_on) begin
      dom_valid_q <= 1'b0;
    end else if (kind_e) begin
      dom_valid_q <= 1'b1;
      dom_kind_q <= fall_kind;
      dom_pass_q <= (dom_pass_q !== 1'b1);
    end
  end

  wire [2:0] rb_idx = reg_index(rb_addr_q);
  wire [1:0] rb_cls = reg_class(rb_idx);
  wire [63:0] rb_value = reg_value(rb_idx, rb_addr_q, sep_rdata_i);
  wire rb_read = sep_r_last_acc && (rb_idx != RegNone);
  // clk_rst.adoc, Reset Architecture: the cold reset clears both classes, the
  // cool pin and the FLR cool reset clear the primary class, and the watchdog
  // warm reset clears neither.
  wire rb_cleared = (dom_kind_q == KindCold)
      || ((rb_cls == ClsPrimary) && ((dom_kind_q == KindCool) || (dom_kind_q == KindFlr)));
  wire [63:0] rb_reset = (rb_idx == 3'd1) ? ResetVectorReset : 64'd0;
  wire rb_function = (rb_cls == ClsWarmScratch)
      || (rb_cleared ? (rb_value === rb_reset) : (rb_value === pattern_q[rb_idx]));

  wire rb_match = (sep_rresp_i === 2'b00) && rb_function;

  // Per pass: the registers read so far, and the classes one of whose reads
  // did not match. A class is sampled once, at the read that completes its
  // members, and only if no read of a member has missed.
  logic dom_pass_seen_q;
  logic [NumRegs-1:0] rd_seen_q;
  logic [2:0] cls_bad_q, cls_done_q;
  wire dom_new_pass = (dom_pass_seen_q !== dom_pass_q);
  wire dom_read = gate_on && (dom_valid_q === 1'b1) && !dom_new_pass && rb_read;
  wire [NumRegs-1:0] rd_seen_next = rd_seen_q | ({{(NumRegs - 1) {1'b0}}, 1'b1} << rb_idx);
  wire cls_all_read = ((rd_seen_next & cls_members(rb_cls)) == cls_members(rb_cls));
  wire dom_sample_e = dom_read && rb_match && cls_all_read && (cls_bad_q[rb_cls] !== 1'b1)
      && (cls_done_q[rb_cls] !== 1'b1);
  always_ff @(posedge clk_smc_i) begin
    if (dom_new_pass) begin
      dom_pass_seen_q <= dom_pass_q;
      rd_seen_q <= '0;
      cls_bad_q <= '0;
      cls_done_q <= '0;
    end else if (dom_read) begin
      rd_seen_q <= rd_seen_next;
      if (!rb_match) cls_bad_q[rb_cls] <= 1'b1;
      if (dom_sample_e) cls_done_q[rb_cls] <= 1'b1;
    end
  end

  // Each event fills one coverpoint and passes the other a value no bin lists.
  covergroup smc_reset_kind_inflight_cg with function sample (
      logic [1:0] kind, logic [2:0] op, logic [1:0] phase, logic [1:0] dom_kind, logic [1:0] cls
  );
    option.per_instance = 1;
    // {kind, op, phase}: 42 goal cells and 6 recorded bins (rec_*: the SPM
    // burst completed before the assertion). The X-resolution leg of
    // CHK-RMT-ALLZERO-X-FREE is a check leg graded on a four-state simulator,
    // not a cell, so it has no bin.
    cp_kind_op_phase: coverpoint {
      kind, op, phase
    } {
      bins cold_spm_wr_before = {7'b00_000_00};
      bins cold_spm_wr_data = {7'b00_000_01};
      bins cold_spm_wr_awaiting = {7'b00_000_10};
      bins cold_spm_rd_before = {7'b00_001_00};
      bins cold_spm_rd_data = {7'b00_001_01};
      bins cold_spm_rd_awaiting = {7'b00_001_10};
      bins cold_dma_before = {7'b00_010_00};
      bins cold_dma_data = {7'b00_010_01};
      bins cold_dma_awaiting = {7'b00_010_10};
      bins cold_zeroer_before = {7'b00_011_00};
      bins cold_zeroer_data = {7'b00_011_01};
      bins cold_zeroer_awaiting = {7'b00_011_10};
      bins cool_spm_wr_before = {7'b01_000_00};
      bins cool_spm_wr_data = {7'b01_000_01};
      bins cool_spm_wr_awaiting = {7'b01_000_10};
      bins cool_spm_rd_before = {7'b01_001_00};
      bins cool_spm_rd_data = {7'b01_001_01};
      bins cool_spm_rd_awaiting = {7'b01_001_10};
      bins cool_dma_before = {7'b01_010_00};
      bins cool_dma_data = {7'b01_010_01};
      bins cool_dma_awaiting = {7'b01_010_10};
      bins cool_zeroer_before = {7'b01_011_00};
      bins cool_zeroer_data = {7'b01_011_01};
      bins cool_zeroer_awaiting = {7'b01_011_10};
      bins flr_spm_wr_before = {7'b10_000_00};
      bins flr_spm_wr_data = {7'b10_000_01};
      bins flr_spm_wr_awaiting = {7'b10_000_10};
      bins flr_spm_rd_before = {7'b10_001_00};
      bins flr_spm_rd_data = {7'b10_001_01};
      bins flr_spm_rd_awaiting = {7'b10_001_10};
      bins flr_dma_before = {7'b10_010_00};
      bins flr_dma_data = {7'b10_010_01};
      bins flr_dma_awaiting = {7'b10_010_10};
      bins flr_zeroer_before = {7'b10_011_00};
      bins flr_zeroer_data = {7'b10_011_01};
      bins flr_zeroer_awaiting = {7'b10_011_10};
      bins wdt_dma_before = {7'b11_010_00};
      bins wdt_dma_data = {7'b11_010_01};
      bins wdt_dma_awaiting = {7'b11_010_10};
      bins wdt_zeroer_before = {7'b11_011_00};
      bins wdt_zeroer_data = {7'b11_011_01};
      bins wdt_zeroer_awaiting = {7'b11_011_10};
      bins rec_cold_spm_wr_completed = {7'b00_000_11};
      bins rec_cold_spm_rd_completed = {7'b00_001_11};
      bins rec_cool_spm_wr_completed = {7'b01_000_11};
      bins rec_cool_spm_rd_completed = {7'b01_001_11};
      bins rec_flr_spm_wr_completed = {7'b10_000_11};
      bins rec_flr_spm_rd_completed = {7'b10_001_11};
      // A watchdog warm reset with an SPM access in flight leaves the cluster
      // boundary unanswering until a primary reset (#3510): the owner never
      // draws the pair. No bin lists these values.
      ignore_bins wdt_spm = {7'b11_000_00, 7'b11_000_01, 7'b11_000_10,
                             7'b11_001_00, 7'b11_001_01, 7'b11_001_10};
    }
    // {kind, class}: 8 goal cells and 4 recorded bins (rec_*: the warm
    // scratch register, whose reset clk_rst.adoc does not name).
    cp_kind_domain: coverpoint {
      dom_kind, cls
    } {
      bins cold_cold_only = {4'b00_00};
      bins cold_primary = {4'b00_01};
      bins cool_cold_only = {4'b01_00};
      bins cool_primary = {4'b01_01};
      bins flr_cold_only = {4'b10_00};
      bins flr_primary = {4'b10_01};
      bins wdt_cold_only = {4'b11_00};
      bins wdt_primary = {4'b11_01};
      bins rec_cold_warm_scratch = {4'b00_10};
      bins rec_cool_warm_scratch = {4'b01_10};
      bins rec_flr_warm_scratch = {4'b10_10};
      bins rec_wdt_warm_scratch = {4'b11_10};
    }
  endgroup

  smc_reset_kind_inflight_cg u_cg_reset_kind_inflight = new();

  always_ff @(posedge clk_ref_i) begin
    if (!not_powered && kind_sample_e) begin
      u_cg_reset_kind_inflight.sample(fall_kind, op_snap_q, ph_snap_q, KindCold, ClsNone);
    end
  end

  always_ff @(posedge clk_smc_i) begin
    if (!not_powered && dom_sample_e) begin
      u_cg_reset_kind_inflight.sample(KindCold, OpNone, PhBefore, dom_kind_q, rb_cls);
    end
  end

  // ------------------------------------------------------------------
  // smc_deglitch_cg and smc_powergood_glitch_cg (SMC_FCOV.adoc): the cool-pin
  // de-glitch window, its pin segments inside the FLR hold, and the power-good
  // glitch length. Both count consecutive low samples of the port on
  // clk_ref_i, the clock the pin is driven on; the DUT's primary and
  // cold-stable resets are cross-check references only.
  // ------------------------------------------------------------------
  localparam logic [7:0] DeglitchSamples = 8'd32;
  // The owner's bench bound on the primary assertion, in clk_ref_i samples.
  localparam logic [7:0] AssertBound = 8'd128;
  // The owner's bench bound on the primary release after the last reset
  // source ends, in clk_ref_i samples.
  localparam logic [8:0] ReleaseBound = 9'd256;
  localparam logic [2:0] Wd1 = 3'd0;
  localparam logic [2:0] Wd2To30 = 3'd1;
  localparam logic [2:0] Wd31 = 3'd2;
  localparam logic [2:0] Wd32 = 3'd3;
  localparam logic [2:0] Wd33To64 = 3'd4;
  localparam logic [2:0] WdAbove64 = 3'd5;
  localparam logic OvSub32 = 1'b0;
  localparam logic OvLater = 1'b1;
  localparam logic [1:0] LenBelow32 = 2'd0;
  localparam logic [1:0] Len32 = 2'd1;
  localparam logic [1:0] LenAbove32 = 2'd2;

  function automatic logic [2:0] width_class(input logic [7:0] n);
    if (n == 8'd1) return Wd1;
    if (n <= 8'd30) return Wd2To30;
    if (n == 8'd31) return Wd31;
    if (n == 8'd32) return Wd32;
    if (n <= 8'd64) return Wd33To64;
    return WdAbove64;
  endfunction

  function automatic logic [1:0] len_class(input logic [15:0] n);
    if (n < 16'd32) return LenBelow32;
    if (n == 16'd32) return Len32;
    return LenAbove32;
  endfunction

  function automatic logic [7:0] sat_inc8(input logic [7:0] n);
    return (n == 8'hFF) ? n : n + 8'd1;
  endfunction

  logic gate_ref_q;
  always_ff @(posedge clk_ref_i) gate_ref_q <= gate_on;
  wire gate_rise_ref = gate_on && (gate_ref_q !== 1'b1);

  // op_seen_q: an SPM, DMA or zeroer operation seen in flight at a clk_smc_i
  // edge since tb_fcov_gate rose. The de-glitch group samples only while it
  // is clear, so a window that carries an operation is no de-glitch window.
  logic op_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (not_powered) op_seen_q <= 1'b0;
    else if (gate_rise_smc) op_seen_q <= op_busy;
    else if (gate_on && op_busy) op_seen_q <= 1'b1;
  end

  wire pin_lo = (rst_cool_ni === 1'b0);
  wire pin_hi = (rst_cool_ni === 1'b1);
  wire flr_hi = (rst_cool_from_flr_ni === 1'b1);
  wire flr_lo = (rst_cool_from_flr_ni === 1'b0);
  wire prim_ref_lo = (rst_primary_ref_clk_ni === 1'b0);
  wire prim_smc_lo = (rst_primary_smc_clk_ni === 1'b0);
  wire prim_ref_hi = (rst_primary_ref_clk_ni === 1'b1);
  wire prim_smc_hi = (rst_primary_smc_clk_ni === 1'b1);
  wire dg_live = !not_powered && gate_on && !gate_rise_ref && (op_seen_q !== 1'b1);

  // cp_width: a low run of the pin that begins with the FLR cool reset high.
  // Its width is the count of consecutive low samples. A run of 32 and above
  // samples its cell at the later of its end and the sample by which both
  // primary resets have read 0, when that happens within AssertBound samples
  // of its first low. A run below 32 samples its cell at the first of two
  // samples, its AssertBound-th sample counted from its first low and the
  // first low sample of the next run, when no primary reset read 0 from its
  // first low through that sample. A run of 32 and above that the next run
  // supersedes before it resolved samples no cell. A contrary outcome samples
  // no cell.
  logic wd_open_q, wd_low_q, wd_ref0_q, wd_smc0_q, wd_hit_q;
  logic [7:0] wd_cnt_q, wd_age_q;
  wire wd_start = dg_live && cool_fall && flr_hi;
  wire wd_open = dg_live && (wd_open_q === 1'b1);
  wire [7:0] wd_age_now = sat_inc8(wd_age_q);
  wire wd_ref0_now = wd_ref0_q || prim_ref_lo;
  wire wd_smc0_now = wd_smc0_q || prim_smc_lo;
  wire wd_any0_now = wd_ref0_now || wd_smc0_now;
  wire wd_hit_now = wd_hit_q || (wd_ref0_now && wd_smc0_now && (wd_age_now <= AssertBound));
  wire wd_ended = !wd_low_q || pin_hi;
  wire wd_long = (wd_cnt_q >= DeglitchSamples);
  wire wd_long_e = wd_open && wd_ended && wd_long && wd_hit_now;
  wire wd_short_e = wd_open && wd_ended && !wd_long && !wd_any0_now
      && (wd_start || (wd_age_now >= AssertBound));
  wire wd_drop = wd_open && wd_ended
      && (wd_long ? (wd_start || ((wd_age_now > AssertBound) && !wd_hit_now)) : wd_any0_now);
  wire wd_e = wd_long_e || wd_short_e;

  always_ff @(posedge clk_ref_i) begin
    if (!dg_live) begin
      wd_open_q <= 1'b0;
      wd_low_q <= 1'b0;
    end else if (wd_start) begin
      wd_open_q <= 1'b1;
      wd_low_q <= 1'b1;
      wd_cnt_q <= 8'd1;
      wd_age_q <= 8'd1;
      wd_ref0_q <= prim_ref_lo;
      wd_smc0_q <= prim_smc_lo;
      wd_hit_q <= prim_ref_lo && prim_smc_lo;
    end else if (wd_open_q) begin
      if (wd_e || wd_drop) wd_open_q <= 1'b0;
      if (wd_low_q && pin_hi) wd_low_q <= 1'b0;
      else if (wd_low_q && pin_lo) wd_cnt_q <= sat_inc8(wd_cnt_q);
      wd_age_q <= wd_age_now;
      wd_ref0_q <= wd_ref0_now;
      wd_smc0_q <= wd_smc0_now;
      wd_hit_q <= wd_hit_now;
    end
  end

  // Pin control: the first low run of the pin under the group with the FLR
  // cool reset high at every sample of it, 32 and above, whose primary
  // resets each read 0 and then read 1 at or after its end (the first sample
  // with the pin high), with the pin and the FLR cool reset high from that end
  // until both have, within ReleaseBound samples. Its release offset per
  // primary reset is the count of samples from the run's end to the first
  // sample at or after it at which that reset reads 1 having read 0 since the
  // run's first low sample.
  logic pc_got_q, pc_act_q, pc_low_q, pc_ref0_q, pc_smc0_q, pc_ref_got_q, pc_smc_got_q;
  logic [7:0] pc_cnt_q;
  logic [8:0] pc_age_q, pc_ref_off_q, pc_smc_off_q;
  wire pc_start = dg_live && (pc_got_q !== 1'b1) && cool_fall && flr_hi;
  wire pc_act = dg_live && !pc_start && (pc_got_q !== 1'b1) && (pc_act_q === 1'b1);
  wire pc_ref0_now = (pc_ref0_q === 1'b1) || prim_ref_lo;
  wire pc_smc0_now = (pc_smc0_q === 1'b1) || prim_smc_lo;
  wire pc_rise = pc_act && (pc_low_q === 1'b1) && pin_hi;
  wire pc_hi = pc_act && ((pc_low_q !== 1'b1) || pin_hi);
  wire pc_bad = pc_act && (!flr_hi || (pc_rise && (pc_cnt_q < DeglitchSamples))
      || (pc_hi && !pin_hi));
  wire [8:0] pc_age_now = pc_rise ? 9'd0 : pc_age_q + 9'd1;
  wire pc_ref_rel = pc_hi && (pc_ref_got_q !== 1'b1) && pc_ref0_now && prim_ref_hi;
  wire pc_smc_rel = pc_hi && (pc_smc_got_q !== 1'b1) && pc_smc0_now && prim_smc_hi;
  wire pc_rec_e = pc_hi && !pc_bad && ((pc_ref_got_q === 1'b1) || pc_ref_rel)
      && ((pc_smc_got_q === 1'b1) || pc_smc_rel);
  wire pc_late = pc_hi && !pc_rec_e && (pc_age_now >= ReleaseBound);

  always_ff @(posedge clk_ref_i) begin
    if (!dg_live) begin
      pc_got_q <= 1'b0;
      pc_act_q <= 1'b0;
    end else if (pc_start) begin
      pc_act_q <= 1'b1;
      pc_low_q <= 1'b1;
      pc_cnt_q <= 8'd1;
      pc_ref0_q <= prim_ref_lo;
      pc_smc0_q <= prim_smc_lo;
      pc_ref_got_q <= 1'b0;
      pc_smc_got_q <= 1'b0;
    end else if (pc_act) begin
      if (pc_bad || pc_late || pc_rec_e) pc_act_q <= 1'b0;
      if (pc_rec_e) pc_got_q <= 1'b1;
      pc_ref0_q <= pc_ref0_now;
      pc_smc0_q <= pc_smc0_now;
      if (pc_rise) pc_low_q <= 1'b0;
      else if (pc_low_q && pin_lo) pc_cnt_q <= sat_inc8(pc_cnt_q);
      if (pc_hi) pc_age_q <= pc_age_now;
      if (pc_ref_rel) begin
        pc_ref_got_q <= 1'b1;
        pc_ref_off_q <= pc_age_now;
      end
      if (pc_smc_rel) begin
        pc_smc_got_q <= 1'b1;
        pc_smc_off_q <= pc_age_now;
      end
    end
  end

  // cp_flr_overlap: an FLR hold (the FLR cool reset low) that begins with the
  // group live, by the pin low runs whose first low sample falls inside it:
  // the sub-32 cell when it saw at least one pin run and every run is below
  // 32, the later-source cell when a run of 32 and above ended and the pin
  // fell again inside the hold. The sources end at the later of the hold's end
  // (the first sample with the FLR cool reset high) and the end of its last
  // pin run (the first sample with the pin high). The hold's window opens at
  // the first sample inside it at which either primary reset reads 0; a
  // primary reset's release is the first sample from there at which it reads
  // 1. The hold resolves at the first sample from the sources' end by which
  // both have released, within ReleaseBound samples of that end. A hold with
  // no pin fall inside it samples nothing: it is the control, and when
  // neither release lies before its end, its release offsets (from its end
  // to each release) are recorded. A hold samples its cell only when each
  // primary reset's release lies exactly at the expected sample: the hold's
  // end plus the last control's offset for that reset, or, in the
  // later-source cell when the last pin run is of 32 and above and its end
  // plus the pin control's offset is later, that end plus the pin control's
  // offset. So a primary reset that reads 1 after the window opens and
  // before that sample, or releases after it, samples no cell. Both cells
  // need a control recorded since the group went live, the later-source cell
  // also the pin control. A hold not resolved within 2047 samples of its
  // start samples nothing.
  logic ov_act_q, ov_end_q, ov_in_q, ov_low_q, ov_seg_q, ov_long_q, ov_reas_q, ov_plong_q;
  logic ov_win_q, ov_ref_got_q, ov_smc_got_q, ov_ctl_q;
  logic [7:0] ov_cnt_q;
  logic [10:0] ov_t_q, ov_hend_t_q, ov_pend_t_q, ov_end_t_q, ov_ref_t_q, ov_smc_t_q;
  logic [8:0] ov_ctl_ref_q, ov_ctl_smc_q;
  localparam logic [10:0] OvReleaseBound = {2'b00, ReleaseBound};
  wire ov_start = dg_live && flr_fall;
  wire ov_act = dg_live && !ov_start && (ov_act_q === 1'b1);
  wire ov_src = ov_act && (ov_end_q !== 1'b1);
  wire ov_in = ov_start || (ov_src && (ov_in_q === 1'b1) && flr_lo);
  wire ov_fall_in = ov_in && cool_fall;
  wire ov_long_now = ov_long_q || (ov_low_q && pin_hi && (ov_cnt_q >= DeglitchSamples));
  wire ov_seg_now = ov_seg_q || ov_fall_in;
  wire ov_reas_now = ov_reas_q || (ov_fall_in && ov_long_q);
  wire [10:0] ov_t_now = ov_start ? 11'd0 : ((ov_t_q == 11'h7FF) ? ov_t_q : ov_t_q + 11'd1);
  wire ov_sat = (ov_t_now == 11'h7FF);
  wire ov_hend_e = ov_src && (ov_in_q === 1'b1) && !flr_lo;
  wire ov_pend_e = ov_src && (ov_low_q === 1'b1) && pin_hi;
  wire ov_end_e = ov_src && (!ov_in_q || flr_hi) && (!ov_low_q || pin_hi) && !ov_fall_in;
  wire [10:0] ov_hend_t_now = ov_hend_e ? ov_t_now : ov_hend_t_q;
  wire [10:0] ov_pend_t_now = ov_pend_e ? ov_t_now : ov_pend_t_q;
  wire [10:0] ov_end_t_now = ov_end_e ? ov_t_now : ov_end_t_q;
  wire ov_plong_now = ov_pend_e ? (ov_cnt_q >= DeglitchSamples) : (ov_plong_q === 1'b1);
  wire ov_win_now = (ov_act && (ov_win_q === 1'b1)) || (ov_in && (prim_ref_lo || prim_smc_lo));
  wire ov_ref_kept = ov_act && (ov_ref_got_q === 1'b1);
  wire ov_smc_kept = ov_act && (ov_smc_got_q === 1'b1);
  wire ov_ref_got_now = ov_ref_kept || (ov_win_now && prim_ref_hi);
  wire ov_smc_got_now = ov_smc_kept || (ov_win_now && prim_smc_hi);
  wire [10:0] ov_ref_t_now = ov_ref_kept ? ov_ref_t_q : ov_t_now;
  wire [10:0] ov_smc_t_now = ov_smc_kept ? ov_smc_t_q : ov_t_now;
  wire ov_ended = ov_act && (ov_end_e || (ov_end_q === 1'b1));
  wire ov_res = ov_ended && ov_ref_got_now && ov_smc_got_now && !ov_sat;
  wire ov_drop = ov_act && !ov_res
      && (ov_sat || (ov_ended && ((ov_t_now - ov_end_t_now) >= OvReleaseBound)));

  // The control's offsets.
  wire [8:0] ov_ref_d = 9'(ov_ref_t_now - ov_hend_t_now);
  wire [8:0] ov_smc_d = 9'(ov_smc_t_now - ov_hend_t_now);
  wire ov_ctl_e = ov_res && !ov_seg_now && (ov_ref_t_now >= ov_hend_t_now)
      && (ov_smc_t_now >= ov_hend_t_now);

  // The expected release samples of a hold with pin runs.
  wire ov_cls = ov_reas_now ? OvLater : OvSub32;
  wire ov_elig = (ov_seg_now && !ov_long_now) || ov_reas_now;
  wire [11:0] ov_hold_ref = {1'b0, ov_hend_t_now} + {3'b000, ov_ctl_ref_q};
  wire [11:0] ov_hold_smc = {1'b0, ov_hend_t_now} + {3'b000, ov_ctl_smc_q};
  wire [11:0] ov_pin_ref = {1'b0, ov_pend_t_now} + {3'b000, pc_ref_off_q};
  wire [11:0] ov_pin_smc = {1'b0, ov_pend_t_now} + {3'b000, pc_smc_off_q};
  wire ov_pin_src = (ov_cls == OvLater) && ov_plong_now;
  wire [11:0] ov_exp_ref = (ov_pin_src && (ov_pin_ref > ov_hold_ref)) ? ov_pin_ref : ov_hold_ref;
  wire [11:0] ov_exp_smc = (ov_pin_src && (ov_pin_smc > ov_hold_smc)) ? ov_pin_smc : ov_hold_smc;
  wire ov_e = ov_res && ov_elig && (ov_ctl_q === 1'b1)
      && ((ov_cls == OvSub32) || (pc_got_q === 1'b1))
      && ({1'b0, ov_ref_t_now} == ov_exp_ref) && ({1'b0, ov_smc_t_now} == ov_exp_smc);

  always_ff @(posedge clk_ref_i) begin
    if (!dg_live) begin
      ov_act_q <= 1'b0;
      ov_ctl_q <= 1'b0;
    end else if (ov_start) begin
      ov_act_q <= 1'b1;
      ov_end_q <= 1'b0;
      ov_in_q <= 1'b1;
      ov_low_q <= ov_fall_in;
      ov_cnt_q <= 8'd1;
      ov_seg_q <= ov_fall_in;
      ov_long_q <= 1'b0;
      ov_reas_q <= 1'b0;
      ov_plong_q <= 1'b0;
      ov_t_q <= ov_t_now;
      ov_win_q <= ov_win_now;
      ov_ref_got_q <= ov_ref_got_now;
      ov_smc_got_q <= ov_smc_got_now;
      ov_ref_t_q <= ov_ref_t_now;
      ov_smc_t_q <= ov_smc_t_now;
    end else if (ov_act) begin
      if (ov_res || ov_drop) ov_act_q <= 1'b0;
      if (ov_ctl_e) begin
        ov_ctl_q <= 1'b1;
        ov_ctl_ref_q <= ov_ref_d;
        ov_ctl_smc_q <= ov_smc_d;
      end
      ov_t_q <= ov_t_now;
      ov_win_q <= ov_win_now;
      ov_ref_got_q <= ov_ref_got_now;
      ov_smc_got_q <= ov_smc_got_now;
      ov_ref_t_q <= ov_ref_t_now;
      ov_smc_t_q <= ov_smc_t_now;
      if (ov_src) begin
        if (ov_end_e) ov_end_q <= 1'b1;
        ov_end_t_q <= ov_end_t_now;
        ov_hend_t_q <= ov_hend_t_now;
        ov_pend_t_q <= ov_pend_t_now;
        ov_plong_q <= ov_plong_now;
        if (!flr_lo) ov_in_q <= 1'b0;
        if (ov_fall_in) begin
          ov_low_q <= 1'b1;
          ov_cnt_q <= 8'd1;
        end else if (ov_low_q && pin_hi) begin
          ov_low_q <= 1'b0;
        end else if (ov_low_q && pin_lo) begin
          ov_cnt_q <= sat_inc8(ov_cnt_q);
        end
        ov_long_q <= ov_long_now;
        ov_seg_q <= ov_seg_now;
        ov_reas_q <= ov_reas_now;
      end
    end
  end

  // smc_powergood_glitch_cg: a powergood_i low run that begins with the gate
  // high. A run whose powergood_stable_o fell inside it leaves the window's
  // glitch record at the powergood_i rise: the count of consecutive low
  // samples. cp_glitch_len samples the record at the falling edge of the
  // gate itself, when the three interrupt aggregates read 0 at every sample
  // from the gate's rise to its last sample with the gate high (a leaf may end
  // less than one clk_ref_i period after it drops the gate), and when
  // powergood_stable_o, the cold-stable reset and both primary resets have
  // each read 1 at some sample after the one that took the record, before the
  // gate fell: the recovery. A window with no record, or whose gate falls
  // without that recovery, samples nothing. cp_cold_assert samples once per run, at the first sample inside
  // it at which powergood_stable_o, the cold-stable reset and both primary
  // resets read 0. A run's flags start at its first low sample; the window's
  // flags clear when the gate rises.
  logic pg_q, pg_run_q, pg_fell_q, pg_cold_q, pg_irq_ok_q, pg_rec_q;
  logic [3:0] pg_rcv_q;
  logic [15:0] pg_cnt_q, pg_rec_cnt_q;
  always_ff @(posedge clk_ref_i) pg_q <= powergood_i;
  wire pg_lo = (powergood_i === 1'b0);
  wire pg_fall = gate_on && (pg_q === 1'b1) && pg_lo;
  wire pg_rise = (pg_q === 1'b0) && (powergood_i === 1'b1);
  wire pg_run_p = (pg_run_q === 1'b1) && !gate_rise_ref;
  wire pg_in_run = gate_on && (pg_fall || (pg_run_p && pg_lo));
  wire pg_stable_fall = (powergood_stable_q === 1'b1) && (powergood_stable_i === 1'b0);
  wire pg_fell_now = (pg_fall ? 1'b0 : (pg_fell_q && pg_run_p)) || (pg_in_run && pg_stable_fall);
  wire pg_irq_quiet = ((sync_irq_i | gpio_irq_any_i | uart_irq_any_i) === 1'b0);
  wire pg_irq_ok_now = (gate_rise_ref || (pg_irq_ok_q === 1'b1)) && pg_irq_quiet;
  wire pg_cold_all0 = (powergood_stable_i === 1'b0) && (rst_cold_stable_ref_clk_ni === 1'b0)
      && prim_ref_lo && prim_smc_lo;
  wire pg_cold_p = !pg_fall && pg_run_p && (pg_cold_q === 1'b1);
  wire pg_cold_e = pg_in_run && pg_cold_all0 && !pg_cold_p;
  wire pg_rec_e = gate_on && pg_run_p && pg_rise && (pg_fell_q === 1'b1);
  wire [3:0] pg_up = {
    powergood_stable_i === 1'b1, rst_cold_stable_ref_clk_ni === 1'b1, prim_ref_hi, prim_smc_hi
  };
  wire pg_len_e = (pg_rec_q === 1'b1) && (pg_irq_ok_q === 1'b1) && (pg_rcv_q === 4'hF);
  wire [15:0] pg_cnt_next = (pg_cnt_q == 16'hFFFF) ? pg_cnt_q : pg_cnt_q + 16'd1;

  always_ff @(posedge clk_ref_i) begin
    if (gate_on) begin
      pg_run_q <= pg_in_run;
      pg_fell_q <= pg_fell_now;
      pg_cold_q <= pg_cold_p || pg_cold_e;
      pg_irq_ok_q <= pg_irq_ok_now;
      if (gate_rise_ref) pg_rec_q <= 1'b0;
      else if (pg_rec_e) pg_rec_q <= 1'b1;
      if (pg_rec_e) pg_rec_cnt_q <= pg_cnt_q;
      if (gate_rise_ref || pg_rec_e) pg_rcv_q <= 4'h0;
      else if (pg_rec_q === 1'b1) pg_rcv_q <= pg_rcv_q | pg_up;
      if (pg_fall) pg_cnt_q <= 16'd1;
      else if (pg_run_p && pg_lo) pg_cnt_q <= pg_cnt_next;
    end
  end

  // One goal bin of a tuple coverpoint led by the graded flag.
  `define SMC_RST_GRADED_BIN(name, cls) \
      bins name = {{1'b1, cls}};

  // Each event fills its coverpoint and passes the other a value no bin lists.
  covergroup smc_deglitch_cg with function sample (
      logic wg, logic [2:0] wcls, logic og, logic ocls
  );
    option.per_instance = 1;
    // {graded, width class}: 6 cells.
    cp_width: coverpoint {
      wg, wcls
    } {
      `SMC_RST_GRADED_BIN(width_1, Wd1)
      `SMC_RST_GRADED_BIN(width_2_30, Wd2To30)
      `SMC_RST_GRADED_BIN(width_31, Wd31)
      `SMC_RST_GRADED_BIN(width_32, Wd32)
      `SMC_RST_GRADED_BIN(width_33_64, Wd33To64)
      `SMC_RST_GRADED_BIN(width_above_64, WdAbove64)
    }
    // {graded, segment class}: 2 cells.
    cp_flr_overlap: coverpoint {
      og, ocls
    } {
      `SMC_RST_GRADED_BIN(sub32_in_hold, OvSub32)
      `SMC_RST_GRADED_BIN(later_source, OvLater)
    }
  endgroup

  covergroup smc_powergood_glitch_cg with function sample (logic lg, logic [1:0] lcls, logic ca);
    option.per_instance = 1;
    // {graded, length class}: 3 cells.
    cp_glitch_len: coverpoint {
      lg, lcls
    } {
      `SMC_RST_GRADED_BIN(len_below_32, LenBelow32)
      `SMC_RST_GRADED_BIN(len_32, Len32)
      `SMC_RST_GRADED_BIN(len_above_32, LenAbove32)
    }
    // The resets the glitch asserts, recorded.
    cp_cold_assert: coverpoint ca {
      bins rec_cold_assert_mid_glitch = {1'b1};
    }
  endgroup
  `undef SMC_RST_GRADED_BIN

  smc_deglitch_cg u_cg_deglitch = new();
  smc_powergood_glitch_cg u_cg_powergood_glitch = new();

  always_ff @(posedge clk_ref_i) begin
    if (!not_powered && (wd_e || ov_e)) begin
      u_cg_deglitch.sample(wd_e, width_class(wd_cnt_q), ov_e, ov_cls);
    end
  end

  always_ff @(posedge clk_ref_i) begin
    if (pg_cold_e) u_cg_powergood_glitch.sample(1'b0, LenBelow32, 1'b1);
  end

  always_ff @(negedge fcov_gate_i) begin
    if (pg_len_e) u_cg_powergood_glitch.sample(1'b1, len_class(pg_rec_cnt_q), 1'b0);
  end

endmodule : smc_reset_fcov
