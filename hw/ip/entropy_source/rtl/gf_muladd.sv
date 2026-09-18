// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file gf_muladd.sv
 * @brief Galois Field GF(2^8) multiply-adder for AES applications.
 *
 * @details This module computes Y = (a * b) + c in GF(2^8) under the AES
 *          primitive polynomial x^8 + x^4 + x^3 + x + 1 (0x11b). The
 *          multiplication is unrolled into a shift-and-XOR sequence of
 *          partial products, eliminating any feedback loops for improved
 *          throughput.
 */

module gf_muladd (
  input       logic [7:0] a_i,
  input       logic [7:0] b_i,
  input       logic [7:0] c_i,
  output      logic [7:0] y_o
);

  /////////////////////
  // Local parameters
  /////////////////////

  // AES poly without the implicit x^8 term: x^4 + x^3 + x + 1 = 0x1b
  localparam logic [7:0] AES_POLY = 8'h1B;

  /////////////
  // Signals
  /////////////

  logic [7:0] a0, a1, a2, a3, a4, a5, a6, a7;
  logic [7:0] p0, p1, p2, p3, p4, p5, p6, p7, p8;
  logic [7:0] mult_result;

  /////////////////
  // Combinational
  /////////////////

  assign a0 = a_i;
  assign p0 = 8'h00;

  assign p1 = p0 ^ (b_i[0] ? a0 : 8'h00);
  assign a1 = a0[7] ? ((a0 << 1) ^ AES_POLY) : (a0 << 1);

  assign p2 = p1 ^ (b_i[1] ? a1 : 8'h00);
  assign a2 = a1[7] ? ((a1 << 1) ^ AES_POLY) : (a1 << 1);

  assign p3 = p2 ^ (b_i[2] ? a2 : 8'h00);
  assign a3 = a2[7] ? ((a2 << 1) ^ AES_POLY) : (a2 << 1);

  assign p4 = p3 ^ (b_i[3] ? a3 : 8'h00);
  assign a4 = a3[7] ? ((a3 << 1) ^ AES_POLY) : (a3 << 1);

  assign p5 = p4 ^ (b_i[4] ? a4 : 8'h00);
  assign a5 = a4[7] ? ((a4 << 1) ^ AES_POLY) : (a4 << 1);

  assign p6 = p5 ^ (b_i[5] ? a5 : 8'h00);
  assign a6 = a5[7] ? ((a5 << 1) ^ AES_POLY) : (a5 << 1);

  assign p7 = p6 ^ (b_i[6] ? a6 : 8'h00);
  assign a7 = a6[7] ? ((a6 << 1) ^ AES_POLY) : (a6 << 1);

  assign p8 = p7 ^ (b_i[7] ? a7 : 8'h00);

  assign mult_result = p8;

  ///////////
  // Output
  ///////////

  assign y_o = mult_result ^ c_i;

endmodule
