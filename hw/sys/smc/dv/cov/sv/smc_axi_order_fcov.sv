// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// One AXI manager's ordering and depth functional coverage. The module keeps
// one outstanding table per direction, MAX_DEPTH entries deep and ordered by
// address acceptance; each entry holds its transaction's ID, so the head of a
// table is the head of that direction's in-order ID FIFO. A response belongs to
// the oldest entry with its ID, as AXI orders responses within one ID.
//
// Every point is outcome-gated: it counts on the cycle the sampled transaction
// completes (the B handshake of a write, the RLAST handshake of a read), and
// only when every response of that transaction is OKAY. A point records what
// the transaction met on the bus and that the DUT completed it; it never
// judges the returned data.
//
//   c_{rd,wr}_depth_{one,few,many}  transactions of that direction in flight at
//                                   its address accept, itself included: 1, 2-4
//                                   or 5-16
//   c_aw_first / c_w_first /        whether the manager raised AWVALID or the
//   c_aw_w_same_cycle               first WVALID of the write first, or both in
//                                   one cycle
//   c_ar_during_write               a read accepted while an accepted AW had no
//                                   WVALID yet; counts once that read and that
//                                   write have both completed OKAY
//   c_rid_out_of_order              a read with an OKAY R beat whose RID was not
//                                   the oldest outstanding ARID
//   c_bid_out_of_order              a write whose BID was not the oldest
//                                   outstanding AWID
//   c_rd_eight_ids                  eight distinct ARIDs accepted since the read
//                                   count was last zero; counts when the count
//                                   returns to zero with every read in that span
//                                   OKAY
//
// PORT names the manager. Verilator counts a cover point once per parameter
// set, so every instance carries a distinct PORT to keep one coverage entry
// per port.
//
// A transaction accepted while MAX_DEPTH of its direction are outstanding is
// not tracked. A read refers to its write by the write's acceptance sequence
// number; the reference lapses once 2 * MAX_DEPTH later writes are accepted.
//
// CONVENTION (smc_axi_chan_fcov.sv): every cover-property body is a single
// continuous-assign wire; no declaration initializers on always_ff-driven
// variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_axi_order_fcov #(
  parameter string       PORT      = "",
  parameter int unsigned ID_WIDTH  = 6,
  parameter int unsigned MAX_DEPTH = 16
) (
  input wire clk_i,
  input wire rst_ni,

  input wire awvalid_i,
  input wire awready_i,
  input wire [ID_WIDTH-1:0] awid_i,

  input wire wvalid_i,
  input wire wready_i,
  input wire wlast_i,

  input wire bvalid_i,
  input wire bready_i,
  input wire [ID_WIDTH-1:0] bid_i,
  input wire [1:0] bresp_i,

  input wire arvalid_i,
  input wire arready_i,
  input wire [ID_WIDTH-1:0] arid_i,

  input wire rvalid_i,
  input wire rready_i,
  input wire [ID_WIDTH-1:0] rid_i,
  input wire [1:0] rresp_i,
  input wire rlast_i
);

  localparam int unsigned DepthW = $clog2(MAX_DEPTH + 1);
  localparam int unsigned IdxW = $clog2(MAX_DEPTH);
  localparam int unsigned TagW = $clog2(MAX_DEPTH) + 1;
  localparam int unsigned NumTags = 1 << TagW;
  localparam int unsigned NumIds = 1 << ID_WIDTH;
  localparam logic [DepthW-1:0] DepthMax = DepthW'(MAX_DEPTH);
  localparam logic [1:0] OrdAwFirst = 2'd0;
  localparam logic [1:0] OrdWFirst = 2'd1;
  localparam logic [1:0] OrdSame = 2'd2;
  localparam logic [1:0] RespOkay = 2'b00;

  wire in_reset = (rst_ni !== 1'b1);

  wire aw_hs = (awvalid_i === 1'b1) && (awready_i === 1'b1);
  wire w_hs = (wvalid_i === 1'b1) && (wready_i === 1'b1);
  wire b_hs = (bvalid_i === 1'b1) && (bready_i === 1'b1);
  wire ar_hs = (arvalid_i === 1'b1) && (arready_i === 1'b1);
  wire r_hs = (rvalid_i === 1'b1) && (rready_i === 1'b1);
  wire r_last = (rlast_i === 1'b1);

  // First cycle of a VALID: AWVALID of a new address, WVALID of a burst's
  // first beat. cyc_q stamps them so an AW and its W compare in time.
  logic aw_wait_q;
  logic w_wait_q;
  logic w_mid_q;
  logic [31:0] cyc_q;
  logic [31:0] aw_t_q;
  wire         aw_pres = (awvalid_i === 1'b1) && !aw_wait_q;
  wire         w_pres = (wvalid_i === 1'b1) && !w_wait_q && !w_mid_q;
  wire  [31:0] aw_t = aw_pres ? cyc_q : aw_t_q;

  function automatic logic [1:0] ord_of(input logic [31:0] t_aw, input logic [31:0] t_w);
    if (t_w < t_aw) return OrdWFirst;
    if (t_w == t_aw) return OrdSame;
    return OrdAwFirst;
  endfunction

  function automatic int unsigned ones(input logic [NumIds-1:0] v);
    int unsigned n;
    n = 0;
    for (int i = 0; i < NumIds; i++) n += int'(v[i]);
    return n;
  endfunction

  // Write table.
  logic [DepthW-1:0] wcnt_q, wcnt_d;
  logic [ID_WIDTH-1:0] wid_q [MAX_DEPTH];
  logic [ID_WIDTH-1:0] wid_d [MAX_DEPTH];
  logic [DepthW-1:0] wdep_q [MAX_DEPTH];
  logic [DepthW-1:0] wdep_d [MAX_DEPTH];
  logic [1:0] word_q [MAX_DEPTH];
  logic [1:0] word_d [MAX_DEPTH];
  logic wst_q [MAX_DEPTH];
  logic wst_d [MAX_DEPTH];
  logic [15:0] wseq_q [MAX_DEPTH];
  logic [15:0] wseq_d [MAX_DEPTH];
  logic [15:0] wr_seq_q, wr_seq_d;
  // First-WVALID times of bursts whose AW is not accepted yet.
  logic [DepthW-1:0] wpq_cnt_q, wpq_cnt_d;
  logic [31:0] wpq_q [MAX_DEPTH];
  logic [31:0] wpq_d [MAX_DEPTH];
  // Write outcome per sequence tag, and a completed OKAY read waiting on it.
  logic wfin_q [NumTags];
  logic wfin_d [NumTags];
  logic wok_q [NumTags];
  logic wok_d [NumTags];
  logic rwait_q [NumTags];
  logic rwait_d [NumTags];

  // Read table.
  logic [DepthW-1:0] rcnt_q, rcnt_d;
  logic [ID_WIDTH-1:0] rid_q [MAX_DEPTH];
  logic [ID_WIDTH-1:0] rid_d [MAX_DEPTH];
  logic [DepthW-1:0] rdep_q [MAX_DEPTH];
  logic [DepthW-1:0] rdep_d [MAX_DEPTH];
  logic rbad_q [MAX_DEPTH];
  logic rbad_d [MAX_DEPTH];
  logic rooo_q [MAX_DEPTH];
  logic rooo_d [MAX_DEPTH];
  logic rlnk_q [MAX_DEPTH];
  logic rlnk_d [MAX_DEPTH];
  logic [15:0] rlseq_q[MAX_DEPTH];
  logic [15:0] rlseq_d[MAX_DEPTH];
  logic [NumIds-1:0] rseen_q, rseen_d;
  logic rwin_ok_q, rwin_ok_d;

  // Completion samples.
  logic b_found;
  logic [IdxW-1:0] b_idx;
  logic [TagW-1:0] b_tag;
  logic wr_done_ok;
  logic [DepthW-1:0] wr_done_dep;
  logic [1:0] wr_done_ord;
  logic wr_done_ooo;
  logic wr_side_ardw;
  logic ws_found;
  logic [IdxW-1:0] ws_idx;
  logic nw_st;
  logic [1:0] nw_ord;
  logic unst_found;
  logic [15:0] unst_seq;
  logic r_found;
  logic [IdxW-1:0] r_idx;
  logic rd_done_ok;
  logic [DepthW-1:0] rd_done_dep;
  logic rd_done_ooo;
  logic rd_side_ardw;
  logic rd_eight;
  logic [TagW-1:0] lnk_tag;
  logic lnk_live;

  always_comb begin
    wcnt_d = wcnt_q;
    wr_seq_d = wr_seq_q;
    wpq_cnt_d = wpq_cnt_q;
    rcnt_d = rcnt_q;
    rseen_d = rseen_q;
    rwin_ok_d = rwin_ok_q;
    for (int i = 0; i < MAX_DEPTH; i++) begin
      wid_d[i] = wid_q[i];
      wdep_d[i] = wdep_q[i];
      word_d[i] = word_q[i];
      wst_d[i] = wst_q[i];
      wseq_d[i] = wseq_q[i];
      wpq_d[i] = wpq_q[i];
      rid_d[i] = rid_q[i];
      rdep_d[i] = rdep_q[i];
      rbad_d[i] = rbad_q[i];
      rooo_d[i] = rooo_q[i];
      rlnk_d[i] = rlnk_q[i];
      rlseq_d[i] = rlseq_q[i];
    end
    for (int t = 0; t < NumTags; t++) begin
      wfin_d[t] = wfin_q[t];
      wok_d[t] = wok_q[t];
      rwait_d[t] = rwait_q[t];
    end

    // ---- Writes -----------------------------------------------------------
    b_found = 1'b0;
    b_idx = '0;
    for (int i = MAX_DEPTH - 1; i >= 0; i--) begin
      if (b_hs && (DepthW'(i) < wcnt_q) && (wid_q[i] == bid_i)) begin
        b_found = 1'b1;
        b_idx = IdxW'(i);
      end
    end
    b_tag = wseq_q[b_idx][TagW-1:0];
    wr_done_ok = b_found && (bresp_i == RespOkay) && wst_q[b_idx];
    wr_done_dep = wdep_q[b_idx];
    wr_done_ord = word_q[b_idx];
    wr_done_ooo = (b_idx != '0);
    wr_side_ardw = wr_done_ok && rwait_q[b_tag];
    if (b_found) begin
      wfin_d[b_tag] = 1'b1;
      wok_d[b_tag] = (bresp_i == RespOkay);
      rwait_d[b_tag] = 1'b0;
    end

    // A burst's first WVALID belongs to the oldest accepted AW without one;
    // with none, to an AW accepted this cycle, else it waits for its AW.
    ws_found = 1'b0;
    ws_idx = '0;
    for (int i = MAX_DEPTH - 1; i >= 0; i--) begin
      if ((DepthW'(i) < wcnt_q) && !wst_q[i]) begin
        ws_found = 1'b1;
        ws_idx = IdxW'(i);
      end
    end
    if (w_pres && ws_found) begin
      wst_d[ws_idx] = 1'b1;
      word_d[ws_idx] = OrdAwFirst;
    end
    nw_st = 1'b0;
    nw_ord = OrdAwFirst;
    if (aw_hs) begin
      if (wpq_cnt_q != '0) begin
        nw_st = 1'b1;
        nw_ord = ord_of(aw_t, wpq_q[0]);
        for (int i = 0; i < MAX_DEPTH - 1; i++) wpq_d[i] = wpq_q[i+1];
        wpq_cnt_d = wpq_cnt_q - DepthW'(1);
      end else if (w_pres && !ws_found) begin
        nw_st = 1'b1;
        nw_ord = ord_of(aw_t, cyc_q);
      end
    end
    if (w_pres && !ws_found && !(aw_hs && (wpq_cnt_q == '0)) && (wpq_cnt_d < DepthMax)) begin
      wpq_d[wpq_cnt_d[IdxW-1:0]] = cyc_q;
      wpq_cnt_d = wpq_cnt_d + DepthW'(1);
    end

    if (b_found) begin
      for (int i = 0; i < MAX_DEPTH - 1; i++) begin
        if (i >= int'(b_idx)) begin
          wid_d[i] = wid_d[i+1];
          wdep_d[i] = wdep_d[i+1];
          word_d[i] = word_d[i+1];
          wst_d[i] = wst_d[i+1];
          wseq_d[i] = wseq_d[i+1];
        end
      end
      wcnt_d = wcnt_q - DepthW'(1);
    end
    if (aw_hs) begin
      if (wcnt_d < DepthMax) begin
        wid_d[wcnt_d[IdxW-1:0]] = awid_i;
        wdep_d[wcnt_d[IdxW-1:0]] = wcnt_d + DepthW'(1);
        word_d[wcnt_d[IdxW-1:0]] = nw_ord;
        wst_d[wcnt_d[IdxW-1:0]] = nw_st;
        wseq_d[wcnt_d[IdxW-1:0]] = wr_seq_q;
        wcnt_d = wcnt_d + DepthW'(1);
      end
      wfin_d[wr_seq_q[TagW-1:0]] = 1'b0;
      wok_d[wr_seq_q[TagW-1:0]] = 1'b0;
      rwait_d[wr_seq_q[TagW-1:0]] = 1'b0;
      wr_seq_d = wr_seq_q + 16'd1;
    end

    // The oldest accepted AW still without WVALID once this cycle is applied.
    unst_found = 1'b0;
    unst_seq = '0;
    for (int i = MAX_DEPTH - 1; i >= 0; i--) begin
      if ((DepthW'(i) < wcnt_d) && !wst_d[i]) begin
        unst_found = 1'b1;
        unst_seq = wseq_d[i];
      end
    end

    // ---- Reads ------------------------------------------------------------
    r_found = 1'b0;
    r_idx = '0;
    for (int i = MAX_DEPTH - 1; i >= 0; i--) begin
      if (r_hs && (DepthW'(i) < rcnt_q) && (rid_q[i] == rid_i)) begin
        r_found = 1'b1;
        r_idx = IdxW'(i);
      end
    end
    if (r_found) begin
      if (rresp_i != RespOkay) begin
        rbad_d[r_idx] = 1'b1;
        rwin_ok_d = 1'b0;
      end else if (r_idx != '0) begin
        rooo_d[r_idx] = 1'b1;
      end
    end
    rd_done_ok = r_found && r_last && !rbad_d[r_idx];
    rd_done_dep = rdep_q[r_idx];
    rd_done_ooo = rooo_d[r_idx];
    lnk_tag = rlseq_q[r_idx][TagW-1:0];
    lnk_live = rlnk_q[r_idx] && ((wr_seq_q - rlseq_q[r_idx]) < 16'(NumTags));
    rd_side_ardw = 1'b0;
    if (rd_done_ok && lnk_live) begin
      if (wfin_q[lnk_tag]) rd_side_ardw = wok_q[lnk_tag];
      else if (b_found && (b_tag == lnk_tag)) rd_side_ardw = wr_done_ok;
      else rwait_d[lnk_tag] = 1'b1;
    end
    if (r_found && r_last) begin
      for (int i = 0; i < MAX_DEPTH - 1; i++) begin
        if (i >= int'(r_idx)) begin
          rid_d[i] = rid_d[i+1];
          rdep_d[i] = rdep_d[i+1];
          rbad_d[i] = rbad_d[i+1];
          rooo_d[i] = rooo_d[i+1];
          rlnk_d[i] = rlnk_d[i+1];
          rlseq_d[i] = rlseq_d[i+1];
        end
      end
      rcnt_d = rcnt_q - DepthW'(1);
    end
    rd_eight = r_found && r_last && (rcnt_d == '0) && !ar_hs && rwin_ok_d && (ones(rseen_q) >= 8);
    if (r_found && r_last && (rcnt_d == '0) && !ar_hs) begin
      rseen_d = '0;
      rwin_ok_d = 1'b1;
    end
    if (ar_hs) begin
      if (rcnt_d < DepthMax) begin
        rid_d[rcnt_d[IdxW-1:0]] = arid_i;
        rdep_d[rcnt_d[IdxW-1:0]] = rcnt_d + DepthW'(1);
        rbad_d[rcnt_d[IdxW-1:0]] = 1'b0;
        rooo_d[rcnt_d[IdxW-1:0]] = 1'b0;
        rlnk_d[rcnt_d[IdxW-1:0]] = unst_found;
        rlseq_d[rcnt_d[IdxW-1:0]] = unst_seq;
        rcnt_d = rcnt_d + DepthW'(1);
      end
      rseen_d[arid_i] = 1'b1;
    end
  end

  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      aw_wait_q <= 1'b0;
      w_wait_q <= 1'b0;
      w_mid_q <= 1'b0;
      cyc_q <= '0;
      aw_t_q <= '0;
      wcnt_q <= '0;
      wr_seq_q <= '0;
      wpq_cnt_q <= '0;
      rcnt_q <= '0;
      rseen_q <= '0;
      rwin_ok_q <= 1'b1;
      for (int t = 0; t < NumTags; t++) begin
        wfin_q[t] <= 1'b0;
        wok_q[t] <= 1'b0;
        rwait_q[t] <= 1'b0;
      end
    end else begin
      aw_wait_q <= (awvalid_i === 1'b1) && (awready_i !== 1'b1);
      w_wait_q <= (wvalid_i === 1'b1) && (wready_i !== 1'b1);
      if (w_hs) w_mid_q <= (wlast_i !== 1'b1);
      cyc_q <= cyc_q + 32'd1;
      aw_t_q <= aw_t;
      wcnt_q <= wcnt_d;
      wr_seq_q <= wr_seq_d;
      wpq_cnt_q <= wpq_cnt_d;
      rcnt_q <= rcnt_d;
      rseen_q <= rseen_d;
      rwin_ok_q <= rwin_ok_d;
      wfin_q <= wfin_d;
      wok_q <= wok_d;
      rwait_q <= rwait_d;
    end
    wid_q <= wid_d;
    wdep_q <= wdep_d;
    word_q <= word_d;
    wst_q <= wst_d;
    wseq_q <= wseq_d;
    wpq_q <= wpq_d;
    rid_q <= rid_d;
    rdep_q <= rdep_d;
    rbad_q <= rbad_d;
    rooo_q <= rooo_d;
    rlnk_q <= rlnk_d;
    rlseq_q <= rlseq_d;
  end

  // Depth at address accept, scored on the completion.
  wire rd_depth_one_e = rd_done_ok && (rd_done_dep == DepthW'(1));
  wire rd_depth_few_e = rd_done_ok && (rd_done_dep >= DepthW'(2)) && (rd_done_dep <= DepthW'(4));
  wire rd_depth_many_e = rd_done_ok && (rd_done_dep >= DepthW'(5));
  wire wr_depth_one_e = wr_done_ok && (wr_done_dep == DepthW'(1));
  wire wr_depth_few_e = wr_done_ok && (wr_done_dep >= DepthW'(2)) && (wr_done_dep <= DepthW'(4));
  wire wr_depth_many_e = wr_done_ok && (wr_done_dep >= DepthW'(5));
  `OCAH_FCOV_COVER(c_rd_depth_one, rd_depth_one_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_rd_depth_few, rd_depth_few_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_rd_depth_many, rd_depth_many_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_wr_depth_one, wr_depth_one_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_wr_depth_few, wr_depth_few_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_wr_depth_many, wr_depth_many_e, clk_i, in_reset)

  // AW / W presentation order of a write, scored on its OKAY B.
  wire aw_first_e = wr_done_ok && (wr_done_ord == OrdAwFirst);
  wire w_first_e = wr_done_ok && (wr_done_ord == OrdWFirst);
  wire aw_w_same_cycle_e = wr_done_ok && (wr_done_ord == OrdSame);
  `OCAH_FCOV_COVER(c_aw_first, aw_first_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_w_first, w_first_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_aw_w_same_cycle, aw_w_same_cycle_e, clk_i, in_reset)

  // A read overlapping a write's address-only phase, scored when the second
  // of the pair completes.
  wire ar_during_write_e = rd_side_ardw || wr_side_ardw;
  `OCAH_FCOV_COVER(c_ar_during_write, ar_during_write_e, clk_i, in_reset)

  // Responses outside acceptance order across IDs.
  wire rid_out_of_order_e = rd_done_ok && rd_done_ooo;
  wire bid_out_of_order_e = wr_done_ok && wr_done_ooo;
  wire rd_eight_ids_e = rd_eight;
  `OCAH_FCOV_COVER(c_rid_out_of_order, rid_out_of_order_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_bid_out_of_order, bid_out_of_order_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_rd_eight_ids, rd_eight_ids_e, clk_i, in_reset)

endmodule : smc_axi_order_fcov
