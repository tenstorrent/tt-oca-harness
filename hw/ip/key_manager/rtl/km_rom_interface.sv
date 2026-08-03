// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

/**
 * @file km_rom_interface.sv
 * @brief ROM interface adapter with parity checking and look-ahead prefetch.
 *
 * @details Bridges the PicoRV32 native memory interface to the standard ROM
 *          memory interface (km_rom_mem_req_t / km_rom_mem_rsp_t).  Read-only;
 *          write attempts are immediately acknowledged and reported as errors.
 *
 *          Supports the PicoRV32 look-ahead interface for efficient prefetching:
 *          mem_la_read_i / mem_la_addr_i arrive one cycle before mem_valid_i,
 *          allowing the ROM to begin the fetch early.
 *
 *          Odd parity is checked per byte on every read response; mismatches
 *          generate a single-cycle parity_error_o pulse to KMCSR.
 *
 * @param ROM_ADDR_WIDTH    Word-address width for the ROM (default KM_ROM_MEM_ADDR_WIDTH).
 */

module km_rom_interface import km_intf_pkg::*; #(
    parameter int unsigned ROM_ADDR_WIDTH = KM_ROM_MEM_ADDR_WIDTH
) (
    // Clock and Reset
    input  logic   clk_i,
    input  logic   rst_ni,

    // PicoRV32 native memory interface (input from CPU)
    input  logic   mem_valid_i,     // Memory request valid
    output logic        mem_ready_o,     // Memory ready (data available)
    input  logic [31:0] mem_addr_i,      // Byte address
    input  logic [31:0] mem_wdata_i,     // Write data (unused, ROM is read-only)
    input  logic [3:0] mem_wstrb_i,     // Write strobe (unused, ROM is read-only)
    input  logic [3:0] mem_rstrb_i,     // Read strobe (byte lanes consumed by CPU)
    output logic [31:0] mem_rdata_o,     // Read data

    // PicoRV32 look-ahead interface (for prefetching)
    input  logic   mem_la_read_i,   // Look-ahead read signal (1 cycle before mem_valid)
    input  logic [31:0] mem_la_addr_i,   // Look-ahead address
    input  logic [3:0] mem_la_rstrb_i,  // Look-ahead read strobe

    // ROM memory interface (exposed at subsystem boundary)
    output km_rom_mem_req_t rom_mem_req_o,
    input  km_rom_mem_rsp_t rom_mem_rsp_i,

    // Parity error output (to KMCSR)
    output logic        parity_error_o,    // Parity error detected (pulse)
    // ROM write error output (to KMCSR)
    output logic        rom_write_err_o    // ROM write attempt detected (pulse)
);

    `include "prim_assert.sv"

    ////////////////////////////////////////////////////////////////////////////
    // Address Decoding
    ////////////////////////////////////////////////////////////////////////////

    // Extract word address from byte address (word-aligned, drop bottom 2 bits)
    // Use look-ahead address when available for prefetching, otherwise use main address
    logic [ROM_ADDR_WIDTH-1:0] word_addr;
    logic [ROM_ADDR_WIDTH-1:0] la_word_addr;
    assign word_addr    = mem_addr_i[ROM_ADDR_WIDTH+1:2];
    assign la_word_addr = mem_la_addr_i[ROM_ADDR_WIDTH+1:2];

    ////////////////////////////////////////////////////////////////////////////
    // Parity Check Function
    ////////////////////////////////////////////////////////////////////////////

    /**
     * @brief Check odd parity per byte of a 32-bit word.
     *
     * @param[in] data    32-bit data word to verify.
     * @param[in] parity  4-bit stored parity (one bit per byte, odd parity).
     * @return            1 if a parity mismatch is detected, 0 otherwise.
     */
    function automatic logic check_parity(
        logic [31:0] data,
        logic [3:0]  parity,
        logic [3:0]  byte_mask
    );
        logic [3:0] computed_parity;
        logic       mismatch;
        mismatch = 1'b0;
        for (int i = 0; i < 4; i++) begin
            // Compute odd parity: XOR all bits in byte, then invert
            // This matches the testbench parity generation: ~(^data[i*8 +: 8])
            computed_parity[i] = ~(^data[i*8 +: 8]);
            if (byte_mask[i]) begin
                mismatch |= (computed_parity[i] != parity[i]);
            end
        end
        return mismatch;
    endfunction

    ////////////////////////////////////////////////////////////////////////////
    // ROM Request Generation with Look-Ahead Support
    ////////////////////////////////////////////////////////////////////////////

    // ROM is read-only - ignore write attempts
    logic is_read;
    assign is_read = mem_valid_i && !(|mem_wstrb_i);

    // Track outstanding requests to ensure we complete them
    // This is critical for pipelined memory when the CPU may de-assert mem_valid
    // before all responses arrive (e.g., second word of unaligned instruction)
    // Support pipelined sequential reads: can accept new request in same cycle as response
    logic request_pending_q;
    logic [3:0] pending_rstrb_q;
    logic [3:0] req_rstrb;
    logic [3:0] current_rsp_rstrb;
    logic       read_complete;
    logic [1:0] req_squelch_q;
    logic       req_enable;

    // Determine if we should issue a new request
    // 1. On look-ahead read (prefetch for next cycle) - highest priority
    // 2. On regular read (when mem_valid is asserted)
    // Don't issue new request if one is already pending and not yet completed
    // EXCEPT: allow new request in same cycle as response (pipelined operation)
    logic issue_new_request;
    assign issue_new_request = (mem_la_read_i || is_read) &&
                               (!request_pending_q || rom_mem_rsp_i.rvalid);
    assign req_rstrb = mem_la_read_i ? mem_la_rstrb_i : mem_rstrb_i;
    assign read_complete = rom_mem_rsp_i.rvalid;
    assign current_rsp_rstrb = (rom_mem_req_o.req && !request_pending_q) ? req_rstrb : pending_rstrb_q;
    assign req_enable = req_squelch_q[1];

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            request_pending_q <= 1'b0;
            pending_rstrb_q <= '0;
            req_squelch_q <= '0;
        end else begin
            // Track when we've issued a request but haven't received response
            // If new request is issued in same cycle as response, keep pending set
            if (rom_mem_req_o.req) begin
                request_pending_q <= 1'b1;
                pending_rstrb_q <= req_rstrb;
            end else if (rom_mem_rsp_i.rvalid) begin
                // Clear pending only if no new request is being issued
                request_pending_q <= 1'b0;
            end

            // Hold req low for two cycles after reset release to avoid propagating
            // PicoRV32 startup X values into the ROM assertion path.
            req_squelch_q <= {req_squelch_q[0], 1'b1};
        end
    end

    assign rom_mem_req_o.req  = req_enable && issue_new_request;
    // Use look-ahead address for prefetch, regular address otherwise
    assign rom_mem_req_o.addr = mem_la_read_i ? la_word_addr : word_addr;

    ////////////////////////////////////////////////////////////////////////////
    // Ready Signal Generation
    ////////////////////////////////////////////////////////////////////////////

    // Ready when ROM data is valid and this is a valid transfer
    // OR immediately for write attempts (which ROM ignores)
    //
    // For pipelined memory with look-ahead: when mem_la_read triggers a prefetch,
    // the response arrives one cycle later when mem_valid is asserted. The CPU
    // samples data when both mem_valid and mem_ready are high.
    assign mem_ready_o = (mem_valid_i && rom_mem_rsp_i.rvalid) ||
                         (mem_valid_i && |mem_wstrb_i);  // Write: respond immediately

    ////////////////////////////////////////////////////////////////////////////
    // Read Data Output
    ////////////////////////////////////////////////////////////////////////////

    // Pass ROM data through directly so the latched-data property is defined by the ROM macro.
    assign mem_rdata_o = rom_mem_rsp_i.rdata;

    ////////////////////////////////////////////////////////////////////////////
    // Parity Error Output
    ////////////////////////////////////////////////////////////////////////////

    // Check parity on the byte lanes actually consumed by the CPU on this read response.
    assign parity_error_o = read_complete ?
                            check_parity(rom_mem_rsp_i.rdata, rom_mem_rsp_i.parity,
                                         current_rsp_rstrb) : 1'b0;

    ////////////////////////////////////////////////////////////////////////////
    // ROM Write Error Output
    ////////////////////////////////////////////////////////////////////////////

    // Detect write attempts to ROM (read-only memory)
    // Assert write error when a write transaction is attempted (mem_wstrb_i is non-zero)
    assign rom_write_err_o = mem_valid_i && (|mem_wstrb_i);

    ////////////////////////////////////////////////////////////////////////////
    // Assertions
    ////////////////////////////////////////////////////////////////////////////

    // ROM request only asserted for look-ahead reads or regular reads
    `OCAH_OT_ASSERT(RomReqOnlyForRead_A,
        rom_mem_req_o.req |-> (mem_la_read_i || (mem_valid_i && !(|mem_wstrb_i))),
        clk_i, !rst_ni)

    // ROM is read-only - writes should be ignored (respond immediately)
    `OCAH_OT_ASSERT(RomReadOnly_A,
        mem_valid_i && |mem_wstrb_i |-> mem_ready_o,
        clk_i, !rst_ni)

    // mem_ready only asserts when mem_valid is also asserted
    `OCAH_OT_ASSERT(MemReadyOnlyWhenValid_A,
        mem_ready_o |-> mem_valid_i,
        clk_i, !rst_ni)

endmodule : km_rom_interface

