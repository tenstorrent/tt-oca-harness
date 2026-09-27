// Copyright 2026 Tenstorrent Inc.
//
// Based on axi_isolate.sv:
// Copyright (c) 2019-2020 ETH Zurich, University of Bologna
// Licensed under the Solderpad Hardware License, Version 0.51.

`include "axi/typedef.svh"
`include "common_cells/registers.svh"

/// AXI4-Lite variant of `axi_isolate`: isolates the master port from the slave port.  When the
/// isolation is not active, the two ports are directly connected.
///
/// The isolation interface has two signals: `isolate_i` and `isolated_o`.  When `isolate_i` is
/// asserted, all open transactions are gracefully terminated.  When no transactions are in flight
/// anymore, the `isolated_o` output is asserted.  As long as `isolated_o` is asserted, all output
/// signals in `mst_req_o` are silenced to `'0`.  When isolated, new transactions initiated on the
/// slave port are stalled until the isolation is terminated by deasserting `isolate_i`.
///
/// ## Response
///
/// If the `TerminateTransaction` parameter is set to `1'b1`, the module will return `SLVERR`
/// responses for incoming transactions while the module isolates.  The data returned on the bus is
/// `1501A7ED` (hexspeak for isolated).
///
/// If `TerminateTransaction` is set to `1'b0`, the transaction will block indefinitely until the
/// module is de-isolated again.
module axi_lite_isolate #(
  /// Maximum number of pending requests per channel
  parameter int unsigned NumPending = 32'd16,
  /// Gracefully terminate all incoming transactions in case of isolation by returning proper
  /// error responses.
  parameter bit TerminateTransaction = 1'b0,
  /// Address width of all AXI4-Lite ports
  parameter int unsigned AxiAddrWidth = 32'd0,
  /// Data width of all AXI4-Lite ports
  parameter int unsigned AxiDataWidth = 32'd0,
  /// Request struct type of all AXI4-Lite ports
  parameter type axi_lite_req_t  = logic,
  /// Response struct type of all AXI4-Lite ports
  parameter type axi_lite_resp_t = logic
) (
  /// Rising-edge clock of all ports
  input  logic           clk_i,
  /// Asynchronous reset, active low
  input  logic           rst_ni,
  /// Testmode enable
  input  logic           test_i,
  /// Slave port request
  input  axi_lite_req_t  slv_req_i,
  /// Slave port response
  output axi_lite_resp_t slv_resp_o,
  /// Master port request
  output axi_lite_req_t  mst_req_o,
  /// Master port response
  input  axi_lite_resp_t mst_resp_i,
  /// Isolate master port from slave port
  input  logic           isolate_i,
  /// Master port is isolated from slave port
  output logic           isolated_o
);

  typedef logic [AxiAddrWidth-1:0]   addr_t;
  typedef logic [AxiDataWidth-1:0]   data_t;
  typedef logic [AxiDataWidth/8-1:0] strb_t;

  `AXI_LITE_TYPEDEF_AW_CHAN_T(aw_chan_t, addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(w_chan_t, data_t, strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(ar_chan_t, addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(r_chan_t, data_t)

  // Capacity of the isolation core, sized above the demux's maximum of in-flight
  // transactions. This makes the inner counter-saturation stall unreachable, so if a host
  // request is stalled then it's always stalled by the demux itself, where it is not
  // yet committed to a port and can still be steered to the error slave.
  localparam int unsigned DemuxMaxPending = 32'd2 * NumPending;
  localparam int unsigned InnerPending    =
      TerminateTransaction ? DemuxMaxPending + 32'd1 : NumPending;

  axi_lite_req_t  [1:0] demux_req;
  axi_lite_resp_t [1:0] demux_rsp;

  // plus 1 in clog for accounting no open transaction
  localparam int unsigned CounterWidth = $clog2(InnerPending + 32'd1);
  typedef logic [CounterWidth-1:0] cnt_t;

  typedef enum logic [1:0] {
    Normal,
    Hold,
    Drain,
    Isolate
  } isolate_state_e;
  isolate_state_e state_aw_d, state_aw_q, state_ar_d, state_ar_q;
  logic           update_aw_state,        update_ar_state;

  cnt_t pending_aw_d,  pending_aw_q;
  logic update_aw_cnt;

  cnt_t pending_w_d,   pending_w_q;
  logic update_w_cnt,  connect_w;

  cnt_t pending_ar_d,  pending_ar_q;
  logic update_ar_cnt;

  if (TerminateTransaction) begin : g_terminate
    logic sel_aw_q, sel_ar_q;
    // A request is presented at a demux master port and not yet accepted.
    logic demux_aw_unaccepted, demux_ar_unaccepted;

    assign demux_aw_unaccepted = (demux_req[0].aw_valid | demux_req[1].aw_valid)
                                 & ~slv_resp_o.aw_ready;
    assign demux_ar_unaccepted = (demux_req[0].ar_valid | demux_req[1].ar_valid)
                                 & ~slv_resp_o.ar_ready;

    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        sel_aw_q <= 1'b1;
        sel_ar_q <= 1'b1;
      end else begin
        if (!demux_aw_unaccepted) sel_aw_q <= isolate_i;
        if (!demux_ar_unaccepted) sel_ar_q <= isolate_i;
      end
    end

    axi_lite_demux #(
      .aw_chan_t  ( aw_chan_t       ),
      .w_chan_t   ( w_chan_t        ),
      .b_chan_t   ( b_chan_t        ),
      .ar_chan_t  ( ar_chan_t       ),
      .r_chan_t   ( r_chan_t        ),
      .axi_req_t  ( axi_lite_req_t  ),
      .axi_resp_t ( axi_lite_resp_t ),
      .NoMstPorts ( 32'd2           ),
      .MaxTrans   ( NumPending      ),
      .SpillAw    ( 1'b0            ),
      .SpillW     ( 1'b0            ),
      .SpillB     ( 1'b0            ),
      .SpillAr    ( 1'b0            ),
      .SpillR     ( 1'b0            )
    ) i_axi_lite_demux (
      .clk_i,
      .rst_ni,
      .test_i,
      .slv_req_i,
      .slv_aw_select_i ( sel_aw_q  ),
      .slv_ar_select_i ( sel_ar_q  ),
      .slv_resp_o,
      .mst_reqs_o      ( demux_req ),
      .mst_resps_i     ( demux_rsp )
    );

    // Error slave for the isolated demux port: accepts one transaction per direction at a time
    // and responds with SLVERR.
    localparam data_t IsolateErrorData = data_t'('h1501A7ED);

    axi_lite_resp_t isolate_err_rsp;
    logic aw_wait_d, aw_wait_q, w_wait_d, w_wait_q, ar_wait_d, ar_wait_q;
    logic isolate_err_b_valid, isolate_err_r_valid;

    assign isolate_err_b_valid = aw_wait_q & w_wait_q;
    assign isolate_err_r_valid = ar_wait_q;

    always_comb begin
      isolate_err_rsp          = '0;
      isolate_err_rsp.aw_ready = ~aw_wait_q;
      isolate_err_rsp.w_ready  = ~w_wait_q;
      isolate_err_rsp.b_valid  = isolate_err_b_valid;
      isolate_err_rsp.b.resp   = axi_pkg::RESP_SLVERR;
      isolate_err_rsp.ar_ready = ~ar_wait_q;
      isolate_err_rsp.r_valid  = isolate_err_r_valid;
      isolate_err_rsp.r.resp   = axi_pkg::RESP_SLVERR;
      isolate_err_rsp.r.data   = IsolateErrorData;
    end

    assign demux_rsp[1] = isolate_err_rsp;

    always_comb begin
      aw_wait_d = aw_wait_q;
      w_wait_d  = w_wait_q;
      ar_wait_d = ar_wait_q;
      if (demux_req[1].aw_valid && !aw_wait_q) begin
        aw_wait_d = 1'b1;
      end
      if (demux_req[1].w_valid && !w_wait_q) begin
        w_wait_d = 1'b1;
      end
      if (isolate_err_b_valid && demux_req[1].b_ready) begin
        aw_wait_d = 1'b0;
        w_wait_d  = 1'b0;
      end
      if (demux_req[1].ar_valid && !ar_wait_q) begin
        ar_wait_d = 1'b1;
      end
      if (isolate_err_r_valid && demux_req[1].r_ready) begin
        ar_wait_d = 1'b0;
      end
    end

    `FFARN(aw_wait_q, aw_wait_d, 1'b0, clk_i, rst_ni)
    `FFARN(w_wait_q, w_wait_d, 1'b0, clk_i, rst_ni)
    `FFARN(ar_wait_q, ar_wait_d, 1'b0, clk_i, rst_ni)
  end else begin : g_passthrough
    assign demux_req[0] = slv_req_i;
    assign slv_resp_o   = demux_rsp[0];
    // In pass-through, silence the second demux port as it is not used
    assign demux_req[1] = '0;
    assign demux_rsp[1] = '0;
  end

  `FFLARN(pending_aw_q, pending_aw_d, update_aw_cnt, '0, clk_i, rst_ni)
  `FFLARN(pending_w_q, pending_w_d, update_w_cnt, '0, clk_i, rst_ni)
  `FFLARN(pending_ar_q, pending_ar_d, update_ar_cnt, '0, clk_i, rst_ni)
  `FFLARN(state_aw_q, state_aw_d, update_aw_state, Isolate, clk_i, rst_ni)
  `FFLARN(state_ar_q, state_ar_d, update_ar_state, Isolate, clk_i, rst_ni)

  // Update counters
  always_comb begin
    pending_aw_d  = pending_aw_q;
    update_aw_cnt = 1'b0;
    pending_w_d   = pending_w_q;
    update_w_cnt  = 1'b0;
    connect_w     = 1'b0;
    pending_ar_d  = pending_ar_q;
    update_ar_cnt = 1'b0;
    // write counters
    if (mst_req_o.aw_valid && (state_aw_q == Normal)) begin
      pending_aw_d++;
      update_aw_cnt = 1'b1;
      pending_w_d++;
      update_w_cnt  = 1'b1;
      connect_w     = 1'b1;
    end
    if (mst_req_o.w_valid && mst_resp_i.w_ready) begin
      pending_w_d--;
      update_w_cnt = 1'b1;
    end
    if (mst_resp_i.b_valid && mst_req_o.b_ready) begin
      pending_aw_d--;
      update_aw_cnt = 1'b1;
    end
    // read counters
    if (mst_req_o.ar_valid && (state_ar_q == Normal)) begin
      pending_ar_d++;
      update_ar_cnt = 1'b1;
    end
    if (mst_resp_i.r_valid && mst_req_o.r_ready) begin
      pending_ar_d--;
      update_ar_cnt = 1'b1;
    end
  end

  // Perform isolation.
  always_comb begin
    // Default assignments
    state_aw_d      = state_aw_q;
    update_aw_state = 1'b0;
    state_ar_d      = state_ar_q;
    update_ar_state = 1'b0;
    // Connect channel per default
    mst_req_o       = demux_req[0];
    demux_rsp[0]      = mst_resp_i;

    /////////////////////////////////////////////////////////////
    // Write transaction
    /////////////////////////////////////////////////////////////
    unique case (state_aw_q)
      Normal: begin // Normal operation
        // Cut valid handshake if a counter capacity is reached.
        if (pending_aw_q >= cnt_t'(InnerPending) || pending_w_q >= cnt_t'(InnerPending)) begin
          mst_req_o.aw_valid  = 1'b0;
          demux_rsp[0].aw_ready = 1'b0;
          if (isolate_i) begin
            state_aw_d      = Drain;
            update_aw_state = 1'b1;
          end
        end else begin
          // here the AW handshake is connected normally
          if (demux_req[0].aw_valid && !mst_resp_i.aw_ready) begin
            state_aw_d      = Hold;
            update_aw_state = 1'b1;
          end else begin
            if (isolate_i) begin
              state_aw_d      = Drain;
              update_aw_state = 1'b1;
            end
          end
        end
      end
      Hold: begin // Hold the valid signal on 1'b1 if there was no transfer
        mst_req_o.aw_valid = 1'b1;
        // aw_ready normal connected
        if (mst_resp_i.aw_ready) begin
          update_aw_state = 1'b1;
          state_aw_d      = isolate_i ? Drain : Normal;
        end
      end
      Drain: begin // cut the AW channel until counter is zero
        mst_req_o.aw        = '0;
        mst_req_o.aw_valid  = 1'b0;
        demux_rsp[0].aw_ready = 1'b0;
        if (pending_aw_q == '0) begin
          state_aw_d      = Isolate;
          update_aw_state = 1'b1;
        end
      end
      Isolate: begin // Cut the signals to the outputs
        mst_req_o.aw        = '0;
        mst_req_o.aw_valid  = 1'b0;
        demux_rsp[0].aw_ready = 1'b0;
        demux_rsp[0].b        = '0;
        demux_rsp[0].b_valid  = 1'b0;
        mst_req_o.b_ready   = 1'b0;
        if (!isolate_i) begin
          state_aw_d      = Normal;
          update_aw_state = 1'b1;
        end
      end
      default: /*do nothing*/;
    endcase

    // W channel is cut as long the counter is zero and not explicitly unlocked through an AW.
    if ((pending_w_q == '0) && !connect_w) begin
      mst_req_o.w        = '0;
      mst_req_o.w_valid  = 1'b0;
      demux_rsp[0].w_ready = 1'b0;
    end

    /////////////////////////////////////////////////////////////
    // Read transaction
    /////////////////////////////////////////////////////////////
    unique case (state_ar_q)
      Normal: begin
        // cut handshake if counter capacity is reached
        if (pending_ar_q >= cnt_t'(InnerPending)) begin
          mst_req_o.ar_valid  = 1'b0;
          demux_rsp[0].ar_ready = 1'b0;
          if (isolate_i) begin
            state_ar_d      = Drain;
            update_ar_state = 1'b1;
          end
        end else begin
          // here the AR handshake is connected normally
          if (demux_req[0].ar_valid && !mst_resp_i.ar_ready) begin
            state_ar_d      = Hold;
            update_ar_state = 1'b1;
          end else begin
            if (isolate_i) begin
              state_ar_d      = Drain;
              update_ar_state = 1'b1;
            end
          end
        end
      end
      Hold: begin // Hold the valid signal on 1'b1 if there was no transfer
        mst_req_o.ar_valid = 1'b1;
        // ar_ready normal connected
        if (mst_resp_i.ar_ready) begin
          update_ar_state = 1'b1;
          state_ar_d      = isolate_i ? Drain : Normal;
        end
      end
      Drain: begin
        mst_req_o.ar        = '0;
        mst_req_o.ar_valid  = 1'b0;
        demux_rsp[0].ar_ready = 1'b0;
        if (pending_ar_q == '0) begin
          state_ar_d      = Isolate;
          update_ar_state = 1'b1;
        end
      end
      Isolate: begin
        mst_req_o.ar        = '0;
        mst_req_o.ar_valid  = 1'b0;
        demux_rsp[0].ar_ready = 1'b0;
        demux_rsp[0].r        = '0;
        demux_rsp[0].r_valid  = 1'b0;
        mst_req_o.r_ready   = 1'b0;
        if (!isolate_i) begin
          state_ar_d      = Normal;
          update_ar_state = 1'b1;
        end
      end
      default: /*do nothing*/;
    endcase
  end

  // the isolated output signal
  assign isolated_o = (state_aw_q == Isolate && state_ar_q == Isolate);

// pragma translate_off
`ifndef VERILATOR
  initial begin
    assume (InnerPending > 0) else $fatal(1, "At least one pending transaction required.");
  end
`ifndef XSIM
  default disable iff (!rst_ni);
  aw_overflow: assert property (@(posedge clk_i)
      (pending_aw_q == '1) |=> (pending_aw_q != '0)) else
      $fatal(1, "pending_aw_q overflowed");
  ar_overflow: assert property (@(posedge clk_i)
      (pending_ar_q == '1) |=> (pending_ar_q != '0)) else
      $fatal(1, "pending_ar_q overflowed");
  aw_underflow: assert property (@(posedge clk_i)
      (pending_aw_q == '0) |=> (pending_aw_q != '1)) else
      $fatal(1, "pending_aw_q underflowed");
  ar_underflow: assert property (@(posedge clk_i)
      (pending_ar_q == '0) |=> (pending_ar_q != '1)) else
      $fatal(1, "pending_ar_q underflowed");
`endif
`endif
// pragma translate_on
endmodule
