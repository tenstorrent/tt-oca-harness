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
// address. The monitor assembles console characters (byte-strobe stores at
// STDOUT) and latches fw_done/fw_pass on the magic sequence at STDOUT:
//   * the first completed magic pair sets fw_done; a later pair can only
//     clear fw_pass, never set it;
//   * a magic pair at any other outbound address sets fw_done with fw_pass
//     low and prints an error, so a PASS pair that misses STDOUT cannot pass.
// tb_top surfaces the decoded signals to cocotb.

`timescale 1ps / 1fs

`include "sep_reg.svh"

module sep_outbound_mbx
  import sep_pkg::*;
(
  input  wire logic clk_i,
  input  wire logic rst_ni,
  input  sep_pkg::sep_system_peripherals_outbound_axi_req_t  req_i,
  output sep_pkg::sep_system_peripherals_outbound_axi_resp_t resp_o,
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
  localparam int unsigned Depth = 16;
  localparam int unsigned Pw = $clog2(Depth);

  localparam logic [Aw-1:0] StdoutAddr = Aw'(SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_REG_DEFAULT);

  // One accepted write burst: address of its next beat, size, burst type, ID.
  typedef struct packed {
    logic [Aw-1:0]  addr;
    logic [2:0]     size;
    logic [1:0]     burst;
    logic [Idw-1:0] id;
  } wburst_t;

  function automatic logic [Aw-1:0] next_addr(input wburst_t b);
    logic [Aw-1:0] step;
    step = Aw'(1) << b.size;
    next_addr = (b.burst == axi_pkg::BURST_FIXED) ? b.addr : (b.addr & ~(step - Aw'(1))) + step;
  endfunction

  wburst_t aw_fifo[Depth];
  logic [Pw-1:0] aw_rd_q, aw_wr_q;
  logic [Pw:0]    aw_cnt_q;
  logic [Idw-1:0] b_fifo[Depth];
  logic [Pw-1:0] b_rd_q, b_wr_q;
  logic [Pw:0]    b_cnt_q;
  logic           w_active_q;
  wburst_t        w_cur_q;
  logic           ar_active_q;
  logic [Idw-1:0] r_id_q;
  logic [8:0]     r_beats_q;
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
  wire w_known = w_active_q || (aw_cnt_q != '0) || req_i.aw_valid;
  wire aw_fire = req_i.aw_valid & resp_o.aw_ready;
  wire w_fire = req_i.w_valid & resp_o.w_ready;
  // The W beat takes the same-cycle AW directly, so that AW is not queued.
  wire aw_bypass = w_fire && !w_active_q && (aw_cnt_q == '0);
  wire aw_push = aw_fire && !aw_bypass;
  wire aw_pop = w_fire && !w_active_q && (aw_cnt_q != '0);
  wire b_push = w_fire && req_i.w.last;
  wire b_pop = (b_cnt_q != '0) && req_i.b_ready;
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

  always_comb begin
    resp_o          = '0;
    resp_o.aw_ready = (aw_cnt_q < (Pw + 1)'(Depth));
    resp_o.w_ready  = w_known;
    resp_o.b_valid  = (b_cnt_q != '0);
    resp_o.b.id     = b_fifo[b_rd_q];
    resp_o.b.resp   = 2'b00;  // OKAY
    resp_o.ar_ready = !ar_active_q;
    resp_o.r_valid  = ar_active_q;
    resp_o.r.id     = r_id_q;
    resp_o.r.data   = '0;
    resp_o.r.resp   = 2'b00;  // OKAY
    resp_o.r.last   = (r_beats_q == 9'd1);
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
      ar_active_q     <= 1'b0;
      r_id_q          <= '0;
      r_beats_q       <= '0;
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

      // Read response: OKAY, zero data, honour the burst length.
      if (req_i.ar_valid & resp_o.ar_ready) begin
        ar_active_q <= 1'b1;
        r_id_q      <= req_i.ar.id;
        r_beats_q   <= req_i.ar.len + 9'd1;
      end else if (ar_active_q & req_i.r_ready) begin
        if (r_beats_q <= 9'd1) ar_active_q <= 1'b0;
        else r_beats_q <= r_beats_q - 9'd1;
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
