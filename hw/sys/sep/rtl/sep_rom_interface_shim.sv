// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------
// SEP ROM Interface Shim
//
//------------------------------------------------

module sep_rom_interface_shim
  import sep_pkg::*;
#(
  parameter int unsigned ROM_ADDR_WIDTH = 10  // Default to 1K entries (10 bits)
) (
  input  logic                        clk_i,
  input  logic                        rst_ni,

  // Memory Interface (from memory_interface module)
  input  sep_sram_req_t               mem_req_i,
  output sep_sram_rsp_t               mem_rsp_o,

  // Macro Interface (to ROM primitive - prim_rom)
  output logic                        macro_req_o,
  output logic [ROM_ADDR_WIDTH-1:0]   macro_addr_o,
  input  logic [SEP_MEM_DATA_WIDTH-1:0] macro_rdata_i
);

  // Generate rvalid by delaying req by one cycle (ROM has 1 cycle latency)
  // NOTE: ROM is read-only. Writes are silently accepted but ignored - the ROM macro
  // doesn't perform the write. This is intentional behavior to avoid bus hangs.
  // The gnt signal must always be asserted to accept requests.
  logic read_req_q;
  logic write_req_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      read_req_q  <= 1'b0;
      write_req_q <= 1'b0;
    end else begin
      read_req_q  <= mem_req_i.req & ~mem_req_i.wenable;  // Track read requests
      write_req_q <= mem_req_i.req &  mem_req_i.wenable;   // Track writes (for response only)
    end
  end

  // Macro Interface assignments
  assign macro_req_o  = mem_req_i.req & ~mem_req_i.wenable;  // ROM is read-only, filter writes

  // Translate byte address to 64-bit word address
  // SEP_MEM_DATA_WIDTH is 64 bits, so divide by 8 (shift right by 3)
  // The shift result is automatically truncated to ROM_ADDR_WIDTH bits
  assign macro_addr_o = mem_req_i.addr >> 3;

  // Memory response
  assign mem_rsp_o.gnt    = 1'b1;  // Must accept all requests to avoid hanging the bus
  assign mem_rsp_o.rdata  = macro_rdata_i;
  assign mem_rsp_o.rvalid = read_req_q | write_req_q;  // Respond to both (writes silently ignored)

endmodule
