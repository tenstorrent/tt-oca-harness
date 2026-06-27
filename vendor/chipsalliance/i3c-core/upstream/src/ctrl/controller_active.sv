// SPDX-License-Identifier: Apache-2.0

module controller_active
    import controller_pkg::*;
    import i3c_pkg::*;
    #(
        parameter int unsigned HciRespFifoDepth = 64,
        parameter int unsigned HciCmdFifoDepth  = 64,
        parameter int unsigned HciRxFifoDepth   = 64,
        parameter int unsigned HciTxFifoDepth   = 64,
        parameter int unsigned HciIbiFifoDepth  = 64,

        localparam int unsigned HciRespFifoDepthWidth = $clog2(HciRespFifoDepth + 1),
        localparam int unsigned HciCmdFifoDepthWidth  = $clog2(HciCmdFifoDepth + 1),
        localparam int unsigned HciTxFifoDepthWidth   = $clog2(HciTxFifoDepth + 1),
        localparam int unsigned HciRxFifoDepthWidth   = $clog2(HciRxFifoDepth + 1),
        localparam int unsigned HciIbiFifoDepthWidth  = $clog2(HciIbiFifoDepth + 1),

        parameter int unsigned HciRespDataWidth = 32,
        parameter int unsigned HciCmdDataWidth  = 64,
        parameter int unsigned HciRxDataWidth   = 32,
        parameter int unsigned HciTxDataWidth   = 32,
        parameter int unsigned HciIbiDataWidth  = 32,

        parameter int unsigned HciRespThldWidth = 8,
        parameter int unsigned HciCmdThldWidth  = 8,
        parameter int unsigned HciRxThldWidth   = 3,
        parameter int unsigned HciTxThldWidth   = 3,
        parameter int unsigned HciIbiThldWidth  = 8
    ) (
        input logic clk_i,
        input logic rst_ni,

        // Interface to SDA/SCL
        input bus_state_t ctrl_bus_i[2],
        output logic ctrl_scl_o[2],
        output logic ctrl_sda_o[2],
        output logic phy_sel_od_pp_o[2],

        // HCI queues
        // Command FIFO
        input logic cmd_queue_full_i,
        input logic [HciCmdFifoDepthWidth-1:0] cmd_queue_depth_i,
        input logic [HciCmdThldWidth-1:0] cmd_queue_ready_thld_i,
        input logic cmd_queue_ready_thld_trig_i,
        input logic cmd_queue_empty_i,
        input logic cmd_queue_rvalid_i,
        output logic cmd_queue_rready_o,
        input logic [HciCmdDataWidth-1:0] cmd_queue_rdata_i,
        // RX FIFO
        input logic rx_queue_full_i,
        input logic [HciRxFifoDepthWidth-1:0] rx_queue_depth_i,
        input logic [HciRxThldWidth-1:0] rx_queue_start_thld_i,
        input logic rx_queue_start_thld_trig_i,
        input logic [HciRxThldWidth-1:0] rx_queue_ready_thld_i,
        input logic rx_queue_ready_thld_trig_i,
        input logic rx_queue_empty_i,
        output logic rx_queue_wvalid_o,
        input logic rx_queue_wready_i,
        output logic [HciRxDataWidth-1:0] rx_queue_wdata_o,
        // TX FIFO
        input logic tx_queue_full_i,
        input logic [HciTxFifoDepthWidth-1:0] tx_queue_depth_i,
        input logic [HciTxThldWidth-1:0] tx_queue_start_thld_i,
        input logic tx_queue_start_thld_trig_i,
        input logic [HciTxThldWidth-1:0] tx_queue_ready_thld_i,
        input logic tx_queue_ready_thld_trig_i,
        input logic tx_queue_empty_i,
        input logic tx_queue_rvalid_i,
        output logic tx_queue_rready_o,
        input logic [HciTxDataWidth-1:0] tx_queue_rdata_i,
        // Response FIFO
        input logic resp_queue_full_i,
        input logic [HciRespFifoDepthWidth-1:0] resp_queue_depth_i,
        input logic [HciRespThldWidth-1:0] resp_queue_ready_thld_i,
        input logic resp_queue_ready_thld_trig_i,
        input logic resp_queue_empty_i,
        output logic resp_queue_wvalid_o,
        input logic resp_queue_wready_i,
        output logic [HciRespDataWidth-1:0] resp_queue_wdata_o,

        // In-band Interrupt queue
        input logic ibi_queue_full_i,
        input logic [HciIbiFifoDepthWidth-1:0] ibi_queue_depth_i,
        input logic [HciIbiThldWidth-1:0] ibi_queue_ready_thld_i,
        input logic ibi_queue_ready_thld_trig_i,
        input logic ibi_queue_empty_i,
        output logic ibi_queue_wvalid_o,
        input logic ibi_queue_wready_data_i,    // Ready for data writes (not full)
        output logic [HciIbiDataWidth-1:0] ibi_queue_wdata_o,
        output logic ibi_status_desc_valid_o,  // NEW: distinguishes status descriptor from data

        // DAT <-> Controller interface
        output logic                          dat_read_valid_hw_o,
        output logic [DatAw-1:0] dat_index_hw_o,
        input  logic [                  63:0] dat_rdata_hw_i,

        // DCT <-> Controller interface
        output logic                          dct_write_valid_hw_o,
        output logic                          dct_read_valid_hw_o,
        output logic [DctAw-1:0] dct_index_hw_o,
        output logic [                 127:0] dct_wdata_hw_o,
        input  logic [                 127:0] dct_rdata_hw_i,

        // TODO: rename
        input  logic i3c_fsm_en_i,
        output logic i3c_fsm_idle_o,

        // Errors
        output i3c_err_t err,
        input logic phy_en_i,
        input logic [1:0] phy_mux_select_i,
        input logic i2c_active_en_i,
        input logic i2c_standby_en_i,
        input logic i3c_active_en_i,
        input logic i3c_standby_en_i,
        input logic [19:0] t_hd_dat_i,
        input logic [19:0] t_r_i,
        input logic [19:0] t_f_i,
        input logic [19:0] t_bus_free_i,
        input logic [19:0] t_bus_idle_i,
        input logic [19:0] t_bus_available_i,

        // Additional timing inputs for I3C controller
        input logic [19:0] t_high_i,
        input logic [19:0] t_low_i,
        input logic [19:0] t_hd_sta_i,
        input logic [19:0] t_su_sta_i,
        input logic [19:0] t_su_sto_i,
        input logic [19:0] t_su_dat_i,
        // PP mode timing inputs
        input logic [19:0] t_r_pp_i,
        input logic [19:0] t_f_pp_i,
        input logic [19:0] t_high_pp_i,
        input logic [19:0] t_low_pp_i,
        input logic [19:0] t_su_pp_i,
        input logic [19:0] t_hd_pp_i,
        input logic [19:0] t_casr_i,
        input logic [19:0] t_cbsr_i

    );

    logic host_enable;
    logic fmt_fifo_rvalid;
    logic [I2CFifoDepthWidth-1:0] fmt_fifo_depth;
    logic fmt_fifo_rready;
    logic [7:0] fmt_byte;
    logic fmt_flag_start_before;
    logic fmt_flag_stop_after;
    logic fmt_flag_read_bytes;
    logic fmt_flag_read_continue;
    logic fmt_flag_nak_ok;
    logic unhandled_unexp_nak;
    logic unhandled_nak_timeout;
    logic rx_fifo_wvalid;
    logic [RxFifoWidth-1:0] rx_fifo_wdata;

    // I3C transfer mode from flow FSM
    i3c_trans_mode_e i3c_trans_mode;

    // I3C Controller interface signals
    logic        i3c_tx_valid;
    logic        i3c_tx_ready;
    logic [7:0]  i3c_tx_byte;
    start_stop_e i3c_start_stop;
    logic        i3c_tx_is_addr;
    logic        i3c_tx_use_tbit;
    logic        i3c_rx_ack;
    logic        i3c_rx_ack_valid;
    // RX interface
    logic        i3c_rx_req;
    logic        i3c_rx_valid;
    logic [7:0]  i3c_rx_byte;
    logic        i3c_rx_data_last;

    logic        ibi_detected;
    logic        ibi_mode;
    logic        ibi_address_byte;

    logic        abort_read;

    // TODO: Connect I2C Controller SDA/SCL to I3C Flow FSM

    flow_active #(
        .HciRxFifoDepth(HciRxFifoDepth),
        .HciTxFifoDepth(HciTxFifoDepth)
    ) flow_fsm (
        .clk_i,
        .rst_ni,
        .cmd_queue_full_i,
        .cmd_queue_empty_i,
        .cmd_queue_rvalid_i,
        .cmd_queue_rready_o,
        .cmd_queue_rdata_i,
        .rx_queue_full_i,
        .rx_queue_depth_i,
        .rx_queue_start_thld_trig_i,
        .rx_queue_ready_thld_trig_i,
        .rx_queue_empty_i,
        .rx_queue_wvalid_o,
        .rx_queue_wready_i,
        .rx_queue_wdata_o,
        .tx_queue_full_i,
        .tx_queue_depth_i,
        .tx_queue_start_thld_trig_i,
        .tx_queue_ready_thld_trig_i,
        .tx_queue_empty_i,
        .tx_queue_rvalid_i,
        .tx_queue_rready_o,
        .tx_queue_rdata_i,
        .resp_queue_full_i,
        .resp_queue_empty_i,
        .resp_queue_wvalid_o,
        .resp_queue_wready_i,
        .resp_queue_wdata_o,
        .ibi_queue_full_i,
        .ibi_queue_empty_i,
        .ibi_queue_wvalid_o,
        .ibi_queue_wready_data_i,
        .ibi_queue_wdata_o,
        .ibi_status_desc_valid_o,  // NEW
        .dat_read_valid_hw_o,
        .dat_index_hw_o,
        .dat_rdata_hw_i,
        .dct_write_valid_hw_o,
        .dct_read_valid_hw_o,
        .dct_index_hw_o,
        .dct_wdata_hw_o,
        .dct_rdata_hw_i,
        .host_enable_o(host_enable),
        .fmt_fifo_rvalid_o(fmt_fifo_rvalid),
        .fmt_fifo_depth_o(fmt_fifo_depth),
        .fmt_fifo_rready_i(fmt_fifo_rready),
        .fmt_byte_o(fmt_byte),
        .fmt_flag_start_before_o(fmt_flag_start_before),
        .fmt_flag_stop_after_o(fmt_flag_stop_after),
        .fmt_flag_read_bytes_o(fmt_flag_read_bytes),
        .fmt_flag_read_continue_o(fmt_flag_read_continue),
        .fmt_flag_nak_ok_o(fmt_flag_nak_ok),
        .unhandled_unexp_nak_o(unhandled_unexp_nak),
        .unhandled_nak_timeout_o(unhandled_nak_timeout),
        .rx_fifo_wvalid_i(rx_fifo_wvalid),
        .rx_fifo_wdata_i(rx_fifo_wdata),

        // I3C Controller interface
        .i3c_tx_valid_o(i3c_tx_valid),
        .i3c_tx_ready_i(i3c_tx_ready),
        .i3c_tx_byte_o(i3c_tx_byte),
        .i3c_start_stop_o(i3c_start_stop),
        .i3c_tx_is_addr_o(i3c_tx_is_addr),
        .i3c_tx_use_tbit_o(i3c_tx_use_tbit),
        .i3c_rx_ack_i(i3c_rx_ack),
        .i3c_rx_ack_valid_i(i3c_rx_ack_valid),
        .i3c_rx_req_o(i3c_rx_req),
        .i3c_rx_valid_i(i3c_rx_valid),
        .i3c_rx_byte_i(i3c_rx_byte),
        .i3c_rx_byte_last_i(i3c_rx_data_last),

        .i3c_fsm_en_i(1'b1),
        .i3c_fsm_idle_o,
        .ibi_detected_i(ibi_detected),
        .ibi_mode_o(ibi_mode),
        .ibi_address_byte_o(ibi_address_byte),
        .abort_read_o(abort_read),
        .i3c_trans_mode_o(i3c_trans_mode),
        .err
    );

    logic unused_host_idle_o;
    logic unused_event_nak_o;
    logic unused_event_unhandled_nak_timeout_o;
    logic unused_event_scl_interference_o;
    logic unused_event_sda_interference_o;
    logic unused_event_stretch_timeout_o;
    logic unused_event_sda_unstable_o;
    logic unused_event_cmd_complete_o;

    i3ccore_i2c_controller_fsm i2c_fsm (
        .clk_i (clk_i),
        .rst_ni(rst_ni),
        .scl_i (ctrl_bus_i[0].scl.value),
        .scl_o (ctrl_scl_o[0]),
        .sda_i (ctrl_bus_i[0].sda.value),
        .sda_o (ctrl_sda_o[0]),

        // These should be controlled by the flow FSM
        // TODO: reconnect to flow fsm once configuration.sv is connected properly to CSRs
        .host_enable_i('0),
        .fmt_fifo_rvalid_i(fmt_fifo_rvalid),
        .fmt_fifo_depth_i(fmt_fifo_depth),
        .fmt_fifo_rready_o(fmt_fifo_rready),
        .fmt_byte_i(fmt_byte),
        .fmt_flag_start_before_i(fmt_flag_start_before),
        .fmt_flag_stop_after_i(fmt_flag_stop_after),
        .fmt_flag_read_bytes_i(fmt_flag_read_bytes),
        .fmt_flag_read_continue_i(fmt_flag_read_continue),
        .fmt_flag_nak_ok_i(fmt_flag_nak_ok),
        .unhandled_unexp_nak_i(unhandled_unexp_nak),
        .unhandled_nak_timeout_i(unhandled_nak_timeout),
        .rx_fifo_wvalid_o(rx_fifo_wvalid),
        .rx_fifo_wdata_o(rx_fifo_wdata),
        .host_idle_o(unused_host_idle_o),

        // TODO: Use calculated timing values
        // TODO: Expose as programmable feature
        .thigh_i(16'd10),
        .tlow_i(16'd10),
        .t_r_i(16'd1),
        .t_f_i(16'd1),
        .thd_sta_i(16'd1),
        .tsu_sta_i(16'd1),
        .tsu_sto_i(16'd1),
        .tsu_dat_i(16'd1),
        .thd_dat_i(16'd1),
        .t_buf_i(16'd1),

        // Clock stretch is not supported by I3C bus
        .stretch_timeout_i('0),
        .timeout_enable_i ('0),

        // TODO: Handle NACK on bus
        .host_nack_handler_timeout_i('0),
        .host_nack_handler_timeout_en_i('0),

        // TODO: Handle bus events
        .event_nak_o(unused_event_nak_o),
        .event_unhandled_nak_timeout_o(unused_event_unhandled_nak_timeout_o),
        .event_scl_interference_o(unused_event_scl_interference_o),
        .event_sda_interference_o(unused_event_sda_interference_o),
        .event_stretch_timeout_o(unused_event_stretch_timeout_o),
        .event_sda_unstable_o(unused_event_sda_unstable_o),
        .event_cmd_complete_o(unused_event_cmd_complete_o)
    );

    // I3C Controller FSM - unused signals
    logic unused_i3c_host_idle;

    i3c_controller_fsm xi3c_controller_fsm (
        .clk_i(clk_i),
        .rst_ni(rst_ni),

        // I3C Bus interface
        .ctrl_scl_i(ctrl_bus_i[1].scl.value),
        .ctrl_sda_i(ctrl_bus_i[1].sda.value),
        .ctrl_scl_o(ctrl_scl_o[1]),
        .ctrl_sda_o(ctrl_sda_o[1]),

        // PP mode timing inputs (from CSRs)
        .t_r_pp_i(t_r_pp_i),
        .t_f_pp_i(t_f_pp_i),
        .thigh_pp_i(t_high_pp_i),
        .tlow_pp_i(t_low_pp_i),
        .tsu_pp_i(t_su_pp_i),
        .thd_pp_i(t_hd_pp_i),
        .t_casr_i(t_casr_i),
        .t_cbsr_i(t_cbsr_i),

        // OD mode timing inputs (from CSRs)
        .thigh_i(t_high_i),
        .tlow_i(t_low_i),
        .t_r_i(t_r_i),
        .t_f_i(t_f_i),
        .thd_sta_i(t_hd_sta_i),
        .tsu_sta_i(t_su_sta_i),
        .tsu_sto_i(t_su_sto_i),
        .tsu_dat_i(t_su_dat_i),
        .thd_dat_i(t_hd_dat_i),
        .t_buf_i(t_bus_free_i),

        // Control interface
        .host_enable_i(host_enable),
        .host_idle_o(unused_i3c_host_idle),

        // TX interface from flow_active
        .tx_valid_i(i3c_tx_valid),
        .tx_data_i(i3c_tx_byte),
        .tx_start_stop_i(i3c_start_stop),
        .tx_is_addr_i(i3c_tx_is_addr),
        .tx_use_tbit_i(i3c_tx_use_tbit),
        .tx_ready_o(i3c_tx_ready),
        .rx_ack_o(i3c_rx_ack),
        .rx_ack_valid_o(i3c_rx_ack_valid),

        // RX interface to flow_active
        .rx_req_i(i3c_rx_req),              // TODO: Connect to flow_active RX request
        .rx_valid_o(i3c_rx_valid),
        .rx_data_o(i3c_rx_byte),
        .rx_data_last_o(i3c_rx_data_last),

        // Mode selection output
        .sel_od_pp_o(phy_sel_od_pp_o[1]),

        .ibi_detected_o(ibi_detected),
        .ibi_mode_i(ibi_mode),
        .ibi_address_byte_i(ibi_address_byte),

        .abort_read_i(abort_read)
    );

    // TODO: Handle driver switching in the active controller mode
    assign phy_sel_od_pp_o[0] = '0;
endmodule
