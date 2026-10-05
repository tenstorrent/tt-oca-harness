// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Stimulus sequence item. Operation kinds:
//
//   OCAH_JTAG_TAP_RESET — assert TRST for cfg.trst_reset_cycles TCK cycles
//     (TMS held 1), release, leave the TAP in Test-Logic-Reset.
//   OCAH_JTAG_TRST_LEVEL — drive TRST to `trst_asserted` (trst_n low when
//     asserted), then hold TMS at `trst_tms` for `trst_tck_cycles` TCK
//     cycles. TMS 1 is the Test-Logic-Reset self-loop; TMS 0 never enters
//     Test-Logic-Reset, so only the reset can put the controller there. Asserting
//     leaves the TAP in Test-Logic-Reset; releasing moves nothing.
//   OCAH_JTAG_IR_SCAN   — from Run-Test/Idle: load `width` IR bits from
//     `wdata` (LSB-first), return to Run-Test/Idle. Observed TDO in `tdo`.
//   OCAH_JTAG_DR_SCAN   — from Run-Test/Idle: shift `width` DR bits from
//     `wdata` (LSB-first), return to Run-Test/Idle. Observed TDO in `tdo`.
//   OCAH_JTAG_RAW_TMS   — drive tms_bits[]/tdi_bits[] one TCK cycle per
//     element from ANY state; per-step observed TDO in tdo_bits[].
//
// Scan preconditions are the caller's contract: IR/DR scans assume the TAP
// is in Run-Test/Idle (the driver navigates RTI -> scan leg -> RTI). The
// driver fills response fields in the same object before item_done, so
// sequences read them directly after finish_item().

typedef enum {
  OCAH_JTAG_TAP_RESET,
  OCAH_JTAG_IR_SCAN,
  OCAH_JTAG_DR_SCAN,
  OCAH_JTAG_RAW_TMS,
  OCAH_JTAG_TRST_LEVEL
} ocah_jtag_op_e;

class ocah_jtag_item extends uvm_sequence_item;
  `uvm_object_utils(ocah_jtag_item)

  rand ocah_jtag_op_e op = OCAH_JTAG_RAW_TMS;
  rand int unsigned  width;        // scan bit count (1..64); unused for raw/reset
  rand bit [63:0]    wdata;        // scan write pattern, LSB-first

  bit tms_bits[];                  // raw op: per-step TMS (defines step count)
  bit tdi_bits[];                  // raw op: per-step TDI (padded with 0 if shorter)

  bit          trst_asserted;      // TRST level op: TRST asserted (trst_n low)
  int unsigned trst_tck_cycles;    // TRST level op: TCK cycles after the level change
  bit          trst_tms = 1'b1;    // TRST level op: TMS level held through those cycles

  // Wide-scan extension: when wbits is non-empty, IR/DR scans shift
  // wbits.size() bits LSB-first (no 64-bit limit; e.g. the 72/132-bit
  // DTP JTAG2AXI TDRs) and width/wdata/tdo are ignored for that item.
  bit wbits[];                     // wide scan write pattern, LSB-first
  bit rbits[];                     // wide scan observed TDO (driver-filled)

  // Responses (driver-filled).
  bit [63:0] tdo;                  // scan ops: observed TDO, LSB-first
  bit tdo_bits[];                  // raw op: per-step observed TDO

  constraint width_c {
    (wbits.size() == 0) ->
    width inside {[1 : 64]};
  }

  function new(string name = "ocah_jtag_item");
    super.new(name);
  endfunction

  function string convert2string();
    case (op)
      OCAH_JTAG_TAP_RESET: return "TAP_RESET";
      OCAH_JTAG_IR_SCAN:
                if (wbits.size() > 0)
                    return $sformatf("IR_SCAN  wide width=%0d", wbits.size());
                else
                    return $sformatf("IR_SCAN  width=%0d wdata=0x%0h tdo=0x%0h", width, wdata, tdo);
      OCAH_JTAG_DR_SCAN:
                if (wbits.size() > 0)
                    return $sformatf("DR_SCAN  wide width=%0d", wbits.size());
                else
                    return $sformatf("DR_SCAN  width=%0d wdata=0x%016h tdo=0x%016h", width, wdata, tdo);
      OCAH_JTAG_TRST_LEVEL:
                return $sformatf("TRST_LEVEL asserted=%0b tck=%0d tms=%0b", trst_asserted,
                                 trst_tck_cycles, trst_tms);
      default:             return $sformatf("RAW_TMS  steps=%0d", tms_bits.size());
    endcase
  endfunction

endclass : ocah_jtag_item
