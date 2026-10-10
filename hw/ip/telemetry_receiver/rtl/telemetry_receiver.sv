// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Assemble ATB telemetry packets into buffered counter messages for AXI-Lite readout.
//
// ATB beats accepted on atvalid_i and atready_o fill an assembly buffer; a packet whose
// last_packet bit is set completes a message, which is decoded into a probe ID and counters
// and pushed into a BUFFER_DEPTH message FIFO read through the CSRs. A push into a full
// FIFO drops the oldest message. BUFFER_DEPTH must be a power of two and greater than or
// equal to 2. CTRL.TELEMETRY_RX_FLUSH empties both buffers and deasserts atready_o, and
// CTRL.TELEMETRY_TX_FLUSH drives the AF flush request.
//
// debug_o bits:
//
// - debug_o[0] missing_last_event: assembly buffer filled without last_packet marker.
// - debug_o[1] message_buffer_full: a further push drops the oldest message.
// - debug_o[2] message_buffer_empty.
// - debug_o[3] assembly_buffer_full: the beat being accepted fills the assembly buffer.

module telemetry_receiver
  import telemetry_receiver_pkg::TelemetryCounterWidth;
  import telemetry_receiver_pkg::TelemetryDataWidth;
  import telemetry_receiver_pkg::NumBlocksPerPacket;
  import telemetry_receiver_pkg::TelemetryPacketWidth;
  import telemetry_receiver_pkg::axil_req_t;
  import telemetry_receiver_pkg::axil_resp_t;
  import telemetry_receiver_pkg::telemetry_data_t;
  import telemetry_receiver_pkg::atb_id_t;
  import telemetry_receiver_pkg::NumCounterRegs;
#(
  parameter int unsigned BUFFER_DEPTH                 = 8,  // Completed-message FIFO depth; must be
                                                            // a power of two and >= 2.
  parameter int unsigned MAX_NUM_COUNTERS_PER_MESSAGE = 4,  // Counters allowed per message; only
                                                            // the first NumCounterRegs are
                                                            // readable.

  localparam int unsigned MaxNumBlocksPerMessage =      // Packet blocks spanning one message: one header block plus one block per counter byte.
        1 + (TelemetryCounterWidth / TelemetryDataWidth) * MAX_NUM_COUNTERS_PER_MESSAGE,
  localparam int unsigned MaxNumPacketsPerMessage =     // ATB packets spanning one message.
        MaxNumBlocksPerMessage % NumBlocksPerPacket == 0 ?
        MaxNumBlocksPerMessage / NumBlocksPerPacket :
        MaxNumBlocksPerMessage / NumBlocksPerPacket + 1,

  localparam int unsigned PacketIndexWidth = $clog2(MaxNumPacketsPerMessage), // Packet-index counter width.
  localparam int unsigned BlockIndexWidth  = $clog2(NumBlocksPerPacket), // Block-index counter width.

  localparam int unsigned AssemblyBufferDepth =           // Assembly-buffer depth in beats.
        (TelemetryPacketWidth / TelemetryDataWidth) * MaxNumPacketsPerMessage,
  localparam int unsigned AssemblyBufferPtrWidth = $clog2(AssemblyBufferDepth), // Assembly-buffer pointer width.
  localparam type assembly_buffer_ptr_t = logic [AssemblyBufferPtrWidth-1:0], // Assembly-buffer pointer type.

  localparam int unsigned MessageBufferPtrWidth = $clog2(BUFFER_DEPTH) + 1, // Message-FIFO pointer width.
  localparam type message_buffer_ptr_t = logic [MessageBufferPtrWidth-1:0] // Message-FIFO pointer type.
) (
  input  logic            clk_i,                            // System clock.
                                                            // All synchronous logic uses the rising
                                                            // edge.
  input  logic            rst_ni,                           // Async reset, active-low.
                                                            // Assert asynchronously; deassert
                                                            // synchronously to clk_i.

  input  axil_req_t       axil_req_i,                       // AXI-Lite CSR request.
  output axil_resp_t      axil_resp_o,                      // AXI-Lite CSR response.

  input  telemetry_data_t atdata_i,                         // ATB data.
                                                            // One 8-bit data beat per transfer.
  input  atb_id_t         atid_i,                           // ATB ID.
                                                            // Identifies the trace source. Unused.
  output logic            atready_o,                        // ATB ready.
                                                            // High when the receiver can accept a
                                                            // beat; low only while
                                                            // CTRL.TELEMETRY_RX_FLUSH is set.
  input  logic            atvalid_i,                        // ATB valid.
                                                            // High when atdata_i and atid_i are
                                                            // valid.
  output logic            afvalid_o,                        // ATB flush valid.
                                                            // Requests a flush from the source. It
                                                            // is CTRL.TELEMETRY_TX_FLUSH, held
                                                            // until afready_i completes the
                                                            // handshake.
  input  logic            afready_i,                        // ATB flush ready.
                                                            // Acknowledges the flush request and
                                                            // clears CTRL.TELEMETRY_TX_FLUSH.

  output logic            irq_o,                            // Receiver interrupt.
                                                            // Active high, level. Asserted while
                                                            // INTR_STATUS.MISSING_LAST is set, or
                                                            // while the FIFO fill level exceeds
                                                            // CTRL.BUFFER_THRESHOLD, each gated by
                                                            // its INTR_ENABLE bit.

  output logic [3:0]      debug_o                           // [0] missing_last_event; [1]
                                                            // message_buffer_full; [2]
                                                            // message_buffer_empty; [3]
                                                            // assembly_buffer_full.
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  /////////////////
  // Definitions //
  /////////////////

  // Telemetry message decoding
  typedef struct packed {
    telemetry_receiver_pkg::telemetry_probe_id_t                                   probe_id;
    telemetry_receiver_pkg::telemetry_counter_t [MAX_NUM_COUNTERS_PER_MESSAGE-1:0] counters;
  } telemetry_message_t;

  function automatic telemetry_receiver_pkg::telemetry_probe_id_t get_telemetry_probe_id(
      telemetry_receiver_pkg::telemetry_packet_t [MaxNumPacketsPerMessage-1:0] telemetry_packets);
    return telemetry_packets[0][60:56];
  endfunction


  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  logic telemetry_receiver_flush;

  logic last_packet_received;

  telemetry_receiver_pkg::telemetry_packet_t [MaxNumPacketsPerMessage-1:0]     received_telemetry_packets;
  telemetry_message_t                                  received_telemetry_message;

  logic message_buffer_pop;
  logic message_buffer_full, message_buffer_empty;
  telemetry_message_t message_buffer_rd_data;

  message_buffer_ptr_t buffer_threshold;

  logic missing_last_event, missing_last_intr_test;
  logic buffer_threshold_intr_test, buffer_threshold_intr_req;


  ///////////////////////////////
  // Telemetry Interface Logic //
  ///////////////////////////////

  assign atready_o = !telemetry_receiver_flush;


  /////////////////////
  // Assembly Buffer //
  /////////////////////

  logic telemetry_beat_received;

  assign telemetry_beat_received = atready_o && atvalid_i;

  assembly_buffer_ptr_t
      assembly_buffer_wr_ptr_q, assembly_buffer_wr_ptr, assembly_buffer_wr_ptr_next;

  telemetry_data_t [AssemblyBufferDepth-1:0] assembly_buffer, assembly_buffer_next;

  logic assembly_buffer_full, assembly_buffer_full_q;

  assign assembly_buffer_full =
        assembly_buffer_wr_ptr == assembly_buffer_ptr_t'(AssemblyBufferDepth - 1) &&
        telemetry_beat_received;

  assign received_telemetry_packets = assembly_buffer;

  logic end_of_packet, end_of_packet_q;

  assign end_of_packet = &assembly_buffer_wr_ptr[$clog2(telemetry_receiver_pkg::NumBeatsPerPacket)-1:0] &&
                           telemetry_beat_received;

  assign last_packet_received =
        end_of_packet_q &&
        received_telemetry_packets[(assembly_buffer_wr_ptr_q) / telemetry_receiver_pkg::NumBeatsPerPacket].last_packet;

  assign missing_last_event = assembly_buffer_full_q && !last_packet_received;

  always_comb begin
    assembly_buffer_next = assembly_buffer;

    // Always write the current beat when valid, regardless of reset conditions
    if (telemetry_beat_received) begin
      assembly_buffer_next[assembly_buffer_wr_ptr] = atdata_i;
    end

    // Handle pointer updates and resets
    if (last_packet_received || assembly_buffer_full || telemetry_receiver_flush) begin
      assembly_buffer_wr_ptr_next = assembly_buffer_ptr_t'(0);
    end else if (telemetry_beat_received) begin
      assembly_buffer_wr_ptr_next = assembly_buffer_wr_ptr + assembly_buffer_ptr_t'(1);
    end else begin
      assembly_buffer_wr_ptr_next = assembly_buffer_wr_ptr;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      assembly_buffer <= '0;
      assembly_buffer_wr_ptr <= assembly_buffer_ptr_t'(0);
      assembly_buffer_wr_ptr_q <= assembly_buffer_ptr_t'(0);
      end_of_packet_q <= 1'b0;
      assembly_buffer_full_q <= 1'b0;
    end else begin
      assembly_buffer <= assembly_buffer_next;
      assembly_buffer_wr_ptr <= assembly_buffer_wr_ptr_next;
      assembly_buffer_wr_ptr_q <= assembly_buffer_wr_ptr;
      end_of_packet_q <= end_of_packet;
      assembly_buffer_full_q <= assembly_buffer_full;
    end
  end


  ////////////////////////////////////
  // Telemetry Message Decode Logic //
  ////////////////////////////////////

  assign received_telemetry_message.probe_id = get_telemetry_probe_id(received_telemetry_packets);

  logic [PacketIndexWidth-1:0] packet_index;
  logic [BlockIndexWidth-1:0]  block_index;

  always_comb begin
    packet_index = 0;
    block_index = 1;

    for (int i = 0; i < MAX_NUM_COUNTERS_PER_MESSAGE; i++) begin
      received_telemetry_message.counters[i].vld = 1'b1;

      // Counter data is stored MSB first
      for (int j = TelemetryCounterWidth / 8 - 1; j >= 0; j--) begin
        received_telemetry_message.counters[i].vld &=
                received_telemetry_packets[packet_index]
                    .blocks[block_index]
                    .vld;
        received_telemetry_message.counters[i].value[j * 8 +: 8] =
                    received_telemetry_packets[packet_index]
                    .blocks[block_index]
                    .counter_val_partial;

        if (block_index == NumBlocksPerPacket - 1) begin
          packet_index++;
          block_index = 0;
        end else begin
          block_index++;
        end
      end
      if (!received_telemetry_message.counters[i].vld) begin
        received_telemetry_message.counters[i].value = telemetry_receiver_pkg::telemetry_counter_val_t'(0);
      end
    end
  end


  ////////////////////
  // Message Buffer //
  ////////////////////

  // NOTE: When this circular buffer overflows, the oldest entry is dropped, and the read pointer
  //       is incremented by 1

  logic message_buffer_push;

  message_buffer_ptr_t message_buffer_wr_ptr, message_buffer_wr_ptr_next;
  message_buffer_ptr_t message_buffer_rd_ptr, message_buffer_rd_ptr_next;
  telemetry_message_t [BUFFER_DEPTH-1:0] message_buffer, message_buffer_next;

  message_buffer_ptr_t message_buffer_fill_level;

  assign message_buffer_push = last_packet_received;

  assign message_buffer_full  =
        message_buffer_wr_ptr[MessageBufferPtrWidth-2:0] ==
        message_buffer_rd_ptr[MessageBufferPtrWidth-2:0] &&
        message_buffer_wr_ptr[MessageBufferPtrWidth-1] !=
        message_buffer_rd_ptr[MessageBufferPtrWidth-1];
  assign message_buffer_empty = message_buffer_wr_ptr == message_buffer_rd_ptr;

  assign message_buffer_fill_level = message_buffer_ptr_t'(message_buffer_wr_ptr - message_buffer_rd_ptr);

  assign message_buffer_rd_data =
        message_buffer_empty ?
        telemetry_message_t'(0) :
        message_buffer[message_buffer_rd_ptr[MessageBufferPtrWidth-2:0]];

  always_comb begin
    message_buffer_wr_ptr_next = message_buffer_wr_ptr;
    message_buffer_rd_ptr_next = message_buffer_rd_ptr;
    message_buffer_next = message_buffer;

    if (telemetry_receiver_flush) begin
      message_buffer_wr_ptr_next = message_buffer_ptr_t'(0);
      message_buffer_rd_ptr_next = message_buffer_ptr_t'(0);
    end else begin
      if (message_buffer_push) begin  // Write
        message_buffer_next[message_buffer_wr_ptr[MessageBufferPtrWidth-2:0]] =
                    received_telemetry_message;
        message_buffer_wr_ptr_next = message_buffer_wr_ptr + message_buffer_ptr_t'(1);
      end
      if (!message_buffer_empty && message_buffer_pop ||
                message_buffer_full && message_buffer_push) begin // Read
        message_buffer_rd_ptr_next = message_buffer_rd_ptr + message_buffer_ptr_t'(1);
      end else begin
        message_buffer_rd_ptr_next = message_buffer_rd_ptr;
      end
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      message_buffer_wr_ptr <= message_buffer_ptr_t'(0);
      message_buffer_rd_ptr <= message_buffer_ptr_t'(0);
    end else begin
      message_buffer_wr_ptr <= message_buffer_wr_ptr_next;
      message_buffer_rd_ptr <= message_buffer_rd_ptr_next;
      message_buffer <= message_buffer_next;
    end
  end


  /////////////////////
  // Interrupt Logic //
  /////////////////////

  assign buffer_threshold_intr_req =
        message_buffer_fill_level > buffer_threshold || buffer_threshold_intr_test;
  // MISSING_LAST latches whether or not the interrupt is enabled
  // Clears only on W1C; INTR_ENABLE masks the output only
  assign irq_o =
        (reg_out.INTR_STATUS.MISSING_LAST.value && reg_out.INTR_ENABLE.MISSING_LAST.value) ||
        (buffer_threshold_intr_req               && reg_out.INTR_ENABLE.BUFFER_THRESHOLD.value);


  //////////
  // CSRs //
  //////////

  logic                   [NumCounterRegs-1:0] counter_reg_vlds;
  telemetry_receiver_pkg::telemetry_counter_val_t [NumCounterRegs-1:0] counter_reg_vals;

  always_comb begin
    for (int i = 0; i < NumCounterRegs; i++) begin
      if (i < MAX_NUM_COUNTERS_PER_MESSAGE) begin
        counter_reg_vlds[i] = message_buffer_rd_data.counters[i].vld;
        counter_reg_vals[i] = message_buffer_rd_data.counters[i].value;
      end else begin
        counter_reg_vlds[i] = 1'b0;
        counter_reg_vals[i] = telemetry_receiver_pkg::reg_data_t'(0);
      end
    end
  end

  telemetry_receiver_reg_pkg::telemetry_receiver__in_t  reg_in;
  telemetry_receiver_reg_pkg::telemetry_receiver__out_t reg_out;

  telemetry_receiver_reg u_telemetry_receiver_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_resp_o.aw_ready),
    .s_axil_awvalid (axil_req_i.aw_valid),
    .s_axil_awaddr  (axil_req_i.aw.addr),
    .s_axil_awprot  (axil_req_i.aw.prot),
    .s_axil_wready  (axil_resp_o.w_ready),
    .s_axil_wvalid  (axil_req_i.w_valid),
    .s_axil_wdata   (axil_req_i.w.data),
    .s_axil_wstrb   (axil_req_i.w.strb),
    .s_axil_bready  (axil_req_i.b_ready),
    .s_axil_bvalid  (axil_resp_o.b_valid),
    .s_axil_bresp   (axil_resp_o.b.resp),
    .s_axil_arready (axil_resp_o.ar_ready),
    .s_axil_arvalid (axil_req_i.ar_valid),
    .s_axil_araddr  (axil_req_i.ar.addr),
    .s_axil_arprot  (axil_req_i.ar.prot),
    .s_axil_rready  (axil_req_i.r_ready),
    .s_axil_rvalid  (axil_resp_o.r_valid),
    .s_axil_rdata   (axil_resp_o.r.data),
    .s_axil_rresp   (axil_resp_o.r.resp),

    .hwif_in        (reg_in),
    .hwif_out       (reg_out)
  );

  // CTRL Register
  assign message_buffer_pop       = reg_out.CTRL.BUFFER_POP.value;
  assign telemetry_receiver_flush = reg_out.CTRL.TELEMETRY_RX_FLUSH.value;

  assign afvalid_o = reg_out.CTRL.TELEMETRY_TX_FLUSH.value;
  assign reg_in.CTRL.TELEMETRY_TX_FLUSH.hwclr = afready_i && afvalid_o;

  assign buffer_threshold = message_buffer_ptr_t'(reg_out.CTRL.BUFFER_THRESHOLD.value);

  // STATUS Register
  assign reg_in.STATUS.BUFFER_EMPTY.next = message_buffer_empty;
  assign reg_in.STATUS.BUFFER_FULL.next  = message_buffer_full;

  // INTR_STATE Register
  assign reg_in.INTR_STATUS.MISSING_LAST.next     = missing_last_event || missing_last_intr_test;
  assign reg_in.INTR_STATUS.BUFFER_THRESHOLD.next = buffer_threshold_intr_req;


  // INTR_TEST Register
  assign missing_last_intr_test     = reg_out.INTR_TEST.MISSING_LAST.value;
  assign buffer_threshold_intr_test = reg_out.INTR_TEST.BUFFER_THRESHOLD.value;

  // TELEMETRY_PROBE_ID Register
  assign reg_in.TELEMETRY_PROBE_ID.PROBE_ID.next = message_buffer_rd_data.probe_id;

  // TELEMETRY_COUNTER_VLDS Register
  assign reg_in.TELEMETRY_COUNTER_VLDS.COUNTER_VLDS.next = counter_reg_vlds;

  // TELEMETRY_COUNTER Registers
  always_comb begin
    for (int i = 0; i < NumCounterRegs; i++) begin
      reg_in.TELEMETRY_COUNTER[i].COUNTER.next = counter_reg_vals[i];
    end
  end


  ///////////
  // Debug //
  ///////////

  assign debug_o = {
    assembly_buffer_full, message_buffer_empty, message_buffer_full, missing_last_event
  };


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_ASSERT_STATIC(paramCheckBufferDepth,
                      BUFFER_DEPTH >= 2 && (BUFFER_DEPTH & (BUFFER_DEPTH - 1)) == 0)

  `OCAH_OT_ASSERT_KNOWN(AxilRespKnownO_A, axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(AtreadyKnownO_A, atready_o)
  `OCAH_OT_ASSERT_KNOWN(AfvalidKnownO_A, afvalid_o)
  `OCAH_OT_ASSERT_KNOWN(IrqKnownO_A, irq_o)
  `OCAH_OT_ASSERT_KNOWN(DebugKnownO_A, debug_o)

endmodule
