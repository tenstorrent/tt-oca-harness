// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AXI4-Lite slave to AHB-Lite master protocol converter.
//
// One transaction is in flight at a time. An accepted read or write is issued
// as a single NONSEQ transfer with HBURST = SINGLE, and its AXI response is
// returned before the next request is accepted, so HTRANS is only ever IDLE or
// NONSEQ and HADDR always carries the full transfer address. With a read and a
// write both waiting, the converter alternates between them.
//
// Reads are word transfers (HSIZE = 3'b010) at the word-aligned address:
// AXI4-Lite carries no transfer size, and the R channel returns the whole
// 32-bit lane.
//
// Writes take HSIZE and HADDR[1:0] from WSTRB. A full-word strobe is always
// issued. ALLOW_SUB_WORD_WRITE also admits the naturally aligned byte and
// halfword strobes; with it clear, and for every other non-zero strobe, the
// write completes with SLVERR and no AHB transfer is issued. Keep it clear for
// a slave that ignores HSIZE on writes, where a sub-word write overwrites the
// rest of the word.
//
// ACK_ZERO_STROBE_WRITE: a write with WSTRB == 0 is a legal AXI no-op. An AXI
// data-width downsizer produces such beats when it splits a wider master's
// beat, putting the lanes outside the master's strobe on the neighbouring
// word. AHB-Lite has no zero-byte transfer, so such a write is never issued:
// with the parameter set it completes with OKAY, and clear, with SLVERR.
//
// AHB_DATA_WIDTH = 64 carries the 32-bit AXI lane on the half of the AHB data
// bus that HADDR[2] selects: HWDATA drives the write data on both halves, and
// the read data is taken from the selected half of HRDATA.
//
// HRESP = ERROR completes the transfer with SLVERR. No second transfer is ever
// pending behind the one in its data phase, so the two-cycle error response
// needs no cancellation.
//
// HPROT carries AxPROT privileged and instruction as HPROT[1] and ~HPROT[0],
// and is never bufferable or cacheable. AHB-Lite has no security attribute, so
// AxPROT[1] (non-secure) is not carried.

`include "ocah_assert.svh"

module axi_lite_to_ahb #(
  parameter int unsigned AXI_ADDR_WIDTH        = 32,
  parameter int unsigned AXI_DATA_WIDTH        = 32,    // Must be 32
  parameter int unsigned AHB_DATA_WIDTH        = 32,    // 32 or 64
  parameter type         axi_lite_req_t        = logic,
  parameter type         axi_lite_rsp_t        = logic,
  parameter bit          ALLOW_SUB_WORD_WRITE  = 1'b0,  // Aligned byte/halfword WSTRB: HSIZE < word
  parameter bit          ACK_ZERO_STROBE_WRITE = 1'b0   // WSTRB==0 writes: OKAY, no AHB transfer
) (
  input  logic                      clk_i,
  input  logic                      rst_ni,

  // AXI4 Lite Slave Interface
  input  axi_lite_req_t             axi_lite_req_i,
  output axi_lite_rsp_t             axi_lite_rsp_o,

  // AHB-Lite Master Interface
  output logic [AXI_ADDR_WIDTH-1:0] ahb_haddr_o,
  output logic [2:0]                ahb_hburst_o,
  output logic                      ahb_hmastlock_o,
  output logic [3:0]                ahb_hprot_o,
  output logic [2:0]                ahb_hsize_o,
  output logic [1:0]                ahb_htrans_o,
  output logic                      ahb_hwrite_o,
  output logic [AHB_DATA_WIDTH-1:0] ahb_hwdata_o,
  input  logic [AHB_DATA_WIDTH-1:0] ahb_hrdata_i,
  input  logic                      ahb_hready_i,
  input  logic                      ahb_hresp_i
);

  `include "prim_assert.sv"

  // --------------------------------------------------
  // Local Parameters
  // --------------------------------------------------
  localparam logic [1:0] AxiRespOkay = 2'b00;
  localparam logic [1:0] AxiRespSlverr = 2'b10;

  localparam logic [1:0] HtransIdle = 2'b00;
  localparam logic [1:0] HtransNonseq = 2'b10;
  localparam logic [2:0] HburstSingle = 3'b000;
  localparam logic [2:0] HsizeByte = 3'b000;
  localparam logic [2:0] HsizeHalf = 3'b001;
  localparam logic [2:0] HsizeWord = 3'b010;

  localparam int unsigned AxiStrbWidth = AXI_DATA_WIDTH / 8;
  localparam int unsigned AhbLanes = AHB_DATA_WIDTH / AXI_DATA_WIDTH;

  `OCAH_ASSERT_STATIC(DataWidth_A, AXI_DATA_WIDTH == 32 && AHB_DATA_WIDTH inside {32, 64},
                      "AXI_DATA_WIDTH must be 32 and AHB_DATA_WIDTH 32 or 64")

  // FSM States
  typedef enum logic [2:0] {
    IDLE,
    AHB_RD_ADDR,  // Read address phase (NONSEQ)
    AHB_RD_DATA,  // Read data phase: wait for HREADY
    AXI_R_RESP,   // Send Read Data on AXI R
    AHB_WR_ADDR,  // Write address phase (NONSEQ)
    AHB_WR_DATA,  // Write data phase: wait for HREADY
    AXI_B_RESP    // Send Write Resp on AXI B
  } state_e;

  state_e state_q, state_d;

  // Latched transaction details
  logic [AXI_ADDR_WIDTH-1:0] req_addr_q;
  logic [AXI_ADDR_WIDTH-1:0] req_addr_d;
  logic [2:0]                req_prot_q;
  logic [2:0]                req_prot_d;
  logic [2:0]                req_size_q;
  logic [2:0]                req_size_d;
  logic [AXI_DATA_WIDTH-1:0] req_data_q;
  logic [AXI_DATA_WIDTH-1:0] req_data_d;

  // Response tracking
  logic [AXI_DATA_WIDTH-1:0] resp_data_q;
  logic [AXI_DATA_WIDTH-1:0] resp_data_d;
  logic                      req_error_q;
  logic                      req_error_d;

  // Read/write arbitration
  logic                      rd_req;
  logic                      wr_req;
  logic                      wr_first_q;  // A write lost to a read, so it goes next
  logic                      wr_first_d;

  // Write strobe decode
  logic                      wr_strb_legal;
  logic [2:0]                wr_strb_size;
  logic [1:0]                wr_strb_offset;

  // Read data lane of the AHB data bus
  logic [AXI_DATA_WIDTH-1:0] ahb_rdata_lane;

  logic                      ahb_addr_phase;

  // --------------------------------------------------
  // FSM Sequential Logic
  // --------------------------------------------------
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q     <= IDLE;
      req_addr_q  <= '0;
      req_prot_q  <= '0;
      req_size_q  <= HsizeWord;
      req_data_q  <= '0;
      resp_data_q <= '0;
      req_error_q <= 1'b0;
      wr_first_q  <= 1'b0;
    end else begin
      state_q     <= state_d;
      req_addr_q  <= req_addr_d;
      req_prot_q  <= req_prot_d;
      req_size_q  <= req_size_d;
      req_data_q  <= req_data_d;
      resp_data_q <= resp_data_d;
      req_error_q <= req_error_d;
      wr_first_q  <= wr_first_d;
    end
  end

  // --------------------------------------------------
  // Write Strobe Decode
  // --------------------------------------------------
  always_comb begin
    wr_strb_legal  = 1'b0;
    wr_strb_size   = HsizeWord;
    wr_strb_offset = 2'd0;
    case (axi_lite_req_i.w.strb)
      4'b1111: begin
        wr_strb_legal = 1'b1;
      end
      4'b0011, 4'b1100: begin
        wr_strb_legal  = ALLOW_SUB_WORD_WRITE;
        wr_strb_size   = HsizeHalf;
        wr_strb_offset = {axi_lite_req_i.w.strb[2], 1'b0};
      end
      4'b0001, 4'b0010, 4'b0100, 4'b1000: begin
        wr_strb_legal  = ALLOW_SUB_WORD_WRITE;
        wr_strb_size   = HsizeByte;
        wr_strb_offset = {axi_lite_req_i.w.strb[3] | axi_lite_req_i.w.strb[2],
                          axi_lite_req_i.w.strb[3] | axi_lite_req_i.w.strb[1]};
      end
      default: ;
    endcase
  end

  // --------------------------------------------------
  // AHB Data Lane Select
  // --------------------------------------------------
  if (AhbLanes > 1) begin : gen_wide_ahb
    logic [$clog2(AhbLanes)-1:0] rd_lane;

    assign rd_lane        = req_addr_q[$clog2(AxiStrbWidth) +: $clog2(AhbLanes)];
    assign ahb_rdata_lane = ahb_hrdata_i[rd_lane*AXI_DATA_WIDTH +: AXI_DATA_WIDTH];
  end else begin : gen_narrow_ahb
    assign ahb_rdata_lane = ahb_hrdata_i;
  end

  // --------------------------------------------------
  // AHB Outputs
  // --------------------------------------------------
  assign ahb_addr_phase = (state_q == AHB_RD_ADDR) || (state_q == AHB_WR_ADDR);

  // Address and control only matter while HTRANS is NONSEQ; they are held from
  // the latched request so they stay stable for the whole address phase.
  assign ahb_haddr_o     = req_addr_q;
  assign ahb_hburst_o    = HburstSingle;
  assign ahb_hmastlock_o = 1'b0;
  assign ahb_hprot_o     = {2'b00, req_prot_q[0], ~req_prot_q[2]};
  assign ahb_hsize_o     = req_size_q;
  assign ahb_htrans_o    = ahb_addr_phase ? HtransNonseq : HtransIdle;
  assign ahb_hwrite_o    = (state_q == AHB_WR_ADDR);
  assign ahb_hwdata_o    = {AhbLanes{req_data_q}};

  // --------------------------------------------------
  // FSM Combinational Logic
  // --------------------------------------------------
  assign rd_req = axi_lite_req_i.ar_valid;
  assign wr_req = axi_lite_req_i.aw_valid && axi_lite_req_i.w_valid;

  always_comb begin
    state_d     = state_q;
    req_addr_d  = req_addr_q;
    req_prot_d  = req_prot_q;
    req_size_d  = req_size_q;
    req_data_d  = req_data_q;
    resp_data_d = resp_data_q;
    req_error_d = req_error_q;
    wr_first_d  = wr_first_q;

    axi_lite_rsp_o        = '0;
    axi_lite_rsp_o.b.resp = AxiRespOkay;
    axi_lite_rsp_o.r.resp = AxiRespOkay;

    case (state_q)
      IDLE: begin
        // A read goes first unless a write has already lost to one.
        if (rd_req && !(wr_req && wr_first_q)) begin
          axi_lite_rsp_o.ar_ready = 1'b1;
          req_addr_d  = {axi_lite_req_i.ar.addr[AXI_ADDR_WIDTH-1:2], 2'b00};
          req_prot_d  = axi_lite_req_i.ar.prot;
          req_size_d  = HsizeWord;
          wr_first_d  = wr_req;
          state_d     = AHB_RD_ADDR;
        end else if (wr_req) begin
          // A write needs both AW and W before either is accepted.
          axi_lite_rsp_o.aw_ready = 1'b1;
          axi_lite_rsp_o.w_ready  = 1'b1;
          req_addr_d  = {axi_lite_req_i.aw.addr[AXI_ADDR_WIDTH-1:2], wr_strb_offset};
          req_prot_d  = axi_lite_req_i.aw.prot;
          req_size_d  = wr_strb_size;
          req_data_d  = axi_lite_req_i.w.data;
          wr_first_d  = 1'b0;
          if (axi_lite_req_i.w.strb == '0) begin
            req_error_d = !ACK_ZERO_STROBE_WRITE;
            state_d     = AXI_B_RESP;
          end else if (!wr_strb_legal) begin
            req_error_d = 1'b1;
            state_d     = AXI_B_RESP;
          end else begin
            state_d = AHB_WR_ADDR;
          end
        end
      end

      // ==========================================
      // READ FLOW
      // ==========================================
      AHB_RD_ADDR: begin
        if (ahb_hready_i) begin
          state_d = AHB_RD_DATA;
        end
      end

      AHB_RD_DATA: begin
        if (ahb_hready_i) begin
          resp_data_d = ahb_rdata_lane;
          req_error_d = ahb_hresp_i;
          state_d     = AXI_R_RESP;
        end
      end

      AXI_R_RESP: begin
        axi_lite_rsp_o.r_valid = 1'b1;
        axi_lite_rsp_o.r.data  = resp_data_q;
        axi_lite_rsp_o.r.resp  = req_error_q ? AxiRespSlverr : AxiRespOkay;

        if (axi_lite_req_i.r_ready) begin
          state_d = IDLE;
        end
      end

      // ==========================================
      // WRITE FLOW
      // ==========================================
      AHB_WR_ADDR: begin
        if (ahb_hready_i) begin
          state_d = AHB_WR_DATA;
        end
      end

      AHB_WR_DATA: begin
        if (ahb_hready_i) begin
          req_error_d = ahb_hresp_i;
          state_d     = AXI_B_RESP;
        end
      end

      AXI_B_RESP: begin
        axi_lite_rsp_o.b_valid = 1'b1;
        axi_lite_rsp_o.b.resp  = req_error_q ? AxiRespSlverr : AxiRespOkay;

        if (axi_lite_req_i.b_ready) begin
          state_d = IDLE;
        end
      end

      default: state_d = IDLE;
    endcase
  end

  // --------------------------------------------------
  // Assertions
  // --------------------------------------------------
`ifdef OCAH_OT_INC_ASSERT
  logic [AXI_ADDR_WIDTH+7:0] ahb_addr_ctrl;
  logic [4:0]                axi_handshake;
  logic                      ahb_addr_stall;
  logic                      ahb_xfer_aligned;
  logic                      wr_data_stall;
  logic                      r_stall;
  logic                      b_stall;

  assign ahb_addr_ctrl  = {ahb_haddr_o, ahb_hwrite_o, ahb_hsize_o, ahb_hprot_o};
  assign axi_handshake  = {axi_lite_rsp_o.ar_ready, axi_lite_rsp_o.aw_ready, axi_lite_rsp_o.w_ready,
                           axi_lite_rsp_o.r_valid, axi_lite_rsp_o.b_valid};
  assign ahb_addr_stall = ahb_addr_phase && !ahb_hready_i;
  assign wr_data_stall  = (state_q == AHB_WR_DATA) && !ahb_hready_i;
  assign r_stall        = axi_lite_rsp_o.r_valid && !axi_lite_req_i.r_ready;
  assign b_stall        = axi_lite_rsp_o.b_valid && !axi_lite_req_i.b_ready;

  always_comb begin
    case (ahb_hsize_o)
      HsizeWord:  ahb_xfer_aligned = (ahb_haddr_o[1:0] == 2'b00);
      HsizeHalf:  ahb_xfer_aligned = ALLOW_SUB_WORD_WRITE && ahb_hwrite_o && !ahb_haddr_o[0];
      HsizeByte:  ahb_xfer_aligned = ALLOW_SUB_WORD_WRITE && ahb_hwrite_o;
      default:    ahb_xfer_aligned = 1'b0;
    endcase
  end
`endif

  `OCAH_OT_ASSERT_KNOWN(HtransKnown_A, ahb_htrans_o)
  `OCAH_OT_ASSERT_KNOWN_IF(AddrCtrlKnown_A, ahb_addr_ctrl, ahb_addr_phase)
  `OCAH_OT_ASSERT_KNOWN(AxiHandshakeKnown_A, axi_handshake)

  // AHB-Lite: an accepted address phase is followed by a data phase with no
  // second transfer behind it.
  `OCAH_OT_ASSERT(SingleOutstanding_A, ahb_addr_phase && ahb_hready_i |=> !ahb_addr_phase)
  // AHB-Lite: address and control stay stable while an address phase is stalled.
  `OCAH_OT_ASSERT(AddrPhaseHeld_A, ahb_addr_stall |=> ahb_addr_phase && $stable(ahb_addr_ctrl))
  `OCAH_OT_COVER(AddrPhaseStalled_C, ahb_addr_stall)
  // AHB-Lite: write data stays stable while a write data phase is stalled.
  `OCAH_OT_ASSERT(WriteDataHeld_A, wr_data_stall |=> $stable(ahb_hwdata_o))
  // Reads are words; sub-word writes only when allowed; HADDR aligned to HSIZE.
  `OCAH_OT_ASSERT(TransferAligned_A, ahb_addr_phase |-> ahb_xfer_aligned)

  // AXI: a response stays valid, and unchanged, until it is taken.
  `OCAH_OT_ASSERT(RespRHeld_A, r_stall |=> axi_lite_rsp_o.r_valid && $stable(axi_lite_rsp_o.r))
  `OCAH_OT_ASSERT(RespBHeld_A, b_stall |=> axi_lite_rsp_o.b_valid && $stable(axi_lite_rsp_o.b))

endmodule : axi_lite_to_ahb
