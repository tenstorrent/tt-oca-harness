// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

// Owner: Deepak
// Description: This module takes an input of bits and detect if the bit-vector is zero-one-hot or not

module dfd_rv_onehot_detect #(parameter WIDTH       = 8,                                        //Number of inputs.
		SIZE        = ($clog2(WIDTH) > 1 ? $clog2(WIDTH) : 1),  //Log2 Number of inputs
		ZERO_ONEHOT = 0                                         // Detect one-hot instead of zero-one-hot
	)

	(
		input  logic [WIDTH-1:0] input_bit_vector,
		output logic             is_one_hot
	);


	localparam PAD_WIDTH = 1 << SIZE;

	//This needs to be a complete binary tree, therefore add padding internally.
	logic [PAD_WIDTH-1:0]           pad_bit_vector;

	// Create per level one-bit or two-bit vectors
	logic [SIZE:0][PAD_WIDTH-1:0] is_intermediate_atleast_one_bit_set;
	logic [SIZE:0][PAD_WIDTH-1:0] is_intermediate_atleast_two_bit_set;

	// PAD the upper bits if zero if the vector is not a power of 2 width
	if (WIDTH != PAD_WIDTH) begin
		assign pad_bit_vector  = {{(PAD_WIDTH-WIDTH){1'b0}}, input_bit_vector};
	end else begin
		assign pad_bit_vector  = {input_bit_vector};
	end

	// Generate the intermediate one-bit and two-bit vectors
	always_comb begin
		// Populate the first level
		is_intermediate_atleast_one_bit_set[SIZE] = pad_bit_vector;
		is_intermediate_atleast_two_bit_set[SIZE] = '0;

		// Traverse the tree and update the intermediate nodes
		for (int LVL=(SIZE-1); LVL>=0; LVL--) begin
			for (int NODE=0; NODE<(1<<LVL); NODE++) begin
				is_intermediate_atleast_one_bit_set[LVL][NODE] =  (is_intermediate_atleast_one_bit_set[LVL+1][2*NODE] | is_intermediate_atleast_one_bit_set[LVL+1][(2*NODE)+1]);
				is_intermediate_atleast_two_bit_set[LVL][NODE] =   is_intermediate_atleast_two_bit_set[LVL+1][2*NODE]
					| is_intermediate_atleast_two_bit_set[LVL+1][(2*NODE)+1]
					| (is_intermediate_atleast_one_bit_set[LVL+1][2*NODE] & is_intermediate_atleast_one_bit_set[LVL+1][(2*NODE)+1]);
			end
		end
	end

	// Root node gives the final answer
	assign is_one_hot = ZERO_ONEHOT ? ~is_intermediate_atleast_two_bit_set[0][0] :
		(~is_intermediate_atleast_two_bit_set[0][0] & is_intermediate_atleast_one_bit_set[0][0]);

endmodule
// Local Variables:
// verilog-library-directories:(".")
// verilog-library-extensions:(".sv" ".h" ".v")
// verilog-typedef-regexp: "_[tseu]$"
// End:
