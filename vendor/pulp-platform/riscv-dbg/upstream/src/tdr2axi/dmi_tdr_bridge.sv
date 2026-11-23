// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// SPDX-License-Identifier: Apache-2.0
//
// Description:
//   DMI requester driven by a 41-bit TDR of an external TAP or IEEE 1687 (IJTAG)
//   network, in the TCK domain.
//
//   TDR layout (standard RISC-V DTM dmi register):
//     [40:34] address | [33:2] data | [1:0] op       (op: 0 NOP, 1 read, 2 write, 3 clear)
//   Capture image driven onto TDR_in:
//     [40:34] address | [33:2] data | [1:0] status   (status: 0 ok, 2 failed, 3 busy)
//
//   This is riscv-dbg dmi_jtag (DMI part) + dmi_cdc, kept as close to upstream as the
//   TDR allows, so the two can be compared block by block:
//   - TCK FSM (p_fsm): the dmi_jtag state machine, states, error rules and read-data
//     markers unchanged: IDLE -> READ/WRITE (request offered) -> WAIT_READ_VALID/
//     WAIT_WRITE_VALID (response awaited) -> IDLE. error_q is the sticky status:
//     busy on an Update-DR outside IDLE, on a Capture-DR in READ/WAIT_READ_VALID, or on
//     a busy DMI response; failed on an error DMI response; the first one wins, failed
//     winning a tie, and op 3 clears it last.
//   - TDR_in (p_shift capture): {address_q, data_q, status}, status ok only if error_q
//     and both flags of the capture cycle are clear, else failed if either says failed,
//     else busy.
//   - CDC (dmi_cdc): one cdc_2phase_clearable carries dmi_req_t TCK -> i_clk, a second
//     carries dmi_resp_t i_clk -> TCK, valid/ready on both sides, as upstream.
//
//   Reset rules:
//   - TRST does not reset the bridge. The TDR and its update/capture strobes are
//     sampled on TCK; TLR is synchronous to TCK, and TRST is asserted and released only
//     while TCK is stopped, so no TCK edge sees a TRST change. An op in flight when TRST
//     asserts completes normally; op 3 clears the DMI error.
//   - dm_csrs.dmi_rst_ni is tied off. At most one op is in flight and the response side
//     is always ready, so dm_csrs never holds a stale response: a response to an op cut
//     off by a reset arrives a few i_clk cycles after the request, long before a new op
//     can cross from TCK, and the FSM drops any response that arrives outside WAIT_*.
//
//   CDC and timing rules:
//   - Both crossings are handshakes, so correctness does not depend on the i_clk / TCK
//     ratio. TCK only runs during scans, so a response reaches TDR_in a few TCK cycles
//     after the DM gives it: a scan that captures while a read is still pending, or
//     updates while any op is pending, sets sticky busy and needs op 3. Run-Test/Idle
//     cycles after the op scan avoid this (dtmcs.idle upstream).
//   - i_dmi_tdr_capture must be high for the TCK rising edge at which the TDR cell
//     loads TDR_in (CaptureEn & select), so the busy decision and the captured status
//     come from the same edge.
//   - The op field of i_dmi_tdr must be valid at the TCK rising edge that samples TDR_upd
//     (the update stage loads on the falling edge inside Update-DR).
//   - i_arst_n and i_arst_tck_n are the same reset, asserted together (asynchronously)
//     and each released synchronously to its own clock.
//   - The TCK side leaves reset SYNC_STAGES TCK cycles after release; the scans that
//     open the IJTAG path provide them before the first Update-DR of this TDR.
//   - TRST is asserted and released only while TCK is stopped.

module dmi_tdr_bridge #(
    parameter int unsigned SYNC_STAGES = 3  // CDC synchroniser depth
) (
    input logic i_clk,
    input logic i_arst_n,

    // DMI TDR (TCK domain)
    input  logic        i_tck,
    input  logic        i_arst_tck_n,
    input  logic [40:0] i_dmi_tdr,
    input  logic        i_dmi_tdr_capture,
    input  logic        i_dmi_tdr_update,
    output logic [40:0] o_dmi_tdr,

    // DMI requester (i_clk domain)
    output dm::dmi_req_t  o_dmi_req,
    output logic          o_dmi_req_valid,
    input  logic          i_dmi_req_ready,
    input  dm::dmi_resp_t i_dmi_resp,
    input  logic          i_dmi_resp_valid,
    output logic          o_dmi_resp_ready
);

  localparam logic [1:0] OpClear = 2'd3;
  // Read data returned for a non-success DMI response (dmi_jtag markers)
  localparam logic [31:0] DataFailed = 32'hDEAD_BEEF;
  localparam logic [31:0] DataBusy = 32'hB051_B051;
  localparam logic [31:0] DataRsvd = 32'hBAAD_C0DE;

  // dmi_jtag dmi_error_e
  typedef enum logic [1:0] {
    DMI_NO_ERROR       = 2'h0,
    DMI_RESERVED_ERROR = 2'h1,
    DMI_OP_FAILED      = 2'h2,
    DMI_BUSY           = 2'h3
  } dmi_error_e;

  // dmi_jtag state_e
  typedef enum logic [2:0] {
    IDLE,
    READ,
    WAIT_READ_VALID,
    WRITE,
    WAIT_WRITE_VALID
  } state_e;

  // dmi_jtag dmi_t: the TDR fields
  typedef struct packed {
    logic [6:0]  address;
    logic [31:0] data;
    logic [1:0]  op;
  } dmi_t;

  // ---------------------------------------------------------------------------
  // TCK: DMI FSM (dmi_jtag p_fsm)
  // ---------------------------------------------------------------------------
  dmi_error_e           error_d;
  dmi_error_e           error_q;
  state_e               state_d;
  state_e               state_q;
  logic          [ 6:0] address_d;
  logic          [ 6:0] address_q;
  logic          [31:0] data_d;
  logic          [31:0] data_q;
  dmi_t                 dmi;
  dm::dmi_req_t         dmi_req;
  logic                 dmi_req_valid;
  logic                 dmi_req_ready;
  dm::dmi_resp_t        dmi_resp;
  logic                 dmi_resp_valid;
  logic                 error_dmi_busy;
  logic                 error_dmi_op_failed;
  logic                 dmi_clear_err;

  assign dmi           = dmi_t'(i_dmi_tdr);
  assign dmi_req.addr  = address_q;
  assign dmi_req.data  = data_q;
  assign dmi_req.op    = (state_q == WRITE) ? dm::DTM_WRITE : dm::DTM_READ;
  assign dmi_clear_err = i_dmi_tdr_update && (dmi.op == OpClear);

  always_comb begin : p_fsm
    error_dmi_busy      = 1'b0;
    error_dmi_op_failed = 1'b0;
    state_d             = state_q;
    address_d           = address_q;
    data_d              = data_q;
    error_d             = error_q;
    dmi_req_valid       = 1'b0;

    unique case (state_q)
      IDLE: begin
        // make sure that no error is sticky
        if (i_dmi_tdr_update && (error_q == DMI_NO_ERROR)) begin
          address_d = dmi.address;
          data_d    = dmi.data;
          if (dm::dtm_op_e'(dmi.op) == dm::DTM_READ) begin
            state_d = READ;
          end else if (dm::dtm_op_e'(dmi.op) == dm::DTM_WRITE) begin
            state_d = WRITE;
          end
          // else NOP (or op 3): stay here
        end
      end

      READ: begin
        dmi_req_valid = 1'b1;
        if (dmi_req_ready) begin
          state_d = WAIT_READ_VALID;
        end
      end

      WAIT_READ_VALID: begin
        if (dmi_resp_valid) begin
          unique case (dmi_resp.resp)
            dm::DTM_SUCCESS: begin
              data_d = dmi_resp.data;
            end
            dm::DTM_ERR: begin
              data_d              = DataFailed;
              error_dmi_op_failed = 1'b1;
            end
            dm::DTM_BUSY: begin
              data_d         = DataBusy;
              error_dmi_busy = 1'b1;
            end
            default: begin
              data_d = DataRsvd;
            end
          endcase
          state_d = IDLE;
        end
      end

      WRITE: begin
        dmi_req_valid = 1'b1;
        if (dmi_req_ready) begin
          state_d = WAIT_WRITE_VALID;
        end
      end

      WAIT_WRITE_VALID: begin
        if (dmi_resp_valid) begin
          unique case (dmi_resp.resp)
            dm::DTM_ERR: begin
              error_dmi_op_failed = 1'b1;
            end
            dm::DTM_BUSY: begin
              error_dmi_busy = 1'b1;
            end
            default: begin
              error_dmi_op_failed = 1'b0;
              error_dmi_busy      = 1'b0;
            end
          endcase
          state_d = IDLE;
        end
      end

      default: begin
        if (dmi_resp_valid) begin
          state_d = IDLE;
        end
      end
    endcase

    // update means we got another request but we didn't finish the one in progress
    if (i_dmi_tdr_update && (state_q != IDLE)) begin
      error_dmi_busy = 1'b1;
    end

    // capture while a read is in flight does not give back a valid word
    if (i_dmi_tdr_capture && (state_q inside {READ, WAIT_READ_VALID})) begin
      error_dmi_busy = 1'b1;
    end

    if (error_dmi_busy && (error_q == DMI_NO_ERROR)) begin
      error_d = DMI_BUSY;
    end

    if (error_dmi_op_failed && (error_q == DMI_NO_ERROR)) begin
      error_d = DMI_OP_FAILED;
    end

    // clear sticky error flag
    if (dmi_clear_err) begin
      error_d = DMI_NO_ERROR;
    end
  end

  always_ff @(posedge i_tck or negedge i_arst_tck_n) begin
    if (!i_arst_tck_n) begin
      state_q   <= IDLE;
      address_q <= '0;
      data_q    <= '0;
      error_q   <= DMI_NO_ERROR;
    end else begin
      state_q   <= state_d;
      address_q <= address_d;
      data_q    <= data_d;
      error_q   <= error_d;
    end
  end

  // ---------------------------------------------------------------------------
  // TCK: TDR_in (dmi_jtag p_shift, capture branch)
  // ---------------------------------------------------------------------------
  dmi_error_e tdr_status;

  always_comb begin
    if ((error_q == DMI_NO_ERROR) && !error_dmi_busy && !error_dmi_op_failed) begin
      tdr_status = DMI_NO_ERROR;
    end else if ((error_q == DMI_OP_FAILED) || error_dmi_op_failed) begin
      tdr_status = DMI_OP_FAILED;
    end else begin
      tdr_status = DMI_BUSY;
    end
  end

  assign o_dmi_tdr = {address_q, data_q, tdr_status};

  // ---------------------------------------------------------------------------
  // CDC (dmi_cdc): request TCK -> i_clk, response i_clk -> TCK
  // ---------------------------------------------------------------------------
  cdc_2phase_clearable #(
      .T          (dm::dmi_req_t),
      .SYNC_STAGES(SYNC_STAGES)
  ) u_cdc_req (
      .src_rst_ni         (i_arst_tck_n),
      .src_clk_i          (i_tck),
      .src_clear_i        (1'b0),
      .src_clear_pending_o(),
      .src_data_i         (dmi_req),
      .src_valid_i        (dmi_req_valid),
      .src_ready_o        (dmi_req_ready),
      .dst_rst_ni         (i_arst_n),
      .dst_clk_i          (i_clk),
      .dst_clear_i        (1'b0),
      .dst_clear_pending_o(),
      .dst_data_o         (o_dmi_req),
      .dst_valid_o        (o_dmi_req_valid),
      .dst_ready_i        (i_dmi_req_ready)
  );

  // TCK is always ready for the response it asked for (dmi_jtag dmi_resp_ready = 1)
  cdc_2phase_clearable #(
      .T          (dm::dmi_resp_t),
      .SYNC_STAGES(SYNC_STAGES)
  ) u_cdc_resp (
      .src_rst_ni         (i_arst_n),
      .src_clk_i          (i_clk),
      .src_clear_i        (1'b0),
      .src_clear_pending_o(),
      .src_data_i         (i_dmi_resp),
      .src_valid_i        (i_dmi_resp_valid),
      .src_ready_o        (o_dmi_resp_ready),
      .dst_rst_ni         (i_arst_tck_n),
      .dst_clk_i          (i_tck),
      .dst_clear_i        (1'b0),
      .dst_clear_pending_o(),
      .dst_data_o         (dmi_resp),
      .dst_valid_o        (dmi_resp_valid),
      .dst_ready_i        (1'b1)
  );

endmodule
