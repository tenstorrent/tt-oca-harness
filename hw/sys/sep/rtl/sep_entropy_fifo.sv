// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Pack native EDN entropy into a fabric FIFO drained by a read-only AXI aperture.
//
// Pull conditioned, FIPS-marked 32-bit words from a native OpenTitan EDN endpoint routed
// out of sep_crypto, pack 32 to 64, and buffer them in a synchronous FIFO. Software (EL2
// host, debug, or an external agent) drains the pool through a 64-bit read-only AXI-Lite
// aperture on sep_local_axi_xbar.
// Datapath: EDN handshake adapter (req_pending_q) into prim_packer_fifo (InW=32, OutW=64,
// ClearOnRead=0), then prim_fifo_sync (Width=64, Depth=FIFO_DEPTH). AXI-Lite decode of the
// 16-bit offset is 0x00 status, 0x08 irq-cause, 0x10 data pop; a pop of an empty pool and
// any other offset return SLVERR with zero data. One read is outstanding at a time.
// The pool FIFO has no hardened pointers, so pool_err_o is always 0.
// The AXI connectivity matrix grants a (master, slave) pair as a single bit and cannot
// mask direction, so AW/W/B arrive whenever any master has read access. Every write
// terminates in place with BRESP=SLVERR and no state change; that SLVERR is the read-only
// enforcement because entropy enters only via the native EDN bus.
// FIFO_DEPTH defaults to 32 packed 64-bit entries. LOW_WATERMARK defaults to 8. STALL_THRESH
// defaults to 4096 cycles (~20 us at 200 MHz) with a request outstanding and no EDN
// acknowledge, and clears on the next ack; the stall detector arms on the first acknowledge
// after reset or entropy_clear_i.

`include "ocah_assert.svh"

`include "prim_assert.sv"

module sep_entropy_fifo
  import edn_pkg::edn_req_t;
  import edn_pkg::edn_rsp_t;
#(
  parameter int unsigned FIFO_DEPTH    = 32,  // Pool depth in packed 64-bit entries (default 32);
                                              // at most 63 to fit the status occupancy field.
  parameter int unsigned LOW_WATERMARK = 8,   // Occupancy below which pool_low_o asserts (default
                                              // 8).
  parameter int unsigned STALL_THRESH  = 4096,  // Outstanding EDN cycles before fill_stall_o
                                                // (default 4096, ~20 us at 200 MHz); clears on next
                                                // ack.
  parameter type axi_req_t   = sep_pkg::sep_32_64_6_12_axi_req_t,  // Full AXI4 slave request type
                                                                   // from sep_local_axi_xbar.
  parameter type axi_resp_t  = sep_pkg::sep_32_64_6_12_axi_resp_t,  // Full AXI4 slave response type to sep_local_axi_xbar.
  parameter type axil_req_t  = sep_pkg::sep_32_64_axil_req_t,  // Internal AXI-Lite request type
                                                               // after conversion.
  parameter type axil_resp_t = sep_pkg::sep_32_64_axil_resp_t  // Internal AXI-Lite response type
                                                               // after conversion.
) (
  input  logic       clk_i,                   // System clock.
  input  logic       rst_ni,                  // Active-low reset.

  input  logic       entropy_clear_i,         // Synchronous clear, active-high, while the internal
                                              // TRNG is in reset. Scrubs only entropy-path state;
                                              // the AXI responder stays alive and reports empty.

  input  logic       test_en_i,               // Test-mode enable for the internal AXI to AXI-Lite
                                              // converter.

  output edn_req_t   edn_req_o,               // Native EDN fill request, raised only while both the
                                              // pool and the packer have room; a hardware pull, not
                                              // an AXI bus.
  input  edn_rsp_t   edn_rsp_i,               // Native EDN fill response; each acknowledge delivers
                                              // one 32-bit word.

  input  axi_req_t   entropy_fifo_axi_req_i,  // Full AXI4 drain request from sep_local_axi_xbar;
                                              // every write completes with SLVERR and no state
                                              // change.
  output axi_resp_t  entropy_fifo_axi_resp_o,  // Full AXI4 drain response to sep_local_axi_xbar.

  output logic       pool_low_o,              // Occupancy below LOW_WATERMARK, and high during
                                              // entropy_clear_i; routed to the SEP PIC.
  output logic       fill_stall_o,            // EDN not acknowledging for more than STALL_THRESH
                                              // cycles; fault to the SEP PIC.
  output logic       pool_err_o,              // Pool pointer-integrity fault; always 0 because the
                                              // pool FIFO has no hardened pointers.
  output logic [$clog2(FIFO_DEPTH+1)-1:0] fifo_level_o  // Current occupancy in packed 64-bit
                                                        // entries; 0 during entropy_clear_i.
);

  // The status-word occupancy field is a fixed 6-bit slot (status_word[5:0]);
  // FIFO_DEPTH must be representable in it.
  `OCAH_ASSERT_STATIC(FifoDepth_A, FIFO_DEPTH <= 63,
                      "FIFO_DEPTH exceeds the 6-bit status[5:0] field")

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
  logic [$clog2(FIFO_DEPTH+1)-1:0]   pool_depth;
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
    .Depth            (FIFO_DEPTH),
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
                          (pool_depth < LOW_WATERMARK[$clog2(FIFO_DEPTH+1)-1:0]);

  // -------------------------------------------------------------------------
  // fill_stall_o -- active fault when EDN stops acknowledging
  // -------------------------------------------------------------------------
  // The detector arms on the first edn_ack so the pre-bring-up window after
  // reset is not reported as a fault. Once armed, a saturating counter
  // increments while a request is outstanding; it clears on any ack (forward
  // progress) so the flag tracks the live stall state rather than latching.
  // The flag and counter both reset to zero on rst_ni.

  localparam int unsigned StallCntW = $clog2(STALL_THRESH + 1);
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
      if (stall_cnt_q != STALL_THRESH[StallCntW-1:0]) begin
        stall_cnt_q <= stall_cnt_q + 1'b1;  // saturating
      end
      if (stall_cnt_q >= STALL_THRESH[StallCntW-1:0]) begin
        fill_stall_q <= 1'b1;
      end
    end
  end

  assign fill_stall_o = fill_stall_q & ~entropy_clear_i;

  `OCAH_OT_ASSERT(ClearDropsRequest_A, entropy_clear_i |=> !req_pending_q, clk_i, !rst_ni)
  // prim_packer_fifo registers clr_i before depth_o falls.
  `OCAH_OT_ASSERT(ClearScrubsPacker_A, entropy_clear_i |-> ##2 (packer_depth == '0), clk_i, !rst_ni)
  `OCAH_OT_ASSERT(ClearScrubsPool_A, entropy_clear_i |=> (pool_depth == '0), clk_i, !rst_ni)
  `OCAH_OT_ASSERT(ClearResetsStall_A, entropy_clear_i |=> (!edn_armed_q && !fill_stall_q), clk_i,
                  !rst_ni)
  `OCAH_OT_ASSERT(NoEntropyAcceptedDuringClear_A, entropy_clear_i |-> !edn_word_valid, clk_i,
                  !rst_ni)

  // -------------------------------------------------------------------------
  // AXI-Lite read channel (single outstanding, non-blocking pop)
  // -------------------------------------------------------------------------
  // Decode the aperture offset (region is 64 KiB) against the register offsets
  // taken from the generated sep_entropy_pool address map, so the three
  // registers are not mirrored across the aperture:
  //   STATUS    -> status word    (non-destructive)
  //   IRQ_CAUSE -> irq-cause word (non-destructive)
  //   DATA      -> pool data pop  (pulses pool_rready when data present;
  //                                SLVERR when the pool is empty)
  //   else      -> RRESP=SLVERR, RDATA=0
  localparam logic [15:0] StatusOffset =
      16'(sep_top_addrmap_pkg::SEP_TOP_ENTROPY_POOL_STATUS_BASE_ADDR
          - sep_top_addrmap_pkg::SEP_TOP_ENTROPY_POOL_BASE_ADDR);
  localparam logic [15:0] IrqCauseOffset =
      16'(sep_top_addrmap_pkg::SEP_TOP_ENTROPY_POOL_IRQ_CAUSE_BASE_ADDR
          - sep_top_addrmap_pkg::SEP_TOP_ENTROPY_POOL_BASE_ADDR);
  localparam logic [15:0] DataOffset =
      16'(sep_top_addrmap_pkg::SEP_TOP_ENTROPY_POOL_DATA_BASE_ADDR
          - sep_top_addrmap_pkg::SEP_TOP_ENTROPY_POOL_BASE_ADDR);

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
      StatusOffset: rd_data_next = status_word;
      IrqCauseOffset: rd_data_next = {61'b0, pool_err_o, fill_stall_o, pool_low_o};
      DataOffset: begin
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
        rd_entropy_q <= (rd_offset == DataOffset);
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
