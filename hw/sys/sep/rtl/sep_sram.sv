// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare the port list of a SEP SRAM controller front-end for an external technology SRAM
// macro.
//
// The module body is empty: no output is driven and no input is used. The port clauses
// describe the intended interface: macro pins synchronous to sram_ck_o, an active-low chip
// enable and write enable, a clock stall, and a wipe command for the data memory.

module sep_sram #(
  parameter int unsigned DWIDTH = 32,         // Intended SRAM data width in bits; sizes the macro
                                              // ports only.
  parameter int unsigned PWIDTH = 5,          // Intended SRAM parity width in bits; sizes the macro
                                              // data ports only.
  parameter int unsigned AWIDTH = 14          // Intended SRAM address width in bits; sizes sram_a_o
                                              // only.
) (
  input  logic       clk_i,                   // System clock; unused.
  input  logic       rst_ni,                  // Active-low reset; unused.
  input  logic       stall_i,                 // Intended macro clock stall; unused.
  input  logic       wipe_i,                  // Intended command to clear the data memory; unused.
  output logic       irq_o,                   // Intended interrupt request; undriven.
  output logic [7:0] error_o,                 // Intended error status with no defined encoding;
                                              // undriven.

  output logic                     sram_ck_o,  // Intended macro clock to which all macro operations
                                               // are synchronous; undriven.
  output logic                     sram_cs_no,  // Intended macro chip enable, active-low; undriven.
  output logic                     sram_wen_o,  // Intended macro write enable, active-low;
                                                // undriven.
  output logic [DWIDTH-1:0]        sram_bwen_o,  // Intended macro bit-write mask; undriven.
  output logic [AWIDTH-1:0]        sram_a_o,  // Intended macro read/write address; undriven.
  output logic [DWIDTH+PWIDTH-1:0] sram_di_o,  // Intended macro write data including parity;
                                               // undriven.
  input  logic [DWIDTH+PWIDTH-1:0] sram_dout_i  // Intended macro read data including parity;
                                                // unused.
);

endmodule
