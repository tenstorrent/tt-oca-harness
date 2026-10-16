// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP outbound mailbox responder + firmware-console monitor for the OSS flow.
//
// SEP firmware writes its console output and a test-completion magic to the
// fixed STDOUT mailbox address 0x8000_0000 (byte stores for characters; 32-bit
// stores of 0xA5A5_5A5A then 0xCAFE_BABE/0xDEAD_BEEF for PASS/FAIL). Those
// stores leave the bare `sep` module on `smn_outbound_axi_req_o`
// (sep_system_peripherals_outbound_axi_*, 56-bit addr / 64-bit data) once the
// firmware has opened the SEP outbound filter.
//
// This module is a minimal AXI subordinate (so the firmware's stores and
// loads do not stall) plus a write-channel monitor. AW requests wait in a
// FIFO in order, and each W beat takes the address of its own burst (INCR
// beats advance by AxSIZE), so the monitor decodes every beat at its own
// address. W beats stall while the B queue is full, so every accepted burst
// gets exactly one B response, in order. AR requests wait in a FIFO in order
// and are answered one burst at a time. The monitor assembles console
// characters (byte-strobe stores at STDOUT) and latches fw_done/fw_pass on the
// magic sequence at STDOUT:
//   * the first completed magic pair sets fw_done; a later pair can only
//     clear fw_pass, never set it;
//   * a magic pair at any other outbound address sets fw_done with fw_pass
//     low and prints an error, so a PASS pair that misses STDOUT cannot pass.
// tb_top surfaces the decoded signals to cocotb.
//
// Response control (an error inject on smn_outbound_axi_resp_i, both inputs 0
// by default, which answers OKAY at once):
//   * resp_hold_i=1 holds B VALID and R VALID low. AW, W and AR are still
//     accepted, so a request reaches the port and waits for its response. The
//     held responses go out in order when the input falls. A firmware console
//     store waits too, so a CPU leaf does not raise it.
//   * rd_slverr_i, sampled at the AR handshake, makes every R beat of that
//     read answer SLVERR (data 0).
//
// Request-side control (both inputs 0 by default, which accepts at once and
// returns zero read data):
//   * ready_stall_i[0], [1] and [2] hold AW READY, W READY and AR READY low
//     while the bit is high. The driver of the input draws the stall cycle
//     by cycle. A W beat is accepted ahead of its AW only in the cycle that
//     AW is accepted.
//   * rd_addr_data_i=1 returns {~a, a} on every R beat, where a is the low 32
//     bits of the 8-byte-aligned address of that beat.
//
// Queue limits: +sep_outbound_depth=<n> (1 to 64) sets the queued write
// bursts, the pending B responses and the queued reads each to n, so the port
// accepts 2n AW, n W-complete bursts and n AR before a held response stops it.
// Without the plusarg they are 16, 16 and 1.

`timescale 1ps / 1fs

`include "sep_reg.svh"

module sep_outbound_mbx
  import sep_pkg::*;
(
  input  wire logic clk_i,
  input  wire logic rst_ni,
  input  sep_pkg::sep_system_peripherals_outbound_axi_req_t  req_i,
  output sep_pkg::sep_system_peripherals_outbound_axi_resp_t resp_o,
  // Response control: hold every B and R response; SLVERR on the next read.
  input  wire logic resp_hold_i,
  input  wire logic rd_slverr_i,
  // Request-side control: hold AW, W and AR READY low; address-derived read data.
  input  wire logic [2:0] ready_stall_i,
  input  wire logic rd_addr_data_i,
  // Decoded firmware-console observables (read by cocotb via tb_top).
  output logic       fw_done_o,
  output logic       fw_pass_o,
  output logic [7:0] fw_char_o,
  output logic       fw_char_valid_o
);

  localparam logic [31:0] Magic0 = 32'hA5A5_5A5A;
  localparam logic [31:0] MagicPass = 32'hCAFE_BABE;
  localparam logic [31:0] MagicFail = 32'hDEAD_BEEF;

  localparam int unsigned Aw = $bits(req_i.aw.addr);
  localparam int unsigned Idw = $bits(req_i.aw.id);
  localparam int unsigned Depth = 64;
  localparam int unsigned Pw = $clog2(Depth);
  localparam int unsigned WrLimitDefault = 16;
  localparam int unsigned RdLimitDefault = 1;

  localparam logic [Aw-1:0] StdoutAddr = Aw'(SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_REG_DEFAULT);

  // One accepted write burst: address of its next beat, size, burst type, ID.
  typedef struct packed {
    logic [Aw-1:0]  addr;
    logic [2:0]     size;
    logic [1:0]     burst;
    logic [Idw-1:0] id;
  } wburst_t;

  // One accepted read burst: start address, size, burst type, ID, AxLEN and
  // the response code sampled at its AR handshake.
  typedef struct packed {
    logic [Aw-1:0]  addr;
    logic [2:0]     size;
    logic [1:0]     burst;
    logic [Idw-1:0] id;
    logic [7:0]     len;
    logic           err;
  } rburst_t;

  function automatic logic [Aw-1:0] next_addr(input wburst_t b);
    logic [Aw-1:0] step;
    step = Aw'(1) << b.size;
    next_addr = (b.burst == axi_pkg::BURST_FIXED) ? b.addr : (b.addr & ~(step - Aw'(1))) + step;
  endfunction

  // The queue limits of this run.
  logic [Pw:0] wr_limit, rd_limit;
  initial begin
    int unsigned n;
    wr_limit = (Pw + 1)'(WrLimitDefault);
    rd_limit = (Pw + 1)'(RdLimitDefault);
    if ($value$plusargs("sep_outbound_depth=%d", n)) begin
      if (n < 1) n = 1;
      if (n > Depth) n = Depth;
      wr_limit = (Pw + 1)'(n);
      rd_limit = (Pw + 1)'(n);
    end
  end

  wburst_t aw_fifo[Depth];
  logic [Pw-1:0] aw_rd_q, aw_wr_q;
  logic [Pw:0]    aw_cnt_q;
  logic [Idw-1:0] b_fifo[Depth];
  logic [Pw-1:0] b_rd_q, b_wr_q;
  logic [Pw:0]    b_cnt_q;
  logic           w_active_q;
  wburst_t        w_cur_q;
  rburst_t ar_fifo[Depth];
  logic [Pw-1:0] ar_rd_q, ar_wr_q, ar_nxt;
  logic [Pw:0]    ar_cnt_q;
  logic [Aw-1:0]  r_addr_q;
  logic [7:0]     r_sent_q;
  logic           magic_seen_q;
  logic           stray_seen_q;
  logic [Aw-1:0]  stray_addr_q;

  // The burst of the current W beat: the burst in progress, else the oldest
  // accepted AW, else an AW that arrives on the same cycle.
  wburst_t aw_in, w_burst;
  always_comb begin
    aw_in = '{addr: req_i.aw.addr, size: req_i.aw.size, burst: req_i.aw.burst, id: req_i.aw.id};
    if (w_active_q) w_burst = w_cur_q;
    else if (aw_cnt_q != '0) w_burst = aw_fifo[aw_rd_q];
    else w_burst = aw_in;
  end
  wire aw_ready_w = (aw_cnt_q < wr_limit) && !ready_stall_i[0];
  wire w_known = w_active_q || (aw_cnt_q != '0) || (req_i.aw_valid && aw_ready_w);
  wire aw_fire = req_i.aw_valid & resp_o.aw_ready;
  wire w_fire = req_i.w_valid & resp_o.w_ready;
  // The W beat takes the same-cycle AW directly, so that AW is not queued.
  wire aw_bypass = w_fire && !w_active_q && (aw_cnt_q == '0);
  wire aw_push = aw_fire && !aw_bypass;
  wire aw_pop = w_fire && !w_active_q && (aw_cnt_q != '0);
  wire b_push = w_fire && req_i.w.last;
  wire b_pop = resp_o.b_valid && req_i.b_ready;
  wburst_t w_next;
  always_comb begin
    w_next      = w_burst;
    w_next.addr = next_addr(w_burst);
  end
  wire [Aw-1:0] beat_addr = w_burst.addr;
  wire to_stdout = (beat_addr == StdoutAddr);
  // 32-bit lane selected by the write strobe (upper lane for strb 0xF0).
  wire [31:0] mbx_word = (req_i.w.strb[7:4] != 4'h0) ? req_i.w.data[63:32] : req_i.w.data[31:0];
  wire word_store = (req_i.w.strb == 8'h0F) || (req_i.w.strb == 8'hF0);

  // The read on offer is the oldest accepted AR; r_addr_q is the address of
  // its next beat and r_sent_q the beats of it already accepted.
  rburst_t r_head;
  assign r_head = ar_fifo[ar_rd_q];
  assign ar_nxt = ar_rd_q + 1'b1;
  wire ar_fire = req_i.ar_valid & resp_o.ar_ready;
  wire r_fire = resp_o.r_valid & req_i.r_ready;
  wire r_last = (r_sent_q == r_head.len);
  wire ar_pop = r_fire & r_last;
  // Low 32 bits of the 8-byte-aligned address of the R beat on offer.
  wire [31:0] r_word_lo = {r_addr_q[31:3], 3'b000};
  wburst_t    r_cur;
  always_comb r_cur = '{addr: r_addr_q, size: r_head.size, burst: r_head.burst, id: '0};

  always_comb begin
    resp_o          = '0;
    resp_o.aw_ready = aw_ready_w;
    resp_o.w_ready  = w_known && (b_cnt_q < wr_limit) && !ready_stall_i[1];
    resp_o.b_valid  = (b_cnt_q != '0) && !resp_hold_i;
    resp_o.b.id     = b_fifo[b_rd_q];
    resp_o.b.resp   = 2'b00;  // OKAY
    resp_o.ar_ready = (ar_cnt_q < rd_limit) && !ready_stall_i[2];
    resp_o.r_valid  = (ar_cnt_q != '0) && !resp_hold_i;
    resp_o.r.id     = r_head.id;
    resp_o.r.data   = rd_addr_data_i ? {~r_word_lo, r_word_lo} : '0;
    resp_o.r.resp   = r_head.err ? 2'b10 : 2'b00;  // SLVERR under rd_slverr_i, else OKAY
    resp_o.r.last   = r_last;
  end

  // Log the first 40 STDOUT writes, so a console decode miss shows in the log.
  int unsigned dbg_cnt;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      aw_rd_q         <= '0;
      aw_wr_q         <= '0;
      aw_cnt_q        <= '0;
      b_rd_q          <= '0;
      b_wr_q          <= '0;
      b_cnt_q         <= '0;
      w_active_q      <= 1'b0;
      w_cur_q         <= '0;
      ar_rd_q         <= '0;
      ar_wr_q         <= '0;
      ar_cnt_q        <= '0;
      r_addr_q        <= '0;
      r_sent_q        <= '0;
      magic_seen_q    <= 1'b0;
      stray_seen_q    <= 1'b0;
      stray_addr_q    <= '0;
      fw_done_o       <= 1'b0;
      fw_pass_o       <= 1'b0;
      fw_char_o       <= 8'h00;
      fw_char_valid_o <= 1'b0;
      dbg_cnt         <= 0;
    end else begin
      fw_char_valid_o <= 1'b0;  // 1-cycle pulse by default

      // AW FIFO.
      if (aw_push) begin
        aw_fifo[aw_wr_q] <= aw_in;
        aw_wr_q <= aw_wr_q + 1'b1;
      end
      if (aw_pop) aw_rd_q <= aw_rd_q + 1'b1;
      aw_cnt_q <= aw_cnt_q + (Pw + 1)'(aw_push) - (Pw + 1)'(aw_pop);

      // W beats: advance the burst address; queue the B ID on the last beat.
      if (w_fire) begin
        if (req_i.w.last) w_active_q <= 1'b0;
        else begin
          w_active_q    <= 1'b1;
          w_cur_q    <= w_next;
        end
      end

      // B FIFO.
      if (b_push) begin
        b_fifo[b_wr_q] <= w_burst.id;
        b_wr_q <= b_wr_q + 1'b1;
      end
      if (b_pop) b_rd_q <= b_rd_q + 1'b1;
      b_cnt_q <= b_cnt_q + (Pw + 1)'(b_push) - (Pw + 1)'(b_pop);

      // AR FIFO.
      if (ar_fire) begin
        ar_fifo[ar_wr_q] <= '{addr: req_i.ar.addr, size: req_i.ar.size, burst: req_i.ar.burst,
                              id: req_i.ar.id, len: req_i.ar.len, err: rd_slverr_i};
        ar_wr_q <= ar_wr_q + 1'b1;
      end
      if (ar_pop) ar_rd_q <= ar_rd_q + 1'b1;
      ar_cnt_q <= ar_cnt_q + (Pw + 1)'(ar_fire) - (Pw + 1)'(ar_pop);

      // R beats: advance the address inside the burst; after its last beat
      // the next read, queued or arriving on this cycle, is on offer.
      if (r_fire && !r_last) begin
        r_addr_q <= next_addr(r_cur);
        r_sent_q <= r_sent_q + 8'd1;
      end else if (ar_pop) begin
        r_sent_q <= '0;
        if (ar_cnt_q > (Pw + 1)'(1)) r_addr_q <= ar_fifo[ar_nxt].addr;
        else if (ar_fire) r_addr_q <= req_i.ar.addr;
      end else if (ar_fire && (ar_cnt_q == '0)) begin
        r_addr_q <= req_i.ar.addr;
      end

      if (w_fire & to_stdout) begin
        if (dbg_cnt < 40) begin
          $display("[sep_outbound_mbx] STDOUT write addr=0x%0h strb=0x%02h data=0x%016h",
                   beat_addr, req_i.w.strb, req_i.w.data);
          dbg_cnt <= dbg_cnt + 1;
        end
        // Console character: single low-byte store.
        if (req_i.w.strb == 8'h01) begin
          fw_char_o       <= req_i.w.data[7:0];
          fw_char_valid_o <= 1'b1;
        end
        // Test-completion magic: 32-bit word stores (low or high lane).
        if (word_store) begin
          if (!magic_seen_q) begin
            if (mbx_word == Magic0) magic_seen_q <= 1'b1;
          end else begin
            if (mbx_word == MagicPass) begin
              // The first verdict stands; a later PASS pair cannot set PASS.
              if (!fw_done_o) fw_pass_o <= 1'b1;
              fw_done_o    <= 1'b1;
              magic_seen_q <= 1'b0;
            end else if (mbx_word == MagicFail) begin
              fw_done_o    <= 1'b1;
              fw_pass_o    <= 1'b0;
              magic_seen_q <= 1'b0;
            end else if (mbx_word != Magic0) begin
              magic_seen_q <= 1'b0;
            end
          end
        end
      end

      // A magic pair at any other address fails the run.
      if (w_fire && !to_stdout && word_store) begin
        if (!stray_seen_q || (beat_addr != stray_addr_q)) begin
          stray_seen_q <= (mbx_word == Magic0);
          stray_addr_q <= beat_addr;
        end else if ((mbx_word == MagicPass) || (mbx_word == MagicFail)) begin
          $display("[sep_outbound_mbx] ERROR: magic pair 0x%08h at 0x%0h, not at STDOUT 0x%0h",
                   mbx_word, beat_addr, StdoutAddr);
          fw_done_o    <= 1'b1;
          fw_pass_o    <= 1'b0;
          stray_seen_q <= 1'b0;
        end else begin
          stray_seen_q <= (mbx_word == Magic0);
        end
      end
    end
  end

endmodule : sep_outbound_mbx
