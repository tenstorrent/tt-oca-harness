// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

module dfd_rv_ccg #(parameter WIDTH=1,
		parameter LATE_EN=0,  // self-gate = 0, no self-gate = 1
		parameter HYST=1,     // hysteresis enabled or not
		parameter HYST_CYC=2) // number of hysteresis cycles
	(
		input                    i_clk,
		input                    i_reset_n,
		input [WIDTH-1:0]        i_en,
		input                    i_force,
		input                    i_hyst,
		input                    i_te,
		output logic [WIDTH-1:0] o_clk
	);

	localparam HSIZE = (HYST_CYC == 1) ? 1 : $clog2(HYST_CYC);

	logic [WIDTH-1:0]              o_en;
	logic [WIDTH-1:0]            HystOn;
	wire [WIDTH-1:0]             VerifForceEn;

	genvar          i;

	assign VerifForceEn = {WIDTH{1'b0}};

	generate
		// Use LATE_EN when enable term is late in the cycle
		if (LATE_EN[0]) begin : nogate_ff
			always @(posedge i_clk) begin
				o_en <= i_en | {WIDTH{~i_reset_n | i_force}} | HystOn | VerifForceEn;
			end
		end
		// LATE_EN = 0, use enable to self gate the coarse flop
		else begin : gate_ff
			for (i=0; i<WIDTH; i=i+1) begin : ff
				always @(posedge i_clk) begin
					if (i_en[i] | ~i_reset_n | i_force | HystOn[i] | VerifForceEn[i]) begin
						o_en[i] <= 1'b1;
					end
					else begin
						o_en[i] <= 1'b0;
					end
				end
			end
		end // block: gate_ff

		if (HYST[0]) begin : hyst_on
			logic [WIDTH-1:0][HSIZE-1:0] HystCount;
			for (i=0; i<WIDTH; i=i+1) begin : hyst_ff
				always @(posedge i_clk) begin
					if (~i_reset_n) HystCount[i] <= '0;
					else if (i_en[i] & i_hyst) HystCount[i] <= (HSIZE)'(HYST_CYC-1);
					else HystCount[i] <= HystCount[i] - (HSIZE)'(|HystCount[i]);
				end
				assign HystOn[i] = |HystCount[i];
			end
		end
		else begin : hyst_off
			assign HystOn = '0;
		end
	endgenerate

`ifdef CCG_BYPASS
	assign o_clk = i_clk;
`elsif SYNTHESIS
	generate
		for (i=0; i<WIDTH; i=i+1) begin : cg
			prim_clkgater clkgate (
				.i_clk(i_clk),
				.i_en(o_en[i]),
				.i_te(i_te),
				.o_clk(o_clk[i])
			);
		end // cg
	endgenerate
`else
	logic [WIDTH-1:0] latched_en /*verilator clock_enable*/;
	always_latch begin
		if (!i_clk) latched_en = o_en;
	end
	assign o_clk = {WIDTH{i_clk}} & latched_en;
`endif
endmodule
