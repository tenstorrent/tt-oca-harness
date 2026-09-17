// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// DMA Request Manager
//
//-----------------------------------------------------------------------------

module idma_request_manager_wrapper #(
  parameter int unsigned NUM_CTRL_INTERFACES = 1,  // must be >= 1
  parameter int unsigned NUM_MST_INTERFACES = 1,  // must be >= 1

  parameter type req_t = logic,
  parameter type resp_t = logic
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic test_en_i,

  input  req_t  [NUM_CTRL_INTERFACES-1:0] ctrl_req_i,
  input  logic  [NUM_CTRL_INTERFACES-1:0] ctrl_req_valid_i,
  output logic  [NUM_CTRL_INTERFACES-1:0] ctrl_req_ready_o,

  output resp_t [NUM_CTRL_INTERFACES-1:0] ctrl_resp_o,
  output logic  [NUM_CTRL_INTERFACES-1:0] ctrl_resp_valid_o,
  input  logic  [NUM_CTRL_INTERFACES-1:0] ctrl_resp_ready_i,

  output req_t  [NUM_MST_INTERFACES-1:0] mst_req_o,
  output logic  [NUM_MST_INTERFACES-1:0] mst_req_valid_o,
  input  logic  [NUM_MST_INTERFACES-1:0] mst_req_ready_i,

  input  resp_t [NUM_MST_INTERFACES-1:0] mst_resp_i,
  input  logic  [NUM_MST_INTERFACES-1:0] mst_resp_valid_i,
  output logic  [NUM_MST_INTERFACES-1:0] mst_resp_ready_o
);

  if ((NUM_CTRL_INTERFACES == 1) && (NUM_MST_INTERFACES == 1)) begin : gen_passthrough
    assign mst_req_o         = ctrl_req_i;
    assign mst_req_valid_o   = ctrl_req_valid_i;
    assign ctrl_req_ready_o  = mst_req_ready_i;

    assign ctrl_resp_o       = mst_resp_i;
    assign ctrl_resp_valid_o = mst_resp_valid_i;
    assign mst_resp_ready_o  = ctrl_resp_ready_i;
  end else begin : gen_manager
    logic [NUM_MST_INTERFACES-1:0][NUM_CTRL_INTERFACES-1:0] ctrl_req_valid, ctrl_req_ready;
    logic [NUM_CTRL_INTERFACES-1:0][NUM_MST_INTERFACES-1:0] ctrl_resp_valid, ctrl_resp_ready;

    logic [NUM_MST_INTERFACES-1:0] mst_req_valid, mst_req_ready;

    resp_t [NUM_MST_INTERFACES-1:0] mst_resp;
    logic [NUM_MST_INTERFACES-1:0] mst_resp_valid, mst_resp_ready;

    logic [NUM_MST_INTERFACES-1:0][$clog2(NUM_CTRL_INTERFACES)-1:0]
        ctrl_winner_id, ctrl_completed_id;
    logic [NUM_MST_INTERFACES-1:0] req_tracking_fifo_full;

    // ctrl req ready is only the ready signal from the accepted req
    always_comb begin
      ctrl_req_ready_o = {(NUM_CTRL_INTERFACES) {1'b0}};
      for (int i = 0; i < NUM_MST_INTERFACES; i = i + 1) begin
        ctrl_req_ready_o = ctrl_req_ready_o | (ctrl_req_ready[i] & (mst_req_valid[i] << ctrl_winner_id[i]));
      end
    end

    for (genvar m = 0; m < NUM_MST_INTERFACES; m = m + 1) begin : gen_req_manager
      // ctrl reqs get arbitrated to mst
      rr_arb_tree #(
        .NumIn    (NUM_CTRL_INTERFACES),
        .DataType (req_t),
        .ExtPrio  (0),
        .AxiVldRdy(1),
        .LockIn   (0)   // don't lock in so in case mst is not ready, req can try a different req
      ) i_rr_arb_tree (
        .clk_i  (clk_i),
        .rst_ni (rst_ni),
        .flush_i(1'b0),
        .rr_i   ('0),
        .req_i  (ctrl_req_valid[m]),
        .gnt_o  (ctrl_req_ready[m]),
        .data_i (ctrl_req_i),
        .gnt_i  (mst_req_ready[m]),
        .req_o  (mst_req_valid[m]),
        .data_o (mst_req_o[m]),
        .idx_o  (ctrl_winner_id[m])
      );

      always_comb begin
        // once a mst accepts a request, block off request from other being seen by other mst
        // don't want mst executing the same request
        // -> this does create a long timing dependency
        if (m == 0) begin
          ctrl_req_valid[m] = ctrl_req_valid_i;
        end else begin
          ctrl_req_valid[m] = ctrl_req_valid[m-1] ^ (ctrl_req_valid_i & ('d1 << ctrl_winner_id[m-1]));
        end

        // don't ready/valid any requests if the req tracking fifo is full
        mst_req_ready[m] = mst_req_ready_i[m] && ~req_tracking_fifo_full[m];
        mst_req_valid_o[m] = mst_req_valid[m] && ~req_tracking_fifo_full[m];
      end

      // track which ctrl mapped to which mst
      // - push when req is accepted by a mst
      // - pop when mst responds
      fifo_v3 #(
        .FALL_THROUGH(1'b0),
        .DATA_WIDTH  ($clog2(NUM_CTRL_INTERFACES)),
        .DEPTH       (4)
      ) u_req_tracking_fifo (
        .clk_i     (clk_i),
        .rst_ni    (rst_ni),
        .flush_i   (1'b0),
        .testmode_i(test_en_i),
        .full_o    (req_tracking_fifo_full[m]),
        .empty_o   (/* NOT CONNECTED */),
        .usage_o   (/* NOT CONNECTED */),
        .data_i    (ctrl_winner_id[m]),
        .push_i    (mst_req_valid[m] & mst_req_ready[m]),
        .data_o    (ctrl_completed_id[m]),
        .pop_i     (mst_resp_valid[m] && mst_resp_ready[m])
      );

      // mst resp can only be valid when mst resp is ready
      // but, in case multiple masters want to respond to same ctrl, ready cannot be given
      // until valid is given to arbiter to decide which mst can resp
      // -> decouple this dependency with 1 depth fifo as a buffer
      stream_fifo #(
        .FALL_THROUGH(1'b0),
        .DATA_WIDTH  ($bits(resp_t)),
        .DEPTH       (1)
      ) u_resp_buffer (
        .clk_i     (clk_i),
        .rst_ni    (rst_ni),
        .flush_i   (1'b0),
        .testmode_i(test_en_i),
        .usage_o   (/* NOT CONNECTED */),
        .data_i    (mst_resp_i[m]),
        .valid_i   (mst_resp_valid_i[m]),
        .ready_o   (mst_resp_ready_o[m]),
        .data_o    (mst_resp[m]),
        .valid_o   (mst_resp_valid[m]),
        .ready_i   (mst_resp_ready[m])
      );

      // redirect to mst resp to corresponding ctrl
      always_comb begin
        for (int c = 0; c < NUM_CTRL_INTERFACES; c = c + 1) begin
          ctrl_resp_valid[c][m] = 1'b0;
          if (c == ctrl_completed_id[m]) begin
            ctrl_resp_valid[c][m] = mst_resp_valid[m];
            mst_resp_ready[m] = ctrl_resp_ready[c][m];
          end
        end
      end
    end

    // for every ctrl, need a resp arbiter in case multiple mst try to respond to the same ctrl
    for (genvar c = 0; c < NUM_CTRL_INTERFACES; c = c + 1) begin : gen_resp_manager
      rr_arb_tree #(
        .NumIn    (NUM_MST_INTERFACES),
        .DataType (resp_t),
        .ExtPrio  (0),
        .AxiVldRdy(1),
        .LockIn   (1)
      ) i_rr_arb_tree (
        .clk_i  (clk_i),
        .rst_ni (rst_ni),
        .flush_i(1'b0),
        .rr_i   ('0),
        .req_i  (ctrl_resp_valid[c]),
        .gnt_o  (ctrl_resp_ready[c]),
        .data_i (mst_resp),
        .gnt_i  (ctrl_resp_ready_i[c]),
        .req_o  (ctrl_resp_valid_o[c]),
        .data_o (ctrl_resp_o[c]),
        .idx_o  ()
      );
    end

  end

endmodule
