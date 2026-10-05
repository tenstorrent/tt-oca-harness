/* Split from YosysHQ PicoRV32; see picorv32.sv for full license. */
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
/***************************************************************
 * picorv32_axi_adapter
 ***************************************************************/

module picorv32_axi_adapter (
	input wire logic clk,
	input wire logic resetn,

	// AXI4-lite master memory interface

	output logic        mem_axi_awvalid,
	input  wire logic   mem_axi_awready,
	output logic [31:0] mem_axi_awaddr,
	output logic [ 2:0] mem_axi_awprot,

	output logic        mem_axi_wvalid,
	input  wire logic   mem_axi_wready,
	output logic [31:0] mem_axi_wdata,
	output logic [ 3:0] mem_axi_wstrb,

	input  wire logic   mem_axi_bvalid,
	output logic        mem_axi_bready,

	output logic        mem_axi_arvalid,
	input  wire logic   mem_axi_arready,
	output logic [31:0] mem_axi_araddr,
	output logic [ 2:0] mem_axi_arprot,

	input  wire logic   mem_axi_rvalid,
	output logic        mem_axi_rready,
	input  wire logic [31:0] mem_axi_rdata,

	// Native PicoRV32 memory interface

	input  wire logic        mem_valid,
	input  wire logic        mem_instr,
	output logic             mem_ready,
	input  wire logic [31:0] mem_addr,
	input  wire logic [31:0] mem_wdata,
	input  wire logic [ 3:0] mem_wstrb,
	output logic [31:0]      mem_rdata
);
	logic ack_awvalid;
	logic ack_arvalid;
	logic ack_wvalid;
	logic xfer_done;

	assign mem_axi_awvalid = mem_valid && |mem_wstrb && !ack_awvalid;
	assign mem_axi_awaddr = mem_addr;
	assign mem_axi_awprot = 3'b000;

	assign mem_axi_arvalid = mem_valid && !mem_wstrb && !ack_arvalid;
	assign mem_axi_araddr = mem_addr;
	assign mem_axi_arprot = mem_instr ? 3'b100 : 3'b000;

	assign mem_axi_wvalid = mem_valid && |mem_wstrb && !ack_wvalid;
	assign mem_axi_wdata = mem_wdata;
	assign mem_axi_wstrb = mem_wstrb;

	assign mem_ready = mem_axi_bvalid || mem_axi_rvalid;
	assign mem_axi_bready = mem_valid && |mem_wstrb;
	assign mem_axi_rready = mem_valid && !mem_wstrb;
	assign mem_rdata = mem_axi_rdata;

	always_ff @(posedge clk) begin
		if (!resetn) begin
			ack_awvalid <= 1'b0;
		end else begin
			xfer_done <= mem_valid && mem_ready;
			if (mem_axi_awready && mem_axi_awvalid)
				ack_awvalid <= 1'b1;
			if (mem_axi_arready && mem_axi_arvalid)
				ack_arvalid <= 1'b1;
			if (mem_axi_wready && mem_axi_wvalid)
				ack_wvalid <= 1'b1;
			if (xfer_done || !mem_valid) begin
				ack_awvalid <= 1'b0;
				ack_arvalid <= 1'b0;
				ack_wvalid <= 1'b0;
			end
		end
	end
endmodule
