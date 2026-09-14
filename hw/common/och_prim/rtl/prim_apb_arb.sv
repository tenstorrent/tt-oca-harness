// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// APB arbiter
//
//--------------------------------------------------
module prim_apb_arb #(
  parameter int unsigned ADDR_WIDTH = 32,
  parameter int unsigned DATA_WIDTH = 32,
  parameter int unsigned MASTER_NUM = 8,
  parameter bit [31:0] SLAVE_ADDR_START = 32'h0000,  // included address
  parameter bit [31:0] SLAVE_ADDR_END = 32'h1000,     // excluded address
  localparam int unsigned DATA_STRB_WIDTH = DATA_WIDTH / 8
) (
  input logic clk_i,
  input logic rst_ni,

`ifdef SIM_APB_ARB
  //APB TEST master interface
  input  logic                        test_psel_i,
  input  logic                        test_penable_i,
  input  logic [ADDR_WIDTH -1:0]      test_paddr_i,
  input  logic                        test_pwrite_i,
  input  logic [DATA_WIDTH -1:0]      test_pwdata_i,
  input  logic [DATA_STRB_WIDTH -1:0] test_pstrb_i,
  output logic [DATA_WIDTH -1:0]      test_prdata_o,
  output logic                        test_pready_o,
  output logic                        test_pslverr_o,
`endif

  //APB master interfaces
  input  logic [MASTER_NUM-1:0]                       mst_psel_i,
  input  logic [MASTER_NUM-1:0]                       mst_penable_i,
  input  logic [MASTER_NUM-1:0][ADDR_WIDTH -1:0]      mst_paddr_i,
  input  logic [MASTER_NUM-1:0]                       mst_pwrite_i,
  input  logic [MASTER_NUM-1:0][DATA_WIDTH -1:0]      mst_pwdata_i,
  input  logic [MASTER_NUM-1:0][DATA_STRB_WIDTH -1:0] mst_pstrb_i,
  output logic [MASTER_NUM-1:0][DATA_WIDTH -1:0]      mst_prdata_o,
  output logic [MASTER_NUM-1:0]                       mst_pready_o,
  output logic [MASTER_NUM-1:0]                       mst_pslverr_o,

  //APB slave interface
  output logic                        slv_psel_o,
  output logic                        slv_penable_o,
  output logic [ADDR_WIDTH -1:0]      slv_paddr_o,
  output logic                        slv_pwrite_o,
  output logic [DATA_WIDTH -1:0]      slv_pwdata_o,
  output logic [DATA_STRB_WIDTH -1:0] slv_pstrb_o,
  input  logic [DATA_WIDTH -1:0]      slv_prdata_i,
  input  logic                        slv_pready_i,
  input  logic                        slv_pslverr_i
);

`ifdef SIM_APB_ARB
  localparam int unsigned MASTER_SUM_NUM = MASTER_NUM + 1;
`else
  localparam int unsigned MASTER_SUM_NUM = MASTER_NUM;
`endif

  localparam int unsigned PTR_WIDTH = $clog2(MASTER_SUM_NUM);

  logic [MASTER_SUM_NUM-1:0]                       mst_sel_arb;

  logic [MASTER_SUM_NUM-1:0]                       mst_psel;
  logic [MASTER_SUM_NUM-1:0]                       mst_penable;
  logic [MASTER_SUM_NUM-1:0][ADDR_WIDTH -1:0]      mst_paddr;
  logic [MASTER_SUM_NUM-1:0]                       mst_pwrite;
  logic [MASTER_SUM_NUM-1:0][DATA_WIDTH -1:0]      mst_pwdata;
  logic [MASTER_SUM_NUM-1:0][DATA_STRB_WIDTH -1:0] mst_pstrb;
  logic [MASTER_SUM_NUM-1:0][DATA_WIDTH -1:0]      mst_prdata;
  logic [MASTER_SUM_NUM-1:0]                       mst_pready;
  logic [MASTER_SUM_NUM-1:0]                       mst_pslverr;

`ifdef SIM_APB_ARB
  // in case we have TEST port, we connect it as highest index master
  assign mst_psel    = {test_psel_i,    mst_psel_i   };
  assign mst_penable = {test_penable_i, mst_penable_i};
  assign mst_paddr   = {test_paddr_i,   mst_paddr_i  };
  assign mst_pwrite  = {test_pwrite_i,  mst_pwrite_i };
  assign mst_pwdata  = {test_pwdata_i,  mst_pwdata_i };
  assign mst_pstrb   = {test_pstrb_i,   mst_pstrb_i  };
  assign {test_prdata_o,  mst_prdata_o } = mst_prdata ;
  assign {test_pready_o,  mst_pready_o } = mst_pready ;
  assign {test_pslverr_o, mst_pslverr_o} = mst_pslverr;
`else
  // else we have only master ports used
  assign mst_psel    = mst_psel_i   ;
  assign mst_penable = mst_penable_i;
  assign mst_paddr   = mst_paddr_i  ;
  assign mst_pwrite  = mst_pwrite_i ;
  assign mst_pwdata  = mst_pwdata_i ;
  assign mst_pstrb   = mst_pstrb_i  ;
  assign mst_prdata_o  = mst_prdata ;
  assign mst_pready_o  = mst_pready ;
  assign mst_pslverr_o = mst_pslverr;
`endif

  logic [MASTER_SUM_NUM-1:0] mst_req_r, mst_req_nxt;
  logic [MASTER_SUM_NUM-1:0][ADDR_WIDTH -1:0] mst_paddr_r, mst_paddr_nxt;
  logic [MASTER_SUM_NUM-1:0] mst_pwrite_r, mst_pwrite_nxt;
  logic [MASTER_SUM_NUM-1:0][DATA_WIDTH -1:0] mst_pwdata_r, mst_pwdata_nxt;
  logic [MASTER_SUM_NUM-1:0][DATA_STRB_WIDTH -1:0] mst_pstrb_r, mst_pstrb_nxt;
  logic [MASTER_SUM_NUM-1:0][DATA_WIDTH -1:0] mst_prdata_r, mst_prdata_nxt;
  logic [MASTER_SUM_NUM-1:0] mst_pready_r, mst_pready_nxt;
  logic [MASTER_SUM_NUM-1:0] mst_pslverr_r, mst_pslverr_nxt;

  logic slv_psel_r, slv_psel_nxt;
  logic slv_penable_r, slv_penable_nxt;
  logic [ADDR_WIDTH -1:0] slv_paddr_r, slv_paddr_nxt;
  logic slv_pwrite_r, slv_pwrite_nxt;
  logic [DATA_WIDTH -1:0] slv_pwdata_r, slv_pwdata_nxt;
  logic [DATA_STRB_WIDTH -1:0] slv_pstrb_r, slv_pstrb_nxt;

  logic [PTR_WIDTH-1:0] mask_ptr_r, mask_ptr_nxt;

  logic update_arb;

  typedef enum logic [1:0] {
    IDLE = 2'd0,
    SETUP = 2'd1,
    ACCESS = 2'd2,
    IDLE_MASK = 2'd3
  } apb_state_t;
  apb_state_t apb_state_r, apb_state_nxt;

  // APB DATAPATH registers don't have reset for common rtl optimization
  always_ff @(posedge clk_i) begin : mst_stage
    if (~rst_ni) begin
      for (int i = 0; i < MASTER_SUM_NUM; i++) begin
        mst_req_r[i]    <= 1'b0;
        mst_pready_r[i] <= 1'b0;
      end
      slv_psel_r    <= 1'b0;
      slv_penable_r <= 1'b0;
      mask_ptr_r    <= {PTR_WIDTH{1'd0}};
    end else begin
      mst_req_r     <= mst_req_nxt;
      mst_paddr_r   <= mst_paddr_nxt;
      mst_pwrite_r  <= mst_pwrite_nxt;
      mst_pwdata_r  <= mst_pwdata_nxt;
      mst_pstrb_r   <= mst_pstrb_nxt;
      mst_prdata_r  <= mst_prdata_nxt;
      mst_pready_r  <= mst_pready_nxt;
      mst_pslverr_r <= mst_pslverr_nxt;
      slv_psel_r    <= slv_psel_nxt;
      slv_penable_r <= slv_penable_nxt;
      slv_paddr_r   <= slv_paddr_nxt;
      slv_pwrite_r  <= slv_pwrite_nxt;
      slv_pwdata_r  <= slv_pwdata_nxt;
      slv_pstrb_r   <= slv_pstrb_nxt;
      mask_ptr_r    <= mask_ptr_nxt;
    end
  end

  wire [$clog2(MASTER_SUM_NUM)-1:0] mst_sel_index;
  wire mst_sel_request;
  prim_fair_rr_arb #(
    .NumIn(MASTER_SUM_NUM),
    .DataWidth(0),
    .DataType(logic),
    .ExtPrio(1'b0),
    .AxiVldRdy(1'b1),
    .LockIn(1'b1),
    .FairArb(1'b1)
  ) apb_arb (
    .clk_i        (clk_i),
    .rst_ni       (rst_ni),
    .flush_i      (1'b0),
    .rr_priority_i({$clog2(MASTER_SUM_NUM){1'b0}}),
    .request_i    (mst_req_r),
    .grant_o      (),
    .data_i       ({MASTER_SUM_NUM{1'b0}}),
    .request_o    (mst_sel_request),
    .grant_i      (update_arb),
    .data_o       (),
    .index_o      (mst_sel_index)
  );

  always_comb begin
    mst_sel_arb = 'd0;
    if (mst_sel_request) mst_sel_arb[mst_sel_index] = 1'b1;
  end

  // APB state machine for slave interface
  always_ff @(posedge clk_i) begin : apb_fsm_ff
    if (~rst_ni) begin
      apb_state_r <= IDLE;
    end else begin
      apb_state_r <= apb_state_nxt;
    end
  end

  always_comb begin : apb_fsm_comb
    apb_state_nxt   = apb_state_r;

    slv_psel_nxt    = slv_psel_r;
    slv_penable_nxt = slv_penable_r;
    slv_paddr_nxt   = slv_paddr_r;
    slv_pwrite_nxt  = slv_pwrite_r;
    slv_pwdata_nxt  = slv_pwdata_r;
    slv_pstrb_nxt   = slv_pstrb_r;

    // Taking reasonable assumption that all APB masters work as in AMBA spec and do not need additional protocol checking for psel/penable
    mst_req_nxt     = mst_psel & mst_penable;
    mst_paddr_nxt   = mst_paddr;
    mst_pwrite_nxt  = mst_pwrite;
    mst_pwdata_nxt  = mst_pwdata;
    mst_pstrb_nxt   = mst_pstrb;
    mst_prdata_nxt  = mst_prdata_r;
    mst_pready_nxt  = {MASTER_SUM_NUM{1'b0}};
    mst_pslverr_nxt = {MASTER_SUM_NUM{1'b0}};

    mask_ptr_nxt    = mask_ptr_r;
    update_arb      = 1'b0;

    unique case (apb_state_r)
      IDLE: begin
        for (int i = 0; i < MASTER_SUM_NUM; i++) begin
          if (mst_sel_arb[i] == 1'b1) begin  // one hot array
            slv_psel_nxt   = 1'b1;
            slv_paddr_nxt  = mst_paddr_r[i];
            slv_pwrite_nxt = mst_pwrite_r[i];
            slv_pwdata_nxt = mst_pwdata_r[i];
            slv_pstrb_nxt  = mst_pstrb_r[i];
            apb_state_nxt  = SETUP;
          end
        end
      end

      SETUP: begin
        slv_penable_nxt = 1'b1;
        apb_state_nxt   = ACCESS;
      end

      ACCESS: begin
        if (slv_pready_i) begin
          for (int i = 0; i < MASTER_SUM_NUM; i++) begin
            if (mst_sel_arb[i] == 1'b1) begin  // one hot array
              mst_prdata_nxt[i] = slv_prdata_i;
              mst_pready_nxt[i] = 1'b1;
              mst_pslverr_nxt[i] = slv_pslverr_i;
              // since there is stage on masters interface, from FSM's point of view,
              // master will deassert its psel/penable with 2 cycle delay since slave pready is asserted
              //    1 cycle for stage on arbiter's master output interface (mst_pready assertion)
              //    1 cycle for stage on arbiter's master input interface (mst_psel/penable deassertion)
              // Therefore, we need to mask served master for 2 clk cycles
              // to prevent it from generating excess transactions
              // That's why we introduce additional state that will mask this for 1 more transaction
              // Otherwise this state is working in same manner as IDLE state, and it can receive next transaction
              mst_req_nxt[i] = 1'b0;
              mask_ptr_nxt = i[PTR_WIDTH-1:0];
            end
          end
          slv_psel_nxt    = 1'b0;
          slv_penable_nxt = 1'b0;
          update_arb = 1'b1;
          apb_state_nxt = IDLE_MASK;
        end
      end

      IDLE_MASK: begin
        // masking the last served master to prevent generating excess transactions
        // at this point in time mst_psel/penable are still asserted from FSM point of view
        mst_req_nxt[mask_ptr_r] = 1'b0;
        // we don't want to stay in this state longer than 1 cycle
        // after this cycle if served master is still having psel/penable this is the sign of new transaction
        // Therefore we need to go to IDLE to stop masking request if there are no other requests
        // If there are some other masters requesting arbitration we continue with serving them
        if (|mst_sel_arb == 1'b0) begin
          apb_state_nxt = IDLE;
        end else begin
          for (int i = 0; i < MASTER_SUM_NUM; i++) begin
            if (mst_sel_arb[i] == 1'b1) begin  // one hot array
              slv_psel_nxt   = 1'b1;
              slv_paddr_nxt  = mst_paddr_r[i];
              slv_pwrite_nxt = mst_pwrite_r[i];
              slv_pwdata_nxt = mst_pwdata_r[i];
              slv_pstrb_nxt  = mst_pstrb_r[i];
              apb_state_nxt  = SETUP;
            end
          end
        end
      end
    endcase
  end

  assign slv_psel_o    = slv_psel_r;
  assign slv_penable_o = slv_penable_r;
  assign slv_paddr_o   = slv_paddr_r;
  assign slv_pwrite_o  = slv_pwrite_r;
  assign slv_pwdata_o  = slv_pwdata_r;
  assign slv_pstrb_o   = slv_pstrb_r;

  assign mst_prdata  = mst_prdata_r;
  assign mst_pready  = mst_pready_r;
  assign mst_pslverr = mst_pslverr_r;

endmodule
