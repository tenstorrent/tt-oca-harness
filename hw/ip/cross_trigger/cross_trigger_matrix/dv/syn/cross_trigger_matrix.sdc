# Cross Trigger Matrix Synthesis Timing Constraints
# SDC (Synopsys Design Constraints) file

# Clock definition: clk_i at 100 MHz nominal
create_clock -name clk_i -period 10.0 [get_ports clk_i]

# Clock uncertainty
set_clock_uncertainty -setup 0.5 [get_clocks clk_i]
set_clock_uncertainty -hold 0.2 [get_clocks clk_i]

# Clock latency
set_clock_latency -source 1.0 [get_clocks clk_i]
set_clock_latency 0.5 [get_clocks clk_i]

# Input delays for synchronous CT_Dst inputs
set_input_delay -clock clk_i -max 2.0 [get_ports ct_dst_i*]
set_input_delay -clock clk_i -min 0.5 [get_ports ct_dst_i*]

# AXI-Lite interface input delays
set_input_delay -clock clk_i -max 2.0 [get_ports axil_req_i*]
set_input_delay -clock clk_i -min 0.5 [get_ports axil_req_i*]

# Output delays for CT_Src outputs
set_output_delay -clock clk_i -max 2.0 [get_ports ct_src_o*]
set_output_delay -clock clk_i -min 0.5 [get_ports ct_src_o*]

# AXI-Lite interface output delays
set_output_delay -clock clk_i -max 2.0 [get_ports axil_resp_o*]
set_output_delay -clock clk_i -min 0.5 [get_ports axil_resp_o*]

# Reset timing
set_false_path -from [get_ports rst_ni] -to [all_registers]

# Maximum transition time
set_max_transition 1.0 [current_design]

# Maximum fanout
set_max_fanout 50 [current_design]

# Maximum capacitance
set_max_capacitance 1.0 [current_design]
