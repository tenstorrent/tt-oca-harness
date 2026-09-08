// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module tilelink_to_rom_mem #(
  parameter int unsigned ADDR_WIDTH = 14,
  parameter int unsigned WORD_WIDTH = 64
) (
  input  logic         clk_i,
  input  logic         rst_i,

  output logic         auto_in_a_ready,
  input  logic         auto_in_a_valid,
  input  logic  [1:0]  auto_in_a_bits_size,
  input  logic  [14:0] auto_in_a_bits_source,
  input  logic  [31:0] auto_in_a_bits_address,
  input  logic         auto_in_d_ready,
  output logic         auto_in_d_valid,
  output logic  [1:0]  auto_in_d_bits_size,
  output logic  [14:0] auto_in_d_bits_source,
  output logic  [WORD_WIDTH-1:0] auto_in_d_bits_data,

  input  logic                  rom_flip_endianness_i,

  // Tilelink to generic memory interface conversion outputs
  output logic [ADDR_WIDTH-1:0] rom_address_o,
  output logic                  mem_chip_en_o,
  // Memory data response from ROM
  input  logic [63:0]           rom_bank_data_i
);

  // Flop the incoming request
  logic [1:0]  prev_auto_in_d_bits_size;
  logic [14:0] prev_auto_in_d_bits_source;
  logic [ADDR_WIDTH-1:0] prev_auto_in_bits_address;

  assign auto_in_a_ready = auto_in_d_ready;


  always_ff @(posedge clk_i or posedge rst_i) begin
    if (rst_i) begin
      prev_auto_in_d_bits_size <= 2'd0;
      prev_auto_in_d_bits_source <= 15'd0;
      prev_auto_in_bits_address <= '0;

      auto_in_d_valid <= 1'b0;

    end else begin

      if (auto_in_a_valid && auto_in_a_ready) begin
        auto_in_d_valid <= 1'b1;  // d_valid should be high a cycle after a_valid and a_ready, and REMAIN high until 1 cycle after d_ready is high

        prev_auto_in_d_bits_size <= auto_in_a_bits_size;
        prev_auto_in_d_bits_source <= auto_in_a_bits_source;

        prev_auto_in_bits_address <= auto_in_a_bits_address[3+:ADDR_WIDTH];  // address is byte addressable and rom is word addressable

      end else if (auto_in_d_ready) begin
        auto_in_d_valid <= 1'b0;
      end
    end
  end


  always_comb begin
    if ((auto_in_a_valid && auto_in_a_ready) == 1'b0) begin
      rom_address_o = prev_auto_in_bits_address;  // hold previous request
    end else begin
      rom_address_o = auto_in_a_bits_address[3+:ADDR_WIDTH];
    end

    auto_in_d_bits_source = prev_auto_in_d_bits_source;
    auto_in_d_bits_size   = prev_auto_in_d_bits_size;
  end

  // Have chip enable follow a_valid and d_valid
  always_comb begin
    if (rst_i) begin
      mem_chip_en_o = 1'b0;
    end else if (auto_in_a_valid || auto_in_d_valid) begin
      mem_chip_en_o = 1'b1;
    end else begin
      mem_chip_en_o = 1'b0;
    end
  end

  function automatic logic [63:0] flip_endianness(input logic [WORD_WIDTH-1:0] data);
    return {
      data[7:0],
      data[15:8],
      data[23:16],
      data[31:24],
      data[39:32],
      data[47:40],
      data[55:48],
      data[63:56]
    };
  endfunction

  // Handle an Endian Flip
  always_comb begin
    if (rom_flip_endianness_i) begin
      auto_in_d_bits_data = flip_endianness(rom_bank_data_i);
    end else begin
      auto_in_d_bits_data = rom_bank_data_i;
    end
  end

endmodule
