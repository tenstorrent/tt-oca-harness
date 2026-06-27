// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//------------------------------------------------------------------------------
// Entropy Debug Monitor
//
// Description:
// Select a bit stream to monitor off chip.
// Asynchronously down convert in frequency. With a default 7-bit frequency
// divider width we have options to divide by factors: {1,2,4,8,16,32,64,128}
// Select one of the down converted streams to send to the output.
//------------------------------------------------------------------------------

module entropy_debug_monitor #(
    parameter int unsigned NSIGNALS       = 32, // Number of input signals to monitor
    parameter int unsigned FREQ_DIV_WIDTH = 8   // Divide down by factors of 2**0 to 2**7
) (
    input  logic                                rst_ni,
    input  logic [$clog2(NSIGNALS)-1:0]         select_signal_i,
    input  logic [NSIGNALS-1:0]                 signal_i,
    input  logic [$clog2(FREQ_DIV_WIDTH-1)-1:0] select_freq_div_i,
    output logic                                sig_monitor_o
);

    logic [NSIGNALS-1:0]       select_signal_binary_decode;

    always_comb begin
        for (int i = 0; i < NSIGNALS; i++) begin
            select_signal_binary_decode[i] = select_signal_i == i[$clog2(NSIGNALS)-1:0];
        end
    end

    logic [NSIGNALS-1:0] select_signal; // must be 1-hot
    assign select_signal = select_signal_binary_decode & signal_i;

    logic fast_signal;
    assign fast_signal = |select_signal;

    // Instantiate the ripple divider to generate frequency division factors
    logic [FREQ_DIV_WIDTH-1:0] div_signals;

    entropy_ripple_divider #(
        .NUM_STAGES(FREQ_DIV_WIDTH - 1)
    ) u_ripple_divider (
        .rst_ni  (rst_ni),
        .clk_i   (fast_signal),
        .div_o   (div_signals)
    );

    // select down converted signal version to monitor
    logic [FREQ_DIV_WIDTH-1:0] select_freq_binary_decode;
    always_comb begin
        for (int i = 0; i < FREQ_DIV_WIDTH; i++) begin
            select_freq_binary_decode[i] = select_freq_div_i == i[$clog2(FREQ_DIV_WIDTH-1)-1:0];
        end
    end

    logic final_signal;
    assign final_signal = |(select_freq_binary_decode & div_signals);
    assign sig_monitor_o = final_signal;

endmodule
