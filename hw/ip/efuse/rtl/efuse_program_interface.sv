// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Program fuse bits or words through the fuse-command interface with optional read-back and timeouts.
//
// program_go_i starts a program to program_addr_i with program_data_in_i;
// program_read_back_enable_i requests post-program read-back.
// program_addr_oob_i is computed upstream against the full-width CSR field because
// casting to efuse_addr_t truncates upper bits.
// Honors secure_tm_blocked_i, efuse_req_err_i, and optional program_req_timeout_* ;
// sticky address errors clear with program_addr_error_clear_i.
// is_programing_o and program_target_addr_o feed the guard while a program is active.

`include "prim_assert.sv"

module efuse_program_interface #(
  parameter unsigned EFUSE_WORD_WIDTH = 32,  // Program/read data word width.

  parameter type efuse_addr_t = logic,  // Fuse bit-address type.
  parameter type efuse_data_t = logic,  // Fuse data-word type.
  parameter type efuse_word_counter_t = logic,  // Fuse access-length counter type.
  parameter type fuse_command_req_t = logic,  // Fuse-command request type.
  parameter type fuse_command_resp_t = logic  // Fuse-command response type.
) (
  input logic clk_i,                    // System clock.
  input logic rst_ni,                   // Active-low reset.
  input logic test_en_i,                // DFT test enable.

  input  logic        program_enable_i,  // Program enable.
  output logic        is_programing_o,  // Is programing.
  output efuse_addr_t program_target_addr_o,  // Program target addr.

  input efuse_addr_t program_addr_i,    // Program addr.
  input logic        program_data_in_i,  // Program data in.
  input logic        program_go_i,      // Program go.
  input logic        program_read_back_enable_i,  // Program read back enable.

  output logic        program_busy_o,   // Program busy.
  output logic        program_done_o,   // Program done.
  output logic        program_error_o,  // Program error.
  output efuse_data_t program_read_back_data_o,  // Program read back data.

  input  logic program_addr_oob_i,      // Program addr oob.
  output logic program_addr_error_o,    // Program addr error.
  input  logic program_addr_error_clear_i,  // Program addr error clear.

  input logic efuse_req_err_i,          // Efuse req err.
  input logic secure_tm_blocked_i,      // Secure tm blocked.

  input logic        program_req_timeout_en_i,  // Program req timeout en.
  input logic [27:0] program_req_timeout_cycles_i,  // Program req timeout cycles.

  output fuse_command_req_t  fuse_command_req_o,  // Fuse command req.
  input  fuse_command_resp_t fuse_command_resp_i,  // Fuse command resp.

  output logic is_program_timeout_debug_o  // Is program timeout debug.
);

  localparam fuse_command_req_t FUSE_COMMAND_REQ_DEFAULT = '0;
  localparam efuse_data_t EFUSE_PROGRAM_ERROR_DATA = efuse_data_t'('hbadcab1e);

  // Timeout logic
  logic [27:0] timeout_count_q, timeout_count_d;
  logic program_timeout_event;

  fuse_command_req_t fuse_command_req_d, fuse_command_req_q;

  efuse_addr_t captured_program_addr;
  logic        captured_program_data;

  // Program execution state machine
  typedef enum logic [1:0] {
    ST_PROGRAM_IDLE = 2'b01,
    ST_WAIT_RESP    = 2'b10
  } efuse_program_state_e;


  efuse_program_state_e program_state_q, program_state_d;
  assign is_programing_o = (program_state_q == ST_PROGRAM_IDLE) ? 1'b0 : 1'b1;
  assign program_target_addr_o = (program_state_q == ST_PROGRAM_IDLE) ? efuse_addr_t'(0) : captured_program_addr;

  // Capture program address and data when idle
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      captured_program_addr <= 'd0;
      captured_program_data <= 'd0;
    end else if (program_state_q == ST_PROGRAM_IDLE) begin
      captured_program_addr <= program_addr_i;
      captured_program_data <= program_data_in_i;
    end
  end

  logic program_err_q, program_err_d;
  logic program_done_q, program_done_d;
  logic program_busy_q, program_busy_d;
  efuse_data_t program_read_back_data_q_n0_scan, program_read_back_data_d;

  // Address error signal
  logic program_addr_error_d;

  always_comb begin

    timeout_count_d = timeout_count_q;

    program_state_d = program_state_q;
    program_err_d = program_err_q;
    program_done_d = program_done_q;
    program_busy_d = program_busy_q;
    program_read_back_data_d = program_read_back_data_q_n0_scan;
    fuse_command_req_d = fuse_command_req_q;

    program_timeout_event = 1'b0;
    program_addr_error_d = 1'b0;  // Default: no address error

    unique case (program_state_q)
      ST_PROGRAM_IDLE: begin
        if (program_go_i) begin
          program_done_d  = 1'b0;
          timeout_count_d = 'd0;
          if (!program_enable_i) begin
            program_state_d = ST_PROGRAM_IDLE;
            program_busy_d  = 1'b0;
            program_done_d  = 1'b1;
            program_err_d   = 1'b1;
          end else if (program_data_in_i == 1'b0) begin
            program_state_d = ST_PROGRAM_IDLE;
            program_busy_d  = 1'b0;
            program_done_d  = 1'b1;
            program_err_d   = 1'b1;
          end else if (program_addr_oob_i) begin
            program_state_d = ST_PROGRAM_IDLE;
            program_busy_d = 1'b0;
            program_done_d = 1'b1;
            program_err_d = 1'b1;
            program_addr_error_d = 1'b1;
          end else begin
            program_state_d = ST_WAIT_RESP;
            program_busy_d = 1'b1;
            fuse_command_req_d.address = program_addr_i;
            fuse_command_req_d.program_data = program_data_in_i;
            fuse_command_req_d.command = program_read_back_enable_i ? efuse_pkg::FUSE_COMMAND_PROGRAM_READ_BACK : efuse_pkg::FUSE_COMMAND_PROGRAM;
            fuse_command_req_d.valid = 1'b1;
            fuse_command_req_d.access_length_words = efuse_word_counter_t'(1);

          end
        end
      end

      ST_WAIT_RESP: begin
        // If req is blocked from a shadow reg lock, or physical efuse returned error, or secure_tm blocked it
        if (efuse_req_err_i || fuse_command_resp_i.status == 1'b1 || secure_tm_blocked_i) begin

          program_done_d = 1'b1;
          program_busy_d = 1'b0;
          program_err_d = 1'b1;
          fuse_command_req_d = FUSE_COMMAND_REQ_DEFAULT;
          program_state_d = ST_PROGRAM_IDLE;

        end else if (fuse_command_resp_i.valid) begin

          program_done_d = 1'b1;
          program_busy_d = 1'b0;
          program_err_d = fuse_command_resp_i.status;
          fuse_command_req_d = FUSE_COMMAND_REQ_DEFAULT;
          program_state_d = ST_PROGRAM_IDLE;

          program_read_back_data_d = fuse_command_resp_i.data;

        end else begin

          program_done_d = 1'b0;
          program_busy_d = 1'b1;
          program_err_d  = 1'b0;

          if (program_req_timeout_en_i && timeout_count_d >= program_req_timeout_cycles_i) begin
            program_done_d = 1'b1;
            program_busy_d = 1'b0;
            program_err_d = 1'b1;
            fuse_command_req_d = FUSE_COMMAND_REQ_DEFAULT;
            program_state_d = ST_PROGRAM_IDLE;

            program_timeout_event = 1'b1;
          end else if (program_req_timeout_en_i) begin
            timeout_count_d = timeout_count_q + 1;
          end
        end

      end

      default: begin
        program_state_d = ST_PROGRAM_IDLE;
        program_busy_d = 1'b0;
        program_done_d = 1'b1;
        program_err_d = 1'b1;
        program_read_back_data_d = EFUSE_PROGRAM_ERROR_DATA;
        fuse_command_req_d = FUSE_COMMAND_REQ_DEFAULT;
      end

    endcase
  end

  // Register the state
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      program_state_q                  <= ST_PROGRAM_IDLE;
      program_err_q                    <= 1'b0;
      program_done_q                   <= 1'b0;
      program_busy_q                   <= 1'b0;
      program_read_back_data_q_n0_scan <= efuse_data_t'(0);
      timeout_count_q                  <= 'd0;
    end else begin
      program_state_q                  <= program_state_d;
      program_err_q                    <= program_err_d;
      program_done_q                   <= program_done_d;
      program_busy_q                   <= program_busy_d;
      program_read_back_data_q_n0_scan <= program_read_back_data_d;
      timeout_count_q                  <= timeout_count_d;
    end
  end

  // Fuse command output register: on the Class 2b secure scan chain
  if (1'b1) begin : gen_fuse_cmd_req_s3c_scan
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) fuse_command_req_q <= FUSE_COMMAND_REQ_DEFAULT;
      else fuse_command_req_q <= fuse_command_req_d;
    end
  end

  // Set-priority sticky latch: a new OOB pulse in the same cycle as a clear
  // wins (error is preserved). SW must read-then-clear.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      program_addr_error_o <= 1'b0;
    end else if (program_addr_error_d) begin
      program_addr_error_o <= 1'b1;
    end else if (program_addr_error_clear_i) begin
      program_addr_error_o <= 1'b0;
    end
  end

  assign program_busy_o = program_busy_q;
  assign program_done_o = program_done_q;
  assign program_error_o = program_err_q;
  assign program_read_back_data_o = program_read_back_data_q_n0_scan;
  assign is_program_timeout_debug_o = program_timeout_event;

  always_comb begin
    fuse_command_req_o = FUSE_COMMAND_REQ_DEFAULT;
    if (program_state_q == ST_WAIT_RESP) begin
      fuse_command_req_o = fuse_command_req_q;
    end
  end

  // verilog_format: off  // Downstream synthesis tooling mis-parses verible's line breaks inside these macro calls.
  `OCAH_OT_ASSERT(
      IllegalProgramStateSuppressesRequest_A,
      ($isunknown(program_state_q) || !(program_state_q inside {ST_PROGRAM_IDLE, ST_WAIT_RESP})) |-> !fuse_command_req_o.valid,
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT(
      IllegalProgramStateFailsClosed_A,
      ($isunknown(program_state_q) || !(program_state_q inside {ST_PROGRAM_IDLE, ST_WAIT_RESP})) |=> program_state_q == ST_PROGRAM_IDLE && !program_busy_o && program_done_o && program_error_o && !fuse_command_req_o.valid && program_read_back_data_o == EFUSE_PROGRAM_ERROR_DATA,
      clk_i, !rst_ni)
  // verilog_format: on

endmodule : efuse_program_interface
