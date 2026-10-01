// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC reset functional coverage: the `reset_op` and `reset_state` intent of
// SMC_FCOV.adoc expressed as native cover-property points, so the public
// flow records them in the `user` metric family (--coverage-user) instead
// of only as scoreboard log text.
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
// assertion itself stays observable.
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
  input wire ndmreset_irq_i
);

  // Powergood-only gate; see the DISABLE CONVENTION note in the header.
  wire not_powered = (powergood_i !== 1'b1);

  // ------------------------------------------------------------------
  // reset_op — each reset source seen asserted. One point per source
  // rather than one saturating tuple: a source with no stimulus stays a
  // named, individually reportable hole.
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
  // reset_state — the post-reset 4-tuple. SMC_FCOV.adoc records the
  // Python bin saturating at unique<=3 because the DUT releases the bits
  // synchronously. Splitting the tuple into all-held / partial / all-
  // released keeps the partially-released window (the mid-glitch state
  // RAW_SAMPLE observes) as its own point instead of hiding it in a
  // tuple whose unique count cannot distinguish the cases.
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

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups mirroring the points above. The
  // cross of reset source against release state is the part a flat list
  // of cover properties cannot express.
  // ------------------------------------------------------------------
  covergroup cg_reset_state with function sample (logic [3:0] state);
    option.per_instance = 1;
    cp_state: coverpoint state {
      bins all_held = {4'b0000};
      bins all_released = {4'b1111};
      bins partial[] = {[4'b0001 : 4'b1110]};
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
    // The group samples on clk_smc_i, which tb_top binds to the PLL output
    // clock. Design fact, for design-engineering review: cold reset asserts
    // warm reset in the same timestep through the fuse-reset path. fuse_reset_ni falls with cold,
    // because u_ext_boot_seq_done_qual is asynchronously reset by the raw cold
    // pin (hw/sys/smc/rtl/smc_peripherals/rtl/smc_peripherals.sv), so the
    // cold-without-warm state never holds. Retired by a design change that
    // sequences warm after cold, or by a specification stating the ordering.
    x_cold_warm: cross cp_cold, cp_warm{
      ignore_bins cold_without_warm = binsof (cp_cold.asserted) && binsof (cp_warm.released);
    }
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
`endif

endmodule : smc_reset_fcov
