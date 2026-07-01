// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
//
// Entropy FIFO with Fault Attack Resilience and Churning Mode
//
// This is a FIFO containing 32-bit words with security enhancements:
// - Depth is parameterized with default of 64 words
// - Bytewise odd-parity checking on stored data
// - Differential pointer storage (normal and inverted) for fault detection
// - Error detection and reporting for parity and pointer faults
// - Optional entropy churning mode for enhanced randomness
//
// On a push command, a 32-bit data word is pushed into the FIFO and written to
// the entry pointed to by the write pointer wptr_o. The wptr_o is incremented
// after the push and the level counter is also incremented.
// On a pop command, one 32-bit data word is read from the entry pointed to by
// rptr_o. The rptr_o is incremented by 1 after the pop  and the level counter
// is decremented by 1 as well.
// The overflow signal is asserted if a push is attempted on a full FIFO i.e.
// the level is at DEPTH.
// The underflow signal is asserted if a pop is attempted on a FIFO having level 0.
//
// Security Features:
// - Each 32-bit data word is stored with 4-bit odd parity (one per byte)
// - Write and read pointers are stored differentially (normal + inverted)
// - Continuous error checking with interrupt generation for fault detection
//
// Entropy Churning Mode (entropy_churn_enable_i):
// - When enabled, incoming entropy is XORed with existing FIFO data
// - Churning address: (write_ptr + DEPTH/2) % DEPTH (halfway around buffer)
// - Operation: final_data = incoming_data XOR mem[churning_address]
// - Purpose: Enhance entropy quality through circular feedback churning
// - Creates self-reinforcing randomness accumulation over time
//------------------------------------------------------------------------------

module entropy_fifo #(
    parameter int unsigned DEPTH = 64,
    localparam type ptr_t   = logic [$clog2(DEPTH)-1:0],
    localparam type level_t = logic [$clog2(DEPTH):0]
) (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic        push_i,
    input  logic        pop_i,
    input  logic [31:0] wdata_i,
    input  logic        entropy_churn_enable_i,
    output logic [31:0] rdata_o,
    output level_t      level_o,
    output ptr_t        wptr_o,
    output ptr_t        rptr_o,
    output logic        overflow_o,
    output logic        underflow_o,
    // Security error outputs
    output logic        parity_error_o,
    output logic        pointer_error_o,
    output logic        security_alert_o
);
    ptr_t   wptr_q,     wptr_d;
    ptr_t   wptr_inv_q, wptr_inv_d; // Inverted write pointer
    ptr_t   rptr_q,     rptr_d;
    ptr_t   rptr_inv_q, rptr_inv_d; // Inverted read pointer
    level_t level_q,    level_d;    // One more bit to handle up to DEPTH

    logic   push_valid, pop_valid;
    logic   fifo_full, fifo_empty;

    // Memory with parity bits: 32-bit data + 4-bit odd parity (one per byte)
    logic [35:0] mem [0:DEPTH-1];  // [35:32] = parity bits, [31:0] = data

    // Parity calculation for 32-bit words
    function automatic logic [3:0] calc_word_parity(input logic [31:0] data_word);
        calc_word_parity[0] = ^data_word[7:0];   // Byte 0 odd parity
        calc_word_parity[1] = ^data_word[15:8];  // Byte 1 odd parity
        calc_word_parity[2] = ^data_word[23:16]; // Byte 2 odd parity
        calc_word_parity[3] = ^data_word[31:24]; // Byte 3 odd parity
    endfunction

    // Error detection
    logic       pointer_mismatch_w, pointer_mismatch_r;
    logic [3:0] expected_parity, stored_parity;
    logic       parity_error_detected;

    // Sequential logic for pointers and level
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            wptr_q     <= ptr_t'( 0);
            wptr_inv_q <= ptr_t'('1); // Inverted reset value
            rptr_q     <= ptr_t'( 0);
            rptr_inv_q <= ptr_t'('1); // Inverted reset value
            level_q    <= level_t'(0);
        end else begin
            wptr_q     <= wptr_d;
            wptr_inv_q <= wptr_inv_d;
            rptr_q     <= rptr_d;
            rptr_inv_q <= rptr_inv_d;
            level_q    <= level_d;
        end
    end

    // Pointer consistency checking
    assign pointer_mismatch_w = wptr_q != ~wptr_inv_q;
    assign pointer_mismatch_r = rptr_q != ~rptr_inv_q;
    assign pointer_error_o    = pointer_mismatch_w | pointer_mismatch_r;

    // FIFO status
    assign fifo_full  = level_q == level_t'(DEPTH);
    assign fifo_empty = level_q == level_t'(0);

    // Valid operation detection
    assign push_valid = push_i & ~fifo_full & ~pointer_error_o;
    assign pop_valid  = pop_i & ~fifo_empty & ~pointer_error_o;

    // Error conditions
    assign overflow_o  = push_i & fifo_full;
    assign underflow_o = pop_i & fifo_empty;

    // Pointer and level update logic
    always_comb begin
        wptr_d     = wptr_q;
        wptr_inv_d = wptr_inv_q;
        rptr_d     = rptr_q;
        rptr_inv_d = rptr_inv_q;
        level_d    = level_q;

        case ({push_valid, pop_valid})
            2'b10: begin  // Push only
                wptr_d     = wptr_q == ptr_t'(DEPTH - 1) ? ptr_t'(0) : wptr_q + ptr_t'(1);
                wptr_inv_d = ~wptr_d;
                level_d    = level_q + level_t'(1);
            end
            2'b01: begin  // Pop only
                rptr_d     = rptr_q == ptr_t'(DEPTH - 1) ? ptr_t'(0) : rptr_q + ptr_t'(1);
                rptr_inv_d = ~rptr_d;
                level_d    = level_q - level_t'(1);
            end
            2'b11: begin  // Push and pop simultaneously
                wptr_d     = wptr_q == ptr_t'(DEPTH - 1) ? ptr_t'(0) : wptr_q + ptr_t'(1);
                wptr_inv_d = ~wptr_d;
                rptr_d     = rptr_q == ptr_t'(DEPTH - 1) ? ptr_t'(0) : rptr_q + ptr_t'(1);
                rptr_inv_d = ~rptr_d;
                // level_d remains the same (push +1, pop -1)
            end
            default: begin
                // Keep current values
            end
        endcase
    end

    // Entropy churning logic
    // Calculate churning address: (wptr + DEPTH/2) % DEPTH
    ptr_t churn_addr;
    logic [35:0] churn_entry;
    logic [31:0] churn_data;
    logic [31:0] final_wdata;

    // Calculate address halfway around the FIFO
    assign churn_addr  = ptr_t'((unsigned'(wptr_q) + unsigned'(DEPTH/2)) % unsigned'(DEPTH));

    // Read full entry from churning address
    assign churn_entry = mem[churn_addr];

    // Extract data portion (bits 31:0)
    assign churn_data  = churn_entry[31:0];

    // Churn incoming data with FIFO data if churning enabled
    assign final_wdata = entropy_churn_enable_i ? (wdata_i ^ churn_data) : wdata_i;

    // Memory write with parity generation
    always_ff @(posedge clk_i) begin
        if (push_valid) begin
            mem[wptr_q] <= {calc_word_parity(final_wdata), final_wdata};
        end
    end

    // Memory read with parity checking
    logic [35:0] read_entry;
    logic [31:0] read_data;

    assign read_entry    = mem[rptr_q];
    assign read_data     = read_entry[31:0];
    assign stored_parity = read_entry[35:32];

    // Parity error detection
    assign expected_parity       = calc_word_parity(read_data);
    assign parity_error_detected = expected_parity != stored_parity;
    assign parity_error_o        = parity_error_detected;

    // Output assignments
    assign rdata_o = read_data;
    assign wptr_o  = wptr_q;
    assign rptr_o  = rptr_q;
    assign level_o = level_q;

    // Security alert generation
    assign security_alert_o = parity_error_o | pointer_error_o;

endmodule
