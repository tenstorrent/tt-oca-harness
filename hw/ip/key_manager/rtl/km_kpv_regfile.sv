// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Store KPV key data in a single-write, single-read register file.
//
// Stores NUM_SLOTS x WORDS_PER_SLOT entries of DATA_WIDTH bits.
//
// - Write port: KM; in km_kpv it carries CPU writes and, while an erase runs, the
//   eraser's writes.
// - Read port: KM only (combinational, zero-latency).
//
// Key data storage has no reset: the power-up value is undefined for security. The wipe
// input provides a synchronous bulk-clear of all entries and takes priority over a write
// in the same cycle.

module km_kpv_regfile #(
  parameter int unsigned NUM_SLOTS      = 64,  // Number of key slots.
  parameter int unsigned WORDS_PER_SLOT = 16,  // Key-data words in each slot; the file holds
                                               // NUM_SLOTS * WORDS_PER_SLOT entries.
  parameter int unsigned DATA_WIDTH     = 32   // Data width in bits.
) (
  input  logic                                    clk_i,  // System clock.

  input  logic                                    wipe_i,  // Bulk wipe: zeroes ALL entries on
                                                           // the next clock edge, overriding
                                                           // any write.

  input  logic                                    wr_a_en_i,        // KM write port enable.
  input  logic [$clog2(NUM_SLOTS*WORDS_PER_SLOT)-1:0] wr_a_addr_i,  // KM write port flat address.
  input  logic [DATA_WIDTH-1:0]                   wr_a_data_i,      // KM write port data.

  input  logic [$clog2(NUM_SLOTS*WORDS_PER_SLOT)-1:0] rd_addr_i,  // KM-only read port flat address.
  output logic [DATA_WIDTH-1:0]                        rd_data_o  // KM-only read data
                                                                  // (combinational).
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

