// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP functional-coverage module (the DTP_FCOV.adoc collection point).
//
// One passive, signal-driven module shared by both DTP flows: the cocotb and
// SV-UVM shapes of dtp_uvm_top instantiate it identically outside the UVM
// harness region, so the same coverage source serves Verilator and the
// commercial simulators.
//
// Two collection layers per DTP_FCOV.adoc:
//   * Labeled `OCAH_FCOV_COVER cover-property points — live in every flow;
//     under Verilator they form the public-CI functional-coverage database
//     (coverage.dat user points via --coverage-user).
//   * SV covergroups under `ifndef VERILATOR — commercial-simulator closure
//     (Verilator cannot compile covergroups; the public build defines
//     VERILATOR explicitly).
//
// JTAG-core coverage lives here; JTAG2AXI/OTP, debug TDR, scan/STAP, and
// cross-trigger coverage live in the sibling dtp_*_fcov.sv modules. The
// shared event decode and the per-boundary liveness points come first.

`include "ocah_fcov_macros.svh"

module dtp_fcov (
  input wire        tck_i,
  input wire        tms_i,
  input wire        tdi_i,
  input wire        tdo_i,
  input wire        trst_ni,
  input wire [15:0] tap_state_i,     // one-hot jtag_tap_pkg::tap_state_e
  input wire [63:0] inst_decoded_i,  // one-hot decoded IR
  input wire sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_i
);

  // ------------------------------------------------------------------
  // Shared event decode. The documented sampling boundaries (completed
  // IR scan, completed DR scan) map onto the UPDATE_* one-hot TAP states;
  // per-area transaction events are wired in by each section.
  //
  // Timing: the TAP state and the decoded IR are registered on TCK, so at
  // a posedge sample tap_state_q/tms_q describe the transition taken INTO
  // tap_state_i, and *_committed means the UPDATE_* state was left on this
  // edge with inst_decoded_i already showing the committed instruction.
  // ------------------------------------------------------------------
  wire in_reset  = (trst_ni !== 1'b1);
  wire update_ir = (tap_state_i == jtag_tap_pkg::UPDATE_IR);
  wire update_dr = (tap_state_i == jtag_tap_pkg::UPDATE_DR);

  // No declaration initializers: VCS rejects them on always_ff-driven
  // variables (initializer_driver_checks). Before the first TCK edge the
  // history reads 0 (Verilator, 2-state) or X (VCS), so every cover
  // condition must require a defined non-zero history pattern.
  logic [15:0] tap_state_q;
  logic        tms_q;
  logic        ir_loaded_since_tlr;

  always_ff @(posedge tck_i) begin
    tap_state_q <= tap_state_i;
    tms_q       <= tms_i;
    if (tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET || in_reset) begin
      ir_loaded_since_tlr <= 1'b0;
    end else if (tap_state_i == jtag_tap_pkg::UPDATE_IR) begin
      ir_loaded_since_tlr <= 1'b1;
    end
  end

  // CONVENTION: every cover-property body below is a single continuous-assign
  // wire. Verilator 5.050's localization pass hits an internal error
  // (V3Localize) on compound expressions or flop references inside
  // cover-property bodies; hoisting each condition into a named wire is the
  // portable shape. Follow it for every added point.
  wire [15:0] tap_state_prev = tap_state_q;
  wire        tms_prev = tms_q;
  wire        ir_seen_since_tlr = ir_loaded_since_tlr;

  wire ir_committed = (tap_state_prev == jtag_tap_pkg::UPDATE_IR) && !in_reset;
  wire dr_committed = (tap_state_prev == jtag_tap_pkg::UPDATE_DR) && !in_reset;
  // First rising edge inside SHIFT_DR: the first captured bit is on TDO.
  wire first_dr_bit =
      (tap_state_prev == jtag_tap_pkg::CAPTURE_DR)
      && (tap_state_i == jtag_tap_pkg::SHIFT_DR);

  // ------------------------------------------------------------------
  // Instruction categories (jtag_instruction_cg.category): one mask per
  // category over the 64-bit one-hot decode; every opcode belongs to
  // exactly one category (checked at time zero below).
  // ------------------------------------------------------------------
  // 0x00 BYPASS_ALT, 0x01 IDCODE, 0x03 SAMPLE_PRELOAD, 0x04 EXTEST, 0x3F BYPASS
  localparam logic [63:0] CatMandatory = 64'h8000_0000_0000_001B;
  // 0x02 RUNBIST, 0x05-0x09 EXTEST_TRAIN/PULSE, CLAMP, HIGHZ, INTEST,
  // 0x3D ZERO_LENGTH_BYPASS, 0x3E INV_BYPASS
  localparam logic [63:0] CatOptional = 64'h6000_0000_0000_03E4;
  // 0x0A CLAMP_HOLD, 0x0B CLAMP_RELEASE, 0x0E TAP_3DCR
  localparam logic [63:0] CatIeee1838 = 64'h0000_0000_0000_4C00;
  // 0x0C TMP_STATUS, 0x0D IC_RESET, 0x18 DEBUG_CONTROL, 0x19 JTAG_CAPS
  localparam logic [63:0] CatDebug = 64'h0000_0000_0300_3000;
  // 0x1A SELECT_IJTAG
  localparam logic [63:0] CatIjtag = 64'h0000_0000_0400_0000;
  // 0x1B-0x2C JTAG2AXI caps/single-op/series TDRs (SMC OTP, SEP OTP, SMC fabric)
  localparam logic [63:0] CatJtag2axi = 64'h0000_1FFF_F800_0000;
  // 0x10-0x17 RISCV_RESERVED
  localparam logic [63:0] CatReserved = 64'h0000_0000_00FF_0000;
  // 0x0F, 0x2D-0x3C UNDEFINED_BYPASS
  localparam logic [63:0] CatUndefined = 64'h1FFF_E000_0000_8000;

  localparam logic [63:0] CatAll = CatMandatory | CatOptional | CatIeee1838 | CatDebug
      | CatIjtag | CatJtag2axi | CatReserved | CatUndefined;
  localparam logic [63:0] CatOverlap = (CatMandatory & CatOptional)
      | ((CatMandatory | CatOptional) & CatIeee1838)
      | ((CatMandatory | CatOptional | CatIeee1838) & CatDebug)
      | ((CatMandatory | CatOptional | CatIeee1838 | CatDebug) & CatIjtag)
      | ((CatMandatory | CatOptional | CatIeee1838 | CatDebug | CatIjtag) & CatJtag2axi)
      | ((CatMandatory | CatOptional | CatIeee1838 | CatDebug | CatIjtag | CatJtag2axi)
         & CatReserved)
      | ((CatMandatory | CatOptional | CatIeee1838 | CatDebug | CatIjtag | CatJtag2axi
          | CatReserved) & CatUndefined);

  initial begin
    if (CatAll != {64{1'b1}} || CatOverlap != '0) begin
      $fatal(1, "dtp_fcov: instruction category masks must partition all 64 opcodes");
    end
  end

  // Gated JTAG2AXI data-path TDR opcodes per bridge (caps TDRs stay readable).
  localparam logic [63:0] SmcJtag2axiOps = 64'h0000_1F00_0000_0000;  // 0x28-0x2C
  localparam logic [63:0] SmcOtpJtag2axiOps = 64'h0000_0001_F000_0000;  // 0x1C-0x20
  localparam logic [63:0] SepOtpJtag2axiOps = 64'h0000_007C_0000_0000;  // 0x22-0x26
  localparam logic [63:0] SelectIjtag = 64'h0000_0000_0400_0000;  // 0x1A

  wire disabled_instruction_committed = ir_committed && (
      (|(inst_decoded_i & SmcJtag2axiOps) && dbg_disable_i.smc_jtag2axi)
   || (|(inst_decoded_i & SmcOtpJtag2axiOps) && dbg_disable_i.smc_otp_jtag2axi)
   || (|(inst_decoded_i & SepOtpJtag2axiOps) && dbg_disable_i.sep_otp_jtag2axi)
   || (|(inst_decoded_i & SelectIjtag) && dbg_disable_i.dft_secure
       && dbg_disable_i.dft_nonsecure && dbg_disable_i.dfd));

  // ------------------------------------------------------------------
  // Scan-boundary liveness points.
  // ------------------------------------------------------------------
  `OCAH_FCOV_COVER(c_completed_ir_scan, update_ir, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_completed_dr_scan, update_dr, tck_i, in_reset)

  // ------------------------------------------------------------------
  // tap_state_cg: all 16 IEEE 1149.1 states, all 32 legal (state, tms)
  // arcs, and the two reset-reachability bins.
  // ------------------------------------------------------------------
  `define DTP_FCOV_STATE(__label, __state)                                    \
    wire __label``_e = (tap_state_i == jtag_tap_pkg::__state);           \
    `OCAH_FCOV_COVER(__label, __label``_e, tck_i, in_reset)

  `DTP_FCOV_STATE(c_state_test_logic_reset, TEST_LOGIC_RESET)
  `DTP_FCOV_STATE(c_state_run_test_idle, RUN_TEST_IDLE)
  `DTP_FCOV_STATE(c_state_select_dr_scan, SELECT_DR_SCAN)
  `DTP_FCOV_STATE(c_state_capture_dr, CAPTURE_DR)
  `DTP_FCOV_STATE(c_state_shift_dr, SHIFT_DR)
  `DTP_FCOV_STATE(c_state_exit1_dr, EXIT1_DR)
  `DTP_FCOV_STATE(c_state_pause_dr, PAUSE_DR)
  `DTP_FCOV_STATE(c_state_exit2_dr, EXIT2_DR)
  `DTP_FCOV_STATE(c_state_update_dr, UPDATE_DR)
  `DTP_FCOV_STATE(c_state_select_ir_scan, SELECT_IR_SCAN)
  `DTP_FCOV_STATE(c_state_capture_ir, CAPTURE_IR)
  `DTP_FCOV_STATE(c_state_shift_ir, SHIFT_IR)
  `DTP_FCOV_STATE(c_state_exit1_ir, EXIT1_IR)
  `DTP_FCOV_STATE(c_state_pause_ir, PAUSE_IR)
  `DTP_FCOV_STATE(c_state_exit2_ir, EXIT2_IR)
  `DTP_FCOV_STATE(c_state_update_ir, UPDATE_IR)
  `undef DTP_FCOV_STATE

  `define DTP_FCOV_ARC(__label, __from, __tms, __to)                                  \
    wire __label``_e = (tap_state_prev == jtag_tap_pkg::__from)                  \
        && (tms_prev == (__tms)) && (tap_state_i == jtag_tap_pkg::__to);               \
    `OCAH_FCOV_COVER(__label, __label``_e, tck_i, in_reset)

  `DTP_FCOV_ARC(c_arc_tlr_tms0_rti, TEST_LOGIC_RESET, 1'b0, RUN_TEST_IDLE)
  `DTP_FCOV_ARC(c_arc_tlr_tms1_tlr, TEST_LOGIC_RESET, 1'b1, TEST_LOGIC_RESET)
  `DTP_FCOV_ARC(c_arc_rti_tms0_rti, RUN_TEST_IDLE, 1'b0, RUN_TEST_IDLE)
  `DTP_FCOV_ARC(c_arc_rti_tms1_seldr, RUN_TEST_IDLE, 1'b1, SELECT_DR_SCAN)
  `DTP_FCOV_ARC(c_arc_seldr_tms0_capdr, SELECT_DR_SCAN, 1'b0, CAPTURE_DR)
  `DTP_FCOV_ARC(c_arc_seldr_tms1_selir, SELECT_DR_SCAN, 1'b1, SELECT_IR_SCAN)
  `DTP_FCOV_ARC(c_arc_capdr_tms0_shdr, CAPTURE_DR, 1'b0, SHIFT_DR)
  `DTP_FCOV_ARC(c_arc_capdr_tms1_ex1dr, CAPTURE_DR, 1'b1, EXIT1_DR)
  `DTP_FCOV_ARC(c_arc_shdr_tms0_shdr, SHIFT_DR, 1'b0, SHIFT_DR)
  `DTP_FCOV_ARC(c_arc_shdr_tms1_ex1dr, SHIFT_DR, 1'b1, EXIT1_DR)
  `DTP_FCOV_ARC(c_arc_ex1dr_tms0_pdr, EXIT1_DR, 1'b0, PAUSE_DR)
  `DTP_FCOV_ARC(c_arc_ex1dr_tms1_updr, EXIT1_DR, 1'b1, UPDATE_DR)
  `DTP_FCOV_ARC(c_arc_pdr_tms0_pdr, PAUSE_DR, 1'b0, PAUSE_DR)
  `DTP_FCOV_ARC(c_arc_pdr_tms1_ex2dr, PAUSE_DR, 1'b1, EXIT2_DR)
  `DTP_FCOV_ARC(c_arc_ex2dr_tms0_shdr, EXIT2_DR, 1'b0, SHIFT_DR)
  `DTP_FCOV_ARC(c_arc_ex2dr_tms1_updr, EXIT2_DR, 1'b1, UPDATE_DR)
  `DTP_FCOV_ARC(c_arc_updr_tms0_rti, UPDATE_DR, 1'b0, RUN_TEST_IDLE)
  `DTP_FCOV_ARC(c_arc_updr_tms1_seldr, UPDATE_DR, 1'b1, SELECT_DR_SCAN)
  `DTP_FCOV_ARC(c_arc_selir_tms0_capir, SELECT_IR_SCAN, 1'b0, CAPTURE_IR)
  `DTP_FCOV_ARC(c_arc_selir_tms1_tlr, SELECT_IR_SCAN, 1'b1, TEST_LOGIC_RESET)
  `DTP_FCOV_ARC(c_arc_capir_tms0_shir, CAPTURE_IR, 1'b0, SHIFT_IR)
  `DTP_FCOV_ARC(c_arc_capir_tms1_ex1ir, CAPTURE_IR, 1'b1, EXIT1_IR)
  `DTP_FCOV_ARC(c_arc_shir_tms0_shir, SHIFT_IR, 1'b0, SHIFT_IR)
  `DTP_FCOV_ARC(c_arc_shir_tms1_ex1ir, SHIFT_IR, 1'b1, EXIT1_IR)
  `DTP_FCOV_ARC(c_arc_ex1ir_tms0_pir, EXIT1_IR, 1'b0, PAUSE_IR)
  `DTP_FCOV_ARC(c_arc_ex1ir_tms1_upir, EXIT1_IR, 1'b1, UPDATE_IR)
  `DTP_FCOV_ARC(c_arc_pir_tms0_pir, PAUSE_IR, 1'b0, PAUSE_IR)
  `DTP_FCOV_ARC(c_arc_pir_tms1_ex2ir, PAUSE_IR, 1'b1, EXIT2_IR)
  `DTP_FCOV_ARC(c_arc_ex2ir_tms0_shir, EXIT2_IR, 1'b0, SHIFT_IR)
  `DTP_FCOV_ARC(c_arc_ex2ir_tms1_upir, EXIT2_IR, 1'b1, UPDATE_IR)
  `DTP_FCOV_ARC(c_arc_upir_tms0_rti, UPDATE_IR, 1'b0, RUN_TEST_IDLE)
  `DTP_FCOV_ARC(c_arc_upir_tms1_seldr, UPDATE_IR, 1'b1, SELECT_DR_SCAN)
  `undef DTP_FCOV_ARC

  // Reset reachability. TRST covers must stay armed while reset is asserted,
  // so they carry no reset disable.
  wire trst_from_active_e = !trst_ni && (tap_state_prev != '0)
      && (tap_state_prev != jtag_tap_pkg::TEST_LOGIC_RESET);
  wire tms_to_tlr_e = (tap_state_prev == jtag_tap_pkg::SELECT_IR_SCAN)
      && tms_prev && (tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET);
  `OCAH_FCOV_COVER(c_reset_trst_from_active, trst_from_active_e, tck_i, 1'b0)
  `OCAH_FCOV_COVER(c_reset_tms5_from_active, tms_to_tlr_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // tap_smoke_cg: TAP reset source and IDCODE access.
  // ------------------------------------------------------------------
  wire trst_low_e = !trst_ni;
  wire idcode_active = (inst_decoded_i == 64'h2);
  wire idcode_default_e = dr_committed && idcode_active && !ir_seen_since_tlr;
  wire idcode_explicit_e = dr_committed && idcode_active && ir_seen_since_tlr;
  // First captured IDCODE bit on TDO is the IEEE 1149.1 marker (must be 1);
  // an invalid marker is a checker failure, never a coverage bin.
  wire idcode_marker_e = first_dr_bit && idcode_active && tdo_i;
  `OCAH_FCOV_COVER(c_smoke_reset_source_trst, trst_low_e, tck_i, 1'b0)
  `OCAH_FCOV_COVER(c_smoke_reset_source_tms_to_tlr, tms_to_tlr_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smoke_idcode_default_after_reset, idcode_default_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smoke_idcode_explicit_instruction, idcode_explicit_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smoke_idcode_marker_1, idcode_marker_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // jtag_instruction_cg: all 64 opcodes at completed IR scans, the eight
  // instruction categories, and the disabled-behavior bins.
  // ------------------------------------------------------------------
  // One labeled point per opcode: a generate loop would collapse into a
  // single aggregated coverage point (Verilator merges generate-array
  // scopes unless per-instance coverage is enabled globally).
  `define DTP_FCOV_OPCODE(__label, __op)                                             \
    wire __label``_e = ir_committed && (inst_decoded_i == (64'h1 << (__op)));  \
    `OCAH_FCOV_COVER(__label, __label``_e, tck_i, in_reset)

  `DTP_FCOV_OPCODE(c_ir_opcode_00, 0)
  `DTP_FCOV_OPCODE(c_ir_opcode_01, 1)
  `DTP_FCOV_OPCODE(c_ir_opcode_02, 2)
  `DTP_FCOV_OPCODE(c_ir_opcode_03, 3)
  `DTP_FCOV_OPCODE(c_ir_opcode_04, 4)
  `DTP_FCOV_OPCODE(c_ir_opcode_05, 5)
  `DTP_FCOV_OPCODE(c_ir_opcode_06, 6)
  `DTP_FCOV_OPCODE(c_ir_opcode_07, 7)
  `DTP_FCOV_OPCODE(c_ir_opcode_08, 8)
  `DTP_FCOV_OPCODE(c_ir_opcode_09, 9)
  `DTP_FCOV_OPCODE(c_ir_opcode_0a, 10)
  `DTP_FCOV_OPCODE(c_ir_opcode_0b, 11)
  `DTP_FCOV_OPCODE(c_ir_opcode_0c, 12)
  `DTP_FCOV_OPCODE(c_ir_opcode_0d, 13)
  `DTP_FCOV_OPCODE(c_ir_opcode_0e, 14)
  `DTP_FCOV_OPCODE(c_ir_opcode_0f, 15)
  `DTP_FCOV_OPCODE(c_ir_opcode_10, 16)
  `DTP_FCOV_OPCODE(c_ir_opcode_11, 17)
  `DTP_FCOV_OPCODE(c_ir_opcode_12, 18)
  `DTP_FCOV_OPCODE(c_ir_opcode_13, 19)
  `DTP_FCOV_OPCODE(c_ir_opcode_14, 20)
  `DTP_FCOV_OPCODE(c_ir_opcode_15, 21)
  `DTP_FCOV_OPCODE(c_ir_opcode_16, 22)
  `DTP_FCOV_OPCODE(c_ir_opcode_17, 23)
  `DTP_FCOV_OPCODE(c_ir_opcode_18, 24)
  `DTP_FCOV_OPCODE(c_ir_opcode_19, 25)
  `DTP_FCOV_OPCODE(c_ir_opcode_1a, 26)
  `DTP_FCOV_OPCODE(c_ir_opcode_1b, 27)
  `DTP_FCOV_OPCODE(c_ir_opcode_1c, 28)
  `DTP_FCOV_OPCODE(c_ir_opcode_1d, 29)
  `DTP_FCOV_OPCODE(c_ir_opcode_1e, 30)
  `DTP_FCOV_OPCODE(c_ir_opcode_1f, 31)
  `DTP_FCOV_OPCODE(c_ir_opcode_20, 32)
  `DTP_FCOV_OPCODE(c_ir_opcode_21, 33)
  `DTP_FCOV_OPCODE(c_ir_opcode_22, 34)
  `DTP_FCOV_OPCODE(c_ir_opcode_23, 35)
  `DTP_FCOV_OPCODE(c_ir_opcode_24, 36)
  `DTP_FCOV_OPCODE(c_ir_opcode_25, 37)
  `DTP_FCOV_OPCODE(c_ir_opcode_26, 38)
  `DTP_FCOV_OPCODE(c_ir_opcode_27, 39)
  `DTP_FCOV_OPCODE(c_ir_opcode_28, 40)
  `DTP_FCOV_OPCODE(c_ir_opcode_29, 41)
  `DTP_FCOV_OPCODE(c_ir_opcode_2a, 42)
  `DTP_FCOV_OPCODE(c_ir_opcode_2b, 43)
  `DTP_FCOV_OPCODE(c_ir_opcode_2c, 44)
  `DTP_FCOV_OPCODE(c_ir_opcode_2d, 45)
  `DTP_FCOV_OPCODE(c_ir_opcode_2e, 46)
  `DTP_FCOV_OPCODE(c_ir_opcode_2f, 47)
  `DTP_FCOV_OPCODE(c_ir_opcode_30, 48)
  `DTP_FCOV_OPCODE(c_ir_opcode_31, 49)
  `DTP_FCOV_OPCODE(c_ir_opcode_32, 50)
  `DTP_FCOV_OPCODE(c_ir_opcode_33, 51)
  `DTP_FCOV_OPCODE(c_ir_opcode_34, 52)
  `DTP_FCOV_OPCODE(c_ir_opcode_35, 53)
  `DTP_FCOV_OPCODE(c_ir_opcode_36, 54)
  `DTP_FCOV_OPCODE(c_ir_opcode_37, 55)
  `DTP_FCOV_OPCODE(c_ir_opcode_38, 56)
  `DTP_FCOV_OPCODE(c_ir_opcode_39, 57)
  `DTP_FCOV_OPCODE(c_ir_opcode_3a, 58)
  `DTP_FCOV_OPCODE(c_ir_opcode_3b, 59)
  `DTP_FCOV_OPCODE(c_ir_opcode_3c, 60)
  `DTP_FCOV_OPCODE(c_ir_opcode_3d, 61)
  `DTP_FCOV_OPCODE(c_ir_opcode_3e, 62)
  `DTP_FCOV_OPCODE(c_ir_opcode_3f, 63)
  `undef DTP_FCOV_OPCODE

  `define DTP_FCOV_CATEGORY(__label, __mask)                                        \
    wire __label``_e = ir_committed && (|(inst_decoded_i & (__mask)));         \
    `OCAH_FCOV_COVER(__label, __label``_e, tck_i, in_reset)

  `DTP_FCOV_CATEGORY(c_ir_category_mandatory, CatMandatory)
  `DTP_FCOV_CATEGORY(c_ir_category_optional, CatOptional)
  `DTP_FCOV_CATEGORY(c_ir_category_ieee1838, CatIeee1838)
  `DTP_FCOV_CATEGORY(c_ir_category_debug, CatDebug)
  `DTP_FCOV_CATEGORY(c_ir_category_ijtag, CatIjtag)
  `DTP_FCOV_CATEGORY(c_ir_category_jtag2axi, CatJtag2axi)
  `DTP_FCOV_CATEGORY(c_ir_category_reserved, CatReserved)
  `DTP_FCOV_CATEGORY(c_ir_category_undefined, CatUndefined)
  `undef DTP_FCOV_CATEGORY

  wire behavior_enabled_e = ir_committed && !disabled_instruction_committed
      && (|(inst_decoded_i & ~(CatReserved | CatUndefined)));
  wire behavior_undefined_e =
      ir_committed && (|(inst_decoded_i & (CatReserved | CatUndefined)));
  `OCAH_FCOV_COVER(c_ir_behavior_enabled_instruction, behavior_enabled_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ir_behavior_undefined_to_bypass, behavior_undefined_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ir_behavior_disabled_to_bypass, disabled_instruction_committed, tck_i,
                   in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups mirroring the cover-property bins.
  // ------------------------------------------------------------------
  function automatic logic [3:0] state_index(logic [15:0] onehot);
    for (int i = 0; i < 16; i++) begin
      if (onehot[i]) return 4'(i);
    end
    return '0;
  endfunction

  function automatic logic [5:0] opcode_index(logic [63:0] onehot);
    for (int i = 0; i < 64; i++) begin
      if (onehot[i]) return 6'(i);
    end
    return '0;
  endfunction

  function automatic logic [2:0] category_index(logic [63:0] onehot);
    if (|(onehot & CatMandatory)) return 3'd0;
    if (|(onehot & CatOptional)) return 3'd1;
    if (|(onehot & CatIeee1838)) return 3'd2;
    if (|(onehot & CatDebug)) return 3'd3;
    if (|(onehot & CatIjtag)) return 3'd4;
    if (|(onehot & CatJtag2axi)) return 3'd5;
    if (|(onehot & CatReserved)) return 3'd6;
    return 3'd7;  // undefined
  endfunction

  covergroup cg_scan_boundary @(posedge tck_i);
    option.per_instance = 1;
    cp_boundary: coverpoint {
      update_ir, update_dr
    } iff (!in_reset) {
      bins ir_scan = {2'b10}; bins dr_scan = {2'b01};
    }
  endgroup

  covergroup cg_tap_state with function sample (logic [3:0] st);
    option.per_instance = 1;
    cp_state: coverpoint st {bins state[] = {[0 : 15]};}
  endgroup

  // Bin values are the same one-hot positions state_index() reports at run
  // time; the labels follow the c_arc_* cover properties.
  `define DTP_FCOV_ARC_BIN(__label, __from, __tms, __to)                        \
    bins __label = {{4'($clog2(jtag_tap_pkg::__from)), (__tms),               \
                     4'($clog2(jtag_tap_pkg::__to))}};

  covergroup cg_tap_arc with function sample (logic [3:0] prev, logic tms, logic [3:0] nxt);
    option.per_instance = 1;
    cp_prev: coverpoint prev {bins state[] = {[0 : 15]};}
    cp_tms: coverpoint tms;
    cp_next: coverpoint nxt {bins state[] = {[0 : 15]};}
    // TMS reaches exactly one next state from each state, so the 32 arcs
    // below are the only (prev, tms, next) triples the controller produces;
    // a TRST pulse between two TCK edges lands in TEST_LOGIC_RESET from any
    // state and is collected by c_reset_trst_from_active instead.
    cp_arc: coverpoint {
      prev, tms, nxt
    } {
      `DTP_FCOV_ARC_BIN(tlr_tms0_rti, TEST_LOGIC_RESET, 1'b0, RUN_TEST_IDLE)
      `DTP_FCOV_ARC_BIN(tlr_tms1_tlr, TEST_LOGIC_RESET, 1'b1, TEST_LOGIC_RESET)
      `DTP_FCOV_ARC_BIN(rti_tms0_rti, RUN_TEST_IDLE, 1'b0, RUN_TEST_IDLE)
      `DTP_FCOV_ARC_BIN(rti_tms1_seldr, RUN_TEST_IDLE, 1'b1, SELECT_DR_SCAN)
      `DTP_FCOV_ARC_BIN(seldr_tms0_capdr, SELECT_DR_SCAN, 1'b0, CAPTURE_DR)
      `DTP_FCOV_ARC_BIN(seldr_tms1_selir, SELECT_DR_SCAN, 1'b1, SELECT_IR_SCAN)
      `DTP_FCOV_ARC_BIN(capdr_tms0_shdr, CAPTURE_DR, 1'b0, SHIFT_DR)
      `DTP_FCOV_ARC_BIN(capdr_tms1_ex1dr, CAPTURE_DR, 1'b1, EXIT1_DR)
      `DTP_FCOV_ARC_BIN(shdr_tms0_shdr, SHIFT_DR, 1'b0, SHIFT_DR)
      `DTP_FCOV_ARC_BIN(shdr_tms1_ex1dr, SHIFT_DR, 1'b1, EXIT1_DR)
      `DTP_FCOV_ARC_BIN(ex1dr_tms0_pdr, EXIT1_DR, 1'b0, PAUSE_DR)
      `DTP_FCOV_ARC_BIN(ex1dr_tms1_updr, EXIT1_DR, 1'b1, UPDATE_DR)
      `DTP_FCOV_ARC_BIN(pdr_tms0_pdr, PAUSE_DR, 1'b0, PAUSE_DR)
      `DTP_FCOV_ARC_BIN(pdr_tms1_ex2dr, PAUSE_DR, 1'b1, EXIT2_DR)
      `DTP_FCOV_ARC_BIN(ex2dr_tms0_shdr, EXIT2_DR, 1'b0, SHIFT_DR)
      `DTP_FCOV_ARC_BIN(ex2dr_tms1_updr, EXIT2_DR, 1'b1, UPDATE_DR)
      `DTP_FCOV_ARC_BIN(updr_tms0_rti, UPDATE_DR, 1'b0, RUN_TEST_IDLE)
      `DTP_FCOV_ARC_BIN(updr_tms1_seldr, UPDATE_DR, 1'b1, SELECT_DR_SCAN)
      `DTP_FCOV_ARC_BIN(selir_tms0_capir, SELECT_IR_SCAN, 1'b0, CAPTURE_IR)
      `DTP_FCOV_ARC_BIN(selir_tms1_tlr, SELECT_IR_SCAN, 1'b1, TEST_LOGIC_RESET)
      `DTP_FCOV_ARC_BIN(capir_tms0_shir, CAPTURE_IR, 1'b0, SHIFT_IR)
      `DTP_FCOV_ARC_BIN(capir_tms1_ex1ir, CAPTURE_IR, 1'b1, EXIT1_IR)
      `DTP_FCOV_ARC_BIN(shir_tms0_shir, SHIFT_IR, 1'b0, SHIFT_IR)
      `DTP_FCOV_ARC_BIN(shir_tms1_ex1ir, SHIFT_IR, 1'b1, EXIT1_IR)
      `DTP_FCOV_ARC_BIN(ex1ir_tms0_pir, EXIT1_IR, 1'b0, PAUSE_IR)
      `DTP_FCOV_ARC_BIN(ex1ir_tms1_upir, EXIT1_IR, 1'b1, UPDATE_IR)
      `DTP_FCOV_ARC_BIN(pir_tms0_pir, PAUSE_IR, 1'b0, PAUSE_IR)
      `DTP_FCOV_ARC_BIN(pir_tms1_ex2ir, PAUSE_IR, 1'b1, EXIT2_IR)
      `DTP_FCOV_ARC_BIN(ex2ir_tms0_shir, EXIT2_IR, 1'b0, SHIFT_IR)
      `DTP_FCOV_ARC_BIN(ex2ir_tms1_upir, EXIT2_IR, 1'b1, UPDATE_IR)
      `DTP_FCOV_ARC_BIN(upir_tms0_rti, UPDATE_IR, 1'b0, RUN_TEST_IDLE)
      `DTP_FCOV_ARC_BIN(upir_tms1_seldr, UPDATE_IR, 1'b1, SELECT_DR_SCAN)
    }
  endgroup
  `undef DTP_FCOV_ARC_BIN

  covergroup cg_jtag_instruction with function sample (
      logic [5:0] opcode, logic [2:0] category, logic disabled_to_bypass
  );
    option.per_instance = 1;
    cp_opcode: coverpoint opcode {bins op[] = {[0 : 63]};}
    cp_category: coverpoint category {
      bins mandatory = {3'd0};
      bins optional_instr = {3'd1};
      bins ieee1838 = {3'd2};
      bins debug = {3'd3};
      bins ijtag = {3'd4};
      bins jtag2axi = {3'd5};
      bins reserved = {3'd6};
      bins undefined = {3'd7};
    }
    cp_disabled_behavior: coverpoint disabled_to_bypass {
      bins enabled_or_undefined = {1'b0}; bins disabled_to_bypass = {1'b1};
    }
  endgroup

  cg_scan_boundary u_cg_scan_boundary = new();
  cg_tap_state u_cg_tap_state = new();
  cg_tap_arc u_cg_tap_arc = new();
  cg_jtag_instruction u_cg_jtag_instruction = new();

  always_ff @(posedge tck_i) begin
    if (!in_reset) begin
      u_cg_tap_state.sample(state_index(tap_state_i));
      if ($onehot(tap_state_q)) begin
        u_cg_tap_arc.sample(state_index(tap_state_q), tms_q, state_index(tap_state_i));
      end
      if (ir_committed && $onehot(inst_decoded_i)) begin
        u_cg_jtag_instruction.sample(opcode_index(inst_decoded_i), category_index(inst_decoded_i),
                                     disabled_instruction_committed);
      end
    end
  end
`endif

endmodule : dtp_fcov
