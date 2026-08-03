// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file km_kpv_eraser.sv
 * @brief KPV per-slot erase controller.
 *
 * @details Drives a hardware erase of a single KPV key slot when its CTRL
 *          erase bit is asserted.  An FSM walks the 16 words of the selected
 *          slot, emitting a logical {slot, word} address and a pseudo-random
 *          data word sourced from a maximal-length LFSR (prim_lfsr, GAL_XOR).
 *          The parent (km_kpv) routes these through the shared KPV scrambler
 *          and into the key register file, so the slot is overwritten with
 *          scrambled random data.  When the last word is written a one-cycle
 *          erase_done pulse is emitted so the parent can clear the slot CTRL
 *          register (including the self-clearing erase bit and the lock bits).
 *
 *          Multiple pending erase requests are serviced sequentially, lowest
 *          slot index first.  Erase is intentionally not gated by the slot
 *          lock_write/lock_use bits.
 *
 *          The LFSR is seeded to all-ones on cold reset only (no warm reset);
 *          the exact seed value is not security-relevant.
 *
 * @param NUM_SLOTS       Number of key slots (default 32).
 * @param WORDS_PER_SLOT  Words per slot (default 16).
 */

module km_kpv_eraser #(
    parameter int unsigned NUM_SLOTS      = 32,
    parameter int unsigned WORDS_PER_SLOT = 16
) (
    input  logic                 clk_i,
    input  logic                 cold_rst_ni,   // Cold reset (AASD); seeds LFSR all-ones

    // Per-slot erase requests (CTRL[i].erase.value)
    input  logic [NUM_SLOTS-1:0] erase_req_i,

    // Register-file write stream (logical address; parent applies scrambler)
    output logic                          wr_en_o,
    output logic [$clog2(NUM_SLOTS)-1:0]  wr_slot_o,
    output logic [$clog2(WORDS_PER_SLOT)-1:0] wr_word_o,
    output logic [31:0]                   wr_data_o,

    // One-cycle pulse per slot when its erase completes (last word written)
    output logic [NUM_SLOTS-1:0]      erase_done_o,

    // High while an erase is in progress (parent gives this priority on the
    // shared scrambler / regfile write port)
    output logic                      busy_o
);

    localparam int unsigned SLOT_W = $clog2(NUM_SLOTS);
    localparam int unsigned WORD_W = $clog2(WORDS_PER_SLOT);
    localparam logic [WORD_W-1:0] LAST_WORD = WORD_W'(WORDS_PER_SLOT - 1);

    // =========================================================================
    // Pseudo-random source: maximal-length 32-bit Galois LFSR.
    // Seeded all-ones on cold reset only.  Advanced once per word written.
    // =========================================================================
    logic [31:0] rnd_word;
    logic        lfsr_en;

    prim_lfsr #(
        .LfsrType    ("GAL_XOR"),
        .LfsrDw      (32),
        .StateOutDw  (32),
        .DefaultSeed (32'hFFFF_FFFF)
    ) u_lfsr (
        .clk_i     (clk_i),
        .rst_ni    (cold_rst_ni),
        .seed_en_i (1'b0),
        .seed_i    (32'h0),
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

    erase_state_e          state_q, state_d;
    logic [SLOT_W-1:0]     slot_q, slot_d;
    logic [WORD_W-1:0]     word_q, word_d;

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

