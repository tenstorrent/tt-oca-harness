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
  input wire        por_ni,          // power-on reset, ANDed with TRST into the TAP reset
  input wire [15:0] tap_state_i,     // one-hot jtag_tap_pkg::tap_state_e
  input wire [63:0] inst_decoded_i,  // one-hot decoded IR
  input wire        stap_select_i,   // PTAP TAP_3DCR select: the STAP chain return drives TDO
  input wire sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_i
);

  // ------------------------------------------------------------------
  // Shared event decode. The documented sampling boundaries (completed
  // IR scan, completed DR scan) map onto the UPDATE_* one-hot TAP states;
  // per-area transaction events are wired in by each section.
  //
  // Timing: the TAP state and the decoded IR are registered on TCK, so a
  // posedge sample reads the state the TAP held up to this edge, and
  // tap_state_q/tms_q describe the transition taken INTO tap_state_i.
  // update_dr is the edge that leaves UPDATE_DR, with the DR scan complete
  // under the instruction it scanned; ir_committed is the edge after the one
  // that left UPDATE_IR, with inst_decoded_i showing the committed
  // instruction. A TRST or the end of a test can follow a scan with no
  // further TCK edge, so DR-scan points sample on update_dr.
  // ------------------------------------------------------------------
  wire in_reset  = (trst_ni !== 1'b1);
  wire update_ir = (tap_state_i == jtag_tap_pkg::UPDATE_IR);
  wire update_dr = (tap_state_i == jtag_tap_pkg::UPDATE_DR);

  // Source of the most recent move to Test-Logic-Reset.
  localparam logic [1:0] RstNone = 2'd0;
  localparam logic [1:0] RstTrst = 2'd1;
  localparam logic [1:0] RstPor = 2'd2;
  localparam logic [1:0] RstTms = 2'd3;

  // No declaration initializers: VCS rejects them on always_ff-driven
  // variables (initializer_driver_checks). Before the first TCK edge the
  // history reads 0 (Verilator, 2-state) or X (VCS), so every cover
  // condition must require a defined non-zero history pattern.
  logic [15:0] tap_state_q;
  logic        tms_q;
  logic        ir_loaded_since_tlr;
  logic        ir_shifted_since_capture;
  logic [1:0]  last_reset_q;
  logic        por_seen_q;

  // Power-on reset holds this set and the next TCK edge clears it, so that
  // edge reads 1 even when TCK stayed idle across the pulse.
  always_ff @(posedge tck_i or negedge por_ni) begin
    if (!por_ni) begin
      por_seen_q <= 1'b1;
    end else begin
      por_seen_q <= 1'b0;
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
  wire        ir_zero_shift = !ir_shifted_since_capture;
  wire [1:0]  last_reset = last_reset_q;
  wire        por_seen = por_seen_q;

  wire ir_committed = (tap_state_prev == jtag_tap_pkg::UPDATE_IR) && !in_reset;
  wire dr_scan_done = update_dr && !in_reset;
  // First rising edge inside SHIFT_DR: the first captured bit is on TDO.
  wire first_dr_bit =
      (tap_state_prev == jtag_tap_pkg::CAPTURE_DR)
      && (tap_state_i == jtag_tap_pkg::SHIFT_DR);
  wire prev_active = (tap_state_prev != '0)
      && (tap_state_prev != jtag_tap_pkg::TEST_LOGIC_RESET);
  // Every TMS-driven entry to Test-Logic-Reset from another state takes the
  // Select-IR-Scan TMS=1 arc.
  wire tms_to_tlr_e = (tap_state_prev == jtag_tap_pkg::SELECT_IR_SCAN)
      && tms_prev && (tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET);

  always_ff @(posedge tck_i) begin
    tap_state_q <= tap_state_i;
    tms_q       <= tms_i;
    if (tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET || in_reset) begin
      ir_loaded_since_tlr <= 1'b0;
    end else if (tap_state_i == jtag_tap_pkg::UPDATE_IR) begin
      ir_loaded_since_tlr <= 1'b1;
    end
    if (tap_state_i == jtag_tap_pkg::CAPTURE_IR) begin
      ir_shifted_since_capture <= 1'b0;
    end else if (tap_state_i == jtag_tap_pkg::SHIFT_IR) begin
      ir_shifted_since_capture <= 1'b1;
    end
    if (in_reset) begin
      last_reset_q <= RstTrst;
    end else if (por_seen) begin
      last_reset_q <= RstPor;
    end else if (tms_to_tlr_e) begin
      last_reset_q <= RstTms;
    end
  end

  // ------------------------------------------------------------------
  // Instruction categories (cg_jtag_instruction.cp_category): one mask per
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

  // Instructions whose data register a dbg_disable_t field gates. A gated
  // instruction decodes as itself and keeps its register on the scan path:
  // a bridge field blocks that bridge's TDR updates and AXI traffic, and a
  // SIB field holds its SIB closed in the iJTAG network that SELECT_IJTAG
  // and RUNBIST select.
  localparam logic [63:0] SmcJtag2axiOps = 64'h0000_1F00_0000_0000;  // 0x28-0x2C
  localparam logic [63:0] SmcOtpJtag2axiOps = 64'h0000_0001_F000_0000;  // 0x1C-0x20
  localparam logic [63:0] SepOtpJtag2axiOps = 64'h0000_007C_0000_0000;  // 0x22-0x26
  localparam logic [63:0] SelectIjtag = 64'h0000_0000_0400_0000;  // 0x1A
  localparam logic [63:0] Runbist = 64'h0000_0000_0000_0004;  // 0x02

  // ------------------------------------------------------------------
  // Scan-boundary liveness points.
  // ------------------------------------------------------------------
  `OCAH_FCOV_COVER(c_completed_ir_scan, update_ir, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_completed_dr_scan, update_dr, tck_i, in_reset)

  // ------------------------------------------------------------------
  // cg_tap_state and cg_tap_arc: all 16 IEEE 1149.1 states and all 32
  // legal (state, tms) arcs.
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

  // ------------------------------------------------------------------
  // cg_tap_smoke: the reset that moves the TAP from an active state to
  // Test-Logic-Reset, the IDCODE reads, and the IDCODE marker bit.
  // ------------------------------------------------------------------
  // TRST covers must stay armed while reset is asserted, so they carry no
  // reset disable. Power-on reset high on the TRST edge and TRST high on the
  // power-on edge make each the only reset source of its point.
  wire trst_from_active_e = !trst_ni && por_ni && prev_active;
  wire por_from_active_e = por_seen && prev_active
      && (tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET);
  `OCAH_FCOV_COVER(c_reset_trst_from_active, trst_from_active_e, tck_i, 1'b0)
  `OCAH_FCOV_COVER(c_reset_por_from_active, por_from_active_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_reset_tms5_from_active, tms_to_tlr_e, tck_i, in_reset)

  // While the TAP_3DCR select is set TDO carries the STAP chain return, so
  // the first bit of a DR scan is not the IDCODE marker.
  wire idcode_active = (inst_decoded_i == 64'h2);
  wire idcode_dr_scan = dr_scan_done && idcode_active && !stap_select_i;
  wire idcode_default_e = idcode_dr_scan && !ir_seen_since_tlr;
  wire idcode_default_after_trst_e = idcode_default_e && (last_reset == RstTrst);
  wire idcode_default_after_por_e = idcode_default_e && (last_reset == RstPor);
  wire idcode_default_after_tms5_e = idcode_default_e && (last_reset == RstTms);
  wire idcode_explicit_e = idcode_dr_scan && ir_seen_since_tlr;
  // First captured IDCODE bit on TDO is the IEEE 1149.1 marker (must be 1);
  // an invalid marker is a checker failure, never a coverage bin.
  wire idcode_marker_read = first_dr_bit && idcode_active && !stap_select_i;
  wire idcode_marker_e = idcode_marker_read && tdo_i;
  `OCAH_FCOV_COVER(c_smoke_idcode_default_after_trst, idcode_default_after_trst_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smoke_idcode_default_after_por, idcode_default_after_por_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smoke_idcode_default_after_tms5, idcode_default_after_tms5_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smoke_idcode_explicit_instruction, idcode_explicit_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_smoke_idcode_marker_1, idcode_marker_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // cg_jtag_instruction: all 64 opcodes at completed IR scans, the eight
  // instruction categories, and the two ways Update-IR loads the register.
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

  // An Update-IR with no Shift-IR cycle since Capture-IR latches the
  // Capture-IR pattern 6'b000001, the IDCODE opcode.
  wire ir_update_shifted_e = ir_committed && !ir_zero_shift;
  wire ir_update_capture_pattern_e = ir_committed && ir_zero_shift && idcode_active;
  `OCAH_FCOV_COVER(c_ir_update_shifted, ir_update_shifted_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ir_update_capture_pattern, ir_update_capture_pattern_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // cg_dr_scan: a completed DR scan under each IEEE 1149.1 and TMP
  // instruction, and the two ZERO_LENGTH_BYPASS paths.
  // ------------------------------------------------------------------
  `define DTP_FCOV_DR_SCAN(__label, __mask)                                         \
    wire __label``_e = dr_scan_done && (|(inst_decoded_i & (__mask)));         \
    `OCAH_FCOV_COVER(__label, __label``_e, tck_i, in_reset)

  `DTP_FCOV_DR_SCAN(c_dr_scan_bypass_alt, 64'h1 << 'h00)
  `DTP_FCOV_DR_SCAN(c_dr_scan_idcode, 64'h1 << 'h01)
  `DTP_FCOV_DR_SCAN(c_dr_scan_runbist, 64'h1 << 'h02)
  `DTP_FCOV_DR_SCAN(c_dr_scan_sample_preload, 64'h1 << 'h03)
  `DTP_FCOV_DR_SCAN(c_dr_scan_extest, 64'h1 << 'h04)
  `DTP_FCOV_DR_SCAN(c_dr_scan_extest_train, 64'h1 << 'h05)
  `DTP_FCOV_DR_SCAN(c_dr_scan_extest_pulse, 64'h1 << 'h06)
  `DTP_FCOV_DR_SCAN(c_dr_scan_clamp, 64'h1 << 'h07)
  `DTP_FCOV_DR_SCAN(c_dr_scan_highz, 64'h1 << 'h08)
  `DTP_FCOV_DR_SCAN(c_dr_scan_intest, 64'h1 << 'h09)
  `DTP_FCOV_DR_SCAN(c_dr_scan_clamp_hold, 64'h1 << 'h0A)
  `DTP_FCOV_DR_SCAN(c_dr_scan_clamp_release, 64'h1 << 'h0B)
  `DTP_FCOV_DR_SCAN(c_dr_scan_reserved, CatReserved)
  `DTP_FCOV_DR_SCAN(c_dr_scan_undefined, CatUndefined)
  `DTP_FCOV_DR_SCAN(c_dr_scan_zero_length_bypass, 64'h1 << 'h3D)
  `DTP_FCOV_DR_SCAN(c_dr_scan_inv_bypass, 64'h1 << 'h3E)
  `DTP_FCOV_DR_SCAN(c_dr_scan_bypass, 64'h1 << 'h3F)
  `undef DTP_FCOV_DR_SCAN

  // ZERO_LENGTH_BYPASS connects TDI to TDO while the TAP_3DCR select is
  // clear and behaves exactly as BYPASS while it is set.
  wire zlb_zero_length_e = c_dr_scan_zero_length_bypass_e && !stap_select_i;
  wire zlb_as_bypass_e = c_dr_scan_zero_length_bypass_e && stap_select_i;
  `OCAH_FCOV_COVER(c_dr_scan_zlb_zero_length, zlb_zero_length_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_dr_scan_zlb_as_bypass, zlb_as_bypass_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // cg_instruction_gate: a completed DR scan under each gated instruction
  // with the dbg_disable_t field that gates its register clear and set.
  // ------------------------------------------------------------------
  `define DTP_FCOV_GATE(__label, __mask, __field, __value)                          \
    wire __label``_e = dr_scan_done && (|(inst_decoded_i & (__mask)))           \
        && (dbg_disable_i.__field == (__value));                                       \
    `OCAH_FCOV_COVER(__label, __label``_e, tck_i, in_reset)

  `DTP_FCOV_GATE(c_gate_smc_axi_tdr_clear, SmcJtag2axiOps, smc_jtag2axi, 1'b0)
  `DTP_FCOV_GATE(c_gate_smc_axi_tdr_set, SmcJtag2axiOps, smc_jtag2axi, 1'b1)
  `DTP_FCOV_GATE(c_gate_smc_otp_tdr_clear, SmcOtpJtag2axiOps, smc_otp_jtag2axi, 1'b0)
  `DTP_FCOV_GATE(c_gate_smc_otp_tdr_set, SmcOtpJtag2axiOps, smc_otp_jtag2axi, 1'b1)
  `DTP_FCOV_GATE(c_gate_sep_otp_tdr_clear, SepOtpJtag2axiOps, sep_otp_jtag2axi, 1'b0)
  `DTP_FCOV_GATE(c_gate_sep_otp_tdr_set, SepOtpJtag2axiOps, sep_otp_jtag2axi, 1'b1)
  `DTP_FCOV_GATE(c_gate_ijtag_dft_secure_clear, SelectIjtag, dft_secure, 1'b0)
  `DTP_FCOV_GATE(c_gate_ijtag_dft_secure_set, SelectIjtag, dft_secure, 1'b1)
  `DTP_FCOV_GATE(c_gate_ijtag_dft_nonsecure_clear, SelectIjtag, dft_nonsecure, 1'b0)
  `DTP_FCOV_GATE(c_gate_ijtag_dft_nonsecure_set, SelectIjtag, dft_nonsecure, 1'b1)
  `DTP_FCOV_GATE(c_gate_ijtag_dfd_clear, SelectIjtag, dfd, 1'b0)
  `DTP_FCOV_GATE(c_gate_ijtag_dfd_set, SelectIjtag, dfd, 1'b1)
  `DTP_FCOV_GATE(c_gate_runbist_dft_nonsecure_clear, Runbist, dft_nonsecure, 1'b0)
  `DTP_FCOV_GATE(c_gate_runbist_dft_nonsecure_set, Runbist, dft_nonsecure, 1'b1)
  `undef DTP_FCOV_GATE

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups mirroring the cover-property bins.
  // ------------------------------------------------------------------
  import jtag_tap_pkg::*;

  // A value that is not one-hot maps past the last index.
  function automatic logic [4:0] state_code(logic [15:0] onehot);
    for (int i = 0; i < 16; i++) begin
      if (onehot == (16'h1 << i)) return 5'(i);
    end
    return 5'd16;
  endfunction

  function automatic logic [6:0] opcode_code(logic [63:0] onehot);
    for (int i = 0; i < 64; i++) begin
      if (onehot == (64'h1 << i)) return 7'(i);
    end
    return 7'd64;
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

  // IEEE 1149.1 state graph: the state TMS selects from each state.
  function automatic logic [15:0] tap_next(logic [15:0] st, logic tms);
    case (st)
      TEST_LOGIC_RESET: return tms ? TEST_LOGIC_RESET : RUN_TEST_IDLE;
      RUN_TEST_IDLE:    return tms ? SELECT_DR_SCAN : RUN_TEST_IDLE;
      SELECT_DR_SCAN:   return tms ? SELECT_IR_SCAN : CAPTURE_DR;
      CAPTURE_DR:       return tms ? EXIT1_DR : SHIFT_DR;
      SHIFT_DR:         return tms ? EXIT1_DR : SHIFT_DR;
      EXIT1_DR:         return tms ? UPDATE_DR : PAUSE_DR;
      PAUSE_DR:         return tms ? EXIT2_DR : PAUSE_DR;
      EXIT2_DR:         return tms ? UPDATE_DR : SHIFT_DR;
      UPDATE_DR:        return tms ? SELECT_DR_SCAN : RUN_TEST_IDLE;
      SELECT_IR_SCAN:   return tms ? TEST_LOGIC_RESET : CAPTURE_IR;
      CAPTURE_IR:       return tms ? EXIT1_IR : SHIFT_IR;
      SHIFT_IR:         return tms ? EXIT1_IR : SHIFT_IR;
      EXIT1_IR:         return tms ? UPDATE_IR : PAUSE_IR;
      PAUSE_IR:         return tms ? EXIT2_IR : PAUSE_IR;
      EXIT2_IR:         return tms ? UPDATE_IR : SHIFT_IR;
      UPDATE_IR:        return tms ? SELECT_DR_SCAN : RUN_TEST_IDLE;
      default:          return '0;
    endcase
  endfunction

  covergroup cg_scan_boundary @(posedge tck_i);
    option.per_instance = 1;
    cp_boundary: coverpoint {
      update_ir, update_dr
    } iff (!in_reset) {
      bins ir_scan = {2'b10}; bins dr_scan = {2'b01};
    }
  endgroup

  covergroup cg_tap_state with function sample (logic [4:0] st);
    option.per_instance = 1;
    cp_state: coverpoint st {
      bins state[] = {[0 : 15]};
      // The controller holds exactly one state bit.
      illegal_bins not_onehot = {5'd16};
    }
  endgroup

  // An arc off the state graph samples ArcIllegal unless it ends in
  // Test-Logic-Reset: TRST and power-on reset hold or move the TAP there
  // whatever TMS is, so the first arc after a reset can end there off the
  // graph, and cg_tap_arc does not sample it.
  localparam logic [9:0] ArcIllegal = 10'h200;

  // Bin values are the same one-hot positions state_code() reports at run
  // time; the labels follow the c_arc_* cover properties.
  `define DTP_FCOV_ARC_BIN(__label, __from, __tms, __to) \
    bins __label = {{1'b0, 4'($clog2(__from)), (__tms), 4'($clog2(__to))}};

  covergroup cg_tap_arc with function sample (logic [9:0] arc);
    option.per_instance = 1;
    cp_arc: coverpoint arc {
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
      // TMS selects exactly one next state from each state.
      illegal_bins off_graph = {ArcIllegal};
    }
  endgroup
  `undef DTP_FCOV_ARC_BIN

  covergroup cg_tap_smoke with function sample (
      logic [1:0] reset_source,
      logic idcode_read,
      logic [2:0] idcode_origin,
      logic marker_read,
      logic marker
  );
    option.per_instance = 1;
    cp_reset_source: coverpoint reset_source iff (reset_source != RstNone) {
      bins trst = {RstTrst}; bins por = {RstPor}; bins tms5 = {RstTms};
    }
    // idcode_origin is {an IR update since Test-Logic-Reset, last reset source}.
    cp_idcode_read: coverpoint idcode_origin iff (idcode_read) {
      bins default_after_trst = {{1'b0, RstTrst}};
      bins default_after_por = {{1'b0, RstPor}};
      bins default_after_tms5 = {{1'b0, RstTms}};
      bins explicit_instruction = {[3'b100 : 3'b111]};
    }
    cp_idcode_marker: coverpoint marker iff (marker_read) {
      bins marker_1 = {1'b1};
      // IEEE 1149.1 fixes the first IDCODE bit at 1.
      illegal_bins marker_0 = {1'b0};
    }
  endgroup

  covergroup cg_jtag_instruction with function sample (
      logic [6:0] opcode, logic [2:0] category, logic zero_shift
  );
    option.per_instance = 1;
    cp_opcode: coverpoint opcode {
      bins op[] = {[0 : 63]};
      // The instruction register decodes exactly one opcode.
      illegal_bins not_onehot = {7'd64};
    }
    cp_category: coverpoint category iff (opcode != 7'd64) {
      bins mandatory = {3'd0};
      bins optional_instr = {3'd1};
      bins ieee1838 = {3'd2};
      bins debug = {3'd3};
      bins ijtag = {3'd4};
      bins jtag2axi = {3'd5};
      bins reserved = {3'd6};
      bins undefined = {3'd7};
    }
    cp_ir_update: coverpoint {
      zero_shift, opcode == 7'd1
    } {
      bins shifted = {2'b00, 2'b01};
      bins capture_pattern = {2'b11};
      // The Capture-IR pattern is the IDCODE opcode.
      illegal_bins capture_not_idcode = {2'b10};
    }
  endgroup

  covergroup cg_dr_scan with function sample (logic [6:0] opcode, logic stap_select);
    option.per_instance = 1;
    cp_dr_instruction: coverpoint opcode {
      bins bypass_alt = {7'h00};
      bins idcode = {7'h01};
      bins runbist = {7'h02};
      bins sample_preload = {7'h03};
      bins extest = {7'h04};
      bins extest_train = {7'h05};
      bins extest_pulse = {7'h06};
      bins clamp = {7'h07};
      bins highz = {7'h08};
      bins intest = {7'h09};
      bins clamp_hold = {7'h0A};
      bins clamp_release = {7'h0B};
      bins reserved = {[7'h10 : 7'h17]};
      bins undefined = {7'h0F, [7'h2D : 7'h3C]};
      bins zero_length_bypass = {7'h3D};
      bins inv_bypass = {7'h3E};
      bins bypass = {7'h3F};
    }
    cp_zero_length_path: coverpoint stap_select iff (opcode == 7'h3D) {
      bins zero_length = {1'b0}; bins as_bypass = {1'b1};
    }
  endgroup

  localparam logic [2:0] GateSmcAxi = 3'd0;
  localparam logic [2:0] GateSmcOtp = 3'd1;
  localparam logic [2:0] GateSepOtp = 3'd2;
  localparam logic [2:0] GateIjtagDftSecure = 3'd3;
  localparam logic [2:0] GateIjtagDftNonsecure = 3'd4;
  localparam logic [2:0] GateIjtagDfd = 3'd5;
  localparam logic [2:0] GateRunbistDftNonsecure = 3'd6;

  // The cross carries the score; its two operands only name the axes.
  covergroup cg_instruction_gate with function sample (logic [2:0] gate, logic disabled);
    option.per_instance = 1;
    cp_gate: coverpoint gate {
      option.weight = 0;
      type_option.weight = 0;
      bins smc_axi_tdr = {GateSmcAxi};
      bins smc_otp_tdr = {GateSmcOtp};
      bins sep_otp_tdr = {GateSepOtp};
      bins ijtag_dft_secure = {GateIjtagDftSecure};
      bins ijtag_dft_nonsecure = {GateIjtagDftNonsecure};
      bins ijtag_dfd = {GateIjtagDfd};
      bins runbist_dft_nonsecure = {GateRunbistDftNonsecure};
    }
    cp_disabled: coverpoint disabled {
      option.weight = 0; type_option.weight = 0; bins clear = {1'b0}; bins set = {1'b1};
    }
    cx_gate_disabled: cross cp_gate, cp_disabled;
  endgroup

  cg_scan_boundary u_cg_scan_boundary = new();
  cg_tap_state u_cg_tap_state = new();
  cg_tap_arc u_cg_tap_arc = new();
  cg_tap_smoke u_cg_tap_smoke = new();
  cg_jtag_instruction u_cg_jtag_instruction = new();
  cg_dr_scan u_cg_dr_scan = new();
  cg_instruction_gate u_cg_instruction_gate = new();

  wire [1:0] reset_source_now = trst_from_active_e ? RstTrst
      : (!in_reset && por_from_active_e) ? RstPor
      : (!in_reset && tms_to_tlr_e) ? RstTms : RstNone;

  wire [4:0] prev_code = state_code(tap_state_q);
  wire [4:0] next_code = state_code(tap_state_i);

  always_ff @(posedge tck_i) begin
    u_cg_tap_smoke.sample(reset_source_now, idcode_dr_scan, {ir_seen_since_tlr, last_reset},
                          idcode_marker_read && !in_reset, tdo_i);
    if (!in_reset) begin
      if (!$isunknown(tap_state_i)) begin
        u_cg_tap_state.sample(next_code);
      end
      if ($onehot(tap_state_q) && $onehot(tap_state_i)) begin
        if (tap_state_i == tap_next(tap_state_q, tms_q)) begin
          u_cg_tap_arc.sample({1'b0, prev_code[3:0], tms_q, next_code[3:0]});
        end else if (tap_state_i != TEST_LOGIC_RESET) begin
          u_cg_tap_arc.sample(ArcIllegal);
        end
      end
      if (ir_committed && !$isunknown(inst_decoded_i)) begin
        u_cg_jtag_instruction.sample(opcode_code(inst_decoded_i), category_index(inst_decoded_i),
                                     ir_zero_shift);
      end
      if (dr_scan_done && !$isunknown(inst_decoded_i)) begin
        u_cg_dr_scan.sample(opcode_code(inst_decoded_i), stap_select_i);
        if (|(inst_decoded_i & SmcJtag2axiOps)) begin
          u_cg_instruction_gate.sample(GateSmcAxi, dbg_disable_i.smc_jtag2axi);
        end
        if (|(inst_decoded_i & SmcOtpJtag2axiOps)) begin
          u_cg_instruction_gate.sample(GateSmcOtp, dbg_disable_i.smc_otp_jtag2axi);
        end
        if (|(inst_decoded_i & SepOtpJtag2axiOps)) begin
          u_cg_instruction_gate.sample(GateSepOtp, dbg_disable_i.sep_otp_jtag2axi);
        end
        if (|(inst_decoded_i & SelectIjtag)) begin
          u_cg_instruction_gate.sample(GateIjtagDftSecure, dbg_disable_i.dft_secure);
          u_cg_instruction_gate.sample(GateIjtagDftNonsecure, dbg_disable_i.dft_nonsecure);
          u_cg_instruction_gate.sample(GateIjtagDfd, dbg_disable_i.dfd);
        end
        if (|(inst_decoded_i & Runbist)) begin
          u_cg_instruction_gate.sample(GateRunbistDftNonsecure, dbg_disable_i.dft_nonsecure);
        end
      end
    end
  end
`endif

endmodule : dtp_fcov
