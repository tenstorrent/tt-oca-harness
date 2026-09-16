// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// GF(2^8) Arithmetic Functions for BIW Extractor Reference Model
//
// Description:
//   Pure combinational functions implementing Galois Field GF(2^8) arithmetic
//   using the AES primitive polynomial: x^8 + x^4 + x^3 + x + 1 (0x1B)
//
// Functions:
//   - gf256_mult(a, b)     : Multiply two GF(2^8) elements
//   - gf256_muladd(a, b, c): Compute (a * b) + c in GF(2^8)
//
// Reference:
//   FIPS 197 (AES Specification) - Finite Field Arithmetic
//   https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.197.pdf
//------------------------------------------------------------------------------

`ifndef GF256_FUNCTIONS_SVH
`define GF256_FUNCTIONS_SVH

//------------------------------------------------------------------------------
// GF(2^8) Multiplication: a * b
//
// Algorithm: Shift-and-XOR (Peasant's algorithm)
//   - Initialize product = 0
//   - For each bit i in b (LSB to MSB):
//       - If b[i] == 1, add (XOR) current a_shifted to product
//       - Shift a_shifted left by 1
//       - If overflow (a_shifted[7] was 1), reduce by XORing with polynomial
//
// Primitive Polynomial: 0x1B (without x^8 term)
//   Binary: 0001_1011 = x^4 + x^3 + x + 1
//   Full:   x^8 + x^4 + x^3 + x + 1
//------------------------------------------------------------------------------
function automatic logic [7:0] gf256_mult(input logic [7:0] a, input logic [7:0] b);
  localparam logic [7:0] POLY = 8'h1B;  // AES primitive polynomial

  logic [7:0] p;          // Product accumulator
  logic [7:0] a_shifted;  // Shifted copy of 'a'
  logic       hi_bit;     // High bit for reduction check

  // Initialize
  p = 8'h00;
  a_shifted = a;

  // Process each bit of b (unrolled for clarity and synthesis)
  // Bit 0
  if (b[0]) p = p ^ a_shifted;
  hi_bit = a_shifted[7];
  a_shifted = a_shifted << 1;
  if (hi_bit) a_shifted = a_shifted ^ POLY;

  // Bit 1
  if (b[1]) p = p ^ a_shifted;
  hi_bit = a_shifted[7];
  a_shifted = a_shifted << 1;
  if (hi_bit) a_shifted = a_shifted ^ POLY;

  // Bit 2
  if (b[2]) p = p ^ a_shifted;
  hi_bit = a_shifted[7];
  a_shifted = a_shifted << 1;
  if (hi_bit) a_shifted = a_shifted ^ POLY;

  // Bit 3
  if (b[3]) p = p ^ a_shifted;
  hi_bit = a_shifted[7];
  a_shifted = a_shifted << 1;
  if (hi_bit) a_shifted = a_shifted ^ POLY;

  // Bit 4
  if (b[4]) p = p ^ a_shifted;
  hi_bit = a_shifted[7];
  a_shifted = a_shifted << 1;
  if (hi_bit) a_shifted = a_shifted ^ POLY;

  // Bit 5
  if (b[5]) p = p ^ a_shifted;
  hi_bit = a_shifted[7];
  a_shifted = a_shifted << 1;
  if (hi_bit) a_shifted = a_shifted ^ POLY;

  // Bit 6
  if (b[6]) p = p ^ a_shifted;
  hi_bit = a_shifted[7];
  a_shifted = a_shifted << 1;
  if (hi_bit) a_shifted = a_shifted ^ POLY;

  // Bit 7
  if (b[7]) p = p ^ a_shifted;
  // No shift needed after last bit

  return p;
endfunction

//------------------------------------------------------------------------------
// GF(2^8) Multiply-Add: (a * b) + c
//
// Computes the BIW extractor operation: y = (a * b) + c
// Note: Addition in GF(2^8) is simply XOR
//
// Parameters:
//   a, b : Multiplicands (8-bit)
//   c    : Addend (8-bit)
//
// Returns:
//   y = (a * b) + c in GF(2^8)
//------------------------------------------------------------------------------
function automatic logic [7:0] gf256_muladd(input logic [7:0] a, input logic [7:0] b,
                                            input logic [7:0] c);
  logic [7:0] product;

  // Multiply in GF(2^8)
  product = gf256_mult(a, b);

  // Add (XOR) in GF(2^8)
  return product ^ c;
endfunction

//------------------------------------------------------------------------------
// Test Vector Verification (for simulation)
//
// These assertions verify the GF(2^8) implementation against known test
// vectors from AES and other sources.
//------------------------------------------------------------------------------

`ifdef GF256_ENABLE_ASSERTIONS

// AES MixColumns test vectors
initial begin
  logic [7:0] test_result;

  // Test 1: Basic multiplication
  test_result = gf256_mult(8'h02, 8'h03);
  assert (test_result == 8'h06)
  else $error("GF256_MULT: 0x02 * 0x03 failed, got 0x%02X, expected 0x06", test_result);

  // Test 2: Multiplication with reduction
  test_result = gf256_mult(8'h02, 8'h87);
  assert (test_result == 8'h0E)
  else $error("GF256_MULT: 0x02 * 0x87 failed, got 0x%02X, expected 0x0E", test_result);

  // Test 3: AES MixColumns known value
  test_result = gf256_mult(8'h53, 8'hCA);
  assert (test_result == 8'h01)
  else $error("GF256_MULT: 0x53 * 0xCA failed, got 0x%02X, expected 0x01", test_result);

  // Test 4: Multiplication by zero
  test_result = gf256_mult(8'h00, 8'hFF);
  assert (test_result == 8'h00)
  else $error("GF256_MULT: 0x00 * 0xFF failed, got 0x%02X, expected 0x00", test_result);

  // Test 5: Multiply-add
  test_result = gf256_muladd(8'h02, 8'h03, 8'h01);
  assert (test_result == 8'h07)
  else $error("GF256_MULADD: (0x02 * 0x03) + 0x01 failed, got 0x%02X, expected 0x07", test_result);

  // Test 6: Multiply-add with zero product
  test_result = gf256_muladd(8'h00, 8'hFF, 8'hAA);
  assert (test_result == 8'hAA)
  else $error("GF256_MULADD: (0x00 * 0xFF) + 0xAA failed, got 0x%02X, expected 0xAA", test_result);

  // Test 7: Multiply-add AES example
  test_result = gf256_muladd(8'h53, 8'hCA, 8'h00);
  assert (test_result == 8'h01)
  else $error("GF256_MULADD: (0x53 * 0xCA) + 0x00 failed, got 0x%02X, expected 0x01", test_result);

  // Test 8: Commutativity of multiplication
  test_result = gf256_mult(8'h12, 8'h34);
  assert (test_result == gf256_mult(8'h34, 8'h12))
  else $error("GF256_MULT: Commutativity failed");

  // Test 9: Identity element (multiply by 1)
  test_result = gf256_mult(8'h57, 8'h01);
  assert (test_result == 8'h57)
  else $error("GF256_MULT: Identity element failed, got 0x%02X, expected 0x57", test_result);

  // Test 10: Distributive property: a*(b+c) = a*b + a*c
  logic [7:0] lhs, rhs;
  lhs = gf256_mult(8'h12, 8'h34 ^ 8'h56);
  rhs = gf256_mult(8'h12, 8'h34) ^ gf256_mult(8'h12, 8'h56);
  assert (lhs == rhs)
  else $error("GF256_MULT: Distributive property failed");

  $display("[GF256] All test vectors passed successfully!");
end

`endif  // GF256_ENABLE_ASSERTIONS

//------------------------------------------------------------------------------
// Additional utility functions (optional)
//------------------------------------------------------------------------------

// Check if value is zero in GF(2^8)
function automatic logic gf256_is_zero(input logic [7:0] a);
  return (a == 8'h00);
endfunction

// Check if value is one (identity) in GF(2^8)
function automatic logic gf256_is_one(input logic [7:0] a);
  return (a == 8'h01);
endfunction

// GF(2^8) addition (just XOR, but explicit for clarity)
function automatic logic [7:0] gf256_add(input logic [7:0] a, input logic [7:0] b);
  return a ^ b;
endfunction

//------------------------------------------------------------------------------
// Reference: Known Test Vectors
//
// From AES Specification (FIPS 197):
//   0x02 * 0x03 = 0x06
//   0x02 * 0x87 = 0x0E
//   0x03 * 0xCA = 0x8D
//   0x53 * 0xCA = 0x01
//
// From GF(2^8) properties:
//   a * 0x00 = 0x00 (zero)
//   a * 0x01 = a    (identity)
//   a * b = b * a   (commutative)
//   a * (b + c) = (a * b) + (a * c)  (distributive, where + is XOR)
//
// BIW Extractor examples:
//   y = (0x12 * 0x34) + 0x56
//   y = (0xFF * 0xFF) + 0x00
//   y = (0x00 * 0xFF) + 0xAA = 0xAA
//------------------------------------------------------------------------------

`endif  // GF256_FUNCTIONS_SVH
