// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file sep_entropy_fifo.sv
 * @brief Fabric-level entropy pool for the SEP.
 *
 * @details Conditioned, FIPS-marked 32-bit words are pulled from a native
 *          OpenTitan EDN endpoint (routed out of sep_crypto), packed 32->64, and
 *          buffered in a synchronous FIFO. Software (EL2 host, debug, or an
 *          external agent) drains the pool through a 64-bit read-only AXI-Lite
 *          aperture on sep_local_axi_xbar.
 *
 *          Datapath:
 *
 *            native EDN edn_req_o/edn_rsp_i
 *                 | EDN handshake adapter (req_pending_q)
 *                 v
 *            u_packer  prim_packer_fifo (InW=32, OutW=64, ClearOnRead=0)
 *                 | 64-bit stream
 *                 v
 *            u_pool    prim_fifo_sync   (Width=64, Depth=FifoDepth)
 *                 | 64-bit read words
 *                 v
 *            AXI-Lite read decode: 0x00 status, 0x08 irq-cause, 0x10 data pop
 *
 *          Read-only enforcement: the AXI connectivity matrix grants a
 *          (master, slave) pair as a single bit and builds all five channels or
 *          none -- it cannot mask direction. So the AW/W/B write channels
 *          physically arrive here whenever any master has read access. This
 *          module terminates every write in-place with BRESP=SLVERR and no state
 *          change. That SLVERR is THE read-only enforcement, not a redundant
 *          nicety: entropy enters exclusively via the native EDN bus, so every
 *          write is by definition an error.
 *
 * @param FifoDepth    Pool depth in packed 64-bit entries (default: 32).
 * @param LowWatermark pool_low_o asserts while occupancy is below this many
 *                     entries (default: 8).
 * @param StallThresh  fill_stall_o asserts after this many cycles with a request
 *                     outstanding and no EDN acknowledge, and clears on the
 *                     next ack (default: 4096, ~20 us at 200 MHz).
 * @param axi_req_t    Full AXI4 slave request type from sep_local_axi_xbar.
 * @param axi_resp_t   Full AXI4 slave response type to sep_local_axi_xbar.
 * @param axil_req_t   Internal AXI-Lite request type after conversion.
 * @param axil_resp_t  Internal AXI-Lite response type after conversion.
 */

`include "prim_assert.sv"

module sep_entropy_fifo
  import edn_pkg::*;
#(
  // Pool depth in packed 64-bit entries.
  parameter int unsigned FifoDepth    = 32,
  // pool_low_o asserts while occupancy is below this many entries.
  parameter int unsigned LowWatermark = 8,
  // fill_stall_o asserts after this many cycles with a request outstanding
  // and no EDN acknowledge; clears on the next ack (~20 us at 200 MHz).
  parameter int unsigned StallThresh  = 4096,
  // Full AXI4 slave bus from sep_local_axi_xbar and the AXI-Lite bus it is
  // internally converted to. Defaults match the SEP local xbar target ports.
  parameter type axi_req_t   = sep_pkg::sep_32_64_6_12_axi_req_t,
  parameter type axi_resp_t  = sep_pkg::sep_32_64_6_12_axi_resp_t,
  parameter type axil_req_t  = sep_pkg::sep_32_64_axil_req_t,
  parameter type axil_resp_t = sep_pkg::sep_32_64_axil_resp_t
) (
  input  logic       clk_i,
  input  logic       rst_ni,

  // Synchronous clear from the internal TRNG reset domain. This scrubs only
  // entropy-path state; the AXI responder remains alive and reports empty.
  input  logic       entropy_clear_i,

  // Test-mode enable for the internal AXI->AXI-Lite converter.
  input  logic       test_en_i,

  // Native EDN fill port (HW pull -- filled autonomously from the DRBG native
  // endpoint routed out of sep_crypto). Not an AXI bus.
  output edn_req_t   edn_req_o,
  input  edn_rsp_t   edn_rsp_i,

  // Full AXI4 read-only drain port from sep_local_axi_xbar.
  input  axi_req_t   entropy_fifo_axi_req_i,
  output axi_resp_t  entropy_fifo_axi_resp_o,

  // Status / interrupt outputs (routed to the SEP PIC in sep.sv).
  output logic       pool_low_o,      // occupancy below LowWatermark (informational)
  output logic       fill_stall_o,    // EDN not acknowledging for > StallThresh (fault)
  // Pool pointer-integrity fault.
  output logic       pool_err_o,
  output logic [$clog2(FifoDepth+1)-1:0] fifo_level_o  // current occupancy in packed 64b entries
);

  // The status-word occupancy field is a fixed 6-bit slot (status_word[5:0]);
  // FifoDepth must be representable in it.
  initial begin
    assert (FifoDepth <= 63)
    else
      $fatal(1, "sep_entropy_fifo: FifoDepth=%0d exceeds the 6-bit status[5:0] field", FifoDepth);
  end

  // -------------------------------------------------------------------------
  // AXI4 -> AXI-Lite (64-bit) conversion
  // -------------------------------------------------------------------------
  // Single-stage conversion: the local xbar bus is already 64-bit data, which
  // matches the AXI-Lite drain width. Mirrors the DRBG CSR conversion pattern
  // in sep_crypto.sv (u_csrng_axi_to_axi_lite).

  axil_req_t  s_axil_req;
  axil_resp_t s_axil_resp;

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (4),
    .AxiMaxReadTxns  (4),
    .full_req_t      (axi_req_t),
    .full_resp_t     (axi_resp_t),
    .lite_req_t      (axil_req_t),
    .lite_resp_t     (axil_resp_t)
  ) u_axi_to_axi_lite (
    .clk_i,
    .rst_ni,
    .test_i      (test_en_i),
    .slv_req_i   (entropy_fifo_axi_req_i),
    .slv_resp_o  (entropy_fifo_axi_resp_o),
    .mst_req_o   (s_axil_req),
    .mst_resp_i  (s_axil_resp)
  );

  // -------------------------------------------------------------------------
  // Internal datapath signals
  // -------------------------------------------------------------------------

  // EDN handshake adapter
  logic        req_pending_q;
  logic        edn_word_valid;
  logic [31:0] edn_word_data;

  // 32 -> 64 packer
  logic        packer_wready;
  logic        packer_rvalid;
  logic [63:0] packer_rdata;
  logic [1:0]  packer_depth;

  // Pool FIFO
  logic                              pool_wready;
  logic                              pool_rvalid;
  logic                              pool_rready;
  logic [63:0]                       pool_rdata;
  logic                              pool_full;
  logic [$clog2(FifoDepth+1)-1:0]    pool_depth;
  logic                              pool_err;

  // -------------------------------------------------------------------------
  // EDN handshake adapter
  // -------------------------------------------------------------------------
  // The EDN interface is a request/acknowledge protocol, not valid/ready. A
  // single registered bit tracks a request in flight. The request is only
  // raised when the pool has room AND the packer can accept, so no acked word
  // is ever dropped.

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      req_pending_q <= 1'b0;
    end else if (entropy_clear_i) begin
      req_pending_q <= 1'b0;
    end else begin
      if (edn_rsp_i.edn_ack) begin
        req_pending_q <= 1'b0;  // ack received -- request complete
      end else if (!pool_full && packer_wready) begin
        req_pending_q <= 1'b1;  // space available -- raise request
      end
    end
  end

  assign edn_req_o.edn_req = req_pending_q;
  assign edn_word_valid    = edn_rsp_i.edn_ack & req_pending_q & ~entropy_clear_i;
  assign edn_word_data     = edn_rsp_i.edn_bus;

  // -------------------------------------------------------------------------
  // 32 -> 64 packer
  // -------------------------------------------------------------------------
  // Accumulates two 32b EDN words into one 64b pool entry. wready_o going low
  // (packer full) stalls the EDN adapter until the pool drains the packed word.

  prim_packer_fifo #(
    .InW         (32),
    .OutW        (64),
    .ClearOnRead (1'b0)
  ) u_packer (
    .clk_i,
    .rst_ni,
    .clr_i    (entropy_clear_i),
    .wvalid_i (edn_word_valid),
    .wdata_i  (edn_word_data),
    .wready_o (packer_wready),
    .rvalid_o (packer_rvalid),
    .rdata_o  (packer_rdata),
    .rready_i (pool_wready),
    .depth_o  (packer_depth)
  );

  // -------------------------------------------------------------------------
  // Pool FIFO (64-bit, synchronous)
  // -------------------------------------------------------------------------

  prim_fifo_sync #(
    .Width            (64),
    .Depth            (FifoDepth),
    .Pass             (1'b0),
    .OutputZeroIfEmpty(1'b1),
    .NeverClears      (1'b0),
    .Secure           (1'b0)
  ) u_pool (
    .clk_i,
    .rst_ni,
    .clr_i    (entropy_clear_i),
    .wvalid_i (packer_rvalid),
    .wready_o (pool_wready),
    .wdata_i  (packer_rdata),
    .rvalid_o (pool_rvalid),
    .rready_i (pool_rready),
    .rdata_o  (pool_rdata),
    .full_o   (pool_full),
    .depth_o  (pool_depth),
    .err_o    (pool_err)
  );

  assign pool_err_o   = pool_err;
  assign fifo_level_o = entropy_clear_i ? '0 : pool_depth;
  assign pool_low_o   = entropy_clear_i ||
                          (pool_depth < LowWatermark[$clog2(FifoDepth+1)-1:0]);

  // -------------------------------------------------------------------------
  // fill_stall_o -- active fault when EDN stops acknowledging
  // -------------------------------------------------------------------------
  // The detector arms on the first edn_ack so the pre-bring-up window after
  // reset is not reported as a fault. Once armed, a saturating counter
  // increments while a request is outstanding; it clears on any ack (forward
  // progress) so the flag tracks the live stall state rather than latching.
  // The flag and counter both reset to zero on rst_ni.

  localparam int unsigned StallCntW = $clog2(StallThresh + 1);
  logic [StallCntW-1:0] stall_cnt_q;
  logic                 fill_stall_q;
  logic                 edn_armed_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) edn_armed_q <= 1'b0;
    else if (entropy_clear_i) edn_armed_q <= 1'b0;
    else if (edn_rsp_i.edn_ack) edn_armed_q <= 1'b1;
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      stall_cnt_q  <= '0;
      fill_stall_q <= 1'b0;
    end else if (entropy_clear_i) begin
      stall_cnt_q  <= '0;
      fill_stall_q <= 1'b0;
    end else if (edn_rsp_i.edn_ack || !req_pending_q || !edn_armed_q) begin
      stall_cnt_q  <= '0;
      fill_stall_q <= 1'b0;                        // forward progress clears the fault
    end else begin
      if (stall_cnt_q != StallThresh[StallCntW-1:0]) begin
        stall_cnt_q <= stall_cnt_q + 1'b1;  // saturating
      end
      if (stall_cnt_q >= StallThresh[StallCntW-1:0]) begin
        fill_stall_q <= 1'b1;
      end
    end
  end

  assign fill_stall_o = fill_stall_q & ~entropy_clear_i;

  `OCAH_OT_ASSERT(ClearDropsRequest_A, entropy_clear_i |=> !req_pending_q, clk_i, !rst_ni)
  `OCAH_OT_ASSERT(ClearScrubsPacker_A, entropy_clear_i |=> (packer_depth == '0), clk_i, !rst_ni)
  `OCAH_OT_ASSERT(ClearScrubsPool_A, entropy_clear_i |=> (pool_depth == '0), clk_i, !rst_ni)
  `OCAH_OT_ASSERT(ClearResetsStall_A, entropy_clear_i |=> (!edn_armed_q && !fill_stall_q), clk_i,
                  !rst_ni)
  `OCAH_OT_ASSERT(NoEntropyAcceptedDuringClear_A, entropy_clear_i |-> !edn_word_valid, clk_i,
                  !rst_ni)

  // -------------------------------------------------------------------------
  // AXI-Lite read channel (single outstanding, non-blocking pop)
  // -------------------------------------------------------------------------
  // Decode the full 16-bit aperture offset (region is 64 KiB) so the three
  // registers are not mirrored across the aperture:
  //   0x0000 -> status word          (non-destructive)
  //   0x0008 -> irq-cause word        (non-destructive)
  //   0x0010 -> pool data pop         (pulses pool_rready when data present;
  //                                    SLVERR when the pool is empty)
  //   else   -> RRESP=SLVERR, RDATA=0

  logic        rd_pending_q;
  logic [63:0] rd_data_q;
  axi_pkg::resp_t rd_resp_q;

  logic        rd_accept;
  logic [63:0] rd_data_next;
  axi_pkg::resp_t rd_resp_next;
  logic [15:0] rd_offset;
  logic        rd_pop;
  logic        rd_entropy_q;

  logic [63:0] status_word;

  // Status word: {..., pool_err, fill_stall, pool_low, fifo_level[5:0]}.
  always_comb begin
    status_word        = 64'b0;
    status_word[5:0]   = 6'(fifo_level_o);
    status_word[6]     = pool_low_o;
    status_word[7]     = fill_stall_o;
    status_word[8]     = pool_err;
  end

  assign rd_accept = s_axil_req.ar_valid & s_axil_resp.ar_ready;
  assign rd_offset = s_axil_req.ar.addr[15:0];

  always_comb begin
    rd_data_next = 64'b0;
    rd_resp_next = axi_pkg::RESP_OKAY;
    rd_pop       = 1'b0;
    unique case (rd_offset)
      16'h0000: rd_data_next = status_word;
      16'h0008: rd_data_next = {61'b0, pool_err_o, fill_stall_o, pool_low_o};
      16'h0010: begin
        rd_data_next = entropy_clear_i ? 64'b0 : pool_rdata;
        rd_pop       = pool_rvalid & ~entropy_clear_i;
        // Distinguish "no entropy available" from a popped word: an
        // empty pool returns SLVERR instead of OKAY with RDATA=0.
        rd_resp_next = pool_rvalid && !entropy_clear_i ? axi_pkg::RESP_OKAY
                                                               : axi_pkg::RESP_SLVERR;
      end
      default: begin
        rd_data_next = 64'b0;
        rd_resp_next = axi_pkg::RESP_SLVERR;
      end
    endcase
  end

  // Pop the pool exactly once, on the cycle the read address is accepted.
  assign pool_rready = rd_accept & rd_pop;

  // Accept a new read only when not already holding a response (single depth).
  assign s_axil_resp.ar_ready = ~rd_pending_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      rd_pending_q <= 1'b0;
      rd_data_q    <= 64'b0;
      rd_resp_q    <= axi_pkg::RESP_OKAY;
      rd_entropy_q <= 1'b0;
    end else begin
      // Keep the AXI response state alive across a TRNG reset, but scrub
      // any staged pool word before it can be consumed.
      if (entropy_clear_i && rd_entropy_q) begin
        rd_data_q <= 64'b0;
        rd_resp_q <= axi_pkg::RESP_SLVERR;
      end
      if (rd_accept) begin
        rd_pending_q <= 1'b1;
        rd_data_q    <= rd_data_next;
        rd_resp_q    <= rd_resp_next;
        rd_entropy_q <= (rd_offset == 16'h0010);
      end else if (rd_pending_q && s_axil_req.r_ready) begin
        rd_pending_q <= 1'b0;
        rd_entropy_q <= 1'b0;
      end
    end
  end

  assign s_axil_resp.r_valid = rd_pending_q;
  assign s_axil_resp.r.data  = entropy_clear_i && rd_entropy_q ? 64'b0
                                                                 : rd_data_q;
  assign s_axil_resp.r.resp  = entropy_clear_i && rd_entropy_q ? axi_pkg::RESP_SLVERR
                                                                 : rd_resp_q;

  `OCAH_OT_ASSERT(
      ClearScrubsPendingRead_A,
      entropy_clear_i && rd_pending_q && rd_entropy_q |-> (s_axil_resp.r.data == '0 && s_axil_resp.r.resp == axi_pkg::RESP_SLVERR),
      clk_i, !rst_ni)

  // -------------------------------------------------------------------------
  // AXI-Lite write channel -- reject every write with SLVERR (no state change)
  // -------------------------------------------------------------------------
  // AW and W may arrive in any order; accept each once, then emit a single
  // SLVERR B response. There is no functional writer: the pool is filled only
  // over the native EDN bus.

  logic aw_recv_q;
  logic w_recv_q;
  logic b_valid_q;

  assign s_axil_resp.aw_ready = ~b_valid_q & ~aw_recv_q;
  assign s_axil_resp.w_ready  = ~b_valid_q & ~w_recv_q;

  logic aw_hs;
  logic w_hs;
  assign aw_hs = s_axil_req.aw_valid & s_axil_resp.aw_ready;
  assign w_hs  = s_axil_req.w_valid  & s_axil_resp.w_ready;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      aw_recv_q <= 1'b0;
      w_recv_q  <= 1'b0;
      b_valid_q <= 1'b0;
    end else begin
      if (aw_hs) aw_recv_q <= 1'b1;
      if (w_hs) w_recv_q <= 1'b1;

      if (!b_valid_q && (aw_recv_q || aw_hs) && (w_recv_q || w_hs)) begin
        b_valid_q <= 1'b1;         // both channels seen -> raise B
        aw_recv_q <= 1'b0;
        w_recv_q  <= 1'b0;
      end else if (b_valid_q && s_axil_req.b_ready) begin
        b_valid_q <= 1'b0;  // B consumed
      end
    end
  end

  assign s_axil_resp.b_valid = b_valid_q;
  assign s_axil_resp.b.resp  = axi_pkg::RESP_SLVERR;

endmodule
