// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SEP external SRAM interface
//
//-----------------------------------------------------------------------------

module sep_sram #(
  parameter int unsigned DWIDTH = 32,
  parameter int unsigned PWIDTH = 5,
  parameter int unsigned AWIDTH = 14
) (
  input  logic       clk_i,
  input  logic       rst_ni,
  input  logic       stall_i, // clock stall
  input  logic       wipe_i,  // command to clear data memory
  output logic       irq_o,   // interrupt request
  output logic [7:0] error_o, // encoding TBD

  // AXI4-lite slave interface for data and CSR access


  // external memory macro function interface
  output logic                     sram_ck,     // all operations synchronous
  output logic                     sram_csn,    // chip enable, active low
  output logic                     sram_wen_o,  // write enable, active low
  output logic [DWIDTH-1:0]        sram_bwen_o, // bit-write mask
  output logic [AWIDTH-1:0]        sram_a_o,    // read/write address
  output logic [DWIDTH+PWIDTH-1:0] sram_di_i,   // data input bus
  input  logic [DWIDTH+PWIDTH-1:0] sram_dout_o  // data output bus
);

endmodule
