// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`timescale 1ns / 1ps

//==============================================================================
// DECORRELATOR REFERENCE MODEL (TESTBENCH ONLY - NOT FOR SYNTHESIS)
//==============================================================================
// PURPOSE:     Generate golden entropy data for verification and comparison
// SCOPE:       Simulation-only behavioral model
// LOCATION:    Testbench infrastructure (models/decorrelator/)
//
// IMPORTANT:   This is NOT the synthesizable RTL design!
//              The synthesizable decorrelator is
//              hw/ip/entropy_source/rtl/entropy_decorrelator.sv.
//
// DESCRIPTION:
//   - For each lane, maintains a 29-bit shift register (DEPTH bits wide)
//   - New input bit always enters at sr[i][DEPTH-1] (bit 28 for DEPTH=29)
//   - The 8-bit output sample is always taken from sr[i][7:0]
//   - Modes differ only in how the feedback bit is computed:
//       * DECOR modes: XOR feedback tap (true decorrelator)
//       * BYPASS mode: no feedback, raw shift (set-only)
//       * LFSR modes: LFSR-style feedback but still stored in sr[]
//   - Captures output when RTL clock divider reloads (probed from DUT)
//   - Supports 5 operating modes for different decorrelation algorithms
//   - Used to generate golden reference data for DUT comparison
//   - Sampling timing automatically follows RTL divider (any period supported)
//   - **PER-LANE BYPASS**: bypass_mask_i allows individual lanes to bypass
//
// MODES:
//   0: DECOR_29  - 29-deep XOR decorrelator (spec default)
//   1: DECOR_7   - 7-deep XOR decorrelator (shallow variant)
//   2: BYPASS    - No decorrelation, raw bits (debug)
//   3: LFSR_29   - 29-bit Fibonacci LFSR (x^29 + x^2 + 1)
//   4: LFSR_7    - 7-bit Fibonacci LFSR (x^7 + x^6 + 1)
//
// BYPASS MASK (Per-Lane Control):
//   bypass_mask_i[i] = 1: Lane i uses BYPASS mode (regardless of mode_i)
//   bypass_mask_i[i] = 0: Lane i uses mode_i setting
//   Examples:
//     0x000 - All lanes decorrelate (pure mode)
//     0xFFF - All lanes bypass (pure bypass mode)
//     0x001 - Lane 0 bypass, others decorrelate (mixed mode)
//     0xAAA - Even lanes bypass, odd lanes decorrelate (mixer mode)
//
// SHIFT DIRECTION:
//   0: SHIFT_RIGHT - Input at [28], output at [7:0], shift right (28→27→...→0)
//   1: SHIFT_LEFT  - Input at [0], output at [28:21], shift left (0→1→2→...→28)
//==============================================================================

module Serial_Decorrelator_RefModel #(
  parameter int N              = 16,
  parameter int DEPTH          = 29    // default decorrelator depth
) (
  input  logic                 clk_i,
  input  logic                 rstn_i,
  // Input stream
  input  logic [N-1:0]         bit_i,     // per-lane input bit each cycle
  input  logic [N-1:0]         vld_i,     // per-lane valid; tie to '1 if not used
  // Configuration
  input  logic [2:0]           mode_i,            // 0: DECOR_29 (default), 1: DECOR_7, 2: BYPASS, 3: LFSR_29, 4: LFSR_7
  input  logic                 shift_dir_i,       // 0: shift right (in[28]→out[7:0]), 1: shift left (in[0]→out[28:21])
  input  logic [N-1:0]         bypass_mask_i,     // Per-lane bypass control: 1=bypass, 0=use mode_i
  // RTL clock divider probe (for synchronization with actual RTL timing)
  input  logic [7:0]           rtl_clk_divider_i, // Connect to DUT's clk_divider (samples when == SAMPLE_PERIOD-1)
  // Outputs
  output logic                 sample_vld_o,
  output logic [N-1:0][7:0]    bytes_o            // per-lane 8-bit sample, captured per effective sample period
);
  // Shift registers: sr[i][DEPTH-1] is the newest bit; sr[i][0] is the oldest bit
  logic [DEPTH-1:0] sr [N];

  // Effective configuration
  logic [5:0]        depth_eff;         // valid when in DECOR modes
  logic [2:0]        mode_q;
  logic              shift_dir_q;        // registered shift direction

  // Sample pulse generation (synchronized with RTL clk_divider for ALL modes)
  // RTL outputs when clk_divider == SAMPLE_PERIOD-1 (e.g., 63 for ÷64, 7 for ÷8)
  logic sample_pulse_d, sample_pulse_q;
  logic [7:0] rtl_clk_divider_q;

  // Mode register and effective config
  // NOTE: Defaults come from test_config.py via decor_cfg interface
  always_ff @(posedge clk_i or negedge rstn_i) begin
    if (!rstn_i) begin
      mode_q <= 3'd0;
      shift_dir_q <= 1'b1;  // Default to SHIFT_LEFT (matches interface default)
    end else begin
      mode_q <= mode_i;
      shift_dir_q <= shift_dir_i;
    end
  end
  always_comb begin
    unique case (mode_q)
      3'd1: depth_eff = 6'd7;      // DECOR_7
      default: depth_eff = DEPTH[5:0];
    endcase
  end

  // Update logic
  genvar i;
  generate
    for (i = 0; i < N; i++) begin : gen_lane
      always_ff @(posedge clk_i or negedge rstn_i) begin
        if (!rstn_i) begin
          sr[i] <= '0;
        end else begin
          if (vld_i[i]) begin
            // Shift direction control (applies to all modes)
            // shift_dir_q == 0: SHIFT_RIGHT - Input at [28], output [7:0], shift right
            // shift_dir_q == 1: SHIFT_LEFT  - Input at [0], output [28:21], shift left
            //
            // Per-lane effective mode: bypass_mask_i[i] = 1 forces BYPASS,
            // 0 uses mode_q.
            if (shift_dir_q == 1'b0) begin
              // SHIFT_RIGHT: sr[i][DEPTH-1] is newest, sr[i][0] is oldest
              unique case (bypass_mask_i[i] ? 3'd2 : mode_q)
                3'd0,  // DECOR_29: XOR feedback from oldest bit
                3'd1: begin  // DECOR_7: XOR feedback from tap DEPTH-depth_eff
                  sr[i] <= {(bit_i[i] ^ sr[i][DEPTH-depth_eff]), sr[i][DEPTH-1:1]};
                end
                3'd2: begin  // BYPASS: no feedback, raw shift
                  sr[i] <= {bit_i[i], sr[i][DEPTH-1:1]};
                end
                3'd3: begin  // LFSR_29: x^29 + x^2 + 1, feedback from [28] and [1]
                  sr[i] <= {(sr[i][DEPTH-1] ^ sr[i][1] ^ bit_i[i]), sr[i][DEPTH-1:1]};
                end
                3'd4: begin  // LFSR_7: x^7 + x^6 + 1, feedback uses bits [6] and [5]
                  sr[i] <= {(sr[i][6] ^ sr[i][5] ^ bit_i[i]), sr[i][DEPTH-1:1]};
                end
                default: begin
                  // Default to simple shift if mode is invalid
                  sr[i] <= {bit_i[i], sr[i][DEPTH-1:1]};
                end
              endcase
            end else begin
              // SHIFT_LEFT: sr[i][0] is newest, sr[i][DEPTH-1] is oldest
              unique case (bypass_mask_i[i] ? 3'd2 : mode_q)
                3'd0,  // DECOR_29: XOR feedback from oldest bit
                3'd1: begin  // DECOR_7: XOR feedback from tap depth_eff-1
                  sr[i] <= {sr[i][DEPTH-2:0], (bit_i[i] ^ sr[i][depth_eff-1])};
                end
                3'd2: begin  // BYPASS: no feedback, raw shift
                  sr[i] <= {sr[i][DEPTH-2:0], bit_i[i]};
                end
                3'd3: begin  // LFSR_29: x^29 + x^2 + 1, feedback from [0] and [27]
                  sr[i] <= {sr[i][DEPTH-2:0], (sr[i][0] ^ sr[i][DEPTH-2] ^ bit_i[i])};
                end
                3'd4: begin  // LFSR_7: x^7 + x^6 + 1, feedback uses bits [0] and [1]
                  sr[i] <= {sr[i][DEPTH-2:0], (sr[i][0] ^ sr[i][1] ^ bit_i[i])};
                end
                default: begin
                  // Default to simple shift if mode is invalid
                  sr[i] <= {sr[i][DEPTH-2:0], bit_i[i]};
                end
              endcase
            end
          end
        end
      end
    end
  endgenerate

  // Sample pulse generation synchronized with RTL clock divider (ALL modes)
  // RTL decorrelator outputs when clk_divider reaches 0
  // Examples:
  //   - SAMPLE_CLK_DIV=63 (÷64): RTL outputs when clk_divider==0
  //   - SAMPLE_CLK_DIV=7  (÷8):  RTL outputs when clk_divider==0
  // Sampling timing comes entirely from probing RTL divider, not from any fixed parameter
  always_comb begin
    sample_pulse_d = 1'b0;
    // Detect when divider reaches 0 (sample output event)
    if (rtl_clk_divider_i == 8'd0) begin
      sample_pulse_d = 1'b1;
    end
  end

  always_ff @(posedge clk_i or negedge rstn_i) begin
    if (!rstn_i) begin
      rtl_clk_divider_q <= '0;
      sample_pulse_q    <= 1'b0;
      sample_vld_o      <= 1'b0;
      bytes_o           <= '0;
    end else begin
      rtl_clk_divider_q <= rtl_clk_divider_i;  // Register for edge detection
      sample_pulse_q    <= sample_pulse_d;

      // Pulse sample_vld_o for one cycle
      sample_vld_o      <= sample_pulse_d;
      if (sample_pulse_d) begin
        // Capture per selected shift direction
        integer j;
        for (j = 0; j < N; j++) begin
          if (shift_dir_q == 1'b0) begin
            // SHIFT_RIGHT: Output window is sr[j][7:0]
            bytes_o[j] <= sr[j][7:0];
          end else begin
            // SHIFT_LEFT: Output window is sr[j][28:21]
            bytes_o[j] <= sr[j][28:21];
          end
        end
      end
    end
  end

endmodule
