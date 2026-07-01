// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module tt_dff #(parameter WIDTH=8,
		parameter RESET_VALUE=0,
		parameter BYP=0)
	(
		input  logic             i_clk,
		input  logic             i_reset_n,
		input  logic             i_en,
		input  logic [WIDTH-1:0] i_d,

		output logic [WIDTH-1:0] o_q
	);

	// spyglass disable_block STARC-2.3.4.3
	// spyglass disable_block FlopEConst
	/* verilator lint_off BLKANDNBLK */
	if(BYP==0) begin
		always @(posedge i_clk) begin
			if(!i_reset_n) o_q <= WIDTH'(RESET_VALUE);
			else begin
				if(i_en) o_q <= i_d;
			end
		end
	end else begin
		assign o_q = i_d;
	end
	/* verilator lint_on BLKANDNBLK */
	// spyglass enable_block FlopEConst
	// spyglass enable_block STARC-2.3.4.3

endmodule
// Local Variables:
// verilog-library-directories:(".")
// verilog-library-extensions:(".sv" ".h" ".v")
// verilog-typedef-regexp: "_[tseu]$"
// End:
