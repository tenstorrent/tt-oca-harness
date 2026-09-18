// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Decorrelator Output Checker
//
// Description:
//   Compares DUT decorrelator outputs against reference model outputs for all
//   lanes. Uses reference model valid signal for synchronization timing.
//   Reports mismatches immediately using $error for simulation failure.
//
// Synchronization Strategy:
//   - Reference model is synchronized to DUT clock dividers (rtl_clk_divider_i)
//   - When ref model asserts valid, both DUT and ref should have new data
//   - Comparison happens on ref_vld_i pulse
//   - No separate DUT valid signal needed (DUT updates when divider reaches 0)
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module Decorrelator_Checker #(
  parameter int N_LANES = 12,      // Number of decorrelator lanes to check
  parameter int MAX_DEPTH = 29,    // Maximum decorrelator depth (DECOR_29 mode)
  parameter int SAFETY_MARGIN = 2  // Extra samples for safety (beyond calculated minimum)
) (
  // Clock and Reset
  input  logic                     clk_i,
  input  logic                     rstn_i,

  // Checker Control
  input  logic                     enable_i,      // Master enable switch (1=allow checking, 0=force disable)
  input  logic                     verbose_i,     // Verbose mode (1=show matches, 0=only mismatches)

  // RTL Monitor (to detect APB programming complete)
  input  logic [7:0]               rtl_clk_divider_i,  // RTL clock divider value (from DUT)
                                                       // Checker waits for != 0 before starting warmup
  input  logic [7:0]               byte_mask_i,        // DECORRELATOR_MASK register value (from DUT)
                                                       // Applied to ref only (DUT already masked in hardware)

  // DUT Decorrelator Outputs (per-lane, no valid signal)
  input  logic [N_LANES-1:0][7:0]  dut_bytes_i,   // DUT byte outputs

  // Reference Model Outputs (per-lane with common valid)
  input  logic [N_LANES-1:0][7:0]  ref_bytes_i,   // Reference model byte outputs
  input  logic                     ref_vld_i,     // Reference model valid (sync timing)

  // Status Outputs (for Python test checking)
  output logic [31:0]              check_count_o,     // Total number of checks performed
  output logic [31:0]              mismatch_count_o,  // Number of cycles with mismatches
  output logic                     warmup_done_o      // Warm-up complete, checking active
);

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  // Warm-up control
  logic        rtl_programmed;     // RTL clock divider has been programmed (rtl_clk_divider_i != 0)
  logic [31:0] warmup_count;       // Count samples during warm-up
  logic [31:0] warmup_target;      // Required samples for warmup (calculated from clk_divider)
  logic        warmup_done;        // Warm-up complete flag
  logic        checking_enabled;   // Internal enable (master enable AND warm-up done)

  // Statistics counters
  logic [31:0] check_count;
  logic [31:0] mismatch_count;
  integer lane_mismatch_count [N_LANES];

  // Connect internal counters to output ports
  assign check_count_o = check_count;
  assign mismatch_count_o = mismatch_count;
  assign warmup_done_o = warmup_done;

  // Internal checking enable: master enable switch AND warm-up complete
  assign checking_enabled = enable_i && warmup_done;

  //--------------------------------------------------------------------------
  // Warm-up Logic
  //--------------------------------------------------------------------------
  // Three-stage warmup process:
  // 1. Wait for rtl_clk_divider_i != 0 (APB write to DECORRELATOR_CTRL complete)
  // 2. Calculate required warmup samples: ceil(MAX_DEPTH / (clk_divider+1)) + SAFETY_MARGIN
  //    - Example: clk_div=0x7 (div-8):  ceil(29/8) + 2 = 4 + 2 = 6 samples
  //    - Example: clk_div=0x63 (div-100): ceil(29/100) + 2 = 1 + 2 = 3 samples
  // 3. Wait for calculated number of valid pulses (shift register fills with data)
  // 4. Enable checking (warmup_done = 1)
  //
  // This avoids false alarms from:
  // - Comparing before RTL is configured
  // - Comparing during X→valid transitions at simulation start
  // - Comparing before decorrelator shift register is filled

  always @(posedge clk_i or negedge rstn_i) begin
    if (!rstn_i) begin
      rtl_programmed <= 1'b0;
      warmup_count   <= 0;
      warmup_target  <= 0;
      warmup_done    <= 1'b0;
    end else begin
      // Stage 1: Detect RTL programming (DECORRELATOR_CTRL written via APB)
      if (!rtl_programmed && rtl_clk_divider_i != 8'h00) begin
        int actual_division;
        int required_samples;

        rtl_programmed <= 1'b1;

        // Calculate actual clock division (register value + 1)
        actual_division = int'(rtl_clk_divider_i) + 1;

        // Calculate minimum samples needed: ceil(MAX_DEPTH / actual_division)
        // Formula: (MAX_DEPTH + actual_division - 1) / actual_division
        required_samples = (MAX_DEPTH + actual_division - 1) / actual_division;

        // Add safety margin
        warmup_target <= required_samples + SAFETY_MARGIN;

        $display("[DECOR_CHK] RTL programmed (clk_divider=0x%02X, div-%0d) @ time=%0t",
                 rtl_clk_divider_i, actual_division, $time);
        $display("[DECOR_CHK] Warmup target: %0d samples (min=%0d + margin=%0d)",
                 required_samples + SAFETY_MARGIN, required_samples, SAFETY_MARGIN);
      end

      // Stage 2: Count warmup samples after RTL programmed
      if (rtl_programmed && ref_vld_i && !warmup_done) begin
        warmup_count <= warmup_count + 1;
        if (warmup_count >= warmup_target - 1) begin
          warmup_done <= 1'b1;
          $display("[DECOR_CHK] Warm-up complete after %0d samples - checking enabled @ time=%0t",
                   warmup_target, $time);
        end
      end
    end
  end

  //--------------------------------------------------------------------------
  // Synchronization and Comparison
  //--------------------------------------------------------------------------
  // Strategy: Use ref_vld_i as the synchronization point
  // When ref model says valid, compare DUT output with ref output
  // Both should have updated simultaneously since ref model tracks DUT dividers

  genvar gi;
  generate
    for (gi = 0; gi < N_LANES; gi++) begin : gen_lane_check

      // Check on reference model valid pulse (only after warm-up)
      always @(posedge clk_i) begin
        if (rstn_i && checking_enabled && ref_vld_i) begin
          // Apply byte mask to reference model only (DUT already masked in hardware)
          logic [7:0] ref_masked;

          ref_masked = ref_bytes_i[gi] & byte_mask_i;

          // Compare DUT (already masked) with masked reference output
          if (dut_bytes_i[gi] !== ref_masked) begin
            $error(
                "[DECOR_CHK] Lane %0d: MISMATCH! DUT=0x%02X, REF=0x%02X (mask=0x%02X) @ time=%0t",
                gi, dut_bytes_i[gi], ref_masked, byte_mask_i, $time);
            lane_mismatch_count[gi]++;
          end else begin
            // Report successful matches if verbose mode enabled
            if (verbose_i) begin
              $display(
                  "[DECOR_CHK] Lane %0d: MATCH! DUT=0x%02X, REF=0x%02X (mask=0x%02X) @ time=%0t",
                  gi, dut_bytes_i[gi], ref_masked, byte_mask_i, $time);
            end
          end
        end
      end

      // Initialize per-lane mismatch counter
      initial begin
        lane_mismatch_count[gi] = 0;
      end
    end
  endgenerate

  //--------------------------------------------------------------------------
  // Statistics Tracking (internal only)
  //--------------------------------------------------------------------------

  initial begin
    check_count = 0;
    mismatch_count = 0;
  end

  // Count checks (only after warm-up)
  always @(posedge clk_i) begin
    if (rstn_i && checking_enabled && ref_vld_i) begin
      integer cycle_mismatch;
      logic [7:0] ref_masked;
      check_count++;

      // Check if any lane mismatched this cycle (apply mask to ref only, DUT already masked)
      cycle_mismatch = 0;
      for (int lane = 0; lane < N_LANES; lane++) begin
        ref_masked = ref_bytes_i[lane] & byte_mask_i;
        if (dut_bytes_i[lane] !== ref_masked) begin
          cycle_mismatch = 1;
          break;
        end
      end
      if (cycle_mismatch) begin
        mismatch_count++;
      end
    end
  end

  //--------------------------------------------------------------------------
  // End-of-simulation summary
  //--------------------------------------------------------------------------
  // The Python test summarizes and fails on mismatches via decor_checker_verify(),
  // reading check_count_o and mismatch_count_o; each mismatch is reported above
  // with $error as it occurs.

  //--------------------------------------------------------------------------
  // SVA Assertions (optional, enable with +define+DECOR_CHECKER_ASSERTIONS)
  //--------------------------------------------------------------------------

`ifdef DECOR_CHECKER_ASSERTIONS

  // Assert that data should match when reference valid
  generate
    for (gi = 0; gi < N_LANES; gi++) begin : gen_assert_match

      property p_data_match;
        @(posedge clk_i) disable iff (~rstn_i || ~enable_i)
                (ref_vld_i) |-> (dut_bytes_i[gi] === ref_bytes_i[gi]);
      endproperty

      a_data_match :
      assert property (p_data_match)
      else
        $error(
            "[SVA] Lane %0d: Data mismatch - DUT=0x%02X, REF=0x%02X",
            gi,
            dut_bytes_i[gi],
            ref_bytes_i[gi]
        );
    end
  endgenerate

`endif  // DECOR_CHECKER_ASSERTIONS

endmodule : Decorrelator_Checker
