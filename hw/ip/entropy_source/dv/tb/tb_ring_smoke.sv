// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module tb_ring_smoke;
  logic enable_i = 1'b0;
  logic detune_i = 1'b0;
  logic noise_o;
  time  enabled_at;

  entropy_ring_oscillator u_dut (
    .enable_i,
    .detune_i,
    .noise_o
  );

  initial begin
    #10;
    enabled_at = $time;
    enable_i = 1'b1;
    repeat (4) @(posedge noise_o);
    if ($time <= enabled_at) begin
      $fatal(1, "ring oscillator edges did not advance simulated time");
    end
    $display("PASS: ring oscillator produced four rising edges by %0t", $time);
    $finish;
  end

  initial begin
    #100;
    $fatal(1, "ring oscillator did not advance");
  end
endmodule
