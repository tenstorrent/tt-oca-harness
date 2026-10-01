// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Expand a narrow address and XOR it with the scrambler key to form a round key.
//
// For ADDR_WIDTH 8 through 13 and 16 the address is concatenated with itself until 32 bits
// are formed, the last copy keeping only its most significant bits; a 32-bit address is
// used as is, and any other width is zero-extended.
// The address must be 32 bits wide or less.
// round_key_o is that expansion XORed with scrambler_key_i.

module scrambler_addr_tweak #(
  parameter int unsigned ADDR_WIDTH = 32  // Input address width; must be <= 32.
) (
  input  logic [ADDR_WIDTH-1:0] addr_i,                     // Plaintext address to expand.
  input  logic [31:0]           scrambler_key_i,            // 32-bit scrambler key.
  output logic [31:0]           round_key_o                 // Expanded address XOR key.
);
  logic [31:0] expanded_addr;

  if (ADDR_WIDTH == 32) begin : gen_addr_32
    assign expanded_addr = addr_i;
  end else if (ADDR_WIDTH == 16) begin : gen_addr_16
    assign expanded_addr = {addr_i, addr_i};
  end else if (ADDR_WIDTH == 8) begin : gen_addr_8
    assign expanded_addr = {addr_i, addr_i, addr_i, addr_i};
  end else if (ADDR_WIDTH == 9) begin : gen_addr_9
    assign expanded_addr = {addr_i, addr_i, addr_i, addr_i[8:4]};  // 9+9+9+5=32
  end else if (ADDR_WIDTH == 10) begin : gen_addr_10
    assign expanded_addr = {addr_i, addr_i, addr_i, addr_i[9:8]};  // 10+10+10+2=32
  end else if (ADDR_WIDTH == 11) begin : gen_addr_11
    assign expanded_addr = {addr_i, addr_i, addr_i[10:1]};  // 11+11+10=32
  end else if (ADDR_WIDTH == 12) begin : gen_addr_12
    assign expanded_addr = {addr_i, addr_i, addr_i[11:4]};  // 12+12+8=32
  end else if (ADDR_WIDTH == 13) begin : gen_addr_13
    assign expanded_addr = {addr_i, addr_i, addr_i[12:7]};  // 13+13+6=32
  end else begin : gen_addr_other
    assign expanded_addr = {{(32 - ADDR_WIDTH) {1'b0}}, addr_i};
  end

  assign round_key_o = expanded_addr ^ scrambler_key_i;
endmodule
