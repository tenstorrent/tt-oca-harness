// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// TL-UL device to AXI4-Lite master protocol converter.

module tlul_to_axi_lite
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
		parameter bit          ENABLE_RSP_INTG_GEN   = 1'b1,  // Generate response integrity
		parameter bit          ENABLE_DATA_INTG_GEN  = 1'b1,  // Generate data integrity for responses
		parameter bit          CMD_INTG_CHECK        = 1'b0   // Check incoming command integrity
	) (
		input  logic      clk_i,
		input  logic      rst_ni,

		// TL-UL Device Interface (Incoming requests)
		input  tl_h2d_t   tl_i,
		output tl_d2h_t   tl_o,

		// AXI4 Lite Master Interface (Outgoing requests)
		output axi_lite_req_t  axi_lite_req_o,
		input  axi_lite_rsp_t  axi_lite_rsp_i,

		// Error output (sticky). Held until err_clr_i; a new error in the same cycle
		// as the clear still latches, so a fault racing the clear is never lost.
		output logic      err_o,
		input  logic      err_clr_i
	);

	// --------------------------------------------------
	// Local Parameters
	// --------------------------------------------------
	localparam logic [1:0] AXI_RESP_OKAY = 2'b00;
	// Size req_size to the actual TL-UL a_size port width, not a global pkg constant, so it tracks the connected bus
	localparam int unsigned ReqSizeW = $bits(tl_i.a_size);

	// FSM States
	typedef enum logic [2:0] {
		IDLE,
		AXI_AR_REQ,   // Drive Read Addr on AXI AR
		AXI_R_ACK,    // Wait for Read Data on AXI R
		AXI_AW_W_REQ, // Drive Write Addr/Data on AXI AW & W
		AXI_B_ACK,    // Wait for Write Resp on AXI B
		TL_D_RESP     // Send Response on TL-UL Ch D
	} state_e;

	state_e state_q, state_d;

	// Latched TL-UL Channel A transaction details
	logic [AXI_ADDR_WIDTH-1:0]   req_addr_q, req_addr_d;
	logic [AXI_DATA_WIDTH-1:0]   req_data_q, req_data_d;
	logic [AXI_DATA_WIDTH/8-1:0] req_mask_q, req_mask_d;
	tl_a_op_e                    req_opcode_q, req_opcode_d;
	logic [7:0]                  req_source_q, req_source_d;
	logic [ReqSizeW-1:0]         req_size_q, req_size_d;

	// AXI Write Tracking (AW and W can be ack'd independently)
	logic aw_done_q, aw_done_d;
	logic w_done_q,  w_done_d;

	// Response tracking
	logic [AXI_DATA_WIDTH-1:0]     resp_data_q, resp_data_d;
	logic                          resp_error_q, resp_error_d;

	// Sticky error tracking
	logic                          sticky_err_q, sticky_err_d;

	// Integrity signals
	logic [D2H_RSP_INTG_WIDTH-1:0] rsp_intg;
	logic [DATA_INTG_WIDTH-1:0]    data_intg;

	// --------------------------------------------------
	// TL-UL Incoming Command Integrity Checking
	// --------------------------------------------------
	logic intg_err;
	if (CMD_INTG_CHECK) begin : gen_cmd_intg_check
		tlul_cmd_intg_chk u_cmd_intg_chk (
			.tl_i(tl_i),
			.err_o(intg_err)
		);
	end else begin : gen_no_intg_check
		assign intg_err = 1'b0;
	end

	// --------------------------------------------------
	// FSM Sequential Logic
	// --------------------------------------------------
	always_ff @(posedge clk_i or negedge rst_ni) begin
		if (!rst_ni) begin
			state_q      <= IDLE;
			req_addr_q   <= '0;
			req_data_q   <= '0;
			req_mask_q   <= '0;
			req_opcode_q <= tlul_pkg::GET;
			req_source_q <= '0;
			req_size_q   <= '0;
			aw_done_q    <= 1'b0;
			w_done_q     <= 1'b0;
			resp_data_q  <= '0;
			resp_error_q <= 1'b0;
			sticky_err_q <= 1'b0;
		end else begin
			state_q      <= state_d;
			req_addr_q   <= req_addr_d;
			req_data_q   <= req_data_d;
			req_mask_q   <= req_mask_d;
			req_opcode_q <= req_opcode_d;
			req_source_q <= req_source_d;
			req_size_q   <= req_size_d;
			aw_done_q    <= aw_done_d;
			w_done_q     <= w_done_d;
			resp_data_q  <= resp_data_d;
			resp_error_q <= resp_error_d;
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
		req_mask_d   = req_mask_q;
		req_opcode_d = req_opcode_q;
		req_source_d = req_source_q;
		req_size_d   = req_size_q;
		aw_done_d    = aw_done_q;
		w_done_d     = w_done_q;
		resp_data_d  = resp_data_q;
		resp_error_d = resp_error_q;
		// Clear applies first; the set conditions below override it in the same cycle.
		sticky_err_d = sticky_err_q & ~err_clr_i;

		// Default TL-UL Outputs (Zero out struct)
		tl_o = '0;
		tl_o.d_user.rsp_intg = rsp_intg;
		tl_o.d_user.data_intg = data_intg;

		// Default AXI Outputs (Zero out struct)
		axi_lite_req_o = '0;

		// Capture Sticky Error from AXI response
		if ((axi_lite_rsp_i.b_valid && axi_lite_rsp_i.b.resp != AXI_RESP_OKAY) ||
				(axi_lite_rsp_i.r_valid && axi_lite_rsp_i.r.resp != AXI_RESP_OKAY)) begin
			sticky_err_d = 1'b1;
		end

		// Capture Sticky Error from TL-UL integrity checks
		if (intg_err) begin
			sticky_err_d = 1'b1;
		end

		case (state_q)
			IDLE: begin
				tl_o.a_ready = 1'b1;

				if (tl_i.a_valid) begin
					req_addr_d   = tl_i.a_address;
					req_data_d   = tl_i.a_data;
					req_mask_d   = tl_i.a_mask;
					req_opcode_d = tl_i.a_opcode;
					req_source_d = tl_i.a_source;
					req_size_d   = tl_i.a_size;

					aw_done_d    = 1'b0;
					w_done_d     = 1'b0;

					if (tl_i.a_opcode == tlul_pkg::GET) begin
						state_d = AXI_AR_REQ;
					end else begin
						state_d = AXI_AW_W_REQ;
					end
				end
			end

			// ==========================================
			// READ FLOW
			// ==========================================
			AXI_AR_REQ: begin
				axi_lite_req_o.ar_valid = 1'b1;
				axi_lite_req_o.ar.addr  = req_addr_q;

				if (axi_lite_rsp_i.ar_ready) begin
					state_d = AXI_R_ACK;
				end
			end

			AXI_R_ACK: begin
				axi_lite_req_o.r_ready = 1'b1;

				if (axi_lite_rsp_i.r_valid) begin
					resp_data_d  = axi_lite_rsp_i.r.data;
					resp_error_d = (axi_lite_rsp_i.r.resp != AXI_RESP_OKAY);
					state_d      = TL_D_RESP;
				end
			end

			// ==========================================
			// WRITE FLOW (Requires tracking AW and W)
			// ==========================================
			AXI_AW_W_REQ: begin
				// Hold valid high until ready is seen for each respective channel
				axi_lite_req_o.aw_valid = ~aw_done_q;
				axi_lite_req_o.aw.addr  = req_addr_q;

				axi_lite_req_o.w_valid  = ~w_done_q;
				axi_lite_req_o.w.data   = req_data_q;
				axi_lite_req_o.w.strb   = req_mask_q;

				// Mark AW as done if handshake completes
				if (axi_lite_req_o.aw_valid && axi_lite_rsp_i.aw_ready) begin
					aw_done_d = 1'b1;
				end

				// Mark W as done if handshake completes
				if (axi_lite_req_o.w_valid && axi_lite_rsp_i.w_ready) begin
					w_done_d = 1'b1;
				end

				// Only proceed when BOTH are completed
				if (aw_done_d && w_done_d) begin
					state_d = AXI_B_ACK;
				end
			end

			AXI_B_ACK: begin
				axi_lite_req_o.b_ready = 1'b1;

				if (axi_lite_rsp_i.b_valid) begin
					resp_error_d = (axi_lite_rsp_i.b.resp != AXI_RESP_OKAY);
					state_d      = TL_D_RESP;
				end
			end

			// ==========================================
			// TL-UL RESPONSE OUT
			// ==========================================
			TL_D_RESP: begin
				tl_o.d_valid  = 1'b1;
				tl_o.d_source = req_source_q;
				tl_o.d_size   = req_size_q;
				tl_o.d_error  = resp_error_q;
				tl_o.d_data   = resp_data_q;

				if (req_opcode_q == tlul_pkg::GET) begin
					tl_o.d_opcode = tlul_pkg::ACCESS_ACK_DATA;
				end else begin
					tl_o.d_opcode = tlul_pkg::ACCESS_ACK;
				end

				if (tl_i.d_ready) begin
					state_d = IDLE;
				end
			end

			default: state_d = IDLE;
		endcase
	end

	// --------------------------------------------------
	// TL-UL Response Integrity Generation (Combinational)
	// --------------------------------------------------
	always_comb begin
		// Generate response integrity (SECDED ECC for opcode, size, error)
		if (ENABLE_RSP_INTG_GEN) begin
			automatic tl_d2h_rsp_intg_t rsp;
			automatic logic [D2H_RSP_MAX_WIDTH-1:0] unused_payload;

			rsp.opcode = tl_o.d_opcode;
			rsp.size = tl_o.d_size;
			rsp.error = tl_o.d_error;

			{rsp_intg, unused_payload} =
				prim_secded_pkg::prim_secded_inv_64_57_enc(D2H_RSP_MAX_WIDTH'(rsp));
		end else begin
			rsp_intg = {D2H_RSP_INTG_WIDTH{1'b1}};
		end

		// Generate data integrity (SECDED ECC for data)
		if (ENABLE_DATA_INTG_GEN) begin
			automatic logic [DATA_MAX_WIDTH-1:0] unused_data;

			{data_intg, unused_data} =
				prim_secded_pkg::prim_secded_inv_39_32_enc(DATA_MAX_WIDTH'(tl_o.d_data));
		end else begin
			data_intg = {DATA_INTG_WIDTH{1'b1}};
		end
	end

	// --------------------------------------------------
	// Assertions
	// --------------------------------------------------
	`OCAH_OT_ASSERT_INIT(AxiDataWidthMatches, AXI_DATA_WIDTH == 32)

endmodule : tlul_to_axi_lite