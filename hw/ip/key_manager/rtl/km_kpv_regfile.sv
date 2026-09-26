// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Single-write, single-read register file for KPV key data.
//
// Stores NUM_SLOTS x WORDS_PER_SLOT entries of DATA_WIDTH bits with a KM write
// port and a combinational KM read port. Key storage has no reset so power-up
// values are undefined; wipe_i synchronously zeroes every entry on the next
// clock edge.

module km_kpv_regfile #(
  parameter int unsigned NUM_SLOTS      = 64,  // Number of key slots
  parameter int unsigned WORDS_PER_SLOT = 16,  // Words per key slot
  parameter int unsigned DATA_WIDTH     = 32   // Key-data word width
) (
  input  logic                                        clk_i,       // System clock
  input  logic                                        wipe_i,      // Bulk-zero all entries next cycle
  input  logic                                        wr_a_en_i,   // KM write enable
  input  logic [$clog2(NUM_SLOTS*WORDS_PER_SLOT)-1:0] wr_a_addr_i, // KM flat write address
  input  logic [DATA_WIDTH-1:0]                       wr_a_data_i, // KM write data
  input  logic [$clog2(NUM_SLOTS*WORDS_PER_SLOT)-1:0] rd_addr_i,   // KM flat read address
  output logic [DATA_WIDTH-1:0]                       rd_data_o    // Combinational KM read data
);

  // Derived address geometry for the flat storage array.
  localparam int unsigned NUM_ENTRIES = NUM_SLOTS * WORDS_PER_SLOT;

  // Storage array: NO RESET for security.
  // Power-up value is undefined/random.
  logic [DATA_WIDTH-1:0] mem[NUM_ENTRIES];

  always_ff @(posedge clk_i) begin
    if (wipe_i) begin
      // Bulk wipe: zero every entry
      for (int unsigned i = 0; i < NUM_ENTRIES; i++) mem[i] <= '0;
    end else begin
      if (wr_a_en_i) mem[wr_a_addr_i] <= wr_a_data_i;
    end
  end

  // Read port: combinational (zero-latency)
  assign rd_data_o = mem[rd_addr_i];

endmodule : km_kpv_regfile

