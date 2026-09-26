// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare default external RAM request and response structs for prim_ram_1p_adv_ext.
//
// Modules may override ram_req_t and ram_rsp_t with tighter typed structs at instantiation.
// Request fields carry clk, enable, write, addr, wdata, and wmask; the response carries
// rdata.

package prim_ram_1p_adv_ext_pkg;

  import prim_ram_1p_pkg::*;

  // Default external RAM request; an instantiation can override it with its own type.
  typedef struct packed {
    logic         clk;      // Clock for external RAM.
    logic         enable;   // RAM request enable.
    logic         write;    // Write enable.
    logic [31:0]  addr;     // Word address.
    logic [38:0]  wdata;    // Write data with its check bits; 39 bits holds 32 data
                            // bits plus 7 ECC bits.
    logic [31:0]  wmask;    // Per-bit write mask.
  } prim_ram_1p_adv_ext_req_t;

  // Default external RAM response; an instantiation can override it with its own type.
  typedef struct packed {
    logic [31:0] rdata;  // Read data.
  } prim_ram_1p_adv_ext_rsp_t;

endpackage : prim_ram_1p_adv_ext_pkg
