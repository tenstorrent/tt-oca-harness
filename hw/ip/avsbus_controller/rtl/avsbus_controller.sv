// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// APB2AVSBus V1.3.1 Controller

`begin_keywords "1800-2005"


module avsbus_controller #(
  parameter int unsigned COMMAND_FIFO_DEPTH = 8,
  parameter int unsigned READBACK_FIFO_DEPTH = 8
) (
  // Global interface
  input  logic            clk_reg_i,
  input  logic            clk_ref_i,
  input  logic            rst_ref_ni,     // async reset, deasserted synchronously to clk_ref_i
  input  logic            rst_reg_ni,     // async reset, deasserted synchronously to clk_reg_i
  input  logic            rst_clk_div_ni, // clock divider needs to be taken out of reset before rest of AVS logic

  // AVSBus Interface
  input  logic            avs_sdata_i,
  output logic            avs_mdata_o,
  output logic            avs_clock_o,
  output logic            avs_gpio_enable_o,

  input  avsbus_controller_pkg::avsbus_axil_req_t              axil_req_i,
  output avsbus_controller_pkg::avsbus_axil_resp_t             axil_resp_o,

  // Interrupt interface
  output logic interrupt_o,

  // DFT interface
  input logic scan_rst_ni,
  input logic test_en_i,
  input logic clk_test_i,

  // Debug interface
  output logic [16:0] cur_state_debug_o
);

  localparam int unsigned SlaveResyncCycles = 34;
  localparam int unsigned ResetSyncStages = 6;
  localparam int unsigned SdataValidFrameBit = 29;
  localparam bit [1:0] MasterSubframePreamble = 2'b01;

  localparam int unsigned CrcDataWidth = 29;
  localparam int unsigned CrcPolyWidth = 3;

  /***********************************************************************/
  /*                                                                     */
  /*                    SECTION: SIGNAL DECLARATIONS                     */
  /*                                                                     */
  /***********************************************************************/

  // APB internal signals:
  logic psel;
  avsbus_controller_pkg::addr_t paddr;
  logic penable;
  logic pwrite;
  apb_pkg::prot_t pprot;
  avsbus_controller_pkg::data_t pwdata;
  avsbus_controller_pkg::strb_t pstrb;
  logic pready;
  avsbus_controller_pkg::data_t prdata;
  logic pslverr;

  //sync'd resets:
  logic reset_n_apb_clk_syncd;
  logic reset_n_avs_clk_syncd;
  logic reset_n_pre_div_clk_syncd;

  // CRC:
  logic [CrcDataWidth+CrcPolyWidth-1 : 0] data_for_crc_calc;
  logic [CrcDataWidth+CrcPolyWidth-1 : 0] data_for_crc_check;
  logic [CrcPolyWidth-1:0] calculated_crc;
  logic crc_check_good;

  // Read-Only Register Fields
  logic [31:0] R_avs_debug_readback_F_avs_slave_subframe;
  logic [31:0] R_avs_latest_slave_subframe_F_avs_slave_subframe;
  logic [15:0] R_avs_normal_status_F_total_retries;
  logic [0:0] R_avs_normal_status_F_readback_has_data;
  logic [0:0] R_avs_normal_status_F_readback_fifo_full;
  logic [0:0] R_avs_normal_status_F_cmd_fifo_full;
  logic [0:0] R_avs_normal_status_F_cmd_fifo_empty;
  logic [0:0] R_avs_interrupt_F_readback_overflow_int;
  logic [0:0] R_avs_interrupt_F_readback_underflow_int;
  logic [0:0] R_avs_interrupt_F_cmd_fifo_overflow_int;
  logic [0:0] R_avs_interrupt_F_max_retries_attempted_int;
  logic [0:0] R_avs_interrupt_F_slave_unresponsive_int;
  logic [0:0] R_avs_interrupt_F_readback_has_data_int;
  logic [0:0] R_avs_interrupt_F_readback_fifo_full_int;
  logic [0:0] R_avs_interrupt_F_cmd_fifo_full_int;
  logic [0:0] R_avs_interrupt_F_avs_slave_issued_interrupt;
  logic [1:0] R_avs_slave_status_F_avs_slave_ack;
  logic [4:0] R_avs_slave_status_F_avs_slave_status_response;

  // Writable Register Fields
  logic [0:0] R_avs_interrupt_mask_F_disable_readback_overflow_int;
  logic [0:0] R_avs_interrupt_mask_F_disable_readback_underflow_int;
  logic [0:0] R_avs_interrupt_mask_F_disable_cmd_fifo_overflow_int;
  logic [0:0] R_avs_interrupt_mask_F_disable_max_retries_attempted_int;
  logic [0:0] R_avs_interrupt_mask_F_disable_slave_unresponsive_int;
  logic [0:0] R_avs_interrupt_mask_F_disable_readback_has_data_int;
  logic [0:0] R_avs_interrupt_mask_F_disable_readback_fifo_full_int;
  logic [0:0] R_avs_interrupt_mask_F_disable_cmd_fifo_full_int;
  logic [0:0] R_avs_interrupt_mask_F_disable_avs_slave_issued_interrupt;
  logic [0:0] R_avs_interrupt_clear_F_clear_readback_overflow_int;
  logic [0:0] R_avs_interrupt_clear_F_clear_readback_underflow_int;
  logic [0:0] R_avs_interrupt_clear_F_clear_cmd_fifo_overflow_int;
  logic [0:0] R_avs_interrupt_clear_F_clear_max_retries_attempted_int;
  logic [0:0] R_avs_interrupt_clear_F_clear_readback_has_data_int;
  logic [0:0] R_avs_interrupt_clear_F_clear_readback_fifo_full_int;
  logic [0:0] R_avs_interrupt_clear_F_clear_cmd_fifo_full_int;
  logic [0:0] R_avs_interrupt_clear_F_clear_avs_slave_issued_interrupt;
  logic [0:0] R_avs_interrupt_clear_F_clear_slave_unresponsive_int;
  logic [7:0] R_avs_cfg_0_F_max_retries;
  logic [15:0] R_avs_cfg_0_F_resync_interval;
  logic [7:0] R_avs_cfg_1_F_clk_divider_value;
  logic [7:0] R_avs_cfg_1_F_clk_divider_value_resync;
  logic [7:0] R_avs_cfg_1_F_clk_divider_duty_cycle_numerator;
  logic [7:0] R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync;
  logic [0:0] R_avs_cfg_1_F_stop_avs_clock_on_idle;
  logic [0:0] R_avs_cfg_1_F_turn_off_all_premux_clocks;
  logic [0:0] R_avs_cfg_1_F_force_slave_resync_operation;
  logic [1:0] R_avs_cfg_1_F_avs_clock_select;
  logic [3:0] R_avs_fifos_status_F_readback_fifo_vacant_slots;
  logic [3:0] R_avs_fifos_status_F_readback_fifo_occupied_slots;
  logic [3:0] R_avs_fifos_status_F_cmd_fifo_vacant_slots;
  logic [3:0] R_avs_fifos_status_F_cmd_fifo_occupied_slots;

  // Clock divider update logic:
  logic [7:0] previous_clk_divider_value_q;
  logic [7:0] previous_clk_divider_duty_cycle_numerator_q;
  logic update_clk_divider_value;
  logic do_initial_divider_setting;

  // clock mux selectors:
  logic postdiv_mux_sel;
  logic prediv_mux_sel;

  // External Registers
  logic [31:0] external_reg_wr_data;
  logic R_avs_cmd_wr_en;
  logic R_avs_readback_rd_en;

  //Register fields resync'd to/from other clock domains:
  logic [0:0] R_avs_cfg_1_F_stop_avs_clock_on_idle_RS_avs_clk;
  logic [0:0] R_avs_cfg_1_F_turn_off_all_premux_clocks_RS_refclk;
  logic [0:0] R_avs_interrupt_clear_F_clear_avs_slave_issued_interrupt_RS_avs_clk;
  logic [0:0] R_avs_interrupt_clear_F_clear_slave_unresponsive_int_RS_avs_clk;
  logic [7:0] R_avs_cfg_0_F_max_retries_RS_avs_clk;
  logic [0:0] R_avs_normal_status_F_readback_fifo_full_AVSCLK;
  logic [0:0] R_avs_normal_status_F_readback_fifo_full_AVSCLK_q;
  logic [0:0] R_avs_interrupt_F_slave_unresponsive_int_AVSCLK;
  logic [0:0] R_avs_interrupt_F_avs_slave_issued_interrupt_AVSCLK;
  logic [15:0] R_avs_normal_status_F_total_retries_AVSCLK;


  // clock signals:
  logic pre_testmux_avs_clk;
  logic avs_clk;
  logic pre_div_clk;
  logic apb_ref_muxed_clk;
  logic avs_clk_enable;
  logic refclk_gated;
  logic apb_clk_gated;

  // Command fifo signals, APB side:
  logic push_avs_cmd_en;

  // Command fifo signals, AVS side:
  logic pop_avs_cmd_en;
  logic [31:0] avs_cmd_from_fifo;
  logic avs_cmd_buf_empty;
  logic fifos_ready_to_launch_frame;
  logic fifos_ready_to_launch_frame_rb_en;
  logic fifos_ready_to_launch_frame_rb_en_b;

  // Readback fifo signals, AVS side:
  logic push_avs_readback_en;
  logic push_avs_readback_en_q;
  logic push_avs_readback_en_RS_apb_clk;
  logic [$clog2(READBACK_FIFO_DEPTH):0] R_avs_fifos_status_F_readback_fifo_vacant_slots_AVSCLK;
  logic [$clog2(READBACK_FIFO_DEPTH):0] R_avs_fifos_status_F_readback_fifo_occupied_slots_AVSCLK;


  // Readback fifo signals, APB side:
  logic apb_readback_buf_empty;
  logic pop_apb_readback_en;
  logic [31:0] apb_readback_from_fifo;

  // Intermediate signals:
  logic apb_cmd_buffer_wrdata_ready_to_sample;
  logic apb_waiting_for_readback_data;

  // AVS related signals:
  logic [5:0] slave_resync_counter;
  logic [15:0] clock_cycles_since_last_resync;
  logic slave_resync_pending;
  logic slave_resync_pending_RS_avs_clk;
  logic [4:0] avs_subframe_bit_index;
  logic [31:0] avs_mdata_transmit_frame;
  logic [31:0] avs_mdata_prev_transmit_frame;
  logic [31:0] avs_sdata_capture;
  logic [31:0] avs_previous_sdata_capture;
  logic avs_got_pending_sdata_from_after_retry_frame;
  logic [7:0] avs_retry_countdown;
  logic [1:0] avs_sdata_interrupt_detect;
  logic avs_max_retries_attempted;
  logic avs_max_retries_attempted_q;
  logic avs_max_retries_attempted_RS_apb_clk;
  logic avs_retry_condition_detected;

  // AVS_Mdata (master subframe) field enums for waving, debug:
  typedef enum logic [1:0] {
    CommitWrite = 2'b00,
    HoldWrite   = 2'b01,
    Read        = 2'b11
  } cmd_type_t;

  typedef enum logic {
    AvsBus = 1'b0,
    ManufacturerSpec = 1'b1
  } cmd_group_t;

  typedef enum logic [3:0] {
    Voltage     = 4'b0000,
    Transition  = 4'b0001,
    Current     = 4'b0010,
    Temperature = 4'b0011,
    ResetVolt   = 4'b0100,
    PowerMode   = 4'b0101,
    Status      = 4'b1110,
    Version     = 4'b1111
  } cmd_data_type_t;

  logic [1:0] CmdPreamble;
  cmd_type_t CmdType;
  cmd_group_t CmdGroup;
  cmd_data_type_t CmdDataType;
  logic [3:0] CmdSelect;
  logic [15:0] CmdData;
  logic [2:0] CmdCRC;

  assign CmdPreamble = avs_mdata_transmit_frame[31:30];
  assign CmdType = cmd_type_t'(avs_mdata_transmit_frame[29:28]);
  assign CmdGroup = cmd_group_t'(avs_mdata_transmit_frame[27]);
  assign CmdDataType = cmd_data_type_t'(avs_mdata_transmit_frame[26:23]);
  assign CmdSelect = avs_mdata_transmit_frame[22:19];
  assign CmdData = avs_mdata_transmit_frame[18:3];
  assign CmdCRC = avs_mdata_transmit_frame[2:0];


  // AVS_Sdata (slave subframe) field enums:
  typedef enum logic [1:0] {
    SlaveAckActionPerformed     = 2'b00,
    SlaveAckResourceUnavailable = 2'b01,
    SlaveAckBadCRC              = 2'b10,
    SlaveAckBadDataOrSelector   = 2'b11
  } slave_ack_t;
  slave_ack_t slave_ack;
  assign slave_ack = slave_ack_t'(avs_sdata_capture[31:30]);


  // AVS FSM states:
  typedef enum logic [16:0] {
    AVS_RESET                              = 17'b00000000000000001,
    AVS_SLAVE_RESYNC                       = 17'b00000000000000010,
    AVS_LAUNCH_FRAME_POST_RESYNC           = 17'b00000000000000100,
    AVS_IDLE                               = 17'b00000000000001000,
    AVS_SHIFT_1ST_SUBFRAME                 = 17'b00000000000010000,
    AVS_END_1ST_SUBFRAME                   = 17'b00000000000100000,
    AVS_SHIFT_MID_SUBFRAME                 = 17'b00000000001000000,
    AVS_END_MID_SUBFRAME                   = 17'b00000000010000000,
    AVS_SHIFT_LAST_SUBFRAME                = 17'b00000000100000000,
    AVS_END_LAST_SUBFRAME                  = 17'b00000001000000000,
    AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME = 17'b00000010000000000,
    AVS_RETRY_END_XMIT_AND_RECV_SUBFRAME   = 17'b00000100000000000,
    AVS_RETRY_SHIFT_XMIT_SUBFRAME          = 17'b00001000000000000,
    AVS_RETRY_END_XMIT_SUBFRAME            = 17'b00010000000000000,
    AVS_RETRY_SHIFT_RECV_SUBFRAME          = 17'b00100000000000000,
    AVS_RETRY_END_RECV_SUBFRAME            = 17'b01000000000000000,
    AVS_PROCESS_PREVIOUS_SDATA             = 17'b10000000000000000
  } state_t;

  state_t cur_state, next_state, cur_state_RS_apb_clk;
  logic [$bits(state_t)-1:0] cur_state_RS_apb_clk_logic;

  assign cur_state_debug_o = cur_state_RS_apb_clk_logic;

  /***********************************************************************/
  /*                                                                     */
  /*                       SECTION: APB LOGIC                            */
  /*                                                                     */
  /***********************************************************************/

  // Use axi4-lite to apb4 conversion
  // Define address map for single APB slave (register block)
  avsbus_controller_pkg::rule_t [0:0] addr_map;
  assign addr_map[0] = '{
          idx: 0,
          start_addr: avsbus_controller_pkg::ADDR_WIDTH'(32'h0000_0000),
          end_addr: avsbus_controller_pkg::ADDR_WIDTH'(32'hFFFF_FFFF)
      };


  // APB request/response signals from bridge
  avsbus_controller_pkg::avsbus_apb_req_t [0:0] apb_bridge_req;
  avsbus_controller_pkg::avsbus_apb_resp_t [0:0] apb_bridge_resp;

  axi_lite_to_apb #(
    .NoApbSlaves(1),
    .NoRules(1),
    .AddrWidth(avsbus_controller_pkg::ADDR_WIDTH),
    .DataWidth(avsbus_controller_pkg::DATA_WIDTH),
    .PipelineRequest(1'b0),
    .PipelineResponse(1'b0),
    .axi_lite_req_t(avsbus_controller_pkg::avsbus_axil_req_t),
    .axi_lite_resp_t(avsbus_controller_pkg::avsbus_axil_resp_t),
    .apb_req_t(avsbus_controller_pkg::avsbus_apb_req_t),
    .apb_resp_t(avsbus_controller_pkg::avsbus_apb_resp_t),
    .rule_t(avsbus_controller_pkg::rule_t)
  ) u_axi_lite_to_apb (
    .clk_i(clk_reg_i),
    .rst_ni(reset_n_apb_clk_syncd),
    .axi_lite_req_i(axil_req_i),
    .axi_lite_resp_o(axil_resp_o),
    .apb_req_o(apb_bridge_req),
    .apb_resp_i(apb_bridge_resp),
    .addr_map_i(addr_map)
  );

  // Connect APB signals from struct to internal signals
  assign psel = apb_bridge_req[0].psel;
  assign paddr = apb_bridge_req[0].paddr;
  assign penable = apb_bridge_req[0].penable;
  assign pwrite = apb_bridge_req[0].pwrite;
  assign pprot = apb_bridge_req[0].pprot;
  assign pwdata = apb_bridge_req[0].pwdata;
  assign pstrb = apb_bridge_req[0].pstrb;
  assign apb_bridge_resp[0].pready = pready;
  assign apb_bridge_resp[0].prdata = prdata;
  assign apb_bridge_resp[0].pslverr = pslverr;

  /***********************************************************************/
  /*                                                                     */
  /*                       SECTION: CLOCK LOGIC                          */
  /*                                                                     */
  /***********************************************************************/

  logic final_update_clk_divider_value;
  logic [7:0] final_R_avs_cfg_1_F_clk_divider_value_resync;
  logic [7:0] final_R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync;
  logic final_postdiv_mux_sel;

  logic i_tdr_peripherals_apb2avsbus_postdiv_override;
  logic i_tdr_peripherals_apb2avsbus_update_clk_divider_value;
  logic [7:0] i_tdr_peripherals_apb2avsbus_R_avs_cfg_1_F_clk_divider_value_resync;
  logic [7:0] i_tdr_peripherals_apb2avsbus_R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync;
  logic i_tdr_peripherals_apb2avsbus_postdiv_mux_sel;

  assign i_tdr_peripherals_apb2avsbus_postdiv_override = 1'b0;
  assign i_tdr_peripherals_apb2avsbus_update_clk_divider_value = 1'b0;
  assign i_tdr_peripherals_apb2avsbus_R_avs_cfg_1_F_clk_divider_value_resync = 8'h0;
  assign i_tdr_peripherals_apb2avsbus_R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync = 8'h0;
  assign i_tdr_peripherals_apb2avsbus_postdiv_mux_sel = 1'b0;

  assign final_update_clk_divider_value = i_tdr_peripherals_apb2avsbus_postdiv_override ? i_tdr_peripherals_apb2avsbus_update_clk_divider_value : update_clk_divider_value;
  assign final_R_avs_cfg_1_F_clk_divider_value_resync = i_tdr_peripherals_apb2avsbus_postdiv_override ? i_tdr_peripherals_apb2avsbus_R_avs_cfg_1_F_clk_divider_value_resync : R_avs_cfg_1_F_clk_divider_value_resync;
  assign final_R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync = i_tdr_peripherals_apb2avsbus_postdiv_override ? i_tdr_peripherals_apb2avsbus_R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync : R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync;
  assign final_postdiv_mux_sel = i_tdr_peripherals_apb2avsbus_postdiv_override ? i_tdr_peripherals_apb2avsbus_postdiv_mux_sel : postdiv_mux_sel;

  // programmable clock divider:
  prim_prog_clk_div_posedge #(
    .RESET_WIDTH(ResetSyncStages),
    .INITIAL_DIVIDER_VAL(8'd4),  // by default, divide by 4 to create a slower freq for AVS
    .DIVIDED_CLOCK_ON_RESET(1'b1) // Select divided clock on reset
  ) u_clk_div (
    .clk_i(pre_div_clk),
    .rst_ni(rst_clk_div_ni),
    .test_en_i(test_en_i),
    .scan_rst_ni(scan_rst_ni),

    .update_settings_i(final_update_clk_divider_value),
    .divider_i(final_R_avs_cfg_1_F_clk_divider_value_resync),
    .duty_cycle_i(final_R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync),
    .use_clk_div_i(final_postdiv_mux_sel),

    .clk_o(pre_testmux_avs_clk)
  );

  // Select bypass (div-by-1) clock in test mode:
  assign postdiv_mux_sel = R_avs_cfg_1_F_avs_clock_select[0] & ~test_en_i;


  always_ff @(posedge apb_ref_muxed_clk) begin
    previous_clk_divider_value_q <= R_avs_cfg_1_F_clk_divider_value_resync;
    previous_clk_divider_duty_cycle_numerator_q <= R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync ;
  end

  // tt_prog_clk_div_posedge.i_update_settings needs to be pulsed initially for the divider to start working.
  // This reg indicates whether initial post-reset pulse is required:
  always_ff @(posedge apb_ref_muxed_clk) begin
    if (~reset_n_pre_div_clk_syncd) begin
      // this is set to 0 to trick clock divider into not initially updating settings
      // this allows the HW-default values to be maintained until SW intentionally writes the register values
      do_initial_divider_setting <= 1'b0;
    end else if (update_clk_divider_value == 1'b1) begin
      do_initial_divider_setting <= 1'b0;
    end
  end


  always_ff @(posedge apb_ref_muxed_clk) begin
    if (~reset_n_pre_div_clk_syncd) begin
      update_clk_divider_value <= 1'b0;
    end else begin
      update_clk_divider_value <= (do_initial_divider_setting == 1'b1 ||
                                    R_avs_cfg_1_F_clk_divider_value_resync != previous_clk_divider_value_q ||
                                    R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync != previous_clk_divider_duty_cycle_numerator_q) ? 1'b1 : 1'b0 ;
    end
  end


  // AVS bus clock gate:
  prim_clkgater u_avs_bus_clkgate (
    .clk_i (avs_clk),
    .en_i  (avs_clk_enable),
    .te_i (test_en_i),
    .clk_o(avs_clock_o)
  );

  prim_ag_clk_mux #(
    .SelectOnReset(1'b1)
  ) u_refclk_apbclk_mux (
    .rst_clk0_ni(rst_reg_ni),
    .rst_clk1_ni(rst_ref_ni),
    .clk0_i(apb_clk_gated),
    .clk1_i(refclk_gated),
    .test_en_i(test_en_i),
    .sel_i(prediv_mux_sel),
    .clk_o(apb_ref_muxed_clk)
  );

  // test mux to bypass APBCLK/REFCLK antiglitch mux in testmode:
  prim_clock_mux2 test_clkmux2_0 (
    .clk0_i (apb_ref_muxed_clk),
    .clk1_i (clk_test_i),
    .sel_i (test_en_i),
    .clk_o  (pre_div_clk)
  );

  // Select apbclk clock in test mode:
  assign prediv_mux_sel = R_avs_cfg_1_F_avs_clock_select[1] & ~test_en_i;

  // apb_clk clock gate:
  prim_clkgater u_apbclk_clkgate (
    .clk_i (clk_reg_i),
    .en_i  (~R_avs_cfg_1_F_turn_off_all_premux_clocks),
    .te_i (test_en_i),
    .clk_o(apb_clk_gated)
  );

  // refclk clock gate:
  prim_clkgater u_refclk_clkgate (
    .clk_i (clk_ref_i),
    .en_i  (~R_avs_cfg_1_F_turn_off_all_premux_clocks_RS_refclk),
    .te_i (test_en_i),
    .clk_o(refclk_gated)
  );

  prim_sync3 u_gate_refclk_en_sync (
    .clk_i(clk_ref_i),
    .d_i (R_avs_cfg_1_F_turn_off_all_premux_clocks),
    .q_o (R_avs_cfg_1_F_turn_off_all_premux_clocks_RS_refclk)
  );

  assign avs_clk = pre_testmux_avs_clk;

  /***********************************************************************/
  /*                                                                     */
  /*                         SECTION: RESYNCS                            */
  /*                                                                     */
  /***********************************************************************/

  // Reset synchronizers:
  prim_sync_reset #(
    .WIDTH(ResetSyncStages)
  ) apb_clk_reset_sync (
    .clk_i(clk_reg_i),
    .rst_ni(rst_reg_ni),
    .test_mode_i(test_en_i),
    .scan_rst_ni(scan_rst_ni),
    .sync_rst_no(reset_n_apb_clk_syncd)
  );

  prim_sync_reset #(
    .WIDTH(ResetSyncStages)
  ) avs_clk_reset_sync (
    .clk_i(avs_clk),
    .rst_ni(rst_reg_ni),
    .test_mode_i(test_en_i),
    .scan_rst_ni(scan_rst_ni),
    .sync_rst_no(reset_n_avs_clk_syncd)
  );

  prim_sync_reset #(
    .WIDTH(ResetSyncStages)
  ) pre_div_clk_reset_sync (
    .clk_i(apb_ref_muxed_clk),
    .rst_ni(rst_reg_ni),
    .test_mode_i(test_en_i),
    .scan_rst_ni(scan_rst_ni),
    .sync_rst_no(reset_n_pre_div_clk_syncd)
  );

  // register re-synchronizers:
  prim_sync3 u_idle_clk_reg_resync (
    .clk_i(avs_clk),
    .d_i (R_avs_cfg_1_F_stop_avs_clock_on_idle),
    .q_o (R_avs_cfg_1_F_stop_avs_clock_on_idle_RS_avs_clk)
  );

  prim_sync3 u_slave_resync_pending_resync (
    .clk_i(avs_clk),
    .d_i (slave_resync_pending),
    .q_o (slave_resync_pending_RS_avs_clk)
  );

  prim_sync3 u_readback_fifo_full_resync (
    .clk_i(clk_reg_i),
    .d_i (R_avs_normal_status_F_readback_fifo_full_AVSCLK_q),
    .q_o (R_avs_normal_status_F_readback_fifo_full)
  );

  // flop before re-sync'ing:
  always_ff @(posedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) begin
      R_avs_normal_status_F_readback_fifo_full_AVSCLK_q <= 1'b0;
    end else begin
      R_avs_normal_status_F_readback_fifo_full_AVSCLK_q <= R_avs_normal_status_F_readback_fifo_full_AVSCLK;
    end
  end

  prim_sync3 u_slave_unresponsive_resync (
    .clk_i(clk_reg_i),
    .d_i (R_avs_interrupt_F_slave_unresponsive_int_AVSCLK),
    .q_o (R_avs_interrupt_F_slave_unresponsive_int)
  );

  prim_sync3 u_slave_interrupt_resync (
    .clk_i(clk_reg_i),
    .d_i (R_avs_interrupt_F_avs_slave_issued_interrupt_AVSCLK),
    .q_o (R_avs_interrupt_F_avs_slave_issued_interrupt)
  );

  prim_sync3 u_avs_readback_en_resync (
    .clk_i(clk_reg_i),
    .d_i (push_avs_readback_en_q),
    .q_o (push_avs_readback_en_RS_apb_clk)
  );

  // flop before re-sync'ing:
  always_ff @(posedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) begin
      push_avs_readback_en_q <= 1'b0;
    end else begin
      push_avs_readback_en_q <= push_avs_readback_en;
    end
  end

  prim_sync3 u_max_retries_attempted_resync (
    .clk_i(clk_reg_i),
    .d_i (avs_max_retries_attempted_q),
    .q_o (avs_max_retries_attempted_RS_apb_clk)
  );
  // flop before re-sync'ing:
  always_ff @(posedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) begin
      avs_max_retries_attempted_q <= 1'b0;
    end else begin
      avs_max_retries_attempted_q <= avs_max_retries_attempted;
    end
  end

  // pulse resyncs from fast domain (APBCLK) to slower domain (AVSCLK):
  prim_sync3_pulse u_clear_avs_slave_int_resync (
    .src_clk_i(clk_reg_i),
    .src_pulse_i(R_avs_interrupt_clear_F_clear_avs_slave_issued_interrupt),
    .src_rst_ni(reset_n_apb_clk_syncd),
    .dst_clk_i(avs_clk),
    .dst_pulse_o(R_avs_interrupt_clear_F_clear_avs_slave_issued_interrupt_RS_avs_clk)
  );

  prim_sync3_pulse u_clear_slave_unresponsive_int_resync (
    .src_clk_i(clk_reg_i),
    .src_pulse_i(R_avs_interrupt_clear_F_clear_slave_unresponsive_int),
    .src_rst_ni(reset_n_apb_clk_syncd),
    .dst_clk_i(avs_clk),
    .dst_pulse_o(R_avs_interrupt_clear_F_clear_slave_unresponsive_int_RS_avs_clk)
  );


  // vectored resyncs:
  prim_sync_data_autohs #(
    .WIDTH($size(cur_state)),
    .DEPTH(3)
  ) u_cur_state_resync (
    .clk_src_i(avs_clk),
    .rst_src_ni(reset_n_avs_clk_syncd),
    .data_i(cur_state),
    .clk_dst_i(clk_reg_i),
    .rst_dst_ni(reset_n_apb_clk_syncd),
    .data_o(cur_state_RS_apb_clk_logic)
  );
  assign cur_state_RS_apb_clk = state_t'(cur_state_RS_apb_clk_logic);

  prim_sync_data_autohs #(
    .WIDTH($size(R_avs_cfg_1_F_clk_divider_value)),
    .DEPTH(3)
  ) u_divider_value_resync (
    .clk_src_i(clk_reg_i),
    .rst_src_ni(reset_n_apb_clk_syncd),
    .data_i(R_avs_cfg_1_F_clk_divider_value),
    .clk_dst_i(apb_ref_muxed_clk),
    .rst_dst_ni(reset_n_pre_div_clk_syncd),
    .data_o(R_avs_cfg_1_F_clk_divider_value_resync)
  );

  prim_sync_data_autohs #(
    .WIDTH($size(R_avs_cfg_1_F_clk_divider_duty_cycle_numerator)),
    .DEPTH(3)
  ) u_duty_numerator_resync (
    .clk_src_i(clk_reg_i),
    .rst_src_ni(reset_n_apb_clk_syncd),
    .data_i(R_avs_cfg_1_F_clk_divider_duty_cycle_numerator),
    .clk_dst_i(apb_ref_muxed_clk),
    .rst_dst_ni(reset_n_pre_div_clk_syncd),
    .data_o(R_avs_cfg_1_F_clk_divider_duty_cycle_numerator_resync)
  );

  prim_sync_data_autohs #(
    .WIDTH($size(R_avs_fifos_status_F_readback_fifo_vacant_slots_AVSCLK)),
    .DEPTH(3)
  ) u_readback_vacant_resync (
    .clk_src_i(avs_clk),
    .rst_src_ni(reset_n_avs_clk_syncd),
    .data_i(R_avs_fifos_status_F_readback_fifo_vacant_slots_AVSCLK),
    .clk_dst_i(clk_reg_i),
    .rst_dst_ni(reset_n_apb_clk_syncd),
    .data_o(R_avs_fifos_status_F_readback_fifo_vacant_slots)
  );

  prim_sync_data_autohs #(
    .WIDTH($size(R_avs_fifos_status_F_readback_fifo_occupied_slots_AVSCLK)),
    .DEPTH(3)
  ) u_readback_occupied_resync (
    .clk_src_i(avs_clk),
    .rst_src_ni(reset_n_avs_clk_syncd),
    .data_i(R_avs_fifos_status_F_readback_fifo_occupied_slots_AVSCLK),
    .clk_dst_i(clk_reg_i),
    .rst_dst_ni(reset_n_apb_clk_syncd),
    .data_o(R_avs_fifos_status_F_readback_fifo_occupied_slots)
  );

  prim_sync_data_autohs #(
    .WIDTH($size(R_avs_normal_status_F_total_retries)),
    .DEPTH(3)
  ) u_total_retries_resync (
    .clk_src_i(avs_clk),
    .rst_src_ni(reset_n_avs_clk_syncd),
    .data_i(R_avs_normal_status_F_total_retries_AVSCLK),
    .clk_dst_i(clk_reg_i),
    .rst_dst_ni(reset_n_apb_clk_syncd),
    .data_o(R_avs_normal_status_F_total_retries)
  );

  // AVS_SLAVE_STATUS and AVS_LATEST_SLAVE_SUBFRAME are storageless (passthrough)
  // CSR reads: without a resync the raw avs_clk-domain registers would ride the
  // register block's read mux straight into the APB/AXI response path. Both
  // fields of AVS_SLAVE_STATUS share one autohs so they stay coherent with each
  // other, matching how software reads them (a single 32-bit CSR read).
  logic [1:0]  R_avs_slave_status_F_avs_slave_ack_RS_apb_clk;
  logic [4:0]  R_avs_slave_status_F_avs_slave_status_response_RS_apb_clk;
  logic [31:0] R_avs_latest_slave_subframe_F_avs_slave_subframe_RS_apb_clk;

  prim_sync_data_autohs #(
      .WIDTH(7),
      .DEPTH(3)
  ) u_slave_status_resync (
      .i_clk_src(avs_clk),
      .i_reset_src_n(reset_n_avs_clk_syncd),
      .i_data({R_avs_slave_status_F_avs_slave_ack,
               R_avs_slave_status_F_avs_slave_status_response}),
      .i_clk_dst(clk_reg_i),
      .i_reset_dst_n(reset_n_apb_clk_syncd),
      .o_data({R_avs_slave_status_F_avs_slave_ack_RS_apb_clk,
               R_avs_slave_status_F_avs_slave_status_response_RS_apb_clk})
  );

  prim_sync_data_autohs #(
      .WIDTH($size(R_avs_latest_slave_subframe_F_avs_slave_subframe)),
      .DEPTH(3)
  ) u_latest_subframe_resync (
      .i_clk_src(avs_clk),
      .i_reset_src_n(reset_n_avs_clk_syncd),
      .i_data(R_avs_latest_slave_subframe_F_avs_slave_subframe),
      .i_clk_dst(clk_reg_i),
      .i_reset_dst_n(reset_n_apb_clk_syncd),
      .o_data(R_avs_latest_slave_subframe_F_avs_slave_subframe_RS_apb_clk)
  );

  prim_sync_data_autohs #(
    .WIDTH($size(R_avs_cfg_0_F_max_retries)),
    .DEPTH(3)
  ) u_max_retries_resync (
    .clk_src_i(clk_reg_i),
    .rst_src_ni(reset_n_apb_clk_syncd),
    .data_i(R_avs_cfg_0_F_max_retries),
    .clk_dst_i(avs_clk),
    .rst_dst_ni(reset_n_avs_clk_syncd),
    .data_o(R_avs_cfg_0_F_max_retries_RS_avs_clk)
  );

  /***********************************************************************/
  /*                                                                     */
  /*                        SECTION: FSM STATE LOGIC                     */
  /*                                                                     */
  /***********************************************************************/

  // FSM update state:
  always_ff @(posedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) cur_state <= AVS_RESET;
    else cur_state <= next_state;
  end


  // FSM: next_state determination:
  always_comb begin
    next_state = AVS_IDLE;
    data_for_crc_calc = '0;
    data_for_crc_check = '0;
    push_avs_readback_en = 1'b0;
    avs_max_retries_attempted = 1'b0;
    unique case (cur_state)
      AVS_RESET: begin
        next_state = AVS_SLAVE_RESYNC;
      end
      AVS_SLAVE_RESYNC: begin
        if (slave_resync_counter == SlaveResyncCycles) begin
          if (fifos_ready_to_launch_frame_rb_en_b) begin
            next_state = AVS_LAUNCH_FRAME_POST_RESYNC;
          end else begin
            next_state = AVS_IDLE;
          end
        end else begin
          next_state = AVS_SLAVE_RESYNC;
        end
      end
      AVS_IDLE: begin
        if (fifos_ready_to_launch_frame_rb_en_b) begin
          if (R_avs_cfg_1_F_stop_avs_clock_on_idle_RS_avs_clk) begin
            // Always do a resync after initially restarting the clock:
            next_state = AVS_SLAVE_RESYNC;
          end else begin
            next_state = AVS_SHIFT_1ST_SUBFRAME;
            data_for_crc_calc = {MasterSubframePreamble, avs_cmd_from_fifo[29:3], 3'b000};
          end
        end else if (slave_resync_pending_RS_avs_clk) begin
          next_state = AVS_SLAVE_RESYNC;
        end else begin
          next_state = AVS_IDLE;
        end
      end
      AVS_LAUNCH_FRAME_POST_RESYNC: begin
        next_state = AVS_SHIFT_1ST_SUBFRAME;
        data_for_crc_calc = {MasterSubframePreamble, avs_cmd_from_fifo[29:3], 3'b000};
      end
      AVS_SHIFT_1ST_SUBFRAME: begin
        if (avs_subframe_bit_index == 0) begin
          next_state = AVS_END_1ST_SUBFRAME;
        end else begin
          next_state = AVS_SHIFT_1ST_SUBFRAME;
        end
      end
      AVS_END_1ST_SUBFRAME: begin
        // Check if 3rd bit of slave response was low - if so, indicates it has sent a valid StatusResp message, so check
        // CRC. Reg field R_avs_slave_status_F_avs_slave_status_response will then get updated (in another always_ff) if CRC
        // check comes back good:
        // issues, if any found, set register status bit or interrupt bit:
        if (avs_sdata_capture[SdataValidFrameBit] == 1'b0) begin
          data_for_crc_check = avs_sdata_capture;
        end else begin
          // Technically this 'else' clause shouldn't be required since this signal is defaulted at the
          // top of the block, but for some reason (tool bug?) Spyglass complains about this specific case with an
          // "AlwaysCombExhaustive" Warning, so add the else here just to keep the tool happy:
          data_for_crc_check = '0;
        end
        if (fifos_ready_to_launch_frame_rb_en_b) begin
          next_state = AVS_SHIFT_MID_SUBFRAME;
          data_for_crc_calc = {MasterSubframePreamble, avs_cmd_from_fifo[29:3], 3'b000};
        end else begin
          next_state = AVS_SHIFT_LAST_SUBFRAME;
        end
      end
      AVS_SHIFT_MID_SUBFRAME: begin
        if (avs_subframe_bit_index == 0) begin
          next_state = AVS_END_MID_SUBFRAME;
        end else begin
          next_state = AVS_SHIFT_MID_SUBFRAME;
        end
      end
      AVS_END_MID_SUBFRAME: begin
        data_for_crc_check   = avs_sdata_capture;
        push_avs_readback_en = 1'b1;
        if (avs_retry_condition_detected) begin
          // retry condition => retry previous frame, but also still need to capture slave response from current frame:
          if (R_avs_cfg_0_F_max_retries_RS_avs_clk > 0) begin
            next_state = AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME;
            data_for_crc_calc = {avs_mdata_prev_transmit_frame[31:3], 3'b000};
            push_avs_readback_en = 1'b0;
          end else begin
            // Programmed to suppress retries, so just send back whatever data was rec'd to the readback fifo
            // and initiate any subsequent frames.
            push_avs_readback_en = 1'b1;
            if (fifos_ready_to_launch_frame_rb_en) begin
              next_state = AVS_SHIFT_MID_SUBFRAME;
              data_for_crc_calc = {MasterSubframePreamble, avs_cmd_from_fifo[29:3], 3'b000};
            end else begin
              next_state = AVS_SHIFT_LAST_SUBFRAME;
            end
          end
        end else if (fifos_ready_to_launch_frame_rb_en) begin
          next_state = AVS_SHIFT_MID_SUBFRAME;
          data_for_crc_calc = {MasterSubframePreamble, avs_cmd_from_fifo[29:3], 3'b000};
        end else begin
          next_state = AVS_SHIFT_LAST_SUBFRAME;
        end
      end
      AVS_SHIFT_LAST_SUBFRAME: begin
        if (avs_subframe_bit_index == 0) begin
          next_state = AVS_END_LAST_SUBFRAME;
        end else begin
          next_state = AVS_SHIFT_LAST_SUBFRAME;
        end
      end
      AVS_END_LAST_SUBFRAME: begin
        data_for_crc_check   = avs_sdata_capture;
        push_avs_readback_en = 1'b1;
        if (avs_retry_condition_detected) begin
          // retry condition => retry previous frame:
          if (R_avs_cfg_0_F_max_retries_RS_avs_clk > 0) begin
            next_state = AVS_RETRY_SHIFT_XMIT_SUBFRAME;
            data_for_crc_calc = {avs_mdata_prev_transmit_frame[31:3], 3'b000};
            push_avs_readback_en = 1'b0;
          end else begin
            // No retries allowed - got to idle:
            next_state = AVS_IDLE;
          end
        end else if (fifos_ready_to_launch_frame_rb_en) begin
          next_state = AVS_SHIFT_1ST_SUBFRAME;
          data_for_crc_calc = {MasterSubframePreamble, avs_cmd_from_fifo[29:3], 3'b000};
        end else begin
          next_state = AVS_IDLE;
        end
      end
      AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME: begin
        if (avs_subframe_bit_index == 0) begin
          next_state = AVS_RETRY_END_XMIT_AND_RECV_SUBFRAME;
        end else begin
          next_state = AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME;
        end
      end
      AVS_RETRY_END_XMIT_AND_RECV_SUBFRAME: begin
        // In this state, we are transmitting a retry subframe while also receiving the slave response from the previous
        // back-to-back master subframe (ie the subframe that was launched immediately after the subframe that requires the retry).
        // In this case, we need to save the slave response for later, after the retries have completed, so that we
        // can push it to the readback fifo *after* the outcome of the retries has been pushed to the readback fifo. We
        // need to do this in order to maintain the proper sequence of readback data that corresponds to the order that
        // the commands were written to the cmd fifo from APB.
        push_avs_readback_en = 1'b0;
        next_state = AVS_RETRY_SHIFT_RECV_SUBFRAME;
      end
      AVS_RETRY_SHIFT_XMIT_SUBFRAME: begin
        if (avs_subframe_bit_index == 0) begin
          next_state = AVS_RETRY_END_XMIT_SUBFRAME;
        end else begin
          next_state = AVS_RETRY_SHIFT_XMIT_SUBFRAME;
        end
      end
      AVS_RETRY_END_XMIT_SUBFRAME: begin
        next_state = AVS_RETRY_SHIFT_RECV_SUBFRAME;
      end
      AVS_RETRY_SHIFT_RECV_SUBFRAME: begin
        if (avs_subframe_bit_index == 0) begin
          next_state = AVS_RETRY_END_RECV_SUBFRAME;
        end else begin
          next_state = AVS_RETRY_SHIFT_RECV_SUBFRAME;
        end
      end
      AVS_RETRY_END_RECV_SUBFRAME: begin
        data_for_crc_check = avs_sdata_capture;
        push_avs_readback_en = 1'b1;
        if (avs_retry_condition_detected && avs_retry_countdown > 0) begin
          // retry condition => retry previous frame:
          next_state = AVS_RETRY_SHIFT_XMIT_SUBFRAME;
          push_avs_readback_en = 1'b0;
        end else begin
          if (avs_retry_condition_detected && avs_retry_countdown == 0) begin
            avs_max_retries_attempted = 1'b1;
          end
          // Either maxed out on retries or succeeded with the latest retry. Either way, send
          // whatever data was received from slave to readback fifo. Then, if there had been
          // a subsequent master frame launched after the frame had triggered the retries
          // (due to a back-to-back frames), then process the buffered response frame from that subsequent
          // master frame (in state AVS_PROCESS_PREVIOUS_SDATA): either send it to readback if it had
          // no issues of its own, or else enter a new retry sequence for that frame.
          // Then issue slave resync operation in case retries were due to lack of synchronization:
          if (avs_got_pending_sdata_from_after_retry_frame) begin
            next_state = AVS_PROCESS_PREVIOUS_SDATA;
          end else begin
            next_state = AVS_SLAVE_RESYNC;
          end
        end
      end
      AVS_PROCESS_PREVIOUS_SDATA: begin
        data_for_crc_check   = avs_previous_sdata_capture;
        push_avs_readback_en = 1'b1;
        if (avs_retry_condition_detected && R_avs_cfg_0_F_max_retries_RS_avs_clk > 0) begin
          // retry condition => retry previous frame:
          next_state = AVS_RETRY_SHIFT_XMIT_SUBFRAME;
          push_avs_readback_en = 1'b0;
        end else begin
          next_state = AVS_SLAVE_RESYNC;
        end
      end
      default: begin
        next_state = AVS_IDLE;
      end
    endcase
  end



  /***********************************************************************/
  /*                                                                     */
  /*            SECTION: FSM STATE-DEPENDENT SEQUENTIAL LOGIC            */
  /*                                                                     */
  /***********************************************************************/


  // FSM-dependent sequential operations:
  always_ff @(posedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) begin
      slave_resync_counter <= '0;
      avs_mdata_o <= 1'b1;
      avs_subframe_bit_index <= 'd30;
      pop_avs_cmd_en <= 1'b0;
      avs_mdata_transmit_frame <= '0;
      avs_mdata_prev_transmit_frame <= '0;
      avs_retry_countdown <= R_avs_cfg_0_F_max_retries_RS_avs_clk;
      avs_previous_sdata_capture <= '0;
      avs_got_pending_sdata_from_after_retry_frame <= 1'b0;
      avs_clk_enable <= 1'b1;
    end else begin
      unique case (cur_state)
        AVS_RESET: begin
          avs_clk_enable <= 1'b1;
          pop_avs_cmd_en <= 1'b0;
          slave_resync_counter <= '0;
          avs_mdata_o <= 1'b1;
          avs_subframe_bit_index <= 'd30;
          avs_retry_countdown <= R_avs_cfg_0_F_max_retries_RS_avs_clk;
        end
        AVS_SLAVE_RESYNC: begin
          avs_clk_enable <= 1'b1;
          pop_avs_cmd_en <= 1'b0;
          avs_mdata_o <= 1'b1;
          slave_resync_counter <= slave_resync_counter + 1;
        end
        AVS_IDLE: begin
          if (fifos_ready_to_launch_frame) begin
            avs_clk_enable <= 1'b1;
            if (R_avs_cfg_1_F_stop_avs_clock_on_idle_RS_avs_clk) begin
              // Go to RESYNC state first after restarting clock:
              avs_mdata_o <= 1'b1;
              pop_avs_cmd_en <= 1'b0;
            end else begin
              // launch frame:
              avs_retry_countdown <= R_avs_cfg_0_F_max_retries_RS_avs_clk;
              pop_avs_cmd_en <= 1'b1;
              avs_mdata_transmit_frame <= {
                MasterSubframePreamble, avs_cmd_from_fifo[29:3], calculated_crc
              };
              avs_subframe_bit_index <= 'd30;
              avs_mdata_o <= 1'b0;
            end
          end else if (slave_resync_pending_RS_avs_clk) begin
            avs_clk_enable <= 1'b1;
            avs_mdata_o <= 1'b1;
            pop_avs_cmd_en <= 1'b0;
          end else begin
            if (R_avs_cfg_1_F_stop_avs_clock_on_idle_RS_avs_clk) begin
              avs_clk_enable <= 1'b0;
            end else begin
              avs_clk_enable <= 1'b1;
            end
            pop_avs_cmd_en <= 1'b0;
            avs_mdata_o <= 1'b1;
          end
          slave_resync_counter <= '0;
        end
        AVS_LAUNCH_FRAME_POST_RESYNC: begin
          // launch frame:
          avs_retry_countdown <= R_avs_cfg_0_F_max_retries_RS_avs_clk;
          pop_avs_cmd_en <= 1'b1;
          avs_mdata_transmit_frame <= {
            MasterSubframePreamble, avs_cmd_from_fifo[29:3], calculated_crc
          };
          avs_subframe_bit_index <= 'd30;
          avs_mdata_o <= 1'b0;
          slave_resync_counter <= '0;
        end
        AVS_SHIFT_1ST_SUBFRAME: begin
          pop_avs_cmd_en <= 1'b0;
          avs_mdata_o <= avs_mdata_transmit_frame[avs_subframe_bit_index];
          avs_subframe_bit_index <= avs_subframe_bit_index - 1;
        end
        AVS_END_1ST_SUBFRAME: begin
          avs_mdata_prev_transmit_frame <= avs_mdata_transmit_frame;
          avs_subframe_bit_index <= 'd30;
          if (fifos_ready_to_launch_frame) begin
            pop_avs_cmd_en <= 1'b1;
            avs_mdata_transmit_frame <= {
              MasterSubframePreamble, avs_cmd_from_fifo[29:3], calculated_crc
            };
            avs_mdata_o <= 1'b0;
          end else begin
            pop_avs_cmd_en <= 1'b0;
            avs_mdata_o <= 1'b1;
          end
        end
        AVS_SHIFT_MID_SUBFRAME: begin
          pop_avs_cmd_en <= 1'b0;
          avs_mdata_o <= avs_mdata_transmit_frame[avs_subframe_bit_index];
          avs_subframe_bit_index <= avs_subframe_bit_index - 1;
        end
        AVS_END_MID_SUBFRAME: begin
          avs_mdata_prev_transmit_frame <= avs_mdata_transmit_frame;
          avs_subframe_bit_index <= 'd30;
          if (avs_retry_condition_detected && R_avs_cfg_0_F_max_retries_RS_avs_clk > 0) begin
            // Slave retry condition: retry previous frame:
            pop_avs_cmd_en <= 1'b0;
            avs_retry_countdown <= R_avs_cfg_0_F_max_retries_RS_avs_clk - 1;
            avs_mdata_transmit_frame <= avs_mdata_prev_transmit_frame;
            avs_mdata_o <= avs_mdata_prev_transmit_frame[31];
          end else if (fifos_ready_to_launch_frame) begin
            // Start next master subframe if there are more commands in cmd fifo:
            avs_mdata_transmit_frame <= {
              MasterSubframePreamble, avs_cmd_from_fifo[29:3], calculated_crc
            };
            avs_mdata_o <= 1'b0;
            pop_avs_cmd_en <= 1'b1;
          end else begin
            // No more commands to launch => Drive 1 on bus for IDLE:
            avs_mdata_o <= 1'b1;
            pop_avs_cmd_en <= 1'b0;
          end
        end
        AVS_SHIFT_LAST_SUBFRAME: begin
          pop_avs_cmd_en <= 1'b0;
          avs_mdata_o <= 1'b1;
          avs_subframe_bit_index <= avs_subframe_bit_index - 1;
        end
        AVS_END_LAST_SUBFRAME: begin
          avs_subframe_bit_index <= 'd30;
          if (avs_retry_condition_detected && R_avs_cfg_0_F_max_retries_RS_avs_clk > 0) begin
            // Slave retry condition: retry previous frame:
            pop_avs_cmd_en <= 1'b0;
            avs_retry_countdown <= R_avs_cfg_0_F_max_retries_RS_avs_clk - 1;
            avs_mdata_transmit_frame <= avs_mdata_prev_transmit_frame;
            avs_mdata_o <= avs_mdata_prev_transmit_frame[31];
          end else if (fifos_ready_to_launch_frame) begin
            avs_mdata_transmit_frame <= {
              MasterSubframePreamble, avs_cmd_from_fifo[29:3], calculated_crc
            };
            avs_mdata_o <= 1'b0;
            pop_avs_cmd_en <= 1'b1;
          end else begin
            // No more commands to launch => Drive 1 on bus for IDLE:
            avs_mdata_o <= 1'b1;
            pop_avs_cmd_en <= 1'b0;
          end
        end
        AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME: begin
          pop_avs_cmd_en <= 1'b0;
          avs_mdata_o <= avs_mdata_transmit_frame[avs_subframe_bit_index];
          avs_subframe_bit_index <= avs_subframe_bit_index - 1;
        end
        AVS_RETRY_END_XMIT_AND_RECV_SUBFRAME: begin
          pop_avs_cmd_en <= 1'b0;
          avs_subframe_bit_index <= 'd30;
          avs_got_pending_sdata_from_after_retry_frame <= 1'b1;
          avs_previous_sdata_capture <= avs_sdata_capture;
          avs_mdata_o <= 1'b1;
        end
        AVS_RETRY_SHIFT_XMIT_SUBFRAME: begin
          pop_avs_cmd_en <= 1'b0;
          avs_mdata_o <= avs_mdata_transmit_frame[avs_subframe_bit_index];
          avs_subframe_bit_index <= avs_subframe_bit_index - 1;
        end
        AVS_RETRY_END_XMIT_SUBFRAME: begin
          pop_avs_cmd_en <= 1'b0;
          avs_mdata_o <= 1'b1;
          avs_subframe_bit_index <= 'd30;
        end
        AVS_RETRY_SHIFT_RECV_SUBFRAME: begin
          pop_avs_cmd_en <= 1'b0;
          avs_mdata_o <= 1'b1;
          avs_subframe_bit_index <= avs_subframe_bit_index - 1;
        end
        AVS_RETRY_END_RECV_SUBFRAME: begin
          avs_subframe_bit_index <= 'd30;
          if (avs_retry_condition_detected && avs_retry_countdown > 0) begin
            // Slave retry condition: retry previous frame:
            avs_retry_countdown <= avs_retry_countdown - 1;
            // Retrying same frame again, so no need to update avs_mdata_transmit_frame:
            avs_mdata_o <= avs_mdata_transmit_frame[31];
            pop_avs_cmd_en <= 1'b0;
          end else begin
            // Reset retry counter on completion of successful slave transfer:
            avs_retry_countdown <= R_avs_cfg_0_F_max_retries_RS_avs_clk;
            // No more commands available to launch => go to IDLE:
            avs_mdata_o <= 1'b1;
            pop_avs_cmd_en <= 1'b0;
          end
        end
        AVS_PROCESS_PREVIOUS_SDATA: begin
          avs_subframe_bit_index <= 'd30;
          avs_got_pending_sdata_from_after_retry_frame <= 1'b0;
          if (avs_retry_condition_detected && R_avs_cfg_0_F_max_retries_RS_avs_clk > 0) begin
            avs_retry_countdown <= R_avs_cfg_0_F_max_retries_RS_avs_clk - 1;
            avs_mdata_o <= avs_mdata_prev_transmit_frame[31];
            avs_mdata_transmit_frame <= avs_mdata_prev_transmit_frame;
            pop_avs_cmd_en <= 1'b0;
          end else begin
            // Reset retry counter on completion of successful slave transfer:
            avs_retry_countdown <= R_avs_cfg_0_F_max_retries_RS_avs_clk;
            // No more commands available to launch => go to IDLE:
            avs_mdata_o <= 1'b1;
            pop_avs_cmd_en <= 1'b0;
          end
        end
        default: begin
        end
      endcase
    end
  end

  // Slave data is captured on negative edge:
  always_ff @(negedge avs_clk) begin
    if (cur_state == AVS_RESET) begin
      avs_sdata_capture <= '0;
    end else if (cur_state == AVS_PROCESS_PREVIOUS_SDATA) begin
      avs_sdata_capture <= avs_previous_sdata_capture;
    end else if (cur_state != AVS_SLAVE_RESYNC && cur_state != AVS_LAUNCH_FRAME_POST_RESYNC && cur_state != AVS_IDLE) begin
      avs_sdata_capture <= {avs_sdata_capture[30:0], avs_sdata_i};
    end
  end



  /***********************************************************************/
  /*                                                                     */
  /*                         SECTION: SLAVE RESYNC MONITORING            */
  /*                                                                     */
  /***********************************************************************/

  always_ff @(posedge clk_reg_i) begin
    if (~reset_n_apb_clk_syncd) begin
      clock_cycles_since_last_resync <= '0;
    end else if (cur_state_RS_apb_clk == AVS_SLAVE_RESYNC) begin
      clock_cycles_since_last_resync <= '0;
    end else if (clock_cycles_since_last_resync < R_avs_cfg_0_F_resync_interval) begin
      clock_cycles_since_last_resync <= clock_cycles_since_last_resync + 1;
    end
  end


  always_ff @(posedge clk_reg_i) begin
    if (~reset_n_apb_clk_syncd) begin
      slave_resync_pending <= 1'b0;
    end else if (cur_state_RS_apb_clk == AVS_SLAVE_RESYNC) begin
      slave_resync_pending <= '0;
    end else if (clock_cycles_since_last_resync >= R_avs_cfg_0_F_resync_interval || R_avs_cfg_1_F_force_slave_resync_operation == 1) begin
      slave_resync_pending <= 1'b1;
    end
  end



  /***********************************************************************/
  /*                                                                     */
  /*                         SECTION: CRC                                */
  /*                                                                     */
  /***********************************************************************/


  // CRC calculator and checker :
  avsbus_crc3 avs_crc3_check_inst (
    .msg_i({data_for_crc_check}),
    .crc_o(),
    .check_good_o(crc_check_good)
  );

  avsbus_crc3 avs_crc3_generate_inst (
    .msg_i({data_for_crc_calc}),
    .crc_o(calculated_crc),
    .check_good_o()
  );


  /***********************************************************************/
  /*                                                                     */
  /*                         SECTION: REGISTER BLOCK                     */
  /*                                                                     */
  /***********************************************************************/

  avsbus_controller_reg_pkg::avsbus_controller__in_t hwif_in;
  avsbus_controller_reg_pkg::avsbus_controller__out_t hwif_out;

  // Reg block :
  logic reg_pslverr;
  avsbus_controller_reg avsbus_controller_reg_inst (
    .clk(clk_reg_i),
    .arst_n(reset_n_apb_clk_syncd),

    .s_apb_psel     (psel),
    .s_apb_penable  (penable),
    .s_apb_pwrite   (pwrite),
    .s_apb_pprot    (pprot),
    .s_apb_paddr    (paddr[
                            avsbus_controller_reg_pkg::AVSBUS_CONTROLLER_REG_MIN_ADDR_WIDTH-1:0
                        ]),
    .s_apb_pwdata   (pwdata),
    .s_apb_pstrb    (pstrb),
    .s_apb_pready   (pready),
    .s_apb_prdata   (prdata),
    .s_apb_pslverr  (reg_pslverr),

    .hwif_in(hwif_in),
    .hwif_out(hwif_out)
  );

  assign avs_gpio_enable_o = hwif_out.AVS_CONFIG.AVS_GPIO_ENABLE.value;

  assign hwif_in.AVS_NORMAL_STATUS.READBACK_HAS_DATA.next = R_avs_normal_status_F_readback_has_data;

  assign hwif_in.AVS_DEBUG_READBACK.AVS_SLAVE_SUBFRAME.next = R_avs_debug_readback_F_avs_slave_subframe;

  assign hwif_in.AVS_LATEST_SLAVE_SUBFRAME.AVS_SLAVE_SUBFRAME.next = R_avs_latest_slave_subframe_F_avs_slave_subframe_RS_apb_clk;

  assign hwif_in.AVS_INTERRUPT.MAX_RETRIES_ATTEMPTED_INT.next = R_avs_interrupt_F_max_retries_attempted_int;
  assign hwif_in.AVS_INTERRUPT.SLAVE_UNRESPONSIVE_INT.next = R_avs_interrupt_F_slave_unresponsive_int;

  assign hwif_in.AVS_NORMAL_STATUS.TOTAL_RETRIES.next = R_avs_normal_status_F_total_retries;
  assign hwif_in.AVS_NORMAL_STATUS.READBACK_FIFO_FULL.next = R_avs_normal_status_F_readback_fifo_full;
  assign hwif_in.AVS_NORMAL_STATUS.CMD_FIFO_FULL.next = R_avs_normal_status_F_cmd_fifo_full;
  assign hwif_in.AVS_NORMAL_STATUS.CMD_FIFO_EMPTY.next = R_avs_normal_status_F_cmd_fifo_empty;
  // Decoded from the APB-domain resynchronized FSM state (u_cur_state_resync)
  // rather than raw cur_state: these CSR fields are storageless passthrough
  // reads, so the decode must not sample avs_clk-domain state directly.
  assign hwif_in.AVS_NORMAL_STATUS.AVS_MASTER_IS_RETRYING.next =
      cur_state_RS_apb_clk inside {AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME,
                                   AVS_RETRY_END_XMIT_AND_RECV_SUBFRAME,
                                   AVS_RETRY_SHIFT_XMIT_SUBFRAME,
                                   AVS_RETRY_END_XMIT_SUBFRAME,
                                   AVS_RETRY_SHIFT_RECV_SUBFRAME,
                                   AVS_RETRY_END_RECV_SUBFRAME};
  assign hwif_in.AVS_NORMAL_STATUS.AVS_BUS_IS_IDLE.next = (cur_state_RS_apb_clk == AVS_IDLE);
  assign hwif_in.AVS_NORMAL_STATUS.AVS_SLAVE_IS_IN_RESYNC.next = (cur_state_RS_apb_clk == AVS_SLAVE_RESYNC);

  assign hwif_in.AVS_SLAVE_STATUS.AVS_SLAVE_ACK.next    = R_avs_slave_status_F_avs_slave_ack_RS_apb_clk;
  assign hwif_in.AVS_SLAVE_STATUS.AVS_SLAVE_STATUS_RESPONSE.next    = R_avs_slave_status_F_avs_slave_status_response_RS_apb_clk;

  assign hwif_in.AVS_FIFOS_STATUS.READBACK_FIFO_VACANT_SLOTS.next   = R_avs_fifos_status_F_readback_fifo_vacant_slots;
  assign hwif_in.AVS_FIFOS_STATUS.READBACK_FIFO_OCCUPIED_SLOTS.next = R_avs_fifos_status_F_readback_fifo_occupied_slots;
  assign hwif_in.AVS_FIFOS_STATUS.CMD_FIFO_VACANT_SLOTS.next        = R_avs_fifos_status_F_cmd_fifo_vacant_slots;
  assign hwif_in.AVS_FIFOS_STATUS.CMD_FIFO_OCCUPIED_SLOTS.next      = R_avs_fifos_status_F_cmd_fifo_occupied_slots;

  assign hwif_in.AVS_INTERRUPT.READBACK_OVERFLOW_INT.next           = R_avs_interrupt_F_readback_overflow_int;
  assign hwif_in.AVS_INTERRUPT.READBACK_UNDERFLOW_INT.next          = R_avs_interrupt_F_readback_underflow_int;
  assign hwif_in.AVS_INTERRUPT.CMD_FIFO_OVERFLOW_INT.next           = R_avs_interrupt_F_cmd_fifo_overflow_int;
  assign hwif_in.AVS_INTERRUPT.READBACK_HAS_DATA_INT.next           = R_avs_interrupt_F_readback_has_data_int;
  assign hwif_in.AVS_INTERRUPT.READBACK_FIFO_FULL_INT.next          = R_avs_interrupt_F_readback_fifo_full_int;
  assign hwif_in.AVS_INTERRUPT.CMD_FIFO_FULL_INT.next               = R_avs_interrupt_F_cmd_fifo_full_int;
  assign hwif_in.AVS_INTERRUPT.AVS_SLAVE_ISSUED_INTERRUPT.next      = R_avs_interrupt_F_avs_slave_issued_interrupt;

  assign R_avs_interrupt_mask_F_disable_readback_overflow_int = hwif_out.AVS_INTERRUPT_MASK.DISABLE_READBACK_OVERFLOW_INT.value;
  assign R_avs_interrupt_mask_F_disable_readback_underflow_int = hwif_out.AVS_INTERRUPT_MASK.DISABLE_READBACK_UNDERFLOW_INT.value;
  assign R_avs_interrupt_mask_F_disable_cmd_fifo_overflow_int = hwif_out.AVS_INTERRUPT_MASK.DISABLE_CMD_FIFO_OVERFLOW_INT.value;
  assign R_avs_interrupt_mask_F_disable_max_retries_attempted_int = hwif_out.AVS_INTERRUPT_MASK.DISABLE_MAX_RETRIES_ATTEMPTED_INT.value;
  assign R_avs_interrupt_mask_F_disable_slave_unresponsive_int = hwif_out.AVS_INTERRUPT_MASK.DISABLE_SLAVE_UNRESPONSIVE_INT.value;
  assign R_avs_interrupt_mask_F_disable_readback_has_data_int = hwif_out.AVS_INTERRUPT_MASK.DISABLE_READBACK_HAS_DATA_INT.value;
  assign R_avs_interrupt_mask_F_disable_readback_fifo_full_int = hwif_out.AVS_INTERRUPT_MASK.DISABLE_READBACK_FIFO_FULL_INT.value;
  assign R_avs_interrupt_mask_F_disable_cmd_fifo_full_int = hwif_out.AVS_INTERRUPT_MASK.DISABLE_CMD_FIFO_FULL_INT.value;
  assign R_avs_interrupt_mask_F_disable_avs_slave_issued_interrupt = hwif_out.AVS_INTERRUPT_MASK.DISABLE_AVS_SLAVE_ISSUED_INTERRUPT.value;

  assign R_avs_interrupt_clear_F_clear_readback_overflow_int = hwif_out.AVS_INTERRUPT_CLEAR.CLEAR_READBACK_OVERFLOW_INT.value;
  assign R_avs_interrupt_clear_F_clear_readback_underflow_int = hwif_out.AVS_INTERRUPT_CLEAR.CLEAR_READBACK_UNDERFLOW_INT.value;
  assign R_avs_interrupt_clear_F_clear_cmd_fifo_overflow_int = hwif_out.AVS_INTERRUPT_CLEAR.CLEAR_CMD_FIFO_OVERFLOW_INT.value;
  assign R_avs_interrupt_clear_F_clear_max_retries_attempted_int = hwif_out.AVS_INTERRUPT_CLEAR.CLEAR_MAX_RETRIES_ATTEMPTED_INT.value;
  assign R_avs_interrupt_clear_F_clear_slave_unresponsive_int = hwif_out.AVS_INTERRUPT_CLEAR.CLEAR_SLAVE_UNRESPONSIVE_INT.value;
  assign R_avs_interrupt_clear_F_clear_readback_has_data_int = hwif_out.AVS_INTERRUPT_CLEAR.CLEAR_READBACK_HAS_DATA_INT.value;
  assign R_avs_interrupt_clear_F_clear_readback_fifo_full_int = hwif_out.AVS_INTERRUPT_CLEAR.CLEAR_READBACK_FIFO_FULL_INT.value;
  assign R_avs_interrupt_clear_F_clear_cmd_fifo_full_int = hwif_out.AVS_INTERRUPT_CLEAR.CLEAR_CMD_FIFO_FULL_INT.value;
  assign R_avs_interrupt_clear_F_clear_avs_slave_issued_interrupt = hwif_out.AVS_INTERRUPT_CLEAR.CLEAR_AVS_SLAVE_ISSUED_INTERRUPT.value;

  assign R_avs_cfg_0_F_max_retries = hwif_out.AVS_CFG_0.MAX_RETRIES.value;
  assign R_avs_cfg_0_F_resync_interval = hwif_out.AVS_CFG_0.RESYNC_INTERVAL.value;

  assign R_avs_cfg_1_F_clk_divider_value = hwif_out.AVS_CFG_1.CLK_DIVIDER_VALUE.value;
  assign R_avs_cfg_1_F_clk_divider_duty_cycle_numerator = hwif_out.AVS_CFG_1.CLK_DIVIDER_DUTY_CYCLE_NUMERATOR.value;
  assign R_avs_cfg_1_F_stop_avs_clock_on_idle = hwif_out.AVS_CFG_1.STOP_AVS_CLOCK_ON_IDLE.value;
  assign R_avs_cfg_1_F_turn_off_all_premux_clocks = hwif_out.AVS_CFG_1.TURN_OFF_ALL_PREMUX_CLOCKS.value;
  assign R_avs_cfg_1_F_force_slave_resync_operation = hwif_out.AVS_CFG_1.FORCE_SLAVE_RESYNC_OPERATION.value;
  assign R_avs_cfg_1_F_avs_clock_select = hwif_out.AVS_CFG_1.AVS_CLOCK_SELECT.value;

  assign external_reg_wr_data = hwif_out.AVS_CMD.wr_data;

  assign R_avs_cmd_wr_en = hwif_out.AVS_CMD.req && hwif_out.AVS_CMD.req_is_wr;
  assign hwif_in.AVS_CMD.wr_ack = R_avs_cmd_wr_en;
  assign R_avs_readback_rd_en = hwif_out.AVS_READBACK.req && !hwif_out.AVS_READBACK.req_is_wr;
  assign hwif_in.AVS_READBACK.rd_data = apb_readback_from_fifo;
  assign hwif_in.AVS_READBACK.rd_ack = R_avs_readback_rd_en;


  /***********************************************************************/
  /*                                                                     */
  /*                         SECTION: FIFOS                              */
  /*                                                                     */
  /***********************************************************************/

  // Command FIFO:
  avsbus_async_fifo #(
    .DEPTH(COMMAND_FIFO_DEPTH),
    .WIDTH(32)
  ) cmd_async_fifo_inst (
    .scan_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),

    .rst_wr_clk_syncd_ni(reset_n_apb_clk_syncd),
    .wr_clk_i(clk_reg_i),
    .wr_en_i(push_avs_cmd_en),
    .wr_data_i(pwdata),
    .wr_full_o(R_avs_normal_status_F_cmd_fifo_full),
    .wr_empty_o(R_avs_normal_status_F_cmd_fifo_empty),

    .rst_rd_clk_syncd_ni(reset_n_avs_clk_syncd),
    .rd_clk_i(avs_clk),
    .rd_en_i(pop_avs_cmd_en),
    .rd_data_o(avs_cmd_from_fifo),
    .rd_empty_o(avs_cmd_buf_empty),
    .vacant_slots_o(R_avs_fifos_status_F_cmd_fifo_vacant_slots),
    .full_slots_o(R_avs_fifos_status_F_cmd_fifo_occupied_slots)
  );


  logic [31:0] avs_fifo_data;
  // Readback FIFO:
  avsbus_async_fifo #(
    .DEPTH(READBACK_FIFO_DEPTH),
    .WIDTH(32)
  ) readasync_back_fifo_inst (
    .scan_rst_ni(scan_rst_ni),
    .test_mode_i(test_en_i),

    .rst_wr_clk_syncd_ni(reset_n_avs_clk_syncd),
    .wr_clk_i(avs_clk),
    .wr_en_i(push_avs_readback_en),
    .wr_data_i(avs_sdata_capture),
    .wr_full_o(R_avs_normal_status_F_readback_fifo_full_AVSCLK),
    .wr_empty_o(),

    .rst_rd_clk_syncd_ni(reset_n_apb_clk_syncd),
    .rd_clk_i(clk_reg_i),
    .rd_en_i(pop_apb_readback_en),
    .rd_data_o(avs_fifo_data),
    .rd_empty_o(apb_readback_buf_empty),
    .vacant_slots_o(R_avs_fifos_status_F_readback_fifo_vacant_slots_AVSCLK),
    .full_slots_o(R_avs_fifos_status_F_readback_fifo_occupied_slots_AVSCLK)
  );

  assign apb_readback_from_fifo = apb_readback_buf_empty ? 32'h0 : avs_fifo_data;

  /***********************************************************************/
  /*                                                                     */
  /*                  SECTION: STATUS REGS AND INTERRUPTS                */
  /*                                                                     */
  /***********************************************************************/


  // Register status bits:
  // Slave StatusResponse bits:
  always_ff @(posedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) begin
      R_avs_latest_slave_subframe_F_avs_slave_subframe <= '0;
      R_avs_slave_status_F_avs_slave_ack <= '0;
      R_avs_slave_status_F_avs_slave_status_response <= '0;
    end else if (  (cur_state inside {AVS_END_1ST_SUBFRAME, AVS_END_MID_SUBFRAME,  AVS_END_LAST_SUBFRAME, AVS_RETRY_END_XMIT_AND_RECV_SUBFRAME, AVS_RETRY_END_RECV_SUBFRAME}) &
                    ~avs_sdata_capture[SdataValidFrameBit] & crc_check_good)
   begin
      R_avs_latest_slave_subframe_F_avs_slave_subframe <= avs_sdata_capture;
      R_avs_slave_status_F_avs_slave_ack <= avs_sdata_capture[31:30];
      R_avs_slave_status_F_avs_slave_status_response <= avs_sdata_capture[28:24];
    end
  end


  // This should maybe be done on apb_clk instead, but then have to pass a bunch of
  // vectors from avs_clk to apb_clk.... on avs_clk, just need to resync a high-speed
  // pulse....
  always_ff @(posedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) begin
      R_avs_interrupt_F_slave_unresponsive_int_AVSCLK <= 1'b0;
    end else if ((cur_state == AVS_END_MID_SUBFRAME ||
                cur_state == AVS_END_LAST_SUBFRAME ||
                cur_state == AVS_RETRY_END_XMIT_AND_RECV_SUBFRAME ||
                cur_state == AVS_RETRY_END_RECV_SUBFRAME ) && avs_sdata_capture[SdataValidFrameBit]
                ) begin
      R_avs_interrupt_F_slave_unresponsive_int_AVSCLK <= 1'b1;
    end else if (R_avs_interrupt_clear_F_clear_slave_unresponsive_int_RS_avs_clk) begin
      R_avs_interrupt_F_slave_unresponsive_int_AVSCLK <= 1'b0;
    end
  end

  // Detect slave interrupt:
  // This should maybe be done on apb_clk instead, but then have to pass a bunch of
  // vectors from avs_clk to apb_clk.... on avs_clk, just need to resync a high-speed
  // pulse....
  always_ff @(posedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) begin
      R_avs_interrupt_F_avs_slave_issued_interrupt_AVSCLK <= 1'b0;
      // These are states where the slave device has the opportunity to signal an interrupt:
    end else if ((
                    (cur_state == AVS_END_1ST_SUBFRAME ||
                     cur_state == AVS_RETRY_END_XMIT_SUBFRAME) &&
                     avs_sdata_capture[31:30] == 2'b00
                ) || (
                    (cur_state == AVS_IDLE ||
                     cur_state == AVS_SLAVE_RESYNC ||
                     cur_state == AVS_LAUNCH_FRAME_POST_RESYNC) && avs_sdata_interrupt_detect == 2'b00
               ))
   begin
      R_avs_interrupt_F_avs_slave_issued_interrupt_AVSCLK <= 1'b1;
    end else if (R_avs_interrupt_clear_F_clear_avs_slave_issued_interrupt_RS_avs_clk) begin
      R_avs_interrupt_F_avs_slave_issued_interrupt_AVSCLK <= 1'b0;
    end
  end


  always_ff @(posedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) begin
      R_avs_normal_status_F_total_retries_AVSCLK <= '0;
    end else if (cur_state == AVS_RETRY_END_RECV_SUBFRAME) begin
      R_avs_normal_status_F_total_retries_AVSCLK <= R_avs_normal_status_F_total_retries_AVSCLK + 1;
    end
  end


  always_ff @(posedge clk_reg_i) begin
    if (~reset_n_apb_clk_syncd) begin
      R_avs_interrupt_F_max_retries_attempted_int <= 1'b0;
    end else if (avs_max_retries_attempted_RS_apb_clk) begin
      R_avs_interrupt_F_max_retries_attempted_int <= 1'b1;
    end else if (R_avs_interrupt_clear_F_clear_max_retries_attempted_int) begin
      R_avs_interrupt_F_max_retries_attempted_int <= 1'b0;
    end
  end


  always_ff @(posedge clk_reg_i) begin
    if (~reset_n_apb_clk_syncd) begin
      R_avs_interrupt_F_readback_overflow_int <= 1'b0;
    end else if (push_avs_readback_en_RS_apb_clk & R_avs_normal_status_F_readback_fifo_full) begin
      R_avs_interrupt_F_readback_overflow_int <= 1'b1;
    end else if (R_avs_interrupt_clear_F_clear_readback_overflow_int) begin
      R_avs_interrupt_F_readback_overflow_int <= 1'b0;
    end
  end

  always_ff @(posedge clk_reg_i) begin
    if (~reset_n_apb_clk_syncd) begin
      R_avs_interrupt_F_readback_underflow_int <= 1'b0;
    end else if (apb_waiting_for_readback_data & apb_readback_buf_empty) begin
      R_avs_interrupt_F_readback_underflow_int <= 1'b1;
    end else if (R_avs_interrupt_clear_F_clear_readback_underflow_int) begin
      R_avs_interrupt_F_readback_underflow_int <= 1'b0;
    end
  end

  always_ff @(posedge clk_reg_i) begin
    if (~reset_n_apb_clk_syncd) begin
      R_avs_interrupt_F_cmd_fifo_overflow_int <= 1'b0;
    end else if (apb_cmd_buffer_wrdata_ready_to_sample & R_avs_normal_status_F_cmd_fifo_full) begin
      R_avs_interrupt_F_cmd_fifo_overflow_int <= 1'b1;
    end else if (R_avs_interrupt_clear_F_clear_cmd_fifo_overflow_int) begin
      R_avs_interrupt_F_cmd_fifo_overflow_int <= 1'b0;
    end
  end

  always_ff @(posedge clk_reg_i) begin
    if (~reset_n_apb_clk_syncd) begin
      R_avs_interrupt_F_readback_has_data_int <= 1'b0;
    end else if (R_avs_normal_status_F_readback_has_data) begin
      R_avs_interrupt_F_readback_has_data_int <= 1'b1;
    end else if (R_avs_interrupt_clear_F_clear_readback_has_data_int) begin
      R_avs_interrupt_F_readback_has_data_int <= 1'b0;
    end
  end

  always_ff @(posedge clk_reg_i) begin
    if (~reset_n_apb_clk_syncd) begin
      R_avs_interrupt_F_readback_fifo_full_int <= 1'b0;
    end else if (R_avs_normal_status_F_readback_fifo_full) begin
      R_avs_interrupt_F_readback_fifo_full_int <= 1'b1;
    end else if (R_avs_interrupt_clear_F_clear_readback_fifo_full_int) begin
      R_avs_interrupt_F_readback_fifo_full_int <= 1'b0;
    end
  end

  always_ff @(posedge clk_reg_i) begin
    if (~reset_n_apb_clk_syncd) begin
      R_avs_interrupt_F_cmd_fifo_full_int <= 1'b0;
    end else if (R_avs_normal_status_F_cmd_fifo_full) begin
      R_avs_interrupt_F_cmd_fifo_full_int <= 1'b1;
    end else if (R_avs_interrupt_clear_F_clear_cmd_fifo_full_int) begin
      R_avs_interrupt_F_cmd_fifo_full_int <= 1'b0;
    end
  end


  // To detect 2 back-to-back '0' bits from slave during IDLE or RESYNC, indicating
  // an interrupt:
  always_ff @(negedge avs_clk) begin
    if (~reset_n_avs_clk_syncd) begin
      avs_sdata_interrupt_detect <= 2'b11;
    end else if (cur_state == AVS_IDLE ||
                cur_state == AVS_SLAVE_RESYNC ||
                cur_state == AVS_LAUNCH_FRAME_POST_RESYNC) begin
      avs_sdata_interrupt_detect <= {avs_sdata_interrupt_detect[0], avs_sdata_i};
    end else if (R_avs_interrupt_F_avs_slave_issued_interrupt_AVSCLK) begin
      // Reset once an interrupt has been detected:
      avs_sdata_interrupt_detect <= 2'b11;
    end
  end


  // Interrupt pin:
  assign interrupt_o = (R_avs_interrupt_F_readback_overflow_int        & ~R_avs_interrupt_mask_F_disable_readback_overflow_int      ) ||
               (R_avs_interrupt_F_readback_underflow_int       & ~R_avs_interrupt_mask_F_disable_readback_underflow_int     ) ||
               (R_avs_interrupt_F_cmd_fifo_overflow_int        & ~R_avs_interrupt_mask_F_disable_cmd_fifo_overflow_int      ) ||
               (R_avs_interrupt_F_readback_has_data_int        & ~R_avs_interrupt_mask_F_disable_readback_has_data_int      ) ||
               (R_avs_interrupt_F_readback_fifo_full_int       & ~R_avs_interrupt_mask_F_disable_readback_fifo_full_int     ) ||
               (R_avs_interrupt_F_cmd_fifo_full_int            & ~R_avs_interrupt_mask_F_disable_cmd_fifo_full_int          ) ||
               (R_avs_interrupt_F_max_retries_attempted_int    & ~R_avs_interrupt_mask_F_disable_max_retries_attempted_int  ) ||
               (R_avs_interrupt_F_slave_unresponsive_int       & ~R_avs_interrupt_mask_F_disable_slave_unresponsive_int     ) ||
               (R_avs_interrupt_F_avs_slave_issued_interrupt   & ~R_avs_interrupt_mask_F_disable_avs_slave_issued_interrupt ) ;





  /***********************************************************************/
  /*                                                                     */
  /*                   SECTION: COMBINATIONAL GLUE LOGIC                 */
  /*                                                                     */
  /***********************************************************************/


  // AVS intermediate signals:
  assign fifos_ready_to_launch_frame = ~R_avs_normal_status_F_readback_fifo_full_AVSCLK &
                                     ~avs_cmd_buf_empty &
                                     ~(push_avs_readback_en & R_avs_fifos_status_F_readback_fifo_vacant_slots_AVSCLK  < 2) &
                                     ~slave_resync_pending_RS_avs_clk;

  // push_avs_readback_en == 1
  assign fifos_ready_to_launch_frame_rb_en   = ~R_avs_normal_status_F_readback_fifo_full_AVSCLK &
                                               ~avs_cmd_buf_empty &
                                               ~(R_avs_fifos_status_F_readback_fifo_vacant_slots_AVSCLK < 2) &
                                               ~slave_resync_pending_RS_avs_clk;

  // push_avs_readback_en == 0
  assign fifos_ready_to_launch_frame_rb_en_b = ~R_avs_normal_status_F_readback_fifo_full_AVSCLK &
                                               ~avs_cmd_buf_empty &
                                               ~slave_resync_pending_RS_avs_clk;

  assign R_avs_normal_status_F_readback_has_data = ~apb_readback_buf_empty;
  assign R_avs_debug_readback_F_avs_slave_subframe = apb_readback_buf_empty ? 32'hFFFFFFFF : apb_readback_from_fifo ;


  always_comb begin
    if (cur_state == AVS_END_MID_SUBFRAME ||
        cur_state == AVS_END_LAST_SUBFRAME ||
        cur_state == AVS_RETRY_END_RECV_SUBFRAME ||
        cur_state == AVS_PROCESS_PREVIOUS_SDATA )
    begin
      avs_retry_condition_detected = ~crc_check_good ||
                                      slave_ack == SlaveAckResourceUnavailable ||
                                      slave_ack == SlaveAckBadCRC ||
                                      avs_sdata_capture[SdataValidFrameBit] == 1'b1 ;
    end else begin
      avs_retry_condition_detected = 1'b0;
    end
  end


  // APB glue logic:
  logic access_error;
  always_comb begin
    if (psel & penable) begin
      access_error = (pwrite & R_avs_normal_status_F_cmd_fifo_full & R_avs_cmd_wr_en) || (~pwrite & apb_readback_buf_empty & R_avs_readback_rd_en) ;
    end else begin
      access_error = 1'b0;
    end
  end

  assign pslverr = access_error | reg_pslverr;

  assign apb_cmd_buffer_wrdata_ready_to_sample = R_avs_cmd_wr_en;
  assign apb_waiting_for_readback_data = R_avs_readback_rd_en;

  // set cmd_fifo write enable & readback_fifo read enable:
  assign push_avs_cmd_en = apb_cmd_buffer_wrdata_ready_to_sample & ~R_avs_normal_status_F_cmd_fifo_full ;
  assign pop_apb_readback_en = apb_waiting_for_readback_data & ~apb_readback_buf_empty;



endmodule
`end_keywords
