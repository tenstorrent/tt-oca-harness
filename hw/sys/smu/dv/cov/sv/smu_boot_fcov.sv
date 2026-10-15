// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU boot and reset-sequencing functional coverage: the `smc_boot_cg`
// bringup intent of smu_fcov.py as cover-property points in the `user`
// metric family.
//
// One passive, signal-driven module. Every port is a signal of the bench
// top, so the module needs no hierarchical reference and no public-scope
// change.
//
// DISABLE CONVENTION, unlike the other SMU cov/sv modules: the gate is
// powergood, not reset. A reset-assertion point behind `disable iff (in
// reset)` can never fire. Once power is good the signals are driven and the
// reset sequence itself stays observable.
//
// Points must need stimulus beyond power-up and reset release. A level that
// is true in the quiescent state is either absent here or qualified by a
// sticky flag recording that its counterpart happened first.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch -- without one a four-state simulator holds it at X
// and the points that read it are unhittable on the commercial path.
//
// NOTE: a `//` comment must not open with the word "verilator" -- the lexer
// reads it as a pragma and BADVLTPRAGMA fails the build.

`include "ocah_fcov_macros.svh"

module smu_boot_fcov #(
  // 0 on an elaboration without SEP. The LCC demote pair is driven by the SEP
  // lifecycle controller, so smu.sv's gen_no_sep branch ties both to '0 and
  // the points that read them are dropped rather than carried unhittable.
  parameter bit SEP_PRESENT = 1'b1
) (
  input wire clk_ref_i,
  input wire clk_smu_i,

  // Power and cold reset stimulus.
  input wire powergood_i,
  input wire rst_cold_ni,
  input wire ext_boot_seq_done_i,

  // Reset-release observables, in the order the bringup walks them.
  input wire rst_cold_stable_ref_clk_ni,
  input wire rst_primary_ref_clk_ni,
  input wire rst_primary_smc_clk_ni,
  input wire rst_primary_periph_clk_ni,

  // Boot-time completion pins.
  input wire init_mem_done_i,
  input wire fuse_sense_done_i,
  input wire fuse_reset_n_delayed_i,

  // Boot-stall sources: the JTAG override pair and the GPIO strap drive.
  input wire jtag_boot_stall_ovrd_i,
  input wire jtag_boot_stall_i,
  input wire gpio_boot_stall_drive_i,

  // Lifecycle broadcast.
  input wire [7:0] lc_state_i,
  input wire lc_sigint_err_i,
  input wire [1:0] lcc_demote_state_1_i,
  input wire [1:0] lcc_demote_state_2_i
);

  // Powergood-only gate; see the DISABLE CONVENTION note in the header.
  wire not_powered = (powergood_i !== 1'b1);

  // ------------------------------------------------------------------
  // Reset release, as edges. The released level is true for the whole run
  // once bringup completes, so only the transition is covered.
  // ------------------------------------------------------------------
  logic cold_stable_q, primary_ref_q, primary_periph_q;
  always_ff @(posedge clk_ref_i) begin
    if (not_powered) begin
      cold_stable_q <= 1'b0;
      primary_ref_q <= 1'b0;
      primary_periph_q <= 1'b0;
    end else begin
      cold_stable_q <= rst_cold_stable_ref_clk_ni;
      primary_ref_q <= rst_primary_ref_clk_ni;
      primary_periph_q <= rst_primary_periph_clk_ni;
    end
  end

  wire release_cold_stable_e = (rst_cold_stable_ref_clk_ni === 1'b1) && (cold_stable_q === 1'b0);
  wire release_primary_ref_e = (rst_primary_ref_clk_ni === 1'b1) && (primary_ref_q === 1'b0);
  wire release_primary_periph_e =
      (rst_primary_periph_clk_ni === 1'b1) && (primary_periph_q === 1'b0);
  `OCAH_FCOV_COVER(c_release_cold_stable_ref, release_cold_stable_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_release_primary_ref, release_primary_ref_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_release_primary_periph, release_primary_periph_e, clk_ref_i, not_powered)

  logic primary_smc_q, init_mem_q, fuse_sense_q, fuse_rst_q;
  always_ff @(posedge clk_smu_i) begin
    if (not_powered) begin
      primary_smc_q <= 1'b0;
      init_mem_q <= 1'b0;
      fuse_sense_q <= 1'b0;
      fuse_rst_q <= 1'b0;
    end else begin
      primary_smc_q <= rst_primary_smc_clk_ni;
      init_mem_q <= init_mem_done_i;
      fuse_sense_q <= fuse_sense_done_i;
      fuse_rst_q <= fuse_reset_n_delayed_i;
    end
  end

  wire release_primary_smc_e = (rst_primary_smc_clk_ni === 1'b1) && (primary_smc_q === 1'b0);
  wire init_mem_done_e = (init_mem_done_i === 1'b1) && (init_mem_q === 1'b0);
  wire fuse_sense_done_e = (fuse_sense_done_i === 1'b1) && (fuse_sense_q === 1'b0);
  wire fuse_reset_release_e = (fuse_reset_n_delayed_i === 1'b1) && (fuse_rst_q === 1'b0);
  `OCAH_FCOV_COVER(c_release_primary_smc, release_primary_smc_e, clk_smu_i, not_powered)
  `OCAH_FCOV_COVER(c_init_mem_done, init_mem_done_e, clk_smu_i, not_powered)
  `OCAH_FCOV_COVER(c_fuse_sense_done, fuse_sense_done_e, clk_smu_i, not_powered)
  `OCAH_FCOV_COVER(c_fuse_reset_released, fuse_reset_release_e, clk_smu_i, not_powered)

  // Cold reset re-asserted after a completed release: proof a reset test
  // drove a second reset rather than only observing the power-on one.
  wire reassert_cold_e = (rst_cold_stable_ref_clk_ni === 1'b0) && (cold_stable_q === 1'b1);
  wire cold_asserted_e = (rst_cold_ni === 1'b0);
  `OCAH_FCOV_COVER(c_reassert_cold_after_release, reassert_cold_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_cold_reset_asserted, cold_asserted_e, clk_ref_i, not_powered)

  // ------------------------------------------------------------------
  // Boot-stall sources. Both override polarities are product states, and
  // the release is qualified by an applied stall having been seen, so it
  // means "the stall lifted" rather than "no stall was ever applied".
  // ------------------------------------------------------------------
  wire jtag_stall_applied_e = (jtag_boot_stall_ovrd_i === 1'b1) && (jtag_boot_stall_i === 1'b1);
  wire jtag_stall_forced_low_e =
      (jtag_boot_stall_ovrd_i === 1'b1) && (jtag_boot_stall_i === 1'b0);
  wire gpio_stall_drive_e = (gpio_boot_stall_drive_i === 1'b1);
  wire ext_boot_seq_done_e = (ext_boot_seq_done_i === 1'b1);

  logic jtag_stall_seen_q, gpio_stall_seen_q;
  always_ff @(posedge clk_ref_i) begin
    if (not_powered) begin
      jtag_stall_seen_q <= 1'b0;
      gpio_stall_seen_q <= 1'b0;
    end else begin
      if (jtag_stall_applied_e) jtag_stall_seen_q <= 1'b1;
      if (gpio_stall_drive_e) gpio_stall_seen_q <= 1'b1;
    end
  end

  wire jtag_stall_released_e = jtag_stall_seen_q && (jtag_boot_stall_ovrd_i === 1'b0);
  wire gpio_stall_released_e = gpio_stall_seen_q && (gpio_boot_stall_drive_i === 1'b0);
  wire stall_from_both_sources_e = jtag_stall_applied_e && gpio_stall_drive_e;
  `OCAH_FCOV_COVER(c_boot_stall_jtag_applied, jtag_stall_applied_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_boot_stall_jtag_forced_low, jtag_stall_forced_low_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_boot_stall_jtag_released, jtag_stall_released_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_boot_stall_gpio_drive, gpio_stall_drive_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_boot_stall_gpio_released, gpio_stall_released_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_boot_stall_both_sources, stall_from_both_sources_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_ext_boot_seq_done, ext_boot_seq_done_e, clk_ref_i, not_powered)

  // ------------------------------------------------------------------
  // Lifecycle broadcast. lc_state takes whatever the fuses leave at
  // power-up, so the state points are qualified by the broadcast having
  // changed at least once; the sigint and demote pins are events already.
  // ------------------------------------------------------------------
  logic [7:0] lc_state_q;
  logic lc_state_changed_q;
  always_ff @(posedge clk_smu_i) begin
    if (not_powered) begin
      lc_state_q <= lc_state_i;
      lc_state_changed_q <= 1'b0;
    end else begin
      lc_state_q <= lc_state_i;
      if (lc_state_i !== lc_state_q) lc_state_changed_q <= 1'b1;
    end
  end

  wire lc_state_changed_e = lc_state_changed_q;
  `OCAH_FCOV_COVER(c_lc_state_changed, lc_state_changed_e, clk_smu_i, not_powered)

  // Each demote lane at its demoted code, and both lanes at once. Each lane is
  // a differential code: 2'b10 not demoted, 2'b01 demoted. Only elaborated
  // with SEP present: the lanes are lifecycle-controller outputs and are tied
  // to constants without it.
  //
  // lc_sigint_err rises only when the LC_STATE pair the SEP exports disagrees
  // with itself. No eFuse image produces that; the bench's LC_STATE pair fault
  // inject (+lc_sigint_inject) does. Without the SEP the pair is a constant.
  if (SEP_PRESENT) begin : g_sep
    localparam logic [1:0] DemoteOn = 2'b01;
    wire lcc_demote_1_e = (lcc_demote_state_1_i === DemoteOn);
    wire lcc_demote_2_e = (lcc_demote_state_2_i === DemoteOn);
    wire lcc_demote_both_e = lcc_demote_1_e && lcc_demote_2_e;
    wire lc_sigint_err_e = (lc_sigint_err_i === 1'b1);
    `OCAH_FCOV_COVER(c_lc_sigint_err, lc_sigint_err_e, clk_smu_i, not_powered)
    `OCAH_FCOV_COVER(c_lcc_demote_state_1, lcc_demote_1_e, clk_smu_i, not_powered)
    `OCAH_FCOV_COVER(c_lcc_demote_state_2, lcc_demote_2_e, clk_smu_i, not_powered)
    `OCAH_FCOV_COVER(c_lcc_demote_both, lcc_demote_both_e, clk_smu_i, not_powered)
  end

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups: the crosses a flat point list
  // cannot express.
  // ------------------------------------------------------------------
  covergroup cg_boot_stall with function sample (logic jtag_ovrd, logic jtag_val, logic gpio_drive);
    option.per_instance = 1;
    cp_jtag_ovrd: coverpoint jtag_ovrd;
    cp_jtag_val: coverpoint jtag_val;
    cp_gpio_drive: coverpoint gpio_drive;
    x_sources: cross cp_jtag_ovrd, cp_gpio_drive;
  endgroup

  // lc_state is the differential pair {~state, state} of the 4-bit lifecycle
  // state (prim_diff_decode_multi), so of its 256 codes only the seven
  // efuse_pkg::lc_state_raw_e encodings are states; every other code is an
  // integrity error and falls in the default bin ungraded.
  covergroup cg_lifecycle with function sample (
      logic [7:0] lc_state, logic [1:0] demote1, logic [1:0] demote2
  );
    option.per_instance = 1;
    cp_lc_state: coverpoint lc_state {
      bins test_dev = {8'hF0};  // LC_TEST_DEV   4'b0000
      bins prod = {8'hE1};  // LC_PROD       4'b0001
      bins rma_sip_0 = {8'hD2};  // LC_RMA_SIP_0  4'b0010
      bins rma_sip_1 = {8'hC3};  // LC_RMA_SIP_1  4'b0011
      bins rma_chip_0 = {8'h96};  // LC_RMA_CHIP_0 4'b0110
      bins rma_chip_1 = {8'h87};  // LC_RMA_CHIP_1 4'b0111
      bins prod_end = {8'h78};  // LC_PROD_END   4'b1000
      bins invalid = default;
    }
    // Each demote lane is a differential code, 2'b10 or 2'b01; 2'b00 and 2'b11
    // are not codes.
    cp_demote1: coverpoint demote1 {
      ignore_bins not_a_code = {2'b00, 2'b11};
    }
    cp_demote2: coverpoint demote2 {ignore_bins not_a_code = {2'b00, 2'b11};}
    x_demote: cross cp_demote1, cp_demote2;
  endgroup

  cg_boot_stall u_cg_boot_stall = new();
  cg_lifecycle u_cg_lifecycle = new();

  always_ff @(posedge clk_ref_i) begin
    if (!not_powered) begin
      u_cg_boot_stall.sample(jtag_boot_stall_ovrd_i, jtag_boot_stall_i, gpio_boot_stall_drive_i);
    end
  end

  always_ff @(posedge clk_smu_i) begin
    if (!not_powered) begin
      u_cg_lifecycle.sample(lc_state_i, lcc_demote_state_1_i, lcc_demote_state_2_i);
    end
  end
`endif

endmodule : smu_boot_fcov
