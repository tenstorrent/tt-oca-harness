// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_fifo.sv
 * @brief Fault-attack hardened entropy FIFO.
 *
 * @details Depth-parameterised 32-bit FIFO with fault-attack hardening via
 *          per-byte odd parity on all stored words and hardened read/write
 *          pointers. The pointer/level engine is delegated to OpenTitan's
 *          prim_fifo_sync_cnt (Secure=1), which duplicates each pointer in a
 *          prim_count and raises err_o on any mismatch. entropy_fifo remains a
 *          "smart wrapper": it keeps its own mem[] storage because the parity
 *          check and the entropy-churn read both need random access into the
 *          stored words, which a black-box FIFO cannot expose.
 *
 *          Entropy churning mode XORs incoming data with the existing entry at
 *          address (wptr + DEPTH/2) % DEPTH before storing. A security alert is
 *          raised on any parity or pointer error.
 *
 * @param DEPTH FIFO depth in words (default: 64)
 */

module entropy_fifo #(
  parameter int unsigned DEPTH = 64,
  localparam type ptr_t   = logic [$clog2(DEPTH)-1:0],
  localparam type level_t = logic [$clog2(DEPTH):0]
) (
  input       logic        clk_i,
  input       logic        rst_ni,
  input       logic        push_i,
  input       logic        pop_i,
  input       logic        clr_i,   // Synchronous flush: reset pointers/level to empty
  input       logic [31:0] wdata_i,
  input       logic        entropy_churn_enable_i,
  output      logic [31:0] rdata_o,
  output      level_t      level_o,
  output      ptr_t        wptr_o,
  output      ptr_t        rptr_o,
  output      logic        overflow_o,
  output      logic        underflow_o,
  output      logic        parity_error_o,
  output      logic        pointer_error_o,
  output      logic        security_alert_o
);

  /////////////////////
  // Local parameters
  /////////////////////

  // Memory: 32-bit data + 4 parity bits (one per byte, odd parity)
  // [35:32] = parity, [31:0] = data
  localparam int unsigned MEM_WIDTH = 36;

  //////////
  // Types
  //////////

  function automatic logic [3:0] calc_word_parity(input logic [31:0] data_word);
    calc_word_parity[0] = ^data_word[7:0];
    calc_word_parity[1] = ^data_word[15:8];
    calc_word_parity[2] = ^data_word[23:16];
    calc_word_parity[3] = ^data_word[31:24];
  endfunction

  /////////////
  // Signals
  /////////////

  // Pointer/level engine outputs (delegated to prim_fifo_sync_cnt).
  ptr_t wptr_prim, rptr_prim;
  level_t depth_prim;
  logic full_prim, empty_prim, counter_err;

  logic push_valid, pop_valid;

  logic [MEM_WIDTH-1:0] mem[DEPTH];

  logic [3:0] expected_parity, stored_parity;
  logic       parity_error_detected;

  ptr_t  churn_addr;
  logic [MEM_WIDTH-1:0] churn_entry;
  logic [31:0] churn_data;
  logic [31:0] final_wdata;

  logic [MEM_WIDTH-1:0] read_entry;
  logic [31:0]          read_data;

  ///////////////////////
  // Pointer/level engine
  ///////////////////////

  // Hardened pointer + occupancy tracking. Secure=1 duplicates each pointer
  // in a prim_count and asserts err_o on mismatch, upgrading the previous
  // single inverted-copy differential check to full duplication.
  prim_fifo_sync_cnt #(
    .Depth      (DEPTH),
    .Secure     (1'b1),
    .NeverClears(1'b0)
  ) u_fifo_cnt (
    .clk_i,
    .rst_ni,
    .clr_i,
    .incr_wptr_i (push_valid),
    .incr_rptr_i (pop_valid),
    .wptr_o      (wptr_prim),
    .rptr_o      (rptr_prim),
    .full_o      (full_prim),
    .empty_o     (empty_prim),
    .depth_o     (depth_prim),
    .err_o       (counter_err)
  );

  ///////////////
  // Sequential
  ///////////////

  // Memory write (no reset — memory is don't-care on reset). On a push_valid
  // cycle wptr_prim still holds the pre-increment address (prim_count commits
  // on the following edge), so the write address matches the old wptr_q.
  always_ff @(posedge clk_i) begin
    if (push_valid) begin
      mem[wptr_prim] <= {calc_word_parity(final_wdata), final_wdata};
    end
  end

  /////////////////
  // Combinational
  /////////////////

  // A synchronous flush discards any simultaneous push/pop this cycle. A push
  // or pop is also suppressed on a detected pointer (counter) error.
  assign push_valid = push_i & ~full_prim  & ~counter_err & ~clr_i;
  assign pop_valid  = pop_i  & ~empty_prim & ~counter_err & ~clr_i;

  // A push/pop swallowed by a flush is intentional, not an over/underflow.
  assign overflow_o  = push_i & full_prim  & ~clr_i;
  assign underflow_o = pop_i  & empty_prim & ~clr_i;

  // Churning: XOR incoming word with entry halfway around the FIFO
  assign churn_addr  = ptr_t'((unsigned'(wptr_prim) + unsigned'(DEPTH/2)) % unsigned'(DEPTH));
  assign churn_entry = mem[churn_addr];
  assign churn_data  = churn_entry[31:0];
  assign final_wdata = entropy_churn_enable_i ? (wdata_i ^ churn_data) : wdata_i;

  assign read_entry            = mem[rptr_prim];
  assign read_data             = read_entry[31:0];
  assign stored_parity         = read_entry[35:32];
  assign expected_parity       = calc_word_parity(read_data);
  assign parity_error_detected = (expected_parity != stored_parity) & ~empty_prim;

  ///////////
  // Output
  ///////////

  assign parity_error_o   = parity_error_detected & ~empty_prim; // Ensure prim FIFO is not empty before outputting parity check. Don't want to check parity on power-up garbage
  assign pointer_error_o  = counter_err;
  assign rdata_o          = read_data & {32{~empty_prim}};
  assign wptr_o           = wptr_prim;
  assign rptr_o           = rptr_prim;
  assign level_o          = depth_prim;
  assign security_alert_o = parity_error_o | pointer_error_o;

endmodule
