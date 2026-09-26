// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// PicoRV32 PCPI front-end that decodes KM CRC custom instructions.
//
// Recognizes custom-0 opcodes with the CRC funct7/funct3 encodings, latches
// rs1/rs2 as CRC state and data, and drives km_crc_engine until completion.
// pcpi_wait_o stalls the CPU while busy; pcpi_ready_o and pcpi_wr_o present
// the engine result on pcpi_rd_o for one cycle.

module picorv32_pcpi_crc (
  input  logic        clk_i,         // System clock
  input  logic        rst_ni,        // Active-low reset
  input  logic        pcpi_valid_i,  // PicoRV32 presents a candidate instruction
  input  logic [31:0] pcpi_insn_i,   // Instruction word under decode
  input  logic [31:0] pcpi_rs1_i,    // rs1 value used as CRC state / seed
  input  logic [31:0] pcpi_rs2_i,    // rs2 value used as CRC data
  output logic        pcpi_wr_o,     // Write-back enable for pcpi_rd_o
  output logic [31:0] pcpi_rd_o,     // CRC result returned to the CPU
  output logic        pcpi_wait_o,   // Stall request while the CRC engine runs
  output logic        pcpi_ready_o   // One-cycle ready pulse with a valid result
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  localparam logic [6:0] CRC_OPCODE_CUSTOM0 = 7'b0001011;
  localparam logic [6:0] CRC_FUNCT7 = 7'b0101100;
  localparam logic [2:0] CRC_FUNCT3_32C_WORD = 3'b000;
  localparam logic [2:0] CRC_FUNCT3_32C_BYTE = 3'b001;
  localparam logic [2:0] CRC_FUNCT3_8_ROHC = 3'b010;

  localparam logic [1:0] CRC_MODE_32C_WORD = 2'b00;
  localparam logic [1:0] CRC_MODE_32C_BYTE = 2'b01;
  localparam logic [1:0] CRC_MODE_8_ROHC = 2'b10;

  localparam logic [31:0] CRC32C_POLY = 32'h82F6_3B78;
  localparam logic [31:0] CRC32C_STATE_MASK = 32'hFFFF_FFFF;
  localparam logic [31:0] CRC8_ROHC_POLY = 32'h0000_00E0;
  localparam logic [31:0] CRC8_STATE_MASK = 32'h0000_00FF;

  logic opcode_match;
  logic funct7_match;
  logic recognized_word;
  logic recognized_byte;
  logic recognized_crc8;
  logic insn_recognized;

  logic [1:0] decoded_mode;

  logic active_q;
  logic [1:0]  op_mode_q;
  logic [31:0] op_state_q;
  logic [31:0] op_data_q;

  logic start_pulse;
  logic engine_busy;
  logic engine_done;
  logic [31:0] engine_result;

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

  assign opcode_match    = pcpi_insn_i[6:0] == CRC_OPCODE_CUSTOM0;
  assign funct7_match    = pcpi_insn_i[31:25] == CRC_FUNCT7;
  assign recognized_word = pcpi_valid_i && opcode_match && funct7_match &&
                             pcpi_insn_i[14:12] == CRC_FUNCT3_32C_WORD;
  assign recognized_byte = pcpi_valid_i && opcode_match && funct7_match &&
                             pcpi_insn_i[14:12] == CRC_FUNCT3_32C_BYTE;
  assign recognized_crc8 = pcpi_valid_i && opcode_match && funct7_match &&
                             pcpi_insn_i[14:12] == CRC_FUNCT3_8_ROHC;
  assign insn_recognized = recognized_word || recognized_byte || recognized_crc8;

  always_comb begin
    unique case (1'b1)
      recognized_word: decoded_mode = CRC_MODE_32C_WORD;
      recognized_byte: decoded_mode = CRC_MODE_32C_BYTE;
      recognized_crc8: decoded_mode = CRC_MODE_8_ROHC;
      default:         decoded_mode = CRC_MODE_32C_WORD;
    endcase
  end

  assign start_pulse = insn_recognized && !active_q && !pcpi_ready_o;

  km_crc_engine u_km_crc_engine (
    .clk_i   (clk_i),
    .rst_ni  (rst_ni),
    .start_i (start_pulse),
    .mode_i  (decoded_mode),
    .state_i (pcpi_rs1_i),
    .data_i  (pcpi_rs2_i),
    .busy_o  (engine_busy),
    .done_o  (engine_done),
    .result_o(engine_result)
  );

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      active_q   <= 1'b0;
      op_mode_q  <= CRC_MODE_32C_WORD;
      op_state_q <= '0;
      op_data_q  <= '0;
    end else begin
      if (start_pulse) begin
        active_q   <= 1'b1;
        op_mode_q  <= decoded_mode;
        op_state_q <= pcpi_rs1_i;
        op_data_q  <= pcpi_rs2_i;
      end else if (engine_done) begin
        active_q <= 1'b0;
      end
    end
  end

  assign pcpi_wr_o    = engine_done;
  assign pcpi_ready_o = engine_done;
  assign pcpi_rd_o    = engine_result;
  assign pcpi_wait_o  = start_pulse || active_q;

  `OCAH_ASSERT(WriteImpliesReady_A, pcpi_wr_o |-> pcpi_ready_o, clk_i, !rst_ni)
  `OCAH_ASSERT(RecognizedOnlyStartsWhenIdle_A, start_pulse |-> !active_q, clk_i, !rst_ni)
  `OCAH_ASSERT(
      UnrecognizedNoResponse_A,
      pcpi_valid_i && !insn_recognized && !active_q |-> !pcpi_wait_o && !pcpi_ready_o && !pcpi_wr_o,
      clk_i, !rst_ni)
  `OCAH_ASSERT(
      Crc32cByteLowByteOnly_A,
      engine_done && op_mode_q == CRC_MODE_32C_BYTE |-> engine_result == crc_reflected_byte_step(
      op_state_q, op_data_q[7:0], CRC32C_POLY, CRC32C_STATE_MASK), clk_i, !rst_ni)
  `OCAH_ASSERT(
      Crc8LowByteOnlyZeroExtended_A,
      engine_done && op_mode_q == CRC_MODE_8_ROHC |-> engine_result == crc_reflected_byte_step(
      op_state_q, op_data_q[7:0], CRC8_ROHC_POLY, CRC8_STATE_MASK) && engine_result[31:8] == '0,
      clk_i, !rst_ni)

  `OCAH_ASSERT_PULSE(ReadyPulse_A, pcpi_ready_o, clk_i, !rst_ni)
  `OCAH_ASSERT_PULSE(WritePulse_A, pcpi_wr_o, clk_i, !rst_ni)
  `OCAH_ASSERT_KNOWN(WaitKnown_A, pcpi_wait_o, clk_i, !rst_ni)
  `OCAH_ASSERT_KNOWN(ReadyKnown_A, pcpi_ready_o, clk_i, !rst_ni)
  `OCAH_ASSERT_KNOWN(WriteKnown_A, pcpi_wr_o, clk_i, !rst_ni)
  `OCAH_ASSERT_KNOWN(ReadDataKnown_A, pcpi_rd_o, clk_i, !rst_ni)

endmodule : picorv32_pcpi_crc

