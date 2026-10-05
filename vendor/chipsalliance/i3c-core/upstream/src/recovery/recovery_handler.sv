// SPDX-License-Identifier: Apache-2.0

//==============================================================================
// Module: recovery_handler
//
// Description:
//   Top-level handler for OCP Secure Firmware Recovery Interface.
//   This module:
//   - Muxes TTI queues between normal operation and recovery mode
//   - Manages recovery mode detection via DEVICE_STATUS CSR
//   - Instantiates width converters (8-to-N and N-to-8) for data paths
//   - Instantiates recovery_receiver for protocol handling
//   - Manages PEC (Packet Error Check) computation for RX/TX
//   - Provides indirect FIFO for firmware data buffer
//   - Supports bypass mode for SoC direct access
//
// Recovery Mode Flow:
//   1. Virtual device selection triggers recovery_pending
//   2. TTI queues are muxed to recovery_receiver
//   3. Protocol commands are parsed and executed
//   4. Firmware data flows through indirect FIFO
//
//==============================================================================

module recovery_handler
  import i3c_pkg::*;
#(

    parameter int unsigned TtiRxDescDataWidth = 32,
    parameter int unsigned TtiRxDescThldWidth = 8,
    parameter int unsigned TtiRxDescFifoDepth = 64,
    localparam int unsigned TtiRxDescFifoDepthWidth = $clog2(TtiRxDescFifoDepth + 1),

    parameter int unsigned TtiTxDescDataWidth = 32,
    parameter int unsigned TtiTxDescThldWidth = 8,
    parameter int unsigned TtiTxDescFifoDepth = 64,
    localparam int unsigned TtiTxDescFifoDepthWidth = $clog2(TtiTxDescFifoDepth + 1),

    parameter int unsigned TtiRxDataDataWidth = 32,
    parameter int unsigned TtiRxDataThldWidth = 3,
    parameter int unsigned TtiRxDataFifoDepth = 64,
    localparam int unsigned TtiRxDataFifoDepthWidth = $clog2(TtiRxDataFifoDepth + 1),

    parameter int unsigned TtiTxDataDataWidth = 32,
    parameter int unsigned TtiTxDataThldWidth = 3,
    parameter int unsigned TtiTxDataFifoDepth = 64,
    localparam int unsigned TtiTxDataFifoDepthWidth = $clog2(TtiTxDataFifoDepth + 1),

    parameter int unsigned TtiIbiDataWidth = 32,
    parameter int unsigned TtiIbiThldWidth = 8,
    parameter int unsigned TtiIbiFifoDepth = 64,
    localparam int unsigned TtiIbiFifoDepthWidth = $clog2(TtiIbiFifoDepth + 1),

    parameter int unsigned CsrDataWidth = 32,

    parameter int unsigned IndirectFifoDepth = 64

) (
    input logic clk_i,  // Clock
    input logic rst_ni, // Reset (active low)

    // ....................................................
    // TTI interface (controller side)

    // RX Descriptor queue
    output logic                               ctl_tti_rx_desc_queue_full_o,
    output logic [TtiRxDescFifoDepthWidth-1:0] ctl_tti_rx_desc_queue_depth_o,
    output logic                               ctl_tti_rx_desc_queue_empty_o,
    input  logic                               ctl_tti_rx_desc_queue_wvalid_i,
    output logic                               ctl_tti_rx_desc_queue_wready_o,
    input  logic [     TtiRxDescDataWidth-1:0] ctl_tti_rx_desc_queue_wdata_i,
    output logic [     TtiRxDescThldWidth-1:0] ctl_tti_rx_desc_queue_ready_thld_o,
    output logic                               ctl_tti_rx_desc_queue_ready_thld_trig_o,

    // TX Descriptor queue
    output logic                               ctl_tti_tx_desc_queue_full_o,
    output logic [TtiTxDescFifoDepthWidth-1:0] ctl_tti_tx_desc_queue_depth_o,
    output logic                               ctl_tti_tx_desc_queue_empty_o,
    output logic                               ctl_tti_tx_desc_queue_rvalid_o,
    input  logic                               ctl_tti_tx_desc_queue_rready_i,
    output logic [     TtiTxDescDataWidth-1:0] ctl_tti_tx_desc_queue_rdata_o,
    output logic [     TtiTxDescThldWidth-1:0] ctl_tti_tx_desc_queue_ready_thld_o,
    output logic                               ctl_tti_tx_desc_queue_ready_thld_trig_o,

    // RX Data queue
    output logic                               ctl_tti_rx_data_queue_full_o,
    output logic [TtiRxDataFifoDepthWidth-1:0] ctl_tti_rx_data_queue_depth_o,
    output logic                               ctl_tti_rx_data_queue_empty_o,
    input  logic                               ctl_tti_rx_data_queue_wvalid_i,
    output logic                               ctl_tti_rx_data_queue_wready_o,
    input  logic [                        7:0] ctl_tti_rx_data_queue_wdata_i,
    input  logic                               ctl_tti_rx_data_queue_flush_i,
    input  logic                               ctl_tti_rx_data_queue_wlast_i,
    output logic [     TtiRxDataThldWidth-1:0] ctl_tti_rx_data_queue_start_thld_o,
    output logic                               ctl_tti_rx_data_queue_start_thld_trig_o,
    output logic [     TtiRxDataThldWidth-1:0] ctl_tti_rx_data_queue_ready_thld_o,
    output logic                               ctl_tti_rx_data_queue_ready_thld_trig_o,

    // TX Data queue
    output logic                               ctl_tti_tx_data_queue_full_o,
    output logic [TtiTxDataFifoDepthWidth-1:0] ctl_tti_tx_data_queue_depth_o,
    output logic                               ctl_tti_tx_data_queue_empty_o,
    output logic                               ctl_tti_tx_data_queue_rvalid_o,
    input  logic                               ctl_tti_tx_data_queue_rready_i,
    output logic [                        7:0] ctl_tti_tx_data_queue_rdata_o,
    input  logic                               ctl_tti_tx_data_queue_flush_i,
    output logic [     TtiTxDataThldWidth-1:0] ctl_tti_tx_data_queue_start_thld_o,
    output logic                               ctl_tti_tx_data_queue_start_thld_trig_o,
    output logic [     TtiTxDataThldWidth-1:0] ctl_tti_tx_data_queue_ready_thld_o,
    output logic                               ctl_tti_tx_data_queue_ready_thld_trig_o,
    input  logic                               ctl_tti_tx_host_nack_i,

    // In-band Interrupt (IBI) queue
    output logic                            ctl_tti_ibi_queue_full_o,
    output logic [TtiIbiFifoDepthWidth-1:0] ctl_tti_ibi_queue_depth_o,
    output logic                            ctl_tti_ibi_queue_empty_o,
    output logic                            ctl_tti_ibi_queue_rvalid_o,
    input  logic                            ctl_tti_ibi_queue_rready_i,
    output logic [     TtiIbiDataWidth-1:0] ctl_tti_ibi_queue_rdata_o,
    output logic [     TtiIbiThldWidth-1:0] ctl_tti_ibi_queue_ready_thld_o,
    output logic                            ctl_tti_ibi_queue_ready_thld_trig_o,

    // S/Sr and P bus condition
    input logic ctl_bus_start_i,   // Start condition (S)
    input logic ctl_bus_rstart_i,  // Repeated Start condition (Sr)
    input logic ctl_bus_stop_i,
    input logic ctl_in_hdr_mode_i,

    // Received I2C/I3C address along with RnW# bit
    input logic [7:0] ctl_bus_addr_i,
    input logic ctl_bus_addr_valid_i,

    // ....................................................
    // TTI interface (CSR side)

    // RX Descriptor queue
    input  logic                          csr_tti_rx_desc_queue_req_i,
    output logic                          csr_tti_rx_desc_queue_ack_o,
    output logic [TtiRxDescDataWidth-1:0] csr_tti_rx_desc_queue_data_o,
    input  logic [TtiRxDescThldWidth-1:0] csr_tti_rx_desc_queue_ready_thld_i,
    output logic [TtiRxDescThldWidth-1:0] csr_tti_rx_desc_queue_ready_thld_o,
    input  logic                          csr_tti_rx_desc_queue_reg_rst_i,
    output logic                          csr_tti_rx_desc_queue_reg_rst_we_o,
    output logic                          csr_tti_rx_desc_queue_reg_rst_data_o,
    output logic                          csr_tti_rx_desc_queue_ready_thld_trig_o,

    // TX Descriptor queue
    output logic                          csr_tti_tx_desc_queue_full_o,
    input  logic                          csr_tti_tx_desc_queue_req_i,
    output logic                          csr_tti_tx_desc_queue_ack_o,
    input  logic [      CsrDataWidth-1:0] csr_tti_tx_desc_queue_data_i,
    input  logic [TtiTxDescThldWidth-1:0] csr_tti_tx_desc_queue_ready_thld_i,
    output logic [TtiTxDescThldWidth-1:0] csr_tti_tx_desc_queue_ready_thld_o,
    input  logic                          csr_tti_tx_desc_queue_reg_rst_i,
    output logic                          csr_tti_tx_desc_queue_reg_rst_we_o,
    output logic                          csr_tti_tx_desc_queue_reg_rst_data_o,

    // RX data queue
    input  logic                          csr_tti_rx_data_queue_req_i,
    output logic                          csr_tti_rx_data_queue_ack_o,
    output logic [TtiRxDataDataWidth-1:0] csr_tti_rx_data_queue_data_o,
    input  logic [TtiRxDataThldWidth-1:0] csr_tti_rx_data_queue_start_thld_i,
    input  logic [TtiRxDataThldWidth-1:0] csr_tti_rx_data_queue_ready_thld_i,
    output logic [TtiRxDataThldWidth-1:0] csr_tti_rx_data_queue_ready_thld_o,
    input  logic                          csr_tti_rx_data_queue_reg_rst_i,
    output logic                          csr_tti_rx_data_queue_reg_rst_we_o,
    output logic                          csr_tti_rx_data_queue_reg_rst_data_o,
    output logic                          csr_tti_rx_data_queue_ready_thld_trig_o,

    // TX data queue
    output logic                          csr_tti_tx_data_queue_full_o,
    input  logic                          csr_tti_tx_data_queue_req_i,
    output logic                          csr_tti_tx_data_queue_ack_o,
    input  logic [      CsrDataWidth-1:0] csr_tti_tx_data_queue_data_i,
    input  logic [TtiTxDataThldWidth-1:0] csr_tti_tx_data_queue_start_thld_i,
    input  logic [TtiTxDataThldWidth-1:0] csr_tti_tx_data_queue_ready_thld_i,
    output logic [TtiTxDataThldWidth-1:0] csr_tti_tx_data_queue_ready_thld_o,
    input  logic                          csr_tti_tx_data_queue_reg_rst_i,
    output logic                          csr_tti_tx_data_queue_reg_rst_we_o,
    output logic                          csr_tti_tx_data_queue_reg_rst_data_o,

    // In-band Interrupt (IBI) queue
    input  logic                       csr_tti_ibi_queue_req_i,
    output logic                       csr_tti_ibi_queue_ack_o,
    input  logic [   CsrDataWidth-1:0] csr_tti_ibi_queue_data_i,
    input  logic [TtiIbiThldWidth-1:0] csr_tti_ibi_queue_ready_thld_i,
    input  logic                       csr_tti_ibi_queue_reg_rst_i,
    output logic                       csr_tti_ibi_queue_reg_rst_we_o,
    output logic                       csr_tti_ibi_queue_reg_rst_data_o,

    // ....................................................
    // SoC Managment CSR interface
    input  I3CCSR_pkg::I3CCSR__I3C_EC__SoCMgmtIf__out_t hwif_socmgmt_i,
    output I3CCSR_pkg::I3CCSR__I3C_EC__SoCMgmtIf__in_t  hwif_socmgmt_o,

    // Recovery CSR interface
    input  I3CCSR_pkg::I3CCSR__I3C_EC__SecFwRecoveryIf__out_t hwif_rec_i,
    output I3CCSR_pkg::I3CCSR__I3C_EC__SecFwRecoveryIf__in_t  hwif_rec_o,

    input logic bypass_i3c_core_i,

    // ....................................................

    // Interrupt
    output logic irq_o,

    // Recovery status
    output logic payload_available_o,
    output logic image_activated_o,
    input  logic virtual_device_sel_i,
    input  logic xfer_in_progress_i,

    // Error detection enables (from TTI CSR)
    input  logic pec_err_det_en_i,
    input  logic length_err_det_en_i,
    input  logic readonly_err_det_en_i,
    input  logic unsupported_err_det_en_i,
    input  logic rx_fifo_overflow_err_det_en_i,
    input  logic indirect_fifo_overflow_err_det_en_i,

    // Error outputs (from recovery_receiver)
    output logic pec_err_o,          // PEC/CRC mismatch error
    output logic length_err_o,       // Length mismatch error
    output logic readonly_err_o,     // Write to read-only error
    output logic unsupported_err_o,  // Unsupported command error
    output logic rx_fifo_overflow_err_o,       // RX FIFO overflow error (always reported)
    output logic indirect_fifo_overflow_err_o  // INDIRECT_FIFO overflow error
);

  //============================================================================
  //
  // SECTION 1: PARAMETERS
  //
  //============================================================================

  localparam int unsigned RecoveryMode = 'h3;

  //============================================================================
  //
  // SECTION 2: SIGNAL DECLARATIONS
  //
  //============================================================================

  //----------------------------------------------------------------------------
  // Recovery Mode Control Signals
  //----------------------------------------------------------------------------
  logic        recovery_mode_csr_active;  // True when DEVICE_STATUS indicates Recovery Mode
  logic        recovery_xfer_pending;     // Transfer in progress to recovery device
  logic        recovery_exec_pending;     // Recovery command execution in progress
  logic        recovery_pending;          // Combined recovery active flag
  logic        virtual_device_sel_q;      // Delayed virtual device select (race fix)
  logic        virtual_target_active;     // Virtual target currently addressed
  logic        virtual_target_active_q;   // Delayed virtual target active
  logic        virtual_target_start;      // Pulse on virtual target start
  logic        ctl_bus_addr_valid_q;      // Delayed address valid for posedge detect
  logic        ctl_bus_addr_valid_posedge;      // Posedge of address valid
  logic        ctl_bus_addr_valid_posedge_q;    // Delayed posedge aligned with virtual_device_sel_i
  logic        other_target_start;        // Pulse when other target is addressed

  //----------------------------------------------------------------------------
  // TTI RX Descriptor Queue Signals
  //----------------------------------------------------------------------------
  logic                               tti_rx_desc_queue_full;
  logic [TtiRxDescFifoDepthWidth-1:0] tti_rx_desc_queue_depth;
  logic                               unused_tti_rx_desc_start_thld_trig;
  logic                               tti_rx_desc_queue_empty;
  logic                               tti_rx_desc_queue_wvalid;
  logic                               tti_rx_desc_queue_wready;
  logic [     TtiRxDescDataWidth-1:0] tti_rx_desc_queue_wdata;
  logic                               tti_rx_desc_queue_ready_thld_trig;
  logic                               tti_rx_desc_queue_req;
  logic                               tti_rx_desc_queue_ack;
  logic [     TtiRxDescDataWidth-1:0] tti_rx_desc_queue_data;
  logic [     TtiRxDescThldWidth-1:0] tti_rx_desc_queue_ready_thld_i;
  logic [     TtiRxDescThldWidth-1:0] tti_rx_desc_queue_ready_thld_o;
  logic                               tti_rx_desc_queue_reg_rst;
  logic                               tti_rx_desc_queue_reg_rst_we;
  logic                               tti_rx_desc_queue_reg_rst_data;

  //----------------------------------------------------------------------------
  // TTI TX Descriptor Queue Signals
  //----------------------------------------------------------------------------
  logic                               tti_tx_desc_queue_full;
  logic [TtiTxDescFifoDepthWidth-1:0] tti_tx_desc_queue_depth;
  logic                               tti_tx_desc_queue_empty;
  logic                               tti_tx_desc_queue_rvalid;
  logic                               tti_tx_desc_queue_rready;
  logic [     TtiTxDescDataWidth-1:0] tti_tx_desc_queue_rdata;
  logic                               tti_tx_desc_queue_ready_thld_trig;
  logic                               tti_tx_desc_queue_req;
  logic                               tti_tx_desc_queue_ack;
  logic [     TtiTxDescDataWidth-1:0] tti_tx_desc_queue_data;
  logic [     TtiTxDescThldWidth-1:0] tti_tx_desc_queue_ready_thld_i;
  logic [     TtiTxDescThldWidth-1:0] tti_tx_desc_queue_ready_thld_o;
  logic                               tti_tx_desc_queue_reg_rst;
  logic                               tti_tx_desc_queue_reg_rst_we;
  logic                               tti_tx_desc_queue_reg_rst_data;

  //----------------------------------------------------------------------------
  // TTI RX Data Queue Signals
  //----------------------------------------------------------------------------
  logic                               tti_rx_data_queue_full;
  logic [TtiRxDataFifoDepthWidth-1:0] tti_rx_data_queue_depth;
  logic                               tti_rx_data_queue_empty;
  logic                               tti_rx_data_queue_wvalid;
  logic                               tti_rx_data_queue_wready;
  logic [                        7:0] tti_rx_data_queue_wdata;
  logic                               tti_rx_data_queue_flush;
  logic                               tti_rx_data_queue_start_thld_trig;
  logic                               tti_rx_data_queue_ready_thld_trig;
  logic                               tti_rx_data_queue_req;
  logic                               tti_rx_data_queue_ack;
  logic [     TtiRxDataDataWidth-1:0] tti_rx_data_queue_data;
  logic [     TtiRxDataThldWidth-1:0] tti_rx_data_queue_start_thld;
  logic [     TtiRxDataThldWidth-1:0] tti_rx_data_queue_ready_thld_i;
  logic [     TtiRxDataThldWidth-1:0] tti_rx_data_queue_ready_thld_o;
  logic                               tti_rx_data_queue_reg_rst;
  logic                               tti_rx_data_queue_reg_rst_we;
  logic                               tti_rx_data_queue_reg_rst_next;

  //----------------------------------------------------------------------------
  // TTI TX Data Queue Signals
  //----------------------------------------------------------------------------
  logic                               tti_tx_data_queue_full;
  logic [TtiTxDataFifoDepthWidth-1:0] tti_tx_data_queue_depth;
  logic                               tti_tx_data_queue_empty;
  logic                               tti_tx_data_queue_rvalid;
  logic                               tti_tx_data_queue_rready;
  logic [                       31:0] tti_tx_data_queue_rdata;
  logic                               tti_tx_data_queue_start_thld_trig;
  logic                               tti_tx_data_queue_ready_thld_trig;
  logic                               tti_tx_data_queue_req;
  logic                               tti_tx_data_queue_ack;
  logic [     TtiTxDataDataWidth-1:0] tti_tx_data_queue_data;
  logic [     TtiTxDataThldWidth-1:0] tti_tx_data_queue_start_thld;
  logic [     TtiTxDataThldWidth-1:0] tti_tx_data_queue_ready_thld_i;
  logic [     TtiTxDataThldWidth-1:0] tti_tx_data_queue_ready_thld_o;
  logic                               tti_tx_data_queue_reg_rst;
  logic                               tti_tx_data_queue_reg_rst_we;
  logic                               tti_tx_data_queue_reg_rst_next;

  //----------------------------------------------------------------------------
  // RX FIFO Overflow Detection
  //----------------------------------------------------------------------------
  // Detect overflow when controller tries to write but FIFO is not ready
  logic rx_fifo_overflow_raw;

  //----------------------------------------------------------------------------
  // Width Converter Signals (8-to-N and N-to-8)
  //----------------------------------------------------------------------------
  // 8toN Converter -> TTI RX Data Queue
  logic                          tti_rx_data_queue_wvalid_q;
  logic                          tti_rx_data_queue_wready_q;
  logic [TtiRxDataDataWidth-1:0] tti_rx_data_queue_wdata_q;

  // TTI TX Data Queue -> Nto8 Converter
  logic                          tti_tx_data_queue_rvalid_conv_sink;
  logic                          tti_tx_data_queue_rready_conv_sink;
  logic [TtiTxDataDataWidth-1:0] tti_tx_data_queue_rdata_conv_sink;

  // Nto8 Converter -> I3C Controller
  logic                          tti_tx_data_queue_rvalid_conv_source;
  logic                          tti_tx_data_queue_rready_conv_source;
  logic [                   7:0] tti_tx_data_queue_rdata_conv_source;
  logic                          tti_tx_data_queue_flush_conv_source;

  //----------------------------------------------------------------------------
  // Recovery Receiver Interface Signals
  //----------------------------------------------------------------------------
  // TX descriptor interface from receiver
  logic                          send_tti_tx_desc_valid;
  logic                          send_tti_tx_desc_ready;
  logic [TtiTxDescDataWidth-1:0] send_tti_tx_desc_data;

  // RX data interface to receiver
  logic       recv_tti_rx_data_valid;
  logic       recv_tti_rx_data_ready;
  logic [7:0] recv_tti_rx_data_data;
  logic       recv_tti_rx_data_last;
  logic       recv_tti_rx_data_queue_select;
  logic       recv_tti_rx_data_queue_flush;
  logic       recv_conv_soft_reset;

  // TX data interface from receiver
  logic       send_tti_tx_data_valid;
  logic       send_tti_tx_data_ready;
  logic [7:0] send_tti_tx_data_data;
  logic       send_tti_tx_data_queue_select;
  logic       send_tti_tx_start_trig;

  // Execution interface to receiver
  logic                          exec_tti_rx_data_req;
  logic                          exec_tti_rx_data_ack;
  logic [TtiRxDataDataWidth-1:0] exec_tti_rx_data_data;
  logic                          exec_tti_rx_queue_sel;
  logic                          exec_tti_rx_desc_queue_clr;
  logic                          exec_tti_tx_desc_queue_clr;
  logic                          exec_tti_rx_data_queue_clr;
  logic                          exec_tti_tx_data_queue_clr;
  logic                          exec_tti_rx_data_ready;

  //----------------------------------------------------------------------------
  // Indirect FIFO Signals
  //----------------------------------------------------------------------------
  logic                          indirect_rx_wvalid;
  logic                          indirect_rx_wvalid_muxed;
  logic                          indirect_rx_wready;
  logic [TtiRxDataDataWidth-1:0] indirect_rx_wdata;
  logic [TtiRxDataDataWidth-1:0] indirect_rx_wdata_muxed;
  logic                          indirect_rx_rreq;
  logic                          indirect_rx_rack;
  logic [      CsrDataWidth-1:0] indirect_rx_rdata;
  logic                          indirect_rx_clr;
  logic                          indirect_rx_full;
  logic                          indirect_rx_empty;
  logic                          allow_indirect_write;
  logic                          allow_indirect_read;

  //----------------------------------------------------------------------------
  // PEC Computation Signals
  //----------------------------------------------------------------------------
  // RX PEC
  logic        ctl_bus_any_start;
  logic [7:0]  rx_pec_data;
  logic [7:0]  rx_pec_crc;
  logic        rx_pec_enable;
  logic        rx_pec_init;

  // TX PEC
  logic [7:0]  tx_pec_data;
  logic [7:0]  tx_pec_crc;
  logic        tx_pec_enable;
  logic        tx_pec_init;
  logic        tx_pec_soft_rst_n;

  //----------------------------------------------------------------------------
  // Unused Signals
  //----------------------------------------------------------------------------
  logic unused_tx_desc_start_thld_trig;
  logic unused_ibi_queue_start_thld_trig;

  //============================================================================
  //
  // SECTION 3: STATIC ASSIGNMENTS
  //
  //============================================================================

  // Recovery mode does not generate interrupts
  assign irq_o = '0;

  //============================================================================
  //
  // SECTION 4: RECOVERY MODE CONTROL
  //
  //============================================================================

  //----------------------------------------------------------------------------
  // Recovery Mode Detection
  // recovery_mode_csr_active: True when DEVICE_STATUS CSR indicates Recovery Mode (0x3)
  // This is used internally for command validation (some commands only valid in recovery mode)
  //----------------------------------------------------------------------------
  assign recovery_mode_csr_active = (hwif_rec_i.DEVICE_STATUS_0.DEV_STATUS.value == RecoveryMode);

  //----------------------------------------------------------------------------
  // Delayed Signal Registers
  // Single process for all 1-cycle delayed versions of control signals:
  // - virtual_device_sel_q: Extends recovery_pending by 1 cycle (see FUTUREFIX below)
  // - virtual_target_active_q: For edge detection on virtual target addressing
  // - ctl_bus_addr_valid_q: For posedge detection of address valid
  // - ctl_bus_addr_valid_posedge_q: Delayed posedge aligned with virtual_device_sel_i
  //
  // The flush race is resolved in descriptor_rx (flush fires on transfer_ended cycle).
  //----------------------------------------------------------------------------
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      virtual_device_sel_q         <= 1'b0;
      virtual_target_active_q      <= 1'b0;
      ctl_bus_addr_valid_q         <= 1'b0;
      ctl_bus_addr_valid_posedge_q <= 1'b0;
    end else begin
      virtual_device_sel_q         <= virtual_device_sel_i;
      virtual_target_active_q      <= virtual_target_active;
      ctl_bus_addr_valid_q         <= ctl_bus_addr_valid_i;
      ctl_bus_addr_valid_posedge_q <= ctl_bus_addr_valid_posedge;
    end
  end

  //----------------------------------------------------------------------------
  // Recovery Pending Logic
  //----------------------------------------------------------------------------
  assign recovery_xfer_pending = xfer_in_progress_i && (virtual_device_sel_i || virtual_device_sel_q);
  assign recovery_pending = recovery_xfer_pending | recovery_exec_pending;

  //----------------------------------------------------------------------------
  // Virtual Target Start Detection
  // Generates pulse on rising edge of virtual target being addressed (handles Sr)
  //----------------------------------------------------------------------------
  assign virtual_target_active = ctl_bus_addr_valid_i && virtual_device_sel_i;
  assign virtual_target_start = virtual_target_active && !virtual_target_active_q;

  //----------------------------------------------------------------------------
  // Other Target Start Detection
  // Generates pulse when a different target (not virtual device) is addressed.
  // Used to detect protocol errors like Sr + Addr(other) during READ command.
  //
  // Timing: ctl_bus_addr_valid_i asserts 1 cycle before virtual_device_sel_i
  // is updated, and they deassert on the same cycle. We detect posedge of
  // ctl_bus_addr_valid_i and delay it by 1 cycle to align with virtual_device_sel_i.
  //
  // Cycle N:   ctl_bus_addr_valid_i rises (0→1), virtual_device_sel_i = old
  // Cycle N+1: posedge_q fires, virtual_device_sel_i = updated (valid)
  //            → other_target_start = posedge_q && !virtual_device_sel_i
  //----------------------------------------------------------------------------
  // Posedge detect: was 0 last cycle, is 1 this cycle (fires on cycle N)
  assign ctl_bus_addr_valid_posedge = ctl_bus_addr_valid_i && !ctl_bus_addr_valid_q;

  // Other target addressed: delayed posedge (aligned) but not for us
  assign other_target_start = ctl_bus_addr_valid_posedge_q && !virtual_device_sel_i;

  //============================================================================
  //
  // SECTION 5: WIDTH CONVERTERS
  //
  //============================================================================

  width_converter_8toN #(
      .Width(TtiRxDataDataWidth)

  ) tti_conv_8toN (
      .clk_i,
      .rst_ni(rst_ni),
      .soft_reset_ni(~bypass_i3c_core_i & ~recv_conv_soft_reset & ~tti_rx_data_queue_reg_rst),

      .sink_valid_i(tti_rx_data_queue_wvalid),
      .sink_ready_o(tti_rx_data_queue_wready),
      .sink_data_i (tti_rx_data_queue_wdata),
      .sink_flush_i(tti_rx_data_queue_flush),

      .source_valid_o(tti_rx_data_queue_wvalid_q),
      .source_ready_i(tti_rx_data_queue_wready_q),
      .source_data_o (tti_rx_data_queue_wdata_q)
  );

  width_converter_Nto8 #(
      .Width(TtiRxDataDataWidth)

  ) tti_conv_Nto8 (
      .clk_i,
      .rst_ni(rst_ni),
      .soft_reset_ni(~bypass_i3c_core_i & ~recv_conv_soft_reset),

      .sink_valid_i(tti_tx_data_queue_rvalid_conv_sink),
      .sink_ready_o(tti_tx_data_queue_rready_conv_sink),
      .sink_data_i (tti_tx_data_queue_rdata_conv_sink),

      .source_valid_o(tti_tx_data_queue_rvalid_conv_source),
      .source_ready_i(tti_tx_data_queue_rready_conv_source),
      .source_data_o (tti_tx_data_queue_rdata_conv_source),
      .source_flush_i(tti_tx_data_queue_flush_conv_source)
  );

  //============================================================================
  //
  // SECTION 6: TTI QUEUES INSTANTIATION
  //
  //============================================================================

  queues #(

      .CsrDataWidth(CsrDataWidth),

      .TxDescFifoDepth(TtiTxDescFifoDepth),
      .RxDescFifoDepth(TtiRxDescFifoDepth),
      .TxFifoDepth    (TtiTxDataFifoDepth),
      .RxFifoDepth    (TtiRxDataFifoDepth),

      .TxDescFifoDataWidth(TtiTxDescDataWidth),
      .RxDescFifoDataWidth(TtiRxDescDataWidth),
      .TxFifoDataWidth    (TtiTxDataDataWidth),
      .RxFifoDataWidth    (TtiRxDataDataWidth),

      .TxDescFifoThldWidth(TtiTxDescThldWidth),
      .RxDescFifoThldWidth(TtiRxDescThldWidth),
      .TxFifoThldWidth    (TtiTxDataThldWidth),
      .RxFifoThldWidth    (TtiRxDataThldWidth)

  ) tti_queues (

      .clk_i,
      .rst_ni,

      // RX descriptor queue
      .rx_desc_full_o(tti_rx_desc_queue_full),
      .rx_desc_depth_o(tti_rx_desc_queue_depth),
      .rx_desc_start_thld_trig_o(unused_tti_rx_desc_start_thld_trig),  // Intentionally left hanging, unsupported by TTI RX Desc Queue
      .rx_desc_ready_thld_trig_o(tti_rx_desc_queue_ready_thld_trig),
      .rx_desc_empty_o(tti_rx_desc_queue_empty),
      .rx_desc_wvalid_i(tti_rx_desc_queue_wvalid),
      .rx_desc_wready_o(tti_rx_desc_queue_wready),
      .rx_desc_wdata_i(tti_rx_desc_queue_wdata),

      .rx_desc_req_i(tti_rx_desc_queue_req),
      .rx_desc_ack_o(tti_rx_desc_queue_ack),
      .rx_desc_data_o(tti_rx_desc_queue_data),
      .rx_desc_start_thld_i('0),  // Unsupported by RX Desc Queue
      .rx_desc_ready_thld_i(tti_rx_desc_queue_ready_thld_i),
      .rx_desc_ready_thld_o(tti_rx_desc_queue_ready_thld_o),
      .rx_desc_reg_rst_i(tti_rx_desc_queue_reg_rst),
      .rx_desc_reg_rst_we_o(tti_rx_desc_queue_reg_rst_we),
      .rx_desc_reg_rst_data_o(tti_rx_desc_queue_reg_rst_data),

      // TX descriptor queue
      .tx_desc_full_o(tti_tx_desc_queue_full),
      .tx_desc_depth_o(tti_tx_desc_queue_depth),
      .tx_desc_start_thld_trig_o(unused_tx_desc_start_thld_trig),  // Intentionally left hanging, unsupported by TTI TX Desc Queue
      .tx_desc_ready_thld_trig_o(tti_tx_desc_queue_ready_thld_trig),
      .tx_desc_empty_o(tti_tx_desc_queue_empty),
      .tx_desc_rvalid_o(tti_tx_desc_queue_rvalid),
      .tx_desc_rready_i(tti_tx_desc_queue_rready),
      .tx_desc_rdata_o(tti_tx_desc_queue_rdata),

      .tx_desc_req_i(tti_tx_desc_queue_req),
      .tx_desc_ack_o(tti_tx_desc_queue_ack),
      .tx_desc_data_i(tti_tx_desc_queue_data),
      .tx_desc_start_thld_i('0),  // Unsupported by TX Desc Queue
      .tx_desc_ready_thld_i(tti_tx_desc_queue_ready_thld_i),
      .tx_desc_ready_thld_o(tti_tx_desc_queue_ready_thld_o),
      .tx_desc_reg_rst_i(tti_tx_desc_queue_reg_rst),
      .tx_desc_reg_rst_we_o(tti_tx_desc_queue_reg_rst_we),
      .tx_desc_reg_rst_data_o(tti_tx_desc_queue_reg_rst_data),

      // RX data queue
      .rx_full_o(tti_rx_data_queue_full),
      .rx_depth_o(tti_rx_data_queue_depth),
      .rx_start_thld_trig_o(tti_rx_data_queue_start_thld_trig),
      .rx_ready_thld_trig_o(tti_rx_data_queue_ready_thld_trig),
      .rx_empty_o(tti_rx_data_queue_empty),
      .rx_wvalid_i(tti_rx_data_queue_wvalid_q),
      .rx_wready_o(tti_rx_data_queue_wready_q),
      .rx_wdata_i(tti_rx_data_queue_wdata_q),
      .rx_req_i(tti_rx_data_queue_req),
      .rx_ack_o(tti_rx_data_queue_ack),
      .rx_data_o(tti_rx_data_queue_data),
      .rx_start_thld_i(tti_rx_data_queue_start_thld),
      .rx_ready_thld_i(tti_rx_data_queue_ready_thld_i),
      .rx_ready_thld_o(tti_rx_data_queue_ready_thld_o),
      .rx_reg_rst_i(tti_rx_data_queue_reg_rst),
      .rx_reg_rst_we_o(tti_rx_data_queue_reg_rst_we),
      .rx_reg_rst_data_o(tti_rx_data_queue_reg_rst_next),

      // TX data queue
      .tx_full_o(tti_tx_data_queue_full),
      .tx_depth_o(tti_tx_data_queue_depth),
      .tx_start_thld_trig_o(tti_tx_data_queue_start_thld_trig),
      .tx_ready_thld_trig_o(tti_tx_data_queue_ready_thld_trig),
      .tx_empty_o(tti_tx_data_queue_empty),
      .tx_rvalid_o(tti_tx_data_queue_rvalid),
      .tx_rready_i(tti_tx_data_queue_rready),
      .tx_rdata_o(tti_tx_data_queue_rdata),
      .tx_req_i(tti_tx_data_queue_req & allow_indirect_write),
      .tx_ack_o(tti_tx_data_queue_ack),
      .tx_data_i(tti_tx_data_queue_data),
      .tx_start_thld_i(tti_tx_data_queue_start_thld),
      .tx_ready_thld_i(tti_tx_data_queue_ready_thld_i),
      .tx_ready_thld_o(tti_tx_data_queue_ready_thld_o),
      .tx_reg_rst_i(tti_tx_data_queue_reg_rst),
      .tx_reg_rst_we_o(tti_tx_data_queue_reg_rst_we),
      .tx_reg_rst_data_o(tti_tx_data_queue_reg_rst_next)
  );

  // IBI
  write_queue #(

      .CsrDataWidth  (CsrDataWidth),
      .Depth         (TtiIbiFifoDepth),
      .DataWidth     (TtiIbiDataWidth),
      .ThldWidth     (TtiIbiThldWidth),
      .LimitReadyThld(0),
      .ThldIsPow     (0)

  ) ibi_queue (

      .clk_i,
      .rst_ni,

      .full_o(ctl_tti_ibi_queue_full_o),
      .depth_o(ctl_tti_ibi_queue_depth_o),
      .start_thld_trig_o(unused_ibi_queue_start_thld_trig),
      .ready_thld_trig_o(ctl_tti_ibi_queue_ready_thld_trig_o),
      .empty_o(ctl_tti_ibi_queue_empty_o),
      .rvalid_o(ctl_tti_ibi_queue_rvalid_o),
      .rready_i(ctl_tti_ibi_queue_rready_i),
      .rdata_o(ctl_tti_ibi_queue_rdata_o),

      .req_i (csr_tti_ibi_queue_req_i),
      .ack_o (csr_tti_ibi_queue_ack_o),
      .data_i(csr_tti_ibi_queue_data_i),

      .start_thld_i('0),  // The IBI queue does not support start threshold
      .ready_thld_i(csr_tti_ibi_queue_ready_thld_i),
      .ready_thld_o(ctl_tti_ibi_queue_ready_thld_o),

      .reg_rst_i(csr_tti_ibi_queue_reg_rst_i),
      .reg_rst_we_o(csr_tti_ibi_queue_reg_rst_we_o),
      .reg_rst_data_o(csr_tti_ibi_queue_reg_rst_data_o)
  );

  //============================================================================
  //
  // SECTION 7: TTI QUEUE MUXING (Recovery vs Normal Mode)
  //
  //============================================================================

  //----------------------------------------------------------------------------
  // RX Descriptor Queue Mux
  //----------------------------------------------------------------------------
  always_comb begin : R1MUX
    if (recovery_pending) begin
      tti_rx_desc_queue_wvalid                = '0;
      ctl_tti_rx_desc_queue_empty_o           = 1'b1; // Need to hide empty to reject AXI reads
      csr_tti_rx_desc_queue_ready_thld_trig_o = '0;
      
      ctl_tti_rx_data_queue_empty_o           = 1'b1; // Need to hide empty to reject AXI reads
    end else begin
      tti_rx_desc_queue_wvalid                = ctl_tti_rx_desc_queue_wvalid_i;
      ctl_tti_rx_desc_queue_empty_o           = tti_rx_desc_queue_empty;
      csr_tti_rx_desc_queue_ready_thld_trig_o = tti_rx_desc_queue_ready_thld_trig;
      
      ctl_tti_rx_data_queue_empty_o           = tti_rx_data_queue_empty;
    end

    tti_rx_desc_queue_wdata                 = ctl_tti_rx_desc_queue_wdata_i; // Don't mux data, disabling valid is enough
    
    ctl_tti_rx_desc_queue_wready_o          = tti_rx_desc_queue_wready;

    // Don't hide status of queue from status registers
    ctl_tti_rx_desc_queue_full_o            = tti_rx_desc_queue_full;
    ctl_tti_rx_desc_queue_depth_o           = tti_rx_desc_queue_depth;

  end
  // Threshold
  assign ctl_tti_rx_desc_queue_ready_thld_o = tti_rx_desc_queue_ready_thld_o;
  assign ctl_tti_rx_desc_queue_ready_thld_trig_o = tti_rx_desc_queue_ready_thld_trig;

  // TX descriptor queue
  always_comb begin : T1MUX
    if (recovery_pending) begin
      send_tti_tx_desc_ready                  = ctl_tti_tx_desc_queue_rready_i;
      tti_tx_desc_queue_rready                = '0;
      ctl_tti_tx_desc_queue_full_o            = '0;
      ctl_tti_tx_desc_queue_depth_o           = '1;  // Always maximum data count available
      ctl_tti_tx_desc_queue_empty_o           = '1;  // Never empty
      ctl_tti_tx_desc_queue_rvalid_o          = send_tti_tx_desc_valid;
      ctl_tti_tx_desc_queue_rdata_o           = send_tti_tx_desc_data;
      ctl_tti_tx_desc_queue_ready_thld_trig_o = '0;
    end else begin
      send_tti_tx_desc_ready                  = '0;
      tti_tx_desc_queue_rready                = ctl_tti_tx_desc_queue_rready_i;
      ctl_tti_tx_desc_queue_full_o            = tti_tx_desc_queue_full;
      ctl_tti_tx_desc_queue_depth_o           = tti_tx_desc_queue_depth;
      ctl_tti_tx_desc_queue_empty_o           = tti_tx_desc_queue_empty;
      ctl_tti_tx_desc_queue_rvalid_o          = tti_tx_desc_queue_rvalid;
      ctl_tti_tx_desc_queue_rdata_o           = tti_tx_desc_queue_rdata;
      ctl_tti_tx_desc_queue_ready_thld_trig_o = tti_tx_desc_queue_ready_thld_trig;
    end
  end

  // Threshold
  assign ctl_tti_tx_desc_queue_ready_thld_o = tti_tx_desc_queue_ready_thld_o;

  //----------------------------------------------------------------------------
  // RX Data Queue Mux
  // When recovery_pending AND recv_tti_rx_data_queue_select = 1:
  //   Receiver consumes data directly (don't queue) - for header/PEC bytes
  // When recovery_pending AND recv_tti_rx_data_queue_select = 0:
  //   Data goes to queue - for payload bytes during recovery
  // When NOT recovery_pending:
  //   Normal private write - data always goes to queue
  //----------------------------------------------------------------------------
  always_comb begin : R2MUX
    if (recovery_pending && recv_tti_rx_data_queue_select) begin
      // Recovery active, receiver consumes directly - don't send to queue
      recv_tti_rx_data_valid                  = ctl_tti_rx_data_queue_wvalid_i;
      tti_rx_data_queue_wvalid                = '0;
      tti_rx_data_queue_flush                 = recv_tti_rx_data_queue_flush;
      ctl_tti_rx_data_queue_wready_o          = recv_tti_rx_data_ready;
      ctl_tti_rx_data_queue_start_thld_trig_o = '0;
      csr_tti_rx_data_queue_ready_thld_trig_o = '0;
    end else begin
      // Either not in recovery, or recovery payload phase - data goes to queue
      recv_tti_rx_data_valid                  = '0;
      tti_rx_data_queue_wvalid                = ctl_tti_rx_data_queue_wvalid_i;
      tti_rx_data_queue_flush                 = ctl_tti_rx_data_queue_flush_i;
      ctl_tti_rx_data_queue_wready_o          = tti_rx_data_queue_wready;
      ctl_tti_rx_data_queue_start_thld_trig_o = tti_rx_data_queue_start_thld_trig;
      csr_tti_rx_data_queue_ready_thld_trig_o = tti_rx_data_queue_ready_thld_trig;
    end

    tti_rx_data_queue_wdata                   = ctl_tti_rx_data_queue_wdata_i; // Don't mux data, disabling valid is enough
    recv_tti_rx_data_data = ctl_tti_rx_data_queue_wdata_i;
    recv_tti_rx_data_last = ctl_tti_rx_data_queue_wlast_i;

    // Don't hide status of queue from status registers
    ctl_tti_rx_data_queue_full_o            = tti_rx_data_queue_full;
    ctl_tti_rx_data_queue_depth_o           = tti_rx_data_queue_depth;
  end

  // Thresholds
  assign ctl_tti_rx_data_queue_start_thld_o = tti_rx_data_queue_start_thld;
  assign ctl_tti_rx_data_queue_ready_thld_o = tti_rx_data_queue_ready_thld_o;
  assign ctl_tti_rx_data_queue_ready_thld_trig_o = tti_rx_data_queue_ready_thld_trig;

  assign rx_fifo_overflow_raw =  tti_rx_data_queue_wvalid_q && !tti_rx_data_queue_wready_q;

  //----------------------------------------------------------------------------
  // TX Data Queue Mux
  //----------------------------------------------------------------------------
  always_comb begin : T2MUX
    if (bypass_i3c_core_i) begin
      tti_tx_data_queue_rready_conv_source    = '0;
      send_tti_tx_data_ready                  = '0;
      tti_tx_data_queue_flush_conv_source     = '0;
      ctl_tti_tx_data_queue_full_o            = '0;
      ctl_tti_tx_data_queue_depth_o           = '0;
      ctl_tti_tx_data_queue_empty_o           = '0;
      ctl_tti_tx_data_queue_rvalid_o          = '0;
      ctl_tti_tx_data_queue_rdata_o           = '0;
      ctl_tti_tx_data_queue_start_thld_trig_o = '0;
      ctl_tti_tx_data_queue_ready_thld_trig_o = '0;
    end else if (recovery_pending & send_tti_tx_data_queue_select) begin
      tti_tx_data_queue_rready_conv_source    = '0;
      send_tti_tx_data_ready                  = ctl_tti_tx_data_queue_rready_i;
      tti_tx_data_queue_flush_conv_source     = '0;
      ctl_tti_tx_data_queue_full_o            = '0;
      ctl_tti_tx_data_queue_depth_o           = '1;  // Always maximum data count available
      ctl_tti_tx_data_queue_empty_o           = '1;  // Never empty
      ctl_tti_tx_data_queue_rvalid_o          = send_tti_tx_data_valid;
      ctl_tti_tx_data_queue_rdata_o           = send_tti_tx_data_data;
      ctl_tti_tx_data_queue_start_thld_trig_o = send_tti_tx_start_trig;
      ctl_tti_tx_data_queue_ready_thld_trig_o = '0;

    end else begin
      tti_tx_data_queue_rready_conv_source    = ctl_tti_tx_data_queue_rready_i;
      tti_tx_data_queue_flush_conv_source     = ctl_tti_tx_data_queue_flush_i | tti_tx_data_queue_reg_rst;
      send_tti_tx_data_ready                  = '0;
      ctl_tti_tx_data_queue_full_o            = tti_tx_data_queue_full;
      ctl_tti_tx_data_queue_depth_o           = tti_tx_data_queue_depth;
      ctl_tti_tx_data_queue_empty_o           = tti_tx_data_queue_empty;
      ctl_tti_tx_data_queue_rvalid_o          = tti_tx_data_queue_rvalid_conv_source;
      ctl_tti_tx_data_queue_rdata_o           = tti_tx_data_queue_rdata_conv_source;
      ctl_tti_tx_data_queue_start_thld_trig_o = tti_tx_data_queue_start_thld_trig;
      ctl_tti_tx_data_queue_ready_thld_trig_o = tti_tx_data_queue_ready_thld_trig;
    end
  end

  // Thresholds
  assign ctl_tti_tx_data_queue_start_thld_o = tti_tx_data_queue_start_thld;
  assign ctl_tti_tx_data_queue_ready_thld_o = tti_tx_data_queue_ready_thld_o;

  //============================================================================
  //
  // SECTION 8: TTI QUEUE CSR INTERFACE
  //
  //============================================================================

  //----------------------------------------------------------------------------
  // RX Descriptor Queue CSR Interface
  //----------------------------------------------------------------------------
  always_comb begin : R4SW
    if (recovery_pending) begin
      csr_tti_rx_desc_queue_ack_o          = '0;
      csr_tti_rx_desc_queue_data_o         = '0;
      csr_tti_rx_desc_queue_reg_rst_we_o   = '0;
      csr_tti_rx_desc_queue_reg_rst_data_o = '0;
      tti_rx_desc_queue_req                = '0;
      tti_rx_desc_queue_reg_rst            = exec_tti_rx_desc_queue_clr;
    end else begin
      csr_tti_rx_desc_queue_ack_o          = tti_rx_desc_queue_ack;
      csr_tti_rx_desc_queue_data_o         = tti_rx_desc_queue_data;
      csr_tti_rx_desc_queue_reg_rst_we_o   = tti_rx_desc_queue_reg_rst_we;
      csr_tti_rx_desc_queue_reg_rst_data_o = tti_rx_desc_queue_reg_rst_data;
      tti_rx_desc_queue_req                = csr_tti_rx_desc_queue_req_i;
      tti_rx_desc_queue_reg_rst            = csr_tti_rx_desc_queue_reg_rst_i;
    end
  end

  // Threshold
  assign tti_rx_desc_queue_ready_thld_i     = csr_tti_rx_desc_queue_ready_thld_i;
  assign csr_tti_rx_desc_queue_ready_thld_o = tti_rx_desc_queue_ready_thld_o;

  //----------------------------------------------------------------------------
  // TX Descriptor Queue CSR Interface
  // TX desc is always connected, recovery logic generates its own descriptors
  // T1MUX disconnects this FIFO from TTI logic
  //----------------------------------------------------------------------------
  assign csr_tti_tx_desc_queue_full_o = tti_tx_desc_queue_full;
  assign csr_tti_tx_desc_queue_ack_o = tti_tx_desc_queue_ack;
  assign csr_tti_tx_desc_queue_reg_rst_we_o = tti_tx_desc_queue_reg_rst_we;
  assign csr_tti_tx_desc_queue_reg_rst_data_o = tti_tx_desc_queue_reg_rst_data;
  assign tti_tx_desc_queue_data = csr_tti_tx_desc_queue_data_i;
  assign tti_tx_desc_queue_req = csr_tti_tx_desc_queue_req_i;
  assign tti_tx_desc_queue_reg_rst = csr_tti_tx_desc_queue_reg_rst_i | exec_tti_tx_desc_queue_clr;

  // Threshold
  assign tti_tx_desc_queue_ready_thld_i = csr_tti_tx_desc_queue_ready_thld_i;
  assign csr_tti_tx_desc_queue_ready_thld_o = tti_tx_desc_queue_ready_thld_o;

  //----------------------------------------------------------------------------
  // RX Data Queue CSR Interface
  //----------------------------------------------------------------------------
  always_comb begin : R3MUX
    if (bypass_i3c_core_i) begin
      exec_tti_rx_data_ack = tti_tx_data_queue_rvalid;
      exec_tti_rx_data_data = tti_tx_data_queue_rdata;
      csr_tti_rx_data_queue_ack_o = '0;
      csr_tti_rx_data_queue_reg_rst_we_o = '0;
      csr_tti_rx_data_queue_reg_rst_data_o = '0;
      tti_rx_data_queue_req = '0;  // exec_tti_rx_data_req is connected to tti_tx_data_queue_req
      tti_rx_data_queue_reg_rst = exec_tti_rx_data_queue_clr;
    end else if (recovery_pending & exec_tti_rx_queue_sel) begin
      csr_tti_rx_data_queue_ack_o          = '0;
      csr_tti_rx_data_queue_reg_rst_we_o   = '0;
      csr_tti_rx_data_queue_reg_rst_data_o = '0;
      tti_rx_data_queue_req                = exec_tti_rx_data_req;
      tti_rx_data_queue_reg_rst            = exec_tti_rx_data_queue_clr;
      exec_tti_rx_data_ack                 = tti_rx_data_queue_ack;
      exec_tti_rx_data_data                = tti_rx_data_queue_data;
    end else begin
      csr_tti_rx_data_queue_ack_o          = tti_rx_data_queue_ack;
      csr_tti_rx_data_queue_reg_rst_we_o   = tti_rx_data_queue_reg_rst_we;
      csr_tti_rx_data_queue_reg_rst_data_o = tti_rx_data_queue_reg_rst_next;
      tti_rx_data_queue_req                = csr_tti_rx_data_queue_req_i;
      tti_rx_data_queue_reg_rst            = csr_tti_rx_data_queue_reg_rst_i;
      exec_tti_rx_data_ack                 = '0;
      exec_tti_rx_data_data                = tti_rx_data_queue_data;
    end

    // No need to mux data
    csr_tti_rx_data_queue_data_o = tti_rx_data_queue_data;
  end

  // Threshold
  assign tti_rx_data_queue_start_thld       = csr_tti_rx_data_queue_start_thld_i;
  assign tti_rx_data_queue_ready_thld_i     = csr_tti_rx_data_queue_ready_thld_i;
  assign csr_tti_rx_data_queue_ready_thld_o = tti_rx_data_queue_ready_thld_o;

  //----------------------------------------------------------------------------
  // TX Data Queue CSR Interface
  // TX data queue is always connected. The recovery logic does not use it
  //----------------------------------------------------------------------------
  assign csr_tti_tx_data_queue_full_o = bypass_i3c_core_i ? indirect_rx_full : tti_tx_data_queue_full;
  assign csr_tti_tx_data_queue_ack_o = tti_tx_data_queue_ack;
  assign csr_tti_tx_data_queue_reg_rst_we_o = tti_tx_data_queue_reg_rst_we;
  assign csr_tti_tx_data_queue_reg_rst_data_o = tti_tx_data_queue_reg_rst_next;
  assign tti_tx_data_queue_data = csr_tti_tx_data_queue_data_i;
  assign tti_tx_data_queue_req = csr_tti_tx_data_queue_req_i;
  assign tti_tx_data_queue_reg_rst = csr_tti_tx_data_queue_reg_rst_i | exec_tti_tx_data_queue_clr;

  // Threshold
  assign tti_tx_data_queue_start_thld = csr_tti_tx_data_queue_start_thld_i;
  assign tti_tx_data_queue_ready_thld_i = csr_tti_tx_data_queue_ready_thld_i;
  assign csr_tti_tx_data_queue_ready_thld_o = tti_tx_data_queue_ready_thld_o;

  //============================================================================
  //
  // SECTION 9: PEC (PACKET ERROR CHECK) COMPUTATION
  //
  //============================================================================

  // Any start (S or Sr) resets address valid tracking
  assign ctl_bus_any_start = ctl_bus_start_i | ctl_bus_rstart_i;

  //----------------------------------------------------------------------------
  // RX PEC Calculator
  //----------------------------------------------------------------------------
  recovery_pec xrecovery_rx_pec (
      .clk_i,
      .rst_ni(rst_ni),
      .soft_reset_ni(!ctl_bus_any_start & virtual_device_sel_i & ~bypass_i3c_core_i),

      .dat_i  (rx_pec_data),
      .valid_i(rx_pec_enable),
      .init_i (rx_pec_init),
      .crc_o  (rx_pec_crc)
  );

  // RX PEC mux for initializing it with I2C/I3C address byte
  always_comb begin
    rx_pec_data  = rx_pec_init ? ctl_bus_addr_i : tti_rx_data_queue_wdata;
  end

  //============================================================================
  //
  // SECTION 10: RECOVERY RECEIVER INSTANTIATION
  //
  //============================================================================

  recovery_receiver #(
      .TtiRxDescDataWidth(TtiRxDescDataWidth),
      .TtiTxDescDataWidth(TtiTxDescDataWidth),
      .TtiRxDataDataWidth(TtiRxDataDataWidth),
      .CsrDataWidth      (CsrDataWidth),
      .IndirectFifoDepth (IndirectFifoDepth)
  ) xrecovery_receiver (
      .clk_i,
      .rst_ni,
      .bypass_i3c_core_i,
      .pec_err_det_en_i,
      .length_err_det_en_i,
      .readonly_err_det_en_i,
      .unsupported_err_det_en_i,
      .rx_fifo_overflow_err_det_en_i,
      .rx_fifo_overflow_raw_i(rx_fifo_overflow_raw),
      .indirect_fifo_overflow_err_det_en_i,
      .recovery_mode_csr_active_i(recovery_mode_csr_active),


      .rx_data_valid_i(recv_tti_rx_data_valid),
      .rx_data_ready_o(recv_tti_rx_data_ready),
      .rx_data_i      (recv_tti_rx_data_data),
      .rx_data_last_i (recv_tti_rx_data_last),

      .rx_data_queue_select_o(recv_tti_rx_data_queue_select),
      .rx_data_queue_flush_o (recv_tti_rx_data_queue_flush),
      .conv_soft_reset_o     (recv_conv_soft_reset),
      .rx_data_queue_flow_i  (tti_rx_data_queue_wvalid & tti_rx_data_queue_wready),

      .tti_rx_rreq_o (exec_tti_rx_data_req),
      .tti_rx_rack_i (exec_tti_rx_data_ack),
      .tti_rx_rdata_i(exec_tti_rx_data_data),
      .tti_rx_sel_o  (exec_tti_rx_queue_sel),
      .rx_data_queue_clr_o(exec_tti_rx_data_queue_clr),
      .rx_desc_queue_clr_o(exec_tti_rx_desc_queue_clr),
      .tx_data_queue_clr_o(exec_tti_tx_data_queue_clr),
      .tx_desc_queue_clr_o(exec_tti_tx_desc_queue_clr),

      .indirect_rx_wvalid_o(indirect_rx_wvalid),
      .indirect_rx_wready_i(indirect_rx_wready),
      .indirect_rx_wdata_o (indirect_rx_wdata),
      .indirect_rx_rreq_o  (indirect_rx_rreq),
      .indirect_rx_rack_i  (indirect_rx_rack),
      .indirect_rx_rdata_i (indirect_rx_rdata),
      .indirect_rx_full_i  (indirect_rx_full),
      .indirect_rx_empty_i (indirect_rx_empty),
      .indirect_rx_clr_o   (indirect_rx_clr),

      .bus_start_i (ctl_bus_start_i),
      .bus_rstart_i(ctl_bus_rstart_i),
      .bus_any_start_i(ctl_bus_any_start),
      .bus_stop_i  (ctl_bus_stop_i),
      .in_hdr_mode_i(ctl_in_hdr_mode_i),
      .bus_addr_i  (ctl_bus_addr_i),

      .pec_crc_i   (rx_pec_crc),
      .pec_enable_o(rx_pec_enable),
      .pec_init_o  (rx_pec_init),

      // TTI TX descriptor interface
      .tx_desc_valid_o(send_tti_tx_desc_valid),
      .tx_desc_ready_i(send_tti_tx_desc_ready),
      .tx_desc_data_o (send_tti_tx_desc_data),

      // TTI TX data interface
      .tx_data_valid_o(send_tti_tx_data_valid),
      .tx_data_ready_i(send_tti_tx_data_ready),
      .tx_data_o      (send_tti_tx_data_data),

      // TTI TX queue mux control
      .tx_data_queue_select_o(send_tti_tx_data_queue_select),
      .tx_start_trig_o       (send_tti_tx_start_trig),

      // TX PEC computation interface
      .tx_pec_crc_i   (tx_pec_crc),
      .tx_pec_enable_o(tx_pec_enable),
      .tx_pec_init_o  (tx_pec_init),
      .tx_pec_soft_rst_n_o(tx_pec_soft_rst_n),

      .payload_available_o,
      .image_activated_o,

      .hwif_rec_i,
      .hwif_rec_o,

      .hwif_socmgmt_i,
      .hwif_socmgmt_o,

      .virtual_target_start_i(virtual_target_start),
      .other_target_start_i(other_target_start),

      .pec_err_o,
      .length_err_o,
      .readonly_err_o,
      .unsupported_err_o,
      .rx_fifo_overflow_err_o,
      .indirect_fifo_overflow_err_o,
      .rx_desc_wvalid_i(ctl_tti_rx_desc_queue_wvalid_i),
      .rx_desc_wdata_i (ctl_tti_rx_desc_queue_wdata_i),
      .exec_pending_o(recovery_exec_pending)
  );

  //----------------------------------------------------------------------------
  // TX PEC Calculator
  //----------------------------------------------------------------------------
  recovery_pec xrecovery_tx_pec (
      .clk_i,
      .rst_ni(rst_ni),
      .soft_reset_ni(tx_pec_soft_rst_n & ~bypass_i3c_core_i),

      .dat_i  (tx_pec_data),
      .valid_i(tx_pec_enable),
      .init_i (tx_pec_init),
      .crc_o  (tx_pec_crc)
  );
  assign tx_pec_data = tx_pec_init ? ctl_bus_addr_i : ctl_tti_tx_data_queue_rdata_o;

  //============================================================================
  //
  // SECTION 11: INDIRECT FIFO (Firmware Data Buffer)
  //
  //============================================================================

  // Bypass mode mux: In bypass mode, TX queue writes directly to indirect FIFO
  assign indirect_rx_wvalid_muxed = bypass_i3c_core_i ?
      (tti_tx_data_queue_rvalid & allow_indirect_write) : indirect_rx_wvalid;
  assign indirect_rx_wdata_muxed = bypass_i3c_core_i ?
      tti_tx_data_queue_rdata : indirect_rx_wdata;

  read_queue #(
      .Depth    (IndirectFifoDepth),
      .DataWidth(CsrDataWidth)
  ) xindirect_rx_fifo (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      // Write port (muxed for bypass mode)
      .wvalid_i(indirect_rx_wvalid_muxed),
      .wready_o(indirect_rx_wready),
      .wdata_i (indirect_rx_wdata_muxed),

      // Read port
      .req_i (indirect_rx_rreq & allow_indirect_read),
      .ack_o (indirect_rx_rack),
      .data_o(indirect_rx_rdata),

      // Clear port
      .reg_rst_i     (indirect_rx_clr),
      .reg_rst_we_o  (),
      .reg_rst_data_o(),

      // Status
      .full_o (indirect_rx_full),
      .empty_o(indirect_rx_empty),

      // Threshold logic (unused)
      .start_thld_i     ('0),
      .ready_thld_i     ('0),
      .ready_thld_o     (),
      .start_thld_trig_o(),
      .ready_thld_trig_o(),
      .depth_o          ()
  );

  always_ff @(posedge clk_i or negedge rst_ni) begin : indirect_fifo_access_permissions
    if (~rst_ni) begin
      allow_indirect_write <= '0;
      allow_indirect_read <= '0;
    end else begin
      if (bypass_i3c_core_i) begin
        if (indirect_rx_empty) begin
          allow_indirect_write <= 1'b1;
          allow_indirect_read <= 1'b0;
        end else if (indirect_rx_full | payload_available_o) begin
          allow_indirect_write <= 1'b0;
          allow_indirect_read <= 1'b1;
        end
      end else begin
        allow_indirect_write <= 1'b1;
        allow_indirect_read <= 1'b1;
      end
    end
  end

  //============================================================================
  //
  // SECTION 12: BYPASS MODE SUPPORT
  //
  //============================================================================

  //----------------------------------------------------------------------------
  // Request to Ready Conversion for Bypass Mode
  //----------------------------------------------------------------------------
  always_ff @(posedge clk_i or negedge rst_ni) begin : convert_req_to_ready
    if (~rst_ni) begin
      exec_tti_rx_data_ready <= '0;
    end else if (exec_tti_rx_data_req) begin
      exec_tti_rx_data_ready <= 1'b1;
    end else if (tti_tx_data_queue_rvalid) begin
      exec_tti_rx_data_ready <= 1'b0;
    end
  end

  always_comb begin : tti_tx_queue_converter_sink
    if (bypass_i3c_core_i) begin
      // In bypass mode: TX queue writes directly to indirect FIFO
      tti_tx_data_queue_rvalid_conv_sink = '0;
      tti_tx_data_queue_rready = indirect_rx_wready & allow_indirect_write;
      tti_tx_data_queue_rdata_conv_sink = '0;
    end else begin
      tti_tx_data_queue_rvalid_conv_sink = tti_tx_data_queue_rvalid;
      tti_tx_data_queue_rready = tti_tx_data_queue_rready_conv_sink;
      tti_tx_data_queue_rdata_conv_sink = tti_tx_data_queue_rdata;
    end
  end

endmodule
