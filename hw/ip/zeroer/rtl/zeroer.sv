// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Write zeros over a programmed AXI address range from a ctrl port.
//
// zeroer_ctrl_axi_* programs DEST_ADDR and SIZE in bytes, and a write to CTRL_STATUS starts
// the clear unless SIZE is 0; mst_axi_* performs the clears.
// The clears are INCR write bursts of zeros at full data width, with ID 0, at most 256 beats,
// never crossing a 4 KiB boundary, and strobes limited to the range. The master never reads
// and ignores write response codes. An illegal FSM state locks the zeroer busy until reset.
// With cg_enable_i high, the clear FSM clock runs only while busy and the register clock is
// gated after ctrl-bus inactivity; zeroer_intp_o signals completion.

module zeroer #(
  parameter type zeroer_ctrl_req_t  = logic,                // Ctrl AXI request type.
  parameter type zeroer_ctrl_resp_t = logic,                // Ctrl AXI response type.

  parameter type mst_req_t  = logic,                        // Master AXI request type.
  parameter type mst_resp_t = logic,                        // Master AXI response type.

  parameter int unsigned CTRL_ADDR_WIDTH = 5,               // Ctrl AXI address width.
  parameter int unsigned CTRL_DATA_WIDTH = 64,              // Ctrl AXI data width.
  parameter int unsigned CTRL_ID_WIDTH   = 8,               // Ctrl AXI ID width.
  parameter int unsigned CTRL_USER_WIDTH = 12,              // Ctrl AXI user width.

  parameter int unsigned AXI_ADDR_WIDTH = 56,               // Master AXI address width; DEST_ADDR
                                                            // is truncated to it.
  parameter int unsigned AXI_DATA_WIDTH = 64,               // Master AXI data width.
  parameter int unsigned AXI_USER_WIDTH = 12,               // Master AXI user width.
  parameter int unsigned MST_ID_WIDTH   = 3,                // Master AXI ID width.

  parameter int unsigned CG_HYSTERESIS_W = 6                // Clock-gater hysteresis width.
) (
  input logic clk_i,                                        // System clock; source of both gated
                                                            // clocks.
  input logic rst_ni,                                       // Async reset, active-low.
  input logic test_en_i,                                    // DFT test enable; forces both clock
                                                            // gates open.

  input logic                       cg_enable_i,            // Enable gating of the clear FSM and
                                                            // register clocks.
  input logic [CG_HYSTERESIS_W-1:0] cg_hysteresis_i,        // Idle cycles before gating the
                                                            // register clock.

  output logic zeroer_busy_o,                               // Zeroer has work in flight: a start,
                                                            // an active clear, or writes awaiting a
                                                            // response. Also high in the error
                                                            // state.
  output logic zeroer_intp_o,                               // Completion interrupt: a one-cycle
                                                            // pulse when busy falls, if
                                                            // CTRL_STATUS.INT_EN is set.

  input  zeroer_ctrl_req_t  zeroer_ctrl_axi_req_i,          // Ctrl AXI slave request.
  output zeroer_ctrl_resp_t zeroer_ctrl_axi_resp_o,         // Ctrl AXI slave response.

  output mst_req_t  mst_axi_req_o,                          // Clearing AXI master request.
  input  mst_resp_t mst_axi_resp_i,                         // Clearing AXI master response.

  output logic zeroer_clk_active_o,                         // Register clock is running.
  output logic zeroer_bus_active_o                          // Ctrl bus has a transaction in
                                                            // progress.
);

  `include "ocah_assert.svh"
  `include "axi/typedef.svh"

  // Local type derivations from width parameters
  localparam int unsigned AXI_STRB_WIDTH = AXI_DATA_WIDTH / 8;
  localparam int unsigned AXI_DATA_SIZE = $clog2(AXI_STRB_WIDTH);

  typedef logic [AXI_ADDR_WIDTH-1:0] axi_addr_t;
  typedef logic [AXI_DATA_WIDTH-1:0] axi_data_t;
  typedef logic [AXI_STRB_WIDTH-1:0] axi_strb_t;
  typedef logic [AXI_USER_WIDTH-1:0] axi_user_t;
  typedef logic [MST_ID_WIDTH-1:0] mst_id_t;

  // Derive AXI-Lite types internally from ctrl width parameters
  typedef logic [CTRL_ADDR_WIDTH-1:0] ctrl_addr_t;
  typedef logic [CTRL_DATA_WIDTH-1:0] ctrl_data_t;
  typedef logic [CTRL_DATA_WIDTH/8-1:0] ctrl_strb_t;
  `AXI_LITE_TYPEDEF_ALL(zeroer_ctrl_axil, ctrl_addr_t, ctrl_data_t, ctrl_strb_t)

  ////////////////////////////////////////////
  // AXI to AXI-Lite for Register Interface //
  ////////////////////////////////////////////

  zeroer_ctrl_axil_req_t  zeroer_ctrl_axil_req;
  zeroer_ctrl_axil_resp_t zeroer_ctrl_axil_resp;

  axi_to_axi_lite #(
    .AxiAddrWidth(CTRL_ADDR_WIDTH),
    .AxiDataWidth(CTRL_DATA_WIDTH),
    .AxiIdWidth(CTRL_ID_WIDTH),
    .AxiUserWidth(CTRL_USER_WIDTH),
    .AxiMaxWriteTxns(1),
    .AxiMaxReadTxns(1),
    .FallThrough(0),
    .FullBW(0),

    .full_req_t (zeroer_ctrl_req_t),
    .full_resp_t(zeroer_ctrl_resp_t),
    .lite_req_t (zeroer_ctrl_axil_req_t),
    .lite_resp_t(zeroer_ctrl_axil_resp_t)

  ) u_ctrl_axi_to_axilite (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_i(test_en_i),
    .slv_req_i(zeroer_ctrl_axi_req_i),
    .slv_resp_o(zeroer_ctrl_axi_resp_o),
    .mst_req_o(zeroer_ctrl_axil_req),
    .mst_resp_i(zeroer_ctrl_axil_resp)
  );

  ///////////////////////
  // Zeroer Core Logic //
  ///////////////////////

  localparam int unsigned AXI_MAX_BURST_LEN = 255;

  logic [63:0] dest_addr;
  logic [63:0] size;
  logic        int_en;
  logic [1:0] status_swacc;
  logic        start;

  logic [31:0] outstanding_reqs;

  typedef enum logic [2:0] {
    ST_ERROR      = 3'b000,
    ST_IDLE       = 3'b001,
    ST_ISSUE_ADDR = 3'b010,
    ST_ISSUE_DATA = 3'b100
  } state_e;
  state_e cur_state, nxt_state;

  // ----------

  logic axi_clk;
  logic reg_clk;

  always_comb begin
    zeroer_busy_o = 1'b1;
    if (cur_state == ST_IDLE) begin
      zeroer_busy_o = start | (|outstanding_reqs);
    end
  end

  wire disable_cg = !cg_enable_i;

  wire axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni;

  prim_clock_gating u_axi_clk_gater (
    .clk_i(clk_i),
    .en_i (axi_clk_enable),
    .test_en_i (test_en_i),
    .clk_o(axi_clk)
  );

  axi_cg_snoop #(
    .OUTSTANDING_TX(1),
    .DENY_DELAY(1),
    .HYST_WIDTH(CG_HYSTERESIS_W)
  ) u_zeroer_cg (
    .clk_i (clk_i),
    .rst_ni(rst_ni),

    .snoop_aw_valid_i(zeroer_ctrl_axil_req.aw_valid),
    .snoop_aw_ready_i(zeroer_ctrl_axil_resp.aw_ready),
    .snoop_w_valid_i(zeroer_ctrl_axil_req.w_valid),
    .snoop_b_valid_i(zeroer_ctrl_axil_resp.b_valid),
    .snoop_b_ready_i(zeroer_ctrl_axil_req.b_ready),
    .snoop_ar_valid_i(zeroer_ctrl_axil_req.ar_valid),
    .snoop_ar_ready_i(zeroer_ctrl_axil_resp.ar_ready),
    .snoop_r_valid_i(zeroer_ctrl_axil_resp.r_valid),
    .snoop_r_ready_i(zeroer_ctrl_axil_req.r_ready),
    .snoop_r_last_i(1'b1),  // every beat is "last" in AXI-L

    .kick_i(disable_cg),  // continuously kick to keep clock awake when not gating

    .test_clk_en_i(test_en_i),
    .hysteresis_i (cg_hysteresis_i),
    .clk_active_o (zeroer_clk_active_o),
    .gated_clk_o  (reg_clk),
    .bus_active_o (zeroer_bus_active_o)
  );

  // ----------

  zeroer_ctrl_reg_pkg::zeroer_ctrl__in_t  hwif_in;
  zeroer_ctrl_reg_pkg::zeroer_ctrl__out_t hwif_out;

  zeroer_ctrl_reg u_zeroer_reg (
    .clk(reg_clk),
    .arst_n(rst_ni),

    .s_axil_awready(zeroer_ctrl_axil_resp.aw_ready),
    .s_axil_awvalid(zeroer_ctrl_axil_req.aw_valid),
    .s_axil_awaddr (zeroer_ctrl_axil_req.aw.addr),
    .s_axil_awprot (zeroer_ctrl_axil_req.aw.prot),
    .s_axil_wready (zeroer_ctrl_axil_resp.w_ready),
    .s_axil_wvalid (zeroer_ctrl_axil_req.w_valid),
    .s_axil_wdata  (zeroer_ctrl_axil_req.w.data),
    .s_axil_wstrb  (zeroer_ctrl_axil_req.w.strb),
    .s_axil_bready (zeroer_ctrl_axil_req.b_ready),
    .s_axil_bvalid (zeroer_ctrl_axil_resp.b_valid),
    .s_axil_bresp  (zeroer_ctrl_axil_resp.b.resp),
    .s_axil_arready(zeroer_ctrl_axil_resp.ar_ready),
    .s_axil_arvalid(zeroer_ctrl_axil_req.ar_valid),
    .s_axil_araddr (zeroer_ctrl_axil_req.ar.addr),
    .s_axil_arprot (zeroer_ctrl_axil_req.ar.prot),
    .s_axil_rready (zeroer_ctrl_axil_req.r_ready),
    .s_axil_rvalid (zeroer_ctrl_axil_resp.r_valid),
    .s_axil_rdata  (zeroer_ctrl_axil_resp.r.data),
    .s_axil_rresp  (zeroer_ctrl_axil_resp.r.resp),

    .hwif_in (hwif_in),
    .hwif_out(hwif_out)
  );

  assign hwif_in.CTRL_STATUS.STATUS.next = zeroer_busy_o;

  assign dest_addr = hwif_out.DEST_ADDR.DEST_ADDR.value;
  assign size = hwif_out.SIZE.SIZE.value;
  assign int_en = hwif_out.CTRL_STATUS.INT_EN.value;

  assign status_swacc = {
    hwif_out.CTRL_STATUS.INT_EN.wr_swacc, hwif_out.CTRL_STATUS.STATUS.rd_swacc
  };

  assign start = status_swacc[1] & (|size);

  // ----------

  axi_addr_t cur_dest_addr, nxt_dest_addr;
  logic [63:0] cur_size, nxt_size;
  logic [64:0] nxt_size_overflow;
  axi_strb_t cur_strb, nxt_strb;
  axi_strb_t cur_last_transfer_strb, nxt_last_transfer_strb;
  axi_pkg::len_t cur_beats_to_transfer, nxt_beats_to_transfer;

  axi_pkg::len_t                    burst_len;
  logic                     [64:0]  aligned_size;
  axi_data_t                        last_transfer_size;
  axi_data_t                        single_beat_bytes;
  axi_data_t                        total_transfer_size;
  logic          [AXI_DATA_WIDTH:0] total_transfer_size_overflow;
  axi_strb_t                        last_strb;

  logic                             mst_awvalid;
  axi_addr_t                        mst_awaddr;
  axi_pkg::len_t                    mst_awlen;

  logic                             mst_wvalid;
  axi_strb_t                        mst_wstrb;
  logic                             mst_wlast;

  logic                             mst_bready;

  always_comb begin
    nxt_state = cur_state;
    nxt_dest_addr = cur_dest_addr;
    nxt_size = cur_size;
    nxt_strb = cur_strb;
    nxt_last_transfer_strb = cur_last_transfer_strb;
    nxt_beats_to_transfer = cur_beats_to_transfer;
    nxt_size_overflow = '0;

    burst_len = axi_pkg::len_t'(0);
    aligned_size = '0;
    last_transfer_size = '0;
    single_beat_bytes = '0;
    total_transfer_size = '0;
    total_transfer_size_overflow = '0;
    last_strb = axi_strb_t'(0);

    mst_awvalid = 1'b0;
    mst_awaddr = axi_addr_t'(0);
    mst_awlen = axi_pkg::len_t'(0);

    mst_wvalid = 1'b0;
    mst_wstrb = axi_strb_t'(0);
    mst_wlast = 1'b0;

    mst_bready = 1'b1;

    unique case (cur_state)
      ST_IDLE: begin
        // when command is triggered, lock in values
        if (start) begin
          nxt_state = ST_ISSUE_ADDR;
          nxt_dest_addr = dest_addr[AXI_ADDR_WIDTH-1:0];
          nxt_size = size;
        end
      end
      ST_ISSUE_ADDR: begin
        mst_awvalid = 1'b1;

        // remove any offset from address
        mst_awaddr = cur_dest_addr & {{(AXI_ADDR_WIDTH-AXI_DATA_SIZE){1'b1}},{AXI_DATA_SIZE{1'b0}}};

        // cannot burst across 4KB boundary, calculate how many bursts can be done before hitting boundary
        // -> using 'hFFF ensures that when addr offset == data_size, it gives the correct length
        if ((('hFFF - 32'(cur_dest_addr[11:0])) >> AXI_DATA_SIZE) > AXI_MAX_BURST_LEN) begin
          burst_len = axi_pkg::len_t'(AXI_MAX_BURST_LEN);
        end else begin
          burst_len = axi_pkg::len_t'(('hFFF - 32'(cur_dest_addr[11:0])) >> AXI_DATA_SIZE);
        end

        // the range can start partway into the first beat, so the beat count and final-beat
        // width follow the aligned end offset within the data width
        aligned_size = {1'b0, cur_size} + {62'd0, cur_dest_addr[AXI_DATA_SIZE-1:0]};

        // check if data left to transfer can be done in less than the max burst length
        // if it can, check if size is not perfectly sized and a strobe is needed
        if (((aligned_size - 65'd1) >> AXI_DATA_SIZE) <= {57'd0, burst_len}) begin
          mst_awlen = axi_pkg::len_t'((aligned_size - 65'd1) >> AXI_DATA_SIZE);
          // final beat starts aligned; its width is the offset end address within the beat
          last_transfer_size = (|aligned_size[AXI_DATA_SIZE-1:0]) ? {61'd0, aligned_size[AXI_DATA_SIZE-1:0]} : {32'd0, AXI_STRB_WIDTH};
        end else begin
          mst_awlen = burst_len;
          // if single beat of data allowed, check for address offsets
          last_transfer_size = |burst_len ? axi_data_t'(AXI_STRB_WIDTH)
                                           : axi_data_t'(AXI_STRB_WIDTH)
                                             - axi_data_t'(cur_dest_addr[AXI_DATA_SIZE-1:0]);
        end

        nxt_last_transfer_strb = ~({AXI_STRB_WIDTH{1'b1}} << last_transfer_size);

        if (|mst_awlen) begin
          total_transfer_size_overflow = ($bits(total_transfer_size_overflow)'(mst_awlen) << AXI_DATA_SIZE)
                                          - $bits(total_transfer_size_overflow)'(cur_dest_addr[AXI_DATA_SIZE-1:0])
                                          + last_transfer_size;
          total_transfer_size = total_transfer_size_overflow[AXI_DATA_WIDTH-1:0];
          // first wstrb depends on address offset
          nxt_strb = {AXI_STRB_WIDTH{1'b1}} << cur_dest_addr[AXI_DATA_SIZE-1:0];
        end else begin
          // single beat: cover [offset, offset+bytes), where bytes is bounded by both the
          // remaining size and the space left in the beat after the offset
          single_beat_bytes = (cur_size < (axi_data_t'(AXI_STRB_WIDTH) - axi_data_t'(cur_dest_addr[AXI_DATA_SIZE-1:0])))
                             ? cur_size[AXI_DATA_WIDTH-1:0]
                             : axi_data_t'(AXI_STRB_WIDTH) - axi_data_t'(cur_dest_addr[AXI_DATA_SIZE-1:0]);
          total_transfer_size = single_beat_bytes;
          // only enough strb bits for the covered bytes when it's a single beat
          for (int i = 0; i < AXI_STRB_WIDTH; i++) begin
            last_strb[i] = single_beat_bytes > axi_data_t'(i);
          end
          // shift strb to correct position based on address offset
          nxt_strb = last_strb << cur_dest_addr[AXI_DATA_SIZE-1:0];
        end

        if (mst_axi_resp_i.aw_ready) begin
          nxt_state = ST_ISSUE_DATA;
          nxt_beats_to_transfer = mst_awlen;
          nxt_dest_addr = mst_awaddr + (($bits(nxt_dest_addr)'(mst_awlen) + 1) << AXI_DATA_SIZE);
          // calculate how much data gets transferred
          // sub last transfer size, sub other transfers, add first transfer offset
          nxt_size_overflow = cur_size - total_transfer_size;
          nxt_size = nxt_size_overflow[63:0];
        end
      end
      ST_ISSUE_DATA: begin
        mst_wvalid = 1'b1;
        mst_wstrb  = cur_strb;

        if (mst_axi_resp_i.w_ready) begin
          if (cur_beats_to_transfer == 0) begin
            mst_wlast = 1'b1;
            nxt_beats_to_transfer = axi_pkg::len_t'(0);
            nxt_strb = {AXI_STRB_WIDTH{1'b0}};
            // after current chunk of data is transferred, anymore chunks?
            nxt_state = (cur_size == '0) ? ST_IDLE : ST_ISSUE_ADDR;
          end else begin
            nxt_beats_to_transfer = cur_beats_to_transfer - 1;
            nxt_strb = (cur_beats_to_transfer == axi_pkg::len_t'(1)) ? cur_last_transfer_strb : {AXI_STRB_WIDTH{1'b1}};
          end
        end
      end
      ST_ERROR: begin
        nxt_state = ST_ERROR;
      end
      default: begin
        nxt_state = ST_ERROR;
      end
    endcase
  end

  always_ff @(posedge axi_clk or negedge rst_ni) begin
    if (~rst_ni) begin
      cur_state <= ST_IDLE;
      cur_dest_addr <= axi_addr_t'(0);
      cur_size <= '0;
      cur_strb <= axi_strb_t'(0);
      cur_last_transfer_strb <= '0;
      cur_beats_to_transfer <= axi_pkg::len_t'(0);
    end else begin
      cur_state <= nxt_state;
      cur_dest_addr <= nxt_dest_addr;
      cur_size <= nxt_size;
      cur_strb <= nxt_strb;
      cur_last_transfer_strb <= nxt_last_transfer_strb;
      cur_beats_to_transfer <= nxt_beats_to_transfer;
    end
  end

  // every time a transaction is sent out, count to know when it has completed
  always_ff @(posedge axi_clk or negedge rst_ni) begin
    if (~rst_ni) begin
      outstanding_reqs <= 32'd0;
    end else begin
      outstanding_reqs <= outstanding_reqs
                           + 32'(mst_axi_resp_i.aw_ready & mst_axi_req_o.aw_valid)
                           - 32'(mst_axi_req_o.b_ready & mst_axi_resp_i.b_valid);
    end
  end

  // Ungated clock: axi_clk stops the cycle busy falls, so it would never sample that edge.
  logic prev_busy;
  always_ff @(posedge clk_i) begin
    if (~rst_ni) begin
      prev_busy <= 1'b0;
      zeroer_intp_o <= 1'b0;
    end else begin
      prev_busy <= zeroer_busy_o;
      if (nxt_state == ST_ERROR) begin
        zeroer_intp_o <= 1'b0;
      end else if (int_en) begin
        // trigger on falling edge of busy
        zeroer_intp_o <= prev_busy & !zeroer_busy_o;
      end
    end
  end

  // ----------

  assign mst_axi_req_o.aw_valid  = mst_awvalid;
  assign mst_axi_req_o.aw.addr   = mst_awaddr;
  assign mst_axi_req_o.aw.len    = mst_awlen;
  assign mst_axi_req_o.w_valid   = mst_wvalid;
  assign mst_axi_req_o.w.data    = '0;  // always write 0
  assign mst_axi_req_o.w.strb    = mst_wstrb;
  assign mst_axi_req_o.w.last    = mst_wlast;
  assign mst_axi_req_o.b_ready   = mst_bready;

  // tie off unused write channel signals
  assign mst_axi_req_o.aw.id     = mst_id_t'(0);
  assign mst_axi_req_o.aw.size   = axi_pkg::size_t'(AXI_DATA_SIZE);
  assign mst_axi_req_o.aw.burst  = axi_pkg::BURST_INCR;
  assign mst_axi_req_o.aw.lock   = 1'b0;
  assign mst_axi_req_o.aw.cache  = axi_pkg::cache_t'(0);
  assign mst_axi_req_o.aw.prot   = axi_pkg::prot_t'(0);
  assign mst_axi_req_o.aw.qos    = axi_pkg::qos_t'(0);
  assign mst_axi_req_o.aw.region = axi_pkg::region_t'(0);
  assign mst_axi_req_o.aw.atop   = axi_pkg::atop_t'(0);
  assign mst_axi_req_o.aw.user   = axi_user_t'(0);
  assign mst_axi_req_o.w.user    = axi_user_t'(0);

  // will never issue a read, tie off
  assign mst_axi_req_o.ar_valid  = 1'b0;
  assign mst_axi_req_o.ar.id     = mst_id_t'(0);
  assign mst_axi_req_o.ar.addr   = axi_addr_t'(0);
  assign mst_axi_req_o.ar.len    = axi_pkg::len_t'(0);
  assign mst_axi_req_o.ar.size   = axi_pkg::size_t'(0);
  assign mst_axi_req_o.ar.burst  = axi_pkg::BURST_INCR;
  assign mst_axi_req_o.ar.lock   = 1'b0;
  assign mst_axi_req_o.ar.cache  = axi_pkg::cache_t'(0);
  assign mst_axi_req_o.ar.prot   = axi_pkg::prot_t'(0);
  assign mst_axi_req_o.ar.qos    = axi_pkg::qos_t'(0);
  assign mst_axi_req_o.ar.region = axi_pkg::region_t'(0);
  assign mst_axi_req_o.ar.user   = axi_user_t'(0);
  assign mst_axi_req_o.r_ready   = 1'b0;

  `OCAH_ASSERT_NEVER(TotalTransferSizeOverflow, total_transfer_size_overflow[AXI_DATA_WIDTH],
                     clk_i, !rst_ni)
  `OCAH_ASSERT_NEVER(NxtSizeOverflow, nxt_size_overflow[64], clk_i, !rst_ni)
  `OCAH_ASSERT(
      IllegalStateTransitionsToError_A,
      ($isunknown(cur_state)
      || !(cur_state inside {ST_ERROR, ST_IDLE, ST_ISSUE_ADDR, ST_ISSUE_DATA})) |=> cur_state == ST_ERROR,
      axi_clk, !rst_ni)
  `OCAH_ASSERT(ErrorStateAbsorbing_A, cur_state == ST_ERROR |=> cur_state == ST_ERROR, axi_clk,
               !rst_ni)
  `OCAH_ASSERT(
      ErrorStateFailsClosed_A,
      cur_state == ST_ERROR |-> zeroer_busy_o && !zeroer_intp_o && !mst_awvalid && !mst_wvalid,
      axi_clk, !rst_ni)

endmodule
