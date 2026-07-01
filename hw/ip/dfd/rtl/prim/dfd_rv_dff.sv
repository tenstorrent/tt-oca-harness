// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module dfd_rv_dff #(parameter WIDTH=8,
		parameter RESET_VALUE=0,
		parameter BYP=0)
	(
		input  logic             i_clk,
		input  logic             i_reset_n,
		input  logic             i_en,
		input  logic [WIDTH-1:0] i_d,

		output logic [WIDTH-1:0] o_q
	);

	tt_dff #(
		.WIDTH(WIDTH),
		.RESET_VALUE(RESET_VALUE),
		.BYP(BYP)
	) tt_dff_inst (
		.i_clk(i_clk),
		.i_reset_n(i_reset_n),
		.i_en(i_en),
		.i_d(i_d),
		.o_q(o_q)
	);

endmodule
// Local Variables:
// verilog-library-directories:(".")
// verilog-library-extensions:(".sv" ".h" ".v")
// verilog-typedef-regexp: "_[tseu]$"
// End:
