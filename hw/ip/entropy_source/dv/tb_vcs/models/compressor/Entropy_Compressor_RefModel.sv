// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Compressor Reference Model
//
// Description:
//   Behavioral reference model of the Entropy Compressor (BIW Extractor).
//   Compresses 12 input byte streams from decorrelators into a single 32-bit
//   word using Barak-Impagliazzo-Wigderson (BIW) extraction.
//
// Algorithm:
//   - Groups 12 lanes into 4 groups of 3
//   - Group i: lanes [i, i+4, i+8]
//   - Each group: y = (a * b) + c in GF(2^8)
//   - Output: {group[0], group[1], group[2], group[3]} = 32-bit word
//
// Usage:
//   compressor_cfg_if cfg();
//   Entropy_Compressor_RefModel #(.N_LANES(12)) model (
//       .bytes_i(bytes), .vld_i(vld), .cfg(cfg.slave), .word_o(word), .vld_o(word_vld));
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

// Include GF(2^8) arithmetic functions
`include "gf256_functions.svh"

module Entropy_Compressor_RefModel #(
  parameter int N_LANES = 12  // Number of input byte lanes (must be 12)
) (
  // Input: 12 bytes from decorrelator model (packed array to match decorrelator output)
  input  logic [N_LANES-1:0][7:0] bytes_i,
  input  logic                vld_i,           // Input valid

  // Configuration Interface
  compressor_cfg_if.slave     cfg,

  // Output: Compressed 32-bit word (combinational)
  output logic [31:0]         word_o,
  output logic                vld_o            // Output valid (combinational)
);

  //--------------------------------------------------------------------------
  // Assertions and Parameter Checks
  //--------------------------------------------------------------------------

  initial begin
    assert (N_LANES == 12)
    else $fatal(1, "Entropy_Compressor_RefModel: N_LANES must be 12 (got %0d)", N_LANES);
  end

  //--------------------------------------------------------------------------
  // Internal Signals (all combinational)
  //--------------------------------------------------------------------------

  // Masked input bytes (apply lane mask)
  logic [7:0] masked_bytes [N_LANES];

  // BIW extractor outputs (4 groups)
  logic [7:0] biw_byte [4];

  //--------------------------------------------------------------------------
  // Lane Masking
  //--------------------------------------------------------------------------

  always_comb begin
    for (int i = 0; i < N_LANES; i++) begin
      if (cfg.lane_mask[i]) masked_bytes[i] = bytes_i[i];
      else masked_bytes[i] = 8'h00;  // Force masked lanes to zero
    end
  end

  //--------------------------------------------------------------------------
  // BIW Extraction (4 parallel groups) - Strided Grouping
  //--------------------------------------------------------------------------

  // Group 0: lanes [0, 4, 8]  → biw_byte[0] → word[31:24]
  // Group 1: lanes [1, 5, 9]  → biw_byte[1] → word[23:16]
  // Group 2: lanes [2, 6, 10] → biw_byte[2] → word[15:8]
  // Group 3: lanes [3, 7, 11] → biw_byte[3] → word[7:0]

  always_comb begin
    if (cfg.enable && !cfg.bypass) begin
      // Normal BIW mode: y = (a * b) + c in GF(2^8)
      // Group 0: lanes [0, 4, 8]
      biw_byte[0] = gf256_muladd(
                masked_bytes[0],      // a: lane 0
                masked_bytes[4],      // b: lane 4
                masked_bytes[8]       // c: lane 8
            );
      // Group 1: lanes [1, 5, 9]
      biw_byte[1] = gf256_muladd(
                masked_bytes[1],      // a: lane 1
                masked_bytes[5],      // b: lane 5
                masked_bytes[9]       // c: lane 9
            );
      // Group 2: lanes [2, 6, 10]
      biw_byte[2] = gf256_muladd(
                masked_bytes[2],      // a: lane 2
                masked_bytes[6],      // b: lane 6
                masked_bytes[10]      // c: lane 10
            );
      // Group 3: lanes [3, 7, 11]
      biw_byte[3] = gf256_muladd(
                masked_bytes[3],      // a: lane 3
                masked_bytes[7],      // b: lane 7
                masked_bytes[11]      // c: lane 11
            );
    end else if (cfg.bypass) begin
      // Bypass mode: simple pass-through (for debug)
      for (int i = 0; i < 4; i++) begin
        biw_byte[i] = masked_bytes[i];
      end
    end else begin
      // Disabled: output zeros
      for (int i = 0; i < 4; i++) begin
        biw_byte[i] = 8'h00;
      end
    end
  end

  //--------------------------------------------------------------------------
  // Output Word Assembly (Combinational)
  //--------------------------------------------------------------------------

  // Concatenate 4 bytes into 32-bit word
  // biw_byte[0] → MSB [31:24]
  // biw_byte[3] → LSB [7:0]
  assign word_o = {biw_byte[0], biw_byte[1], biw_byte[2], biw_byte[3]};

  // Valid output follows input valid (with enable check) - combinational
  assign vld_o = vld_i && cfg.enable;

  //--------------------------------------------------------------------------
  // Notes
  //--------------------------------------------------------------------------
  // This is a purely combinational model - no clocking or statistics tracking
  // Debug signals can be probed directly from masked_bytes[] and biw_byte[]
  // Grouping is fixed: [0,4,8], [1,5,9], [2,6,10], [3,7,11] (strided)

endmodule : Entropy_Compressor_RefModel
