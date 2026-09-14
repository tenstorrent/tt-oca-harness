# Cross Trigger Network Synthesis Constraints
# Copyright 2025 Tenstorrent Inc.

# Clock definition: clk_i at 100 MHz nominal
create_clock -name clk -period 10.0 [get_ports clk_i]

# Reset is asynchronous
set_false_path -from [get_ports rst_ni]

# stop_clks_o is a registered output; the clock gates it feeds are constrained at the top level

# AXI-Lite interface timing
# Input delay for AXI-Lite request signals
set_input_delay -clock clk -max 2.0 [get_ports axil_req_i*]
set_input_delay -clock clk -min 0.5 [get_ports axil_req_i*]

# Output delay for AXI-Lite response signals
set_output_delay -clock clk -max 2.0 [get_ports axil_resp_o*]
set_output_delay -clock clk -min 0.5 [get_ports axil_resp_o*]

# Cross trigger interface timing
# Internal cross trigger interface
set_input_delay -clock clk -max 2.0 [get_ports ctm_*_i]
set_output_delay -clock clk -max 2.0 [get_ports ctm_*_o]

# External CTP GPIO interface
set_input_delay -clock clk -max 2.0 [get_ports ctp_*_din_i]
set_output_delay -clock clk -max 2.0 [get_ports ctp_*_dout*_o]
set_output_delay -clock clk -max 2.0 [get_ports ctp_*_en_o]

# Clock stop interface
set_input_delay -clock clk -max 2.0 [get_ports clk_stop_req_i*]
set_input_delay -clock clk -max 2.0 [get_ports cla_clock_stop_en_i]
set_input_delay -clock clk -max 2.0 [get_ports jtag_clock_stop_i]
set_output_delay -clock clk -max 2.0 [get_ports stop_clks_o]
