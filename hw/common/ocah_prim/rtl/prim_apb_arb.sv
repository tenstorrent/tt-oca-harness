// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Arbitrate MASTER_NUM APB masters onto one slave port.
//
// Register every master's request, pick one with a fair round-robin prim_fair_rr_arb, and
// replay it on the registered slave port; forward every address without decoding.
// When SIM_APB_ARB is defined, splice a test master in at the highest index.
// Grant one master at a time and steer the slave response back to that master through a
// register stage. Mask the master just served for one cycle after its response so its
// still-asserted PSEL and PENABLE do not start a second transfer.

module prim_apb_arb #(
  parameter int unsigned ADDR_WIDTH = 32,  // APB address width.
  parameter int unsigned DATA_WIDTH = 32,  // APB data width.
  parameter int unsigned MASTER_NUM = 8,  // Number of APB master ports.
  parameter bit [31:0] SLAVE_ADDR_START = 32'h0000,  // Declared but unused; no address decoding.
  parameter bit [31:0] SLAVE_ADDR_END = 32'h1000,  // Declared but unused; addresses reach
                                                   // the slave port unchecked.
  localparam int unsigned DATA_STRB_WIDTH = DATA_WIDTH / 8  // Write-strobe width from DATA_WIDTH.
) (
  input logic clk_i,  // APB clock.
  input logic rst_ni,  // Active-low reset, sampled synchronously; clears requests and
                       // controls, while datapath registers are not reset.

`ifdef SIM_APB_ARB
  input  logic                        test_psel_i,  // SIM test-master PSEL.
  input  logic                        test_penable_i,  // SIM test-master PENABLE.
  input  logic [ADDR_WIDTH -1:0]      test_paddr_i,  // SIM test-master PADDR.
  input  logic                        test_pwrite_i,  // SIM test-master PWRITE.
  input  logic [DATA_WIDTH -1:0]      test_pwdata_i,  // SIM test-master PWDATA.
  input  logic [DATA_STRB_WIDTH -1:0] test_pstrb_i,  // SIM test-master PSTRB.
  output logic [DATA_WIDTH -1:0]      test_prdata_o,  // SIM test-master PRDATA.
  output logic                        test_pready_o,  // SIM test-master PREADY.
  output logic                        test_pslverr_o,  // SIM test-master PSLVERR.
`endif

  input  logic [MASTER_NUM-1:0]                       mst_psel_i,  // APB master PSELs.
  input  logic [MASTER_NUM-1:0]                       mst_penable_i,  // APB master PENABLEs; a master requests once its PSEL
                                                                      // and PENABLE are both high.
  input  logic [MASTER_NUM-1:0][ADDR_WIDTH -1:0]      mst_paddr_i,  // APB master PADDRs.
  input  logic [MASTER_NUM-1:0]                       mst_pwrite_i,  // APB master PWRITEs.
  input  logic [MASTER_NUM-1:0][DATA_WIDTH -1:0]      mst_pwdata_i,  // APB master PWDATAs.
  input  logic [MASTER_NUM-1:0][DATA_STRB_WIDTH -1:0] mst_pstrb_i,  // APB master PSTRBs.
  output logic [MASTER_NUM-1:0][DATA_WIDTH -1:0]      mst_prdata_o,  // APB master PRDATAs.
  output logic [MASTER_NUM-1:0]                       mst_pready_o,  // APB master PREADYs.
  output logic [MASTER_NUM-1:0]                       mst_pslverr_o,  // APB master PSLVERRs.

  output logic                        slv_psel_o,  // APB slave PSEL.
  output logic                        slv_penable_o,  // APB slave PENABLE.
  output logic [ADDR_WIDTH -1:0]      slv_paddr_o,  // APB slave PADDR.
  output logic                        slv_pwrite_o,  // APB slave PWRITE.
  output logic [DATA_WIDTH -1:0]      slv_pwdata_o,  // APB slave PWDATA.
  output logic [DATA_STRB_WIDTH -1:0] slv_pstrb_o,  // APB slave PSTRB.
  input  logic [DATA_WIDTH -1:0]      slv_prdata_i,  // APB slave PRDATA.
  input  logic                        slv_pready_i,  // APB slave PREADY.
  input  logic                        slv_pslverr_i  // APB slave PSLVERR.
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
  } apb_state_e;
  apb_state_e apb_state_r, apb_state_nxt;

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
    .NUM_IN(MASTER_SUM_NUM),
    .DATA_WIDTH(0),
    .data_t(logic),
    .EXT_PRIO(1'b0),
    .AXI_VLD_RDY(1'b1),
    .LOCK_IN(1'b1),
    .FAIR_ARB(1'b1)
  ) u_apb_arb (
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
