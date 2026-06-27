// SPDX-License-Identifier: Apache-2.0
//
// IBI queue with dual write pointers for out-of-order IBI data buffering
// Forked from read_queue.sv
//
// Key differences from original:
// - ibi_status_desc_valid_i input to distinguish status descriptor from data writes
// - ready_thld_trig_o based on ibi_status_desc_entries (not total depth)
// - No start_thld support (IBI queue doesn't use it, always hardwired to 0)
//
// This queue handles the IBI buffering requirement where:
// - IBI data arrives FIRST (payload bytes)
// - IBI status descriptor arrives LAST (metadata including data_length)
// - Software must read status descriptor FIRST, then data
//
// The dual write pointer mechanism reserves a slot for the status descriptor
// before the data, allowing correct read ordering despite out-of-order writes.

module hci_ibi_queue #(
    parameter int unsigned Depth = 64,
    parameter int unsigned DataWidth = 32,
    parameter int unsigned ThldWidth = 8,
    // ThldIsPow is always 0 for IBI queue (linear threshold)
    localparam int unsigned FifoDepthWidth = $clog2(Depth + 1)
) (
    input logic clk_i,
    input logic rst_ni,

    // Direct FIFO write control
    output logic full_o,
    output logic [FifoDepthWidth-1:0] depth_o,
    output logic ready_thld_trig_o,  // Based on ibi_status_desc_entries
    output logic empty_o,
    input logic wvalid_i,
    output logic wready_data_o,    // Ready for data writes (not full)
    input logic [DataWidth-1:0] wdata_i,
    input logic ibi_status_desc_valid_i,  // NEW: distinguishes status from data

    // CSR access control
    input logic req_i,
    output logic ack_o,
    output logic [DataWidth-1:0] data_o,

    // Threshold value (only ready_thld, no start_thld for IBI queue)
    input  logic [ThldWidth-1:0] ready_thld_i,
    output logic [ThldWidth-1:0] ready_thld_o,

    // CSR reset control
    input  logic reg_rst_i,
    output logic reg_rst_we_o,
    output logic reg_rst_data_o
);

  logic fifo_clr;
  logic [FifoDepthWidth-1:0] fifo_depth;
  logic [FifoDepthWidth-1:0] ibi_status_desc_entries;
  logic fifo_rvalid;
  logic fifo_rready;
  logic [DataWidth-1:0] fifo_rdata;

  assign fifo_clr = reg_rst_i;
  assign reg_rst_data_o = 1'b0;

  assign depth_o = fifo_depth;

  // Threshold trigger based on status descriptor count (not total depth)
  // Per HCI spec, IBI_STATUS_THLD counts complete IBI status descriptors
  always_comb begin : trigger_threshold
    empty_o = ~|fifo_depth;
    // Linear threshold (ThldIsPow=0): trigger when entries >= threshold
    ready_thld_trig_o = |ready_thld_o && (ibi_status_desc_entries >= FifoDepthWidth'(ready_thld_o));
  end : trigger_threshold

  // Threshold passthrough (no limiting logic needed for IBI queue)
  always_ff @(posedge clk_i or negedge rst_ni) begin : populate_thld
    if (!rst_ni) begin
      ready_thld_o <= '0;
    end else begin
      ready_thld_o <= ready_thld_i;
    end
  end : populate_thld

  // CSR reset control
  always_ff @(posedge clk_i or negedge rst_ni) begin : csr_rst_control
    if (~rst_ni) begin : rst_control_rst
      reg_rst_we_o <= '0;
    end else begin
      reg_rst_we_o <= reg_rst_i && empty_o;
    end
  end : csr_rst_control

  // CSR read port logic (FIFO to software)
  always_ff @(posedge clk_i or negedge rst_ni) begin : fifo_to_port
    if (!rst_ni) begin : fifo_to_port_rst
      fifo_rready <= '0;
      data_o <= '0;
      ack_o <= '0;
    end else begin : push_to_port
      if (reg_rst_i) begin
        fifo_rready <= '0;
        data_o <= '0;
        ack_o <= '0;
      end else begin
        if (req_i) begin
          fifo_rready <= 1'b1;
        end

        if (fifo_rready & fifo_rvalid) begin
          fifo_rready <= 1'b0;
          data_o <= fifo_rdata;
          ack_o <= 1'b1;
        end else begin
          data_o <= '0;
          ack_o  <= 1'b0;
        end
      end
    end : push_to_port
  end : fifo_to_port

  logic unused_err;

  // Instantiate IBI FIFO with dual write pointers
  hci_ibi_fifo_sync #(
      .Width(DataWidth),
      .Pass (1'b0),  // No passthrough for IBI queue
      .Depth(Depth)
  ) fifo (
      .clk_i,
      .rst_ni,
      .clr_i(fifo_clr),
      .wvalid_i,
      .wready_data_o,
      .wdata_i,
      .ibi_status_desc_valid_i,
      .depth_o(fifo_depth),
      .rvalid_o(fifo_rvalid),
      .rready_i(fifo_rready),
      .rdata_o(fifo_rdata),
      .full_o,
      .err_o(unused_err),
      .ibi_status_desc_entries_o(ibi_status_desc_entries)
  );

endmodule
