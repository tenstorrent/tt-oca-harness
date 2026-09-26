// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Forward the SEP SRAM memory_interface struct onto an SRAM macro.
//
// SRAM_ADDR_WIDTH defaults to 10 (1K 64-bit entries). Forwards read/write requests onto
// macro_* pins and returns macro_rdata_i when macro_rvalid_i.
// Every request is granted at once. Reads complete on macro_rvalid_i; writes are
// acknowledged with rvalid one cycle after the request.

module sep_sram_interface_shim
  import sep_pkg::*;
#(
  parameter int unsigned SRAM_ADDR_WIDTH = 10  // SRAM address width; default 10 for 1K entries.
) (
  input  logic                        clk_i,  // System clock.
  input  logic                        rst_ni,  // Active-low reset.

  input  sep_sram_req_t               mem_req_i,  // Memory request from the SEP memory_interface;
                                                  // byte address, 64-bit data.
  output sep_sram_rsp_t               mem_rsp_o,  // Memory response: gnt always high, rvalid from
                                                  // macro_rvalid_i for reads and one cycle after
                                                  // the request for writes.

  output logic                        macro_req_o,  // Request to the SRAM macro, for reads and
                                                    // writes.
  output logic                        macro_write_o,  // Write enable qualifying macro_req_o; low
                                                      // for reads.
  output logic [SRAM_ADDR_WIDTH-1:0]  macro_addr_o,  // SRAM word address: the request byte address
                                                     // divided by eight.
  output logic [SEP_MEM_DATA_WIDTH-1:0] macro_wdata_o,  // Write data to the SRAM macro.
  output logic [SEP_MEM_DATA_WIDTH-1:0] macro_wmask_o,  // Bit write mask, each request byte strobe
                                                        // expanded to eight bits.
  input  logic [SEP_MEM_DATA_WIDTH-1:0] macro_rdata_i,  // Read data from the SRAM macro; valid with
                                                        // macro_rvalid_i.
  input  logic                        macro_rvalid_i  // Read-data valid from the SRAM macro.
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
