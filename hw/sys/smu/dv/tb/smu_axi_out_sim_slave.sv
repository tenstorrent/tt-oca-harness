// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Synchronous AXI4 slave for the SMU outbound (ext_out) boundary.
//
// Answers every write and read with OKAY, backing reads with whatever was
// previously written; bytes never strobed read as zero. It is a bus terminator,
// not a checker -- observation of the traffic belongs to the testbench snoops on
// the same wires.
//
// Two properties matter beyond storing data:
//
// The address channels are unconditionally ready. Gating them on the data phase
// lets a request whose handshake never completes park the channel, and because
// the crossbar serialises across targets that stalls traffic which never touches
// this boundary at all. Requests are taken into shallow queues instead.
//
// Everything is clocked, with no `#` delays, so acceptance does not depend on
// simulator scheduling order or on the clock period, both of which the SMU
// environments vary.

`timescale 1ps / 1fs

module smu_axi_out_sim_slave #(
  parameter type axi_req_t  = logic,
  parameter type axi_resp_t = logic,
  parameter int unsigned AddrWidth = 56,
  // More outstanding requests per direction than the crossbar issues here; the
  // queues exist so ready never has to drop, not for throughput.
  parameter int unsigned QueueDepth = 4
) (
  input  logic      clk_i,
  input  logic      rst_ni,
  input  axi_req_t  axi_req_i,
  output axi_resp_t axi_resp_o
);

  localparam int unsigned WordIdxWidth = AddrWidth - 3;
  localparam int unsigned IdxWidth = $clog2(QueueDepth);

  logic [63:0] store[logic [WordIdxWidth-1:0]];

  typedef struct packed {
    logic [7:0]           id;
    logic [AddrWidth-1:0] addr;
    logic [7:0]           len;
    logic [2:0]           size;
    logic [1:0]           burst;
  } req_t;

  // Declared with initialisers, not only reset-assigned: the ready/valid
  // outputs are combinational from these, and an X before the first clock edge
  // would drive an X handshake back into the crossbar.
  req_t                 aw_q [QueueDepth];
  req_t                 ar_q [QueueDepth];
  logic [IdxWidth-1:0] aw_wr = '0, aw_rd = '0;
  logic [IdxWidth-1:0] ar_wr = '0, ar_rd = '0;
  logic aw_full = 1'b0, ar_full = 1'b0;
  logic [AddrWidth-1:0] wr_addr = '0;
  logic [AddrWidth-1:0] rd_addr = '0;
  logic [7:0]           rd_beat = '0;
  logic                 wr_active = 1'b0;
  logic                 rd_active = 1'b0;
  logic                 b_pending = 1'b0;
  logic [7:0]           b_id = '0;
  logic [63:0]          wr_merged;

  wire aw_empty = (aw_wr == aw_rd) && !aw_full;
  wire ar_empty = (ar_wr == ar_rd) && !ar_full;

  // FIXED bursts hold the address; INCR advances by the transfer size. WRAP is
  // not generated on this port and is treated as INCR.
  function automatic logic [AddrWidth-1:0] next_addr(logic [AddrWidth-1:0] a, logic [2:0] sz,
                                                     logic [1:0] bt);
    return (bt == 2'b00) ? a : (a + (AddrWidth'(1) << sz));
  endfunction

  always_comb begin
    axi_resp_o          = '0;
    axi_resp_o.aw_ready = 1'b1;
    axi_resp_o.ar_ready = 1'b1;
    axi_resp_o.w_ready  = wr_active;
    axi_resp_o.b_valid  = b_pending;
    axi_resp_o.b.id     = b_id;
    axi_resp_o.b.resp   = axi_pkg::RESP_OKAY;
    axi_resp_o.r_valid  = rd_active;
    axi_resp_o.r.id     = ar_q[ar_rd].id;
    axi_resp_o.r.data   = store.exists(rd_addr[AddrWidth-1:3])
                            ? store[rd_addr[AddrWidth-1:3]] : '0;
    axi_resp_o.r.resp   = axi_pkg::RESP_OKAY;
    axi_resp_o.r.last   = (rd_beat == ar_q[ar_rd].len);

    // Strobe-masked merge of the pending write beat onto the current memory
    // word, computed combinationally so the always_ff below only ever reads
    // wr_merged rather than recomputing the merge itself.
    wr_merged = store.exists(wr_addr[AddrWidth-1:3]) ? store[wr_addr[AddrWidth-1:3]] : '0;
    for (int unsigned b = 0; b < 8; b++) begin
      if (axi_req_i.w.strb[b]) begin
        wr_merged[b*8+:8] = axi_req_i.w.data[b*8+:8];
      end
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      aw_wr     <= '0;
      aw_rd     <= '0;
      ar_wr     <= '0;
      ar_rd     <= '0;
      aw_full   <= 1'b0;
      ar_full   <= 1'b0;
      wr_addr   <= '0;
      rd_addr   <= '0;
      rd_beat   <= '0;
      wr_active <= 1'b0;
      rd_active <= 1'b0;
      b_pending <= 1'b0;
      b_id      <= '0;
      store.delete();
    end else begin
      if (axi_req_i.aw_valid) begin
        aw_q[aw_wr] <= '{id:    axi_req_i.aw.id,
                                 addr:  axi_req_i.aw.addr,
                                 len:   axi_req_i.aw.len,
                                 size:  axi_req_i.aw.size,
                                 burst: axi_req_i.aw.burst};
        aw_wr   <= aw_wr + 1'b1;
        aw_full <= (IdxWidth'(aw_wr + 1'b1) == aw_rd);
      end
      if (axi_req_i.ar_valid) begin
        ar_q[ar_wr] <= '{id:    axi_req_i.ar.id,
                                 addr:  axi_req_i.ar.addr,
                                 len:   axi_req_i.ar.len,
                                 size:  axi_req_i.ar.size,
                                 burst: axi_req_i.ar.burst};
        ar_wr   <= ar_wr + 1'b1;
        ar_full <= (IdxWidth'(ar_wr + 1'b1) == ar_rd);
      end

      if (!wr_active && !aw_empty && !b_pending) begin
        wr_addr   <= aw_q[aw_rd].addr;
        wr_active <= 1'b1;
      end else if (wr_active && axi_req_i.w_valid) begin
        // store is an associative array, not a fixed-size register: Verilator
        // rejects a nonblocking assignment into a dynamically-sized variable,
        // so this assignment stays blocking unlike its sibling state updates.
        store[wr_addr[AddrWidth-1:3]] = wr_merged;
        if (axi_req_i.w.last) begin
          wr_active <= 1'b0;
          b_pending <= 1'b1;
          b_id      <= aw_q[aw_rd].id;
          aw_rd     <= aw_rd + 1'b1;
          aw_full   <= 1'b0;
        end else begin
          wr_addr <= next_addr(wr_addr, aw_q[aw_rd].size, aw_q[aw_rd].burst);
        end
      end

      if (b_pending && axi_req_i.b_ready) begin
        b_pending <= 1'b0;
      end

      if (!rd_active && !ar_empty) begin
        rd_addr   <= ar_q[ar_rd].addr;
        rd_beat   <= '0;
        rd_active <= 1'b1;
      end else if (rd_active && axi_req_i.r_ready) begin
        if (rd_beat == ar_q[ar_rd].len) begin
          rd_active <= 1'b0;
          ar_rd     <= ar_rd + 1'b1;
          ar_full   <= 1'b0;
        end else begin
          rd_addr <= next_addr(rd_addr, ar_q[ar_rd].size,
                                         ar_q[ar_rd].burst);
          rd_beat <= rd_beat + 8'd1;
        end
      end
    end
  end

endmodule
