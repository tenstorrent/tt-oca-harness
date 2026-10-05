/* Split from YosysHQ PicoRV32; see picorv32.sv for full license. */
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
module picorv32_pcpi_fast_mul #(
	parameter EXTRA_MUL_FFS = 0,
	parameter EXTRA_INSN_FFS = 0,
	parameter MUL_CLKGATE = 0
) (
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
	logic instr_mul, instr_mulh, instr_mulhsu, instr_mulhu;
	logic instr_any_mul;
	logic instr_any_mulh;
	logic instr_rs1_signed;
	logic instr_rs2_signed;

	logic shift_out;
	logic [3:0] active;
	logic [32:0] rs1, rs2, rs1_q, rs2_q;
	logic [63:0] rd, rd_q;

	logic pcpi_insn_valid;
	logic pcpi_insn_valid_q;

	assign instr_any_mul = |{instr_mul, instr_mulh, instr_mulhsu, instr_mulhu};
	assign instr_any_mulh = |{instr_mulh, instr_mulhsu, instr_mulhu};
	assign instr_rs1_signed = |{instr_mulh, instr_mulhsu};
	assign instr_rs2_signed = instr_mulh;
	assign pcpi_insn_valid =
			pcpi_valid && pcpi_insn[6:0] == 7'b0110011 && pcpi_insn[31:25] == 7'b0000001;

	always_comb begin
		instr_mul = 1'b0;
		instr_mulh = 1'b0;
		instr_mulhsu = 1'b0;
		instr_mulhu = 1'b0;

		if (resetn && (EXTRA_INSN_FFS ? pcpi_insn_valid_q : pcpi_insn_valid)) begin
			case (pcpi_insn[14:12])
				3'b000: instr_mul = 1;
				3'b001: instr_mulh = 1;
				3'b010: instr_mulhsu = 1;
				3'b011: instr_mulhu = 1;
			endcase
		end
	end

	always_ff @(posedge clk) begin
		pcpi_insn_valid_q <= pcpi_insn_valid;
		if (!MUL_CLKGATE || active[0]) begin
			rs1_q <= rs1;
			rs2_q <= rs2;
		end
		if (!MUL_CLKGATE || active[1]) begin
			rd <= $signed(EXTRA_MUL_FFS ? rs1_q : rs1) * $signed(EXTRA_MUL_FFS ? rs2_q : rs2);
		end
		if (!MUL_CLKGATE || active[2]) begin
			rd_q <= rd;
		end
	end

	always_ff @(posedge clk) begin
		if (instr_any_mul && !(EXTRA_MUL_FFS ? active[3:0] : active[1:0])) begin
			if (instr_rs1_signed)
				rs1 <= $signed(pcpi_rs1);
			else
				rs1 <= $unsigned(pcpi_rs1);

			if (instr_rs2_signed)
				rs2 <= $signed(pcpi_rs2);
			else
				rs2 <= $unsigned(pcpi_rs2);
			active[0] <= 1;
		end else begin
			active[0] <= 0;
		end

		active[3:1] <= active;
		shift_out <= instr_any_mulh;

		if (!resetn)
			active <= 0;
	end

	assign pcpi_wr = active[EXTRA_MUL_FFS ? 3 : 1];
	assign pcpi_wait = 1'b0;
	assign pcpi_ready = active[EXTRA_MUL_FFS ? 3 : 1];
`ifdef RISCV_FORMAL_ALTOPS
	assign pcpi_rd =
			instr_mul    ? (pcpi_rs1 + pcpi_rs2) ^ 32'h5876063e :
			instr_mulh   ? (pcpi_rs1 + pcpi_rs2) ^ 32'hf6583fb7 :
			instr_mulhsu ? (pcpi_rs1 - pcpi_rs2) ^ 32'hecfbe137 :
			instr_mulhu  ? (pcpi_rs1 + pcpi_rs2) ^ 32'h949ce5e8 : 1'bx;
`else
	assign pcpi_rd = shift_out ? (EXTRA_MUL_FFS ? rd_q : rd) >> 32 : (EXTRA_MUL_FFS ? rd_q : rd);
`endif
endmodule
