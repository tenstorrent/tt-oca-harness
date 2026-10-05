
// Author: Michael Rogenmoser <mrogenmoser@tenstorrent.com>

/// This module hides fully zero strobes at the start and the end of a transfer.
module axi_hidestrb #(
  parameter int unsigned MaxNumBeats    = 256,
  parameter type         axi_req_t      = logic,
  parameter type         axi_aw_chan_t  = logic,
  parameter type         axi_w_chan_t   = logic,
  parameter type         axi_resp_t     = logic
) (
  input  logic clk_i,
  input  logic rst_ni,

  input  axi_req_t  slv_port_req_i,
  output axi_resp_t slv_port_resp_o,

  output axi_req_t  mst_port_req_o,
  input  axi_resp_t mst_port_resp_i
);

  // TODO!!! Figure out full transfer of '0 strb (currently leads to single beat transfer)

  localparam int unsigned LogMaxNumWBeats = 9; // 256 beats + 1 bit for statekeeping

  axi_aw_chan_t next_aw_d, next_aw_q, next_aw_out;
  logic slv_port_aw_ready, mst_port_aw_valid;
  logic slv_port_w_ready, slv_allow_w;

  logic mst_port_w_valid, mst_port_w_ready;
  axi_w_chan_t mst_port_w;

  logic updating_aw_d, updating_aw_q;
  logic updating_aw_done_d, updating_aw_done_q;

  logic [LogMaxNumWBeats-1:0] start_zero_d, start_zero_q;
  logic [$clog2(MaxNumBeats)-1:0] end_zero_d, end_zero_q;
  logic start_done_d, start_done_q;
  logic end_done_d, end_done_q;

  logic [LogMaxNumWBeats-1:0] beats_sent_d, beats_sent_q;
  logic [LogMaxNumWBeats-1:0] beats_to_send_d, beats_to_send_q;
  logic ready_to_send_d, ready_to_send_q;

  logic len_too_long_d, len_too_long_q;

  // AR, R channels feedthrough
  assign mst_port_req_o.ar_valid  = slv_port_req_i.ar_valid;
  assign slv_port_resp_o.ar_ready = mst_port_resp_i.ar_ready;
  assign mst_port_req_o.ar        = slv_port_req_i.ar;
  assign slv_port_resp_o.r_valid  = mst_port_resp_i.r_valid;
  assign mst_port_req_o.r_ready   = slv_port_req_i.r_ready;
  assign slv_port_resp_o.r        = mst_port_resp_i.r;

  always @(posedge clk_i) begin
    if (rst_ni) begin
      if (slv_port_req_i.aw_valid) begin
        // Only allow INCR bursts
        assert (slv_port_req_i.aw.burst == axi_pkg::BURST_INCR)
          else $error("Only INCR AW bursts are supported for now.");
      end
    end
  end

  // No burst splitting or transfer dropping, feed through B channel
  assign slv_port_resp_o.b_valid  = mst_port_resp_i.b_valid;
  assign mst_port_req_o.b_ready   = slv_port_req_i.b_ready;
  assign slv_port_resp_o.b        = mst_port_resp_i.b;

  assign slv_port_resp_o.aw_ready = slv_port_aw_ready;
  assign mst_port_req_o.aw_valid = mst_port_aw_valid;
  assign mst_port_req_o.aw = end_done_q ? next_aw_out : next_aw_q;

  // This might violate dependencies in AXI spec
  assign slv_port_resp_o.w_ready = slv_port_w_ready && slv_allow_w;

  assign slv_allow_w = ~slv_port_req_i.w.last | ready_to_send_d;

  // Block handles sending of W
  always_comb begin
    // Default assignment passes through
    beats_sent_d = beats_sent_q;
    ready_to_send_d = ready_to_send_q;
    mst_port_req_o.w = mst_port_w;
    mst_port_req_o.w_valid = 1'b0;
    mst_port_w_ready = 1'b0;

    // This triggers to start sending Ws (also triggers AW send)
    if ((end_done_q || len_too_long_q) && ready_to_send_q) begin
      ready_to_send_d = 1'b0;
    end

    // This is the last element we're sending
    if ((beats_sent_q == (beats_to_send_q - 1)) && (beats_to_send_d == beats_to_send_q) || beats_to_send_d == 1) begin
      mst_port_req_o.w.last = 1'b1;
    end

    // If the AW is sending or was sent, send the Ws
    if ((end_done_q || updating_aw_done_q || len_too_long_q) || !ready_to_send_q) begin
      // MIM-470 added the "if" condition on the next line based on mst_port_req/mst_port_resp:
      if(mst_port_req_o.aw_valid && !mst_port_resp_i.aw_ready && mst_port_req_o.w.last) begin
        mst_port_req_o.w_valid = 1'b0;
        mst_port_w_ready = 1'b0;
      end else begin
        mst_port_req_o.w_valid = mst_port_w_valid;
        mst_port_w_ready = mst_port_resp_i.w_ready;
      end
    end


    // These elements are '0 and should be dropped
    if ((beats_sent_q == beats_to_send_q) && !ready_to_send_q) begin
      mst_port_req_o.w_valid = 1'b0;
      mst_port_w_ready = 1'b1;
      if (mst_port_w.last) begin
        beats_sent_d = '0;
        ready_to_send_d = 1'b1;
      end
    end

    // When sending a beat
    if (mst_port_req_o.w_valid && mst_port_resp_i.w_ready) begin
      beats_sent_d = beats_sent_q + 1;
      // If this is anyway the last transfer
      if (mst_port_w.last) begin
        beats_sent_d = '0;
        ready_to_send_d = 1'b1;
      end
    end
  end

  // Buffer for W
  stream_fifo #(
    // MIM-466 disabled FALL_THROUGH, and added 1 to DEPTH:
    .FALL_THROUGH(1'b0),
    .DEPTH        (MaxNumBeats+1),
    .T            (axi_w_chan_t)
  ) i_w_fifo (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .flush_i    ('0),
    .testmode_i ('0),
    .usage_o    (),

    // Input all nonzero strb W beats
    .data_i  (slv_port_req_i.w),
    .valid_i (slv_port_req_i.w_valid && // valid from handshake
              ( slv_port_req_i.w.strb != '0 || // keep nonzero strobe
		// MIM-462 changed to start_done_d from start_done_q:
                start_done_d || // keep when start is complete
                slv_port_req_i.w.last) &&  // keep final
              slv_allow_w), // allow external stalling
    .ready_o (slv_port_w_ready),

    // No delay on W, assuming downstream will stall, may violate dependencies in AXI spec
    .data_o  (mst_port_w),
    .valid_o (mst_port_w_valid), // mst_port_req_o.w_valid),
    .ready_i (mst_port_w_ready) // mst_port_resp_i.w_ready)
  );

  // Count zero strobe W beats on arrival
  always_comb begin
    // Default keep previous state
    start_zero_d = start_zero_q;
    end_zero_d = end_zero_q;
    start_done_d = start_done_q;
    end_done_d = '0;

    // If we're done, zero out the state
    if (end_done_q) begin
      start_zero_d = '0;
      end_zero_d = '0;
      start_done_d = '0;
    end

    // New handshake
    if (slv_port_req_i.w_valid && slv_port_resp_o.w_ready) begin
      // If we get a last handshake in a burst, we indicate we are done.
      end_done_d = slv_port_req_i.w.last;

      if (!start_done_q || end_done_q) begin
        // When counting the starting '0s
        if (slv_port_req_i.w.strb == '0) begin
          // If '0, add 1
          if (end_done_q) begin
            // If end_done_q, then this is the first beat (start_zero_q still has old data)
            start_zero_d = 1;
          end else begin
            // Otherwise we know that the start_zero_q has correct state
            start_zero_d = start_zero_q + 1;
          end

          // Handle complete zero transfer
          if (slv_port_req_i.w.last) begin
            // Ensure we execute a single beat
	    // MIM-472 fix adds the aw_ready && aw_valid setting for corner case of one-beat burst:
            start_zero_d = (slv_port_resp_o.aw_ready && slv_port_req_i.aw_valid) ? slv_port_req_i.aw.len : start_zero_q;
          end
        end else begin
          // otherwise we're done counting the start
          start_done_d = 1'b1;
        end
      end else begin
        // When attempting to count the trailing zeros
        if (slv_port_req_i.w.strb == '0 && !len_too_long_q) begin
          // If '0, add 1
          end_zero_d = end_zero_q + 1;
        end else begin
          // otherwise zero out, as this wasn't the end.
          end_zero_d = '0;
        end
      end
    end
  end

  // Handle AW
  always_comb begin
    updating_aw_d = updating_aw_q;
    updating_aw_done_d = updating_aw_done_q;
    next_aw_d = next_aw_q;
    next_aw_out = next_aw_q;
    mst_port_aw_valid = 1'b0;
    slv_port_aw_ready = 1'b0;
    beats_to_send_d = beats_to_send_q;
    len_too_long_d = len_too_long_q;

    // Add new AW if not updating
    if (!updating_aw_q || (mst_port_req_o.aw_valid && mst_port_resp_i.aw_ready)) begin
      next_aw_d = slv_port_req_i.aw;
      slv_port_aw_ready = 1'b1;
      if (slv_port_req_i.aw_valid) begin
        updating_aw_d = 1'b1;
      end else begin
        updating_aw_d = 1'b0;
      end
    end

    // Update AW
    if (!updating_aw_done_q) begin // MIM-469 added the !updating_aw_done_q condition
      next_aw_out.addr = axi_pkg::beat_addr(next_aw_q.addr, next_aw_q.size, next_aw_q.len, next_aw_q.burst, start_zero_q);
      next_aw_out.len = next_aw_q.len - start_zero_q - end_zero_q; // no_rollover assertion added below
    end

    if (updating_aw_q && start_done_q && next_aw_out.len >= MaxNumBeats) begin
      len_too_long_d = 1'b1;
    end

    if (end_done_q) begin
      len_too_long_d = 1'b0;
    end

    // Send AW downstream
    if (((end_done_q || len_too_long_q) && ready_to_send_q) || updating_aw_done_q) begin
      mst_port_aw_valid = 1'b1;
      beats_to_send_d = {1'b0, next_aw_out.len} + 1;
      // Ensure AW sticks around to be properly handshaked
      if (mst_port_resp_i.aw_ready) begin
        updating_aw_done_d = 1'b0;
      end else begin
        updating_aw_done_d = 1'b1;
        // Keep constant as start_zero_q and end_zero_q are zeroed
        next_aw_d.addr = next_aw_out.addr;
        next_aw_d.len = next_aw_out.len;
      end
    end

  end
  no_rollover : assert property(
    @(posedge clk_i) (rst_ni !== 1'b1) || updating_aw_done_q || (next_aw_q.len >= start_zero_q + end_zero_q))
      else $error("next_aw_q.len must always be at least as big as start_zero_q - end_zero_q.");

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      next_aw_q <= '{ default: '0};
      updating_aw_q <= '0;
      updating_aw_done_q <= '0;
      start_zero_q <= '0;
      end_zero_q <= '0;
      start_done_q <= '0;
      end_done_q <= '0;
      beats_sent_q <= '0;
      beats_to_send_q <= '0;
      ready_to_send_q <= 1'b1;
      len_too_long_q <= '0;
    end else begin
      next_aw_q <= next_aw_d;
      updating_aw_q <= updating_aw_d;
      updating_aw_done_q <= updating_aw_done_d;
      start_zero_q <= start_zero_d;
      end_zero_q <= end_zero_d;
      start_done_q <= start_done_d;
      end_done_q <= end_done_d;
      beats_sent_q <= beats_sent_d;
      beats_to_send_q <= beats_to_send_d;
      ready_to_send_q <= ready_to_send_d;
      len_too_long_q <= len_too_long_d;
    end
  end

endmodule
