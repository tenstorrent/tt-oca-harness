// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Adapt the PicoRV32 native memory interface to the ROM with parity checking and
// look-ahead prefetch.
//
// Bridges the PicoRV32 native memory interface to the standard ROM memory interface
// (km_rom_mem_req_t / km_rom_mem_rsp_t). Read-only: write attempts are immediately
// acknowledged and reported as errors on rom_write_err_o.
//
// Supports the PicoRV32 look-ahead interface for efficient prefetching: mem_la_read_i /
// mem_la_addr_i arrive one cycle before mem_valid_i, allowing the ROM to begin the fetch
// early.
//
// Odd parity is checked per byte on the read-strobe lanes of every read response; a
// mismatch raises parity_error_o for the cycle the response is valid. Requests are held
// off for two cycles after reset release.

module km_rom_interface
  import km_intf_pkg::KM_ROM_MEM_ADDR_WIDTH;
  import km_intf_pkg::km_rom_mem_req_t;
  import km_intf_pkg::km_rom_mem_rsp_t;
#(
  parameter int unsigned ROM_ADDR_WIDTH = KM_ROM_MEM_ADDR_WIDTH  // Word-address width for the ROM.
) (
  input  logic clk_i,   // System clock.
  input  logic rst_ni,  // Active-low asynchronous reset.

  input  logic        mem_valid_i,  // PicoRV32 native memory request valid (from CPU).
  output logic        mem_ready_o,  // Memory ready: read data valid, or immediately for a write.
  input  logic [31:0] mem_addr_i,   // Byte address.
  input  logic [31:0] mem_wdata_i,  // Write data (unused, ROM is read-only).
  input  logic [3:0]  mem_wstrb_i,  // Write strobe; any set bit marks a write, which is
                                    // acknowledged without effect and flagged on rom_write_err_o.
  input  logic [3:0]  mem_rstrb_i,  // Read strobe: byte lanes consumed by the CPU, which select the
                                    // parity-checked lanes.
  output logic [31:0] mem_rdata_o,  // Read data.

  input  logic        mem_la_read_i,   // Look-ahead read signal (1 cycle before mem_valid).
  input  logic [31:0] mem_la_addr_i,   // Look-ahead address.
  input  logic [3:0]  mem_la_rstrb_i,  // Look-ahead read strobe; selects the parity-checked lanes
                                       // of a look-ahead fetch.

  output km_rom_mem_req_t rom_mem_req_o,  // ROM memory request, exposed at the subsystem
                                          // boundary.
  input  km_rom_mem_rsp_t rom_mem_rsp_i,  // ROM memory response.

  output logic parity_error_o,  // Combinational; high while a valid read response fails parity on
                                // a strobed lane.
  output logic rom_write_err_o  // Combinational; high while mem_valid_i is high with a nonzero
                                // write strobe.
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

  // Check odd parity per byte of a 32-bit word. data is the word to verify and parity the
  // 4-bit stored parity (one bit per byte, odd parity). Returns 1 if a parity mismatch is
  // detected, 0 otherwise.
  function automatic logic check_parity(logic [31:0] data, logic [3:0] parity,
                                        logic [3:0] byte_mask);
    logic [3:0] computed_parity;
    logic       mismatch;
    mismatch = 1'b0;
    for (int i = 0; i < 4; i++) begin
      // Compute odd parity: XOR all bits in byte, then invert
      // This matches the testbench parity generation: ~(^data[i*8 +: 8])
      computed_parity[i] = ~(^data[i*8+:8]);
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

  // The ROM answers every request on the next clock, so the response of a request is
  // valid, and checked against that request's read strobe, exactly one clock later.
  logic       rdata_valid_q;
  logic [3:0] rdata_rstrb_q;
  logic [3:0] req_rstrb;
  logic [1:0] req_squelch_q;

  assign req_rstrb = mem_la_read_i ? mem_la_rstrb_i : mem_rstrb_i;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      rdata_valid_q <= 1'b0;
      rdata_rstrb_q <= '0;
      req_squelch_q <= '0;
    end else begin
      rdata_valid_q <= rom_mem_req_o.req;
      if (rom_mem_req_o.req) begin
        rdata_rstrb_q <= req_rstrb;
      end

      // Hold req low for two cycles after reset release to avoid propagating
      // PicoRV32 startup X values into the ROM assertion path.
      req_squelch_q <= {req_squelch_q[0], 1'b1};
    end
  end

  assign rom_mem_req_o.clk  = clk_i;
  // Look-ahead reads prefetch the word the CPU will request on the next clock.
  assign rom_mem_req_o.req  = req_squelch_q[1] && (mem_la_read_i || is_read);
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
  assign mem_ready_o = (mem_valid_i && rdata_valid_q) ||
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
  assign parity_error_o = rdata_valid_q ?
                            check_parity(rom_mem_rsp_i.rdata, rom_mem_rsp_i.parity,
                                         rdata_rstrb_q) : 1'b0;

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
                  rom_mem_req_o.req |-> (mem_la_read_i || (mem_valid_i && !(|mem_wstrb_i))), clk_i,
                  !rst_ni)

  // ROM is read-only - writes should be ignored (respond immediately)
  `OCAH_OT_ASSERT(RomReadOnly_A, mem_valid_i && |mem_wstrb_i |-> mem_ready_o, clk_i, !rst_ni)

  // mem_ready only asserts when mem_valid is also asserted
  `OCAH_OT_ASSERT(MemReadyOnlyWhenValid_A, mem_ready_o |-> mem_valid_i, clk_i, !rst_ni)

endmodule : km_rom_interface

