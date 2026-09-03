// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------
// SEP SRAM Interface Shim
//
//------------------------------------------------

module sep_sram_interface_shim
  import sep_pkg::*;
#(
  parameter int unsigned SRAM_ADDR_WIDTH = 10  // Default to 1K entries (10 bits)
) (
  input  logic                        clk_i,
  input  logic                        rst_ni,

  // Memory Interface (from memory_interface module)
  input  sep_sram_req_t               mem_req_i,
  output sep_sram_rsp_t               mem_rsp_o,

  // Macro Interface (to SRAM primitive)
  output logic                        macro_req_o,
  output logic                        macro_write_o,
  output logic [SRAM_ADDR_WIDTH-1:0]  macro_addr_o,
  output logic [SEP_MEM_DATA_WIDTH-1:0] macro_wdata_o,
  output logic [SEP_MEM_DATA_WIDTH-1:0] macro_wmask_o,
  input  logic [SEP_MEM_DATA_WIDTH-1:0] macro_rdata_i,
  input  logic                        macro_rvalid_i
);

  // Generate write response (SRAM macro only generates rvalid for reads)
  logic write_req_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      write_req_q <= 1'b0;
    end else begin
      write_req_q <= mem_req_i.req & mem_req_i.wenable;
    end
  end

  // Macro Interface assignments
  assign macro_req_o   = mem_req_i.req;
  assign macro_write_o = mem_req_i.wenable;

  // Translate byte address to 64-bit word address
  // SEP_MEM_DATA_WIDTH is 64 bits, so divide by 8 (shift right by 3)
  // The shift result is automatically truncated to SRAM_ADDR_WIDTH bits
  assign macro_addr_o  = mem_req_i.addr >> 3;

  assign macro_wdata_o = mem_req_i.wdata;

  // Expand byte mask (8 bits for 64-bit bus) to bit mask (64 bits)
  assign macro_wmask_o = {{8{mem_req_i.strb[7]}},
                            {8{mem_req_i.strb[6]}},
                            {8{mem_req_i.strb[5]}},
                            {8{mem_req_i.strb[4]}},
                            {8{mem_req_i.strb[3]}},
                            {8{mem_req_i.strb[2]}},
                            {8{mem_req_i.strb[1]}},
                            {8{mem_req_i.strb[0]}}};

  // Memory response
  assign mem_rsp_o.gnt    = 1'b1;  // Always ready to accept requests
  assign mem_rsp_o.rdata  = macro_rdata_i;
  assign mem_rsp_o.rvalid = macro_rvalid_i | write_req_q;  // rvalid for reads (from macro) and writes (delayed)

endmodule
