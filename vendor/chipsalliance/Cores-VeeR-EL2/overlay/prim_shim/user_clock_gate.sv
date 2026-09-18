// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OCAH technology clock gate for VeeR EL2, routed to the OCH prim so there is one
// ICG in the design and it inherits the och_prim_generic `not(synth)` tech swap.
//
// common_defines.vh already names this module via `USER_EC_RV_ICG; the
// TECH_SPECIFIC_EC_RV_ICG define set in this package's Bender.yml is what makes
// beh_lib.sv skip its own behavioural `TEC_RV_ICG gate and instantiate this
// instead. Replaces upstream/testbench/user_cells.sv, whose example cell used an
// initial block and was simulation-only.
//
// Port set must match what rvclkhdr/rvoclkhdr expect: they bind EN/CK/Q by name
// and pick up SE through `.*`, so scan enable reaches the ICG test-enable pin -
// which upstream's example cell, lacking an SE port, silently dropped.
module user_clock_gate (
  input  logic SE,
  input  logic EN,
  input  logic CK,
  output logic Q
);

  prim_clkgater u_clkgater (
    .clk_i(CK),
    .en_i (EN),
    .te_i (SE),
    .clk_o(Q)
  );

endmodule
