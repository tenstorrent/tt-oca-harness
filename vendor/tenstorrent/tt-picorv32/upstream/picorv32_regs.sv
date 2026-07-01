/* Split from YosysHQ PicoRV32; see picorv32.sv for full license. */
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
// This is a simple example implementation of PICORV32_REGS.
// Use the PICORV32_REGS mechanism if you want to use custom
// memory resources to implement the processor register file.
// Note that your implementation must match the requirements of
// the PicoRV32 configuration. (e.g. QREGS, etc)
module picorv32_regs (
	input  wire logic       clk,
	input  wire logic       wen,
	input  wire logic [5:0] waddr,
	input  wire logic [5:0] raddr1,
	input  wire logic [5:0] raddr2,
	input  wire logic [31:0] wdata,
	output logic [31:0]     rdata1,
	output logic [31:0]     rdata2
);
	localparam int unsigned NUM_REGS = 20;

	logic [31:0] regs [0:NUM_REGS-1];

	always_ff @(posedge clk)
		if (wen && waddr < NUM_REGS) regs[waddr] <= wdata;

	assign rdata1 = (raddr1 < NUM_REGS) ? regs[raddr1] : 'x;
	assign rdata2 = (raddr2 < NUM_REGS) ? regs[raddr2] : 'x;
endmodule
