// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Fair Round Robin arbiter
//
//--------------------------------------------------

module prim_fair_rr_arb #(
  /// Number of inputs to be arbitrated.
  parameter int unsigned NumIn      = 64,
  /// Data width of the payload in bits. Not needed if `DataType` is overwritten.
  parameter int unsigned DataWidth  = 32,
  /// Data type of the payload, can be overwritten with custom type. Only use of `DataWidth`.
  parameter type         DataType   = logic [DataWidth-1:0],
  /// The `ExtPrio` option allows to override the internal round robin counter via the
  /// `i_rr_priority` signal. This can be useful in case multiple arbiters need to have
  /// rotating priorities that are operating in lock-step. If static priority arbitration
  /// is needed, just connect `i_rr_priority` to '0.
  ///
  /// Set to 1'b1 to enable.
  parameter bit          ExtPrio    = 1'b0,
  /// If `AxiVldRdy` is set, the req/gnt signals are compliant with the AXI style vld/rdy
  /// handshake. Namely, upstream vld (req) must not depend on rdy (gnt), as it can be deasserted
  /// again even though vld is asserted. Enabling `AxiVldRdy` leads to a reduction of arbiter
  /// delay and area.
  ///
  /// Set to `1'b1` to treat req/gnt as vld/rdy.
  parameter bit          AxiVldRdy  = 1'b0,
  /// The `LockIn` option prevents the arbiter from changing the arbitration
  /// decision when the arbiter is disabled. I.e., the index of the first request
  /// that wins the arbitration will be locked in case the destination is not
  /// able to grant the request in the same cycle.
  ///
  /// Set to `1'b1` to enable.
  parameter bit          LockIn     = 1'b0,
  /// When set, ensures that throughput gets distributed evenly between all inputs.
  ///
  /// Set to `1'b0` to disable.
  parameter bit          FairArb    = 1'b1,
  /// Dependent parameter, do **not** overwrite.
  /// Width of the arbitration priority signal and the arbitrated index.
  /// Dependent parameter, do **not** overwrite.
  /// Type for defining the arbitration priority and arbitrated index signal.
  localparam int unsigned IdxWidth   = (NumIn > 32'd1) ? unsigned'($clog2(NumIn)) : 32'd1,
  parameter type         idx_t      = logic [IdxWidth-1:0]
) (
  /// Clock, positive edge triggered.
  input  logic                i_clk,
  /// Asynchronous reset, active low.
  input  logic                i_reset_n,
  /// Clears the arbiter state. Only used if `ExtPrio` is `1'b0` or `LockIn` is `1'b1`.
  input  logic                i_flush,
  /// External round-robin priority. Only used if `ExtPrio` is `1'b1.`
  input  idx_t                i_rr_priority,
  /// Input requests arbitration.
  input  logic    [NumIn-1:0] i_request,
  /* verilator lint_off UNOPTFLAT */
  /// Input request is granted.
  output logic    [NumIn-1:0] o_grant,
  /* verilator lint_on UNOPTFLAT */
  /// Input data for arbitration.
  input  DataType [NumIn-1:0] i_data,
  /// Output request is valid.
  output logic                o_request,
  /// Output request is granted.
  input  logic                i_grant,
  /// Output data.
  output DataType             o_data,
  /// Index from which input the data came from.
  output idx_t                o_index
);

  `include "ocah_assert.svh"


  // just pass through in this corner case
  if (NumIn == unsigned'(1)) begin : gen_pass_through
    assign o_request    = i_request[0];
    assign o_grant[0] = i_grant;
    assign o_data   = i_data[0];
    assign o_index    = '0;
    // non-degenerate cases
  end else begin : gen_arbiter
    localparam int unsigned NumLevels = unsigned'($clog2(NumIn));

    /* verilator lint_off UNOPTFLAT */
    idx_t    [2**NumLevels-2:0] index_nodes; // used to propagate the indices
    DataType [2**NumLevels-2:0] data_nodes;  // used to propagate the data
    logic    [2**NumLevels-2:0] gnt_nodes;   // used to propagate the grant to masters
    logic    [2**NumLevels-2:0] req_nodes;   // used to propagate the requests to slave
    /* lint_off */
    idx_t                       rr_q;
    logic [NumIn-1:0]           req_d;

    // the final arbitration decision can be taken from the root of the tree
    assign o_request        = req_nodes[0];
    assign o_data       = data_nodes[0];
    assign o_index        = index_nodes[0];

    if (ExtPrio) begin : gen_ext_rr
      assign rr_q       = i_rr_priority;
      assign req_d      = i_request;
    end else begin : gen_int_rr
      idx_t rr_d;

      // lock arbiter decision in case we got at least one req and no acknowledge
      if (LockIn) begin : gen_lock
        logic lock_d, lock_q;
        logic [NumIn-1:0] req_q;

        assign lock_d     = o_request & ~i_grant;
        assign req_d      = (lock_q) ? req_q : i_request;

        always_ff @(posedge i_clk) begin : p_lock_reg
          if (!i_reset_n) begin
            lock_q <= '0;
          end else begin
            if (i_flush) begin
              lock_q <= '0;
            end else begin
              lock_q <= lock_d;
            end
          end
        end

        `OCAH_ASSERT_IF(LockImplicationA,
                        o_request && (!i_grant && !i_flush) |=> o_index == $past(o_index), LockIn,
                        i_clk, (!i_reset_n || i_flush))
        wire [NumIn-1:0] req_for_assertion_only = req_q & i_request;
        `OCAH_ASSERT_IF(NoDeassertReqWhenLockedA, lock_d |=> req_for_assertion_only == req_q,
                        LockIn, i_clk, (!i_reset_n || i_flush))

        always_ff @(posedge i_clk) begin : p_req_regs
          if (!i_reset_n) begin
            req_q <= '0;
          end else begin
            if (i_flush) begin
              req_q <= '0;
            end else begin
              req_q <= req_d;
            end
          end
        end
      end else begin : gen_no_lock
        assign req_d = i_request;
      end

      if (FairArb) begin : gen_fair_arb
        logic [NumIn-1:0] upper_mask, lower_mask;
        idx_t upper_idx, lower_idx, next_idx;
        logic upper_empty, lower_empty;

        for (genvar i = 0; i < NumIn; i++) begin : gen_mask
          assign upper_mask[i] = (i >  rr_q) ? req_d[i] : 1'b0;
          assign lower_mask[i] = (i <= rr_q) ? req_d[i] : 1'b0;
        end

        prim_zero_counter #(
          .WIDTH        (NumIn),
          .COUNT_LEADING(1'b0)
        ) i_lzc_upper (
          .i_in   ( upper_mask  ),
          .o_count( upper_idx   ),
          .o_empty( upper_empty )
        );

        prim_zero_counter #(
          .WIDTH        (NumIn),
          .COUNT_LEADING(1'b0)
        ) i_lzc_lower (
          .i_in   ( lower_mask  ),
          .o_count( lower_idx   ),
          .o_empty( /*unused*/  )
        );

        assign next_idx = upper_empty      ? lower_idx : upper_idx;
        assign rr_d     = (i_grant && o_request) ? next_idx  : rr_q;

      end else begin : gen_unfair_arb
        assign rr_d = (i_grant && o_request) ? ((rr_q == idx_t'(NumIn-1)) ? '0 : rr_q + 1'b1) : rr_q;
      end

      // this holds the highest priority
      always_ff @(posedge i_clk) begin : p_rr_regs
        if (!i_reset_n) begin
          rr_q <= '0;
        end else begin
          if (i_flush) begin
            rr_q <= '0;
          end else begin
            rr_q <= rr_d;
          end
        end
      end
    end

    assign gnt_nodes[0] = i_grant;

    // arbiter tree
    for (genvar level = 0; unsigned'(level) < NumLevels; level++) begin : gen_levels
      for (genvar l = 0; l < 2 ** level; l++) begin : gen_level
        // local select signal
        logic sel;
        // index calcs
        localparam int unsigned Idx0 = 2 ** level - 1 + l;  // current node
        localparam int unsigned Idx1 = 2 ** (level + 1) - 1 + l * 2;
        //////////////////////////////////////////////////////////////
        // uppermost level where data is fed in from the inputs
        if (unsigned'(level) == NumLevels - 1) begin : gen_first_level
          // if two successive indices are still in the vector...
          if (unsigned'(l) * 2 < NumIn - 1) begin : gen_reduce
            assign req_nodes[Idx0]   = req_d[l*2] | req_d[l*2+1];

            // arbitration: round robin
            assign sel =  ~req_d[l*2] | req_d[l*2+1] & rr_q[NumLevels-1-level];

            assign index_nodes[Idx0] = idx_t'(sel);
            assign data_nodes[Idx0]  = (sel) ? i_data[l*2+1] : i_data[l*2];
            assign o_grant[l*2]        = gnt_nodes[Idx0] & (AxiVldRdy | req_d[l*2])   & ~sel;
            assign o_grant[l*2+1]      = gnt_nodes[Idx0] & (AxiVldRdy | req_d[l*2+1]) & sel;
          end
          // if only the first index is still in the vector...
          if (unsigned'(l) * 2 == NumIn - 1) begin : gen_first
            assign req_nodes[Idx0]   = req_d[l*2];
            assign index_nodes[Idx0] = '0;// always zero in this case
            assign data_nodes[Idx0]  = i_data[l*2];
            assign o_grant[l*2]        = gnt_nodes[Idx0] & (AxiVldRdy | req_d[l*2]);
          end
          // if index is out of range, fill up with zeros (will get pruned)
          if (unsigned'(l) * 2 > NumIn - 1) begin : gen_out_of_range
            assign req_nodes[Idx0]   = 1'b0;
            assign index_nodes[Idx0] = idx_t'('0);
            assign data_nodes[Idx0]  = DataType'('0);
          end
          //////////////////////////////////////////////////////////////
          // general case for other levels within the tree
        end else begin : gen_other_levels
          assign req_nodes[Idx0]   = req_nodes[Idx1] | req_nodes[Idx1+1];

          // arbitration: round robin
          assign sel =  ~req_nodes[Idx1] | req_nodes[Idx1+1] & rr_q[NumLevels-1-level];

          assign index_nodes[Idx0] = (sel) ?
            idx_t'({1'b1, index_nodes[Idx1+1][NumLevels-unsigned'(level)-2:0]}) :
            idx_t'({1'b0, index_nodes[Idx1][NumLevels-unsigned'(level)-2:0]});

          assign data_nodes[Idx0]  = (sel) ? data_nodes[Idx1+1] : data_nodes[Idx1];
          assign gnt_nodes[Idx1]   = gnt_nodes[Idx0] & ~sel;
          assign gnt_nodes[Idx1+1] = gnt_nodes[Idx0] & sel;
        end
        //////////////////////////////////////////////////////////////
      end
    end

    `OCAH_ASSERT(One_hot_grant_A, $onehot0(o_grant), i_clk, (!i_reset_n || i_flush))
    `OCAH_ASSERT(Grant_implies_grant_A, |o_grant |-> i_grant, i_clk, (!i_reset_n || i_flush))
    `OCAH_ASSERT(Request_grant_chain_A, o_request |-> i_grant |-> |o_grant, i_clk,
                 (!i_reset_n || i_flush))
    `OCAH_ASSERT(Index_matches_grant_A, o_request |-> i_grant |-> o_grant[o_index], i_clk,
                 (!i_reset_n || i_flush))
    `OCAH_ASSERT(Req_in_implies_req_out_A, |i_request |-> o_request, i_clk, (!i_reset_n || i_flush))
    `OCAH_ASSERT(Req_out_impl, o_request |-> |i_request, i_clk, (!i_reset_n || i_flush))
  end


endmodule
