// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// DFD Wrapper
//
//------------------------------------------------------------------------------


module smc_dfd_wrap #(
  parameter logic [22:0] BASE_ADDR       = 0,
  parameter int unsigned NUM_INPUT_LANES = 64,
  // Width of the reference tick accounting counters. Bounds how far clk_gated_i may fall behind
  // clk_ref_i before ticks are lost; 2**REF_CNT_W ref cycles of slack.
  parameter int unsigned REF_CNT_W  = 8,
  localparam int unsigned LANE_WIDTH = 16
) (
  input  logic clk_smc_i,
  input  logic clk_ref_i,
  input  logic rst_primary_ni,

  input  smc_pkg::smc_dfd_apb_req_t  apb_smc_dfd_reg_req_i,
  output smc_pkg::smc_dfd_apb_resp_t apb_smc_dfd_reg_resp_o,

  input  smc_pkg::dfd_enable_t dfd_enables_i,

  output logic                                             external_action_debug_interrupt_o,
  output logic [cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0] external_action_custom_o,

  output smc_pkg::xtrigger_t xtrigger_ss_o,
  input  smc_pkg::xtrigger_t xtrigger_ss_i,
  input  logic               tdr_dbg_ctrl_clock_stop_en_i,
  output logic               tdr_dbg_ctrl_clocks_stopped_by_cla_o,

  input  tt_dbm_pkg::DbgMuxSelMmr_s             dbg_mux_sel_csr_i,
  input  logic [NUM_INPUT_LANES*LANE_WIDTH-1:0] debug_bus_i,
  output logic [7:0]                            debug_marker_o,

  // Trace sink RAMs live outside the DFD block (EXTERNAL_SINK_MEM = 1).
  output trace_mem_pkg::SinkMemPktIn_s [tn_pkg::TRC_RAM_INSTANCES-1:0]  trace_mem_req_o,
  input  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp_i,

  // DFT
  input  logic test_en_i,
  input  logic scan_rst_ni
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  logic external_action_toggle_gpio_o;

  smc_pkg::xtrigger_t smc_xtrigger_out_o;

  logic smc_action_halt_clock_o;

  logic time_tick;
  logic rst_ref_n;
  logic [REF_CNT_W-1:0] ref_cnt, ref_cnt_gray_q;
  logic [REF_CNT_W-1:0] ref_cnt_gray, ref_cnt_gray_sync;
  logic [REF_CNT_W-1:0] ref_cnt_sync, tick_cnt;

  logic [LANE_WIDTH*16-1:0] debug_bus_l2;
  logic [LANE_WIDTH*32-1:0] debug_bus_l3;

  logic clk_gated_i;

  //////////////////
  // Clock Gating //
  //////////////////

  generic_ccg #(
    .HYST_EN(0),
    .HYST_CYC(0)
  ) u_dfd_clk_gate (
    .out_clk(clk_gated_i),
    .clk(clk_smc_i),
    .rst_n(rst_primary_ni),
    .en(~dfd_enables_i.dfd_cg_en),
    .force_en(dfd_enables_i.dfd_force_clk_en),
    .te(test_en_i),
    .hyst(1'b0)
  );


  ////////////////
  // DBM Level 3 //
  ////////////////

  for (genvar i = 1; i <= 8; i++) begin : gen_dbm_l3

    localparam int unsigned MUX_ID = 6 + i;

    tt_debug_bus_mux #(
      .DEBUG_MUX_OUTPUT_WIDTH (LANE_WIDTH*4),
      .LANE_WIDTH          (LANE_WIDTH),
      .NUM_INPUT_LANES     (8),
      .DISABLE_OUTPUT_FLOP (1),
      .DEBUG_MUX_ID        (MUX_ID)
    ) u_debug_bus_mux_l3 (
      .clk                 (clk_gated_i),
      .reset_n             (rst_primary_ni),
      .debug_signals_in    (debug_bus_i[LANE_WIDTH*8*i -1:LANE_WIDTH*8*(i-1)]),
      .debug_bus_out       (debug_bus_l3[LANE_WIDTH*4*i -1:LANE_WIDTH*4*(i-1)]),
      .debug_clken         (/* UNUSED */),
      .DbgMuxSelMmr        (dbg_mux_sel_csr_i)
    );
  end

  /////////////////
  // DBM Level 2 //
  /////////////////

  for (genvar i = 1; i <= 4; i++) begin : gen_dbm_l2

    localparam int unsigned MUX_ID = 2 + i;

    tt_debug_bus_mux #(
      .DEBUG_MUX_OUTPUT_WIDTH (LANE_WIDTH*4),
      .LANE_WIDTH          (LANE_WIDTH),
      .NUM_INPUT_LANES     (8),
      .DEBUG_MUX_ID        (MUX_ID)
    ) u_debug_bus_mux_l2 (
      .clk                 (clk_gated_i),
      .reset_n             (rst_primary_ni),
      .debug_signals_in    (debug_bus_l3[LANE_WIDTH*8*i -1:LANE_WIDTH*8*(i-1)]),
      .debug_bus_out       (debug_bus_l2[LANE_WIDTH*4*i -1:LANE_WIDTH*4*(i-1)]),
      .debug_clken         (/* UNUSED */),
      .DbgMuxSelMmr        (dbg_mux_sel_csr_i)
    );
  end

  ////////////
  // DFD IP //
  ////////////

  dfd_top_cla_dst_apb #(
    .NUM_CLA_INST                           (1),
    .NUM_DST_INST                           (1),
    .DEBUG_SIGNAL_WIDTH                     (64),
    .LANE_WIDTH                             (LANE_WIDTH),
    .NUM_INPUT_LANES                        (16),
    .DEBUGMARKER_WIDTH                      (8),
    .TRC_SIZE_IN_KB                         (16),
    .TRC_RAM_INDEX                          (256),
    .MMR_ADDR_WIDTH                         (23),
    .MMR_DATA_WIDTH                         (32),
    .MMR_BASE_ADDRESS                       (BASE_ADDR),
    .EXTERNAL_SINK_MEM                      (1),
    // SMC has no reference-timestamp source: the CLA timestamp is driven by
    // the local time_tick below, which is scheme 0. The top defaults to 1.
    .TIMESTAMP_SYNC_SCHEME                  (0),
    .OCTS_TS_OUTPUT                         (0)
  ) u_dfd_top (
    .i_clk                                  (clk_gated_i),
    .i_rst_n                                (rst_primary_ni),
    .i_critical_signal_hold                 (1'b0),

    .psel                                   (apb_smc_dfd_reg_req_i.psel),
    .penable                                (apb_smc_dfd_reg_req_i.penable),
    .pwrite                                 (apb_smc_dfd_reg_req_i.pwrite),
    .paddr                                  (apb_smc_dfd_reg_req_i.paddr[22:0]),
    .pwdata                                 (apb_smc_dfd_reg_req_i.pwdata),
    .pstrb                                  (apb_smc_dfd_reg_req_i.pstrb),
    .pready                                 (apb_smc_dfd_reg_resp_o.pready),
    .prdata                                 (apb_smc_dfd_reg_resp_o.prdata),
    .pslverr                                (apb_smc_dfd_reg_resp_o.pslverr),

    // JTAG-side MMR access (was JT_TR_SlvReq / TR_JT_SlvResp) - unused
    .i_jtag_mmr_req_vld                     ('0),
    .i_jtag_mmr_req_we                      ('0),
    .i_jtag_mmr_req_addr                    ('0),
    .i_jtag_mmr_req_data                    ('0),
    .o_jtag_mmr_rsp_vld                     (),
    .o_jtag_mmr_rsp_data                    (),

    .o_cla_xtrigger                         (smc_xtrigger_out_o),
    .i_cla_xtrigger                         (xtrigger_ss_i),
    .o_cla_external_action_halt_clock_out   (smc_action_halt_clock_o),
    .o_cla_external_action_halt_clock_local_out (),
    .o_cla_external_action_debug_interrupt_out  (external_action_debug_interrupt_o),
    .o_cla_external_action_toggle_gpio_out  (external_action_toggle_gpio_o),
    .o_cla_external_action_custom           (external_action_custom_o),

    .i_debug_bus_signals                    (debug_bus_l2),
    .o_debug_mux_sel                        (),
    .o_cla_debug_marker                     (debug_marker_o),

    .i_cla_time_tick                        (time_tick),
    .i_timestamp                            ('0),
    .i_ref_timestamp                        ('0),
    .i_octs_timestamp                       ('0),

    // DST instruction-trigger control (from N-Trace); no N-Trace in this build
    .i_sdtrig_control                       (te_pkg::TRIG_TRACE_NONE),
    .i_vid_map                              ('0),

    // Trace sink RAMs are external; tsel travels with them
    .o_sink_mem_req                         (trace_mem_req_o),
    .i_sink_mem_rsp                         (trace_mem_resp_i),
    .i_mem_tsel_settings                    ('0),

    // Power / fuse controls: 0 = enabled. clk_dis_ctrl = ~rst_primary_ni leaves the functional
    // clock enable under the block's own MMRs except when primary reset is applied, which in
    // that case will force clock gates to all ungate
    .i_cla_fuse_dis                         ('0),
    .i_cla_clk_dis                          ('0),
    .i_cla_clk_dis_ctrl                     (~rst_primary_ni),
    .i_cla_func_clamp                       ('0),
    .i_dst_fuse_dis                         ('0),
    .i_dst_clk_dis                          ('0),
    .i_dst_clk_dis_ctrl                     (~rst_primary_ni),
    .i_dst_func_clamp                       ('0),
    .i_dst_sink_fuse_dis                    ('0),
    .i_dst_sink_clk_dis                     ('0),
    .i_dst_sink_clk_dis_ctrl                (~rst_primary_ni),
    .i_dst_sink_func_clamp                  ('0),
    .i_funnel_fuse_dis                      ('0),
    .i_funnel_clk_dis                       ('0),
    .i_funnel_clk_dis_ctrl                  (~rst_primary_ni),
    .i_funnel_func_clamp                    ('0),

    // DFT
    .i_test_icg_en                          (test_en_i),
    .i_test_reset_en                        (test_en_i),
    .i_test_reset_n                         (scan_rst_ni),

    // Trace-to-memory AXI master (was TR_EXT_SlvReq / EXT_TR_SlvResp) - unused
    .m_trc_axi_awready                      ('0),
    .m_trc_axi_wready                       ('0),
    .m_trc_axi_bid                          ('0),
    .m_trc_axi_bresp                        ('0),
    .m_trc_axi_buser                        ('0),
    .m_trc_axi_bvalid                       ('0),
    .m_trc_axi_arready                      ('0),
    .m_trc_axi_rid                          ('0),
    .m_trc_axi_rdata                        ('0),
    .m_trc_axi_rresp                        ('0),
    .m_trc_axi_rlast                        ('0),
    .m_trc_axi_ruser                        ('0),
    .m_trc_axi_rvalid                       ('0),
    .m_trc_axi_awid                         (),
    .m_trc_axi_awaddr                       (),
    .m_trc_axi_awlen                        (),
    .m_trc_axi_awsize                       (),
    .m_trc_axi_awburst                      (),
    .m_trc_axi_awlock                       (),
    .m_trc_axi_awcache                      (),
    .m_trc_axi_awprot                       (),
    .m_trc_axi_awqos                        (),
    .m_trc_axi_awregion                     (),
    .m_trc_axi_awatop                       (),
    .m_trc_axi_awuser                       (),
    .m_trc_axi_awvalid                      (),
    .m_trc_axi_wdata                        (),
    .m_trc_axi_wstrb                        (),
    .m_trc_axi_wlast                        (),
    .m_trc_axi_wuser                        (),
    .m_trc_axi_wvalid                       (),
    .m_trc_axi_bready                       (),
    .m_trc_axi_arid                         (),
    .m_trc_axi_araddr                       (),
    .m_trc_axi_arlen                        (),
    .m_trc_axi_arsize                       (),
    .m_trc_axi_arburst                      (),
    .m_trc_axi_arlock                       (),
    .m_trc_axi_arcache                      (),
    .m_trc_axi_arprot                       (),
    .m_trc_axi_arqos                        (),
    .m_trc_axi_arregion                     (),
    .m_trc_axi_aruser                       (),
    .m_trc_axi_arvalid                      (),
    .m_trc_axi_rready                       ()
  );

  ////////////////////////////////////////
  // Global Debug Halt Clock Handling  //
  ////////////////////////////////////////

  logic halt_clock_global_or_o;

  assign halt_clock_global_or_o               = smc_action_halt_clock_o & dfd_enables_i.xtrig_clk_halt_mask[0];
  assign tdr_dbg_ctrl_clocks_stopped_by_cla_o = tdr_dbg_ctrl_clock_stop_en_i && halt_clock_global_or_o;

  //////////////////////////
  // Time Tick Generation //
  //////////////////////////

  // count in refclk and then send value to clk_gated_i domain
  // - do this to be able to detect every rising edge of refclk
  prim_sync_reset #(
    .WIDTH(3)
  ) u_ref_rst_sync (
    .clk_i       (clk_ref_i),
    .rst_ni      (rst_primary_ni),
    .test_mode_i (test_en_i),
    .scan_rst_ni (scan_rst_ni),
    .sync_rst_no (rst_ref_n)
  );

  always_ff @(posedge clk_ref_i) begin
    if (!rst_ref_n) begin
      ref_cnt        <= '0;
      ref_cnt_gray_q <= '0;
    end else begin
      ref_cnt        <= REF_CNT_W'(ref_cnt + 1'b1);
      ref_cnt_gray_q <= ref_cnt_gray;
    end
  end

  prim_bin2gray #(
    .N(REF_CNT_W)
  ) u_ref_cnt_bin2gray (
    .a_i(ref_cnt),
    .z_o(ref_cnt_gray)
  );

  prim_sync3r #(
    .WIDTH(REF_CNT_W)
  ) u_ref_cnt_sync (
    .clk_i  (clk_gated_i),
    .rst_ni (rst_primary_ni),
    .d_i    (ref_cnt_gray_q),
    .q_o    (ref_cnt_gray_sync)
  );

  prim_gray2bin #(
    .N(REF_CNT_W)
  ) u_ref_cnt_gray2bin (
    .a_i(ref_cnt_gray_sync),
    .z_o(ref_cnt_sync)
  );

  assign time_tick = (tick_cnt != ref_cnt_sync);

  always_ff @(posedge clk_gated_i or negedge rst_primary_ni) begin
    if (!rst_primary_ni) begin
      tick_cnt <= '0;
    end else if (time_tick) begin
      tick_cnt <= REF_CNT_W'(tick_cnt + 1'b1);
    end
  end

  ////////////////////
  // Cross Triggers //
  ////////////////////

  assign xtrigger_ss_o = smc_xtrigger_out_o & {smc_pkg::XTRIGGER_WIDTH{dfd_enables_i.xtrig_clk_halt_mask[0]}};

endmodule
