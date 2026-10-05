// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Shape pulse_in_i with programmable pre- and post-wait counts.
//
// pulse_start_i samples pulse_in_i and starts a sequence: drive the sampled level for
// pre_pulse_wait_i + 1 cycles, assert pulse_out_o for post_pulse_wait_i + 1 cycles, then
// return to idle. A new pulse_start_i during the sequence reloads the count of the current
// phase.
// IS_ACTIVE_HIGH sets the polarity of pulse_out_o.
// pulse_done_o is high while idle and low for the whole sequence; pulse_out_o sits at its
// asserted level while idle, so use it only while pulse_done_o is low.

module prim_pulse_signal #(
  parameter int COUNT_WIDTH = 16,  // Width of the wait counters.
  parameter bit IS_ACTIVE_HIGH = 0  // 1 makes pulse_out_o active-high; 0 makes it active-low.
) (
  input  logic                        clk_i,  // Pulse clock.
  input  logic                        rst_ni,  // Active-low reset, sampled synchronously.

  input  logic                        pulse_start_i,  // Arms a shaped pulse sequence.
  input  logic      [COUNT_WIDTH-1:0] pre_pulse_wait_i,  // Cycles, minus one, of the sampled
                                                         // pulse_in_i level before pulse_out_o
                                                         // asserts.
  input  logic      [COUNT_WIDTH-1:0] post_pulse_wait_i,  // Cycles, minus one, that pulse_out_o
                                                          // stays asserted.

  input  logic                        pulse_in_i,  // Level sampled on pulse_start_i and driven
                                                   // during the pre-pulse wait.
  output logic                        pulse_out_o,  // Shaped pulse output; valid while pulse_done_o
                                                    // is low.
  output logic                        pulse_done_o  // High while idle; low while a sequence runs.

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
  } pulse_state_e;

  pulse_state_e pulse_state, pulse_state_nxt;

  prim_updown_counter #(
    .WIDTH(COUNT_WIDTH),
    .RESET_VALUE({COUNT_WIDTH{1'b0}})
  ) u_pulse_pulse_counter (
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
        pulse_done_o = 1'b0;

        if (pulse_start_i) begin  // new reset has arrived, restart the count
          pulse_out_o = IS_ACTIVE_HIGH;
          pulse_set_cnt = post_pulse_wait_i;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b1;
          pulse_commit = 1'b1;
          pulse_state_nxt = POST_RESET;

        end else if (~|pulse_count) begin  // count reached
          pulse_out_o = IS_ACTIVE_HIGH;
          pulse_set_cnt = '0;
          pulse_set = 1'b1;
          pulse_decr_en = 1'b0;
          pulse_commit = 1'b1;
          pulse_state_nxt = IDLE;

        end else begin  // keep counting
          pulse_out_o = IS_ACTIVE_HIGH;
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
