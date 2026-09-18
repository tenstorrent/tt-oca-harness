// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Zero counter
//
//--------------------------------------------------

module prim_zero_counter #(
  /// The width of the input vector.
  parameter int unsigned WIDTH = 2,
  /// COUNT_LEADING selection: 0 -> trailing zero, 1 -> leading zero
  parameter bit          COUNT_LEADING  = 1'b0,
  /// Dependent parameter. Do **not** change!
  ///
  /// Width of the output signal with the zero count.
  localparam int unsigned CNT_WIDTH = WIDTH > 1 ? $clog2(WIDTH) : 1
) (
  /// Input vector to be counted.
  input  logic [WIDTH-1:0]     in_i,
  /// Count of the leading / trailing zeros.
  output logic [CNT_WIDTH-1:0] count_o,
  /// Counter is empty: Asserted if all bits in in_i are zero.
  output logic                 empty_o
);

  `include "ocah_assert.svh"

  if (WIDTH == 1) begin : gen_degenerate_lzc

    assign count_o[0] = !in_i[0];
    assign empty_o = !in_i[0];

  end else begin : gen_lzc

    localparam int unsigned NumLevels = $clog2(WIDTH);

    logic [WIDTH-1:0][NumLevels-1:0] index_lut;
    logic [2**NumLevels-1:0] sel_nodes;
    logic [2**NumLevels-1:0][NumLevels-1:0] index_nodes;

    logic [WIDTH-1:0] in_tmp;

    // reverse vector if required
    always_comb begin : flip_vector
      for (int unsigned i = 0; i < WIDTH; i++) begin
        in_tmp[i] = (COUNT_LEADING) ? in_i[WIDTH-1-i] : in_i[i];
      end
    end

    for (genvar j = 0; unsigned'(j) < WIDTH; j++) begin : gen_index_lut
      assign index_lut[j] = (NumLevels)'(unsigned'(j));
    end

    for (genvar level = 0; unsigned'(level) < NumLevels; level++) begin : gen_levels
      if (unsigned'(level) == NumLevels - 1) begin : gen_last_level
        for (genvar k = 0; k < 2 ** level; k++) begin : gen_level
          // if two successive indices are still in the vector...
          if (unsigned'(k) * 2 < WIDTH - 1) begin : gen_reduce
            assign sel_nodes[2 ** level - 1 + k] = in_tmp[k * 2] | in_tmp[k * 2 + 1];
            assign index_nodes[2 ** level - 1 + k] = (in_tmp[k * 2] == 1'b1)
              ? index_lut[k * 2] :
                index_lut[k * 2 + 1];
          end
          // if only the first index is still in the vector...
          if (unsigned'(k) * 2 == WIDTH - 1) begin : gen_base
            assign sel_nodes[2 ** level - 1 + k] = in_tmp[k * 2];
            assign index_nodes[2 ** level - 1 + k] = index_lut[k * 2];
          end
          // if index is out of range
          if (unsigned'(k) * 2 > WIDTH - 1) begin : gen_out_of_range
            assign sel_nodes[2 ** level - 1 + k] = 1'b0;
            assign index_nodes[2 ** level - 1 + k] = '0;
          end
        end
      end else begin : gen_not_last_level
        for (genvar l = 0; l < 2 ** level; l++) begin : gen_level
          assign sel_nodes[2 ** level - 1 + l] =
              sel_nodes[2 ** (level + 1) - 1 + l * 2] | sel_nodes[2 ** (level + 1) - 1 + l * 2 + 1];
          assign index_nodes[2 ** level - 1 + l] = (sel_nodes[2 ** (level + 1) - 1 + l * 2] == 1'b1)
            ? index_nodes[2 ** (level + 1) - 1 + l * 2] :
              index_nodes[2 ** (level + 1) - 1 + l * 2 + 1];
        end
      end
    end

    assign count_o = NumLevels > unsigned'(0) ? index_nodes[0] : {($clog2(WIDTH)) {1'b0}};
    assign empty_o = NumLevels > unsigned'(0) ? ~sel_nodes[0] : ~(|in_i);

  end : gen_lzc

  `OCAH_ASSERT_INIT(WidthConstraintA, WIDTH >= 1)

endmodule : prim_zero_counter
