// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Compressor Checker Module
//
// Description:
//   Compares DUT compressor output against reference model output.
//   Reports mismatches using $error and tracks statistics.
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module Compressor_Checker (
  input  logic        clk_i,
  input  logic        rstn_i,

  // Control
  input  logic        enable_i,           // Master enable
  input  logic        verbose_i,          // Show MATCH messages

  // DUT inputs (from entropy_source)
  input  logic [31:0] dut_word_i,         // DUT compressed word
  input  logic [31:0] dut_vld_i,          // DUT valid (32-bit vector, check bit [0])

  // Reference model inputs
  input  logic [31:0] ref_word_i,         // Reference compressed word
  input  logic        ref_vld_i,          // Reference valid

  // Statistics outputs
  output integer      check_count_o,      // Total checks performed
  output integer      mismatch_count_o    // Number of mismatches detected
);

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  integer check_count;
  integer mismatch_count;

  // Extract DUT valid signal (bit 0 of the 32-bit vector)
  logic dut_vld;
  assign dut_vld = dut_vld_i[0];

  //--------------------------------------------------------------------------
  // Statistics Tracking
  //--------------------------------------------------------------------------

  always_ff @(posedge clk_i or negedge rstn_i) begin
    if (!rstn_i) begin
      check_count    <= 0;
      mismatch_count <= 0;
    end else if (enable_i && ref_vld_i && dut_vld) begin
      // Both outputs are valid - perform comparison
      check_count <= check_count + 1;

      if (ref_word_i !== dut_word_i) begin
        // Mismatch detected
        mismatch_count <= mismatch_count + 1;

        $error("[COMPRESSOR_CHECKER] MISMATCH at check %0d:", check_count + 1);
        $error("  DUT:  0x%08X", dut_word_i);
        $error("  REF:  0x%08X", ref_word_i);
        $error("  XOR:  0x%08X", dut_word_i ^ ref_word_i);

        // Show byte-by-byte breakdown
        $error("  Byte breakdown:");
        $error("    [31:24] DUT=0x%02X REF=0x%02X %s", dut_word_i[31:24], ref_word_i[31:24],
               (dut_word_i[31:24] === ref_word_i[31:24]) ? "MATCH" : "MISMATCH");
        $error("    [23:16] DUT=0x%02X REF=0x%02X %s", dut_word_i[23:16], ref_word_i[23:16],
               (dut_word_i[23:16] === ref_word_i[23:16]) ? "MATCH" : "MISMATCH");
        $error("    [15:8]  DUT=0x%02X REF=0x%02X %s", dut_word_i[15:8], ref_word_i[15:8],
               (dut_word_i[15:8] === ref_word_i[15:8]) ? "MATCH" : "MISMATCH");
        $error("    [7:0]   DUT=0x%02X REF=0x%02X %s", dut_word_i[7:0], ref_word_i[7:0],
               (dut_word_i[7:0] === ref_word_i[7:0]) ? "MATCH" : "MISMATCH");
      end else if (verbose_i) begin
        // Match - only show if verbose enabled
        $display("[COMPRESSOR_CHECKER] MATCH at check %0d: 0x%08X", check_count + 1, ref_word_i);
      end
    end
  end

  //--------------------------------------------------------------------------
  // Output Assignments
  //--------------------------------------------------------------------------

  assign check_count_o    = check_count;
  assign mismatch_count_o = mismatch_count;

  //--------------------------------------------------------------------------
  // Valid Signal Monitoring
  //--------------------------------------------------------------------------

  // Warn if valid signals are mismatched (both should be synchronized)
  always_ff @(posedge clk_i) begin
    if (rstn_i && enable_i) begin
      if (ref_vld_i !== dut_vld) begin
        $warning("[COMPRESSOR_CHECKER] Valid signal mismatch: DUT=%b REF=%b", dut_vld, ref_vld_i);
      end
    end
  end

  //--------------------------------------------------------------------------
  // Final Report
  //--------------------------------------------------------------------------

  final begin
    // The Python compressor_checker_verify() summarizes check_count_o and
    // mismatch_count_o at end of test; each mismatch is reported above via $error.
  end

endmodule : Compressor_Checker
