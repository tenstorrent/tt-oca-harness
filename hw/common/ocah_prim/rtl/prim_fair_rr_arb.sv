// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Arbitrate NumIn requesters round-robin through a combinational binary tree.
//
// request_o, data_o, index_o and grant_o are combinational; only the round-robin pointer
// and the optional lock state are registered. With NumIn of 1 the module is a pass-through.
// Select the arbitration behaviour with these parameters:
//
// - FairArb moves the pointer to the next requesting input after each grant, spreading
//   grants evenly across inputs.
// - LockIn holds a winner until grant_i completes.
// - ExtPrio replaces the internal RR counter with rr_priority_i so multiple arbiters can
//   share rotating priorities in lock-step; tie rr_priority_i to '0 for static priority,
//   lowest index first. FairArb and LockIn apply only when ExtPrio is 0.
// - AxiVldRdy treats request/grant as AXI-style valid/ready, so upstream valid must not
//   depend on ready; it reduces arbiter delay and area.

module prim_fair_rr_arb #(
  parameter int unsigned NumIn      = 64,  // Number of inputs to arbitrate.
  parameter int unsigned DataWidth  = 32,  // Payload width in bits; unused when DataType is
                                           // overridden.
  parameter type         DataType   = logic [DataWidth-1:0],  // Payload type; defaults to logic
                                                              // [DataWidth-1:0].
  parameter bit          ExtPrio    = 1'b0,  // 1 overrides the internal RR counter with
                                             // rr_priority_i. Share rr_priority_i across arbiters
                                             // for lock-step rotation; tie to '0 for static
                                             // priority.
  parameter bit          AxiVldRdy  = 1'b0,  // 1 treats request/grant as AXI valid/ready: upstream
                                             // valid must not depend on ready, and grant_o may
                                             // assert on the selected input without its request;
                                             // reduces arbiter delay and area.
  parameter bit          LockIn     = 1'b0,  // 1 freezes the request vector, and so the winning
                                             // index, while request_o is high and grant_i is low;
                                             // ignored when ExtPrio is 1.
  parameter bit          FairArb    = 1'b1,  // 1 spreads throughput evenly across inputs; 0
                                             // advances the pointer by one per grant. Ignored when
                                             // ExtPrio is 1.
  localparam int unsigned IdxWidth   = (NumIn > 32'd1) ? unsigned'($clog2(NumIn)) : 32'd1,  // Dependent width of priority and index; do not overwrite.
  parameter type         idx_t      = logic [IdxWidth-1:0]  // Type for arbitration priority and
                                                            // granted index; do not overwrite
                                                            // IdxWidth behind it.
) (
  input  logic                clk_i,  // Clock, positive-edge triggered.
  input  logic                rst_ni,  // Active-low reset, sampled synchronously.
  input  logic                flush_i,  // Synchronously clears the RR pointer and, with LockIn, the
                                        // lock state; no effect when ExtPrio is 1.
  input  idx_t                rr_priority_i,  // External RR priority; used only when ExtPrio is 1.
  input  logic    [NumIn-1:0] request_i,  // Per-port arbitration requests.
  /* verilator lint_off UNOPTFLAT */
  output logic    [NumIn-1:0] grant_o,  // Per-port grants.
  /* verilator lint_on UNOPTFLAT */
  input  DataType [NumIn-1:0] data_i,  // Per-port payloads.
  output logic                request_o,  // Winning request toward the destination.
  input  logic                grant_i,  // Destination grant for the winner.
  output DataType             data_o,  // Winning payload.
  output idx_t                index_o  // Index of the winning input; valid while request_o is high.
);

  `include "ocah_assert.svh"


  // just pass through in this corner case
  if (NumIn == unsigned'(1)) begin : gen_pass_through
    assign request_o    = request_i[0];
    assign grant_o[0] = grant_i;
    assign data_o   = data_i[0];
    assign index_o    = '0;
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
    assign request_o        = req_nodes[0];
    assign data_o       = data_nodes[0];
    assign index_o        = index_nodes[0];

    if (ExtPrio) begin : gen_ext_rr
      assign rr_q       = rr_priority_i;
      assign req_d      = request_i;
    end else begin : gen_int_rr
      idx_t rr_d;

      // lock arbiter decision in case we got at least one req and no acknowledge
      if (LockIn) begin : gen_lock
        logic lock_d, lock_q;
        logic [NumIn-1:0] req_q;

        assign lock_d     = request_o & ~grant_i;
        assign req_d      = (lock_q) ? req_q : request_i;

        always_ff @(posedge clk_i) begin : p_lock_reg
          if (!rst_ni) begin
            lock_q <= '0;
          end else begin
            if (flush_i) begin
              lock_q <= '0;
            end else begin
              lock_q <= lock_d;
            end
          end
        end

        `OCAH_ASSERT_IF(LockImplicationA,
                        request_o && (!grant_i && !flush_i) |=> index_o == $past(index_o), LockIn,
                        clk_i, (!rst_ni || flush_i))
        wire [NumIn-1:0] req_for_assertion_only = req_q & request_i;
        `OCAH_ASSERT_IF(NoDeassertReqWhenLockedA, lock_d |=> req_for_assertion_only == req_q,
                        LockIn, clk_i, (!rst_ni || flush_i))

        always_ff @(posedge clk_i) begin : p_req_regs
          if (!rst_ni) begin
            req_q <= '0;
          end else begin
            if (flush_i) begin
              req_q <= '0;
            end else begin
              req_q <= req_d;
            end
          end
        end
      end else begin : gen_no_lock
        assign req_d = request_i;
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
        ) u_lzc_upper (
          .in_i   ( upper_mask  ),
          .count_o( upper_idx   ),
          .empty_o( upper_empty )
        );

        prim_zero_counter #(
          .WIDTH        (NumIn),
          .COUNT_LEADING(1'b0)
        ) u_lzc_lower (
          .in_i   ( lower_mask  ),
          .count_o( lower_idx   ),
          .empty_o( /*unused*/  )
        );

        assign next_idx = upper_empty      ? lower_idx : upper_idx;
        assign rr_d     = (grant_i && request_o) ? next_idx  : rr_q;

      end else begin : gen_unfair_arb
        assign rr_d = (grant_i && request_o) ? ((rr_q == idx_t'(NumIn-1)) ? '0 : rr_q + 1'b1) : rr_q;
      end

      // this holds the highest priority
      always_ff @(posedge clk_i) begin : p_rr_regs
        if (!rst_ni) begin
          rr_q <= '0;
        end else begin
          if (flush_i) begin
            rr_q <= '0;
          end else begin
            rr_q <= rr_d;
          end
        end
      end
    end

    assign gnt_nodes[0] = grant_i;

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
            assign data_nodes[Idx0]  = (sel) ? data_i[l*2+1] : data_i[l*2];
            assign grant_o[l*2]        = gnt_nodes[Idx0] & (AxiVldRdy | req_d[l*2])   & ~sel;
            assign grant_o[l*2+1]      = gnt_nodes[Idx0] & (AxiVldRdy | req_d[l*2+1]) & sel;
          end
          // if only the first index is still in the vector...
          if (unsigned'(l) * 2 == NumIn - 1) begin : gen_first
            assign req_nodes[Idx0]   = req_d[l*2];
            assign index_nodes[Idx0] = '0;// always zero in this case
            assign data_nodes[Idx0]  = data_i[l*2];
            assign grant_o[l*2]        = gnt_nodes[Idx0] & (AxiVldRdy | req_d[l*2]);
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

    `OCAH_ASSERT(One_hot_grant_A, $onehot0(grant_o), clk_i, (!rst_ni || flush_i))
    `OCAH_ASSERT(Grant_implies_grant_A, |grant_o |-> grant_i, clk_i, (!rst_ni || flush_i))
    `OCAH_ASSERT(Request_grant_chain_A, request_o |-> grant_i |-> |grant_o, clk_i,
                 (!rst_ni || flush_i))
    `OCAH_ASSERT(Index_matches_grant_A, request_o |-> grant_i |-> grant_o[index_o], clk_i,
                 (!rst_ni || flush_i))
    `OCAH_ASSERT(Req_in_implies_req_out_A, |request_i |-> request_o, clk_i, (!rst_ni || flush_i))
    `OCAH_ASSERT(Req_out_impl, request_o |-> |request_i, clk_i, (!rst_ni || flush_i))
  end


endmodule
