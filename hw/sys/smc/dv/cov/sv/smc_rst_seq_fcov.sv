// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC reset-sequencing functional coverage: the power-on ordering, the
// asynchronous-assert / synchronous-deassert contract of the primary reset,
// what the primary reset holds, the warm cascade, and the boot-sequence gate
// on the fuse reset.
//
// smc_reset_fcov carries the per-source assertion and release-edge points;
// this module carries the relationships between them.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal or a smc_wrapper boundary port.
//
// DISABLE CONVENTION, as in smc_reset_fcov: the gate is powergood, not
// reset, so reset assertion itself stays observable. The "seen" flags that
// qualify the held-state points clear with powergood for the same reason.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_rst_seq_fcov (
  input wire clk_ref_i,
  input wire clk_smc_i,
  input wire clk_periph_i,

  // Reset stimulus (TB -> DUT).
  input wire powergood_i,
  input wire rst_cold_ni,
  input wire ext_boot_seq_done_i,
  input wire rst_telemetry_ni,

  // Reset observables (DUT -> TB).
  input wire powergood_stable_i,
  input wire rst_cold_stable_ref_clk_ni,
  input wire rst_primary_smc_clk_ni,
  input wire rst_primary_periph_clk_ni,
  input wire rst_warm_smc_clk_ni,
  input wire fuse_sense_done_i,
  input wire fuse_reset_ni,
  input wire cpu_core_reset_ni,

  // What the primary reset holds.
  input wire sep_awready_i,
  input wire sep_arready_i,
  input wire [31:0] region_size_i,
  input wire [31:0] scratch_0_i,
  input wire [31:0] ss_config_i
);

  wire not_powered = (powergood_i !== 1'b1);

  // ------------------------------------------------------------------
  // Power-on: powergood_i is stretched into powergood_stable, and the cold
  // reset path waits for it.
  // ------------------------------------------------------------------
  logic powergood_stable_q, cold_stable_q;
  logic [7:0] powergood_hi_cnt_q;
  always_ff @(posedge clk_ref_i) begin
    powergood_stable_q <= powergood_stable_i;
    cold_stable_q <= rst_cold_stable_ref_clk_ni;
    if (not_powered) powergood_hi_cnt_q <= '0;
    else if (powergood_hi_cnt_q != 8'hFF) powergood_hi_cnt_q <= powergood_hi_cnt_q + 8'd1;
  end

  wire release_powergood_stable = (powergood_stable_i === 1'b1) && (powergood_stable_q === 1'b0);
  wire release_cold_stable = (rst_cold_stable_ref_clk_ni === 1'b1) && (cold_stable_q === 1'b0);

  wire powergood_rise_stretched_e = release_powergood_stable && (powergood_hi_cnt_q >= 8'd2);
  wire cold_gated_before_powergood_e = (rst_cold_ni === 1'b1) && (powergood_stable_i === 1'b0)
      && (rst_cold_stable_ref_clk_ni === 1'b0);
  wire cold_released_after_powergood_e = release_cold_stable && (powergood_stable_i === 1'b1);
  `OCAH_FCOV_COVER(c_powergood_rise_stretched, powergood_rise_stretched_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_cold_reset_gated_before_powergood, cold_gated_before_powergood_e, clk_ref_i,
                   not_powered)
  `OCAH_FCOV_COVER(c_cold_reset_released_after_powergood, cold_released_after_powergood_e,
                   clk_ref_i, not_powered)

  // ------------------------------------------------------------------
  // Cold reset into the primary reset: asserted in the same sample that
  // first sees the input low, released only after the input has been high
  // for whole cycles, through at least two synchronizer stages.
  // ------------------------------------------------------------------
  logic cold_ni_q, primary_smc_q, primary_periph_q;
  logic [7:0] cold_hi_cnt_q;
  always_ff @(posedge clk_smc_i) begin
    cold_ni_q <= rst_cold_ni;
    primary_smc_q <= rst_primary_smc_clk_ni;
    if (rst_cold_ni !== 1'b1) cold_hi_cnt_q <= '0;
    else if (cold_hi_cnt_q != 8'hFF) cold_hi_cnt_q <= cold_hi_cnt_q + 8'd1;
  end
  always_ff @(posedge clk_periph_i) primary_periph_q <= rst_primary_periph_clk_ni;

  wire cold_fell = (rst_cold_ni === 1'b0) && (cold_ni_q === 1'b1);
  wire release_primary_smc = (rst_primary_smc_clk_ni === 1'b1) && (primary_smc_q === 1'b0);
  wire release_primary_periph_e =
      (rst_primary_periph_clk_ni === 1'b1) && (primary_periph_q === 1'b0);

  wire cold_async_assert_e = cold_fell && (rst_primary_smc_clk_ni === 1'b0);
  wire cold_sync_deassert_e = release_primary_smc && (rst_cold_ni === 1'b1) && (cold_ni_q === 1'b1);
  wire multi_stage_sync_e = release_primary_smc && (cold_hi_cnt_q >= 8'd2);
  `OCAH_FCOV_COVER(c_cold_reset_async_assert, cold_async_assert_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_async_assert_observed, cold_async_assert_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_cold_reset_sync_deassert, cold_sync_deassert_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_sync_deassert_observed, cold_sync_deassert_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_multi_stage_sync_present, multi_stage_sync_e, clk_smc_i, not_powered)
  // The bare primary-reset release edge on clk_smc is smc_reset_fcov's
  // c_release_primary_smc; the cell map points at that one.
  `OCAH_FCOV_COVER(c_release_primary_periph, release_primary_periph_e, clk_periph_i, not_powered)

  // ------------------------------------------------------------------
  // What the primary reset holds. Held is the state at power-up, so each
  // point is qualified by that domain having been released once: it means
  // "held again by a later primary reset", not "nothing has happened yet".
  // ------------------------------------------------------------------
  logic primary_released_seen_q, core_released_seen_q, warm_released_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (not_powered) begin
      primary_released_seen_q <= 1'b0;
      core_released_seen_q <= 1'b0;
      warm_released_seen_q <= 1'b0;
    end else begin
      if (rst_primary_smc_clk_ni === 1'b1) primary_released_seen_q <= 1'b1;
      if (cpu_core_reset_ni === 1'b1) core_released_seen_q <= 1'b1;
      if (rst_warm_smc_clk_ni === 1'b1) warm_released_seen_q <= 1'b1;
    end
  end

  wire primary_held = (rst_primary_smc_clk_ni === 1'b0);
  wire cores_held_e = core_released_seen_q && primary_held && (cpu_core_reset_ni === 1'b0);
  wire fabric_held_e = primary_released_seen_q && primary_held && (sep_awready_i === 1'b0)
      && (sep_arready_i === 1'b0);
  wire peripherals_held_e = primary_released_seen_q && primary_held
      && (rst_primary_periph_clk_ni === 1'b0);
  wire warm_cascaded_e = warm_released_seen_q && primary_held && (rst_warm_smc_clk_ni === 1'b0);
  `OCAH_FCOV_COVER(c_cores_held_in_primary_reset, cores_held_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_fabric_held_in_primary_reset, fabric_held_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_peripherals_held_in_primary_reset, peripherals_held_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_warm_cascaded_from_primary, warm_cascaded_e, clk_smc_i, not_powered)

  // Configuration registers at their reset values in the sample that
  // releases the primary reset: REGION_SIZE 16 MiB, SCRATCH_0 zero.
  wire region_size_reset_e = release_primary_smc && (region_size_i === 32'h0100_0000);
  wire config_at_reset_value_e = region_size_reset_e && (scratch_0_i === 32'h0000_0000);
  `OCAH_FCOV_COVER(c_region_size_reset_16mib, region_size_reset_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_config_registers_at_reset_value, config_at_reset_value_e, clk_smc_i,
                   not_powered)

  // ss_config_o driven to a new value while out of reset.
  logic [31:0] ss_config_q;
  always_ff @(posedge clk_smc_i) ss_config_q <= ss_config_i;
  wire ss_config_driven_e = (rst_primary_smc_clk_ni === 1'b1) && (ss_config_i !== ss_config_q)
      && (^ss_config_q !== 1'bx);
  `OCAH_FCOV_COVER(c_ss_config_driven, ss_config_driven_e, clk_smc_i, not_powered)

  // ------------------------------------------------------------------
  // Boot-sequence gate: the fuse reset stays held after sense completes
  // while ext_boot_seq_done_i is low, and releases once it is high.
  // ------------------------------------------------------------------
  logic fuse_reset_q;
  always_ff @(posedge clk_smc_i) fuse_reset_q <= fuse_reset_ni;
  wire release_fuse_reset = (fuse_reset_ni === 1'b1) && (fuse_reset_q === 1'b0);

  wire reset_held_before_boot_seq_e = (fuse_sense_done_i === 1'b1) && (ext_boot_seq_done_i === 1'b0)
      && (fuse_reset_ni === 1'b0);
  wire reset_released_after_boot_seq_e = release_fuse_reset && (ext_boot_seq_done_i === 1'b1);
  `OCAH_FCOV_COVER(c_reset_held_before_boot_seq_done, reset_held_before_boot_seq_e, clk_smc_i,
                   not_powered)
  `OCAH_FCOV_COVER(c_reset_released_after_boot_seq_done, reset_released_after_boot_seq_e,
                   clk_smc_i, not_powered)

  // ------------------------------------------------------------------
  // Telemetry reset, on the telemetry clock (clk_smc_i in this tb).
  // ------------------------------------------------------------------
  logic telemetry_rst_q;
  always_ff @(posedge clk_smc_i) telemetry_rst_q <= rst_telemetry_ni;
  wire telemetry_reset_asserted_e = (rst_telemetry_ni === 1'b0);
  wire telemetry_reset_released_e = (rst_telemetry_ni === 1'b1) && (telemetry_rst_q === 1'b0);
  `OCAH_FCOV_COVER(c_telemetry_reset_asserted, telemetry_reset_asserted_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_telemetry_reset_released, telemetry_reset_released_e, clk_smc_i, not_powered)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the held-domain tuple while the primary
  // reset is asserted, which the flat list cannot cross.
  // ------------------------------------------------------------------
  covergroup cg_primary_holds with function sample (
      logic core_held, logic fabric_held, logic periph_held, logic warm_held
  );
    option.per_instance = 1;
    // Sampled only while the primary SMC reset is held. The core, periph and
    // warm resets sit below it in the same tree, so none of them is released
    // during the hold; the SEP_IN port's ready terms are driven by the
    // fabric, which the primary hold does not lower.
    cp_core: coverpoint core_held {ignore_bins released_during_hold = {1'b0};}
    cp_fabric: coverpoint fabric_held {ignore_bins ready_lowered_by_hold = {1'b1};}
    cp_periph: coverpoint periph_held {ignore_bins released_during_hold = {1'b0};}
    cp_warm: coverpoint warm_held {ignore_bins released_during_hold = {1'b0};}
    x_holds: cross cp_core, cp_fabric, cp_periph, cp_warm;
  endgroup

  cg_primary_holds u_cg_primary_holds = new();

  always_ff @(posedge clk_smc_i) begin
    if (!not_powered && primary_held) begin
      u_cg_primary_holds.sample(cpu_core_reset_ni === 1'b0,
                                (sep_awready_i === 1'b0) && (sep_arready_i === 1'b0),
                                rst_primary_periph_clk_ni === 1'b0, rst_warm_smc_clk_ni === 1'b0);
    end
  end
`endif

endmodule : smc_rst_seq_fcov
