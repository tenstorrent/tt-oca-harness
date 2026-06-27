// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

module dfd_rv_decoded_mux #(parameter
		DISABLE_ASSERTIONS=0,
		VALUE_WIDTH=32,
		MUX_WIDTH=4
	)
	(
		// spyglass disable_block W240
		input logic                                  i_clk , // This is needed for the assertion
		input logic                                  i_reset_n , // This is needed for the assertion
		input logic                                  i_enable , // This is only used to qualify the assertion
		// spyglass enable_block W240
		input logic [MUX_WIDTH-1:0][VALUE_WIDTH-1:0] i_inputs,
		input logic [MUX_WIDTH-1:0]                  i_select ,

		/* verilator lint_off UNOPTFLAT */
		output logic [VALUE_WIDTH-1:0]               o_output
		/* verilator lint_on UNOPTFLAT */
	);

	generate
		// If these assertions are "don't care" for this instance of the module, set the DISABLE_ASSERTIONS=1 parameter when instantiating the module
		if(DISABLE_ASSERTIONS == 0) begin
			// Check if the select is one-hot
			`RV_ASSERT(MuxSelectNotOneHot, i_clk  , i_reset_n, i_enable,   $onehot(i_select[MUX_WIDTH-1:0])  , "dfd_rv_decoded_mux received a select input signal which was not one-hot")
		end
	endgenerate

// spyglass disable_block W415a
	always_comb begin

		o_output = VALUE_WIDTH'('0);

		for(int m=0; m<MUX_WIDTH; m++) begin
			if (i_select[m]) begin
				o_output |= i_inputs[m];
			end
			// alternate code
			//o_output |= {VALUE_WIDTH{i_select[n]}} & i_inputs[n];
		end

	end
// spyglass enable_block W415a

endmodule
// Local Variables:
// verilog-library-directories:(".")
// verilog-library-extensions:(".sv" ".h" ".v")
// verilog-typedef-regexp: "_[tseu]$"
// End:
