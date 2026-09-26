// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// KPV per-slot erase controller that overwrites one key slot with LFSR data.
//
// An FSM walks WORDS_PER_SLOT words of the selected slot, emitting a logical
// {slot, word} address and a maximal-length Galois LFSR data word for the
// parent to scramble into the key regfile. Pending erases are serviced
// lowest-index first and are not gated by lock bits; erase_done_o pulses for
// one cycle when the last word of a slot is written. The LFSR seeds to
// all-ones on cold reset only.

module km_kpv_eraser #(
  parameter int unsigned NUM_SLOTS      = 64,  // Number of key slots
  parameter int unsigned WORDS_PER_SLOT = 16,  // Words per key slot
  parameter int unsigned DATA_WIDTH     = 32   // Key-data and LFSR width
) (
  input  logic                              clk_i,        // System clock
  input  logic                              cold_rst_ni,  // Cold reset (AASD); seeds LFSR all-ones
  input  logic [NUM_SLOTS-1:0]              erase_req_i,  // Per-slot erase requests from CTRL.erase
  output logic                              wr_en_o,      // Regfile write enable for erase stream
  output logic [$clog2(NUM_SLOTS)-1:0]      wr_slot_o,    // Logical slot index being erased
  output logic [$clog2(WORDS_PER_SLOT)-1:0] wr_word_o,    // Word index within the active slot
  output logic [DATA_WIDTH-1:0]             wr_data_o,    // Pseudo-random erase data from LFSR
  output logic [NUM_SLOTS-1:0]              erase_done_o, // One-cycle pulse when a slot erase finishes
  output logic                              busy_o        // High while an erase owns the write port
);

  localparam int unsigned SLOT_W = $clog2(NUM_SLOTS);
  localparam int unsigned WORD_W = $clog2(WORDS_PER_SLOT);
  localparam logic [WORD_W-1:0] LAST_WORD = WORD_W'(WORDS_PER_SLOT - 1);

  // =========================================================================
  // Pseudo-random source: maximal-length Galois LFSR, one bit per data bit.
  // Seeded all-ones on cold reset only.  Advanced once per word written.
  // =========================================================================
  logic [DATA_WIDTH-1:0] rnd_word;
  logic                  lfsr_en;

  prim_lfsr #(
    .LfsrType    ("GAL_XOR"),
    .LfsrDw      (DATA_WIDTH),
    .StateOutDw  (DATA_WIDTH),
    .DefaultSeed ({DATA_WIDTH{1'b1}})
  ) u_lfsr (
    .clk_i     (clk_i),
    .rst_ni    (cold_rst_ni),
    .seed_en_i (1'b0),
    .seed_i    ('0),
    .lfsr_en_i (lfsr_en),
    .entropy_i ('0),
    .state_o   (rnd_word)
  );

  // =========================================================================
  // Erase FSM
  // =========================================================================
  typedef enum logic {
    IDLE    = 1'b0,
    ERASING = 1'b1
  } erase_state_e;

  erase_state_e state_q, state_d;
  logic [SLOT_W-1:0] slot_q, slot_d;
  logic [WORD_W-1:0] word_q, word_d;

  // Lowest-index pending erase request (priority encoder)
  logic              req_pending;
  logic [SLOT_W-1:0] req_slot;
  always_comb begin
    req_pending = 1'b0;
    req_slot    = '0;
    for (int i = NUM_SLOTS - 1; i >= 0; i--) begin
      if (erase_req_i[i]) begin
        req_pending = 1'b1;
        req_slot    = SLOT_W'(i);
      end
    end
  end

  always_comb begin
    // Defaults
    state_d      = state_q;
    slot_d       = slot_q;
    word_d       = word_q;
    wr_en_o      = 1'b0;
    lfsr_en      = 1'b0;
    erase_done_o = '0;
    wr_slot_o    = slot_q;
    wr_word_o    = word_q;
    wr_data_o    = rnd_word;
    busy_o       = (state_q == ERASING);

    unique case (state_q)
      IDLE: begin
        if (req_pending) begin
          state_d = ERASING;
          slot_d  = req_slot;
          word_d  = '0;
        end
      end

      ERASING: begin
        // Write the current word with the current LFSR output, and
        // advance the LFSR so the next word gets fresh random data.
        wr_en_o = 1'b1;
        lfsr_en = 1'b1;
        if (word_q == LAST_WORD) begin
          erase_done_o[slot_q] = 1'b1;
          state_d              = IDLE;
        end else begin
          word_d = word_q + WORD_W'(1);
        end
      end

      default: state_d = IDLE;
    endcase
  end

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      state_q <= IDLE;
      slot_q  <= '0;
      word_q  <= '0;
    end else begin
      state_q <= state_d;
      slot_q  <= slot_d;
      word_q  <= word_d;
    end
  end

endmodule : km_kpv_eraser

