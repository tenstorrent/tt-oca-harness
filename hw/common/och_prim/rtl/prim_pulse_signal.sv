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
  input  logic                        clk_i,
  input  logic                        rst_ni,

  input  logic                        pulse_start_i,
  input  logic      [COUNT_WIDTH-1:0] pre_pulse_wait_i,
  input  logic      [COUNT_WIDTH-1:0] post_pulse_wait_i,

  input  logic                        pulse_in_i,
  output logic                        pulse_out_o,
  output logic                        pulse_done_o

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
    .clk_i(clk_i),
    .rst_ni(rst_ni),
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
  always_ff @(posedge clk_i) begin
    if (~rst_ni) begin
      pulse_in_initial_val <= 1'b0;
    end else begin
      if (pulse_start_i) begin
        pulse_in_initial_val <= pulse_in_i;
      end
    end
  end

  always_comb begin

    case (pulse_state)
      IDLE: begin
        // keep deasserted
        pulse_out_o = IS_ACTIVE_HIGH;
        pulse_done_o = 1'b1;

        if (pulse_start_i) begin
          pulse_set_cnt = pre_pulse_wait_i;
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
        pulse_out_o = pulse_in_initial_val;
        pulse_done_o = 1'b0;

        if (pulse_start_i) begin  // new reset has arrived, restart the count
          pulse_set_cnt = pre_pulse_wait_i;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b1;
          pulse_commit = 1'b1;
          pulse_state_nxt = PRE_RESET;

        end else if (~|pulse_count) begin
          pulse_set_cnt = post_pulse_wait_i;
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

        if (pulse_start_i) begin  // new reset has arrived, restart the count
          pulse_out_o = IS_ACTIVE_HIGH;
          pulse_done_o = 1'b0;
          pulse_set_cnt = post_pulse_wait_i;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b1;
          pulse_commit = 1'b1;
          pulse_state_nxt = POST_RESET;

        end else if (~|pulse_count) begin  // count reached
          pulse_out_o = ~IS_ACTIVE_HIGH;
          pulse_done_o = 1'b0;
          pulse_set_cnt = '0;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b0;
          pulse_commit = 1'b1;
          pulse_state_nxt = IDLE;

        end else begin  // keep counting
          pulse_out_o = IS_ACTIVE_HIGH;
          pulse_done_o = 1'b0;
          pulse_set_cnt = '0;
          pulse_set = 1'b0;
          pulse_decr_en = 1'b1;
          pulse_commit = 1'b1;
          pulse_state_nxt = POST_RESET;
        end
      end

      default: begin
        // keep deasserted
        pulse_out_o = IS_ACTIVE_HIGH;
        pulse_done_o = 1'b1;
        pulse_set_cnt = '0;
        pulse_set = 1'b0;
        pulse_decr_en = 1'b0;
        pulse_commit = 1'b0;
        pulse_state_nxt = IDLE;
      end
    endcase
  end

  // pulse core reset state
  always_ff @(posedge clk_i) begin
    if (~rst_ni) begin
      pulse_state <= IDLE;
    end else begin
      pulse_state <= pulse_state_nxt;
    end
  end

endmodule
