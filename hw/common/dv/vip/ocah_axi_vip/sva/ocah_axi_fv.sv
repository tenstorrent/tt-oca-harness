// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Clean-room AXI4 / AXI4-Lite protocol rules for formal environments, written in the boolean
// subset that the open-source frontend and the licensed backends both elaborate
// (hw/common/dv/docs/formal-property-style.adoc).
//
// Rule provenance: every rule below is implemented from the public AMBA AXI4 specification
// (ARM IHI 0022) rule DESCRIPTIONS. No third-party protocol checker source was consulted or
// copied; all rule names are OCAH-original. Additions cite an IHI 0022 section, never another
// checker implementation.
//
// Shape: the flat port list of ocah_axi_sva without its runtime enable, bound into a design by
// module name (`bind <module> ocah_axi_fv #(...) u_ocah_axi_fv (...)`). Each rule belongs to the
// side that drives its signals: the master drives the AW, W and AR channels and the B and R
// readies; the slave drives the B and R channels and the AW, W and AR readies.
// ASSUME_MASTER_RULES and ASSUME_SLAVE_RULES emit that side's rules as assumptions, so one
// instance asserts the design's side and assumes the environment's; both default to assertions.
// Set IS_LITE=1 for AXI4-Lite: the burst rules are excluded and the response-legality rules are
// included. MAX_OUTSTANDING bounds the request counters behind the response-ordering rules, and
// the capacity rules hold the master to it.
//
// Rules (gen_<rule>.ast_<rule>, or asm_<rule> on an assumed side; cov_* covers):
//   Reset      : axi_<ch>_valid_reset_low (VALID low while aresetn is low, A3.1.2)
//   Handshake  : axi_<ch>_valid_held, axi_<ch>_payload_stable (A3.2.1)
//   AW/AR      : axi_<ch>_burst_legal (A3.4.1 reserved encoding), axi_<ch>_size_legal (A3.4.1),
//                axi_<ch>_len_fixed_max16, axi_<ch>_len_wrap_legal (A3.4.1 burst length),
//                axi_<ch>_wrap_aligned (A3.4.1 wrapping bursts), axi_<ch>_4kb_boundary (A3.4.1),
//                axi_<ch>_within_capacity (MAX_OUTSTANDING)
//   B/R        : axi_b_not_before_aw, axi_r_not_before_ar (A3.3 dependencies),
//                axi_axil_b_resp_legal, axi_axil_r_resp_legal (B1.1.1: no EXOKAY on AXI4-Lite)
//   Covers     : axi_<ch>_handshake
//
// The rules that need per-ID or per-beat history (WLAST and RLAST position, strobe lanes, ID
// matching, exclusive responses) are ocah_axi_sva's: the boolean subset has no queues. The covers
// name the handshakes only; whether a channel ever backpressures is a property of the bound
// design, so a cover on it belongs to the design's property module.
//
// Every $past of an input is guarded with $past(aresetn), and the initial-reset assumption of the
// macro layer pins aresetn low at the first aclk edge, so no rule reads an unconstrained initial
// value. The reset model of the environment releases aresetn; this module does not.

`include "ocah_fv_macros.svh"

module ocah_axi_fv #(
  parameter bit          IS_LITE             = 1'b0,
  parameter int unsigned ADDR_WIDTH          = 32,
  parameter int unsigned DATA_WIDTH          = 32,
  parameter int unsigned ID_WIDTH            = 4,
  parameter int unsigned MAX_OUTSTANDING     = 8,
  parameter bit          ASSUME_MASTER_RULES = 1'b0,
  parameter bit          ASSUME_SLAVE_RULES  = 1'b0
) (
  input logic                    aclk,
  input logic                    aresetn,

  // Write address channel.
  input logic [ID_WIDTH-1:0]     awid,
  input logic [ADDR_WIDTH-1:0]   awaddr,
  input logic [7:0]              awlen,
  input logic [2:0]              awsize,
  input logic [1:0]              awburst,
  input logic                    awlock,
  input logic [2:0]              awprot,
  input logic                    awvalid,
  input logic                    awready,

  // Write data channel.
  input logic [DATA_WIDTH-1:0]   wdata,
  input logic [DATA_WIDTH/8-1:0] wstrb,
  input logic                    wlast,
  input logic                    wvalid,
  input logic                    wready,

  // Write response channel.
  input logic [ID_WIDTH-1:0]     bid,
  input logic [1:0]              bresp,
  input logic                    bvalid,
  input logic                    bready,

  // Read address channel.
  input logic [ID_WIDTH-1:0]     arid,
  input logic [ADDR_WIDTH-1:0]   araddr,
  input logic [7:0]              arlen,
  input logic [2:0]              arsize,
  input logic [1:0]              arburst,
  input logic                    arlock,
  input logic [2:0]              arprot,
  input logic                    arvalid,
  input logic                    arready,

  // Read data channel.
  input logic [ID_WIDTH-1:0]     rid,
  input logic [DATA_WIDTH-1:0]   rdata,
  input logic [1:0]              rresp,
  input logic                    rlast,
  input logic                    rvalid,
  input logic                    rready
);

  localparam int unsigned StrbWidth = DATA_WIDTH / 8;
  localparam int unsigned CntWidth = $clog2(MAX_OUTSTANDING + 2);
  localparam int unsigned AxPayloadWidth = ID_WIDTH + ADDR_WIDTH + 8 + 3 + 2 + 1 + 3;
  localparam int unsigned WPayloadWidth = DATA_WIDTH + StrbWidth + 1;
  localparam int unsigned BPayloadWidth = ID_WIDTH + 2;
  localparam int unsigned RPayloadWidth = ID_WIDTH + DATA_WIDTH + 2 + 1;

  localparam logic [1:0] BurstFixed = 2'b00;
  localparam logic [1:0] BurstIncr = 2'b01;
  localparam logic [1:0] BurstWrap = 2'b10;
  localparam logic [1:0] RespExokay = 2'b01;
  localparam logic [CntWidth-1:0] Capacity = CntWidth'(MAX_OUTSTANDING);

  logic aw_hs, w_hs, wlast_hs, b_hs, ar_hs, r_hs, rlast_hs;
  assign aw_hs    = awvalid && awready;
  assign w_hs     = wvalid && wready;
  assign wlast_hs = w_hs && wlast;
  assign b_hs     = bvalid && bready;
  assign ar_hs    = arvalid && arready;
  assign r_hs     = rvalid && rready;
  assign rlast_hs = r_hs && rlast;

  // One vector per channel, so that a stability rule compares the payload as a whole.
  logic [AxPayloadWidth-1:0] aw_payload, ar_payload;
  logic [WPayloadWidth-1:0]  w_payload;
  logic [BPayloadWidth-1:0]  b_payload;
  logic [RPayloadWidth-1:0]  r_payload;
  assign aw_payload = {awid, awaddr, awlen, awsize, awburst, awlock, awprot};
  assign w_payload  = {wdata, wstrb, wlast};
  assign b_payload  = {bid, bresp};
  assign ar_payload = {arid, araddr, arlen, arsize, arburst, arlock, arprot};
  assign r_payload  = {rid, rdata, rresp, rlast};

  // Requests the slave owes a response for: accepted addresses and completed write bursts,
  // each net of the responses handed back. Write data may precede its address (A3.3.1), so the
  // two write counts move independently.
  logic [CntWidth-1:0] writes_addressed_q, writes_data_done_q, reads_addressed_q;
  always_ff @(posedge aclk or negedge aresetn) begin
    if (!aresetn) begin
      writes_addressed_q <= '0;
      writes_data_done_q <= '0;
      reads_addressed_q  <= '0;
    end else begin
      writes_addressed_q <= writes_addressed_q + CntWidth'(aw_hs) - CntWidth'(b_hs);
      writes_data_done_q <= writes_data_done_q + CntWidth'(wlast_hs) - CntWidth'(b_hs);
      reads_addressed_q  <= reads_addressed_q + CntWidth'(ar_hs) - CntWidth'(rlast_hs);
    end
  end

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(aclk, aresetn)

  // ---- Master: VALID low in reset (A3.1.2) ---------------------------------------------------
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_valid_reset_low,
                `OCAH_FV_IMPLIES(!aresetn, !awvalid), aclk, 1'b1)
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_w_valid_reset_low,
                `OCAH_FV_IMPLIES(!aresetn, !wvalid), aclk, 1'b1)
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_valid_reset_low,
                `OCAH_FV_IMPLIES(!aresetn, !arvalid), aclk, 1'b1)

  // ---- Master: a VALID holds with its payload until the READY (A3.2.1) -------------------------
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_valid_held,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(awvalid && !awready), awvalid),
                aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_payload_stable,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(awvalid && !awready),
                                 aw_payload == $past(aw_payload)),
                aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_w_valid_held,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(wvalid && !wready), wvalid),
                aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_w_payload_stable,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(wvalid && !wready),
                                 w_payload == $past(w_payload)),
                aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_valid_held,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(arvalid && !arready), arvalid),
                aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_payload_stable,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(arvalid && !arready),
                                 ar_payload == $past(ar_payload)),
                aclk, aresetn)

  // ---- Master: the request counters stay within MAX_OUTSTANDING ------------------------------
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_within_capacity,
                `OCAH_FV_IMPLIES(aw_hs, writes_addressed_q < Capacity), aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_w_within_capacity,
                `OCAH_FV_IMPLIES(wlast_hs, writes_data_done_q < Capacity), aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_within_capacity,
                `OCAH_FV_IMPLIES(ar_hs, reads_addressed_q < Capacity), aclk, aresetn)

  // ---- Slave: VALID low in reset (A3.1.2) ----------------------------------------------------
  `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_b_valid_reset_low,
                `OCAH_FV_IMPLIES(!aresetn, !bvalid), aclk, 1'b1)
  `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_r_valid_reset_low,
                `OCAH_FV_IMPLIES(!aresetn, !rvalid), aclk, 1'b1)

  // ---- Slave: a VALID holds with its payload until the READY (A3.2.1) --------------------------
  `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_b_valid_held,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(bvalid && !bready), bvalid),
                aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_b_payload_stable,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(bvalid && !bready),
                                 b_payload == $past(b_payload)),
                aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_r_valid_held,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(rvalid && !rready), rvalid),
                aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_r_payload_stable,
                `OCAH_FV_IMPLIES($past(aresetn) && $past(rvalid && !rready),
                                 r_payload == $past(r_payload)),
                aclk, aresetn)

  // ---- Slave: a response follows its request (A3.3.1), the same cycle at the earliest ---------
  `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_b_not_before_aw,
                `OCAH_FV_IMPLIES(bvalid, (writes_addressed_q != '0 || aw_hs) &&
                                         (writes_data_done_q != '0 || wlast_hs)),
                aclk, aresetn)
  `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_r_not_before_ar,
                `OCAH_FV_IMPLIES(rvalid, reads_addressed_q != '0 || ar_hs), aclk, aresetn)

  `OCAH_FV_COVER(cov_axi_aw_handshake, aw_hs, aclk, aresetn)
  `OCAH_FV_COVER(cov_axi_w_handshake, w_hs, aclk, aresetn)
  `OCAH_FV_COVER(cov_axi_b_handshake, b_hs, aclk, aresetn)
  `OCAH_FV_COVER(cov_axi_ar_handshake, ar_hs, aclk, aresetn)
  `OCAH_FV_COVER(cov_axi_r_handshake, r_hs, aclk, aresetn)

  if (IS_LITE) begin : gen_lite_rules
    // ---- Slave: EXOKAY is undefined on AXI4-Lite (B1.1.1) --------------------------------------
    `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_axil_b_resp_legal,
                  `OCAH_FV_IMPLIES(b_hs, bresp != RespExokay), aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_SLAVE_RULES, axi_axil_r_resp_legal,
                  `OCAH_FV_IMPLIES(r_hs, rresp != RespExokay), aclk, aresetn)
  end else begin : gen_axi4_rules
    // ---- Master: address-channel burst legality at the handshake (A3.4.1) ----------------------
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_burst_legal,
                  `OCAH_FV_IMPLIES(aw_hs, awburst != 2'b11), aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_size_legal,
                  `OCAH_FV_IMPLIES(aw_hs, (32'd8 << awsize) <= DATA_WIDTH), aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_len_fixed_max16,
                  `OCAH_FV_IMPLIES(aw_hs && awburst == BurstFixed, awlen <= 8'd15), aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_len_wrap_legal,
                  `OCAH_FV_IMPLIES(aw_hs && awburst == BurstWrap,
                                   awlen inside {8'd1, 8'd3, 8'd7, 8'd15}),
                  aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_wrap_aligned,
                  `OCAH_FV_IMPLIES(aw_hs && awburst == BurstWrap,
                                   (awaddr & ((ADDR_WIDTH'(1) << awsize) - 1)) == '0),
                  aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_aw_4kb_boundary,
                  `OCAH_FV_IMPLIES(aw_hs && awburst == BurstIncr,
                                   (((13'(awaddr[11:0]) >> awsize) << awsize) +
                                    ((13'(awlen) + 13'd1) << awsize)) <= 13'h1000),
                  aclk, aresetn)

    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_burst_legal,
                  `OCAH_FV_IMPLIES(ar_hs, arburst != 2'b11), aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_size_legal,
                  `OCAH_FV_IMPLIES(ar_hs, (32'd8 << arsize) <= DATA_WIDTH), aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_len_fixed_max16,
                  `OCAH_FV_IMPLIES(ar_hs && arburst == BurstFixed, arlen <= 8'd15), aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_len_wrap_legal,
                  `OCAH_FV_IMPLIES(ar_hs && arburst == BurstWrap,
                                   arlen inside {8'd1, 8'd3, 8'd7, 8'd15}),
                  aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_wrap_aligned,
                  `OCAH_FV_IMPLIES(ar_hs && arburst == BurstWrap,
                                   (araddr & ((ADDR_WIDTH'(1) << arsize) - 1)) == '0),
                  aclk, aresetn)
    `OCAH_FV_RULE(ASSUME_MASTER_RULES, axi_ar_4kb_boundary,
                  `OCAH_FV_IMPLIES(ar_hs && arburst == BurstIncr,
                                   (((13'(araddr[11:0]) >> arsize) << arsize) +
                                    ((13'(arlen) + 13'd1) << arsize)) <= 13'h1000),
                  aclk, aresetn)
  end
  // verilog_format: on

endmodule : ocah_axi_fv
