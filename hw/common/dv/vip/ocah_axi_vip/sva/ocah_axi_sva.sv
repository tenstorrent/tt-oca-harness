// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Clean-room AXI4 / AXI4-Lite protocol-rule checker (practical subset).
//
// Rule provenance: every rule below is implemented from the public AMBA AXI4
// specification (ARM IHI 0022) rule DESCRIPTIONS. No third-party protocol
// checker source (including ARM's Axi4PC) was consulted or copied; all rule
// names are OCAH-original. Reviewers: verify additions cite an IHI 0022
// section, never another checker implementation.
//
// Shape: a module with explicit flat ports so it can be instantiated at TB
// scope next to flattened DUT nets (the DTP integration) or bound into a
// hierarchy (`bind <module> ocah_axi_sva #(...) u_sva (...)`).
// Set IS_LITE=1 for AXI4-Lite: burst/ID/exclusive rules are excluded and the
// Lite response-legality rules are included. `en_i` is a runtime suppress
// knob (tie to 1'b1, or drive from a TB interface bit for suppression
// windows); every concurrent rule is qualified by it.
//
// Each concurrent rule belongs to the side that drives its signals: the
// master drives the AW, W and AR channels and the B and R readies, the slave
// drives the B and R channels and the AW, W and AR readies.
// ASSUME_MASTER_RULES and ASSUME_SLAVE_RULES emit that side's concurrent
// rules as assumptions, so a formal backend that binds one instance asserts
// the design's side and assumes the environment's; both default to
// assertions, which is the simulation shape. Each such rule sits in a
// generate block named gen_<rule> (`OCAH_SVA_RULE, `OCAH_RULE). The
// immediate checks of the SIMULATION-only tracking blocks stay assertions: no
// formal model elaborates them, and a simulator treats both kinds alike.
//
// Rules (OCAH_AXI_* assert, OCAH_AXI_C_* cover):
//   Reset      : <CH>_VALID_RESET_LOW (VALID low while aresetn is low)
//   Handshake  : <CH>_PAYLOAD_STABLE, <CH>_VALID_HELD (IHI 0022 A3.2.1/A3.2.2)
//   X-hygiene  : <CH>_VALID_KNOWN, <CH>_READY_KNOWN, <CH>_PAYLOAD_KNOWN
//   AW/AR      : BURST_LEGAL (A3.4.1 reserved encoding), SIZE_LEGAL (A3.4.1),
//                LEN_FIXED_MAX16 / LEN_WRAP_LEGAL (A3.4.1 burst length),
//                WRAP_ALIGNED (A3.4.1 wrapping bursts), 4KB_BOUNDARY (A3.4.1)
//   W          : LAST_POSITION (A3.4.1 burst length), STRB_IN_LANES (A3.4.3)
//   B/R        : NOT_BEFORE_AW / NOT_BEFORE_AR (A3.3 dependencies),
//                ID_OUTSTANDING (A5.2 transaction ID ordering),
//                RESP_EXOKAY_EXCL (A7.2 exclusive access responses),
//                AXIL_{B,R}_RESP_LEGAL (B1.1.1: no EXOKAY on AXI4-Lite)
//
// Two simulation trees. The two-state rules and the tracking state use
// `OCAH_SVA_RULE / `OCAH_SVA_ASSERT_I (ocah_sva_macros.svh): live on every
// SIMULATION compile, evaluated by Verilator under --assert, and on every
// FORMAL elaboration of a licensed backend. The X-hygiene rules and the
// covers use `OCAH_RULE (ocah_sva_macros.svh) / `OCAH_COVER
// (ocah_assert.svh): live only where OCAH_INC_ASSERT is defined, i.e. on a
// four-state simulator or a licensed backend. Not synthesizable: the tracking
// state uses queues and associative arrays, so it stays under SIMULATION. The
// open-source formal frontend reads none of the concurrent operators here;
// ocah_axi_fv.sv beside this file carries the boolean-subset rules for that
// path.

`include "ocah_assert.svh"
`include "ocah_sva_macros.svh"

module ocah_axi_sva #(
  parameter bit          IS_LITE             = 1'b0,
  parameter int unsigned ADDR_WIDTH          = 32,
  parameter int unsigned DATA_WIDTH          = 32,
  parameter int unsigned ID_WIDTH            = 4,
  parameter int unsigned MAX_OUTSTANDING     = 8,
  parameter bit          ASSUME_MASTER_RULES = 1'b0,
  parameter bit          ASSUME_SLAVE_RULES  = 1'b0
) (
  input wire logic                    aclk,
  input wire logic                    aresetn,
  input wire logic                    en_i,

  // Write address channel.
  input wire logic [ID_WIDTH-1:0]     awid,
  input wire logic [ADDR_WIDTH-1:0]   awaddr,
  input wire logic [7:0]              awlen,
  input wire logic [2:0]              awsize,
  input wire logic [1:0]              awburst,
  input wire logic                    awlock,
  input wire logic [2:0]              awprot,
  input wire logic                    awvalid,
  input wire logic                    awready,

  // Write data channel.
  input wire logic [DATA_WIDTH-1:0]   wdata,
  input wire logic [DATA_WIDTH/8-1:0] wstrb,
  input wire logic                    wlast,
  input wire logic                    wvalid,
  input wire logic                    wready,

  // Write response channel.
  input wire logic [ID_WIDTH-1:0]     bid,
  input wire logic [1:0]              bresp,
  input wire logic                    bvalid,
  input wire logic                    bready,

  // Read address channel.
  input wire logic [ID_WIDTH-1:0]     arid,
  input wire logic [ADDR_WIDTH-1:0]   araddr,
  input wire logic [7:0]              arlen,
  input wire logic [2:0]              arsize,
  input wire logic [1:0]              arburst,
  input wire logic                    arlock,
  input wire logic [2:0]              arprot,
  input wire logic                    arvalid,
  input wire logic                    arready,

  // Read data channel.
  input wire logic [ID_WIDTH-1:0]     rid,
  input wire logic [DATA_WIDTH-1:0]   rdata,
  input wire logic [1:0]              rresp,
  input wire logic                    rlast,
  input wire logic                    rvalid,
  input wire logic                    rready
);

  localparam int unsigned StrbWidth = DATA_WIDTH / 8;

  localparam logic [1:0] BurstFixed = 2'b00;
  localparam logic [1:0] BurstIncr = 2'b01;
  localparam logic [1:0] BurstWrap = 2'b10;
  localparam logic [1:0] RespExokay = 2'b01;

  // ------------------------------------------------------------------
  // Reset behavior: VALID must be low while reset is asserted (A3.1.2).
  // Not reset-disabled (the rule checks reset itself); qualified on a
  // resolved-low aresetn so an X reset at time zero cannot fire it.
  // ------------------------------------------------------------------
  `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_VALID_RESET_LOW,
                 (en_i && (aresetn === 1'b0)) |-> !awvalid, aclk, 1'b0)
  `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_W_VALID_RESET_LOW,
                 (en_i && (aresetn === 1'b0)) |-> !wvalid, aclk, 1'b0)
  `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_B_VALID_RESET_LOW,
                 (en_i && (aresetn === 1'b0)) |-> !bvalid, aclk, 1'b0)
  `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_VALID_RESET_LOW,
                 (en_i && (aresetn === 1'b0)) |-> !arvalid, aclk, 1'b0)
  `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_R_VALID_RESET_LOW,
                 (en_i && (aresetn === 1'b0)) |-> !rvalid, aclk, 1'b0)

  // ------------------------------------------------------------------
  // Handshake stability and hold (A3.2.1): once VALID is asserted the
  // payload must remain stable and VALID must stay high until READY.
  // ------------------------------------------------------------------
  `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_VALID_HELD,
                 (en_i && awvalid && !awready) |=> awvalid, aclk, !aresetn)
  `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_PAYLOAD_STABLE,
                 (en_i && awvalid && !awready) |=> $stable({awid, awaddr, awlen, awsize, awburst,
                                                            awlock, awprot}), aclk, !aresetn)
  `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_W_VALID_HELD,
                 (en_i && wvalid && !wready) |=> wvalid, aclk, !aresetn)
  `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_W_PAYLOAD_STABLE,
                 (en_i && wvalid && !wready) |=> $stable({wdata, wstrb, wlast}), aclk, !aresetn)
  `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_B_VALID_HELD, (en_i && bvalid && !bready) |=> bvalid,
                 aclk, !aresetn)
  `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_B_PAYLOAD_STABLE,
                 (en_i && bvalid && !bready) |=> $stable({bid, bresp}), aclk, !aresetn)
  `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_VALID_HELD,
                 (en_i && arvalid && !arready) |=> arvalid, aclk, !aresetn)
  `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_PAYLOAD_STABLE,
                 (en_i && arvalid && !arready) |=> $stable({arid, araddr, arlen, arsize, arburst,
                                                            arlock, arprot}), aclk, !aresetn)
  `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_R_VALID_HELD, (en_i && rvalid && !rready) |=> rvalid,
                 aclk, !aresetn)
  `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_R_PAYLOAD_STABLE,
                 (en_i && rvalid && !rready) |=> $stable({rid, rdata, rresp, rlast}), aclk,
                 !aresetn)

  // ------------------------------------------------------------------
  // X-hygiene (four-state simulators only): control strobes always
  // resolved; payload resolved when its VALID is high.
  // ------------------------------------------------------------------
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_VALID_KNOWN, en_i |-> !$isunknown(awvalid), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_AW_READY_KNOWN, en_i |-> !$isunknown(awready), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_PAYLOAD_KNOWN,
             (en_i && awvalid) |-> !$isunknown
             ({awid, awaddr, awlen, awsize, awburst, awlock, awprot}), aclk, !aresetn)
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_AXI_W_VALID_KNOWN, en_i |-> !$isunknown(wvalid), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_W_READY_KNOWN, en_i |-> !$isunknown(wready), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_AXI_W_PAYLOAD_KNOWN, (en_i && wvalid) |-> !$isunknown
                                                            ({wstrb, wlast}), aclk, !aresetn)
  `OCAH_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_B_VALID_KNOWN, en_i |-> !$isunknown(bvalid), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_AXI_B_READY_KNOWN, en_i |-> !$isunknown(bready), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_B_PAYLOAD_KNOWN, (en_i && bvalid) |-> !$isunknown
                                                           ({bid, bresp}), aclk, !aresetn)
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_VALID_KNOWN, en_i |-> !$isunknown(arvalid), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_AR_READY_KNOWN, en_i |-> !$isunknown(arready), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_PAYLOAD_KNOWN,
             (en_i && arvalid) |-> !$isunknown
             ({arid, araddr, arlen, arsize, arburst, arlock, arprot}), aclk, !aresetn)
  `OCAH_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_R_VALID_KNOWN, en_i |-> !$isunknown(rvalid), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_MASTER_RULES, OCAH_AXI_R_READY_KNOWN, en_i |-> !$isunknown(rready), aclk,
             !aresetn)
  `OCAH_RULE(ASSUME_SLAVE_RULES, OCAH_AXI_R_PAYLOAD_KNOWN, (en_i && rvalid) |-> !$isunknown
                                                           ({rid, rresp, rlast}), aclk, !aresetn)

  // ------------------------------------------------------------------
  // Handshake / backpressure / error-response covers (rule non-vacuity).
  // ------------------------------------------------------------------
  `OCAH_COVER(OCAH_AXI_C_AW_HANDSHAKE, en_i && awvalid && awready, aclk, !aresetn)
  `OCAH_COVER(OCAH_AXI_C_AW_BACKPRESSURE, en_i && awvalid && !awready, aclk, !aresetn)
  `OCAH_COVER(OCAH_AXI_C_W_HANDSHAKE, en_i && wvalid && wready, aclk, !aresetn)
  `OCAH_COVER(OCAH_AXI_C_W_BACKPRESSURE, en_i && wvalid && !wready, aclk, !aresetn)
  `OCAH_COVER(OCAH_AXI_C_W_PARTIAL_STRB, en_i && wvalid && wready && (wstrb != '1), aclk, !aresetn)
  `OCAH_COVER(OCAH_AXI_C_B_HANDSHAKE, en_i && bvalid && bready, aclk, !aresetn)
  `OCAH_COVER(OCAH_AXI_C_B_ERR_RESP, en_i && bvalid && bready && bresp inside {2'b10, 2'b11}, aclk,
              !aresetn)
  `OCAH_COVER(OCAH_AXI_C_AR_HANDSHAKE, en_i && arvalid && arready, aclk, !aresetn)
  `OCAH_COVER(OCAH_AXI_C_R_HANDSHAKE, en_i && rvalid && rready, aclk, !aresetn)
  `OCAH_COVER(OCAH_AXI_C_R_ERR_RESP, en_i && rvalid && rready && rresp inside {2'b10, 2'b11}, aclk,
              !aresetn)

  if (!IS_LITE) begin : gen_axi4_rules

    // --------------------------------------------------------------
    // Address-channel burst legality, checked at the AW/AR handshake.
    // --------------------------------------------------------------
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_BURST_LEGAL,
                   (en_i && awvalid && awready) |-> (awburst != 2'b11), aclk, !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_SIZE_LEGAL,
                   (en_i && awvalid && awready) |-> ((32'd8 << awsize) <= DATA_WIDTH), aclk,
                   !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_LEN_FIXED_MAX16,
                   (en_i && awvalid && awready && (awburst == BurstFixed)) |-> (awlen <= 8'd15),
                   aclk, !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_LEN_WRAP_LEGAL,
                   (en_i && awvalid && awready && (awburst == BurstWrap)) |->
              (awlen inside {8'd1, 8'd3, 8'd7, 8'd15}),
                   aclk, !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_WRAP_ALIGNED,
                   (en_i && awvalid && awready && (awburst == BurstWrap)) |->
              ((awaddr & ((ADDR_WIDTH'(1) << awsize) - 1)) == '0),
                   aclk, !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AW_4KB_BOUNDARY,
                   (en_i && awvalid && awready && (awburst == BurstIncr)) |->
              ((((13'(awaddr[11:0]) >> awsize) << awsize)
                + ((13'(awlen) + 13'd1) << awsize)) <= 13'h1000),
                   aclk, !aresetn)

    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_BURST_LEGAL,
                   (en_i && arvalid && arready) |-> (arburst != 2'b11), aclk, !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_SIZE_LEGAL,
                   (en_i && arvalid && arready) |-> ((32'd8 << arsize) <= DATA_WIDTH), aclk,
                   !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_LEN_FIXED_MAX16,
                   (en_i && arvalid && arready && (arburst == BurstFixed)) |-> (arlen <= 8'd15),
                   aclk, !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_LEN_WRAP_LEGAL,
                   (en_i && arvalid && arready && (arburst == BurstWrap)) |->
              (arlen inside {8'd1, 8'd3, 8'd7, 8'd15}),
                   aclk, !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_WRAP_ALIGNED,
                   (en_i && arvalid && arready && (arburst == BurstWrap)) |->
              ((araddr & ((ADDR_WIDTH'(1) << arsize) - 1)) == '0),
                   aclk, !aresetn)
    `OCAH_SVA_RULE(ASSUME_MASTER_RULES, OCAH_AXI_AR_4KB_BOUNDARY,
                   (en_i && arvalid && arready && (arburst == BurstIncr)) |->
              ((((13'(araddr[11:0]) >> arsize) << arsize)
                + ((13'(arlen) + 13'd1) << arsize)) <= 13'h1000),
                   aclk, !aresetn)

    `OCAH_COVER(OCAH_AXI_C_AW_MULTI_BEAT, en_i && awvalid && awready && (awlen > 0), aclk, !aresetn)
    `OCAH_COVER(OCAH_AXI_C_AR_MULTI_BEAT, en_i && arvalid && arready && (arlen > 0), aclk, !aresetn)

`ifdef SIMULATION
    // --------------------------------------------------------------
    // Stateful burst/ID tracking (simulation-only). Ordering within the
    // procedural block is load-bearing: W is processed before B and AR
    // before R, so a same-cycle completion is visible to the dependent
    // check. All state flushes on reset.
    // --------------------------------------------------------------
    typedef struct {
      logic [ID_WIDTH-1:0]   id;
      logic [ADDR_WIDTH-1:0] addr;
      logic [7:0]            len;
      logic [2:0]            size;
      logic [1:0]            burst;
      logic                  lock;
    } aw_info_t;

    typedef struct {
      logic [ID_WIDTH-1:0] id;
      logic                lock;
    } wr_done_t;

    aw_info_t   aw_q[$];          // accepted AWs awaiting write data
    wr_done_t   wr_done_q[$];     // data-complete writes awaiting B
    int unsigned early_wburst_len_q[$];  // W bursts completed before their AW
    int unsigned w_beat_idx = 0;
    bit          w_burst_checkable = 1'b0;
    // Working variables for the procedural checks below (declared at
    // generate scope; in-block declarations with initializers would be
    // static-initialized once, retaining stale values across cycles).
    int          wr_match_idx;
    bit          rd_id_known;
    int unsigned early_wlen;

    typedef struct {
      logic [7:0] len;
      logic       lock;
    } ar_info_t;

    ar_info_t    rd_q[logic [ID_WIDTH-1:0]][$];  // per-ID accepted ARs
    int unsigned r_beat_idx[logic [ID_WIDTH-1:0]];

    // Active byte lanes for one write beat (IHI 0022 A3.4.3). WRAP lane
    // windows are not modeled; WRAP beats return the all-lanes mask.
    function automatic logic [StrbWidth-1:0] active_lanes(
        input logic [ADDR_WIDTH-1:0] addr, input logic [2:0] size, input logic [1:0] burst,
        input int unsigned beat_idx);
      logic [ADDR_WIDTH-1:0] aligned;
      logic [ADDR_WIDTH-1:0] beat_addr;
      int unsigned           num_bytes;
      int unsigned           lane_lo;
      int unsigned           lane_base;
      logic [StrbWidth-1:0]  mask;
      num_bytes = 1 << size;
      aligned   = (addr >> size) << size;
      if (burst == BurstWrap) return '1;
      if (burst == BurstFixed || beat_idx == 0) beat_addr = addr;
      else beat_addr = aligned + ADDR_WIDTH'(beat_idx * num_bytes);
      lane_lo   = int'(beat_addr % StrbWidth);
      lane_base = int'(((beat_addr >> size) << size) % StrbWidth);
      mask = '0;
      for (int unsigned lane = 0; lane < StrbWidth; lane++) begin
        if (lane >= lane_lo && lane < lane_base + num_bytes) mask[lane] = 1'b1;
      end
      return mask;
    endfunction

    always @(posedge aclk) begin
      if (aresetn !== 1'b1) begin
        aw_q.delete();
        wr_done_q.delete();
        early_wburst_len_q.delete();
        w_beat_idx = 0;
        w_burst_checkable = 1'b0;
        rd_q.delete();
        r_beat_idx.delete();
      end else if (en_i === 1'b1) begin
        // -- Write address acceptance -------------------------------
        if (awvalid === 1'b1 && awready === 1'b1) begin
          if (early_wburst_len_q.size() > 0) begin
            // A W burst completed before this AW (legal: A3.3).
            // Check its length retroactively and move it straight
            // to the response-pending queue with the AW's id/lock.
            early_wlen = early_wburst_len_q.pop_front();
            `OCAH_SVA_ASSERT_I(OCAH_AXI_W_LAST_POSITION_EARLY, (early_wlen == int'(awlen) + 1))
            wr_done_q.push_back('{id: awid, lock: awlock});
          end else begin
            aw_q.push_back('{id: awid, addr: awaddr, len: awlen, size: awsize, burst: awburst,
                           lock: awlock});
          end
        end

        // -- Write data beats --------------------------------------
        if (wvalid === 1'b1 && wready === 1'b1) begin
          if (w_beat_idx == 0) w_burst_checkable = (aw_q.size() > 0);
          if (w_burst_checkable) begin
            `OCAH_SVA_ASSERT_I(OCAH_AXI_W_LAST_POSITION,
                               (wlast === (w_beat_idx == int'(aw_q[0].len))))
            `OCAH_SVA_ASSERT_I(OCAH_AXI_W_STRB_IN_LANES, ((wstrb & ~active_lanes(
                               aw_q[0].addr, aw_q[0].size, aw_q[0].burst, w_beat_idx)) == '0))
          end
          if (wlast === 1'b1) begin
            if (w_burst_checkable) begin
              wr_done_q.push_back('{id: aw_q[0].id, lock: aw_q[0].lock});
              void'(aw_q.pop_front());
            end else begin
              // No AW yet: retro-checked at AW acceptance.
              early_wburst_len_q.push_back(w_beat_idx + 1);
            end
            w_beat_idx = 0;
            w_burst_checkable = 1'b0;
          end else begin
            w_beat_idx++;
          end
        end

        // -- Write response ----------------------------------------
        if (bvalid === 1'b1 && bready === 1'b1) begin
          wr_match_idx = -1;
          `OCAH_SVA_ASSERT_I(OCAH_AXI_B_NOT_BEFORE_AW, (wr_done_q.size() > 0))
          foreach (wr_done_q[i]) begin
            if (wr_match_idx == -1 && wr_done_q[i].id === bid) wr_match_idx = i;
          end
          `OCAH_SVA_ASSERT_I(OCAH_AXI_B_ID_OUTSTANDING, (wr_match_idx != -1))
          if (wr_match_idx != -1) begin
            `OCAH_SVA_ASSERT_I(OCAH_AXI_B_RESP_EXOKAY_EXCL,
                               ((bresp !== RespExokay) || (wr_done_q[wr_match_idx].lock === 1'b1)))
            wr_done_q.delete(wr_match_idx);
          end
        end

        // -- Read address acceptance -------------------------------
        if (arvalid === 1'b1 && arready === 1'b1) begin
          rd_q[arid].push_back('{len: arlen, lock: arlock});
          if (!r_beat_idx.exists(arid)) r_beat_idx[arid] = 0;
        end

        // -- Read data beats ---------------------------------------
        if (rvalid === 1'b1 && rready === 1'b1) begin
          rd_id_known = rd_q.exists(rid) && (rd_q[rid].size() > 0);
          `OCAH_SVA_ASSERT_I(OCAH_AXI_R_ID_OUTSTANDING, rd_id_known)
          `OCAH_SVA_ASSERT_I(OCAH_AXI_R_NOT_BEFORE_AR, rd_id_known)
          if (rd_id_known) begin
            `OCAH_SVA_ASSERT_I(OCAH_AXI_R_LAST_POSITION,
                               (rlast === (r_beat_idx[rid] == int'(rd_q[rid][0].len))))
            `OCAH_SVA_ASSERT_I(OCAH_AXI_R_RESP_EXOKAY_EXCL,
                               ((rresp !== RespExokay) || (rd_q[rid][0].lock === 1'b1)))
            if (rlast === 1'b1) begin
              void'(rd_q[rid].pop_front());
              r_beat_idx[rid] = 0;
            end else begin
              r_beat_idx[rid]++;
            end
          end
        end

        // -- Outstanding-depth sanity (checker capacity, not AXI) --
        `OCAH_SVA_ASSERT_I(OCAH_AXI_AW_OUTSTANDING_DEPTH,
                           (aw_q.size() + wr_done_q.size() <= 2 * MAX_OUTSTANDING))
      end
    end
`endif  // SIMULATION

  end else begin : gen_lite_rules

    // --------------------------------------------------------------
    // AXI4-Lite response legality (IHI 0022 B1.1.1: EXOKAY undefined).
    // --------------------------------------------------------------
    `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_AXIL_B_RESP_LEGAL,
                   (en_i && bvalid && bready) |-> (bresp != RespExokay), aclk, !aresetn)
    `OCAH_SVA_RULE(ASSUME_SLAVE_RULES, OCAH_AXIL_R_RESP_LEGAL,
                   (en_i && rvalid && rready) |-> (rresp != RespExokay), aclk, !aresetn)

`ifdef SIMULATION
    // Response-ordering counters (same same-cycle ordering note as AXI4).
    int unsigned lite_wr_addr_cnt = 0;
    int unsigned lite_wr_data_cnt = 0;
    int unsigned lite_rd_cnt      = 0;

    always @(posedge aclk) begin
      if (aresetn !== 1'b1) begin
        lite_wr_addr_cnt = 0;
        lite_wr_data_cnt = 0;
        lite_rd_cnt      = 0;
      end else if (en_i === 1'b1) begin
        if (awvalid === 1'b1 && awready === 1'b1) lite_wr_addr_cnt++;
        if (wvalid === 1'b1 && wready === 1'b1) lite_wr_data_cnt++;
        if (arvalid === 1'b1 && arready === 1'b1) lite_rd_cnt++;
        if (bvalid === 1'b1 && bready === 1'b1) begin
          `OCAH_SVA_ASSERT_I(OCAH_AXI_B_NOT_BEFORE_AW,
                             (lite_wr_addr_cnt > 0 && lite_wr_data_cnt > 0))
          if (lite_wr_addr_cnt > 0) lite_wr_addr_cnt--;
          if (lite_wr_data_cnt > 0) lite_wr_data_cnt--;
        end
        if (rvalid === 1'b1 && rready === 1'b1) begin
          `OCAH_SVA_ASSERT_I(OCAH_AXI_R_NOT_BEFORE_AR, (lite_rd_cnt > 0))
          if (lite_rd_cnt > 0) lite_rd_cnt--;
        end
      end
    end
`endif  // SIMULATION

  end

endmodule : ocah_axi_sva
