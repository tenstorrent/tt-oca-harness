// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// External RAM Interface Package for Advanced Memory Primitives
//
//--------------------------------------------------
package prim_ram_1p_adv_ext_pkg;

  import prim_ram_1p_pkg::*;

  // Default external RAM request struct
  // Can be overridden with custom types in module instantiation
  typedef struct packed {
    logic         clk;      // Clock for external RAM
    logic         enable;   // RAM request enable
    logic         write;    // Write enable
    logic [31:0]  addr;     // Address (32-bit default, parameterizable)
    logic [38:0]  wdata;    // Write data (32-bit default, parameterizable)
    logic [31:0]  wmask;    // Write mask (32-bit default, parameterizable)
  } prim_ram_1p_adv_ext_req_t;

  // Default external RAM response struct
  // Can be overridden with custom types in module instantiation
  typedef struct packed {
    logic [31:0] rdata;  // Read data (32-bit default, parameterizable)
  } prim_ram_1p_adv_ext_rsp_t;

endpackage : prim_ram_1p_adv_ext_pkg
