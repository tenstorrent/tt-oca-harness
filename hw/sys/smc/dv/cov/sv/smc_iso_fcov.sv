// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC isolation, FLR and reset-source functional coverage: which of the three
// ISOLATE_REQ terms raised a subsystem's isolation, that one FLR trigger
// starts one sequence, and which timeout source drove the warm reset.
//
// The isolation points compare the composed isolate_req_o against the term
// that should have produced it, so a bit that is simply stuck high cannot
// satisfy them.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal or a smc_wrapper boundary port.
//
// DISABLE CONVENTION: powergood, not reset -- the cool/warm reset points
// observe reset assertion itself, which a reset-gated point cannot see.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_iso_fcov (
  input wire clk_smc_i,
  input wire clk_ref_i,
  input wire powergood_i,

  // Isolation request composition.
  input wire [31:0] isolate_req_i,
  input wire [31:0] isolate_req_reg_i,
  input wire [31:0] isolate_req_smcen_reg_i,
  input wire isolate_req_smc_reg_i,

  // FLR edge detect and its pre-reset delay state machine.
  input wire cfg_flr_pf_active_i,
  input wire flr_sync_ref_i,
  input wire flr_posedge_ref_i,
  input wire [1:0] flr_counter_state_i,

  // Reset sources and the resets they drive.
  input wire rst_cool_ni,
  input wire rst_primary_smc_clk_ni,
  input wire rst_warm_smc_clk_ni,
  input wire sep_wdt_reset_ni,
  input wire wdt_first_timeout_i,
  input wire wdt_second_timeout_i
);

  wire not_powered = (powergood_i !== 1'b1);

  localparam logic [1:0] FlrIdle = 2'b00;

  // ------------------------------------------------------------------
  // Software isolation. The point is a bit that ISOLATE_REQ_REG raised and
  // isolate_req_o carries, with at least one other subsystem left alone --
  // that selectivity is what "per subsystem" means.
  // ------------------------------------------------------------------
  wire sw_bits_valid = (^isolate_req_reg_i !== 1'bx) && (^isolate_req_i !== 1'bx);
  wire sw_isolate_per_subsystem_e = sw_bits_valid && (isolate_req_reg_i !== 32'd0)
      && ((isolate_req_i & isolate_req_reg_i) === isolate_req_reg_i)
      && (isolate_req_i !== 32'hFFFF_FFFF);
  `OCAH_FCOV_COVER(c_sw_isolate_per_subsystem, sw_isolate_per_subsystem_e, clk_smc_i, not_powered)

  // ------------------------------------------------------------------
  // FLR-sourced isolation. The sticky FLR flag gates the SMCEN mask, so an
  // enabled bit must appear in isolate_req_o and a disabled one must not.
  // ------------------------------------------------------------------
  wire flr_sticky = (isolate_req_smc_reg_i === 1'b1);
  wire [31:0] flr_enabled_bits = isolate_req_smcen_reg_i;
  wire [31:0] flr_disabled_bits = ~isolate_req_smcen_reg_i & ~isolate_req_reg_i;
  wire flr_iso_enabled_e = flr_sticky && (flr_enabled_bits !== 32'd0)
      && ((isolate_req_i & flr_enabled_bits) === flr_enabled_bits);
  wire flr_iso_disabled_e = flr_sticky && (flr_disabled_bits !== 32'd0)
      && ((isolate_req_i & flr_disabled_bits) === 32'd0);
  `OCAH_FCOV_COVER(c_flr_isolate_enabled, flr_iso_enabled_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_flr_isolate_disabled, flr_iso_disabled_e, clk_smc_i, not_powered)

  // ------------------------------------------------------------------
  // One sequence per rising edge. The start point is the edge pulse taken
  // in the idle state; the hold point is the trigger still asserted with no
  // further pulse, which is the half that shows a level cannot re-trigger.
  // ------------------------------------------------------------------
  logic flr_started_q;
  always_ff @(posedge clk_ref_i) begin
    if (not_powered) flr_started_q <= 1'b0;
    else if (flr_posedge_ref_i === 1'b1) flr_started_q <= 1'b1;
    else if (flr_sync_ref_i === 1'b0) flr_started_q <= 1'b0;
  end

  wire single_sequence_e = (flr_posedge_ref_i === 1'b1) && (flr_counter_state_i === FlrIdle);
  wire no_sequence_on_hold_e = flr_started_q && (flr_sync_ref_i === 1'b1)
      && (flr_posedge_ref_i === 1'b0);
  `OCAH_FCOV_COVER(c_single_sequence_per_rising_edge, single_sequence_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_no_sequence_on_level_hold, no_sequence_on_hold_e, clk_ref_i, not_powered)

  // ------------------------------------------------------------------
  // Warm reset by source. Each point is the warm reset asserted with one
  // timeout source up and the other down, so the two sources stay separable.
  // ------------------------------------------------------------------
  wire warm_asserted = (rst_warm_smc_clk_ni === 1'b0);
  wire internal_wdt = (wdt_first_timeout_i === 1'b1) || (wdt_second_timeout_i === 1'b1);
  wire external_wdt = (sep_wdt_reset_ni === 1'b0);
  wire warm_from_internal_e = warm_asserted && internal_wdt && !external_wdt;
  wire warm_from_external_e = warm_asserted && external_wdt && !internal_wdt;
  `OCAH_FCOV_COVER(c_warm_from_internal_wdt, warm_from_internal_e, clk_smc_i, not_powered)
  `OCAH_FCOV_COVER(c_warm_from_external_wdt, warm_from_external_e, clk_smc_i, not_powered)

  // ------------------------------------------------------------------
  // Pin-initiated cool reset. The FLR path drives the same cool reset, so
  // the point requires the FLR trigger to be down: what is left is the pin.
  // ------------------------------------------------------------------
  wire cool_from_pin_e = (rst_cool_ni === 1'b0) && (cfg_flr_pf_active_i === 1'b0)
      && (rst_primary_smc_clk_ni === 1'b0);
  `OCAH_FCOV_COVER(c_cool_reset_from_gpio_pin_61, cool_from_pin_e, clk_smc_i, not_powered)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: which isolation terms were live at
  // once, which the flat point list cannot cross.
  // ------------------------------------------------------------------
  covergroup cg_isolate_terms with function sample (
      logic sw_term, logic flr_term, logic any_isolated
  );
    option.per_instance = 1;
    cp_sw: coverpoint sw_term {bins clear = {1'b0}; bins set = {1'b1};}
    cp_flr: coverpoint flr_term {bins clear = {1'b0}; bins set = {1'b1};}
    cp_any: coverpoint any_isolated {bins none = {1'b0}; bins some = {1'b1};}
    // Each subsystem's isolation is the OR of the software, pin and FLR terms
    // (clk_rst.adoc, Isolation Control Architecture), so a software request
    // with nothing isolated is not a state the composition can hold.
    x_terms: cross cp_sw, cp_flr, cp_any{
      ignore_bins sw_without_isolation = binsof (cp_sw.set) && binsof (cp_any.none);
    }
  endgroup

  cg_isolate_terms u_cg_isolate_terms = new();

  always_ff @(posedge clk_smc_i) begin
    if (!not_powered) begin
      u_cg_isolate_terms.sample(isolate_req_reg_i != 32'd0, isolate_req_smc_reg_i,
                                isolate_req_i != 32'd0);
    end
  end
`endif

endmodule : smc_iso_fcov
