// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Add a_i and b_i with a carry-select datapath split into NUM_CHUNKS.
//
// Compute each chunk for carry-in 0 and 1, then select on the prior carry.
// Drive c_o with the final carry out of the MSB chunk.
// DATA_WIDTH must divide evenly across NUM_CHUNKS.

module prim_carry_select_adder #(
  parameter int unsigned DATA_WIDTH = 64,  // Operand width.
  parameter int unsigned NUM_CHUNKS = 2  // Number of carry-select chunks.
) (
  input  logic [DATA_WIDTH-1:0] a_i,  // Addend A.
  input  logic [DATA_WIDTH-1:0] b_i,  // Addend B.
  output logic [DATA_WIDTH-1:0] sum_o,  // Sum result.
  output logic                  c_o  // Carry out.
);

  localparam int unsigned ChunkWidth = DATA_WIDTH / NUM_CHUNKS;

  logic [NUM_CHUNKS-1:0][ChunkWidth-1:0] sum_chunk;
  logic [NUM_CHUNKS-1:1][ChunkWidth:0] sum_chunk_c0, sum_chunk_c1;
  logic [NUM_CHUNKS-1:0]                  carry;
  logic carry_prev;

  always_comb begin

    // Sum 1st chunk separately, as it doesn't need carry-select logic
    {carry_prev, sum_chunk[0]} = a_i[0 +: ChunkWidth] + b_i[0 +: ChunkWidth];
    carry[0]                   = carry_prev;

    // Sum the rest with carry-select logic
    for (int i = 1; i < NUM_CHUNKS; i++) begin
      // Compute sum and mux based on carry
      sum_chunk_c0[i]          = a_i[i*ChunkWidth +: ChunkWidth] + b_i[i*ChunkWidth +: ChunkWidth];
      sum_chunk_c1[i]          = a_i[i*ChunkWidth +: ChunkWidth] + b_i[i*ChunkWidth +: ChunkWidth] + 1'b1;
      {carry[i], sum_chunk[i]} = carry_prev ? sum_chunk_c1[i] : sum_chunk_c0[i];
      carry_prev               = carry[i];
    end
  end

  assign sum_o  = sum_chunk;
  assign c_o = carry[NUM_CHUNKS-1];

  // Assertion to make sure NUM_CHUNKS divides DATA_WIDTH without remainder
  if (DATA_WIDTH % NUM_CHUNKS != 0) begin : gen_error
    $error("DATA_WIDTH must be a multiple of NUM_CHUNKS");
  end

endmodule
