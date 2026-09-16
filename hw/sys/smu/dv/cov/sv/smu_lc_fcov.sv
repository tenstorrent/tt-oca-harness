// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU lifecycle-boundary and SEP=0 composition functional coverage, from
// the SMU-LC-STATE, SMU-LC-DEMOTE and SMU-NOSEP scenarios of the feature
// list.
//
// One passive, signal-driven module shared by tb_top and tb_wrapper_top.
// Every port is a signal both benches expose at their top level.
//
// The lifecycle outputs are static once the fuses are read, so a level on
// them proves nothing by itself. Every point here samples at the primary
// reset release edge: the moment the boundary values are first presented
// to the rest of the chiplet, and one that only the reset sequence produces.
// Presence is X-aware ($isunknown), so a four-state run distinguishes a
// driven output from an undriven one.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_lc_fcov #(
  parameter bit SepPresent = 1'b1
) (
  input wire clk_smu_i,
  input wire rst_cold_ni,
  input wire rst_primary_smc_clk_ni,

  // Lifecycle broadcast at the SMU boundary.
  input wire [2*smc_pkg::LC_STATE_WIDTH-1:0] lc_state_i,
  input wire [1:0] lcc_demote_state_1_i,
  input wire [1:0] lcc_demote_state_2_i,

  // SEP-facing outputs a SEP=0 build ties off.
  input wire [55:0] sep_global_base_i,
  input wire [55:0] sep_region_size_i,
  input wire sep_fuse_sense_done_i
);

  localparam logic [7:0] LcStateSep0 = 8'hf0;

  wire in_reset = (rst_cold_ni !== 1'b1);

  logic primary_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      primary_q <= 1'b0;
    end else begin
      primary_q <= rst_primary_smc_clk_ni;
    end
  end

  wire primary_rose_e = (rst_primary_smc_clk_ni === 1'b1) && (primary_q === 1'b0);

  wire lc_state_width_8_e =
      primary_rose_e && ($bits(lc_state_i) == 8) && !$isunknown(lc_state_i);
  wire demote_1_width_2_e =
      primary_rose_e && ($bits(lcc_demote_state_1_i) == 2) && !$isunknown(lcc_demote_state_1_i);
  wire demote_2_width_2_e =
      primary_rose_e && ($bits(lcc_demote_state_2_i) == 2) && !$isunknown(lcc_demote_state_2_i);
  `OCAH_FCOV_COVER(c_lc_state_width_8, lc_state_width_8_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_demote_1_width_2, demote_1_width_2_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_demote_2_width_2, demote_2_width_2_e, clk_smu_i, in_reset)

  // SEP=0 composition, only elaborated without SEP: the lifecycle broadcast at
  // its SEP-absent value, every SEP-facing output at its tie-off value when the
  // primary domain comes up, and the two configuration presets differing in
  // nothing but the SEP parameter.
  if (!SepPresent) begin : g_nosep
    wire lc_state_sep0_is_f0_e = primary_rose_e && (lc_state_i === LcStateSep0);
    wire sep_outputs_tied_off = (sep_global_base_i === '0) && (sep_region_size_i === '0)
        && (lcc_demote_state_1_i === 2'b00) && (lcc_demote_state_2_i === 2'b00)
        && (sep_fuse_sense_done_i === 1'b0) && (lc_state_i === LcStateSep0);
    wire nosep_sep_outputs_tied_off_e = primary_rose_e && sep_outputs_tied_off;
    wire nosepcfg_fields_equal_defaultcfg_e =
        primary_rose_e && (smu_pkg::NoSepCfg == smu_pkg::DefaultCfg);
    `OCAH_FCOV_COVER(c_lc_state_sep0_is_f0, lc_state_sep0_is_f0_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_nosep_sep_outputs_tied_off, nosep_sep_outputs_tied_off_e, clk_smu_i,
                     in_reset)
    `OCAH_FCOV_COVER(c_nosepcfg_fields_equal_defaultcfg, nosepcfg_fields_equal_defaultcfg_e,
                     clk_smu_i, in_reset)
  end

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the lifecycle value presented at
  // release, against the demote pair.
  // ------------------------------------------------------------------
  covergroup cg_lc_at_release with function sample (
      logic [7:0] lc_state, logic [1:0] demote1, logic [1:0] demote2
  );
    option.per_instance = 1;
    cp_lc_state: coverpoint lc_state {bins sep0 = {LcStateSep0}; bins other = default;}
    cp_demote1: coverpoint demote1;
    cp_demote2: coverpoint demote2;
    x_demote: cross cp_demote1, cp_demote2;
  endgroup

  cg_lc_at_release u_cg_lc_at_release = new();

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset && primary_rose_e) begin
      u_cg_lc_at_release.sample(lc_state_i, lcc_demote_state_1_i, lcc_demote_state_2_i);
    end
  end
`endif

endmodule : smu_lc_fcov
