// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Drive an external technology SRAM macro from the SEP SRAM controller front-end.
//
// All macro operations are synchronous to sram_ck_o. sram_cs_no is active-low chip enable;
// sram_wen_o is active-low write enable.
// stall_i gates the macro clock. wipe_i clears data memory and may raise irq_o. error_o
// encoding is TBD.

module sep_sram #(
  parameter int unsigned DWIDTH = 32,         // SRAM data width.
  parameter int unsigned PWIDTH = 5,          // SRAM parity width.
  parameter int unsigned AWIDTH = 14          // SRAM address width.
) (
  input  logic       clk_i,                   // System clock.
  input  logic       rst_ni,                  // Active-low reset.
  input  logic       stall_i,                 // clock stall.
  input  logic       wipe_i,                  // command to clear data memory.
  output logic       irq_o,                   // interrupt request.
  output logic [7:0] error_o,                 // encoding TBD.

  output logic                     sram_ck_o,  // AXI4-lite slave interface for data and CSR access
                                               // external memory macro function interface
                                               // all operations synchronous.
  output logic                     sram_cs_no,  // chip enable, active low.
  output logic                     sram_wen_o,  // write enable, active low.
  output logic [DWIDTH-1:0]        sram_bwen_o,  // bit-write mask.
  output logic [AWIDTH-1:0]        sram_a_o,  // read/write address.
  output logic [DWIDTH+PWIDTH-1:0] sram_di_o,  // data input bus.
  input  logic [DWIDTH+PWIDTH-1:0] sram_dout_i  // data output bus.
);

endmodule
