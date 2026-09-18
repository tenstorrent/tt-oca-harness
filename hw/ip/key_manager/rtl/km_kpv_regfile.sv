// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

/**
 * @file km_kpv_regfile.sv
 * @brief Single-write, single-read register file for KPV key data storage.
 *
 * @details Stores NUM_SLOTS x WORDS_PER_SLOT entries of DATA_WIDTH bits.
 *          - Write port: KM (Key Manager CPU).
 *          - Read port: KM only (combinational, zero-latency).
 *
 *          No reset for key data storage: power-up value is
 *          undefined for security.  The wipe input provides synchronous
 *          bulk-clear of all entries.
 *
 * @param NUM_SLOTS       Number of key slots (default 64).
 * @param WORDS_PER_SLOT  Words per slot (default 16).
 * @param DATA_WIDTH      Data width in bits (default 32).
 */

module km_kpv_regfile #(
  parameter int unsigned NUM_SLOTS      = 64,
  parameter int unsigned WORDS_PER_SLOT = 16,
  parameter int unsigned DATA_WIDTH     = 32
) (
  input  logic                                    clk_i,

  // Bulk wipe: zeroes ALL entries on the next clock edge
  input  logic                                    wipe_i,

  // Write port (KM)
  input  logic                                    wr_a_en_i,
  input  logic [$clog2(NUM_SLOTS*WORDS_PER_SLOT)-1:0] wr_a_addr_i,
  input  logic [DATA_WIDTH-1:0]                   wr_a_data_i,

  // Read port (KM only, combinational)
  input  logic [$clog2(NUM_SLOTS*WORDS_PER_SLOT)-1:0] rd_addr_i,
  output logic [DATA_WIDTH-1:0]                        rd_data_o
);

  /** @brief Derived address geometry for the flat storage array. */
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

