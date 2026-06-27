// SPDX-License-Identifier: Apache-2.0
//
// AXI4-Lite to Passthrough CSR Interface Adapter
// Standalone adapter - no Caliptra dependency
//

module axi_lite_adapter
  import I3CCSR_pkg::I3CCSR_DATA_WIDTH;
  import I3CCSR_pkg::I3CCSR_MIN_ADDR_WIDTH;
#(
    localparam int unsigned CsrAddrWidth = I3CCSR_MIN_ADDR_WIDTH,
    localparam int unsigned CsrDataWidth = I3CCSR_DATA_WIDTH,

    parameter int unsigned AxiLiteDataWidth = 32,
    parameter int unsigned AxiLiteAddrWidth = 32
) (
    input  logic                           clk_i,
    input  logic                           rst_ni,

    // AXI4-Lite Slave Interface
    // Write Address Channel
    input  logic                           awvalid_i,
    output logic                           awready_o,
    input  logic [AxiLiteAddrWidth-1:0]    awaddr_i,
    input  logic [2:0]                     awprot_i,

    // Write Data Channel
    input  logic                           wvalid_i,
    output logic                           wready_o,
    input  logic [AxiLiteDataWidth-1:0]    wdata_i,
    input  logic [AxiLiteDataWidth/8-1:0]  wstrb_i,

    // Write Response Channel
    output logic                           bvalid_o,
    input  logic                           bready_i,
    output logic [1:0]                     bresp_o,

    // Read Address Channel
    input  logic                           arvalid_i,
    output logic                           arready_o,
    input  logic [AxiLiteAddrWidth-1:0]    araddr_i,
    input  logic [2:0]                     arprot_i,

    // Read Data Channel
    output logic                           rvalid_o,
    input  logic                           rready_i,
    output logic [AxiLiteDataWidth-1:0]    rdata_o,
    output logic [1:0]                     rresp_o,

    // Passthrough CSR Interface (to I3CCSR)
    output logic                           s_cpuif_req,
    output logic                           s_cpuif_req_is_wr,
    output logic [CsrAddrWidth-1:0]        s_cpuif_addr,
    output logic [CsrDataWidth-1:0]        s_cpuif_wr_data,
    output logic [CsrDataWidth-1:0]        s_cpuif_wr_biten,
    input  logic                           s_cpuif_req_stall_wr,
    input  logic                           s_cpuif_req_stall_rd,
    input  logic                           s_cpuif_rd_ack,
    input  logic                           s_cpuif_rd_err,
    input  logic [CsrDataWidth-1:0]        s_cpuif_rd_data,
    input  logic                           s_cpuif_wr_ack,
    input  logic                           s_cpuif_wr_err
);

  // Check configuration
  initial begin : axilite_param_check
    if (!(AxiLiteAddrWidth >= 10 && AxiLiteAddrWidth <= 64)) begin
      $error("ERROR: Violated requirement: 10 <= AxiLiteAddrWidth <= 64 (instance %m)");
      $finish;
    end
    if (!(AxiLiteDataWidth == 32)) begin
      $error("ERROR: AxiLiteDataWidth must be 32 for I3C CSR (instance %m)");
      $finish;
    end
  end

  // AXI-Lite response codes
  localparam logic [1:0] RESP_OKAY   = 2'b00;
  localparam logic [1:0] RESP_SLVERR = 2'b10;

  // State machine states
  typedef enum logic [2:0] {
    IDLE,
    WRITE_WAIT_DATA,    // Got AW, waiting for W
    WRITE_WAIT_ADDR,    // Got W, waiting for AW
    WRITE_REQ,          // Both AW and W received, issue request
    WRITE_RESP,         // Waiting to send B response
    READ_REQ,           // AR received, issue request
    READ_RESP           // Waiting to send R response
  } state_e;

  state_e state_q, state_d;

  // Registered address/data for write transactions
  logic [AxiLiteAddrWidth-1:0] awaddr_q;
  logic [AxiLiteDataWidth-1:0] wdata_q;
  logic [AxiLiteDataWidth/8-1:0] wstrb_q;
  logic [AxiLiteAddrWidth-1:0] araddr_q;

  // Response registers
  logic [1:0] bresp_q;
  logic [CsrDataWidth-1:0] rdata_q;
  logic [1:0] rresp_q;

  // Convert wstrb to bit-enable
  logic [CsrDataWidth-1:0] wr_biten;
  always_comb begin
    for (int i = 0; i < AxiLiteDataWidth/8; i++) begin
      wr_biten[i*8 +: 8] = wstrb_q[i] ? 8'hFF : 8'h00;
    end
  end

  // State machine
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      awaddr_q <= '0;
      wdata_q <= '0;
      wstrb_q <= '0;
      araddr_q <= '0;
      bresp_q <= RESP_OKAY;
      rdata_q <= '0;
      rresp_q <= RESP_OKAY;
    end else begin
      state_q <= state_d;

      // Capture write address
      if (awvalid_i && awready_o) begin
        awaddr_q <= awaddr_i;
      end

      // Capture write data
      if (wvalid_i && wready_o) begin
        wdata_q <= wdata_i;
        wstrb_q <= wstrb_i;
      end

      // Capture read address
      if (arvalid_i && arready_o) begin
        araddr_q <= araddr_i;
      end

      // Capture write response
      if (s_cpuif_wr_ack) begin
        bresp_q <= s_cpuif_wr_err ? RESP_SLVERR : RESP_OKAY;
      end

      // Capture read response
      if (s_cpuif_rd_ack) begin
        rdata_q <= s_cpuif_rd_data;
        rresp_q <= s_cpuif_rd_err ? RESP_SLVERR : RESP_OKAY;
      end
    end
  end

  // Next state and output logic
  always_comb begin
    // Default next state
    state_d = state_q;

    // Default outputs - deasserted
    awready_o = 1'b0;
    wready_o = 1'b0;
    bvalid_o = 1'b0;
    bresp_o = bresp_q;
    arready_o = 1'b0;
    rvalid_o = 1'b0;
    rdata_o = rdata_q;
    rresp_o = rresp_q;

    s_cpuif_req = 1'b0;
    s_cpuif_req_is_wr = 1'b0;
    s_cpuif_addr = '0;
    s_cpuif_wr_data = wdata_q;
    s_cpuif_wr_biten = wr_biten;

    case (state_q)
      IDLE: begin
        // Accept write address
        awready_o = 1'b1;
        // Accept write data
        wready_o = 1'b1;
        // Accept read address (prioritize reads if simultaneous)
        arready_o = 1'b1;

        // Determine next state based on what arrives
        if (arvalid_i) begin
          // Read request
          state_d = READ_REQ;
        end else if (awvalid_i && wvalid_i) begin
          // Both write address and data arrived together
          state_d = WRITE_REQ;
        end else if (awvalid_i) begin
          // Only write address arrived
          state_d = WRITE_WAIT_DATA;
        end else if (wvalid_i) begin
          // Only write data arrived
          state_d = WRITE_WAIT_ADDR;
        end
      end

      WRITE_WAIT_DATA: begin
        // Waiting for write data, accept it
        wready_o = 1'b1;
        if (wvalid_i) begin
          state_d = WRITE_REQ;
        end
      end

      WRITE_WAIT_ADDR: begin
        // Waiting for write address, accept it
        awready_o = 1'b1;
        if (awvalid_i) begin
          state_d = WRITE_REQ;
        end
      end

      WRITE_REQ: begin
        // Issue write request to CSR
        s_cpuif_req = 1'b1;
        s_cpuif_req_is_wr = 1'b1;
        s_cpuif_addr = awaddr_q[CsrAddrWidth-1:0];

        if (s_cpuif_wr_ack) begin
          state_d = WRITE_RESP;
        end else if (!s_cpuif_req_stall_wr) begin
          // Request accepted, wait for ack
          state_d = WRITE_RESP;
        end
      end

      WRITE_RESP: begin
        // Wait for write ack if not received yet
        if (!s_cpuif_wr_ack && !bresp_q[1]) begin
          // Still waiting for ack
          s_cpuif_req = 1'b0;
        end

        // Send write response
        bvalid_o = 1'b1;
        bresp_o = bresp_q;
        if (bready_i) begin
          state_d = IDLE;
        end
      end

      READ_REQ: begin
        // Issue read request to CSR
        s_cpuif_req = 1'b1;
        s_cpuif_req_is_wr = 1'b0;
        s_cpuif_addr = araddr_q[CsrAddrWidth-1:0];

        if (s_cpuif_rd_ack) begin
          state_d = READ_RESP;
        end 

        /* 
         * if s_cpuif_req_stall_rd is 1, then do NOT transition to READ_RESP.
         * Yes, s_cpuif_req will be 1 for multiple cycles, but in I3CCSR.sv if s_cpuif_req_stall_rd is 1,
         * then it masks off the request, so it won't issue multiple reads!
        */

      end

      READ_RESP: begin        
        // Send read response
        rvalid_o = 1'b1;
        rdata_o = rdata_q;
        rresp_o = rresp_q;

        if (rready_i) begin
          state_d = IDLE;
        end
      end

      default: state_d = IDLE;
    endcase
  end

endmodule
