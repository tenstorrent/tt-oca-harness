/* Split from YosysHQ PicoRV32; see picorv32.sv for full license. */
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
/***************************************************************
 * picorv32_pcpi_div
 ***************************************************************/

module picorv32_pcpi_div (
	input wire logic clk,
	input wire logic resetn,

	input  wire logic        pcpi_valid,
	input  wire logic [31:0] pcpi_insn,
	input  wire logic [31:0] pcpi_rs1,
	input  wire logic [31:0] pcpi_rs2,
	output logic             pcpi_wr,
	output logic [31:0]      pcpi_rd,
	output logic             pcpi_wait,
	output logic             pcpi_ready
);
	logic instr_div, instr_divu, instr_rem, instr_remu;
	logic instr_any_div_rem;

	logic pcpi_wait_q;
	logic start;

	assign instr_any_div_rem = |{instr_div, instr_divu, instr_rem, instr_remu};
	assign start = pcpi_wait && !pcpi_wait_q;

	always_ff @(posedge clk) begin
		instr_div <= 1'b0;
		instr_divu <= 1'b0;
		instr_rem <= 1'b0;
		instr_remu <= 1'b0;

		if (resetn && pcpi_valid && !pcpi_ready && pcpi_insn[6:0] == 7'b0110011 && pcpi_insn[31:25] == 7'b0000001) begin
			case (pcpi_insn[14:12])
				3'b100: instr_div <= 1;
				3'b101: instr_divu <= 1;
				3'b110: instr_rem <= 1;
				3'b111: instr_remu <= 1;
			endcase
		end

		pcpi_wait <= instr_any_div_rem && resetn;
		pcpi_wait_q <= pcpi_wait && resetn;
	end

	logic [31:0] dividend;
	logic [62:0] divisor;
	logic [31:0] quotient;
	logic [31:0] quotient_msk;
	logic running;
	logic outsign;

	always_ff @(posedge clk) begin
		pcpi_ready <= 1'b0;
		pcpi_wr <= 1'b0;
		pcpi_rd <= 'bx;

		if (!resetn) begin
			running <= 1'b0;
		end else
		if (start) begin
			running <= 1'b1;
			dividend <= (instr_div || instr_rem) && pcpi_rs1[31] ? -pcpi_rs1 : pcpi_rs1;
			divisor <= ((instr_div || instr_rem) && pcpi_rs2[31] ? -pcpi_rs2 : pcpi_rs2) << 31;
			outsign <= (instr_div && (pcpi_rs1[31] != pcpi_rs2[31]) && |pcpi_rs2) || (instr_rem && pcpi_rs1[31]);
			quotient <= '0;
			quotient_msk <= 32'h8000_0000;
		end else
		if (!quotient_msk && running) begin
			running <= 1'b0;
			pcpi_ready <= 1'b1;
			pcpi_wr <= 1'b1;
`ifdef RISCV_FORMAL_ALTOPS
			case (1)
				instr_div:  pcpi_rd <= (pcpi_rs1 - pcpi_rs2) ^ 32'h7f8529ec;
				instr_divu: pcpi_rd <= (pcpi_rs1 - pcpi_rs2) ^ 32'h10e8fd70;
				instr_rem:  pcpi_rd <= (pcpi_rs1 - pcpi_rs2) ^ 32'h8da68fa5;
				instr_remu: pcpi_rd <= (pcpi_rs1 - pcpi_rs2) ^ 32'h3138d0e1;
			endcase
`else
			if (instr_div || instr_divu)
				pcpi_rd <= outsign ? -quotient : quotient;
			else
				pcpi_rd <= outsign ? -dividend : dividend;
`endif
		end else begin
			if (divisor <= dividend) begin
				dividend <= dividend - divisor;
				quotient <= quotient | quotient_msk;
			end
			divisor <= divisor >> 1;
`ifdef RISCV_FORMAL_ALTOPS
			quotient_msk <= quotient_msk >> 5;
`else
			quotient_msk <= quotient_msk >> 1;
`endif
		end
	end
endmodule
