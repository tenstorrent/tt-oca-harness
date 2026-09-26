// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Hold PRESENT sbox and permute helpers for SRAM data and address scrambling.
//
// Provides the nibble S-box, 32-bit and 8-bit permutations, and their inverses.

package scrambler_pkg;
  // Pyjamask lightweight cipher substitution function
  function automatic logic [2:0] sbox3(input logic [2:0] d);
    unique case (d)
      3'h0: return 3'h1;
      3'h1: return 3'h3;
      3'h2: return 3'h6;
      3'h3: return 3'h5;
      3'h4: return 3'h2;
      3'h5: return 3'h4;
      3'h6: return 3'h7;
      3'h7: return 3'h0;
      default: return 3'hx;
    endcase
  endfunction

  // Pyjamask lightweight cipher inverse substitution function
  function automatic logic [2:0] ibox3(input logic [2:0] d);
    unique case (d)
      3'h1: return 3'h0;
      3'h3: return 3'h1;
      3'h6: return 3'h2;
      3'h5: return 3'h3;
      3'h2: return 3'h4;
      3'h4: return 3'h5;
      3'h7: return 3'h6;
      3'h0: return 3'h7;
      default: return 3'hx;
    endcase
  endfunction

  // PRESENT lightweight cipher substitution function
  function automatic logic [3:0] sbox4(input logic [3:0] d);
    unique case (d)
      4'h0: return 4'hc;
      4'h1: return 4'h5;
      4'h2: return 4'h6;
      4'h3: return 4'hb;
      4'h4: return 4'h9;
      4'h5: return 4'h0;
      4'h6: return 4'ha;
      4'h7: return 4'hd;
      4'h8: return 4'h3;
      4'h9: return 4'he;
      4'ha: return 4'hf;
      4'hb: return 4'h8;
      4'hc: return 4'h4;
      4'hd: return 4'h7;
      4'he: return 4'h1;
      4'hf: return 4'h2;
      default: return 4'hx;
    endcase
  endfunction

  // PRESENT lightweight cipher inverse substitution function
  function automatic logic [3:0] ibox4(input logic [3:0] d);
    unique case (d)
      4'hc: return 4'h0;
      4'h5: return 4'h1;
      4'h6: return 4'h2;
      4'hb: return 4'h3;
      4'h9: return 4'h4;
      4'h0: return 4'h5;
      4'ha: return 4'h6;
      4'hd: return 4'h7;
      4'h3: return 4'h8;
      4'he: return 4'h9;
      4'hf: return 4'ha;
      4'h8: return 4'hb;
      4'h4: return 4'hc;
      4'h7: return 4'hd;
      4'h1: return 4'he;
      4'h2: return 4'hf;
      default: return 4'hx;
    endcase
  endfunction

  // PRESENT Permutation Layer
  function automatic logic [31:0] perm32(input logic [31:0] d);
    return {
      d[0],
      d[8],
      d[16],
      d[24],

      d[1],
      d[9],
      d[17],
      d[25],

      d[2],
      d[10],
      d[18],
      d[26],

      d[3],
      d[11],
      d[19],
      d[27],

      d[4],
      d[12],
      d[20],
      d[28],

      d[5],
      d[13],
      d[21],
      d[29],

      d[6],
      d[14],
      d[22],
      d[30],

      d[7],
      d[15],
      d[23],
      d[31]
    };
  endfunction

  // PRESENT Inverse Permutation Layer
  function automatic logic [31:0] iperm32(input logic [31:0] d);
    return {
      d[0],
      d[4],
      d[8],
      d[12],

      d[16],
      d[20],
      d[24],
      d[28],

      d[1],
      d[5],
      d[9],
      d[13],

      d[17],
      d[21],
      d[25],
      d[29],

      d[2],
      d[6],
      d[10],
      d[14],

      d[18],
      d[22],
      d[26],
      d[30],

      d[3],
      d[7],
      d[11],
      d[15],

      d[19],
      d[23],
      d[27],
      d[31]
    };
  endfunction

  // Permutation functions

  function automatic logic [5:0] perm6(input logic [5:0] d);
    return {d[1], d[4], d[2], d[5], d[0], d[3]};
  endfunction

  function automatic logic [6:0] perm7(input logic [6:0] d);
    return {d[1], d[5], d[2], d[6], d[4], d[0], d[3]};
  endfunction

  function automatic logic [7:0] perm8(input logic [7:0] d);
    return {d[1], d[4], d[0], d[2], d[3], d[7], d[5], d[6]};
  endfunction

  function automatic logic [8:0] perm9(input logic [8:0] d);
    return {d[1], d[5], d[8], d[2], d[6], d[0], d[4], d[7], d[3]};
  endfunction

  function automatic logic [9:0] perm10(input logic [9:0] d);
    return {d[1], d[5], d[8], d[2], d[6], d[9], d[4], d[7], d[0], d[3]};
  endfunction

  function automatic logic [10:0] perm11(input logic [10:0] d);
    return {d[1], d[5], d[9], d[2], d[6], d[10], d[8], d[7], d[0], d[4], d[3]};
  endfunction

  function automatic logic [11:0] perm12(input logic [11:0] d);
    return {d[1], d[4], d[7], d[10], d[2], d[5], d[8], d[11], d[0], d[6], d[9], d[3]};
  endfunction

  function automatic logic [12:0] perm13(input logic [12:0] d);
    return {d[1], d[5], d[8], d[11], d[2], d[6], d[9], d[12], d[4], d[7], d[10], d[0], d[3]};
  endfunction

  function automatic logic [13:0] perm14(input logic [13:0] d);
    return {d[1], d[5], d[9], d[12], d[2], d[6], d[10], d[13], d[8], d[7], d[11], d[0], d[4], d[3]};
  endfunction

  function automatic logic [14:0] perm15(input logic [14:0] d);
    return {
      d[1], d[5], d[9], d[13], d[2], d[6], d[10], d[14], d[12], d[7], d[11], d[0], d[4], d[8], d[3]
    };
  endfunction

  function automatic logic [15:0] perm16(input logic [15:0] d);
    return {
      d[1],
      d[5],
      d[9],
      d[13],
      d[2],
      d[6],
      d[10],
      d[14],
      d[0],
      d[7],
      d[11],
      d[15],
      d[4],
      d[8],
      d[12],
      d[3]
    };
  endfunction


  // ROL - Rotate Left functions enumerated for input data width range [6,16]
  // The barrel shifter uses a triple-replicated (or double for powers-of-2)
  // extended word; only the top WIDTH bits of the final stage are returned.
  // The lower bits of intermediate signals are intentionally unused.
  /* verilator lint_off UNUSEDSIGNAL */
  function automatic logic [5:0] rol6(input logic [5:0] d, input logic [2:0] r);
    localparam int WIDTH = 6;
    localparam int IWIDTH = 3 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2;

    d_xtnd = {d,d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    return d_xtnd_s2[IWIDTH-1:IWIDTH-WIDTH];
  endfunction

  function automatic logic [6:0] rol7(input logic [6:0] d, input logic [2:0] r);
    localparam int WIDTH = 7;
    localparam int IWIDTH = 3 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2;

    d_xtnd = {d,d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    return d_xtnd_s2[IWIDTH-1:IWIDTH-WIDTH];
  endfunction

  function automatic logic [7:0] rol8(input logic [7:0] d, input logic [2:0] r);
    localparam int WIDTH = 8;
    localparam int IWIDTH = 2 * WIDTH;
    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2;

    d_xtnd = {d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    return d_xtnd_s2[IWIDTH-1:IWIDTH-WIDTH];
  endfunction

  function automatic logic [8:0] rol9(input logic [8:0] d, input logic [3:0] r);
    localparam int WIDTH = 9;
    localparam int IWIDTH = 3 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2, d_xtnd_s3;

    d_xtnd = {d,d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    d_xtnd_s3 = r[3] ? d_xtnd_s2 << 8 : d_xtnd_s2;
    return d_xtnd_s3[IWIDTH-1:IWIDTH-WIDTH];
  endfunction

  function automatic logic [9:0] rol10(input logic [9:0] d, input logic [3:0] r);
    localparam int WIDTH = 10;
    localparam int IWIDTH = 3 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2, d_xtnd_s3;

    d_xtnd = {d,d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    d_xtnd_s3 = r[3] ? d_xtnd_s2 << 8 : d_xtnd_s2;
    return d_xtnd_s3[IWIDTH-1:IWIDTH-WIDTH];
  endfunction

  function automatic logic [10:0] rol11(input logic [10:0] d, input logic [3:0] r);
    localparam int WIDTH = 11;
    localparam int IWIDTH = 3 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2, d_xtnd_s3;

    d_xtnd = {d,d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    d_xtnd_s3 = r[3] ? d_xtnd_s2 << 8 : d_xtnd_s2;
    return d_xtnd_s3[IWIDTH-1:IWIDTH-WIDTH];
  endfunction

  function automatic logic [11:0] rol12(input logic [11:0] d, input logic [3:0] r);
    localparam int WIDTH = 12;
    localparam int IWIDTH = 3 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2, d_xtnd_s3;

    d_xtnd = {d,d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    d_xtnd_s3 = r[3] ? d_xtnd_s2 << 8 : d_xtnd_s2;
    return d_xtnd_s3[IWIDTH-1:IWIDTH-WIDTH];
  endfunction


  function automatic logic [12:0] rol13(input logic [12:0] d, input logic [3:0] r);
    localparam int WIDTH = 13;
    localparam int IWIDTH = 3 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2, d_xtnd_s3;

    d_xtnd = {d,d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    d_xtnd_s3 = r[3] ? d_xtnd_s2 << 8 : d_xtnd_s2;
    return d_xtnd_s3[IWIDTH-1:IWIDTH-WIDTH];
  endfunction

  function automatic logic [13:0] rol14(input logic [13:0] d, input logic [3:0] r);
    localparam int WIDTH = 14;
    localparam int IWIDTH = 3 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2, d_xtnd_s3;

    d_xtnd = {d,d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    d_xtnd_s3 = r[3] ? d_xtnd_s2 << 8 : d_xtnd_s2;
    return d_xtnd_s3[IWIDTH-1:IWIDTH-WIDTH];
  endfunction

  function automatic logic [14:0] rol15(input logic [14:0] d, input logic [3:0] r);
    localparam int WIDTH = 15;
    localparam int IWIDTH = 3 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2, d_xtnd_s3;

    d_xtnd = {d,d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    d_xtnd_s3 = r[3] ? d_xtnd_s2 << 8 : d_xtnd_s2;
    return d_xtnd_s3[IWIDTH-1:IWIDTH-WIDTH];
  endfunction

  function automatic logic [15:0] rol16(input logic [15:0] d, input logic [3:0] r);
    localparam int WIDTH = 16;
    localparam int IWIDTH = 2 * WIDTH;

    logic [IWIDTH-1:0] d_xtnd;
    logic [IWIDTH-1:0] d_xtnd_s0, d_xtnd_s1, d_xtnd_s2, d_xtnd_s3;

    d_xtnd = {d,d};
    d_xtnd_s0 = r[0] ? d_xtnd    << 1 : d_xtnd;
    d_xtnd_s1 = r[1] ? d_xtnd_s0 << 2 : d_xtnd_s0;
    d_xtnd_s2 = r[2] ? d_xtnd_s1 << 4 : d_xtnd_s1;
    d_xtnd_s3 = r[3] ? d_xtnd_s2 << 8 : d_xtnd_s2;
    return d_xtnd_s3[IWIDTH-1:IWIDTH-WIDTH];
  endfunction
  /* verilator lint_on UNUSEDSIGNAL */


  // Inverse permutation functions for address widths 6-16.
  // Derived from permN: if permN maps input bit i to output bit j,
  // then ipermN maps input bit j to output bit i.

  function automatic logic [5:0] iperm6(input logic [5:0] d);
    return {d[2], d[4], d[0], d[3], d[5], d[1]};
  endfunction

  function automatic logic [6:0] iperm7(input logic [6:0] d);
    return {d[3], d[5], d[2], d[0], d[4], d[6], d[1]};
  endfunction

  function automatic logic [7:0] iperm8(input logic [7:0] d);
    return {d[2], d[0], d[1], d[6], d[3], d[4], d[7], d[5]};
  endfunction

  function automatic logic [8:0] iperm9(input logic [8:0] d);
    return {d[6], d[1], d[4], d[7], d[2], d[0], d[5], d[8], d[3]};
  endfunction

  function automatic logic [9:0] iperm10(input logic [9:0] d);
    return {d[4], d[7], d[2], d[5], d[8], d[3], d[0], d[6], d[9], d[1]};
  endfunction

  function automatic logic [10:0] iperm11(input logic [10:0] d);
    return {d[5], d[8], d[4], d[3], d[6], d[9], d[1], d[0], d[7], d[10], d[2]};
  endfunction

  function automatic logic [11:0] iperm12(input logic [11:0] d);
    return {d[4], d[8], d[1], d[5], d[9], d[2], d[6], d[10], d[0], d[7], d[11], d[3]};
  endfunction

  function automatic logic [12:0] iperm13(input logic [12:0] d);
    return {d[5], d[9], d[2], d[6], d[10], d[3], d[7], d[11], d[4], d[0], d[8], d[12], d[1]};
  endfunction

  function automatic logic [13:0] iperm14(input logic [13:0] d);
    return {d[6], d[10], d[3], d[7], d[11], d[5], d[4], d[8], d[12], d[1], d[0], d[9], d[13], d[2]};
  endfunction

  function automatic logic [14:0] iperm15(input logic [14:0] d);
    return {
      d[7], d[11], d[6], d[4], d[8], d[12], d[1], d[5], d[9], d[13], d[2], d[0], d[10], d[14], d[3]
    };
  endfunction

  function automatic logic [15:0] iperm16(input logic [15:0] d);
    return {
      d[4],
      d[8],
      d[12],
      d[1],
      d[5],
      d[9],
      d[13],
      d[2],
      d[6],
      d[10],
      d[14],
      d[3],
      d[0],
      d[11],
      d[15],
      d[7]
    };
  endfunction

  // address scramblers: add round key, apply sbox, apply permutation
  function automatic logic [5:0] addr_scramble6(input logic [5:0] addr, input logic [5:0] key);
    logic [5:0] ark;
    logic [5:0] sb;
    ark = addr ^ key;
    sb = {sbox3(ark[5:3]), sbox3(ark[2:0])};
    return perm6(sb);
  endfunction

  function automatic logic [6:0] addr_scramble7(input logic [6:0] addr, input logic [6:0] key);
    logic [6:0] ark;
    logic [6:0] sb;
    ark = addr ^ key;
    sb = {sbox4(ark[6:3]), sbox3(ark[2:0])};
    return perm7(sb);
  endfunction

  function automatic logic [7:0] addr_scramble8(input logic [7:0] addr, input logic [7:0] key);
    logic [7:0] ark;
    logic [7:0] sb;
    ark = addr ^ key;
    sb = {sbox4(ark[7:4]), sbox4(ark[3:0])};
    return perm8(sb);
  endfunction

  function automatic logic [8:0] addr_scramble9(input logic [8:0] addr, input logic [8:0] key);
    logic [8:0] ark;
    logic [8:0] sb;
    ark = addr ^ key;
    sb = {sbox3(ark[8:6]), sbox3(ark[5:3]), sbox3(ark[2:0])};
    return perm9(sb);
  endfunction

  function automatic logic [9:0] addr_scramble10(input logic [9:0] addr, input logic [9:0] key);
    logic [9:0] ark;
    logic [9:0] sb;
    ark = addr ^ key;
    sb = {sbox4(ark[9:6]), sbox3(ark[5:3]), sbox3(ark[2:0])};
    return perm10(sb);
  endfunction

  function automatic logic [10:0] addr_scramble11(input logic [10:0] addr, input logic [10:0] key);
    logic [10:0] ark;
    logic [10:0] sb;
    ark = addr ^ key;
    sb = {sbox3(ark[10:8]), sbox4(ark[7:4]), sbox4(ark[3:0])};
    return perm11(sb);
  endfunction

  function automatic logic [11:0] addr_scramble12(input logic [11:0] addr, input logic [11:0] key);
    logic [11:0] ark;
    logic [11:0] sb;
    ark = addr ^ key;
    sb = {sbox4(ark[11:8]), sbox4(ark[7:4]), sbox4(ark[3:0])};
    return perm12(sb);
  endfunction

  function automatic logic [12:0] addr_scramble13(input logic [12:0] addr, input logic [12:0] key);
    logic [12:0] ark;
    logic [12:0] sb;
    ark = addr ^ key;
    sb = {sbox4(ark[12:9]), sbox3(ark[8:6]), sbox3(ark[5:3]), sbox3(ark[2:0])};
    return perm13(sb);
  endfunction



endpackage
