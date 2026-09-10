// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Carry Select Adder
//
//--------------------------------------------------
module prim_carry_select_adder #(
  parameter int unsigned DATA_WIDTH = 64,
  parameter int unsigned NUM_CHUNKS = 2
) (
  input  logic [DATA_WIDTH-1:0] a_i,
  input  logic [DATA_WIDTH-1:0] b_i,
  output logic [DATA_WIDTH-1:0] sum_o,
  output logic                  cout_o
);

  localparam int unsigned CHUNK_WIDTH = DATA_WIDTH / NUM_CHUNKS;

  logic [NUM_CHUNKS-1:0][CHUNK_WIDTH-1:0] sum_chunk;
  logic [NUM_CHUNKS-1:1][CHUNK_WIDTH:0] sum_chunk_c0, sum_chunk_c1;
  logic [NUM_CHUNKS-1:0]                  carry;
  logic carry_prev;

  always_comb begin

    // Sum 1st chunk separately, as it doesn't need carry-select logic
    {carry_prev, sum_chunk[0]} = a_i[0 +: CHUNK_WIDTH] + b_i[0 +: CHUNK_WIDTH];
    carry[0]                   = carry_prev;

    // Sum the rest with carry-select logic
    for (int i = 1; i < NUM_CHUNKS; i++) begin
      // Compute sum and mux based on carry
      sum_chunk_c0[i]          = a_i[i*CHUNK_WIDTH +: CHUNK_WIDTH] + b_i[i*CHUNK_WIDTH +: CHUNK_WIDTH];
      sum_chunk_c1[i]          = a_i[i*CHUNK_WIDTH +: CHUNK_WIDTH] + b_i[i*CHUNK_WIDTH +: CHUNK_WIDTH] + 1'b1;
      {carry[i], sum_chunk[i]} = carry_prev ? sum_chunk_c1[i] : sum_chunk_c0[i];
      carry_prev               = carry[i];
    end
  end

  assign sum_o  = sum_chunk;
  assign cout_o = carry[NUM_CHUNKS-1];

  // Assertion to make sure NUM_CHUNKS divides DATA_WIDTH without remainder
  generate
    if (DATA_WIDTH % NUM_CHUNKS != 0) begin : gen_error
      $error("DATA_WIDTH must be a multiple of NUM_CHUNKS");
    end
  endgenerate

endmodule
