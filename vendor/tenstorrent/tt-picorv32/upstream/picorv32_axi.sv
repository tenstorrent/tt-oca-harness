/* Split from YosysHQ PicoRV32; see picorv32.sv for full license. */
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
/***************************************************************
 * picorv32_axi
 ***************************************************************/

module picorv32_axi #(
	parameter [ 0:0] ENABLE_COUNTERS = 1,
	parameter [ 0:0] ENABLE_COUNTERS64 = 1,
	parameter [ 0:0] ENABLE_REGS_16_31 = 1,
	parameter [ 0:0] ENABLE_REGS_DUALPORT = 1,
	parameter [ 0:0] TWO_STAGE_SHIFT = 1,
	parameter [ 0:0] BARREL_SHIFTER = 0,
	parameter [ 0:0] TWO_CYCLE_COMPARE = 0,
	parameter [ 0:0] TWO_CYCLE_ALU = 0,
	parameter [ 0:0] COMPRESSED_ISA = 0,
	parameter [ 0:0] CATCH_MISALIGN = 1,
	parameter [ 0:0] CATCH_ILLINSN = 1,
	parameter [ 0:0] ENABLE_PCPI = 0,
	parameter [ 0:0] ENABLE_MUL = 0,
	parameter [ 0:0] ENABLE_FAST_MUL = 0,
	parameter [ 0:0] ENABLE_DIV = 0,
	parameter [ 0:0] ENABLE_IRQ = 0,
	parameter [ 0:0] ENABLE_IRQ_QREGS = 1,
	parameter [ 0:0] ENABLE_IRQ_TIMER = 1,
	parameter [ 0:0] ENABLE_TRACE = 0,
	parameter [ 0:0] REGS_INIT_ZERO = 0,
	parameter [31:0] MASKED_IRQ = 32'h 0000_0000,
	parameter [31:0] LATCHED_IRQ = 32'h ffff_ffff,
	parameter [31:0] PROGADDR_RESET = 32'h 0000_0000,
	parameter [31:0] STACKADDR = 32'h ffff_ffff
) (
	input wire logic clk,
	input wire logic resetn,
	output logic trap,

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

	// Pico Co-Processor Interface (PCPI)
	output logic        pcpi_valid,
	output logic [31:0] pcpi_insn,
	output logic [31:0] pcpi_rs1,
	output logic [31:0] pcpi_rs2,
	input  wire logic   pcpi_wr,
	input  wire logic [31:0] pcpi_rd,
	input  wire logic   pcpi_wait,
	input  wire logic   pcpi_ready,

	// IRQ interface
	input  wire logic [31:0] irq,
	input  wire logic [31:0] irq_entry_addr_i,
	output logic [31:0] eoi,

`ifdef RISCV_FORMAL
	output logic        rvfi_valid,
	output logic [63:0] rvfi_order,
	output logic [31:0] rvfi_insn,
	output logic        rvfi_trap,
	output logic        rvfi_halt,
	output logic        rvfi_intr,
	output logic [ 4:0] rvfi_rs1_addr,
	output logic [ 4:0] rvfi_rs2_addr,
	output logic [31:0] rvfi_rs1_rdata,
	output logic [31:0] rvfi_rs2_rdata,
	output logic [ 4:0] rvfi_rd_addr,
	output logic [31:0] rvfi_rd_wdata,
	output logic [31:0] rvfi_pc_rdata,
	output logic [31:0] rvfi_pc_wdata,
	output logic [31:0] rvfi_mem_addr,
	output logic [ 3:0] rvfi_mem_rmask,
	output logic [ 3:0] rvfi_mem_wmask,
	output logic [31:0] rvfi_mem_rdata,
	output logic [31:0] rvfi_mem_wdata,
`endif

	// Trace Interface
	output logic        trace_valid,
	output logic [35:0] trace_data
);
	logic        mem_valid;
	logic [31:0] mem_addr;
	logic [31:0] mem_wdata;
	logic [ 3:0] mem_wstrb;
	logic [ 3:0] mem_rstrb;
	logic        mem_instr;
	logic        mem_ready;
	logic [31:0] mem_rdata;

	picorv32_axi_adapter u_axi_adapter (
		.clk            (clk            ),
		.resetn         (resetn         ),
		.mem_axi_awvalid(mem_axi_awvalid),
		.mem_axi_awready(mem_axi_awready),
		.mem_axi_awaddr (mem_axi_awaddr ),
		.mem_axi_awprot (mem_axi_awprot ),
		.mem_axi_wvalid (mem_axi_wvalid ),
		.mem_axi_wready (mem_axi_wready ),
		.mem_axi_wdata  (mem_axi_wdata  ),
		.mem_axi_wstrb  (mem_axi_wstrb  ),
		.mem_axi_bvalid (mem_axi_bvalid ),
		.mem_axi_bready (mem_axi_bready ),
		.mem_axi_arvalid(mem_axi_arvalid),
		.mem_axi_arready(mem_axi_arready),
		.mem_axi_araddr (mem_axi_araddr ),
		.mem_axi_arprot (mem_axi_arprot ),
		.mem_axi_rvalid (mem_axi_rvalid ),
		.mem_axi_rready (mem_axi_rready ),
		.mem_axi_rdata  (mem_axi_rdata  ),
		.mem_valid      (mem_valid      ),
		.mem_instr      (mem_instr      ),
		.mem_ready      (mem_ready      ),
		.mem_addr       (mem_addr       ),
		.mem_wdata      (mem_wdata      ),
		.mem_wstrb      (mem_wstrb      ),
		.mem_rstrb      (mem_rstrb      ),
		.mem_rdata      (mem_rdata      )
	);

	picorv32 #(
		.ENABLE_COUNTERS     (ENABLE_COUNTERS     ),
		.ENABLE_COUNTERS64   (ENABLE_COUNTERS64   ),
		.ENABLE_REGS_16_31   (ENABLE_REGS_16_31   ),
		.ENABLE_REGS_DUALPORT(ENABLE_REGS_DUALPORT),
		.TWO_STAGE_SHIFT     (TWO_STAGE_SHIFT     ),
		.BARREL_SHIFTER      (BARREL_SHIFTER      ),
		.TWO_CYCLE_COMPARE   (TWO_CYCLE_COMPARE   ),
		.TWO_CYCLE_ALU       (TWO_CYCLE_ALU       ),
		.COMPRESSED_ISA      (COMPRESSED_ISA      ),
		.CATCH_MISALIGN      (CATCH_MISALIGN      ),
		.CATCH_ILLINSN       (CATCH_ILLINSN       ),
		.ENABLE_PCPI         (ENABLE_PCPI         ),
		.ENABLE_MUL          (ENABLE_MUL          ),
		.ENABLE_FAST_MUL     (ENABLE_FAST_MUL     ),
		.ENABLE_DIV          (ENABLE_DIV          ),
		.ENABLE_IRQ          (ENABLE_IRQ          ),
		.ENABLE_IRQ_QREGS    (ENABLE_IRQ_QREGS    ),
		.ENABLE_IRQ_TIMER    (ENABLE_IRQ_TIMER    ),
		.ENABLE_TRACE        (ENABLE_TRACE        ),
		.REGS_INIT_ZERO      (REGS_INIT_ZERO      ),
		.MASKED_IRQ          (MASKED_IRQ          ),
		.LATCHED_IRQ         (LATCHED_IRQ         ),
		.PROGADDR_RESET      (PROGADDR_RESET      ),
		.STACKADDR           (STACKADDR           )
	) u_picorv32_core (
		.clk      (clk   ),
		.resetn   (resetn),
		.trap     (trap  ),

		.mem_valid(mem_valid),
		.mem_addr (mem_addr ),
		.mem_wdata(mem_wdata),
		.mem_wstrb(mem_wstrb),
		.mem_rstrb(mem_rstrb),
		.mem_instr(mem_instr),
		.mem_ready(mem_ready),
		.mem_rdata(mem_rdata),
		.mem_la_read (),
		.mem_la_write(),
		.mem_la_addr (),
		.mem_la_wdata(),
		.mem_la_wstrb(),
		.mem_la_rstrb(),

		.pcpi_valid(pcpi_valid),
		.pcpi_insn (pcpi_insn ),
		.pcpi_rs1  (pcpi_rs1  ),
		.pcpi_rs2  (pcpi_rs2  ),
		.pcpi_wr   (pcpi_wr   ),
		.pcpi_rd   (pcpi_rd   ),
		.pcpi_wait (pcpi_wait ),
		.pcpi_ready(pcpi_ready),

		.irq(irq),
		.irq_entry_addr_i(irq_entry_addr_i),
		.eoi(eoi),

`ifdef RISCV_FORMAL
		.rvfi_valid    (rvfi_valid    ),
		.rvfi_order    (rvfi_order    ),
		.rvfi_insn     (rvfi_insn     ),
		.rvfi_trap     (rvfi_trap     ),
		.rvfi_halt     (rvfi_halt     ),
		.rvfi_intr     (rvfi_intr     ),
		.rvfi_rs1_addr (rvfi_rs1_addr ),
		.rvfi_rs2_addr (rvfi_rs2_addr ),
		.rvfi_rs1_rdata(rvfi_rs1_rdata),
		.rvfi_rs2_rdata(rvfi_rs2_rdata),
		.rvfi_rd_addr  (rvfi_rd_addr  ),
		.rvfi_rd_wdata (rvfi_rd_wdata ),
		.rvfi_pc_rdata (rvfi_pc_rdata ),
		.rvfi_pc_wdata (rvfi_pc_wdata ),
		.rvfi_mem_addr (rvfi_mem_addr ),
		.rvfi_mem_rmask(rvfi_mem_rmask),
		.rvfi_mem_wmask(rvfi_mem_wmask),
		.rvfi_mem_rdata(rvfi_mem_rdata),
		.rvfi_mem_wdata(rvfi_mem_wdata),
`endif

		.trace_valid(trace_valid),
		.trace_data (trace_data)
	);
endmodule
