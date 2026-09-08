// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Debug Signal Aliases for nWave Visibility
//
// This file flattens nested SystemVerilog structs from the register interface
// into simple logic signals that nWave can properly display.
//
// nWave has poor support for viewing nested structs, often showing concatenated
// names like "STATUSreg_in.STATUS" or failing to display them at all.
//
// Usage: `include this file in your testbench top module
//------------------------------------------------------------------------------

// Debug signals for register interface visibility
/* verilator lint_off UNUSED */
logic [31:0] debug_component_id;
logic [31:0] debug_ctrl;
logic        debug_ctrl_reserved_0;      // Reserved bit 0, reads zero
logic        debug_ctrl_autotune_enable; // CTRL.AUTOTUNE_ENABLE bit
logic [9:0]  debug_ctrl_downsample_rate; // CTRL.DOWNSAMPLE_RATE field
logic [31:0] debug_debug_ctrl;
logic [31:0] debug_intr_status;
logic [31:0] debug_intr_enable;
logic [31:0] debug_fifo_status;
logic [31:0] debug_fifo_rdata;
logic [31:0] debug_health_test_ctrl;
logic [31:0] debug_markov_thresholds;
logic [31:0] debug_health_test_status;
logic [31:0] debug_repetition_count;
logic [31:0] debug_apt_proportion_1bit;
logic [31:0] debug_apt_proportion_lo;
logic [31:0] debug_ring_osc_enable;
logic [31:0] debug_ring_osc_tune;
logic [31:0] debug_ring_osc_ctrl;
logic [31:0] debug_decorrelator_ctrl;
logic [31:0] debug_decorrelator_mask;

// Additional debug signals for internal DUT state
logic [11:0] debug_ring_osc_enable_wire;  // Actual enable signal from reg_out
logic [7:0]  debug_clk_divider [12];      // Clock dividers from all 12 decorrelator lanes
logic [31:0] debug_entropy_stream_data;   // Entropy stream data output
logic        debug_entropy_stream_vld;    // Entropy stream valid output

// Decorrelator reference model byte outputs per channel (separate signals for nWave)
logic [7:0]  debug_decorr_refmodel_bytes_0;
logic [7:0]  debug_decorr_refmodel_bytes_1;
logic [7:0]  debug_decorr_refmodel_bytes_2;
logic [7:0]  debug_decorr_refmodel_bytes_3;
logic [7:0]  debug_decorr_refmodel_bytes_4;
logic [7:0]  debug_decorr_refmodel_bytes_5;
logic [7:0]  debug_decorr_refmodel_bytes_6;
logic [7:0]  debug_decorr_refmodel_bytes_7;
logic [7:0]  debug_decorr_refmodel_bytes_8;
logic [7:0]  debug_decorr_refmodel_bytes_9;
logic [7:0]  debug_decorr_refmodel_bytes_10;
logic [7:0]  debug_decorr_refmodel_bytes_11;

// Flatten COMPONENT_ID register (Read-Only, not in reg_out - hardwired)
assign debug_component_id = 32'h0;  // Not accessible in reg_out interface

// Flatten CTRL register
assign debug_ctrl[0]      = 1'b0;
assign debug_ctrl[1] = dut.reg_out.CTRL.MODULE_ENABLE.value;
assign debug_ctrl[3:2] = 2'h0;
assign debug_ctrl[4]      = dut.reg_out.CTRL.AUTOTUNE_ENABLE.value;
assign debug_ctrl[7:5] = 3'h0;
assign debug_ctrl[8] = dut.reg_out.CTRL.BYPASS_ENTROPY_COMPRESSOR.value;
assign debug_ctrl[15:9] = 7'h0;
assign debug_ctrl[25:16]  = dut.reg_out.CTRL.DOWNSAMPLE_RATE.value;
assign debug_ctrl[27:26] = 2'h0;
assign debug_ctrl[28] = dut.reg_out.CTRL.SHA256_WHITENING_ENABLE.value;
assign debug_ctrl[31:29] = 3'h0;

// CTRL register individual fields (for easier Verdi visualization)
assign debug_ctrl_reserved_0      = 1'b0;
assign debug_ctrl_autotune_enable = dut.reg_out.CTRL.AUTOTUNE_ENABLE.value;
assign debug_ctrl_downsample_rate = dut.reg_out.CTRL.DOWNSAMPLE_RATE.value;

// Flatten DEBUG_CTRL register
assign debug_debug_ctrl[7:0] = dut.reg_out.DEBUG_CTRL.SELECT_SIGNAL.value;
assign debug_debug_ctrl[10:8]  = dut.reg_out.DEBUG_CTRL.SELECT_FREQ_DIV.value;
assign debug_debug_ctrl[31:11] = 21'h0;

// Flatten INTR_STATUS register (Write-One-to-Clear)
// Note: PeakRDL generates only a combined .intr signal for level intr fields
assign debug_intr_status[0]       = dut.reg_out.INTR_STATUS.intr;
assign debug_intr_status[31:1]    = 31'h0;

// Flatten INTR_ENABLE register (not in reg_out - hw=na, no hardware access)
assign debug_intr_enable = 32'h0;  // Not accessible in reg_out interface

// Flatten FIFO_STATUS register
assign debug_fifo_status[6:0]     = dut.reg_in.FIFO_STATUS.LEVEL.next;
assign debug_fifo_status[7]       = 1'h0;
assign debug_fifo_status[12:8]    = dut.reg_in.FIFO_STATUS.WPTR.next;
assign debug_fifo_status[15:13]   = 3'h0;
assign debug_fifo_status[20:16]   = dut.reg_in.FIFO_STATUS.RPTR.next;
assign debug_fifo_status[31:21]   = 11'h0;

// Flatten FIFO_RDATA register
assign debug_fifo_rdata[31:0]     = dut.reg_in.FIFO_RDATA.rd_data;

// Flatten HEALTH_TEST_CTRL register
assign debug_health_test_ctrl[7:0]   = dut.reg_out.HEALTH_TEST_CTRL.ENABLE.value;
assign debug_health_test_ctrl[15:8]  = dut.reg_out.HEALTH_TEST_CTRL.REPETITION_LIMIT.value;
assign debug_health_test_ctrl[31:16] = 16'h0;

// Flatten MARKOV_TEST_PROB_THRESHOLDS register
assign debug_markov_thresholds[15:0]  = dut.reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_01_THRESHOLD.value;
assign debug_markov_thresholds[31:16] = dut.reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_10_THRESHOLD.value;

// Flatten HEALTH_TEST_STATUS register
assign debug_health_test_status[7:0]  = dut.reg_in.HEALTH_TEST_STATUS.HEALTH_STATUS.next;
assign debug_health_test_status[31:8] = 24'h0;

// Flatten REPETITION_TEST_COUNT register
assign debug_repetition_count[15:0] = dut.reg_in.REPETITION_TEST_COUNT.REPETITION_COUNT.next;
assign debug_repetition_count[31:16] = 16'h0;

// Flatten APT high and low limit registers.
assign debug_apt_proportion_1bit[15:0] = dut.reg_out.APT_PROPORTION_1BIT.LIMIT.value;
assign debug_apt_proportion_1bit[31:16] = 16'h0;
assign debug_apt_proportion_lo[15:0] = dut.reg_out.APT_PROPORTION_LO.LIMIT.value;
assign debug_apt_proportion_lo[31:16] = 16'h0;

// Flatten RING_OSC_ENABLE register
assign debug_ring_osc_enable[11:0]  = dut.reg_out.RING_OSC_ENABLE.ENABLE.value;
assign debug_ring_osc_enable[23:12] = dut.reg_out.RING_OSC_ENABLE.SAMPLE_CLK_ENABLE.value;
assign debug_ring_osc_enable[31:24] = 8'h0;

// Flatten RING_OSC_TUNE register
assign debug_ring_osc_tune[11:0]  = dut.reg_out.RING_OSC_TUNE.DETUNE.value;
assign debug_ring_osc_tune[23:12] = dut.reg_out.RING_OSC_TUNE.SAMPLE_CLK_DETUNE.value;
assign debug_ring_osc_tune[31:24] = 8'h0;

// Flatten RING_OSC_CTRL register
assign debug_ring_osc_ctrl[11:0]  = dut.reg_out.RING_OSC_CTRL.SAMPLE_CLK_SELECT.value;
assign debug_ring_osc_ctrl[31:12] = 20'h0;

// Flatten DECORRELATOR_CTRL register
assign debug_decorrelator_ctrl[11:0]  = dut.reg_out.DECORRELATOR_CTRL.BYPASS.value;
assign debug_decorrelator_ctrl[31:12] = dut.reg_out.DECORRELATOR_CTRL.SAMPLE_CLK_DIV.value;

// Flatten DECORRELATOR_MASK register
assign debug_decorrelator_mask[7:0]   = dut.reg_out.DECORRELATOR_MASK.ENTROPY_BYTE_MASK.value;
assign debug_decorrelator_mask[31:8]  = 24'h0;

// Additional internal signals (post-register, actual wire to design)
assign debug_ring_osc_enable_wire = dut.reg_out.RING_OSC_ENABLE.ENABLE.value;

// Entropy stream outputs (top-level DUT outputs)
assign debug_entropy_stream_data = entropy_stream_data;
assign debug_entropy_stream_vld  = entropy_stream_vld;

// Clock dividers from all decorrelator lanes (for synchronization verification)
genvar debug_gi;
generate
  for (debug_gi = 0; debug_gi < 12; debug_gi++) begin : gen_debug_clk_divider
    assign debug_clk_divider[debug_gi] = dut.egen.gen_ecmplx[debug_gi].gen_inst.dcor.clk_divider;
  end
endgenerate

// Detune status from all generator lanes (for autotune verification)
// When autotune is enabled, this shows the FSM-controlled detune state, not the register value
logic debug_detune[12];
generate
  for (debug_gi = 0; debug_gi < 12; debug_gi++) begin : gen_debug_detune
    assign debug_detune[debug_gi] = dut.egen.gen_ecmplx[debug_gi].gen_inst.detune;
  end
endgenerate

// Decorrelator reference model byte outputs per channel
assign debug_decorr_refmodel_bytes_0  = u_decorrelator_refmodel.bytes_o[0];
assign debug_decorr_refmodel_bytes_1  = u_decorrelator_refmodel.bytes_o[1];
assign debug_decorr_refmodel_bytes_2  = u_decorrelator_refmodel.bytes_o[2];
assign debug_decorr_refmodel_bytes_3  = u_decorrelator_refmodel.bytes_o[3];
assign debug_decorr_refmodel_bytes_4  = u_decorrelator_refmodel.bytes_o[4];
assign debug_decorr_refmodel_bytes_5  = u_decorrelator_refmodel.bytes_o[5];
assign debug_decorr_refmodel_bytes_6  = u_decorrelator_refmodel.bytes_o[6];
assign debug_decorr_refmodel_bytes_7  = u_decorrelator_refmodel.bytes_o[7];
assign debug_decorr_refmodel_bytes_8  = u_decorrelator_refmodel.bytes_o[8];
assign debug_decorr_refmodel_bytes_9  = u_decorrelator_refmodel.bytes_o[9];
assign debug_decorr_refmodel_bytes_10 = u_decorrelator_refmodel.bytes_o[10];
assign debug_decorr_refmodel_bytes_11 = u_decorrelator_refmodel.bytes_o[11];

// Decorrelator checker control (from decor_cfg interface)
logic debug_decor_checker_enable;
logic debug_decor_checker_verbose;
assign debug_decor_checker_enable  = decor_cfg.checker_enable;
assign debug_decor_checker_verbose = decor_cfg.checker_verbose;

// Decorrelator checker statistics (internal to checker module, probe for waveforms)
integer debug_decor_check_count;
integer debug_decor_mismatch_count;
assign debug_decor_check_count    = u_decorrelator_checker.check_count;
assign debug_decor_mismatch_count = u_decorrelator_checker.mismatch_count;

// Decorrelator reference model 29-bit shift registers (per channel, for nWave visibility)
// These show the internal state of the decorrelator model
logic [28:0] debug_decor_sr_0;
logic [28:0] debug_decor_sr_1;
logic [28:0] debug_decor_sr_2;
logic [28:0] debug_decor_sr_3;
logic [28:0] debug_decor_sr_4;
logic [28:0] debug_decor_sr_5;
logic [28:0] debug_decor_sr_6;
logic [28:0] debug_decor_sr_7;
logic [28:0] debug_decor_sr_8;
logic [28:0] debug_decor_sr_9;
logic [28:0] debug_decor_sr_10;
logic [28:0] debug_decor_sr_11;

assign debug_decor_sr_0  = u_decorrelator_refmodel.sr[0];
assign debug_decor_sr_1  = u_decorrelator_refmodel.sr[1];
assign debug_decor_sr_2  = u_decorrelator_refmodel.sr[2];
assign debug_decor_sr_3  = u_decorrelator_refmodel.sr[3];
assign debug_decor_sr_4  = u_decorrelator_refmodel.sr[4];
assign debug_decor_sr_5  = u_decorrelator_refmodel.sr[5];
assign debug_decor_sr_6  = u_decorrelator_refmodel.sr[6];
assign debug_decor_sr_7  = u_decorrelator_refmodel.sr[7];
assign debug_decor_sr_8  = u_decorrelator_refmodel.sr[8];
assign debug_decor_sr_9  = u_decorrelator_refmodel.sr[9];
assign debug_decor_sr_10 = u_decorrelator_refmodel.sr[10];
assign debug_decor_sr_11 = u_decorrelator_refmodel.sr[11];

// Decorrelator reference model feedback bits (per channel, for nWave visibility)
// Feedback bit calculation depends on mode:
//   DECOR_29/7: XOR from tap position (shift_dir dependent)
//   BYPASS: no feedback (always 0)
//   LFSR_29: XOR of sr[28] and sr[1] (right shift) or sr[0] and sr[27] (left shift)
//   LFSR_7: XOR of sr[6] and sr[5] (right shift) or sr[0] and sr[1] (left shift)
logic debug_decor_fb_0;
logic debug_decor_fb_1;
logic debug_decor_fb_2;
logic debug_decor_fb_3;
logic debug_decor_fb_4;
logic debug_decor_fb_5;
logic debug_decor_fb_6;
logic debug_decor_fb_7;
logic debug_decor_fb_8;
logic debug_decor_fb_9;
logic debug_decor_fb_10;
logic debug_decor_fb_11;

// Compute feedback bits based on current mode and shift direction
// This replicates the feedback calculation from the decorrelator model for visibility
generate
  for (debug_gi = 0; debug_gi < 12; debug_gi++) begin : gen_debug_feedback
    always_comb begin
      logic [5:0] depth_eff;
      logic [2:0] mode;
      logic shift_dir;

      mode = u_decorrelator_refmodel.mode_q;
      shift_dir = u_decorrelator_refmodel.shift_dir_q;

      // Determine effective depth based on mode
      unique case (mode)
        3'd1: depth_eff = 6'd7;      // DECOR_7
        default: depth_eff = 6'd29;  // DECOR_29, LFSR modes
      endcase

      // Calculate feedback based on mode and shift direction
      unique case (mode)
        3'd0,  // DECOR_29
        3'd1: begin  // DECOR_7
          if (shift_dir == 1'b0) begin
            // SHIFT_RIGHT: feedback from sr[29-depth_eff]
            unique case (debug_gi)
              0:  debug_decor_fb_0  = debug_decor_sr_0[29-depth_eff];
              1:  debug_decor_fb_1  = debug_decor_sr_1[29-depth_eff];
              2:  debug_decor_fb_2  = debug_decor_sr_2[29-depth_eff];
              3:  debug_decor_fb_3  = debug_decor_sr_3[29-depth_eff];
              4:  debug_decor_fb_4  = debug_decor_sr_4[29-depth_eff];
              5:  debug_decor_fb_5  = debug_decor_sr_5[29-depth_eff];
              6:  debug_decor_fb_6  = debug_decor_sr_6[29-depth_eff];
              7:  debug_decor_fb_7  = debug_decor_sr_7[29-depth_eff];
              8:  debug_decor_fb_8  = debug_decor_sr_8[29-depth_eff];
              9:  debug_decor_fb_9  = debug_decor_sr_9[29-depth_eff];
              10: debug_decor_fb_10 = debug_decor_sr_10[29-depth_eff];
              11: debug_decor_fb_11 = debug_decor_sr_11[29-depth_eff];
            endcase
          end else begin
            // SHIFT_LEFT: feedback from sr[depth_eff-1]
            unique case (debug_gi)
              0:  debug_decor_fb_0  = debug_decor_sr_0[depth_eff-1];
              1:  debug_decor_fb_1  = debug_decor_sr_1[depth_eff-1];
              2:  debug_decor_fb_2  = debug_decor_sr_2[depth_eff-1];
              3:  debug_decor_fb_3  = debug_decor_sr_3[depth_eff-1];
              4:  debug_decor_fb_4  = debug_decor_sr_4[depth_eff-1];
              5:  debug_decor_fb_5  = debug_decor_sr_5[depth_eff-1];
              6:  debug_decor_fb_6  = debug_decor_sr_6[depth_eff-1];
              7:  debug_decor_fb_7  = debug_decor_sr_7[depth_eff-1];
              8:  debug_decor_fb_8  = debug_decor_sr_8[depth_eff-1];
              9:  debug_decor_fb_9  = debug_decor_sr_9[depth_eff-1];
              10: debug_decor_fb_10 = debug_decor_sr_10[depth_eff-1];
              11: debug_decor_fb_11 = debug_decor_sr_11[depth_eff-1];
            endcase
          end
        end
        3'd2: begin  // BYPASS: no feedback
          unique case (debug_gi)
            0:  debug_decor_fb_0  = 1'b0;
            1:  debug_decor_fb_1  = 1'b0;
            2:  debug_decor_fb_2  = 1'b0;
            3:  debug_decor_fb_3  = 1'b0;
            4:  debug_decor_fb_4  = 1'b0;
            5:  debug_decor_fb_5  = 1'b0;
            6:  debug_decor_fb_6  = 1'b0;
            7:  debug_decor_fb_7  = 1'b0;
            8:  debug_decor_fb_8  = 1'b0;
            9:  debug_decor_fb_9  = 1'b0;
            10: debug_decor_fb_10 = 1'b0;
            11: debug_decor_fb_11 = 1'b0;
          endcase
        end
        3'd3: begin  // LFSR_29
          if (shift_dir == 1'b0) begin
            // SHIFT_RIGHT: fb = sr[28] ^ sr[1]
            unique case (debug_gi)
              0:  debug_decor_fb_0  = debug_decor_sr_0[28]  ^ debug_decor_sr_0[1];
              1:  debug_decor_fb_1  = debug_decor_sr_1[28]  ^ debug_decor_sr_1[1];
              2:  debug_decor_fb_2  = debug_decor_sr_2[28]  ^ debug_decor_sr_2[1];
              3:  debug_decor_fb_3  = debug_decor_sr_3[28]  ^ debug_decor_sr_3[1];
              4:  debug_decor_fb_4  = debug_decor_sr_4[28]  ^ debug_decor_sr_4[1];
              5:  debug_decor_fb_5  = debug_decor_sr_5[28]  ^ debug_decor_sr_5[1];
              6:  debug_decor_fb_6  = debug_decor_sr_6[28]  ^ debug_decor_sr_6[1];
              7:  debug_decor_fb_7  = debug_decor_sr_7[28]  ^ debug_decor_sr_7[1];
              8:  debug_decor_fb_8  = debug_decor_sr_8[28]  ^ debug_decor_sr_8[1];
              9:  debug_decor_fb_9  = debug_decor_sr_9[28]  ^ debug_decor_sr_9[1];
              10: debug_decor_fb_10 = debug_decor_sr_10[28] ^ debug_decor_sr_10[1];
              11: debug_decor_fb_11 = debug_decor_sr_11[28] ^ debug_decor_sr_11[1];
            endcase
          end else begin
            // SHIFT_LEFT: fb = sr[0] ^ sr[27]
            unique case (debug_gi)
              0:  debug_decor_fb_0  = debug_decor_sr_0[0]  ^ debug_decor_sr_0[27];
              1:  debug_decor_fb_1  = debug_decor_sr_1[0]  ^ debug_decor_sr_1[27];
              2:  debug_decor_fb_2  = debug_decor_sr_2[0]  ^ debug_decor_sr_2[27];
              3:  debug_decor_fb_3  = debug_decor_sr_3[0]  ^ debug_decor_sr_3[27];
              4:  debug_decor_fb_4  = debug_decor_sr_4[0]  ^ debug_decor_sr_4[27];
              5:  debug_decor_fb_5  = debug_decor_sr_5[0]  ^ debug_decor_sr_5[27];
              6:  debug_decor_fb_6  = debug_decor_sr_6[0]  ^ debug_decor_sr_6[27];
              7:  debug_decor_fb_7  = debug_decor_sr_7[0]  ^ debug_decor_sr_7[27];
              8:  debug_decor_fb_8  = debug_decor_sr_8[0]  ^ debug_decor_sr_8[27];
              9:  debug_decor_fb_9  = debug_decor_sr_9[0]  ^ debug_decor_sr_9[27];
              10: debug_decor_fb_10 = debug_decor_sr_10[0] ^ debug_decor_sr_10[27];
              11: debug_decor_fb_11 = debug_decor_sr_11[0] ^ debug_decor_sr_11[27];
            endcase
          end
        end
        3'd4: begin  // LFSR_7
          if (shift_dir == 1'b0) begin
            // SHIFT_RIGHT: fb = sr[6] ^ sr[5]
            unique case (debug_gi)
              0:  debug_decor_fb_0  = debug_decor_sr_0[6]  ^ debug_decor_sr_0[5];
              1:  debug_decor_fb_1  = debug_decor_sr_1[6]  ^ debug_decor_sr_1[5];
              2:  debug_decor_fb_2  = debug_decor_sr_2[6]  ^ debug_decor_sr_2[5];
              3:  debug_decor_fb_3  = debug_decor_sr_3[6]  ^ debug_decor_sr_3[5];
              4:  debug_decor_fb_4  = debug_decor_sr_4[6]  ^ debug_decor_sr_4[5];
              5:  debug_decor_fb_5  = debug_decor_sr_5[6]  ^ debug_decor_sr_5[5];
              6:  debug_decor_fb_6  = debug_decor_sr_6[6]  ^ debug_decor_sr_6[5];
              7:  debug_decor_fb_7  = debug_decor_sr_7[6]  ^ debug_decor_sr_7[5];
              8:  debug_decor_fb_8  = debug_decor_sr_8[6]  ^ debug_decor_sr_8[5];
              9:  debug_decor_fb_9  = debug_decor_sr_9[6]  ^ debug_decor_sr_9[5];
              10: debug_decor_fb_10 = debug_decor_sr_10[6] ^ debug_decor_sr_10[5];
              11: debug_decor_fb_11 = debug_decor_sr_11[6] ^ debug_decor_sr_11[5];
            endcase
          end else begin
            // SHIFT_LEFT: fb = sr[0] ^ sr[1]
            unique case (debug_gi)
              0:  debug_decor_fb_0  = debug_decor_sr_0[0]  ^ debug_decor_sr_0[1];
              1:  debug_decor_fb_1  = debug_decor_sr_1[0]  ^ debug_decor_sr_1[1];
              2:  debug_decor_fb_2  = debug_decor_sr_2[0]  ^ debug_decor_sr_2[1];
              3:  debug_decor_fb_3  = debug_decor_sr_3[0]  ^ debug_decor_sr_3[1];
              4:  debug_decor_fb_4  = debug_decor_sr_4[0]  ^ debug_decor_sr_4[1];
              5:  debug_decor_fb_5  = debug_decor_sr_5[0]  ^ debug_decor_sr_5[1];
              6:  debug_decor_fb_6  = debug_decor_sr_6[0]  ^ debug_decor_sr_6[1];
              7:  debug_decor_fb_7  = debug_decor_sr_7[0]  ^ debug_decor_sr_7[1];
              8:  debug_decor_fb_8  = debug_decor_sr_8[0]  ^ debug_decor_sr_8[1];
              9:  debug_decor_fb_9  = debug_decor_sr_9[0]  ^ debug_decor_sr_9[1];
              10: debug_decor_fb_10 = debug_decor_sr_10[0] ^ debug_decor_sr_10[1];
              11: debug_decor_fb_11 = debug_decor_sr_11[0] ^ debug_decor_sr_11[1];
            endcase
          end
        end
        default: begin  // Invalid mode - set feedback to 0
          unique case (debug_gi)
            0:  debug_decor_fb_0  = 1'b0;
            1:  debug_decor_fb_1  = 1'b0;
            2:  debug_decor_fb_2  = 1'b0;
            3:  debug_decor_fb_3  = 1'b0;
            4:  debug_decor_fb_4  = 1'b0;
            5:  debug_decor_fb_5  = 1'b0;
            6:  debug_decor_fb_6  = 1'b0;
            7:  debug_decor_fb_7  = 1'b0;
            8:  debug_decor_fb_8  = 1'b0;
            9:  debug_decor_fb_9  = 1'b0;
            10: debug_decor_fb_10 = 1'b0;
            11: debug_decor_fb_11 = 1'b0;
          endcase
        end
      endcase
    end
  end
endgenerate

//------------------------------------------------------------------------------
// Compressor Reference Model Debug Signals (for nWave visibility)
//------------------------------------------------------------------------------
// Expose BIW extraction inputs (a, b, c) and outputs (y) for all 4 groups
// Strided grouping: [0,4,8], [1,5,9], [2,6,10], [3,7,11]
// Formula: y = (a * b) + c in GF(2^8)

// Group 0: lanes [0, 4, 8] -> output[31:24]
logic [7:0] debug_comp_group_0_a;
logic [7:0] debug_comp_group_0_b;
logic [7:0] debug_comp_group_0_c;
logic [7:0] debug_comp_group_0_y;

// Group 1: lanes [1, 5, 9] -> output[23:16]
logic [7:0] debug_comp_group_1_a;
logic [7:0] debug_comp_group_1_b;
logic [7:0] debug_comp_group_1_c;
logic [7:0] debug_comp_group_1_y;

// Group 2: lanes [2, 6, 10] -> output[15:8]
logic [7:0] debug_comp_group_2_a;
logic [7:0] debug_comp_group_2_b;
logic [7:0] debug_comp_group_2_c;
logic [7:0] debug_comp_group_2_y;

// Group 3: lanes [3, 7, 11] -> output[7:0]
logic [7:0] debug_comp_group_3_a;
logic [7:0] debug_comp_group_3_b;
logic [7:0] debug_comp_group_3_c;
logic [7:0] debug_comp_group_3_y;

// Assign debug signals from compressor model internals
// Group 0: lanes [0, 4, 8]
assign debug_comp_group_0_a = u_compressor_refmodel.masked_bytes[0];
assign debug_comp_group_0_b = u_compressor_refmodel.masked_bytes[4];
assign debug_comp_group_0_c = u_compressor_refmodel.masked_bytes[8];
assign debug_comp_group_0_y = u_compressor_refmodel.biw_byte[0];

// Group 1: lanes [1, 5, 9]
assign debug_comp_group_1_a = u_compressor_refmodel.masked_bytes[1];
assign debug_comp_group_1_b = u_compressor_refmodel.masked_bytes[5];
assign debug_comp_group_1_c = u_compressor_refmodel.masked_bytes[9];
assign debug_comp_group_1_y = u_compressor_refmodel.biw_byte[1];

// Group 2: lanes [2, 6, 10]
assign debug_comp_group_2_a = u_compressor_refmodel.masked_bytes[2];
assign debug_comp_group_2_b = u_compressor_refmodel.masked_bytes[6];
assign debug_comp_group_2_c = u_compressor_refmodel.masked_bytes[10];
assign debug_comp_group_2_y = u_compressor_refmodel.biw_byte[2];

// Group 3: lanes [3, 7, 11]
assign debug_comp_group_3_a = u_compressor_refmodel.masked_bytes[3];
assign debug_comp_group_3_b = u_compressor_refmodel.masked_bytes[7];
assign debug_comp_group_3_c = u_compressor_refmodel.masked_bytes[11];
assign debug_comp_group_3_y = u_compressor_refmodel.biw_byte[3];

// Compressor checker control (from compressor_cfg interface)
logic debug_compressor_checker_enable;
logic debug_compressor_checker_verbose;
assign debug_compressor_checker_enable  = compressor_cfg.checker_enable;
assign debug_compressor_checker_verbose = compressor_cfg.checker_verbose;

// Compressor checker statistics (internal to checker module, probe for waveforms)
integer debug_compressor_check_count;
integer debug_compressor_mismatch_count;
assign debug_compressor_check_count    = u_compressor_checker.check_count;
assign debug_compressor_mismatch_count = u_compressor_checker.mismatch_count;

/* verilator lint_on UNUSED */
