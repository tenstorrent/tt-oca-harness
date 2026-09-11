# Cross Trigger Port Synthesis Timing Constraints
# SDC (Synopsys Design Constraints) file

# Clock definition: clk_i at 100 MHz nominal
create_clock -name clk_i -period 10.0 [get_ports clk_i]

# Clock uncertainty
set_clock_uncertainty -setup 0.5 [get_clocks clk_i]
set_clock_uncertainty -hold 0.2 [get_clocks clk_i]

# Clock latency
set_clock_latency -source 1.0 [get_clocks clk_i]
set_clock_latency 0.5 [get_clocks clk_i]

# Input delays (asynchronous GPIO inputs)
# These are false paths - synchronized internally
set_false_path -from [get_ports ct_req_out_din_i] -to [all_registers]
set_false_path -from [get_ports ct_req_in_din_i] -to [all_registers]
set_false_path -from [get_ports ct_ack_in_din_i] -to [all_registers]

# Input delays for synchronous inputs
set_input_delay -clock clk_i -max 2.0 [get_ports ct_src_i]
set_input_delay -clock clk_i -min 0.5 [get_ports ct_src_i]

# APB interface input delays
set_input_delay -clock clk_i -max 2.0 [get_ports paddr_i]
set_input_delay -clock clk_i -max 2.0 [get_ports psel_i]
set_input_delay -clock clk_i -max 2.0 [get_ports penable_i]
set_input_delay -clock clk_i -max 2.0 [get_ports pwrite_i]
set_input_delay -clock clk_i -max 2.0 [get_ports pwdata_i]
set_input_delay -clock clk_i -max 2.0 [get_ports pstrb_i]
set_input_delay -clock clk_i -min 0.5 [get_ports paddr_i]
set_input_delay -clock clk_i -min 0.5 [get_ports psel_i]
set_input_delay -clock clk_i -min 0.5 [get_ports penable_i]
set_input_delay -clock clk_i -min 0.5 [get_ports pwrite_i]
set_input_delay -clock clk_i -min 0.5 [get_ports pwdata_i]
set_input_delay -clock clk_i -min 0.5 [get_ports pstrb_i]

# Output delays for pad outputs
set_output_delay -clock clk_i -max 2.0 [get_ports ct_req_out_dout_en_o]
set_output_delay -clock clk_i -max 2.0 [get_ports ct_req_out_din_en_o]
set_output_delay -clock clk_i -max 2.0 [get_ports ct_req_out_dout_o]
set_output_delay -clock clk_i -max 2.0 [get_ports ct_req_in_din_en_o]
set_output_delay -clock clk_i -max 2.0 [get_ports ct_ack_in_din_en_o]
set_output_delay -clock clk_i -max 2.0 [get_ports ct_ack_out_dout_en_o]
set_output_delay -clock clk_i -max 2.0 [get_ports ct_ack_out_dout_o]
set_output_delay -clock clk_i -min 0.5 [get_ports ct_req_out_dout_en_o]
set_output_delay -clock clk_i -min 0.5 [get_ports ct_req_out_din_en_o]
set_output_delay -clock clk_i -min 0.5 [get_ports ct_req_out_dout_o]
set_output_delay -clock clk_i -min 0.5 [get_ports ct_req_in_din_en_o]
set_output_delay -clock clk_i -min 0.5 [get_ports ct_ack_in_din_en_o]
set_output_delay -clock clk_i -min 0.5 [get_ports ct_ack_out_dout_en_o]
set_output_delay -clock clk_i -min 0.5 [get_ports ct_ack_out_dout_o]

# Core-side output delays
set_output_delay -clock clk_i -max 2.0 [get_ports ct_dst_o]
set_output_delay -clock clk_i -max 2.0 [get_ports busy_o]
set_output_delay -clock clk_i -min 0.5 [get_ports ct_dst_o]
set_output_delay -clock clk_i -min 0.5 [get_ports busy_o]

# APB interface output delays
set_output_delay -clock clk_i -max 2.0 [get_ports pready_o]
set_output_delay -clock clk_i -max 2.0 [get_ports prdata_o]
set_output_delay -clock clk_i -max 2.0 [get_ports pslverr_o]
set_output_delay -clock clk_i -min 0.5 [get_ports pready_o]
set_output_delay -clock clk_i -min 0.5 [get_ports prdata_o]
set_output_delay -clock clk_i -min 0.5 [get_ports pslverr_o]

# Reset timing
set_false_path -from [get_ports rst_ni] -to [all_registers]

# Maximum transition time
set_max_transition 1.0 [current_design]

# Maximum fanout
set_max_fanout 50 [current_design]

# Maximum capacitance
set_max_capacitance 1.0 [current_design]
