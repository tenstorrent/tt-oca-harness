// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AXI4-Lite slave to TL-UL host protocol converter.

module axi_lite_to_tlul
	import tlul_pkg::*;

	`include "prim_assert.sv"
	import axi_pkg::*;
	import prim_mubi_pkg::mubi4_t;
	#(
		parameter int unsigned AXI_ADDR_WIDTH    = 32,
		parameter int unsigned AXI_DATA_WIDTH    = 32,  // Must be 32 to match TL-UL
		parameter int unsigned AXI_ID_WIDTH      = 8,
		parameter int unsigned AXI_USER_WIDTH    = 1,
		parameter type         axi_lite_req_t    = logic,
		parameter type         axi_lite_rsp_t    = logic,
		parameter bit          EnableCmdIntgGen  = 1'b1,  // Generate command integrity
		parameter bit          EnableDataIntgGen = 1'b1   // Generate data integrity
	) (
		input  logic      clk_i,
		input  logic      rst_ni,

		// AXI4 Lite Slave Interface
		input  axi_lite_req_t  axi_lite_req_i,
		output axi_lite_rsp_t  axi_lite_rsp_o,

		// TL-UL Host Interface
		output tl_h2d_t   tl_o,
		input  tl_d2h_t   tl_i,

		// Error output (sticky). Held until err_clr_i; a new error in the same cycle
		// as the clear still latches, so a fault racing the clear is never lost.
		// Tie err_clr_i low to keep the pre-clear behaviour of holding until reset.
		output logic      err_o,
		input  logic      err_clr_i
	);

	// --------------------------------------------------
	// Local Parameters
	// --------------------------------------------------
	// AXI Responses (Fallback if not defined in axi_pkg)
	localparam logic [1:0] AXI_RESP_OKAY   = 2'b00;
	localparam logic [1:0] AXI_RESP_SLVERR = 2'b10;

	// FSM States
	typedef enum logic [2:0] {
		IDLE,
		TL_GET_REQ,   // Send Read on Ch A
		TL_GET_ACK,   // Wait for Read Ack on Ch D
		AXI_R_RESP,   // Send Read Data on AXI R
		TL_PUT_REQ,   // Send Write on Ch A
		TL_PUT_ACK,   // Wait for Write Ack on Ch D
		AXI_B_RESP    // Send Write Resp on AXI B
	} state_e;

	state_e state_q, state_d;

	// Latched transaction details
	logic [AXI_ADDR_WIDTH-1:0]   req_addr_q, req_addr_d;
	logic [AXI_DATA_WIDTH-1:0]   req_data_q, req_data_d;
	logic [AXI_DATA_WIDTH/8-1:0] req_strb_q, req_strb_d;

	// Response tracking
	logic [AXI_DATA_WIDTH-1:0]   resp_data_q, resp_data_d;
	logic                        req_error_q, req_error_d;

	// Sticky error tracking
	logic                        sticky_err_q, sticky_err_d;

	// Integrity signals
	logic [H2DCmdIntgWidth-1:0]  cmd_intg;
	logic [DataIntgWidth-1:0]    data_intg;

	// --------------------------------------------------
	// FSM Sequential Logic
	// --------------------------------------------------
	always_ff @(posedge clk_i or negedge rst_ni) begin
		if (!rst_ni) begin
			state_q      <= IDLE;
			req_addr_q   <= '0;
			req_data_q   <= '0;
			req_strb_q   <= '0;
			resp_data_q  <= '0;
			req_error_q  <= 1'b0;
			sticky_err_q <= 1'b0;
		end else begin
			state_q      <= state_d;
			req_addr_q   <= req_addr_d;
			req_data_q   <= req_data_d;
			req_strb_q   <= req_strb_d;
			resp_data_q  <= resp_data_d;
			req_error_q  <= req_error_d;
			sticky_err_q <= sticky_err_d;
		end
	end

	// Assign sticky error output
	assign err_o = sticky_err_q;

	// --------------------------------------------------
	// FSM Combinational Logic
	// --------------------------------------------------
	always_comb begin
		// Default FSM bindings
		state_d      = state_q;
		req_addr_d   = req_addr_q;
		req_data_d   = req_data_q;
		req_strb_d   = req_strb_q;
		resp_data_d  = resp_data_q;
		req_error_d  = req_error_q;
		// Clear applies first; the set condition below overrides it in the same cycle.
		sticky_err_d = sticky_err_q & ~err_clr_i;

		// Default AXI Outputs (Zero out the structs first)
		axi_lite_rsp_o = '0;
		axi_lite_rsp_o.b.resp = AXI_RESP_OKAY;
		axi_lite_rsp_o.r.resp = AXI_RESP_OKAY;

		// Default TL-UL Outputs (Zero out the struct first)
		tl_o = '0;
		tl_o.a_size  = 2; // 2^2 = 4 bytes (32-bit transfer)
		tl_o.a_user.instr_type = prim_mubi_pkg::MuBi4False; // Must be MuBi4False (0x9), not 0
		tl_o.a_user.cmd_intg = cmd_intg;
		tl_o.a_user.data_intg = data_intg;

		// Sticky Error Capture
		if (tl_i.d_valid && tl_i.d_error) begin
			sticky_err_d = 1'b1;
		end

		case (state_q)
			IDLE: begin
				// Priority 1: Handle Reads
				if (axi_lite_req_i.ar_valid) begin
					axi_lite_rsp_o.ar_ready = 1'b1;
					req_addr_d = axi_lite_req_i.ar.addr;
					state_d = TL_GET_REQ;
				end
				// Priority 2: Handle Writes (Only if both AW and W are valid)
				else if (axi_lite_req_i.aw_valid && axi_lite_req_i.w_valid) begin
					axi_lite_rsp_o.aw_ready = 1'b1;
					axi_lite_rsp_o.w_ready  = 1'b1;
					req_addr_d = axi_lite_req_i.aw.addr;
					req_data_d = axi_lite_req_i.w.data;
					req_strb_d = axi_lite_req_i.w.strb;
					state_d = TL_PUT_REQ;
				end
			end

			// ==========================================
			// READ FLOW
			// ==========================================
			TL_GET_REQ: begin
				tl_o.a_valid   = 1'b1;
				tl_o.a_opcode  = tlul_pkg::Get;
				tl_o.a_address = req_addr_q;
				tl_o.a_mask    = {(AXI_DATA_WIDTH/8){1'b1}};

				if (tl_i.a_ready) begin
					state_d = TL_GET_ACK;
				end
			end

			TL_GET_ACK: begin
				tl_o.d_ready = 1'b1;

				if (tl_i.d_valid) begin
					resp_data_d = tl_i.d_data;
					req_error_d = tl_i.d_error;
					state_d     = AXI_R_RESP;
				end
			end

			AXI_R_RESP: begin
				axi_lite_rsp_o.r_valid = 1'b1;
				axi_lite_rsp_o.r.data  = resp_data_q;
				axi_lite_rsp_o.r.resp  = req_error_q ? AXI_RESP_SLVERR : AXI_RESP_OKAY;

				if (axi_lite_req_i.r_ready) begin
					state_d = IDLE;
				end
			end

			// ==========================================
			// WRITE FLOW
			// ==========================================
			TL_PUT_REQ: begin
				tl_o.a_valid   = 1'b1;
				tl_o.a_address = req_addr_q;
				tl_o.a_data    = req_data_q;
				tl_o.a_mask    = req_strb_q;

				// Determine opcode based on write strobe
				if (req_strb_q == {(AXI_DATA_WIDTH/8){1'b1}}) begin
					tl_o.a_opcode = tlul_pkg::PutFullData;
				end else begin
					tl_o.a_opcode = tlul_pkg::PutPartialData;
				end

				if (tl_i.a_ready) begin
					state_d = TL_PUT_ACK;
				end
			end

			TL_PUT_ACK: begin
				tl_o.d_ready = 1'b1;

				if (tl_i.d_valid) begin
					req_error_d = tl_i.d_error;
					state_d     = AXI_B_RESP;
				end
			end

			AXI_B_RESP: begin
				axi_lite_rsp_o.b_valid = 1'b1;
				axi_lite_rsp_o.b.resp  = req_error_q ? AXI_RESP_SLVERR : AXI_RESP_OKAY;

				if (axi_lite_req_i.b_ready) begin
					state_d = IDLE;
				end
			end

			default: state_d = IDLE;
		endcase

	end

	// --------------------------------------------------
	// TL-UL Integrity Generation (Combinational)
	// --------------------------------------------------
	always_comb begin
		// Generate command integrity (SECDED ECC for address, opcode, mask, instr_type)
		if (EnableCmdIntgGen) begin
			automatic tl_h2d_cmd_intg_t cmd;
			automatic logic [H2DCmdMaxWidth-1:0] unused_cmd_payload;

			cmd.addr = tl_o.a_address;
			cmd.opcode = tl_o.a_opcode;
			cmd.mask = tl_o.a_mask;
			cmd.instr_type = tl_o.a_user.instr_type;

			{cmd_intg, unused_cmd_payload} =
				prim_secded_pkg::prim_secded_inv_64_57_enc(H2DCmdMaxWidth'(cmd));
		end else begin
			cmd_intg = {H2DCmdIntgWidth{1'b1}};
		end

		// Generate data integrity (SECDED ECC for data)
		if (EnableDataIntgGen) begin
			automatic logic [DataMaxWidth-1:0] unused_data;

			{data_intg, unused_data} =
				prim_secded_pkg::prim_secded_inv_39_32_enc(DataMaxWidth'(tl_o.a_data));
		end else begin
			data_intg = {DataIntgWidth{1'b1}};
		end
	end

	// --------------------------------------------------
	// Assertions
	// --------------------------------------------------
	`OCAH_OT_ASSERT_INIT(AxiDataWidthMatches, AXI_DATA_WIDTH == 32)

endmodule : axi_lite_to_tlul