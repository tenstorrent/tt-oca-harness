/* Split from YosysHQ PicoRV32; see picorv32.sv for full license. */
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
/***************************************************************
 * picorv32_pcpi_mul
 ***************************************************************/

module picorv32_pcpi_mul #(
	parameter STEPS_AT_ONCE = 1,
	parameter CARRY_CHAIN = 4
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

	logic pcpi_wait_q;
	logic mul_start;

	assign instr_any_mul = |{instr_mul, instr_mulh, instr_mulhsu, instr_mulhu};
	assign instr_any_mulh = |{instr_mulh, instr_mulhsu, instr_mulhu};
	assign instr_rs1_signed = |{instr_mulh, instr_mulhsu};
	assign instr_rs2_signed = instr_mulh;
	assign mul_start = pcpi_wait && !pcpi_wait_q;

	always_ff @(posedge clk) begin
		instr_mul <= 1'b0;
		instr_mulh <= 1'b0;
		instr_mulhsu <= 1'b0;
		instr_mulhu <= 1'b0;

		if (resetn && pcpi_valid && pcpi_insn[6:0] == 7'b0110011 && pcpi_insn[31:25] == 7'b0000001) begin
			case (pcpi_insn[14:12])
				3'b000: instr_mul <= 1;
				3'b001: instr_mulh <= 1;
				3'b010: instr_mulhsu <= 1;
				3'b011: instr_mulhu <= 1;
			endcase
		end

		pcpi_wait <= instr_any_mul;
		pcpi_wait_q <= pcpi_wait;
	end

	logic [63:0] rs1, rs2, rd, rdx;
	logic [63:0] next_rs1, next_rs2, this_rs2;
	logic [63:0] next_rd, next_rdx, next_rdt;
	logic [6:0] mul_counter;
	logic mul_waiting;
	logic mul_finish;
	integer i, j;

	// carry save accumulator
	always_comb begin
		next_rd = rd;
		next_rdx = rdx;
		next_rs1 = rs1;
		next_rs2 = rs2;

		for (i = 0; i < STEPS_AT_ONCE; i=i+1) begin
			this_rs2 = next_rs1[0] ? next_rs2 : 0;
			if (CARRY_CHAIN == 0) begin
				next_rdt = next_rd ^ next_rdx ^ this_rs2;
				next_rdx = ((next_rd & next_rdx) | (next_rd & this_rs2) | (next_rdx & this_rs2)) << 1;
				next_rd = next_rdt;
			end else begin
				next_rdt = '0;
				for (j = 0; j < 64; j = j + CARRY_CHAIN)
					{next_rdt[j+CARRY_CHAIN-1], next_rd[j +: CARRY_CHAIN]} =
							next_rd[j +: CARRY_CHAIN] + next_rdx[j +: CARRY_CHAIN] + this_rs2[j +: CARRY_CHAIN];
				next_rdx = next_rdt << 1;
			end
			next_rs1 = next_rs1 >> 1;
			next_rs2 = next_rs2 << 1;
		end
	end

	always_ff @(posedge clk) begin
		mul_finish <= 1'b0;
		if (!resetn) begin
			mul_waiting <= 1'b1;
		end else
		if (mul_waiting) begin
			if (instr_rs1_signed)
				rs1 <= $signed(pcpi_rs1);
			else
				rs1 <= $unsigned(pcpi_rs1);

			if (instr_rs2_signed)
				rs2 <= $signed(pcpi_rs2);
			else
				rs2 <= $unsigned(pcpi_rs2);

			rd <= '0;
			rdx <= '0;
			mul_counter <= (instr_any_mulh ? 63 - STEPS_AT_ONCE : 31 - STEPS_AT_ONCE);
			mul_waiting <= !mul_start;
		end else begin
			rd <= next_rd;
			rdx <= next_rdx;
			rs1 <= next_rs1;
			rs2 <= next_rs2;

			mul_counter <= mul_counter - STEPS_AT_ONCE;
			if (mul_counter[6]) begin
				mul_finish <= 1'b1;
				mul_waiting <= 1'b1;
			end
		end
	end

	always_ff @(posedge clk) begin
		pcpi_wr <= 1'b0;
		pcpi_ready <= 1'b0;
		if (mul_finish && resetn) begin
			pcpi_wr <= 1'b1;
			pcpi_ready <= 1'b1;
			pcpi_rd <= instr_any_mulh ? rd >> 32 : rd;
		end
	end
endmodule
