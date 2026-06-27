// SPDX-License-Identifier: Apache-2.0
//
// APB4 to Passthrough CSR Interface Adapter
// Standalone adapter - no Caliptra dependency
//

module apb_adapter
  import I3CCSR_pkg::I3CCSR_DATA_WIDTH;
  import I3CCSR_pkg::I3CCSR_MIN_ADDR_WIDTH;
#(
    localparam int unsigned CsrAddrWidth = I3CCSR_MIN_ADDR_WIDTH,
    localparam int unsigned CsrDataWidth = I3CCSR_DATA_WIDTH,

    parameter int unsigned ApbDataWidth = 32,
    parameter int unsigned ApbAddrWidth = 32
) (
    input  logic                       clk_i,
    input  logic                       rst_ni,

    // APB4 Slave Interface
    input  logic                       psel_i,
    input  logic                       penable_i,
    input  logic                       pwrite_i,
    input  logic [ApbAddrWidth-1:0]    paddr_i,
    input  logic [ApbDataWidth-1:0]    pwdata_i,
    input  logic [ApbDataWidth/8-1:0]  pstrb_i,
    output logic [ApbDataWidth-1:0]    prdata_o,
    output logic                       pready_o,
    output logic                       pslverr_o,

    // Passthrough CSR Interface (to I3CCSR)
    output logic                       s_cpuif_req,
    output logic                       s_cpuif_req_is_wr,
    output logic [CsrAddrWidth-1:0]    s_cpuif_addr,
    output logic [CsrDataWidth-1:0]    s_cpuif_wr_data,
    output logic [CsrDataWidth-1:0]    s_cpuif_wr_biten,
    input  logic                       s_cpuif_req_stall_wr,
    input  logic                       s_cpuif_req_stall_rd,
    input  logic                       s_cpuif_rd_ack,
    input  logic                       s_cpuif_rd_err,
    input  logic [CsrDataWidth-1:0]    s_cpuif_rd_data,
    input  logic                       s_cpuif_wr_ack,
    input  logic                       s_cpuif_wr_err
);

  // Check configuration
  initial begin : apb_param_check
    if (!(ApbAddrWidth >= 10 && ApbAddrWidth <= 64)) begin
      $error("ERROR: Violated requirement: 10 <= ApbAddrWidth <= 64 (instance %m)");
      $finish;
    end
    if (!(ApbDataWidth == 32)) begin
      $error("ERROR: ApbDataWidth must be 32 for I3C CSR (instance %m)");
      $finish;
    end
  end

  // APB state machine states
  typedef enum logic [1:0] {
    IDLE,
    SETUP,
    ACCESS,
    WAIT_ACK
  } apb_state_e;

  apb_state_e state_q, state_d;

  // Internal signals
  logic cpuif_req_stall;
  logic cpuif_ack;
  logic cpuif_err;
  logic req_pending_q;

  // Stall and ack signals
  assign cpuif_req_stall = pwrite_i ? s_cpuif_req_stall_wr : s_cpuif_req_stall_rd;
  assign cpuif_ack = s_cpuif_wr_ack | s_cpuif_rd_ack;
  assign cpuif_err = s_cpuif_wr_err | s_cpuif_rd_err;

  // Convert pstrb to bit-enable (expand each strobe bit to 8 data bits)
  logic [CsrDataWidth-1:0] wr_biten;
  always_comb begin
    for (int i = 0; i < ApbDataWidth/8; i++) begin
      wr_biten[i*8 +: 8] = pstrb_i[i] ? 8'hFF : 8'h00;
    end
  end

  // State machine
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= IDLE;
      req_pending_q <= 1'b0;
    end else begin
      state_q <= state_d;
      req_pending_q <= (state_d == ACCESS || state_d == WAIT_ACK) && !cpuif_ack;
    end
  end

  // Next state logic
  always_comb begin
    state_d = state_q;

    case (state_q)
      IDLE: begin
        if (psel_i && !penable_i) begin
          state_d = SETUP;
        end
      end

      SETUP: begin
        if (psel_i && penable_i) begin
          if (cpuif_req_stall) begin
            state_d = WAIT_ACK;
          end else begin
            state_d = ACCESS;
          end
        end else if (!psel_i) begin
          state_d = IDLE;
        end
      end

      ACCESS: begin
        if (cpuif_ack) begin
          if (psel_i && !penable_i) begin
            state_d = SETUP;  // Back-to-back transaction
          end else begin
            state_d = IDLE;
          end
        end else begin
          state_d = WAIT_ACK;
        end
      end

      WAIT_ACK: begin
        if (cpuif_ack) begin
          if (psel_i && !penable_i) begin
            state_d = SETUP;  // Back-to-back transaction
          end else begin
            state_d = IDLE;
          end
        end
      end

      default: state_d = IDLE;
    endcase
  end

  // Output logic
  always_comb begin
    // Default outputs
    s_cpuif_req = 1'b0;
    s_cpuif_req_is_wr = pwrite_i;
    s_cpuif_addr = paddr_i[CsrAddrWidth-1:0];
    s_cpuif_wr_data = pwdata_i;
    s_cpuif_wr_biten = wr_biten;
    pready_o = 1'b0;
    pslverr_o = 1'b0;
    prdata_o = s_cpuif_rd_data;

    case (state_q)
      IDLE: begin
        // No active transaction
      end

      SETUP: begin
        // Setup phase - prepare request
        if (psel_i && penable_i) begin
          s_cpuif_req = 1'b1;
        end
      end

      ACCESS: begin
        // Access phase - request active, waiting for ack
        s_cpuif_req = !req_pending_q;  // Only assert on first cycle
        if (cpuif_ack) begin
          pready_o = 1'b1;
          pslverr_o = cpuif_err;
        end
      end

      WAIT_ACK: begin
        // Waiting for CSR to acknowledge
        if (cpuif_ack) begin
          pready_o = 1'b1;
          pslverr_o = cpuif_err;
        end
      end

      default: ;
    endcase
  end

endmodule
