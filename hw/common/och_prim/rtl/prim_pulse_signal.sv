// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Pulse Signal
//
//--------------------------------------------------
module prim_pulse_signal #(
  parameter int COUNT_WIDTH = 16,
  parameter bit IS_ACTIVE_HIGH = 0  // set whether the pulse is active high
) (
  input  logic                        i_clk,
  input  logic                        i_reset_n,

  input  logic                        i_pulse_start,
  input  logic      [COUNT_WIDTH-1:0] i_pre_pulse_wait,
  input  logic      [COUNT_WIDTH-1:0] i_post_pulse_wait,

  input  logic                        i_pulse_in,
  output logic                        o_pulse_out,
  output logic                        o_pulse_done

);

  logic                               pulse_in_initial_val;

  logic                               pulse_set;
  logic             [COUNT_WIDTH-1:0] pulse_set_cnt;           // Set value for the counter.
  logic                               pulse_decr_en;
  logic                               pulse_commit;
  logic             [COUNT_WIDTH-1:0] pulse_count;             // Current counter state
  logic             [COUNT_WIDTH-1:0] pulse_cnt_after_commit;  // Next counter state if committed

  typedef enum logic [1:0] {
    IDLE        = 2'b00,
    PRE_RESET   = 2'b01,
    POST_RESET  = 2'b10
  } pulse_state_t;

  pulse_state_t pulse_state, pulse_state_nxt;

  prim_updown_counter #(
    .Width(COUNT_WIDTH),
    .ResetValue({COUNT_WIDTH{1'b0}})
  ) pulse_pulse_counter (
    .clk_i(i_clk),
    .reset_n_i(i_reset_n),
    .clear_i(1'b0),
    .set_i(pulse_set),
    .set_cnt_i(pulse_set_cnt),           // Set value for the counter.
    .incr_en_i(1'b0),
    .decr_en_i(pulse_decr_en),
    .step_i(16'd1),              // Increment/decrement step when enabled.
    .commit_i(pulse_commit),
    .count_o(pulse_count),             // Current counter state
    .cnt_after_commit_o(pulse_cnt_after_commit),  // Next counter state if committed
    .err_o()
  );

  // when a pulse is requested, lock in the prev value
  always_ff @(posedge i_clk) begin
    if (~i_reset_n) begin
      pulse_in_initial_val <= 1'b0;
    end else begin
      if (i_pulse_start) begin
        pulse_in_initial_val <= i_pulse_in;
      end
    end
  end

  always_comb begin

    case (pulse_state)
      IDLE: begin
        // keep deasserted
        o_pulse_out = IS_ACTIVE_HIGH;
        o_pulse_done = 1'b1;

        if (i_pulse_start) begin
          pulse_set_cnt = i_pre_pulse_wait;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b0;
          pulse_commit = 1'b1;
          pulse_state_nxt = PRE_RESET;

        end else begin
          pulse_set_cnt = '0;
          pulse_set = 1'b0;
          pulse_decr_en = 1'b0;
          pulse_commit = 1'b0;
          pulse_state_nxt = IDLE;
        end
      end

      PRE_RESET: begin  // wait some cycles before pulsing
        // keep deasserted
        o_pulse_out = pulse_in_initial_val;
        o_pulse_done = 1'b0;

        if (i_pulse_start) begin  // new reset has arrived, restart the count
          pulse_set_cnt = i_pre_pulse_wait;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b1;
          pulse_commit = 1'b1;
          pulse_state_nxt = PRE_RESET;

        end else if (~|pulse_count) begin
          pulse_set_cnt = i_post_pulse_wait;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b0;
          pulse_commit = 1'b1;
          pulse_state_nxt = POST_RESET;

        end else begin  // keep counting
          pulse_set_cnt = '0;
          pulse_set = 1'b0;
          pulse_decr_en = 1'b1;
          pulse_commit = 1'b1;
          pulse_state_nxt = PRE_RESET;
        end
      end

      POST_RESET: begin  // hold pulse for some duration

        if (i_pulse_start) begin  // new reset has arrived, restart the count
          o_pulse_out = IS_ACTIVE_HIGH;
          o_pulse_done = 1'b0;
          pulse_set_cnt = i_post_pulse_wait;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b1;
          pulse_commit = 1'b1;
          pulse_state_nxt = POST_RESET;

        end else if (~|pulse_count) begin  // count reached
          o_pulse_out = ~IS_ACTIVE_HIGH;
          o_pulse_done = 1'b0;
          pulse_set_cnt = '0;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b0;
          pulse_commit = 1'b1;
          pulse_state_nxt = IDLE;

        end else begin  // keep counting
          o_pulse_out = IS_ACTIVE_HIGH;
          o_pulse_done = 1'b0;
          pulse_set_cnt = '0;
          pulse_set = 1'b0;
          pulse_decr_en = 1'b1;
          pulse_commit = 1'b1;
          pulse_state_nxt = POST_RESET;
        end
      end

      default: begin
        // keep deasserted
        o_pulse_out = IS_ACTIVE_HIGH;
        o_pulse_done = 1'b1;
        pulse_set_cnt = '0;
        pulse_set = 1'b0;
        pulse_decr_en = 1'b0;
        pulse_commit = 1'b0;
        pulse_state_nxt = IDLE;
      end
    endcase
  end

  // pulse core reset state
  always_ff @(posedge i_clk) begin
    if (~i_reset_n) begin
      pulse_state <= IDLE;
    end else begin
      pulse_state <= pulse_state_nxt;
    end
  end

endmodule
