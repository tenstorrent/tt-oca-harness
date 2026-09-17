// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Clean-room IEEE 1149.1 JTAG protocol rules for formal environments, written in the boolean
// subset that the open-source frontend and the licensed backends both elaborate
// (hw/common/dv/docs/formal-property-style.adoc).
//
// Rule provenance: every rule below is implemented from the public IEEE Std 1149.1 clause
// DESCRIPTIONS. No third-party protocol checker source was consulted or copied; all rule names
// are OCAH-original. Additions cite an IEEE Std 1149.1 clause, never another checker
// implementation.
//
// Shape: the port list of ocah_jtag_sva without its runtime enable, bound into a design by module
// name. `trst_n` is the controller's effective asynchronous reset: AND every source that resets
// the TAP (TRST, a power-on reset) so a DUT-side reset is not read as an illegal state transition.
// `tap_state_i` is the DUT's one-hot TAP-state observable (bit index == IEEE state number 0..15,
// Test-Logic-Reset = bit 0); set EN_STATE_RULES=0 and tie it off for a pin-only instance.
// Each rule belongs to the side that drives its signals: the master (the host) drives TMS and
// TDI; the slave (the TAP) drives TDO, its enable and the state. ASSUME_MASTER_RULES and
// ASSUME_SLAVE_RULES emit that side's rules as assumptions, so one instance asserts the design's
// side and assumes the environment's; both default to assertions.
//
// Rules (gen_<rule>.ast_<rule>, or asm_<rule> on an assumed side; cov_* covers):
//   Master : jtag_tms_tdi_stable_while_tck_high. The target samples TMS and TDI on the rising
//            edge (§4.3.1, §4.4.1); a host that changes them only while TCK is low presents one
//            value per edge.
//   Slave  : jtag_tdo_stable_while_tck_high (§4.5.1: the enable, and TDO while the enable is
//            active, change on the falling edge); jtag_state_onehot, jtag_state_next_legal
//            (§6.1.1 controller diagram);
//            jtag_trst_tlr (§6.1.1: TRST forces Test-Logic-Reset); jtag_tlr_tms5 (§6.1.1.1:
//            five TMS-high edges reach Test-Logic-Reset); jtag_tdo_oen_shift_only (§4.5.1:
//            the driver is active only while shifting)
//   Covers : jtag_shift_dr, jtag_shift_ir, jtag_tlr_from_five_tms_high, jtag_tdo_driven
//
// The two phase rules hold at every step of the tck-high phase, so the model carries both edges
// of tck (`multiclock on` in a SymbiYosys task file). The rules guard every $past with the reset
// seen since the previous edge, and the initial-reset assumption of the macro layer pins trst_n
// low at the first tck edge; the reset model of the environment releases it.

`include "ocah_fv_macros.svh"

module ocah_jtag_fv #(
  parameter bit EN_STATE_RULES      = 1'b1,
  parameter bit ASSUME_MASTER_RULES = 1'b0,
  parameter bit ASSUME_SLAVE_RULES  = 1'b0
) (
  input logic        tck,
  input logic        tms,
  input logic        tdi,
  input logic        trst_n,       // active-low asynchronous TAP reset
  input logic        tdo,
  input logic        tdo_oen,      // active-high TDO output enable
  input logic [15:0] tap_state_i   // one-hot; tie '0 when EN_STATE_RULES=0
);

  localparam logic [15:0] TlrOnehot = 16'h0001;
  localparam logic [15:0] ShiftDrOnehot = 16'h0010;
  localparam logic [15:0] ShiftIrOnehot = 16'h0800;
  localparam logic [2:0] TmsHighToTlr = 3'd5;

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

  // A reset that falls between two rising edges is invisible to the sampled trst_n and to a
  // clock-sampled disable iff, so trst_seen_q latches it until the next rising edge: the
  // transition rule then expects Test-Logic-Reset, and the phase rules skip that cycle.
  logic trst_seen_q;
  always_ff @(posedge tck or negedge trst_n) begin
    if (!trst_n) trst_seen_q <= 1'b1;
    else trst_seen_q <= 1'b0;
  end

  // Pin values at the rising edge, compared at every step while tck stays high; the trace's
  // first high phase has no rising edge before it.
  logic posedge_seen_q = 1'b0;
  logic tms_at_posedge_q, tdi_at_posedge_q, tdo_at_posedge_q, tdo_oen_at_posedge_q;
  always_ff @(posedge tck) begin
    posedge_seen_q       <= 1'b1;
    tms_at_posedge_q     <= tms;
    tdi_at_posedge_q     <= tdi;
    tdo_at_posedge_q     <= tdo;
    tdo_oen_at_posedge_q <= tdo_oen;
  end

  logic phase_checkable;
  assign phase_checkable = tck && posedge_seen_q && trst_n && !trst_seen_q;

  // Consecutive rising edges with TMS high, saturating at five.
  logic [2:0] tms_high_cnt_q;
  always_ff @(posedge tck or negedge trst_n) begin
    if (!trst_n) tms_high_cnt_q <= '0;
    else if (!tms) tms_high_cnt_q <= '0;
    else if (tms_high_cnt_q != TmsHighToTlr) tms_high_cnt_q <= tms_high_cnt_q + 3'd1;
  end

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(tck, trst_n)

  // ---- Master: TMS and TDI hold through the TCK-high phase (§4.3.1, §4.4.1) -------------------
  if (ASSUME_MASTER_RULES) begin : gen_jtag_tms_tdi_stable_while_tck_high
    always_comb begin
      if (phase_checkable) begin
        `OCAH_FV_ASSUME_I(asm_jtag_tms_tdi_stable_while_tck_high,
                          tms == tms_at_posedge_q && tdi == tdi_at_posedge_q)
      end
    end
  end else begin : gen_jtag_tms_tdi_stable_while_tck_high
    always_comb begin
      if (phase_checkable) begin
        `OCAH_FV_ASSERT_I(ast_jtag_tms_tdi_stable_while_tck_high,
                          tms == tms_at_posedge_q && tdi == tdi_at_posedge_q)
      end
    end
  end

  // ---- Slave: the enable, and TDO while it is driven, change on the falling edge alone (§4.5.1)
  if (ASSUME_SLAVE_RULES) begin : gen_jtag_tdo_stable_while_tck_high
    always_comb begin
      if (phase_checkable) begin
        `OCAH_FV_ASSUME_I(asm_jtag_tdo_stable_while_tck_high,
                          tdo_oen == tdo_oen_at_posedge_q &&
                          (!tdo_oen_at_posedge_q || tdo == tdo_at_posedge_q))
      end
    end
  end else begin : gen_jtag_tdo_stable_while_tck_high
    always_comb begin
      if (phase_checkable) begin
        `OCAH_FV_ASSERT_I(ast_jtag_tdo_stable_while_tck_high,
                          tdo_oen == tdo_oen_at_posedge_q &&
                          (!tdo_oen_at_posedge_q || tdo == tdo_at_posedge_q))
      end
    end
  end

  `OCAH_FV_COVER(cov_jtag_tdo_driven, tdo_oen, tck, trst_n)

  if (EN_STATE_RULES) begin : gen_state_rules
    // ---- Slave: state encoding and controller-diagram legality (§6.1.1) ----------------------
    `OCAH_FV_RULE(ASSUME_SLAVE_RULES, jtag_state_onehot,
                  $countones(tap_state_i) == 1 && jtag_next_onehot(tap_state_i, 1'b0) != '0,
                  tck, trst_n)
    `OCAH_FV_RULE(ASSUME_SLAVE_RULES, jtag_state_next_legal,
                  tap_state_i == (trst_seen_q ? TlrOnehot
                                              : jtag_next_onehot($past(tap_state_i), $past(tms))),
                  tck, trst_n)
    // TRST forces Test-Logic-Reset (§6.1.1); the rule checks reset itself, so it is not
    // reset-disabled.
    `OCAH_FV_RULE(ASSUME_SLAVE_RULES, jtag_trst_tlr,
                  `OCAH_FV_IMPLIES(!trst_n, tap_state_i == TlrOnehot), tck, 1'b1)
    // Five TMS-high rising edges reach Test-Logic-Reset from any state (§6.1.1.1).
    `OCAH_FV_RULE(ASSUME_SLAVE_RULES, jtag_tlr_tms5,
                  `OCAH_FV_IMPLIES(tms_high_cnt_q == TmsHighToTlr, tap_state_i == TlrOnehot),
                  tck, trst_n)
    // The driver is active only while shifting (§4.5.1); sampled at the rising edge, the enable
    // follows the state sampled at the same edge.
    `OCAH_FV_RULE(ASSUME_SLAVE_RULES, jtag_tdo_oen_shift_only,
                  tdo_oen == (tap_state_i == ShiftDrOnehot || tap_state_i == ShiftIrOnehot),
                  tck, trst_n)

    `OCAH_FV_COVER(cov_jtag_shift_dr, tap_state_i == ShiftDrOnehot, tck, trst_n)
    `OCAH_FV_COVER(cov_jtag_shift_ir, tap_state_i == ShiftIrOnehot, tck, trst_n)
    `OCAH_FV_COVER(cov_jtag_tlr_from_five_tms_high,
                   tms_high_cnt_q == TmsHighToTlr && $past(tap_state_i) != TlrOnehot,
                   tck, trst_n)
  end
  // verilog_format: on

endmodule : ocah_jtag_fv
