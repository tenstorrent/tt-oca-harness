// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Read fuse words through the fuse-command interface with timeouts and sticky errors.
//
// read_go_i starts a read from read_addr_i; read_back_data_o captures the response.
// read_addr_oob_i is computed upstream against the full-width CSR field because casting
// to efuse_addr_t truncates upper bits.
// Honors secure_tm_blocked_i, efuse_req_err_i, and optional read_req_timeout_*; sticky
// address errors clear with read_addr_error_clear_i.
// is_reading_o and read_target_addr_o feed the guard while a read is active.

`include "prim_assert.sv"

module efuse_read_interface #(
  parameter type efuse_addr_t = logic,  // Fuse bit-address type.
  parameter type efuse_word_counter_t = logic,  // Fuse access-length counter type.
  parameter type fuse_command_req_t = logic,  // Fuse-command request type.
  parameter type fuse_command_resp_t = logic,  // Fuse-command response type.
  parameter type efuse_data_t = logic   // Fuse data-word type.
) (
  input logic clk_i,                    // System clock.
  input logic rst_ni,                   // Active-low asynchronous reset.
  input logic test_en_i,                // DFT test enable; not used in this module.

  input  logic        read_enable_i,    // Read operations allowed; a start while low completes
                                        // immediately with an error.
  output logic        is_reading_o,     // High while a read command is outstanding, for the guard.
  output efuse_addr_t read_target_addr_o,  // Fuse bit address of the outstanding read command; zero
                                           // when idle.

  input  efuse_addr_t read_addr_i,      // Fuse bit address to read, sampled on a start.
  input  logic        read_go_i,        // Starts a read operation when high in the idle state.
  output logic        read_busy_o,      // High while a read operation waits for its response.
  output logic        read_done_o,      // Set when the last read operation completed; cleared by
                                        // the next start.
  output logic        read_error_o,     // Set when the last read operation failed: rejected,
                                        // blocked, errored by the bank, or timed out.
  output efuse_data_t read_back_data_o,  // Data word from the last read; zero after an
                                         // out-of-bounds, blocked, errored or timed-out read, and
                                         // unchanged when a start is rejected because read_enable_i
                                         // is low.

  input  logic read_addr_oob_i,         // High when the full-width CSR read address is beyond the
                                        // fuse array; a start is then rejected.
  output logic read_addr_error_o,       // Sticky out-of-bounds read address error.
  input  logic read_addr_error_clear_i,  // Clears the sticky address error; a same-cycle new error
                                         // takes priority.

  input logic efuse_req_err_i,          // Guard lock error; ends an outstanding read with an error.
  input logic secure_tm_blocked_i,      // Guard secure-test-mode block; ends an outstanding read
                                        // with an error.

  input logic        read_req_timeout_en_i,  // Enables the response timeout for read operations.
  input logic [27:0] read_req_timeout_cycles_i,  // Response timeout in clock cycles.

  output fuse_command_req_t  fuse_command_req_o,  // Read command to the guard; valid only while
                                                  // waiting for the response.
  input  fuse_command_resp_t fuse_command_resp_i,  // Filtered response to the read command.

  output logic is_read_timeout_debug_o  // One-cycle pulse when a read operation times out.
);

  localparam fuse_command_req_t FUSE_COMMAND_REQ_DEFAULT = '0;
  localparam fuse_command_resp_t FUSE_COMMAND_RESP_DEFAULT = '0;
  localparam efuse_data_t EFUSE_READ_ERROR_DATA = efuse_data_t'('hbadcab1e);

  // Timeout logic
  logic [27:0] timeout_count_q, timeout_count_d;
  logic read_timeout_event;

  fuse_command_req_t fuse_command_req_d, fuse_command_req_q;

  efuse_addr_t captured_read_addr;

  // Program execution state machine
  typedef enum logic [1:0] {
    ST_READ_IDLE = 2'b01,
    ST_WAIT_RESP = 2'b10
  } efuse_read_state_e;


  efuse_read_state_e read_state_q, read_state_d;
  assign is_reading_o = (read_state_q == ST_READ_IDLE) ? 1'b0 : 1'b1;
  assign read_target_addr_o = (read_state_q == ST_READ_IDLE) ? efuse_addr_t'(0) : captured_read_addr;

  // Capture read address when idle
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      captured_read_addr <= 'd0;
    end else if (read_state_q == ST_READ_IDLE) begin
      captured_read_addr <= read_addr_i;
    end
  end

  logic read_err_q, read_err_d;
  logic read_done_q, read_done_d;
  logic read_busy_q, read_busy_d;
  efuse_data_t read_back_data_q_n0_scan, read_back_data_d;

  // Address error signal
  logic read_addr_error_d;

  always_comb begin

    timeout_count_d = timeout_count_q;

    read_state_d = read_state_q;
    read_err_d = read_err_q;
    read_done_d = read_done_q;
    read_busy_d = read_busy_q;
    read_back_data_d = read_back_data_q_n0_scan;
    fuse_command_req_d = FUSE_COMMAND_REQ_DEFAULT;

    read_timeout_event = 1'b0;
    read_addr_error_d = 1'b0;  // Default: no address error

    unique case (read_state_q)
      ST_READ_IDLE: begin
        if (read_go_i) begin
          read_done_d = 1'b0;
          timeout_count_d = 'd0;  // Reset timeout counter on new operation
          if (!read_enable_i) begin
            read_state_d = ST_READ_IDLE;
            read_busy_d  = 1'b0;
            read_done_d  = 1'b1;
            read_err_d   = 1'b1;
          end else if (read_addr_oob_i) begin
            read_state_d = ST_READ_IDLE;
            read_busy_d = 1'b0;
            read_done_d = 1'b1;
            read_err_d = 1'b1;
            read_addr_error_d = 1'b1;
            // Out-of-bounds read returns data=0
            read_back_data_d = efuse_data_t'(0);
          end else begin
            read_state_d = ST_WAIT_RESP;
            read_busy_d = 1'b1;
            read_err_d = 1'b0;
            fuse_command_req_d.address = read_addr_i;
            fuse_command_req_d.program_data = '0;
            fuse_command_req_d.command = efuse_pkg::FUSE_COMMAND_READ;
            fuse_command_req_d.valid = 1'b1;
            fuse_command_req_d.access_length_words = efuse_word_counter_t'(1);
          end
        end
      end

      ST_WAIT_RESP: begin

        if (efuse_req_err_i || fuse_command_resp_i.status == 1'b1 || secure_tm_blocked_i) begin
          // If req is blocked from a shadow reg lock, or physical efuse returned error, or secure_tm blocked it
          read_done_d = 1'b1;
          read_busy_d = 1'b0;
          read_err_d = 1'b1;
          read_back_data_d = efuse_data_t'(0);
          fuse_command_req_d = FUSE_COMMAND_REQ_DEFAULT;
          read_state_d = ST_READ_IDLE;
        end else if (fuse_command_resp_i.valid) begin
          read_done_d = 1'b1;
          read_busy_d = 1'b0;
          read_err_d = 1'b0;  // EFUSE_READ_OK
          read_back_data_d = fuse_command_resp_i.data;
          fuse_command_req_d = FUSE_COMMAND_REQ_DEFAULT;
          read_state_d = ST_READ_IDLE;
        end else begin
          read_done_d = 1'b0;
          read_busy_d = 1'b1;
          read_back_data_d = read_back_data_q_n0_scan;
          fuse_command_req_d = fuse_command_req_q;

          if (read_req_timeout_en_i && timeout_count_d >= read_req_timeout_cycles_i) begin
            read_done_d = 1'b1;
            read_busy_d = 1'b0;
            read_err_d = 1'b1;
            read_back_data_d = efuse_data_t'(0);
            fuse_command_req_d = FUSE_COMMAND_REQ_DEFAULT;
            read_state_d = ST_READ_IDLE;

            read_timeout_event = 1'b1;
          end else if (read_req_timeout_en_i) begin
            timeout_count_d = timeout_count_q + 1;
          end
        end

      end

      default: begin
        read_state_d = ST_READ_IDLE;
        read_busy_d = 1'b0;
        read_done_d = 1'b1;
        read_err_d = 1'b1;
        fuse_command_req_d = FUSE_COMMAND_REQ_DEFAULT;
        read_back_data_d = EFUSE_READ_ERROR_DATA;
      end

    endcase
  end

  // Register the state
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      read_state_q <= ST_READ_IDLE;
      fuse_command_req_q <= FUSE_COMMAND_REQ_DEFAULT;
      read_err_q <= 1'b0;
      read_done_q <= 1'b0;
      read_busy_q <= 1'b0;
      read_back_data_q_n0_scan <= '0;

      timeout_count_q <= 'd0;
    end else begin
      read_state_q <= read_state_d;
      fuse_command_req_q <= fuse_command_req_d;
      read_err_q <= read_err_d;
      read_done_q <= read_done_d;
      read_busy_q <= read_busy_d;
      read_back_data_q_n0_scan <= read_back_data_d;

      timeout_count_q <= timeout_count_d;
    end
  end

  // Set-priority sticky latch: a new OOB pulse in the same cycle as a clear
  // wins (error is preserved). SW must read-then-clear.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      read_addr_error_o <= 1'b0;
    end else if (read_addr_error_d) begin
      read_addr_error_o <= 1'b1;
    end else if (read_addr_error_clear_i) begin
      read_addr_error_o <= 1'b0;
    end
  end

  assign read_busy_o = read_busy_q;
  assign read_done_o = read_done_q;
  assign read_error_o = read_err_q;
  assign read_back_data_o = read_back_data_q_n0_scan;
  assign is_read_timeout_debug_o = read_timeout_event;

  always_comb begin
    fuse_command_req_o = FUSE_COMMAND_REQ_DEFAULT;
    if (read_state_q == ST_WAIT_RESP) begin
      fuse_command_req_o = fuse_command_req_q;
    end
  end

  // verilog_format: off  // Downstream synthesis tooling mis-parses verible's line breaks inside these macro calls.
  `OCAH_OT_ASSERT(
      IllegalReadStateSuppressesRequest_A,
      ($isunknown(read_state_q) || !(read_state_q inside {ST_READ_IDLE, ST_WAIT_RESP})) |-> !fuse_command_req_o.valid,
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT(
      ReadFailureSetsError_A,
      read_state_q == ST_WAIT_RESP && (efuse_req_err_i || fuse_command_resp_i.status || secure_tm_blocked_i) |=> read_done_o && !read_busy_o && read_error_o && read_back_data_o == efuse_data_t'(0),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT(
      ReadTimeoutSetsError_A,
      read_timeout_event |=> read_done_o && !read_busy_o && read_error_o,
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT(
      ReadRequestClearsError_A,
      read_state_q == ST_READ_IDLE && read_go_i && read_enable_i && !read_addr_oob_i |=> !read_error_o,
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT(
      ReadSuccessClearsError_A,
      read_state_q == ST_WAIT_RESP && !efuse_req_err_i && !fuse_command_resp_i.status && !secure_tm_blocked_i && fuse_command_resp_i.valid |=> read_done_o && !read_busy_o && !read_error_o,
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT(
      IllegalReadStateFailsClosed_A,
      ($isunknown(read_state_q) || !(read_state_q inside {ST_READ_IDLE, ST_WAIT_RESP})) |=> read_state_q == ST_READ_IDLE && !read_busy_o && read_done_o && read_error_o && !fuse_command_req_o.valid && read_back_data_o == EFUSE_READ_ERROR_DATA,
      clk_i, !rst_ni)
  // verilog_format: on

endmodule : efuse_read_interface
