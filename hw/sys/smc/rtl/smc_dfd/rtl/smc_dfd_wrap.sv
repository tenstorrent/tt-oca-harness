// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// DFD Wrapper
//
//------------------------------------------------------------------------------


module smc_dfd_wrap
#(
	parameter  BASE_ADDR       = 0,
	parameter  NUM_INPUT_LANES = 64,
	localparam LANE_WIDTH      = 16
) (
	input  logic                                                                     clk_smc_i,
	input  logic                                                                     clk_ref_i,
	input  logic                                                                     rst_primary_ni,

	input  smc_pkg::smc_dfd_apb_req_t                                                apb_smc_dfd_reg_req_i,
	output smc_pkg::smc_dfd_apb_resp_t                                               apb_smc_dfd_reg_resp_o,

	input  smc_pkg::dfd_enable_t                                                     dfd_enables_i,

	output logic                                                                     external_action_debug_interrupt_o,
	output logic [dfd_cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0]                     external_action_custom_o,

	output smc_pkg::xtrigger_t                                                       xtrigger_ss_o,
	input  smc_pkg::xtrigger_t                                                       xtrigger_ss_i,
	input  logic                                                                     tdr_dbg_ctrl_clock_stop_en_i,
	output logic                                                                     tdr_dbg_ctrl_clocks_stopped_by_cla_o,

	input  dfd_tt_dbm_pkg::DbgMuxSelCsr_s                                            dbg_mux_sel_csr_i,
	input  logic [NUM_INPUT_LANES*LANE_WIDTH-1:0]                                    debug_bus_i,
	output logic [7:0]                                                               debug_marker_o,

	output dfd_trace_mem_pkg::SinkMemPktIn_s [dfd_tn_pkg::TRC_RAM_INSTANCES-1:0]     trace_mem_req_o,
	input  dfd_trace_mem_pkg::SinkMemPktOut_s [dfd_tn_pkg::TRC_RAM_INSTANCES-1:0]    trace_mem_resp_i,

	// DFT
	input  logic                                                                     test_en_i
);

	/////////////////////////
	// Signal Declarations //
	/////////////////////////

	logic                                                             external_action_trace_start_o;
	logic                                                             external_action_trace_stop_o;
	logic                                                             external_action_trace_pulse_o;
	logic                                                             external_action_toggle_gpio_o;

	smc_pkg::xtrigger_t                                               smc_xtrigger_out_o;

	logic                                                    	      smc_action_halt_clock_o;

	logic                                                             ref_sync, ref_sync_ff;
	logic                                                             time_tick;

	logic [LANE_WIDTH*16-1:0]                                         debug_bus_l2;
	logic [LANE_WIDTH*32-1:0]                                         debug_bus_l3;

	logic                                                             clk_gated_i;

	//////////////////
	// Clock Gating //
	//////////////////

	dfd_rv_ccg #(.HYST(0), .HYST_CYC(0)) dfd_clk_gate (.o_clk(clk_gated_i), .i_clk(clk_smc_i), .i_reset_n(rst_primary_ni),
		.i_en(~dfd_enables_i.dfd_cg_en), .i_force(dfd_enables_i.dfd_force_clk_en), .i_te(test_en_i), .i_hyst(1'b0));


	////////////////
	// DBM Level 3 //
	////////////////

	for (genvar i = 1; i <= 8; i++) begin : DBM_L3

		localparam MUX_ID = 6 + i;

		dfd_debug_bus_mux #(
			.LANE_WIDTH			 (LANE_WIDTH),
			.NUM_INPUT_LANES	 (8),
			.DISABLE_OUTPUT_FLOP (1),
			.DEBUG_MUX_ID		 (MUX_ID)
		) u_debug_bus_mux_l3 (
			.clk				 (clk_gated_i),
			.reset_n			 (rst_primary_ni),
			.debug_signals_in	 (debug_bus_i[LANE_WIDTH*8*i -1:LANE_WIDTH*8*(i-1)]),
			.debug_bus_out		 (debug_bus_l3[LANE_WIDTH*4*i -1:LANE_WIDTH*4*(i-1)]),
			.debug_clken		 (/* UNUSED */),
			.DbgMuxSelCsr		 (dbg_mux_sel_csr_i)
		);
	end

	/////////////////
	// DBM Level 2 //
	/////////////////

	for (genvar i = 1; i<=4; i++) begin: DBM_L2

		localparam MUX_ID = 2 + i;

		dfd_debug_bus_mux #(
			.LANE_WIDTH			 (LANE_WIDTH),
			.NUM_INPUT_LANES	 (8),
			.DEBUG_MUX_ID        (MUX_ID)
		) u_debug_bus_mux_l2 (
			.clk                 (clk_gated_i),
			.reset_n             (rst_primary_ni),
			.debug_signals_in    (debug_bus_l3[LANE_WIDTH*8*i -1:LANE_WIDTH*8*(i-1)]),
			.debug_bus_out       (debug_bus_l2[LANE_WIDTH*4*i -1:LANE_WIDTH*4*(i-1)]),
			.debug_clken         (/* UNUSED */),
			.DbgMuxSelCsr        (dbg_mux_sel_csr_i)
		);
	end

	////////////
	// DFD IP //
	////////////

	dfd_top #(
		.BASE_ADDR                              (BASE_ADDR),
		.TRC_SIZE_IN_KB                         (16),
		.NTRACE_SUPPORT                         (0)
	) u_dfd_top (
		.clk									(clk_gated_i),
		.cold_reset_n							(rst_primary_ni),
		.reset_n								(rst_primary_ni),
		.reset_n_warm_ovrride					(rst_primary_ni),

		.psel									(apb_smc_dfd_reg_req_i.psel),
		.penable								(apb_smc_dfd_reg_req_i.penable),
		.pwrite									(apb_smc_dfd_reg_req_i.pwrite),
		.paddr									(apb_smc_dfd_reg_req_i.paddr[22:0]),
		.pwdata									(apb_smc_dfd_reg_req_i.pwdata),
		.pstrb									(apb_smc_dfd_reg_req_i.pstrb),
		.pready									(apb_smc_dfd_reg_resp_o.pready),
		.prdata									(apb_smc_dfd_reg_resp_o.prdata),
		.pslverr								(apb_smc_dfd_reg_resp_o.pslverr),

		.xtrigger_out							(smc_xtrigger_out_o),
		.external_action_halt_clock_out			(smc_action_halt_clock_o),
		.external_action_halt_clock_local_out	(),
		.external_action_debug_interrupt_out	(external_action_debug_interrupt_o),
		.external_action_toggle_gpio_out		(external_action_toggle_gpio_o),
		.external_action_custom					(external_action_custom_o),
		.external_action_trace_start			(external_action_trace_start_o),
		.external_action_trace_stop				(external_action_trace_stop_o),
		.external_action_trace_pulse			(external_action_trace_pulse_o),
		.external_cla_action_trace_start		('0),
		.external_cla_action_trace_stop			('0),
		.external_cla_action_trace_pulse		('0),
		.xtrigger_in							(xtrigger_ss_i),
		.DfdCsrs_external						('0),
		.DfdCsrsWr_external						(),

		.hw0									(debug_bus_l2[15:0]),
		.hw1									(debug_bus_l2[31:16]),
		.hw2									(debug_bus_l2[47:32]),
		.hw3									(debug_bus_l2[63:48]),
		.hw4									(debug_bus_l2[79:64]),
		.hw5									(debug_bus_l2[95:80]),
		.hw6									(debug_bus_l2[111:96]),
		.hw7									(debug_bus_l2[127:112]),
		.hw8									(debug_bus_l2[143:128]),
		.hw9									(debug_bus_l2[159:144]),
		.hw10									(debug_bus_l2[175:160]),
		.hw11									(debug_bus_l2[191:176]),
		.hw12									(debug_bus_l2[207:192]),
		.hw13									(debug_bus_l2[223:208]),
		.hw14									(debug_bus_l2[239:224]),
		.hw15									(debug_bus_l2[255:240]),

		.Time_Tick								(time_tick),
		.time_match_event						('0),
		.CoreTime								('0),
		.cla_debug_marker						(debug_marker_o),
		.timesync_cla_timestamp					(),

		.IRetire								('0),
		.IType									('0),
		.IAddr									('0),
		.ILastSize								('0),
		.Tstamp									('0),
		.Priv									(dfd_te_pkg::PRIVMODE_USER),
		.Context								('0),
		.Tval									('0),
		.Error									('0),
		.Active									(),
		.StallModeEn							(),
		.StartStop								(),
		.Backpressure							(),
		.TrigControl							(dfd_te_pkg::TRIG_TRACE_ON),

		.TR_EXT_SlvReq							(),
		.EXT_TR_SlvResp							('0),
		.JT_TR_SlvReq							('0),
		.TR_JT_SlvResp							(),

		.funnel_mem_SinkMemPktIn_ANY			(trace_mem_req_o),
		.mem_funnel_SinkMemPktOut_ANY			(trace_mem_resp_i)
	);

	////////////////////////////////////////
	// Global Debug Halt Clock Handling  //
	////////////////////////////////////////

	logic                                             halt_clock_global_or_o;

	assign halt_clock_global_or_o               = smc_action_halt_clock_o & dfd_enables_i.xtrig_clk_halt_mask[0];
	assign tdr_dbg_ctrl_clocks_stopped_by_cla_o = tdr_dbg_ctrl_clock_stop_en_i && halt_clock_global_or_o;

	//////////////////////////
	// Time Tick Generation //
	//////////////////////////

	prim_sync3r #(.WIDTH(1))   ref_clk_sync   ( .i_clk(clk_gated_i), .i_reset_n(rst_primary_ni),              .i_d(clk_ref_i),         .o_q(ref_sync));
	dfd_rv_dff #(.WIDTH(1))    ref_edge_det   ( .i_clk(clk_gated_i), .i_reset_n(rst_primary_ni), .i_en(1'b1), .i_d(ref_sync),          .o_q(ref_sync_ff));
	assign time_tick = ref_sync && !ref_sync_ff;

	////////////////////
	// Cross Triggers //
	////////////////////

	assign xtrigger_ss_o = smc_xtrigger_out_o & {smc_pkg::XTRIGGER_WIDTH{dfd_enables_i.xtrig_clk_halt_mask[0]}};

endmodule
