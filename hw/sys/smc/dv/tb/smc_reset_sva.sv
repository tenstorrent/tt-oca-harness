// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reset-protocol rules of the SMC chapters (hw/sys/smc/doc/cpu.adoc and
// clk_rst.adoc), graded on every clock edge of every single-instance run.
// Every rule is an `OCAH_SVA_ASSERT, two-state and live on both simulators;
// the operands are nets of the signal list and a few hierarchical reads that
// tb_top passes in as flat ports. The previous-edge values a rule needs come
// from shadow flops on the rule's clock, so no rule uses $past.
//
// Clocks and disables: the CPU cluster rules sample clk_smc_i; the rules that
// grade a reset of that domain are disabled while powergood is low, the others
// while the primary reset is low. The FLR rules sample clk_ref_i and are
// disabled while the stable cold reset of that domain is low. en_i is the
// bench's checker enable and is ANDed into every antecedent.
//
// Hold-off knob: +smc_flr_requeue_assertoff turns SMC_FLR_ONE_PULSE_PER_EDGE
// off for the leaf that reproduces the FLR requeue defect, whose own check
// line the fire would preempt on Verilator.
//
// Non-vacuity: a counter per rule group counts the clock edges at which its
// antecedent held; the final block prints each as
// CHK-RESET-SVA-<GROUP>: antecedent_edges=<n>, and
// +smc_reset_sva_need_<group> fails the run when that count is 0. Two counts
// leave out what every run does on its own: iso_release counts a release of
// the cluster boundary only after a software reset request was applied, and
// uncore_low counts an uncore reset only after its first release. A need
// plusarg whose group is not reported fails the run too; $value$plusargs
// returns the first plusarg with the prefix, so the final block sees one need
// plusarg per run, and the testlist unit test checks every one statically.

`include "ocah_sva_macros.svh"

module smc_reset_sva #(
  parameter int unsigned NUM_CORES       = 4,
  parameter int unsigned FLR_CNT_WIDTH   = 32,
  parameter int unsigned PENDING_WIDTH   = 4,
  parameter int unsigned WB_PC_WIDTH     = 58
) (
  input  wire logic                       clk_smc_i,
  input  wire logic                       clk_ref_i,
  input  wire logic                       en_i,
  input  wire logic                       powergood_stable_i,
  input  wire logic                       rst_primary_smc_clk_ni,
  input  wire logic                       rst_wdt_smc_clk_ni,
  input  wire logic                       rst_warm_smc_clk_ni,
  input  wire logic                       rst_cold_stable_ref_clk_ni,
  input  smc_pkg::jtag_smc_reset_ctrl_t   jtag_reset_ctrl_i,
  // CPU control wrapper: the software uncore reset handshake.
  input  wire logic                       cpu_isolate_req_i,
  input  wire logic                       cpu_drained_i,
  input  wire logic                       cpu_reset_timeout_i,
  input  wire logic                       cpu_reset_applied_i,
  input  wire logic                       cpu_timeout_mode_i,
  input  wire logic                       cpu_isolate_flush_i,
  input  wire logic                       cpu_uncore_reset_ni,
  input  wire logic [NUM_CORES-1:0]       cpu_core_resets_ni,
  // Cluster boundary.
  input  wire logic                       init_mem_done_i,
  input  wire logic                       cpu_cluster_isolate_i,
  input  wire logic                       cpu_l2_isolated_i,
  input  wire logic                       cpu_mmio_isolated_i,
  input  wire logic                       cpu_l2_flush_active_i,
  input  wire logic                       cpu_mmio_flush_active_i,
  input  wire logic [NUM_CORES-1:0]       cpu_wb_pc_valid_i,
  input  wire logic [NUM_CORES-1:0][WB_PC_WIDTH-1:0] cpu_wb_reg_pc_i,
  input  wire logic [NUM_CORES-1:0]       cpu_wdt_reset_i,
  input  wire logic [PENDING_WIDTH-1:0]   cpu_l2_pending_aw_i,
  input  wire logic [PENDING_WIDTH-1:0]   cpu_l2_pending_ar_i,
  input  wire logic [PENDING_WIDTH-1:0]   cpu_mmio_pending_aw_i,
  input  wire logic [PENDING_WIDTH-1:0]   cpu_mmio_pending_ar_i,
  // L2 frontend isolate, fabric side (its slave port).
  input  wire logic                       l2_slv_aw_valid_i,
  input  wire logic                       l2_slv_aw_ready_i,
  input  wire logic                       l2_slv_ar_valid_i,
  input  wire logic                       l2_slv_ar_ready_i,
  // CPU MMIO port, fabric side of the MMIO isolate.
  input  wire logic                       mmio_port_aw_valid_i,
  input  wire logic                       mmio_port_aw_ready_i,
  input  wire logic                       mmio_port_w_valid_i,
  input  wire logic                       mmio_port_w_ready_i,
  input  wire logic                       mmio_port_ar_valid_i,
  input  wire logic                       mmio_port_ar_ready_i,
  // CPU MMIO port, cluster side of the MMIO isolate.
  input  wire logic                       mmio_cpu_b_valid_i,
  input  wire logic [1:0]                 mmio_cpu_b_resp_i,
  input  wire logic                       mmio_cpu_r_valid_i,
  input  wire logic [1:0]                 mmio_cpu_r_resp_i,
  // FLR sequencer, reference clock domain.
  input  wire logic                       flr_posedge_ref_i,
  input  wire logic [1:0]                 flr_counter_state_i,
  input  wire logic                       flr_cool_reset_ni,
  input  wire logic [FLR_CNT_WIDTH-1:0]   flr_hold_count_ref_i,
  // Cool reset after the JTAG override, and the cool-reset-out pad it drives.
  input  wire logic                       cool_reset_ni,
  input  wire logic                       cool_pad_lsio_pin_i,
  input  wire logic                       cool_pad_core2pad_i,
  input  wire logic                       cool_pad_core2pad_en_i
);

  localparam logic [1:0] RespSlvErr = 2'b10;

  bit flr_requeue_assertoff = $test$plusargs("smc_flr_requeue_assertoff");

  logic force_apply, withheld, warm_ovrd_idle, cluster_ready, flush_active, mmio_flush;
  assign force_apply    = cpu_reset_timeout_i && cpu_timeout_mode_i;
  assign withheld       = cpu_isolate_req_i && !cpu_drained_i && !force_apply;
  assign warm_ovrd_idle = !jtag_reset_ctrl_i.ovrd.warm_reset_n_ovrd;
  assign cluster_ready  = init_mem_done_i && cpu_uncore_reset_ni && !cpu_isolate_req_i;
  assign flush_active   = cpu_l2_flush_active_i || cpu_mmio_flush_active_i;
  assign mmio_flush     = cpu_isolate_flush_i || cpu_mmio_flush_active_i;

  // The disable term of every rule in this module is a net: a negation inside the disable
  // iff of a non-top module does not compile under expression coverage.
  logic primary_reset_active, powergood_lost, cold_reset_ref_active;
  assign primary_reset_active  = !rst_primary_smc_clk_ni;
  assign powergood_lost        = !powergood_stable_i;
  assign cold_reset_ref_active = !rst_cold_stable_ref_clk_ni;

  // Previous-edge values on clk_smc_i.
  logic warm_q, withheld_q, applied_q, isolate_q, flush_active_q, force_apply_q, w_held_q;
  logic [3:0] ready_q;
  always_ff @(posedge clk_smc_i) begin
    warm_q         <= rst_warm_smc_clk_ni;
    withheld_q     <= withheld;
    applied_q      <= cpu_reset_applied_i;
    isolate_q      <= cpu_cluster_isolate_i;
    flush_active_q <= flush_active;
    force_apply_q  <= force_apply;
    w_held_q       <= mmio_port_w_valid_i && !mmio_port_w_ready_i;
    ready_q        <= {ready_q[2:0], cluster_ready};
  end

  // ------------------------------------------------------------------
  // A1: the uncore reset is low only through the warm reset or an applied
  // software request, never while the request is withheld, and the drained
  // report the request waits for means both isolates hold no open address
  // request (cpu.adoc 233-240, 272-280, 293-295).
  // ------------------------------------------------------------------
  logic a1_withheld_ant, a1_cause_ant, a1_applied_ant;
  assign a1_withheld_ant = en_i && rst_warm_smc_clk_ni && warm_q && withheld_q;
  assign a1_cause_ant    = en_i && !cpu_uncore_reset_ni;
  assign a1_applied_ant  = en_i && rst_warm_smc_clk_ni && applied_q;

  `OCAH_SVA_ASSERT(SMC_RST_UNCORE_NOT_WHILE_WITHHELD, a1_withheld_ant |-> cpu_uncore_reset_ni,
                   clk_smc_i, primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_RST_UNCORE_LOW_HAS_CAUSE,
                   a1_cause_ant |-> (!rst_warm_smc_clk_ni || !warm_q || applied_q), clk_smc_i,
                   primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_RST_APPLIED_TAKES_EFFECT, a1_applied_ant |-> !cpu_uncore_reset_ni,
                   clk_smc_i, primary_reset_active)
  logic isolates_empty;
  assign isolates_empty = ({cpu_l2_pending_aw_i, cpu_l2_pending_ar_i,
                            cpu_mmio_pending_aw_i, cpu_mmio_pending_ar_i} == '0);
  `OCAH_SVA_ASSERT(SMC_ISO_DRAINED_MEANS_EMPTY, (en_i && cpu_drained_i) |-> isolates_empty,
                   clk_smc_i, primary_reset_active)

  // ------------------------------------------------------------------
  // A2: the cluster boundary is isolated whenever it is not ready, releases
  // only when ready now and four edges earlier, and is connected once ready
  // has held five edges (cpu.adoc 253-258).
  // ------------------------------------------------------------------
  logic a2_release_ant, a2_held_ant;
  assign a2_release_ant = en_i && !cpu_cluster_isolate_i && isolate_q;
  assign a2_held_ant    = en_i && cluster_ready && (ready_q == 4'hF);

  `OCAH_SVA_ASSERT(SMC_ISO_HELD_WHEN_NOT_READY, (en_i && !cluster_ready) |-> cpu_cluster_isolate_i,
                   clk_smc_i, primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_ISO_RELEASE_AFTER_FOUR, a2_release_ant |-> (cluster_ready && ready_q[3]),
                   clk_smc_i, primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_ISO_RELEASED_WHEN_READY_HELD, a2_held_ant |-> !cpu_cluster_isolate_i,
                   clk_smc_i, primary_reset_active)

  // ------------------------------------------------------------------
  // A3: an uncore reset holds every core on the same edge (cpu.adoc 157-158).
  // ------------------------------------------------------------------
  logic a3_ant;
  assign a3_ant = en_i && !cpu_uncore_reset_ni;

  `OCAH_SVA_ASSERT(SMC_RST_UNCORE_HOLDS_CORES, a3_ant |-> (cpu_core_resets_ni == '0), clk_smc_i,
                   powergood_lost)

  // ------------------------------------------------------------------
  // A4: the warm reset holds the cluster; the primary reset and the watchdog
  // reset each imply the warm reset (clk_rst.adoc 287-291, 299-301). The warm
  // JTAG override replaces the warm equation, so it is the one override that
  // qualifies the two implications; the fuse, cold and cool overrides enter
  // the equation as sources and keep it.
  // ------------------------------------------------------------------
  `OCAH_SVA_ASSERT(
      SMC_RST_WARM_HOLDS_CLUSTER,
      (en_i && !rst_warm_smc_clk_ni) |-> (!cpu_uncore_reset_ni && cpu_core_resets_ni == '0),
      clk_smc_i, powergood_lost)
  `OCAH_SVA_ASSERT(SMC_RST_PRIMARY_IMPLIES_WARM,
                   (en_i && warm_ovrd_idle && !rst_primary_smc_clk_ni) |-> !rst_warm_smc_clk_ni,
                   clk_smc_i, powergood_lost)
  `OCAH_SVA_ASSERT(SMC_RST_WDT_IMPLIES_WARM,
                   (en_i && warm_ovrd_idle && !rst_wdt_smc_clk_ni) |-> !rst_warm_smc_clk_ni,
                   clk_smc_i, powergood_lost)

  // ------------------------------------------------------------------
  // A5: an isolated L2 frontend accepts nothing; an isolated MMIO port
  // presents no address request to the fabric and answers the cluster with
  // SLVERR (cpu.adoc 245-249). The flush discards the cluster's write data
  // (cpu.adoc 297-299) and cannot cancel a beat presented without READY
  // (cpu.adoc 304-306), so a W beat the port presents while isolated is that
  // held beat, under the flush, and nothing else.
  // ------------------------------------------------------------------
  logic a5_l2_ant, a5_mmio_ant, a5_w_ant, a5_b_ant, a5_r_ant, l2_slv_accept;
  assign a5_l2_ant   = en_i && cpu_l2_isolated_i && (l2_slv_aw_valid_i || l2_slv_ar_valid_i);
  assign l2_slv_accept = (l2_slv_aw_valid_i && l2_slv_aw_ready_i)
                         || (l2_slv_ar_valid_i && l2_slv_ar_ready_i);
  assign a5_mmio_ant = en_i && cpu_mmio_isolated_i;
  assign a5_w_ant    = en_i && cpu_mmio_isolated_i && mmio_port_w_valid_i;
  assign a5_b_ant    = en_i && cpu_mmio_isolated_i && mmio_cpu_b_valid_i;
  assign a5_r_ant    = en_i && cpu_mmio_isolated_i && mmio_cpu_r_valid_i;

  `OCAH_SVA_ASSERT(SMC_ISO_L2_ACCEPTS_NONE, (en_i && cpu_l2_isolated_i) |-> !l2_slv_accept,
                   clk_smc_i, primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_ISO_MMIO_PRESENTS_NONE,
                   a5_mmio_ant |-> !(mmio_port_aw_valid_i || mmio_port_ar_valid_i), clk_smc_i,
                   primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_ISO_MMIO_W_ONLY_HELD, a5_w_ant |-> (cpu_mmio_flush_active_i && w_held_q),
                   clk_smc_i, primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_ISO_MMIO_B_SLVERR, a5_b_ant |-> (mmio_cpu_b_resp_i == RespSlvErr),
                   clk_smc_i, primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_ISO_MMIO_R_SLVERR, a5_r_ant |-> (mmio_cpu_r_resp_i == RespSlvErr),
                   clk_smc_i, primary_reset_active)

  // ------------------------------------------------------------------
  // A6: the status crossings are clamped while the boundary is isolated
  // (cpu.adoc 251-253).
  // ------------------------------------------------------------------
  logic status_clamped;
  assign status_clamped = (cpu_wb_pc_valid_i == '0) && (cpu_wb_reg_pc_i == '0)
                          && (cpu_wdt_reset_i == '0);
  `OCAH_SVA_ASSERT(SMC_ISO_STATUS_CLAMPED, (en_i && cpu_cluster_isolate_i) |-> status_clamped,
                   clk_smc_i, powergood_lost)

  // ------------------------------------------------------------------
  // A7: a request beat the MMIO port presents to the fabric under the
  // force-mode flush stays presented until accepted; the flush window is the
  // flush request and the isolate's latched flush, and the asynchronous warm
  // reset is outside the rule (cpu.adoc 304-306, 328-338).
  // ------------------------------------------------------------------
  logic a7_aw_ant, a7_w_ant, a7_ar_ant, a7_on;
  assign a7_on     = en_i && rst_warm_smc_clk_ni && mmio_flush;
  assign a7_aw_ant = a7_on && mmio_port_aw_valid_i && !mmio_port_aw_ready_i;
  assign a7_w_ant  = a7_on && mmio_port_w_valid_i && !mmio_port_w_ready_i;
  assign a7_ar_ant = a7_on && mmio_port_ar_valid_i && !mmio_port_ar_ready_i;

  `OCAH_SVA_ASSERT(SMC_MMIO_AW_HELD_UNDER_FLUSH,
                   a7_aw_ant |=> (mmio_port_aw_valid_i || !rst_warm_smc_clk_ni), clk_smc_i,
                   primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_MMIO_W_HELD_UNDER_FLUSH,
                   a7_w_ant |=> (mmio_port_w_valid_i || !rst_warm_smc_clk_ni), clk_smc_i,
                   primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_MMIO_AR_HELD_UNDER_FLUSH,
                   a7_ar_ant |=> (mmio_port_ar_valid_i || !rst_warm_smc_clk_ni), clk_smc_i,
                   primary_reset_active)

  // ------------------------------------------------------------------
  // A8: the flush is the force path and lives only while the boundary is
  // isolated (cpu.adoc 287-291, 297-298).
  // ------------------------------------------------------------------
  logic a8_rose_ant;
  assign a8_rose_ant = en_i && flush_active && !flush_active_q;

  `OCAH_SVA_ASSERT(SMC_FLUSH_IS_FORCE, en_i |-> (cpu_isolate_flush_i == force_apply), clk_smc_i,
                   primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_FLUSH_WINDOW_CLOSES_AT_RECONNECT,
                   (en_i && !cpu_cluster_isolate_i) |=> !flush_active, clk_smc_i,
                   primary_reset_active)
  `OCAH_SVA_ASSERT(SMC_FLUSH_ONLY_WHEN_FORCED, a8_rose_ant |-> force_apply_q, clk_smc_i,
                   primary_reset_active)

  // ------------------------------------------------------------------
  // A9: one FLR edge taken with the sequencer idle starts at most one cool
  // reset pulse, and no pulse starts from a zero hold count
  // (clk_rst.adoc 410-414, 418-419). An edge arriving with the sequencer idle
  // and the cool reset high is the one the sequencer judges: its hold count is
  // latched, and flr_edge_pending is set when that count is nonzero and
  // cleared by the fall of the cool reset.
  // ------------------------------------------------------------------
  logic flr_edge_pending, flr_cool_reset_q, flr_edge_taken;
  logic [FLR_CNT_WIDTH-1:0] flr_hold_at_edge;
  assign flr_edge_taken = flr_posedge_ref_i && flr_cool_reset_ni && flr_counter_state_i == '0;
  always_ff @(posedge clk_ref_i or negedge rst_cold_stable_ref_clk_ni) begin
    if (!rst_cold_stable_ref_clk_ni) begin
      flr_edge_pending <= 1'b0;
      flr_cool_reset_q <= 1'b1;
      flr_hold_at_edge <= '0;
    end else begin
      flr_cool_reset_q <= flr_cool_reset_ni;
      if (flr_edge_taken) flr_hold_at_edge <= flr_hold_count_ref_i;
      if (flr_edge_taken && flr_hold_count_ref_i != '0) begin
        flr_edge_pending <= 1'b1;
      end else if (!flr_cool_reset_ni && flr_cool_reset_q) begin
        flr_edge_pending <= 1'b0;
      end
    end
  end

  logic a9_fall_ant;
  assign a9_fall_ant = en_i && !flr_cool_reset_ni && flr_cool_reset_q;

  `OCAH_SVA_ASSERT(SMC_FLR_ONE_PULSE_PER_EDGE,
                   (a9_fall_ant && !flr_requeue_assertoff) |-> flr_edge_pending, clk_ref_i,
                   cold_reset_ref_active)
  `OCAH_SVA_ASSERT(SMC_FLR_HOLD_ZERO_NO_PULSE, a9_fall_ant |-> (flr_hold_at_edge != '0), clk_ref_i,
                   cold_reset_ref_active)

  // ------------------------------------------------------------------
  // A10: the cool-reset-out pad (BP_COOL_RESET_N_O) is driven low while the
  // cool reset is asserted and left undriven otherwise, while the pad is on
  // its LSIO function (clk_rst.adoc 440-442).
  // ------------------------------------------------------------------
  logic a10_low_ant;
  assign a10_low_ant = en_i && cool_pad_lsio_pin_i && !cool_reset_ni;

  `OCAH_SVA_ASSERT(SMC_FLR_COOL_PAD_PULLS_LOW,
                   a10_low_ant |-> (cool_pad_core2pad_en_i && !cool_pad_core2pad_i), clk_ref_i,
                   cold_reset_ref_active)
  `OCAH_SVA_ASSERT(SMC_FLR_COOL_PAD_UNDRIVEN,
                   (en_i && cool_pad_lsio_pin_i && cool_reset_ni) |-> !cool_pad_core2pad_en_i,
                   clk_ref_i, cold_reset_ref_active)

  // ------------------------------------------------------------------
  // Non-vacuity counts, one per rule group, on the group's clock.
  // ------------------------------------------------------------------
  int unsigned cnt_uncore_withheld, cnt_uncore_cause, cnt_uncore_applied;
  int unsigned cnt_iso_release, cnt_iso_ready_held, cnt_uncore_low;
  int unsigned cnt_iso_l2_blocked, cnt_iso_mmio_resp, cnt_mmio_held, cnt_flush_rose;
  int unsigned cnt_flr_fall, cnt_cool_pad_low;

  // A release that follows an applied software request, and an uncore reset
  // after the first release: the cold-boot release and the bring-up reset of
  // every run do not count.
  bit sw_request_applied, uncore_released_once;
  always_ff @(posedge clk_smc_i) begin
    if (!rst_primary_smc_clk_ni) sw_request_applied <= 1'b0;
    else if (a2_release_ant) sw_request_applied <= 1'b0;
    else if (cpu_reset_applied_i) sw_request_applied <= 1'b1;
    if (powergood_stable_i && cpu_uncore_reset_ni) uncore_released_once <= 1'b1;
  end

  always_ff @(posedge clk_smc_i) begin
    if (rst_primary_smc_clk_ni) begin
      if (a1_withheld_ant) cnt_uncore_withheld <= cnt_uncore_withheld + 1;
      if (a1_cause_ant && rst_warm_smc_clk_ni && warm_q) cnt_uncore_cause <= cnt_uncore_cause + 1;
      if (a1_applied_ant) cnt_uncore_applied <= cnt_uncore_applied + 1;
      if (a2_release_ant && sw_request_applied) cnt_iso_release <= cnt_iso_release + 1;
      if (a2_held_ant) cnt_iso_ready_held <= cnt_iso_ready_held + 1;
      if (a5_l2_ant) cnt_iso_l2_blocked <= cnt_iso_l2_blocked + 1;
      if (a5_b_ant || a5_r_ant) cnt_iso_mmio_resp <= cnt_iso_mmio_resp + 1;
      if (a7_aw_ant || a7_w_ant || a7_ar_ant) cnt_mmio_held <= cnt_mmio_held + 1;
      if (a8_rose_ant) cnt_flush_rose <= cnt_flush_rose + 1;
    end
    if (powergood_stable_i && uncore_released_once && a3_ant) cnt_uncore_low <= cnt_uncore_low + 1;
  end

  always_ff @(posedge clk_ref_i) begin
    if (rst_cold_stable_ref_clk_ni) begin
      if (a9_fall_ant) cnt_flr_fall <= cnt_flr_fall + 1;
      if (a10_low_ant) cnt_cool_pad_low <= cnt_cool_pad_low + 1;
    end
  end

  // verilog_format: off
`define SMC_RESET_SVA_REPORT(__group, __plusarg, __cnt)                                 \
    $display("CHK-RESET-SVA-%0s: antecedent_edges=%0d", __group, __cnt);                \
    if ($test$plusargs(__plusarg) && __cnt == 0)                                        \
      $error("smc_reset_sva: +%0s, but its antecedent never held", __plusarg);          \
    if (need_group == __group) need_known = 1'b1;
  // verilog_format: on

  final begin
    string need_group;
    bit need_present, need_known;
    need_present = $value$plusargs("smc_reset_sva_need_%s", need_group);
    need_known   = 1'b0;
    `SMC_RESET_SVA_REPORT("uncore_withheld", "smc_reset_sva_need_uncore_withheld",
                          cnt_uncore_withheld)
    `SMC_RESET_SVA_REPORT("uncore_cause", "smc_reset_sva_need_uncore_cause", cnt_uncore_cause)
    `SMC_RESET_SVA_REPORT("uncore_applied", "smc_reset_sva_need_uncore_applied", cnt_uncore_applied)
    `SMC_RESET_SVA_REPORT("iso_release", "smc_reset_sva_need_iso_release", cnt_iso_release)
    `SMC_RESET_SVA_REPORT("iso_ready_held", "smc_reset_sva_need_iso_ready_held", cnt_iso_ready_held)
    `SMC_RESET_SVA_REPORT("uncore_low", "smc_reset_sva_need_uncore_low", cnt_uncore_low)
    `SMC_RESET_SVA_REPORT("iso_l2_blocked", "smc_reset_sva_need_iso_l2_blocked", cnt_iso_l2_blocked)
    `SMC_RESET_SVA_REPORT("iso_mmio_resp", "smc_reset_sva_need_iso_mmio_resp", cnt_iso_mmio_resp)
    `SMC_RESET_SVA_REPORT("mmio_held", "smc_reset_sva_need_mmio_held", cnt_mmio_held)
    `SMC_RESET_SVA_REPORT("flush_rose", "smc_reset_sva_need_flush_rose", cnt_flush_rose)
    `SMC_RESET_SVA_REPORT("flr_fall", "smc_reset_sva_need_flr_fall", cnt_flr_fall)
    `SMC_RESET_SVA_REPORT("cool_pad_low", "smc_reset_sva_need_cool_pad_low", cnt_cool_pad_low)
    if (need_present && !need_known)
      $error("smc_reset_sva: +smc_reset_sva_need_%0s names no rule group", need_group);
  end
  `undef SMC_RESET_SVA_REPORT

endmodule : smc_reset_sva
