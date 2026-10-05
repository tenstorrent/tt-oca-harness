typedef enum logic [2:0] {
  AwaitPattern = 3'h0,
  AwaitSCL = 3'h1,
  AwaitSr = 3'h2,
  AwaitP = 3'h3,
  ResetDetected = 3'h4
} target_reset_detector_state_e;

module target_reset_detector
  import i3c_pkg::*;
(
    input logic clk_i,
    input logic rst_ni,

    input logic enable_i,

    // Bus state (provides stable signals for glitch immunity)
    input bus_state_t bus_i,

    output logic target_reset_detect_o
);

  // Gate bus signals with enable - when disabled, bus appears idle (high, no edges/events)
  bus_state_t bus;
  always_comb begin
    if (enable_i) begin
      bus = bus_i;
    end else begin
      // When disabled: force idle state
      bus = '1;
    end
  end

  logic count_sda_transition_en;

  logic [3:0] sda_transition_count_q;
  logic [3:0] sda_transition_count_d;

  target_reset_detector_state_e state_q, state_d;

  always_comb begin
    if ((state_q == AwaitPattern) & (sda_transition_count_q < 4'd14)) begin
      count_sda_transition_en = (bus.sda.pos_edge & (sda_transition_count_q != 0)) | bus.sda.neg_edge;
      if (bus.scl.stable_high) sda_transition_count_d = 4'h0;
      else
        sda_transition_count_d = count_sda_transition_en ?
                                    sda_transition_count_q + 4'h1 :
                                    sda_transition_count_q;
    end else begin
      count_sda_transition_en = 1'b0;
      if (bus.scl.stable_high) sda_transition_count_d = 4'h0;
      else sda_transition_count_d = sda_transition_count_q;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin : target_reset_sda_transition_counter
    if (!rst_ni) begin
      sda_transition_count_q <= 4'h0;
    end else begin
      sda_transition_count_q <= sda_transition_count_d;
    end
  end : target_reset_sda_transition_counter

  always_ff @(posedge clk_i or negedge rst_ni) begin : target_reset_detection_state
    if (!rst_ni) begin
      state_q <= AwaitPattern;
    end else begin
      state_q <= state_d;
    end
  end : target_reset_detection_state

  always_comb begin : target_reset_detection_fsm
    case (state_q)
      AwaitPattern: begin
        state_d = (sda_transition_count_q == 4'he) ? AwaitSCL : AwaitPattern;
      end
      AwaitSCL: begin
        state_d = AwaitSCL;
        // Bus state has changed, go back
        if (bus.scl.stable_high | bus.sda.stable_low) begin
          state_d = AwaitPattern;
        end else if (bus.scl.pos_edge) begin
          state_d = AwaitSr;
        end
      end
      AwaitSr: begin
        state_d = AwaitSr;
        // If SDA posedge is detected, it means that it toggled from LOW to HIGH before fulfilling
        // the START condition hold timing, otherwise `start_detected` would be asserted
        if (bus.scl.stable_low | bus.sda.pos_edge) begin
          state_d = AwaitPattern;
        end else if (bus.start_det | bus.rstart_det) begin
          state_d = AwaitP;
        end
      end
      AwaitP: begin
        state_d = AwaitP;
        // If SDA negedge is detected, it means that it toggled from HIGH to LOW before fulfilling
        // the STOP condition hold timing, otherwise `stop_detected` would be asserted
        if (bus.scl.stable_low | bus.sda.neg_edge) begin
          state_d = AwaitPattern;
        end else if (bus.stop_det) begin
          state_d = ResetDetected;
        end
      end
      ResetDetected: begin
        state_d = AwaitPattern;
      end
      default: begin
        state_d = AwaitPattern;
      end
    endcase
  end : target_reset_detection_fsm

  assign target_reset_detect_o = state_d == ResetDetected;
endmodule
