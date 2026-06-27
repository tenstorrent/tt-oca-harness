// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

// Generated from i3c-core/src/i3c.sv - DO NOT EDIT MANUALLY

module i3c
  import i3c_pkg::*;
  import controller_pkg::*;
  import I3CCSR_pkg::CONTROLLER_SUPPORT;
  import I3CCSR_pkg::TARGET_SUPPORT;
#(
    parameter int unsigned AxiLiteDataWidth = 32,
    parameter int unsigned AxiLiteAddrWidth = 32,
    parameter int unsigned DatAw = i3c_pkg::DatAw,
    parameter int unsigned DctAw = i3c_pkg::DctAw,

    parameter int unsigned CsrAddrWidth = I3CCSR_pkg::I3CCSR_MIN_ADDR_WIDTH,
    parameter int unsigned CsrDataWidth = I3CCSR_pkg::I3CCSR_DATA_WIDTH,

    // HCI parameters (active when CONTROLLER_SUPPORT=1)
    parameter int unsigned HciRespFifoDepth = I3CCSR_pkg::resp_fifo_size,
    parameter int unsigned HciCmdFifoDepth = I3CCSR_pkg::cmd_fifo_size,
    parameter int unsigned HciRxFifoDepth = I3CCSR_pkg::rx_fifo_size,
    parameter int unsigned HciTxFifoDepth = I3CCSR_pkg::tx_fifo_size,
    parameter int unsigned HciIbiFifoDepth = I3CCSR_pkg::ibi_fifo_size,

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
    parameter int unsigned HciIbiThldWidth  = 8,
    // TTI parameters (active when TARGET_SUPPORT=1)
    parameter int unsigned TtiRxDescFifoDepth = I3CCSR_pkg::tti_rx_desc_fifo_size,
    parameter int unsigned TtiTxDescFifoDepth = I3CCSR_pkg::tti_tx_desc_fifo_size,
    parameter int unsigned TtiRxFifoDepth = I3CCSR_pkg::tti_rx_fifo_size,
    parameter int unsigned TtiTxFifoDepth = I3CCSR_pkg::tti_tx_fifo_size,
    parameter int unsigned TtiIbiFifoDepth = I3CCSR_pkg::tti_ibi_fifo_size,
    localparam int unsigned TtiTxDescFifoDepthWidth = $clog2(TtiTxDescFifoDepth + 1),
    localparam int unsigned TtiRxDescFifoDepthWidth = $clog2(TtiRxDescFifoDepth + 1),
    localparam int unsigned TtiTxFifoDepthWidth = $clog2(TtiTxFifoDepth + 1),
    localparam int unsigned TtiRxFifoDepthWidth = $clog2(TtiRxFifoDepth + 1),
    localparam int unsigned TtiIbiFifoDepthWidth = $clog2(TtiIbiFifoDepth + 1),

    parameter int unsigned TtiRxDescDataWidth = 32,
    parameter int unsigned TtiTxDescDataWidth = 32,
    parameter int unsigned TtiRxDataWidth = 32,
    parameter int unsigned TtiTxDataWidth = 32,
    parameter int unsigned TtiIbiDataWidth = 32,

    parameter int unsigned TtiRxDescThldWidth = 8,
    parameter int unsigned TtiTxDescThldWidth = 8,
    parameter int unsigned TtiRxThldWidth = 3,
    parameter int unsigned TtiTxThldWidth = 3,
    parameter int unsigned TtiIbiThldWidth = 8,
    parameter int unsigned IndirectFifoDepth = 64
) (
    input clk_i,  // clock
    input rst_ni, // active low reset

    // AXI4-Lite Interface
    // Write Address Channel
    input  logic                           awvalid_i,
    output logic                           awready_o,
    input  logic [AxiLiteAddrWidth-1:0]    awaddr_i,
    input  logic [2:0]                     awprot_i,

    // Write Data Channel
    input  logic                           wvalid_i,
    output logic                           wready_o,
    input  logic [AxiLiteDataWidth-1:0]    wdata_i,
    input  logic [AxiLiteDataWidth/8-1:0]  wstrb_i,

    // Write Response Channel
    output logic                           bvalid_o,
    input  logic                           bready_i,
    output logic [1:0]                     bresp_o,

    // Read Address Channel
    input  logic                           arvalid_i,
    output logic                           arready_o,
    input  logic [AxiLiteAddrWidth-1:0]    araddr_i,
    input  logic [2:0]                     arprot_i,

    // Read Data Channel
    output logic                           rvalid_o,
    input  logic                           rready_i,
    output logic [AxiLiteDataWidth-1:0]    rdata_o,
    output logic [1:0]                     rresp_o,


    // I3C bus IO
    input  logic i3c_scl_i,  // serial clock input from i3c bus
    output logic i3c_scl_o,  // serial clock output to i3c bus

    input  logic i3c_sda_i,  // serial data input from i3c bus
    output logic i3c_sda_o,  // serial data output to i3c bus

    output logic sel_od_pp_o,  // 0 - Open Drain, 1 - Push Pull

    // Output enable signals for I3C bus drivers
    output logic i3c_sda_oe_o,  // SDA output enable
    output logic i3c_scl_oe_o,  // SCL output enable

    // DAT memory export interface (active when CONTROLLER_SUPPORT=1)
    input  dat_mem_src_t  dat_mem_src_i,
    output dat_mem_sink_t dat_mem_sink_o,

    // DCT memory export interface (active when CONTROLLER_SUPPORT=1)
    input  dct_mem_src_t  dct_mem_src_i,
    output dct_mem_sink_t dct_mem_sink_o,

    // Recovery interface signals
    output logic recovery_payload_available_o,
    output logic recovery_image_activated_o,

    output logic peripheral_reset_o,
    input  logic peripheral_reset_done_i,
    output logic escalated_reset_o,

    // Interrupt output
    output logic irq_o
);

  // I3C SW CSR IF
  logic                    s_cpuif_req;
  logic                    s_cpuif_req_is_wr;
  logic [CsrAddrWidth-1:0] s_cpuif_addr;
  logic [CsrDataWidth-1:0] s_cpuif_wr_data;
  logic [CsrDataWidth-1:0] s_cpuif_wr_biten;
  logic                    s_cpuif_req_stall_wr;
  logic                    s_cpuif_req_stall_rd;
  logic                    s_cpuif_rd_ack;
  logic                    s_cpuif_rd_err;
  logic [CsrDataWidth-1:0] s_cpuif_rd_data;
  logic                    s_cpuif_wr_ack;
  logic                    s_cpuif_wr_err;

  // HCI signals (active when CONTROLLER_SUPPORT=1)
  // Response queue
  logic                             hci_resp_full;
  logic [HciRespFifoDepthWidth-1:0] hci_resp_depth;
  logic [     HciRespThldWidth-1:0] hci_resp_ready_thld;
  logic                             hci_resp_ready_thld_trig;
  logic                             hci_resp_empty;
  logic                             hci_resp_wvalid;
  logic                             hci_resp_wready;
  logic [     HciRespDataWidth-1:0] hci_resp_wdata;

  // Command queue
  logic                             hci_cmd_full;
  logic [ HciCmdFifoDepthWidth-1:0] hci_cmd_depth;
  logic [      HciCmdThldWidth-1:0] hci_cmd_ready_thld;
  logic                             hci_cmd_ready_thld_trig;
  logic                             hci_cmd_empty;
  logic                             hci_cmd_rvalid;
  logic                             hci_cmd_rready;
  logic [      HciCmdDataWidth-1:0] hci_cmd_rdata;

  // RX queue
  logic                             hci_rx_full;
  logic [  HciRxFifoDepthWidth-1:0] hci_rx_depth;
  logic [       HciRxThldWidth-1:0] hci_rx_start_thld;
  logic                             hci_rx_start_thld_trig;
  logic [       HciRxThldWidth-1:0] hci_rx_ready_thld;
  logic                             hci_rx_ready_thld_trig;
  logic                             hci_rx_empty;
  logic                             hci_rx_wvalid;
  logic                             hci_rx_wready;
  logic [       HciRxDataWidth-1:0] hci_rx_wdata;

  // TX queue
  logic                             hci_tx_full;
  logic [  HciTxFifoDepthWidth-1:0] hci_tx_depth;
  logic [       HciTxThldWidth-1:0] hci_tx_start_thld;
  logic                             hci_tx_start_thld_trig;
  logic [       HciTxThldWidth-1:0] hci_tx_ready_thld;
  logic                             hci_tx_ready_thld_trig;
  logic                             hci_tx_empty;
  logic                             hci_tx_rvalid;
  logic                             hci_tx_rready;
  logic [       HciTxDataWidth-1:0] hci_tx_rdata;

  // IBI queue
  logic                             hci_ibi_full;
  logic [ HciIbiFifoDepthWidth-1:0] hci_ibi_depth;
  logic [      HciIbiThldWidth-1:0] hci_ibi_ready_thld;
  logic                             hci_ibi_ready_thld_trig;
  logic                             hci_ibi_empty;
  logic                             hci_ibi_wvalid;
  logic                             hci_ibi_wready_data;    // Ready for data writes (not full)
  logic [      HciIbiDataWidth-1:0] hci_ibi_wdata;
  logic                             hci_ibi_status_desc_valid;  // NEW: distinguishes status descriptor from data

  // DAT <-> Controller interface
  logic                                            dat_read_valid_hw;
  logic [$clog2(I3CCSR_pkg::dat_depth + 1)-1:0] dat_index_hw;
  logic [                                    63:0] dat_rdata_hw;

  // DCT <-> Controller interface
  logic                                            dct_write_valid_hw;
  logic                                            dct_read_valid_hw;
  logic [$clog2(I3CCSR_pkg::dct_depth + 1)-1:0] dct_index_hw;
  logic [                    127:0] dct_wdata_hw;
  logic [                    127:0] dct_rdata_hw;

  // TTI signals (active when TARGET_SUPPORT=1)
  // TTI TX descriptors queue
  logic                               tti_tx_desc_full;
  logic [TtiRxDescFifoDepthWidth-1:0] tti_tx_desc_depth;
  logic [     TtiRxDescThldWidth-1:0] tti_tx_desc_ready_thld;
  logic                               tti_tx_desc_ready_thld_trig;
  logic                               tti_tx_desc_empty;
  logic                               tti_tx_desc_rvalid;
  logic                               tti_tx_desc_rready;
  logic [     TtiRxDescDataWidth-1:0] tti_tx_desc_rdata;

  // TTI RX descriptors queue
  logic                               tti_rx_desc_full;
  logic [TtiTxDescFifoDepthWidth-1:0] tti_rx_desc_depth;
  logic [     TtiTxDescThldWidth-1:0] tti_rx_desc_ready_thld;
  logic                               tti_rx_desc_ready_thld_trig;
  logic                               tti_rx_desc_empty;
  logic                               tti_rx_desc_wvalid;
  logic                               tti_rx_desc_wready;
  logic [     TtiTxDescDataWidth-1:0] tti_rx_desc_wdata;

  // TTI RX queue
  logic                               tti_rx_full;
  logic [    TtiRxFifoDepthWidth-1:0] tti_rx_depth;
  logic [         TtiRxThldWidth-1:0] tti_rx_start_thld;
  logic                               tti_rx_start_thld_trig;
  logic [         TtiRxThldWidth-1:0] tti_rx_ready_thld;
  logic                               tti_rx_ready_thld_trig;
  logic                               tti_rx_empty;
  logic                               tti_rx_wvalid;
  logic                               tti_rx_wready;
  logic [                        7:0] tti_rx_wdata;
  logic                               tti_rx_flush;

  // TTI TX queue
  logic                               tti_tx_full;
  logic [    TtiTxFifoDepthWidth-1:0] tti_tx_depth;
  logic [         TtiTxThldWidth-1:0] tti_tx_start_thld;
  logic                               tti_tx_start_thld_trig;
  logic [         TtiTxThldWidth-1:0] tti_tx_ready_thld;
  logic                               tti_tx_ready_thld_trig;
  logic                               tti_tx_empty;
  logic                               tti_tx_rvalid;
  logic                               tti_tx_rready;
  logic [                        7:0] tti_tx_rdata;
  logic                               tti_tx_flush;

  logic                               tti_tx_host_nack;
  logic                               tti_tx_pr_end;
  logic                               tti_tx_pr_start;

  // In-band Interrupt queue
  logic                               tti_ibi_full;
  logic [   TtiIbiFifoDepthWidth-1:0] tti_ibi_depth;
  logic [        TtiIbiThldWidth-1:0] tti_ibi_ready_thld;
  logic                               tti_ibi_ready_thld_trig;
  logic                               tti_ibi_empty;
  logic                               tti_ibi_rvalid;
  logic                               tti_ibi_rready;
  logic [        TtiIbiDataWidth-1:0] tti_ibi_rdata;

  // TODO: Fix these signals
  logic i3c_fsm_en_i;
  assign i3c_fsm_en_i = 1'b0;
  logic i3c_fsm_idle_o;

  axi_lite_adapter #(
      .AxiLiteDataWidth(AxiLiteDataWidth),
      .AxiLiteAddrWidth(AxiLiteAddrWidth)
  ) i3c_axi_lite_if (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      // AXI4-Lite Write Address Channel
      .awvalid_i(awvalid_i),
      .awready_o(awready_o),
      .awaddr_i(awaddr_i),
      .awprot_i(awprot_i),

      // AXI4-Lite Write Data Channel
      .wvalid_i(wvalid_i),
      .wready_o(wready_o),
      .wdata_i(wdata_i),
      .wstrb_i(wstrb_i),

      // AXI4-Lite Write Response Channel
      .bvalid_o(bvalid_o),
      .bready_i(bready_i),
      .bresp_o(bresp_o),

      // AXI4-Lite Read Address Channel
      .arvalid_i(arvalid_i),
      .arready_o(arready_o),
      .araddr_i(araddr_i),
      .arprot_i(arprot_i),

      // AXI4-Lite Read Data Channel
      .rvalid_o(rvalid_o),
      .rready_i(rready_i),
      .rdata_o(rdata_o),
      .rresp_o(rresp_o),

      // I3C SW CSR access interface
      .s_cpuif_req(s_cpuif_req),
      .s_cpuif_req_is_wr(s_cpuif_req_is_wr),
      .s_cpuif_addr(s_cpuif_addr),
      .s_cpuif_wr_data(s_cpuif_wr_data),
      .s_cpuif_wr_biten(s_cpuif_wr_biten),
      .s_cpuif_req_stall_wr(s_cpuif_req_stall_wr),
      .s_cpuif_req_stall_rd(s_cpuif_req_stall_rd),
      .s_cpuif_rd_ack(s_cpuif_rd_ack),
      .s_cpuif_rd_err(s_cpuif_rd_err),
      .s_cpuif_rd_data(s_cpuif_rd_data),
      .s_cpuif_wr_ack(s_cpuif_wr_ack),
      .s_cpuif_wr_err(s_cpuif_wr_err)
  );


  logic phy2ctrl_scl;
  logic phy2ctrl_sda;
  logic ctrl2phy_scl;
  logic ctrl2phy_sda;
  logic ctrl_sel_od_pp;

  // Configuration
  logic phy_en;
  logic [1:0] phy_mux_select;
  logic i2c_active_en;
  logic i2c_standby_en;
  logic i3c_active_en;
  logic i3c_standby_en;
  logic [19:0] t_hd_dat;
  logic [19:0] t_su_dat;
  logic [19:0] t_r;
  logic [19:0] t_f;
  logic [19:0] t_bus_free;
  logic [19:0] t_bus_idle;
  logic [19:0] t_bus_available;
  logic [31:0] stby_cr_device_addr_reg;
  logic [31:0] stby_cr_device_char_reg;
  logic [31:0] stby_cr_device_pid_lo_reg;

  // Interrupts
  logic ctl_irq;
  logic tti_irq;
  logic recovery_irq;

  logic bus_start;
  logic bus_rstart;
  logic bus_stop;

  logic [7:0] rx_bus_addr;
  logic rx_bus_addr_valid;
  logic [6:0] set_dasa;
  logic set_dasa_valid;
  logic set_dasa_virtual_device;
  logic set_aasa;
  logic set_aasa_virt;
  logic set_newda;
  logic set_newda_virtual_device;
  logic [6:0] newda;
  logic rstdaa;

  logic enec_ibi;
  logic enec_crr;
  logic enec_hj;
  logic disec_ibi;
  logic disec_crr;
  logic disec_hj;

  logic [7:0] rst_action;
  logic rst_action_valid;

  // Status
  logic [1:0] ibi_status;
  logic ibi_status_we;

  logic controller_error;

  logic recovery_mode_enter;
  logic recovery_mode_enabled;
  logic virtual_device_sel;
  logic xfer_in_progress;

  logic arbitration_lost, arbitration_lost_q;
  logic bus_scl_posedge;

  assign arbitration_lost = i3c_sda_o && !phy2ctrl_sda;
  assign arbitration_lost_q = arbitration_lost & bus_scl_posedge;

  // CSR Interface
  // Target Transaction CSR Interface
  I3CCSR_pkg::I3CCSR__I3C_EC__TTI__in_t hwif_tti_in;
  I3CCSR_pkg::I3CCSR__I3C_EC__TTI__out_t hwif_tti_out;

  // Recovery CSR Interface
  I3CCSR_pkg::I3CCSR__I3C_EC__SecFwRecoveryIf__in_t hwif_rec_in;
  I3CCSR_pkg::I3CCSR__I3C_EC__SecFwRecoveryIf__out_t hwif_rec_out;

  // SoC Management CSR Interface
  I3CCSR_pkg::I3CCSR__I3C_EC__SoCMgmtIf__in_t hwif_soc_mgmt_in;
  I3CCSR_pkg::I3CCSR__I3C_EC__SoCMgmtIf__out_t hwif_soc_mgmt_out;

  // PIO CONTROL CSR interface
  I3CCSR_pkg::I3CCSR__PIOControl__in_t hwif_pio_control_in;
  I3CCSR_pkg::I3CCSR__PIOControl__out_t hwif_pio_control_out;

  // I3C BASE CSR interface
  I3CCSR_pkg::I3CCSR__I3CBase__in_t hwif_base_in;
  I3CCSR_pkg::I3CCSR__I3CBase__out_t hwif_base_out;

  // DAT CSR interface
  I3CCSR_pkg::I3CCSR__DAT__in_t dat_in;
  I3CCSR_pkg::I3CCSR__DAT__out_t dat_out;

  // DCT CSR interface
  I3CCSR_pkg::I3CCSR__DCT__in_t dct_in;
  I3CCSR_pkg::I3CCSR__DCT__out_t dct_out;

  I3CCSR_pkg::I3CCSR__out_t hwif_out;

  logic bypass_i3c_core;
  assign bypass_i3c_core = hwif_out.I3C_EC.SoCMgmtIf.REC_INTF_CFG.REC_INTF_BYPASS.value;

  logic unused_err;

  controller #(
      .DatAw(DatAw),
      .DctAw(DctAw)
      // HCI FIFO depth parameters
      ,.HciRespFifoDepth(HciRespFifoDepth)
      ,.HciCmdFifoDepth(HciCmdFifoDepth)
      ,.HciRxFifoDepth(HciRxFifoDepth)
      ,.HciTxFifoDepth(HciTxFifoDepth)
      ,.HciIbiFifoDepth(HciIbiFifoDepth)
      // TTI FIFO depth parameters
      ,.TtiRxDescFifoDepth(TtiRxDescFifoDepth)
      ,.TtiTxDescFifoDepth(TtiTxDescFifoDepth)
      ,.TtiRxFifoDepth(TtiRxFifoDepth)
      ,.TtiTxFifoDepth(TtiTxFifoDepth)
      ,.TtiIbiFifoDepth(TtiIbiFifoDepth)
  ) xcontroller (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      .scl_i(phy2ctrl_scl),
      .sda_i(phy2ctrl_sda),
      .scl_o(ctrl2phy_scl),
      .sda_o(ctrl2phy_sda),
      .sel_od_pp_o(ctrl_sel_od_pp),
      .arbitration_lost_i(arbitration_lost_q),

      // HCI Response queue
      .hci_resp_queue_empty_i(hci_resp_empty),
      .hci_resp_queue_full_i(hci_resp_full),
      .hci_resp_queue_depth_i(hci_resp_depth),
      .hci_resp_queue_ready_thld_i(hci_resp_ready_thld),
      .hci_resp_queue_ready_thld_trig_i(hci_resp_ready_thld_trig),
      .hci_resp_queue_wvalid_o(hci_resp_wvalid),
      .hci_resp_queue_wready_i(hci_resp_wready),
      .hci_resp_queue_wdata_o(hci_resp_wdata),

      // HCI Command queue
      .hci_cmd_queue_empty_i(hci_cmd_empty),
      .hci_cmd_queue_full_i(hci_cmd_full),
      .hci_cmd_queue_depth_i(hci_cmd_depth),
      .hci_cmd_queue_ready_thld_i(hci_cmd_ready_thld),
      .hci_cmd_queue_ready_thld_trig_i(hci_cmd_ready_thld_trig),
      .hci_cmd_queue_rvalid_i(hci_cmd_rvalid),
      .hci_cmd_queue_rready_o(hci_cmd_rready),
      .hci_cmd_queue_rdata_i(hci_cmd_rdata),

      // HCI RX queue
      .hci_rx_queue_empty_i(hci_rx_empty),
      .hci_rx_queue_full_i(hci_rx_full),
      .hci_rx_queue_depth_i(hci_rx_depth),
      .hci_rx_queue_start_thld_i(hci_rx_start_thld),
      .hci_rx_queue_start_thld_trig_i(hci_rx_start_thld_trig),
      .hci_rx_queue_ready_thld_i(hci_rx_ready_thld),
      .hci_rx_queue_ready_thld_trig_i(hci_rx_ready_thld_trig),
      .hci_rx_queue_wvalid_o(hci_rx_wvalid),
      .hci_rx_queue_wready_i(hci_rx_wready),
      .hci_rx_queue_wdata_o(hci_rx_wdata),

      // HCI TX queue
      .hci_tx_queue_empty_i(hci_tx_empty),
      .hci_tx_queue_full_i(hci_tx_full),
      .hci_tx_queue_depth_i(hci_tx_depth),
      .hci_tx_queue_start_thld_i(hci_tx_start_thld),
      .hci_tx_queue_start_thld_trig_i(hci_tx_start_thld_trig),
      .hci_tx_queue_ready_thld_i(hci_tx_ready_thld),
      .hci_tx_queue_ready_thld_trig_i(hci_tx_ready_thld_trig),
      .hci_tx_queue_rvalid_i(hci_tx_rvalid),
      .hci_tx_queue_rready_o(hci_tx_rready),
      .hci_tx_queue_rdata_i(hci_tx_rdata),

      // In-band Interrupt queue
      .hci_ibi_queue_full_i(hci_ibi_full),
      .hci_ibi_queue_depth_i(hci_ibi_depth),
      .hci_ibi_queue_ready_thld_i(hci_ibi_ready_thld),
      .hci_ibi_queue_ready_thld_trig_i(hci_ibi_ready_thld_trig),
      .hci_ibi_queue_empty_i(hci_ibi_empty),
      .hci_ibi_queue_wvalid_o(hci_ibi_wvalid),
      .hci_ibi_queue_wready_data_i(hci_ibi_wready_data),
      .hci_ibi_queue_wdata_o(hci_ibi_wdata),
      .hci_ibi_status_desc_valid_o(hci_ibi_status_desc_valid),  // NEW

      // TTI: RX Descriptor
      .tti_rx_desc_queue_full_i(tti_rx_desc_full),
      .tti_rx_desc_queue_depth_i(tti_rx_desc_depth),
      .tti_rx_desc_queue_ready_thld_i(tti_rx_desc_ready_thld),
      .tti_rx_desc_queue_ready_thld_trig_i(tti_rx_desc_ready_thld_trig),
      .tti_rx_desc_queue_empty_i(tti_rx_desc_empty),
      .tti_rx_desc_queue_wvalid_o(tti_rx_desc_wvalid),
      .tti_rx_desc_queue_wready_i(tti_rx_desc_wready),
      .tti_rx_desc_queue_wdata_o(tti_rx_desc_wdata),

      // TTI: RX Data
      .tti_rx_queue_full_i(tti_rx_full),
      .tti_rx_queue_depth_i(tti_rx_depth),
      .tti_rx_queue_start_thld_i(tti_rx_start_thld),
      .tti_rx_queue_start_thld_trig_i(tti_rx_start_thld_trig),
      .tti_rx_queue_ready_thld_i(tti_rx_ready_thld),
      .tti_rx_queue_ready_thld_trig_i(tti_rx_ready_thld_trig),
      .tti_rx_queue_empty_i(tti_rx_empty),
      .tti_rx_queue_wvalid_o(tti_rx_wvalid),
      .tti_rx_queue_wready_i(tti_rx_wready),
      .tti_rx_queue_wdata_o(tti_rx_wdata),
      .tti_rx_queue_flush_o(tti_rx_flush),

      // TTI: TX Descriptor
      .tti_tx_desc_queue_full_i(tti_tx_desc_full),
      .tti_tx_desc_queue_depth_i(tti_tx_desc_depth),
      .tti_tx_desc_queue_ready_thld_i(tti_tx_desc_ready_thld),
      .tti_tx_desc_queue_ready_thld_trig_i(tti_tx_desc_ready_thld_trig),
      .tti_tx_desc_queue_empty_i(tti_tx_desc_empty),
      .tti_tx_desc_queue_rvalid_i(tti_tx_desc_rvalid),
      .tti_tx_desc_queue_rready_o(tti_tx_desc_rready),
      .tti_tx_desc_queue_rdata_i(tti_tx_desc_rdata),

      // TTI: TX Data
      .tti_tx_queue_full_i(tti_tx_full),
      .tti_tx_queue_depth_i(tti_tx_depth),
      .tti_tx_queue_start_thld_i(tti_tx_start_thld),
      .tti_tx_queue_start_thld_trig_i(tti_tx_start_thld_trig),
      .tti_tx_queue_ready_thld_i(tti_tx_ready_thld),
      .tti_tx_queue_ready_thld_trig_i(tti_tx_ready_thld_trig),
      .tti_tx_queue_empty_i(tti_tx_empty),
      .tti_tx_queue_rvalid_i(tti_tx_rvalid),
      .tti_tx_queue_rready_o(tti_tx_rready),
      .tti_tx_queue_rdata_i(tti_tx_rdata),
      .tti_tx_queue_flush_o(tti_tx_flush),
      .tti_tx_host_nack_o(tti_tx_host_nack),
      .tti_tx_pr_end_o(tti_tx_pr_end),
      .tti_tx_pr_start_o(tti_tx_pr_start),

      // TTI: In-band Interrupt queue
      .tti_ibi_queue_full_i(tti_ibi_full),
      .tti_ibi_queue_depth_i(tti_ibi_depth),
      .tti_ibi_queue_ready_thld_i(tti_ibi_ready_thld),
      .tti_ibi_queue_ready_thld_trig_i(tti_ibi_ready_thld_trig),
      .tti_ibi_queue_empty_i(tti_ibi_empty),
      .tti_ibi_queue_rvalid_i(tti_ibi_rvalid),
      .tti_ibi_queue_rready_o(tti_ibi_rready),
      .tti_ibi_queue_rdata_i(tti_ibi_rdata),

      // I2C/I3C bus condition detection
      .bus_start_o (bus_start),
      .bus_rstart_o(bus_rstart),
      .bus_stop_o  (bus_stop),
      .bus_scl_posedge_o(bus_scl_posedge),

      // I2C/I3C received address (with RnW# bit) for the recovery handler
      .bus_addr_o(rx_bus_addr),
      .bus_addr_valid_o(rx_bus_addr_valid),
      // DAT <-> Controller interface
      .dat_read_valid_hw_o(dat_read_valid_hw),
      .dat_index_hw_o(dat_index_hw),
      .dat_rdata_hw_i(dat_rdata_hw),

      // DCT <-> Controller interface
      .dct_write_valid_hw_o(dct_write_valid_hw),
      .dct_read_valid_hw_o(dct_read_valid_hw),
      .dct_index_hw_o(dct_index_hw),
      .dct_wdata_hw_o(dct_wdata_hw),
      .dct_rdata_hw_i(dct_rdata_hw),
      .i3c_fsm_en_i  (i3c_fsm_en_i),
      .i3c_fsm_idle_o(i3c_fsm_idle_o),

      .err(unused_err),
      .hwif_out_i(hwif_out),
      .hwif_rec_i(hwif_rec_out),

      .ibi_status_o(ibi_status),
      .ibi_status_we_o(ibi_status_we),

      .set_dasa_o(set_dasa),
      .set_dasa_valid_o(set_dasa_valid),
      .set_dasa_virtual_device_o(set_dasa_virtual_device),
      .set_aasa_o(set_aasa),
      .set_aasa_virt_o(set_aasa_virt),
      .rstdaa_o(rstdaa),
      .set_newda_o(set_newda),
      .set_newda_virtual_device_o(set_newda_virtual_device),
      .newda_o(newda),

      .rst_action_o(rst_action),
      .rst_action_valid_o(rst_action_valid),

      .enec_ibi_o (enec_ibi),
      .enec_crr_o (enec_crr),
      .enec_hj_o  (enec_hj),
      .disec_ibi_o(disec_ibi),
      .disec_crr_o(disec_crr),
      .disec_hj_o (disec_hj),

      .peripheral_reset_o,
      .peripheral_reset_done_i,
      .escalated_reset_o,

      .err_o(controller_error),
      .recovery_mode_enter_i(recovery_mode_enter),
      .virtual_device_sel_o(virtual_device_sel),
      .xfer_in_progress_o(xfer_in_progress),

      .i3c_active_en_o(i3c_active_en),
      .i3c_standby_en_o(i3c_standby_en)
  );

  // HCI
  hci #(
      .CsrAddrWidth(CsrAddrWidth),
      .CsrDataWidth(CsrDataWidth),
      .DatAw(DatAw),
      .DctAw(DctAw),
      .HciRespFifoDepth(HciRespFifoDepth),
      .HciCmdFifoDepth(HciCmdFifoDepth),
      .HciRxFifoDepth(HciRxFifoDepth),
      .HciTxFifoDepth(HciTxFifoDepth),
      .HciIbiFifoDepth(HciIbiFifoDepth),
      .HciRespDataWidth(HciRespDataWidth),
      .HciCmdDataWidth(HciCmdDataWidth),
      .HciRxDataWidth(HciRxDataWidth),
      .HciTxDataWidth(HciTxDataWidth),
      .HciRespThldWidth(HciRespThldWidth),
      .HciCmdThldWidth(HciCmdThldWidth),
      .HciRxThldWidth(HciRxThldWidth),
      .HciTxThldWidth(HciTxThldWidth)
  ) xhci (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      .dat_read_valid_hw_i(dat_read_valid_hw),
      .dat_index_hw_i(dat_index_hw),
      .dat_rdata_hw_o(dat_rdata_hw),

      .dct_write_valid_hw_i(dct_write_valid_hw),
      .dct_read_valid_hw_i(dct_read_valid_hw),
      .dct_index_hw_i(dct_index_hw),
      .dct_wdata_hw_i(dct_wdata_hw),
      .dct_rdata_hw_o(dct_rdata_hw),

      .dat_mem_src_i (dat_mem_src_i),
      .dat_mem_sink_o(dat_mem_sink_o),

      .dct_mem_src_i (dct_mem_src_i),
      .dct_mem_sink_o(dct_mem_sink_o),

      // CSR Interface
      .hwif_pio_control_i(hwif_pio_control_out),
      .hwif_pio_control_o(hwif_pio_control_in),
      .hwif_base_i(hwif_base_out),
      .hwif_base_o(hwif_base_in),
      .dat_i(dat_out),
      .dat_o(dat_in),
      .dct_i(dct_out),
      .dct_o(dct_in),

      // HCI Response queue
      .hci_resp_full_o(hci_resp_full),
      .hci_resp_depth_o(hci_resp_depth),
      .hci_resp_ready_thld_o(hci_resp_ready_thld),
      .hci_resp_ready_thld_trig_o(hci_resp_ready_thld_trig),
      .hci_resp_empty_o(hci_resp_empty),
      .hci_resp_wvalid_i(hci_resp_wvalid),
      .hci_resp_wready_o(hci_resp_wready),
      .hci_resp_wdata_i(hci_resp_wdata),

      // HCI Command queue
      .hci_cmd_full_o(hci_cmd_full),
      .hci_cmd_depth_o(hci_cmd_depth),
      .hci_cmd_ready_thld_o(hci_cmd_ready_thld),
      .hci_cmd_ready_thld_trig_o(hci_cmd_ready_thld_trig),
      .hci_cmd_empty_o(hci_cmd_empty),
      .hci_cmd_rvalid_o(hci_cmd_rvalid),
      .hci_cmd_rready_i(hci_cmd_rready),
      .hci_cmd_rdata_o(hci_cmd_rdata),

      // HCI RX queue
      .hci_rx_full_o(hci_rx_full),
      .hci_rx_depth_o(hci_rx_depth),
      .hci_rx_start_thld_o(hci_rx_start_thld),
      .hci_rx_start_thld_trig_o(hci_rx_start_thld_trig),
      .hci_rx_ready_thld_o(hci_rx_ready_thld),
      .hci_rx_ready_thld_trig_o(hci_rx_ready_thld_trig),
      .hci_rx_empty_o(hci_rx_empty),
      .hci_rx_wvalid_i(hci_rx_wvalid),
      .hci_rx_wready_o(hci_rx_wready),
      .hci_rx_wdata_i(hci_rx_wdata),

      // HCI TX queue
      .hci_tx_full_o(hci_tx_full),
      .hci_tx_depth_o(hci_tx_depth),
      .hci_tx_start_thld_o(hci_tx_start_thld),
      .hci_tx_start_thld_trig_o(hci_tx_start_thld_trig),
      .hci_tx_ready_thld_o(hci_tx_ready_thld),
      .hci_tx_ready_thld_trig_o(hci_tx_ready_thld_trig),
      .hci_tx_empty_o(hci_tx_empty),
      .hci_tx_rvalid_o(hci_tx_rvalid),
      .hci_tx_rready_i(hci_tx_rready),
      .hci_tx_rdata_o(hci_tx_rdata),

      .hci_ibi_full_o(hci_ibi_full),
      .hci_ibi_depth_o(hci_ibi_depth),
      .hci_ibi_ready_thld_o(hci_ibi_ready_thld),
      .hci_ibi_ready_thld_trig_o(hci_ibi_ready_thld_trig),
      .hci_ibi_empty_o(hci_ibi_empty),
      .hci_ibi_wvalid_i(hci_ibi_wvalid),
      .hci_ibi_wready_data_o(hci_ibi_wready_data),
      .hci_ibi_wdata_i(hci_ibi_wdata),
      .hci_ibi_status_desc_valid_i(hci_ibi_status_desc_valid),  // NEW

      // Controller configuration status
      .set_dasa_i(set_dasa),
      .set_dasa_valid_i(set_dasa_valid),
      .set_dasa_virtual_device_i(set_dasa_virtual_device),
      .rstdaa_i(rstdaa),
      .newda_i(newda),
      .set_newda_i(set_newda),
      .set_newda_virtual_device_i(set_newda_virtual_device),

      .rst_action_i(rst_action),
      .rst_action_valid_i(rst_action_valid),

      .irq_o(ctl_irq)
  );

  // TTI RX Descriptor queue
  logic                          csr_tti_rx_desc_req;
  logic                          csr_tti_rx_desc_ack;
  logic [TtiRxDescDataWidth-1:0] csr_tti_rx_desc_data;
  logic [TtiRxDescThldWidth-1:0] csr_tti_rx_desc_ready_thld_i;
  logic [TtiRxDescThldWidth-1:0] csr_tti_rx_desc_ready_thld_o;
  logic                          csr_tti_rx_desc_ready_trig;
  logic                          csr_tti_rx_desc_reg_rst;
  logic                          csr_tti_rx_desc_reg_rst_we;
  logic                          csr_tti_rx_desc_reg_rst_data;

  logic                          csr_tti_rx_desc_empty;
  logic                          csr_tti_rx_desc_full;
  logic                          csr_tti_rx_desc_write;

  // TTI TX Descriptor queue
  logic                          csr_tti_tx_desc_req;
  logic                          csr_tti_tx_desc_ack;
  logic [      CsrDataWidth-1:0] csr_tti_tx_desc_data;
  logic [TtiTxDescThldWidth-1:0] csr_tti_tx_desc_ready_thld_i;
  logic [TtiTxDescThldWidth-1:0] csr_tti_tx_desc_ready_thld_o;
  logic                          csr_tti_tx_desc_reg_rst;
  logic                          csr_tti_tx_desc_reg_rst_we;
  logic                          csr_tti_tx_desc_reg_rst_data;
  logic                          csr_tti_tx_desc_full;

  // TTI RX data queue
  logic                          csr_tti_rx_data_req;
  logic                          csr_tti_rx_data_ack;
  logic [    TtiRxDataWidth-1:0] csr_tti_rx_data_data;
  logic [    TtiRxThldWidth-1:0] csr_tti_rx_data_start_thld;
  logic [    TtiRxThldWidth-1:0] csr_tti_rx_data_ready_thld_i;
  logic [    TtiRxThldWidth-1:0] csr_tti_rx_data_ready_thld_o;
  logic                          csr_tti_rx_data_ready_trig;
  logic                          csr_tti_rx_data_reg_rst;
  logic                          csr_tti_rx_data_reg_rst_we;
  logic                          csr_tti_rx_data_reg_rst_data;

  logic                          csr_tti_rx_data_empty;
  logic                          csr_tti_rx_data_full;
  logic                          csr_tti_rx_data_write;

  // TTI TX data queue
  logic                          csr_tti_tx_data_req;
  logic                          csr_tti_tx_data_ack;
  logic [      CsrDataWidth-1:0] csr_tti_tx_data_data;
  logic [    TtiTxThldWidth-1:0] csr_tti_tx_data_start_thld;
  logic [    TtiTxThldWidth-1:0] csr_tti_tx_data_ready_thld_i;
  logic [    TtiTxThldWidth-1:0] csr_tti_tx_data_ready_thld_o;
  logic                          csr_tti_tx_data_reg_rst;
  logic                          csr_tti_tx_data_reg_rst_we;
  logic                          csr_tti_tx_data_reg_rst_data;
  logic                          csr_tti_tx_data_full;

  // TTI In-band Interrupt (IBI) queue
  logic                          csr_tti_ibi_req;
  logic                          csr_tti_ibi_ack;
  logic [      CsrDataWidth-1:0] csr_tti_ibi_data;
  logic [   TtiIbiThldWidth-1:0] csr_tti_ibi_ready_thld;
  logic                          csr_tti_ibi_reg_rst;
  logic                          csr_tti_ibi_reg_rst_we;
  logic                          csr_tti_ibi_reg_rst_data;

  tti xtti (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      .hwif_tti_i(hwif_tti_out),
      .hwif_tti_o(hwif_tti_in),

      // TTI RX descriptors queue
      .rx_desc_queue_req_o            (csr_tti_rx_desc_req),
      .rx_desc_queue_ack_i            (csr_tti_rx_desc_ack),
      .rx_desc_queue_data_i           (csr_tti_rx_desc_data),
      .rx_desc_queue_ready_thld_o     (csr_tti_rx_desc_ready_thld_i),
      .rx_desc_queue_ready_thld_i     (csr_tti_rx_desc_ready_thld_o),
      .rx_desc_queue_reg_rst_o        (csr_tti_rx_desc_reg_rst),
      .rx_desc_queue_reg_rst_we_i     (csr_tti_rx_desc_reg_rst_we),
      .rx_desc_queue_reg_rst_data_i   (csr_tti_rx_desc_reg_rst_data),
      .rx_desc_queue_ready_thld_trig_i(csr_tti_rx_desc_ready_trig),

      .rx_desc_queue_empty_i(tti_rx_desc_empty),
      .rx_desc_queue_full_i (tti_rx_desc_full),
      .rx_desc_queue_write_i(tti_rx_desc_wvalid & tti_rx_desc_wready),

      // TTI TX descriptors queue
      .tx_desc_queue_req_o             (csr_tti_tx_desc_req),
      .tx_desc_queue_ack_i             (csr_tti_tx_desc_ack),
      .tx_desc_queue_data_o            (csr_tti_tx_desc_data),
      .tx_desc_queue_ready_thld_o      (csr_tti_tx_desc_ready_thld_i),
      .tx_desc_queue_ready_thld_i      (csr_tti_tx_desc_ready_thld_o),
      .tx_desc_queue_reg_rst_o         (csr_tti_tx_desc_reg_rst),
      .tx_desc_queue_reg_rst_we_i      (csr_tti_tx_desc_reg_rst_we),
      .tx_desc_queue_reg_rst_data_i    (csr_tti_tx_desc_reg_rst_data),
      .tx_desc_queue_full_i            (csr_tti_tx_desc_full),
      .tx_desc_queue_write_i           ('0), // TODO: tied off - tx_*_queue_write_r is currently unused in tti.sv; wire to TX write strobe if a TX write interrupt is added
      .tx_desc_queue_ready_thld_trig_i (tti_tx_desc_ready_thld_trig),

      // TTI RX queue
      .rx_data_queue_req_o            (csr_tti_rx_data_req),
      .rx_data_queue_ack_i            (csr_tti_rx_data_ack),
      .rx_data_queue_data_i           (csr_tti_rx_data_data),
      .rx_data_queue_start_thld_o     (csr_tti_rx_data_start_thld),
      .rx_data_queue_ready_thld_o     (csr_tti_rx_data_ready_thld_i),
      .rx_data_queue_ready_thld_i     (csr_tti_rx_data_ready_thld_o),
      .rx_data_queue_reg_rst_o        (csr_tti_rx_data_reg_rst),
      .rx_data_queue_reg_rst_we_i     (csr_tti_rx_data_reg_rst_we),
      .rx_data_queue_reg_rst_data_i   (csr_tti_rx_data_reg_rst_data),
      .rx_data_queue_ready_thld_trig_i(csr_tti_rx_data_ready_trig),

      .rx_data_queue_empty_i(tti_rx_empty),
      .rx_data_queue_full_i (tti_rx_full),
      .rx_data_queue_write_i(tti_rx_wvalid & tti_rx_wready),

      // TTI TX queue
      .tx_data_queue_req_o             (csr_tti_tx_data_req),
      .tx_data_queue_ack_i             (csr_tti_tx_data_ack),
      .tx_data_queue_data_o            (csr_tti_tx_data_data),
      .tx_data_queue_start_thld_o      (csr_tti_tx_data_start_thld),
      .tx_data_queue_ready_thld_o      (csr_tti_tx_data_ready_thld_i),
      .tx_data_queue_ready_thld_i      (csr_tti_tx_data_ready_thld_o),
      .tx_data_queue_reg_rst_o         (csr_tti_tx_data_reg_rst),
      .tx_data_queue_reg_rst_we_i      (csr_tti_tx_data_reg_rst_we),
      .tx_data_queue_reg_rst_data_i    (csr_tti_tx_data_reg_rst_data),
      .tx_data_queue_full_i            (csr_tti_tx_data_full),
      .tx_data_queue_write_i           ('0), // TODO: tied off - tx_*_queue_write_r is currently unused in tti.sv; wire to TX write strobe if a TX write interrupt is added
      .tx_data_queue_ready_thld_trig_i (tti_tx_ready_thld_trig),

      // TTI In-band Interrupt (IBI) queue
      .ibi_queue_full_i            (tti_ibi_full),
      .ibi_queue_req_o             (csr_tti_ibi_req),
      .ibi_queue_ack_i             (csr_tti_ibi_ack),
      .ibi_queue_data_o            (csr_tti_ibi_data),
      .ibi_queue_ready_thld_o      (csr_tti_ibi_ready_thld),
      .ibi_queue_reg_rst_o         (csr_tti_ibi_reg_rst),
      .ibi_queue_reg_rst_we_i      (csr_tti_ibi_reg_rst_we),
      .ibi_queue_reg_rst_data_i    (csr_tti_ibi_reg_rst_data),
      .ibi_queue_ready_thld_trig_i (tti_ibi_ready_thld_trig),

      .bypass_i3c_core_i(bypass_i3c_core),

      .recovery_mode_enabled_i(recovery_mode_enabled),
      .ibi_status_i(ibi_status),
      .ibi_status_we_i(ibi_status_we),
      .tx_pr_end_i(tti_tx_pr_end),
      .tx_pr_start_i(tti_tx_pr_start),

      .enec_ibi_i (enec_ibi),
      .enec_crr_i (enec_crr),
      .enec_hj_i  (enec_hj),
      .disec_ibi_i(disec_ibi),
      .disec_crr_i(disec_crr),
      .disec_hj_i (disec_hj),

      .err_i(controller_error),

      .irq_o(tti_irq)
  );

  csri #(
      .CsrAddrWidth(CsrAddrWidth),
      .CsrDataWidth(CsrDataWidth)
  ) xcsri (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      .s_cpuif_req(s_cpuif_req),
      .s_cpuif_req_is_wr(s_cpuif_req_is_wr),
      .s_cpuif_addr(s_cpuif_addr),
      .s_cpuif_wr_data(s_cpuif_wr_data),
      .s_cpuif_wr_biten(s_cpuif_wr_biten),
      .s_cpuif_req_stall_wr(s_cpuif_req_stall_wr),
      .s_cpuif_req_stall_rd(s_cpuif_req_stall_rd),
      .s_cpuif_rd_ack(s_cpuif_rd_ack),
      .s_cpuif_rd_err(s_cpuif_rd_err),
      .s_cpuif_rd_data(s_cpuif_rd_data),
      .s_cpuif_wr_ack(s_cpuif_wr_ack),
      .s_cpuif_wr_err(s_cpuif_wr_err),

      // CSR Interface
      .hwif_tti_i(hwif_tti_in),
      .hwif_tti_o(hwif_tti_out),
      .hwif_rec_i(hwif_rec_in),
      .hwif_rec_o(hwif_rec_out),
      .hwif_socmgmt_i(hwif_soc_mgmt_in),
      .hwif_socmgmt_o(hwif_soc_mgmt_out),
      .hwif_pio_control_i(hwif_pio_control_in),
      .hwif_pio_control_o(hwif_pio_control_out),
      .hwif_base_i(hwif_base_in),
      .hwif_base_o(hwif_base_out),
      .dat_i(dat_in),
      .dat_o(dat_out),
      .dct_i(dct_in),
      .dct_o(dct_out),
      .hwif_out_o(hwif_out),

      // Controller configuration status
      .set_dasa_i(set_dasa),
      .set_dasa_valid_i(set_dasa_valid),
      .set_dasa_virtual_device_i(set_dasa_virtual_device),
      .set_aasa_i(set_aasa),
      .set_aasa_virt_i(set_aasa_virt),
      .rstdaa_i(rstdaa),
      .set_newda_i(set_newda),
      .set_newda_virtual_device_i(set_newda_virtual_device),
      .newda_i(newda),

      .rst_action_i(rst_action),
      .rst_action_valid_i(rst_action_valid)
  );

  // Recovery handler
  recovery_handler #(
      .TtiRxDescDataWidth(TtiRxDescDataWidth),
      .TtiRxDescThldWidth(TtiRxDescThldWidth),
      .TtiRxDescFifoDepth(TtiRxDescFifoDepth),
      .TtiRxDataDataWidth(TtiRxDataWidth),
      .TtiRxDataThldWidth(TtiRxThldWidth),
      .TtiRxDataFifoDepth(TtiRxFifoDepth),
      .TtiTxDescDataWidth(TtiTxDescDataWidth),
      .TtiTxDescThldWidth(TtiTxDescThldWidth),
      .TtiTxDescFifoDepth(TtiTxDescFifoDepth),
      .TtiTxDataDataWidth(TtiTxDataWidth),
      .TtiTxDataThldWidth(TtiTxThldWidth),
      .TtiTxDataFifoDepth(TtiTxFifoDepth),
      .TtiIbiDataWidth(TtiIbiDataWidth),
      .TtiIbiThldWidth(TtiIbiThldWidth),
      .TtiIbiFifoDepth(TtiIbiFifoDepth),
      .CsrDataWidth(CsrDataWidth),
      .IndirectFifoDepth(IndirectFifoDepth)
  ) xrecovery_handler (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      // SoC Management CSR interface
      .hwif_socmgmt_i(hwif_soc_mgmt_out),
      .hwif_socmgmt_o(hwif_soc_mgmt_in),

      // Recovery CSR interface
      .hwif_rec_i(hwif_rec_out),
      .hwif_rec_o(hwif_rec_in),

      .bypass_i3c_core_i(bypass_i3c_core),

      // TTI RX descriptors queue
      .csr_tti_rx_desc_queue_req_i            (csr_tti_rx_desc_req),
      .csr_tti_rx_desc_queue_ack_o            (csr_tti_rx_desc_ack),
      .csr_tti_rx_desc_queue_data_o           (csr_tti_rx_desc_data),
      .csr_tti_rx_desc_queue_ready_thld_i     (csr_tti_rx_desc_ready_thld_i),
      .csr_tti_rx_desc_queue_ready_thld_o     (csr_tti_rx_desc_ready_thld_o),
      .csr_tti_rx_desc_queue_reg_rst_i        (csr_tti_rx_desc_reg_rst),
      .csr_tti_rx_desc_queue_reg_rst_we_o     (csr_tti_rx_desc_reg_rst_we),
      .csr_tti_rx_desc_queue_reg_rst_data_o   (csr_tti_rx_desc_reg_rst_data),
      .csr_tti_rx_desc_queue_ready_thld_trig_o(csr_tti_rx_desc_ready_trig),

      // TTI TX descriptors queue
      .csr_tti_tx_desc_queue_req_i         (csr_tti_tx_desc_req),
      .csr_tti_tx_desc_queue_ack_o         (csr_tti_tx_desc_ack),
      .csr_tti_tx_desc_queue_data_i        (csr_tti_tx_desc_data),
      .csr_tti_tx_desc_queue_ready_thld_i  (csr_tti_tx_desc_ready_thld_i),
      .csr_tti_tx_desc_queue_ready_thld_o  (csr_tti_tx_desc_ready_thld_o),
      .csr_tti_tx_desc_queue_reg_rst_i     (csr_tti_tx_desc_reg_rst),
      .csr_tti_tx_desc_queue_reg_rst_we_o  (csr_tti_tx_desc_reg_rst_we),
      .csr_tti_tx_desc_queue_reg_rst_data_o(csr_tti_tx_desc_reg_rst_data),
      .csr_tti_tx_desc_queue_full_o        (csr_tti_tx_desc_full),

      // TTI RX queue
      .csr_tti_rx_data_queue_req_i            (csr_tti_rx_data_req),
      .csr_tti_rx_data_queue_ack_o            (csr_tti_rx_data_ack),
      .csr_tti_rx_data_queue_data_o           (csr_tti_rx_data_data),
      .csr_tti_rx_data_queue_start_thld_i     (csr_tti_rx_data_start_thld),
      .csr_tti_rx_data_queue_ready_thld_i     (csr_tti_rx_data_ready_thld_i),
      .csr_tti_rx_data_queue_ready_thld_o     (csr_tti_rx_data_ready_thld_o),
      .csr_tti_rx_data_queue_reg_rst_i        (csr_tti_rx_data_reg_rst),
      .csr_tti_rx_data_queue_reg_rst_we_o     (csr_tti_rx_data_reg_rst_we),
      .csr_tti_rx_data_queue_reg_rst_data_o   (csr_tti_rx_data_reg_rst_data),
      .csr_tti_rx_data_queue_ready_thld_trig_o(csr_tti_rx_data_ready_trig),

      // TTI TX queue
      .csr_tti_tx_data_queue_req_i         (csr_tti_tx_data_req),
      .csr_tti_tx_data_queue_ack_o         (csr_tti_tx_data_ack),
      .csr_tti_tx_data_queue_data_i        (csr_tti_tx_data_data),
      .csr_tti_tx_data_queue_start_thld_i  (csr_tti_tx_data_start_thld),
      .csr_tti_tx_data_queue_ready_thld_i  (csr_tti_tx_data_ready_thld_i),
      .csr_tti_tx_data_queue_ready_thld_o  (csr_tti_tx_data_ready_thld_o),
      .csr_tti_tx_data_queue_reg_rst_i     (csr_tti_tx_data_reg_rst),
      .csr_tti_tx_data_queue_reg_rst_we_o  (csr_tti_tx_data_reg_rst_we),
      .csr_tti_tx_data_queue_reg_rst_data_o(csr_tti_tx_data_reg_rst_data),
      .csr_tti_tx_data_queue_full_o        (csr_tti_tx_data_full),

      // TTI In-band Interrupt (IBI) queue
      .csr_tti_ibi_queue_req_i         (csr_tti_ibi_req),
      .csr_tti_ibi_queue_ack_o         (csr_tti_ibi_ack),
      .csr_tti_ibi_queue_data_i        (csr_tti_ibi_data),
      .csr_tti_ibi_queue_ready_thld_i  (csr_tti_ibi_ready_thld),
      .csr_tti_ibi_queue_reg_rst_i     (csr_tti_ibi_reg_rst),
      .csr_tti_ibi_queue_reg_rst_we_o  (csr_tti_ibi_reg_rst_we),
      .csr_tti_ibi_queue_reg_rst_data_o(csr_tti_ibi_reg_rst_data),

      // TTI RX descriptors queue
      .ctl_tti_rx_desc_queue_full_o(tti_rx_desc_full),
      .ctl_tti_rx_desc_queue_depth_o(tti_rx_desc_depth),
      .ctl_tti_rx_desc_queue_empty_o(tti_rx_desc_empty),
      .ctl_tti_rx_desc_queue_wvalid_i(tti_rx_desc_wvalid),
      .ctl_tti_rx_desc_queue_wready_o(tti_rx_desc_wready),
      .ctl_tti_rx_desc_queue_wdata_i(tti_rx_desc_wdata),
      .ctl_tti_rx_desc_queue_ready_thld_o(tti_rx_desc_ready_thld),
      .ctl_tti_rx_desc_queue_ready_thld_trig_o(tti_rx_desc_ready_thld_trig),

      // TTI TX descriptors queue
      .ctl_tti_tx_desc_queue_full_o(tti_tx_desc_full),
      .ctl_tti_tx_desc_queue_depth_o(tti_tx_desc_depth),
      .ctl_tti_tx_desc_queue_empty_o(tti_tx_desc_empty),
      .ctl_tti_tx_desc_queue_rvalid_o(tti_tx_desc_rvalid),
      .ctl_tti_tx_desc_queue_rready_i(tti_tx_desc_rready),
      .ctl_tti_tx_desc_queue_rdata_o(tti_tx_desc_rdata),
      .ctl_tti_tx_desc_queue_ready_thld_o(tti_tx_desc_ready_thld),
      .ctl_tti_tx_desc_queue_ready_thld_trig_o(tti_tx_desc_ready_thld_trig),

      // TTI RX data queue
      .ctl_tti_rx_data_queue_full_o(tti_rx_full),
      .ctl_tti_rx_data_queue_depth_o(tti_rx_depth),
      .ctl_tti_rx_data_queue_empty_o(tti_rx_empty),
      .ctl_tti_rx_data_queue_wvalid_i(tti_rx_wvalid),
      .ctl_tti_rx_data_queue_wready_o(tti_rx_wready),
      .ctl_tti_rx_data_queue_wdata_i(tti_rx_wdata),
      .ctl_tti_rx_data_queue_flush_i(tti_rx_flush),
      .ctl_tti_rx_data_queue_start_thld_o(tti_rx_start_thld),
      .ctl_tti_rx_data_queue_start_thld_trig_o(tti_rx_start_thld_trig),
      .ctl_tti_rx_data_queue_ready_thld_o(tti_rx_ready_thld),
      .ctl_tti_rx_data_queue_ready_thld_trig_o(tti_rx_ready_thld_trig),

      // TTI TX data queue
      .ctl_tti_tx_data_queue_full_o(tti_tx_full),
      .ctl_tti_tx_data_queue_depth_o(tti_tx_depth),
      .ctl_tti_tx_data_queue_empty_o(tti_tx_empty),
      .ctl_tti_tx_data_queue_rvalid_o(tti_tx_rvalid),
      .ctl_tti_tx_data_queue_rready_i(tti_tx_rready),
      .ctl_tti_tx_data_queue_rdata_o(tti_tx_rdata),
      .ctl_tti_tx_data_queue_flush_i(tti_tx_flush),
      .ctl_tti_tx_data_queue_start_thld_o(tti_tx_start_thld),
      .ctl_tti_tx_data_queue_start_thld_trig_o(tti_tx_start_thld_trig),
      .ctl_tti_tx_data_queue_ready_thld_o(tti_tx_ready_thld),
      .ctl_tti_tx_data_queue_ready_thld_trig_o(tti_tx_ready_thld_trig),
      .ctl_tti_tx_host_nack_i(tti_tx_host_nack),

      // TTI In-band Interrupt (IBI) queue
      .ctl_tti_ibi_queue_full_o(tti_ibi_full),
      .ctl_tti_ibi_queue_depth_o(tti_ibi_depth),
      .ctl_tti_ibi_queue_empty_o(tti_ibi_empty),
      .ctl_tti_ibi_queue_rvalid_o(tti_ibi_rvalid),
      .ctl_tti_ibi_queue_rready_i(tti_ibi_rready),
      .ctl_tti_ibi_queue_rdata_o(tti_ibi_rdata),
      .ctl_tti_ibi_queue_ready_thld_o(tti_ibi_ready_thld),
      .ctl_tti_ibi_queue_ready_thld_trig_o(tti_ibi_ready_thld_trig),

      .irq_o(recovery_irq),

      // Recovery status signals
      .payload_available_o(recovery_payload_available_o),
      .image_activated_o  (recovery_image_activated_o),

      // I2C/I3C bus condition detection
      .ctl_bus_start_i(bus_start | bus_rstart),
      .ctl_bus_stop_i (bus_stop),

      // Received I2C/I3C address along with RnW# bit
      .ctl_bus_addr_i(rx_bus_addr),
      .ctl_bus_addr_valid_i(rx_bus_addr_valid),
      .recovery_mode_enter_o(recovery_mode_enter),
      .recovery_mode_enabled_o(recovery_mode_enabled),
      .virtual_device_sel_i(virtual_device_sel),
      .xfer_in_progress_i(xfer_in_progress)
  );

  // I3C PHY
  i3c_phy xphy (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      .scl_i(i3c_scl_i),
      .scl_o(i3c_scl_o),
      .sda_i(i3c_sda_i),
      .sda_o(i3c_sda_o),
      .ctrl_scl_i(ctrl2phy_scl),
      .ctrl_sda_i(ctrl2phy_sda),
      .ctrl_scl_o(phy2ctrl_scl),
      .ctrl_sda_o(phy2ctrl_sda),
      .sel_od_pp_i(ctrl_sel_od_pp),
      .sel_od_pp_o(sel_od_pp_o)
  );

/*
  Truth table for SDA output enable.

  sel_od_pp_o | i3c_sda_o || i3c_sda_oe_o | IO state
  ------------+-----------++--------+-----------
       0      |     0     ||   1    |    0
       0      |     1     ||   0    |   hi-z
       1      |     0     ||   1    |    0
       1      |     1     ||   1    |    1
*/

  assign i3c_sda_oe_o = sel_od_pp_o || !i3c_sda_o;
  assign i3c_scl_oe_o = i3c_active_en && (sel_od_pp_o || !i3c_scl_o);

  // Aggregate interrupts
  assign irq_o = ctl_irq | tti_irq | recovery_irq;

endmodule
