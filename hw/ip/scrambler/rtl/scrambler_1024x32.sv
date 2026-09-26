// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Scramble a 1024x32 SRAM with a PRESENT-style round and address tweak.
//
// Implements a simplified, single-round PRESENT-style cipher for 32-bit data blocks with
// address tweaking. The round_key is the expanded address XORed with scrambler_key_i.
//
// The round depends on BYTE_WISE:
//
// - BYTE_WISE=0 (full word): scramble is XOR round_key, sbox4 over 8 nibbles, then
//   perm32; descramble is iperm32, ibox4, then XOR round_key.
// - BYTE_WISE=1 (per-byte): scramble ends in perm8 x4; descramble starts with iperm8 x4.

module scrambler_1024x32
  import scrambler_pkg::*;
#(
  parameter int unsigned ADDR_WIDTH = 10,                   // SRAM address width.
  parameter int unsigned DATA_WIDTH = 32,                   // SRAM data width.
  parameter int unsigned BYTE_WISE  = 0                     // Use per-byte perm8 instead of full-word perm32.
) (
  input  logic [ADDR_WIDTH-1:0]   addr_i,                   // Plaintext SRAM address.
  /* verilator lint_off UNUSEDSIGNAL */
  input  logic [DATA_WIDTH/8-1:0] byte_mask_i,              // Byte enables; unused in word mode.
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic [31:0]             scrambler_key_i,          // 32-bit scrambler key.
  output logic [ADDR_WIDTH-1:0]   scrambled_addr_o,         // Address after tweak.
  input  logic [DATA_WIDTH-1:0]   write_data_i,             // Plaintext write data.
  output logic [DATA_WIDTH-1:0]   scrambled_write_data_o,   // Scrambled write data.
  input  logic [DATA_WIDTH-1:0]   scrambled_read_data_i,    // Scrambled read data from the SRAM.
  output logic [DATA_WIDTH-1:0]   read_data_o               // Descrambled read data.
);

  logic [31:0] round_key;
  logic [31:0] after_key_xor;
  logic [31:0] after_sbox;
  logic [31:0] after_iplayer;
  logic [31:0] after_ibox;

  scrambler_addr_tweak #(
    .ADDR_WIDTH(ADDR_WIDTH)
  ) u_addr_tweak (
    .addr_i         (addr_i),
    .scrambler_key_i(scrambler_key_i),
    .round_key_o    (round_key)
  );

  assign scrambled_addr_o = addr_scramble10(addr_i, scrambler_key_i[ADDR_WIDTH-1:0]);

  // Scramble
  assign after_key_xor = write_data_i ^ round_key;
  assign after_sbox = {sbox4(after_key_xor[31:28]),
                         sbox4(after_key_xor[27:24]),
                         sbox4(after_key_xor[23:20]),
                         sbox4(after_key_xor[19:16]),
                         sbox4(after_key_xor[15:12]),
                         sbox4(after_key_xor[11:8]),
                         sbox4(after_key_xor[7:4]),
                         sbox4(after_key_xor[3:0])};

  if (BYTE_WISE == 0) begin : gen_scramble_word
    assign scrambled_write_data_o = perm32(after_sbox);
  end else begin : gen_scramble_bytewise
    assign scrambled_write_data_o = {
      perm8(after_sbox[31:24]),
      perm8(after_sbox[23:16]),
      perm8(after_sbox[15:8]),
      perm8(after_sbox[7:0])
    };
  end

  // Descramble
  if (BYTE_WISE == 0) begin : gen_descramble_word
    assign after_iplayer = iperm32(scrambled_read_data_i);
  end else begin : gen_descramble_bytewise
    assign after_iplayer = {
      iperm8(scrambled_read_data_i[31:24]),
      iperm8(scrambled_read_data_i[23:16]),
      iperm8(scrambled_read_data_i[15:8]),
      iperm8(scrambled_read_data_i[7:0])
    };
  end

  assign after_ibox = {ibox4(after_iplayer[31:28]),
                         ibox4(after_iplayer[27:24]),
                         ibox4(after_iplayer[23:20]),
                         ibox4(after_iplayer[19:16]),
                         ibox4(after_iplayer[15:12]),
                         ibox4(after_iplayer[11:8]),
                         ibox4(after_iplayer[7:4]),
                         ibox4(after_iplayer[3:0])};
  assign read_data_o = after_ibox ^ round_key;

endmodule
