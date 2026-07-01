// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module dfd_xtrigger_stretch_circuit
	import dfd_cla_csr_pkg::*;
	import dfd_cla_pkg::*;
	(
		input  logic                              clock,
		input  logic                              reset_n,
		input  logic                              reset_n_warm_ovrride,

		input  logic   [XTRIGGER_WIDTH-1:0]      xtrigger_in,
		output logic   [XTRIGGER_WIDTH-1:0]      xtrigger_out,

		// Registers
		input CrCdbgclaxtriggertimestretchCsr_s   CrCsrCdbgclaxtriggertimestretch
	);

// Stretch width
	localparam XTRIGGER_STRETCH_CNTR_WIDTH = 8;

// Stretch logic
	logic [XTRIGGER_WIDTH-1:0][XTRIGGER_STRETCH_CNTR_WIDTH-1:0] xtrigger_stretch_cntr, xtrigger_stretch_cntr_nxt;
	logic [XTRIGGER_WIDTH-1:0] xtrigger_stretch_cntr_en;
	logic [XTRIGGER_WIDTH-1:0] xtrigger_stretch_cntr_clr;
	logic [XTRIGGER_WIDTH-1:0] xtrigger_stretch_in_d1;
	logic [XTRIGGER_WIDTH-1:0] xtrigger_stretch_out;
	logic [XTRIGGER_WIDTH-1:0][XTRIGGER_STRETCH_CNTR_WIDTH-1:0] xtrigger_stretch;

// Stretch control signals
	assign xtrigger_stretch[0] = CrCsrCdbgclaxtriggertimestretch.Xtrigger0Stretch;
	assign xtrigger_stretch[1] = CrCsrCdbgclaxtriggertimestretch.Xtrigger1Stretch;

// Stretch circuit
	for (genvar i=0; i<XTRIGGER_WIDTH; i++) begin: stretch_circuit
		// Posedge detection
		dfd_rv_dff #(.WIDTH(1)) xtrigger_in_d1_ff (.o_q(xtrigger_stretch_in_d1[i]), .i_d(xtrigger_in[i]), .i_en(1'b1), .i_clk(clock), .i_reset_n(reset_n));

		// Detect new pulse (posedge)
		logic xtrigger_posedge;
		assign xtrigger_posedge = xtrigger_in[i] & ~xtrigger_stretch_in_d1[i];

		// Stretch output control logic
		logic xtrigger_stretch_clear;
		logic xtrigger_stretch_d_next;
		assign xtrigger_stretch_clear = (xtrigger_stretch_cntr[i] == xtrigger_stretch[i]) && (xtrigger_stretch[i] != 0);
		assign xtrigger_stretch_d_next = xtrigger_posedge | (xtrigger_stretch_out[i] & ~xtrigger_stretch_clear);

		dfd_rv_dff_clr #(.WIDTH(1)) xtrigger_stretch_out_ff (
			.o_q(xtrigger_stretch_out[i]),
			.i_d(xtrigger_stretch_d_next),
			.i_clr(1'b0),
			.i_en(1'b1),
			.i_clk(clock),
			.i_reset_n(reset_n)
		);

		// Enable counter when stretch is active
		assign xtrigger_stretch_cntr_en[i] = xtrigger_stretch_out[i] && (xtrigger_stretch[i] != 0);

		// Increment counter
		assign xtrigger_stretch_cntr_nxt[i] = XTRIGGER_STRETCH_CNTR_WIDTH'(xtrigger_stretch_cntr[i] + 1'b1);

		// Clear counter when:
		// 1. New pulse arrives (restart stretching)
		// 2. Counter has reached the stretch width (stretch complete)
		assign xtrigger_stretch_cntr_clr[i] = xtrigger_posedge || xtrigger_stretch_clear;

		// Counter
		dfd_rv_dff_clr #(.WIDTH(XTRIGGER_STRETCH_CNTR_WIDTH)) xtrigger_stretch_cntr_ff (
			.o_q(xtrigger_stretch_cntr[i]),
			.i_d(xtrigger_stretch_cntr_nxt[i]),
			.i_clr(xtrigger_stretch_cntr_clr[i]),
			.i_en(xtrigger_stretch_cntr_en[i]),
			.i_clk(clock),
			.i_reset_n(reset_n)
		);

		// Stretch output
		assign xtrigger_out[i] = xtrigger_in[i] | xtrigger_stretch_out[i];

	end

endmodule
