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
  input logic i_clk,
  input logic i_reset_n,

`ifdef SIM_APB_ARB
  //APB TEST master interface
  input  logic                        i_test_psel,
  input  logic                        i_test_penable,
  input  logic [ADDR_WIDTH -1:0]      i_test_paddr,
  input  logic                        i_test_pwrite,
  input  logic [DATA_WIDTH -1:0]      i_test_pwdata,
  input  logic [DATA_STRB_WIDTH -1:0] i_test_pstrb,
  output logic [DATA_WIDTH -1:0]      o_test_prdata,
  output logic                        o_test_pready,
  output logic                        o_test_pslverr,
`endif

  //APB master interfaces
  input  logic [MASTER_NUM-1:0]                       i_mst_psel,
  input  logic [MASTER_NUM-1:0]                       i_mst_penable,
  input  logic [MASTER_NUM-1:0][ADDR_WIDTH -1:0]      i_mst_paddr,
  input  logic [MASTER_NUM-1:0]                       i_mst_pwrite,
  input  logic [MASTER_NUM-1:0][DATA_WIDTH -1:0]      i_mst_pwdata,
  input  logic [MASTER_NUM-1:0][DATA_STRB_WIDTH -1:0] i_mst_pstrb,
  output logic [MASTER_NUM-1:0][DATA_WIDTH -1:0]      o_mst_prdata,
  output logic [MASTER_NUM-1:0]                       o_mst_pready,
  output logic [MASTER_NUM-1:0]                       o_mst_pslverr,

  //APB slave interface
  output logic                        o_slv_psel,
  output logic                        o_slv_penable,
  output logic [ADDR_WIDTH -1:0]      o_slv_paddr,
  output logic                        o_slv_pwrite,
  output logic [DATA_WIDTH -1:0]      o_slv_pwdata,
  output logic [DATA_STRB_WIDTH -1:0] o_slv_pstrb,
  input  logic [DATA_WIDTH -1:0]      i_slv_prdata,
  input  logic                        i_slv_pready,
  input  logic                        i_slv_pslverr
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
  assign mst_psel    = {i_test_psel,    i_mst_psel   };
  assign mst_penable = {i_test_penable, i_mst_penable};
  assign mst_paddr   = {i_test_paddr,   i_mst_paddr  };
  assign mst_pwrite  = {i_test_pwrite,  i_mst_pwrite };
  assign mst_pwdata  = {i_test_pwdata,  i_mst_pwdata };
  assign mst_pstrb   = {i_test_pstrb,   i_mst_pstrb  };
  assign {o_test_prdata,  o_mst_prdata } = mst_prdata ;
  assign {o_test_pready,  o_mst_pready } = mst_pready ;
  assign {o_test_pslverr, o_mst_pslverr} = mst_pslverr;
`else
  // else we have only master ports used
  assign mst_psel    = i_mst_psel   ;
  assign mst_penable = i_mst_penable;
  assign mst_paddr   = i_mst_paddr  ;
  assign mst_pwrite  = i_mst_pwrite ;
  assign mst_pwdata  = i_mst_pwdata ;
  assign mst_pstrb   = i_mst_pstrb  ;
  assign o_mst_prdata  = mst_prdata ;
  assign o_mst_pready  = mst_pready ;
  assign o_mst_pslverr = mst_pslverr;
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
  always_ff @(posedge i_clk) begin : mst_stage
    if (~i_reset_n) begin
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
    .i_clk        (i_clk),
    .i_reset_n    (i_reset_n),
    .i_flush      (1'b0),
    .i_rr_priority({$clog2(MASTER_SUM_NUM){1'b0}}),
    .i_request    (mst_req_r),
    .o_grant      (),
    .i_data       ({MASTER_SUM_NUM{1'b0}}),
    .o_request    (mst_sel_request),
    .i_grant      (update_arb),
    .o_data       (),
    .o_index      (mst_sel_index)
  );

  always_comb begin
    mst_sel_arb = 'd0;
    if (mst_sel_request) mst_sel_arb[mst_sel_index] = 1'b1;
  end

  // APB state machine for slave interface
  always_ff @(posedge i_clk) begin : apb_fsm_ff
    if (~i_reset_n) begin
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
        if (i_slv_pready) begin
          for (int i = 0; i < MASTER_SUM_NUM; i++) begin
            if (mst_sel_arb[i] == 1'b1) begin  // one hot array
              mst_prdata_nxt[i] = i_slv_prdata;
              mst_pready_nxt[i] = 1'b1;
              mst_pslverr_nxt[i] = i_slv_pslverr;
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

  assign o_slv_psel    = slv_psel_r;
  assign o_slv_penable = slv_penable_r;
  assign o_slv_paddr   = slv_paddr_r;
  assign o_slv_pwrite  = slv_pwrite_r;
  assign o_slv_pwdata  = slv_pwdata_r;
  assign o_slv_pstrb   = slv_pstrb_r;

  assign mst_prdata  = mst_prdata_r;
  assign mst_pready  = mst_pready_r;
  assign mst_pslverr = mst_pslverr_r;

endmodule
