// SPDX-License-Identifier: Apache-2.0
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
// This module is a minimal always-ready AXI subordinate (so the firmware's
// stores/loads never stall) plus a write-channel monitor that mirrors the reference suite
// internal env decode: it assembles console characters
// (byte-strobe stores) and latches fw_done/fw_pass on the magic sequence. The
// decoded signals are surfaced to cocotb through tb_top.

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

  localparam logic [31:0] MAGIC0 = 32'hA5A5_5A5A;
  localparam logic [31:0] MAGIC_PASS = 32'hCAFE_BABE;
  localparam logic [31:0] MAGIC_FAIL = 32'hDEAD_BEEF;
  localparam logic [31:0] STDOUT_LO =
      SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_REG_DEFAULT[31:0];

  localparam int unsigned AW = $bits(req_i.aw.addr);
  localparam int unsigned IDW = $bits(req_i.aw.id);

  logic [IDW-1:0] aw_id_q;
  logic [AW-1:0]  aw_addr_q;
  logic           b_valid_q;
  logic           ar_active_q;
  logic [IDW-1:0] r_id_q;
  logic [8:0]     r_beats_q;
  logic           magic_seen_q;

  // Address of the in-flight write (handle AW+W arriving on the same cycle).
  wire [AW-1:0] cur_awaddr = req_i.aw_valid ? req_i.aw.addr : aw_addr_q;
  wire          to_stdout  = (cur_awaddr[31:0] == STDOUT_LO);
  wire          w_fire     = req_i.w_valid & resp_o.w_ready;
  // 32-bit lane selected by the write strobe (upper lane for strb 0xF0).
  wire [31:0]   mbx_word   = (req_i.w.strb[7:4] != 4'h0) ? req_i.w.data[63:32]
                                                           : req_i.w.data[31:0];

  always_comb begin
    resp_o          = '0;
    resp_o.aw_ready = 1'b1;
    resp_o.w_ready  = 1'b1;
    resp_o.b_valid  = b_valid_q;
    resp_o.b.id     = aw_id_q;
    resp_o.b.resp   = 2'b00;          // OKAY
    resp_o.ar_ready = !ar_active_q;
    resp_o.r_valid  = ar_active_q;
    resp_o.r.id     = r_id_q;
    resp_o.r.data   = '0;
    resp_o.r.resp   = 2'b00;          // OKAY
    resp_o.r.last   = (r_beats_q == 9'd1);
  end

  // Debug: surface the first handful of outbound writes so a first-run console
  // miss (e.g. an unexpected post-filter address) is diagnosable from the log
  // without a rebuild.
  int unsigned dbg_cnt;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      aw_id_q         <= '0;
      aw_addr_q       <= '0;
      b_valid_q       <= 1'b0;
      ar_active_q     <= 1'b0;
      r_id_q          <= '0;
      r_beats_q       <= '0;
      magic_seen_q    <= 1'b0;
      fw_done_o       <= 1'b0;
      fw_pass_o       <= 1'b0;
      fw_char_o       <= 8'h00;
      fw_char_valid_o <= 1'b0;
      dbg_cnt         <= 0;
    end else begin
      fw_char_valid_o <= 1'b0;  // 1-cycle pulse by default

      if (req_i.aw_valid & resp_o.aw_ready) begin
        aw_id_q   <= req_i.aw.id;
        aw_addr_q <= req_i.aw.addr;
      end

      // Write response: raise B on the last write beat, drop on handshake.
      if (w_fire & req_i.w.last) b_valid_q <= 1'b1;
      if (b_valid_q & req_i.b_ready) b_valid_q <= 1'b0;

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
                   cur_awaddr, req_i.w.strb, req_i.w.data);
          dbg_cnt <= dbg_cnt + 1;
        end
        // Console character: single low-byte store.
        if (req_i.w.strb == 8'h01) begin
          fw_char_o       <= req_i.w.data[7:0];
          fw_char_valid_o <= 1'b1;
        end
        // Test-completion magic: 32-bit word stores (low or high lane).
        if (req_i.w.strb == 8'h0F || req_i.w.strb == 8'hF0) begin
          if (!magic_seen_q) begin
            if (mbx_word == MAGIC0) magic_seen_q <= 1'b1;
          end else begin
            if (mbx_word == MAGIC_PASS) begin
              fw_done_o    <= 1'b1;
              fw_pass_o    <= 1'b1;
              magic_seen_q <= 1'b0;
            end else if (mbx_word == MAGIC_FAIL) begin
              fw_done_o    <= 1'b1;
              fw_pass_o    <= 1'b0;
              magic_seen_q <= 1'b0;
            end else if (mbx_word != MAGIC0) begin
              magic_seen_q <= 1'b0;
            end
          end
        end
      end
    end
  end

endmodule : sep_outbound_mbx
