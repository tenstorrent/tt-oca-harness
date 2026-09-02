// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Behavioral AXI4-Lite RAM responder with deterministic error injection.
//
// SystemVerilog analogue of the cocotb OcahFaultAxiLiteRam: a zero-initialized
// byte memory with strobe-masked writes, single outstanding transaction per
// direction, registered single-cycle responses, and port-driven error
// controls. While `err_arm_i` is high and the beat-aligned address matches
// `err_addr_i`, the enabled direction responds `err_resp_i`, skips the memory
// update (writes), and returns zero data (reads). Arming discipline (arm ->
// operate -> disarm) belongs to the driving sequence, mirroring the cocotb
// `configure_target_error` / `clear_target_errors` flow.
//
// Simulation TB collateral for the SV-UVM flow (e.g. replacing the DTP tb_top
// UVM-mode tie-offs). Not intended for synthesis or Verilator filelists.

module ocah_axil_ram_responder #(
  parameter int unsigned ADDR_WIDTH = 32,
  parameter int unsigned DATA_WIDTH = 32,
  parameter int unsigned MEM_BYTES  = 65536  // power of two
) (
  input wire logic clk_i,
  input wire logic rst_ni,

  // AXI4-Lite subordinate.
  input  wire logic [  ADDR_WIDTH-1:0] awaddr,
  input  wire logic [             2:0] awprot,
  input  wire logic                    awvalid,
  output logic                         awready,
  input  wire logic [  DATA_WIDTH-1:0] wdata,
  input  wire logic [DATA_WIDTH/8-1:0] wstrb,
  input  wire logic                    wvalid,
  output logic                         wready,
  output logic      [             1:0] bresp,
  output logic                         bvalid,
  input  wire logic                    bready,
  input  wire logic [  ADDR_WIDTH-1:0] araddr,
  input  wire logic [             2:0] arprot,
  input  wire logic                    arvalid,
  output logic                         arready,
  output logic      [  DATA_WIDTH-1:0] rdata,
  output logic      [             1:0] rresp,
  output logic                         rvalid,
  input  wire logic                    rready,

  // Error-injection controls (driven from a TB interface).
  input wire logic                  err_arm_i,
  input wire logic [ADDR_WIDTH-1:0] err_addr_i,
  input wire logic [           1:0] err_resp_i,
  input wire logic                  err_on_read_i,
  input wire logic                  err_on_write_i
);

  localparam int unsigned StrbWidth = DATA_WIDTH / 8;
  localparam logic [1:0] RespOkay = 2'b00;

  logic [7:0] mem[0:MEM_BYTES-1];
  initial begin
    for (int unsigned i = 0; i < MEM_BYTES; i++) mem[i] = '0;
  end

  function automatic logic [ADDR_WIDTH-1:0] word_align(input logic [ADDR_WIDTH-1:0] addr);
    return (addr & ~ADDR_WIDTH'(StrbWidth - 1)) & ADDR_WIDTH'(MEM_BYTES - 1);
  endfunction

  function automatic logic err_match(input logic [ADDR_WIDTH-1:0] addr, input logic dir_en);
    return err_arm_i && dir_en && (word_align(addr) == word_align(err_addr_i));
  endfunction

  // ------------------------------------------------------------------
  // Write path: single outstanding; B once both AW and W are held.
  // ------------------------------------------------------------------
  logic aw_pend, w_pend;
  logic [ADDR_WIDTH-1:0] aw_addr_q;
  logic [DATA_WIDTH-1:0] w_data_q;
  logic [ StrbWidth-1:0] w_strb_q;

  assign awready = rst_ni && !aw_pend && !bvalid;
  assign wready  = rst_ni && !w_pend && !bvalid;

  // Plain `always`: `mem` is also zero-filled by the time-0 initial block,
  // and always_ff forbids a variable written by any other process.
  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      aw_pend  <= 1'b0;
      w_pend   <= 1'b0;
      bvalid   <= 1'b0;
      bresp    <= RespOkay;
      aw_addr_q <= '0;
      w_data_q  <= '0;
      w_strb_q  <= '0;
    end else begin
      if (awvalid && awready) begin
        aw_addr_q <= awaddr;
        aw_pend   <= 1'b1;
      end
      if (wvalid && wready) begin
        w_data_q <= wdata;
        w_strb_q <= wstrb;
        w_pend   <= 1'b1;
      end
      if (aw_pend && w_pend && !bvalid) begin
        if (err_match(aw_addr_q, err_on_write_i)) begin
          bresp <= err_resp_i;
        end else begin
          bresp <= RespOkay;
          for (int unsigned lane = 0; lane < StrbWidth; lane++) begin
            if (w_strb_q[lane]) mem[int'(word_align(aw_addr_q))+lane] <= w_data_q[8*lane+:8];
          end
        end
        bvalid  <= 1'b1;
        aw_pend <= 1'b0;
        w_pend  <= 1'b0;
      end
      if (bvalid && bready) bvalid <= 1'b0;
    end
  end

  // ------------------------------------------------------------------
  // Read path: single outstanding, registered single-cycle response.
  // ------------------------------------------------------------------
  assign arready = rst_ni && !rvalid;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      rvalid <= 1'b0;
      rresp  <= RespOkay;
      rdata  <= '0;
    end else begin
      if (arvalid && arready) begin
        if (err_match(araddr, err_on_read_i)) begin
          rresp <= err_resp_i;
          rdata <= '0;
        end else begin
          rresp <= RespOkay;
          for (int unsigned lane = 0; lane < StrbWidth; lane++)
          rdata[8*lane+:8] <= mem[int'(word_align(araddr))+lane];
        end
        rvalid <= 1'b1;
      end
      if (rvalid && rready) rvalid <= 1'b0;
    end
  end

endmodule : ocah_axil_ram_responder
