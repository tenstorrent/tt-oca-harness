// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Clean-room IEEE 1149.1 JTAG protocol-rule checker (practical subset).
//
// Rule provenance: every rule below is implemented from the public IEEE Std
// 1149.1 clause DESCRIPTIONS. No third-party protocol checker source was
// consulted or copied; all rule names are OCAH-original. Additions cite an
// IEEE Std 1149.1 clause, never another checker implementation.
//
// Shape: a module with explicit flat ports so it can be instantiated at TB
// scope next to flattened DUT nets or bound into a hierarchy. `en_i` is a
// runtime suppress knob (tie to 1'b1, or drive from a TB interface bit).
// Each concurrent rule belongs to the side that drives its signals: the
// master (the host) drives TMS and TDI, the slave (the TAP) drives TDO, its
// enable and the state. ASSUME_MASTER_RULES and ASSUME_SLAVE_RULES emit that
// side's concurrent rules as assumptions, so a formal backend that binds one
// instance asserts the design's side and assumes the environment's; both
// default to assertions, which is the simulation shape. Each such rule sits
// in a generate block named gen_<rule> (`OCAH_SVA_RULE, `OCAH_RULE). The
// event-driven TDO-timing checks stay assertions: no formal model elaborates
// them, and a simulator treats both kinds alike.
// `trst_n` is the controller's effective asynchronous reset: AND every
// source that resets the TAP (TRST, a power-on reset) so a DUT-side reset
// is not read as an illegal state transition.
// `tap_state_i` is an optional DUT-exported one-hot TAP-state observable
// (bit index == IEEE state number 0..15, Test-Logic-Reset = bit 0); set
// EN_STATE_RULES=0 and tie it off for pin-only instances (e.g. secondary
// TAP legs without a state observable).
//
// Rules (OCAH_JTAG_* assert, OCAH_JTAG_C_* cover):
//   X-hygiene : TMS/TDI resolved at each rising TCK edge (§4.3, §4.4 sample
//               them there); TDO resolved while its driver is active
//   TDO timing: TDO and its output enable change only in the TCK-low phase
//               (§4.5.1: TDO changes on the falling edge)
//   State     : one-hot/valid state encoding; every transition matches the
//               IEEE 1149.1 controller diagram (§6.1.1); TRST forces
//               Test-Logic-Reset (§6.1.1); five TMS-high cycles reach
//               Test-Logic-Reset from any state (§6.1.1.1); TDO driver
//               active only while shifting (§4.5.1)
//
// Two simulation trees. The TDO-timing and state rules use `OCAH_SVA_RULE /
// `OCAH_SVA_ASSERT_I (ocah_sva_macros.svh): live on every SIMULATION compile,
// evaluated by Verilator under --assert, and on every FORMAL elaboration of a
// licensed backend. The X-hygiene rules and the covers use `OCAH_RULE
// (ocah_sva_macros.svh) / `OCAH_COVER (ocah_assert.svh): live only where
// OCAH_INC_ASSERT is defined, i.e. on a four-state simulator or a licensed
// backend. The open-source
// formal frontend reads none of the concurrent operators here;
// ocah_jtag_fv.sv beside this file carries the boolean-subset rules for
// that path.

`include "ocah_assert.svh"
`include "ocah_sva_macros.svh"

module ocah_jtag_sva #(
  parameter bit EN_STATE_RULES      = 1'b1,
  parameter bit ASSUME_MASTER_RULES = 1'b0,
  parameter bit ASSUME_SLAVE_RULES  = 1'b0
) (
  input wire logic        tck,
  input wire logic        tms,
  input wire logic        tdi,
  input wire logic        trst_n,   // active-low asynchronous TAP reset
  input wire logic        tdo,
  input wire logic        tdo_oen,  // active-high TDO output enable
  input wire logic        en_i,
  input wire logic [15:0] tap_state_i  // one-hot; tie '0 when EN_STATE_RULES=0
);

  localparam logic [15:0] TlrOnehot = 16'h0001;
  localparam logic [15:0] ShiftDrOnehot = 16'h0010;
  localparam logic [15:0] Exit2DrOnehot = 16'h0080;
  localparam logic [15:0] ShiftIrOnehot = 16'h0800;
  localparam logic [15:0] Exit2IrOnehot = 16'h4000;

  // IEEE 1149.1 controller diagram (§6.1.1) over the one-hot encoding.
  function automatic logic [15:0] jtag_next_onehot(input logic [15:0] state, input logic tms_bit);
    case (state)
      16'h0001: return tms_bit ? 16'h0001 : 16'h0002;  // TLR
      16'h0002: return tms_bit ? 16'h0004 : 16'h0002;  // RTI
      16'h0004: return tms_bit ? 16'h0200 : 16'h0008;  // Select-DR
      16'h0008: return tms_bit ? 16'h0020 : 16'h0010;  // Capture-DR
      16'h0010: return tms_bit ? 16'h0020 : 16'h0010;  // Shift-DR
      16'h0020: return tms_bit ? 16'h0100 : 16'h0040;  // Exit1-DR
      16'h0040: return tms_bit ? 16'h0080 : 16'h0040;  // Pause-DR
      16'h0080: return tms_bit ? 16'h0100 : 16'h0010;  // Exit2-DR
      16'h0100: return tms_bit ? 16'h0004 : 16'h0002;  // Update-DR
      16'h0200: return tms_bit ? 16'h0001 : 16'h0400;  // Select-IR
      16'h0400: return tms_bit ? 16'h1000 : 16'h0800;  // Capture-IR
      16'h0800: return tms_bit ? 16'h1000 : 16'h0800;  // Shift-IR
      16'h1000: return tms_bit ? 16'h8000 : 16'h2000;  // Exit1-IR
      16'h2000: return tms_bit ? 16'h4000 : 16'h2000;  // Pause-IR
      16'h4000: return tms_bit ? 16'h8000 : 16'h0800;  // Exit2-IR
      16'h8000: return tms_bit ? 16'h0004 : 16'h0002;  // Update-IR
      default:  return '0;                             // illegal input
    endcase
  endfunction

  // ------------------------------------------------------------------
  // X-hygiene (four-state simulators only): the target samples TMS/TDI
  // on the rising TCK edge (§4.3.1, §4.4.1), so they must be resolved
  // there; TDO must be resolved whenever its driver is active (§4.5.1).
  // ------------------------------------------------------------------
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_JTAG_TMS_KNOWN, en_i |-> !$isunknown(tms), tck, !trst_n)
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_JTAG_TDI_KNOWN, en_i |-> !$isunknown(tdi), tck, !trst_n)
  `OCAH_RULE(ASSUME_SLAVE_RULES, OCAH_JTAG_TDO_KNOWN_WHEN_DRIVEN,
             (en_i && tdo_oen === 1'b1) |-> !$isunknown(tdo), tck, !trst_n)

  `OCAH_COVER(OCAH_JTAG_C_TRST_ASSERTED, en_i && (trst_n === 1'b0), tck, 1'b0)
  `OCAH_COVER(OCAH_JTAG_C_OEN_ACTIVE, en_i && (tdo_oen === 1'b1), tck, !trst_n)

`ifdef SIMULATION
  // ------------------------------------------------------------------
  // TDO timing (§4.5.1): TDO and its output enable change only on the
  // falling edge, i.e. never while TCK is high. Event-driven because the
  // violation is a change, not a sampled level.
  // ------------------------------------------------------------------
  always @(tdo) begin
    if (en_i === 1'b1 && trst_n === 1'b1 && !$isunknown(tdo))
      `OCAH_SVA_ASSERT_I(OCAH_JTAG_TDO_NEGEDGE_ONLY, (tck !== 1'b1))
  end
  always @(tdo_oen) begin
    if (en_i === 1'b1 && trst_n === 1'b1 && !$isunknown(tdo_oen))
      `OCAH_SVA_ASSERT_I(OCAH_JTAG_OEN_NEGEDGE_ONLY, (tck !== 1'b1))
  end
`endif  // SIMULATION

  generate
    if (EN_STATE_RULES) begin : gen_state_rules

      // --------------------------------------------------------------
      // State encoding and controller-diagram legality (§6.1.1).
      // --------------------------------------------------------------
      // A reset pulse that falls between two rising TCK edges is invisible
      // both to the sampled trst_n and to a clock-sampled disable iff, so
      // trst_seen_q latches it until the next rising edge; the transition
      // rule then expects Test-Logic-Reset instead of the diagram successor.
      logic trst_seen_q;
      always @(negedge trst_n or posedge tck) begin
        if (!trst_n) trst_seen_q <= 1'b1;
        else trst_seen_q <= 1'b0;
      end

      `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_JTAG_STATE_ONEHOT,
                     en_i |-> (!$isunknown(
                         tap_state_i
                     ) && ($countones(
                         tap_state_i
                     ) == 1) && (jtag_next_onehot(
                         tap_state_i, 1'b0
                     ) != '0)),
                     tck, !trst_n)
      `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_JTAG_STATE_NEXT_LEGAL,
                     en_i |=> (tap_state_i == (trst_seen_q ? TlrOnehot : jtag_next_onehot(
                         $past(tap_state_i), $past(tms)
                     ))),
                     tck, !trst_n)

      // TRST forces Test-Logic-Reset (§6.1.1). Not reset-disabled (the rule
      // checks reset itself); qualified on a resolved-low trst_n.
      `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_JTAG_TRST_TLR,
                     (en_i && (trst_n === 1'b0)) |-> (tap_state_i == TlrOnehot), tck, 1'b0)

      // Five TMS-high rising edges reach TLR from any state (§6.1.1.1).
      `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_JTAG_TLR_TMS5,
                     ((en_i && tms) [* 5]) |=> (tap_state_i == TlrOnehot), tck, !trst_n)

      // TDO driver active only while shifting (§4.5.1): the enable,
      // re-registered on the falling edge, tracks Shift-DR/Shift-IR
      // occupancy as sampled at the next rising edge.
      `OCAH_SVA_ASSERT(
          OCAH_JTAG_TDO_OEN_SHIFT_ONLY,
          en_i |-> (tdo_oen == ((tap_state_i == ShiftDrOnehot) || (tap_state_i == ShiftIrOnehot))),
          tck, !trst_n)

      `OCAH_COVER(OCAH_JTAG_C_SHIFT_DR, en_i && (tap_state_i == ShiftDrOnehot), tck, !trst_n)
      `OCAH_COVER(OCAH_JTAG_C_SHIFT_IR, en_i && (tap_state_i == ShiftIrOnehot), tck, !trst_n)
      `OCAH_COVER(OCAH_JTAG_C_DR_RESHIFT, en_i && (tap_state_i == ShiftDrOnehot) && ($past(
                  tap_state_i) == Exit2DrOnehot), tck, !trst_n)
      `OCAH_COVER(OCAH_JTAG_C_IR_RESHIFT, en_i && (tap_state_i == ShiftIrOnehot) && ($past(
                  tap_state_i) == Exit2IrOnehot), tck, !trst_n)
      `OCAH_COVER(OCAH_JTAG_C_TLR_VIA_TMS, en_i && (tap_state_i == TlrOnehot) && ($past(tap_state_i
                  ) != TlrOnehot), tck, !trst_n)

    end
  endgenerate

endmodule : ocah_jtag_sva
