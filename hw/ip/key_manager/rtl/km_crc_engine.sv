// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Compute CRCs one byte per cycle as the shared engine behind the Key Manager PicoRV32
// PCPI CRC instructions.
//
// On start_i it latches mode_i, state_i, and data_i, then folds one reflected byte per
// cycle until the mode's byte count completes. busy_o stays high for the duration; done_o
// pulses with result_o when the last byte finishes. mode_i selects CRC-32C word, CRC-32C
// byte, or CRC-8/ROHC.

module km_crc_engine (
  input  logic        clk_i,    // System clock.
  input  logic        rst_ni,   // Active-low asynchronous reset.
  input  logic        start_i,  // Pulse that begins a CRC operation; ignored while busy_o is high.
  input  logic [1:0]  mode_i,   // CRC mode: 2'b00 CRC-32C word, 2'b01 CRC-32C byte, 2'b10
                                // CRC-8/ROHC; 2'b11 is illegal.
  input  logic [31:0] state_i,  // Incoming CRC state / seed, used without inversion; CRC-8 uses
                                // bits [7:0].
  input  logic [31:0] data_i,   // Data word, folded least-significant byte first; byte modes
                                // use bits [7:0].
  output logic        busy_o,   // High while a CRC operation is in progress.
  output logic        done_o,   // One-cycle pulse when result_o is valid.
  output logic [31:0] result_o  // Final CRC value (CRC-8 zero-extended), held until the next
                                // completion.
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  localparam logic [1:0] CrcMode32cWord = 2'b00;
  localparam logic [1:0] CrcMode32cByte = 2'b01;
  localparam logic [1:0] CrcMode8Rohc = 2'b10;

  localparam logic [31:0] Crc32cPoly = 32'h82F6_3B78;
  localparam logic [31:0] Crc32cStateMask = 32'hFFFF_FFFF;
  localparam logic [31:0] Crc8RohcPoly = 32'h0000_00E0;
  localparam logic [31:0] Crc8StateMask = 32'h0000_00FF;

  logic [1:0]  mode_q;
  logic [2:0]  bytes_remaining_q;
  logic [31:0] state_q;
  logic [31:0] data_q;

  logic [31:0] current_poly;
  logic [31:0] current_mask;
  logic [31:0] next_state;

  function automatic logic mode_legal(input logic [1:0] mode);
    unique case (mode)
      CrcMode32cWord,
            CrcMode32cByte,
            CrcMode8Rohc: mode_legal = 1'b1;
      default:         mode_legal = 1'b0;
    endcase
  endfunction

  function automatic logic [2:0] mode_byte_count(input logic [1:0] mode);
    unique case (mode)
      CrcMode32cWord: mode_byte_count = 3'd4;
      CrcMode32cByte,
            CrcMode8Rohc:   mode_byte_count = 3'd1;
      default:           mode_byte_count = 3'd0;
    endcase
  endfunction

  function automatic logic [31:0] mode_poly(input logic [1:0] mode);
    unique case (mode)
      CrcMode32cWord,
            CrcMode32cByte: mode_poly = Crc32cPoly;
      CrcMode8Rohc:      mode_poly = Crc8RohcPoly;
      default:           mode_poly = Crc32cPoly;
    endcase
  endfunction

  function automatic logic [31:0] mode_mask(input logic [1:0] mode);
    unique case (mode)
      CrcMode32cWord,
            CrcMode32cByte: mode_mask = Crc32cStateMask;
      CrcMode8Rohc:      mode_mask = Crc8StateMask;
      default:           mode_mask = Crc32cStateMask;
    endcase
  endfunction

  function automatic logic [31:0] crc_reflected_byte_step(
      input logic [31:0] state, input logic [7:0] data_byte, input logic [31:0] poly,
      input logic [31:0] state_mask);
    logic [31:0] crc;
    int unsigned bit_idx;
    begin
      crc = (state ^ {24'h0, data_byte}) & state_mask;
      for (bit_idx = 0; bit_idx < 8; bit_idx++) begin
        if (crc[0]) begin
          crc = (crc >> 1) ^ poly;
        end else begin
          crc = crc >> 1;
        end
        crc = crc & state_mask;
      end
      crc_reflected_byte_step = crc & state_mask;
    end
  endfunction

  assign current_poly = mode_poly(mode_q);
  assign current_mask = mode_mask(mode_q);
  assign next_state   = crc_reflected_byte_step(state_q, data_q[7:0], current_poly, current_mask);

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      busy_o            <= 1'b0;
      done_o            <= 1'b0;
      result_o          <= '0;
      mode_q            <= CrcMode32cWord;
      bytes_remaining_q <= '0;
      state_q           <= '0;
      data_q            <= '0;
    end else begin
      done_o <= 1'b0;

      if (start_i && !busy_o) begin
        busy_o            <= 1'b1;
        mode_q            <= mode_i;
        bytes_remaining_q <= mode_byte_count(mode_i);
        state_q           <= state_i;
        data_q            <= data_i;
      end else if (busy_o) begin
        state_q <= next_state;
        data_q  <= {8'h00, data_q[31:8]};

        if (bytes_remaining_q == 3'd1) begin
          busy_o   <= 1'b0;
          done_o   <= 1'b1;
          result_o <= next_state;
        end

        bytes_remaining_q <= bytes_remaining_q - 3'd1;
      end
    end
  end

  `OCAH_ASSERT(LegalModeOnStart_A, start_i |-> mode_legal(mode_i), clk_i, !rst_ni)
  `OCAH_ASSERT(
      StartWordToDone_A,
      start_i && !busy_o && mode_i == CrcMode32cWord |=> busy_o ##1 busy_o ##1 busy_o ##1 busy_o ##1 done_o,
      clk_i, !rst_ni)
  `OCAH_ASSERT(
      StartByteToDone_A,
      start_i && !busy_o && (mode_i == CrcMode32cByte || mode_i == CrcMode8Rohc) |=> busy_o ##1 done_o,
      clk_i, !rst_ni)
  `OCAH_ASSERT(NoRestartWhileBusy_A, busy_o |-> !start_i, clk_i, !rst_ni)
  `OCAH_ASSERT(Crc8ZeroExtended_A, done_o && mode_q == CrcMode8Rohc |-> result_o[31:8] == '0,
               clk_i, !rst_ni)

  `OCAH_ASSERT_PULSE(DonePulse_A, done_o, clk_i, !rst_ni)
  `OCAH_ASSERT_KNOWN(BusyKnown_A, busy_o, clk_i, !rst_ni)
  `OCAH_ASSERT_KNOWN(DoneKnown_A, done_o, clk_i, !rst_ni)
  `OCAH_ASSERT_KNOWN(ResultKnown_A, result_o, clk_i, !rst_ni)

endmodule : km_crc_engine

