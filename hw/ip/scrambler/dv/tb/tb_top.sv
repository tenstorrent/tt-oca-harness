// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scrambler IP-level testbench top for the cocotb flow.
//
// The scrambler is combinational, so the bench needs no clock: cocotb drives
// an address, a key, write data and scrambled read data, lets time advance,
// and samples the scrambled address, the scrambled write data and the
// descrambled read data. Every sized variant (512 to 8192 words of 32 bits)
// is instantiated twice, once per BYTE_WISE mode, with its own pin bundle
// named <mode><depth>_* (w = word mode, b = byte-wise mode), so one model
// covers the whole family.

`timescale 1ns / 1ps

module scrambler_tb_top (
  // scrambler_512x32, BYTE_WISE=0
  input  wire [8:0]  w512_addr,
  input  wire [3:0]  w512_byte_mask,
  input  wire [31:0] w512_key,
  input  wire [31:0] w512_write_data,
  input  wire [31:0] w512_scrambled_read_data,
  output wire [8:0]  w512_scrambled_addr,
  output wire [31:0] w512_scrambled_write_data,
  output wire [31:0] w512_read_data,

  // scrambler_512x32, BYTE_WISE=1
  input  wire [8:0]  b512_addr,
  input  wire [3:0]  b512_byte_mask,
  input  wire [31:0] b512_key,
  input  wire [31:0] b512_write_data,
  input  wire [31:0] b512_scrambled_read_data,
  output wire [8:0]  b512_scrambled_addr,
  output wire [31:0] b512_scrambled_write_data,
  output wire [31:0] b512_read_data,

  // scrambler_1024x32, BYTE_WISE=0
  input  wire [9:0]  w1024_addr,
  input  wire [3:0]  w1024_byte_mask,
  input  wire [31:0] w1024_key,
  input  wire [31:0] w1024_write_data,
  input  wire [31:0] w1024_scrambled_read_data,
  output wire [9:0]  w1024_scrambled_addr,
  output wire [31:0] w1024_scrambled_write_data,
  output wire [31:0] w1024_read_data,

  // scrambler_1024x32, BYTE_WISE=1
  input  wire [9:0]  b1024_addr,
  input  wire [3:0]  b1024_byte_mask,
  input  wire [31:0] b1024_key,
  input  wire [31:0] b1024_write_data,
  input  wire [31:0] b1024_scrambled_read_data,
  output wire [9:0]  b1024_scrambled_addr,
  output wire [31:0] b1024_scrambled_write_data,
  output wire [31:0] b1024_read_data,

  // scrambler_2048x32, BYTE_WISE=0
  input  wire [10:0] w2048_addr,
  input  wire [3:0]  w2048_byte_mask,
  input  wire [31:0] w2048_key,
  input  wire [31:0] w2048_write_data,
  input  wire [31:0] w2048_scrambled_read_data,
  output wire [10:0] w2048_scrambled_addr,
  output wire [31:0] w2048_scrambled_write_data,
  output wire [31:0] w2048_read_data,

  // scrambler_2048x32, BYTE_WISE=1
  input  wire [10:0] b2048_addr,
  input  wire [3:0]  b2048_byte_mask,
  input  wire [31:0] b2048_key,
  input  wire [31:0] b2048_write_data,
  input  wire [31:0] b2048_scrambled_read_data,
  output wire [10:0] b2048_scrambled_addr,
  output wire [31:0] b2048_scrambled_write_data,
  output wire [31:0] b2048_read_data,

  // scrambler_4096x32, BYTE_WISE=0
  input  wire [11:0] w4096_addr,
  input  wire [3:0]  w4096_byte_mask,
  input  wire [31:0] w4096_key,
  input  wire [31:0] w4096_write_data,
  input  wire [31:0] w4096_scrambled_read_data,
  output wire [11:0] w4096_scrambled_addr,
  output wire [31:0] w4096_scrambled_write_data,
  output wire [31:0] w4096_read_data,

  // scrambler_4096x32, BYTE_WISE=1
  input  wire [11:0] b4096_addr,
  input  wire [3:0]  b4096_byte_mask,
  input  wire [31:0] b4096_key,
  input  wire [31:0] b4096_write_data,
  input  wire [31:0] b4096_scrambled_read_data,
  output wire [11:0] b4096_scrambled_addr,
  output wire [31:0] b4096_scrambled_write_data,
  output wire [31:0] b4096_read_data,

  // scrambler_8192x32, BYTE_WISE=0
  input  wire [12:0] w8192_addr,
  input  wire [3:0]  w8192_byte_mask,
  input  wire [31:0] w8192_key,
  input  wire [31:0] w8192_write_data,
  input  wire [31:0] w8192_scrambled_read_data,
  output wire [12:0] w8192_scrambled_addr,
  output wire [31:0] w8192_scrambled_write_data,
  output wire [31:0] w8192_read_data,

  // scrambler_8192x32, BYTE_WISE=1
  input  wire [12:0] b8192_addr,
  input  wire [3:0]  b8192_byte_mask,
  input  wire [31:0] b8192_key,
  input  wire [31:0] b8192_write_data,
  input  wire [31:0] b8192_scrambled_read_data,
  output wire [12:0] b8192_scrambled_addr,
  output wire [31:0] b8192_scrambled_write_data,
  output wire [31:0] b8192_read_data
);

  scrambler_512x32 #(
    .BYTE_WISE (0)
  ) u_w512 (
    .addr_i                 (w512_addr),
    .byte_mask_i            (w512_byte_mask),
    .scrambler_key_i        (w512_key),
    .scrambled_addr_o       (w512_scrambled_addr),
    .write_data_i           (w512_write_data),
    .scrambled_write_data_o (w512_scrambled_write_data),
    .scrambled_read_data_i  (w512_scrambled_read_data),
    .read_data_o            (w512_read_data)
  );

  scrambler_512x32 #(
    .BYTE_WISE (1)
  ) u_b512 (
    .addr_i                 (b512_addr),
    .byte_mask_i            (b512_byte_mask),
    .scrambler_key_i        (b512_key),
    .scrambled_addr_o       (b512_scrambled_addr),
    .write_data_i           (b512_write_data),
    .scrambled_write_data_o (b512_scrambled_write_data),
    .scrambled_read_data_i  (b512_scrambled_read_data),
    .read_data_o            (b512_read_data)
  );

  scrambler_1024x32 #(
    .BYTE_WISE (0)
  ) u_w1024 (
    .addr_i                 (w1024_addr),
    .byte_mask_i            (w1024_byte_mask),
    .scrambler_key_i        (w1024_key),
    .scrambled_addr_o       (w1024_scrambled_addr),
    .write_data_i           (w1024_write_data),
    .scrambled_write_data_o (w1024_scrambled_write_data),
    .scrambled_read_data_i  (w1024_scrambled_read_data),
    .read_data_o            (w1024_read_data)
  );

  scrambler_1024x32 #(
    .BYTE_WISE (1)
  ) u_b1024 (
    .addr_i                 (b1024_addr),
    .byte_mask_i            (b1024_byte_mask),
    .scrambler_key_i        (b1024_key),
    .scrambled_addr_o       (b1024_scrambled_addr),
    .write_data_i           (b1024_write_data),
    .scrambled_write_data_o (b1024_scrambled_write_data),
    .scrambled_read_data_i  (b1024_scrambled_read_data),
    .read_data_o            (b1024_read_data)
  );

  scrambler_2048x32 #(
    .BYTE_WISE (0)
  ) u_w2048 (
    .addr_i                 (w2048_addr),
    .byte_mask_i            (w2048_byte_mask),
    .scrambler_key_i        (w2048_key),
    .scrambled_addr_o       (w2048_scrambled_addr),
    .write_data_i           (w2048_write_data),
    .scrambled_write_data_o (w2048_scrambled_write_data),
    .scrambled_read_data_i  (w2048_scrambled_read_data),
    .read_data_o            (w2048_read_data)
  );

  scrambler_2048x32 #(
    .BYTE_WISE (1)
  ) u_b2048 (
    .addr_i                 (b2048_addr),
    .byte_mask_i            (b2048_byte_mask),
    .scrambler_key_i        (b2048_key),
    .scrambled_addr_o       (b2048_scrambled_addr),
    .write_data_i           (b2048_write_data),
    .scrambled_write_data_o (b2048_scrambled_write_data),
    .scrambled_read_data_i  (b2048_scrambled_read_data),
    .read_data_o            (b2048_read_data)
  );

  scrambler_4096x32 #(
    .BYTE_WISE (0)
  ) u_w4096 (
    .addr_i                 (w4096_addr),
    .byte_mask_i            (w4096_byte_mask),
    .scrambler_key_i        (w4096_key),
    .scrambled_addr_o       (w4096_scrambled_addr),
    .write_data_i           (w4096_write_data),
    .scrambled_write_data_o (w4096_scrambled_write_data),
    .scrambled_read_data_i  (w4096_scrambled_read_data),
    .read_data_o            (w4096_read_data)
  );

  scrambler_4096x32 #(
    .BYTE_WISE (1)
  ) u_b4096 (
    .addr_i                 (b4096_addr),
    .byte_mask_i            (b4096_byte_mask),
    .scrambler_key_i        (b4096_key),
    .scrambled_addr_o       (b4096_scrambled_addr),
    .write_data_i           (b4096_write_data),
    .scrambled_write_data_o (b4096_scrambled_write_data),
    .scrambled_read_data_i  (b4096_scrambled_read_data),
    .read_data_o            (b4096_read_data)
  );

  scrambler_8192x32 #(
    .BYTE_WISE (0)
  ) u_w8192 (
    .addr_i                 (w8192_addr),
    .byte_mask_i            (w8192_byte_mask),
    .scrambler_key_i        (w8192_key),
    .scrambled_addr_o       (w8192_scrambled_addr),
    .write_data_i           (w8192_write_data),
    .scrambled_write_data_o (w8192_scrambled_write_data),
    .scrambled_read_data_i  (w8192_scrambled_read_data),
    .read_data_o            (w8192_read_data)
  );

  scrambler_8192x32 #(
    .BYTE_WISE (1)
  ) u_b8192 (
    .addr_i                 (b8192_addr),
    .byte_mask_i            (b8192_byte_mask),
    .scrambler_key_i        (b8192_key),
    .scrambled_addr_o       (b8192_scrambled_addr),
    .write_data_i           (b8192_write_data),
    .scrambled_write_data_o (b8192_scrambled_write_data),
    .scrambled_read_data_i  (b8192_scrambled_read_data),
    .read_data_o            (b8192_read_data)
  );

endmodule : scrambler_tb_top
