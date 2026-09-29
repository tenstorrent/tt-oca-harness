#------------------------------------------------------------------------------
# Copyright 2025 Tenstorrent Inc.
# Entropy Source Component
#
# Description:
# Timing constraints for the entropy_source module.
# Special considerations:
# 1. The clk_i signal is the global synchronous clock and rst_ni is the global
#    asynchronous, active low reset signal. They have high fanout as they feed
#    most flip-flop instances in the design. Define the clock period as a
#    parameter named PERIOD that we set to a value determined by the target
#    technology. The default value is 1 ns.
# 2. entropy_ring_oscillator.sv
#    The timing path on the feedback path must be broken. Also, we do
#    not want any logic optimization to be performed on any of the logic cells
#    in this module other than direct mapping to equivalent technology specific
#    cells.
# 3. entropy_sampler_clocks.sv and entropy_noise_source.sv
#    The sample_clk_o output signals must be treated as clocks for the smpl
#    flip-flop instance in the entropy_noise_source.sv module.
#    The input timing path to the sync0 flip-flop instance in
#    entropy_noise_sourc.sv should be broken as this is the first stage of a
#    synchronizer. The second stage is instance sync1 and is treated as normal.
# 4. entropy_ripple_divider.sv
#    Each divided flop Q is a generated clock. The toggle feedback into D is a
#    synchronous data path relative to that stage's clock and is timed normally.
#    The divider structure is preserved.
#------------------------------------------------------------------------------

#------------------------------------------------------------------------------
# DESIGN PARAMETERS
#------------------------------------------------------------------------------

# Define clock period parameter - adjust based on target technology
# Default: 1.0 ns (1.0 GHz)
set PERIOD 1.0

# APB interface timing margins (as percentage of clock period)
set INPUT_DELAY_PERCENT  0.3
set OUTPUT_DELAY_PERCENT 0.3

#------------------------------------------------------------------------------
# CLOCK DEFINITIONS
#------------------------------------------------------------------------------

# Primary system clock - drives all synchronous logic
create_clock -name clk_sys -period $PERIOD [get_ports clk_i]

# External ring oscillator sample clock
# Estimated period 2.5 ns (400 MHz)
# This clock is used as an alternative to internal sampling ring oscillators

create_clock -name clk_sample_ext -period 2.5 [get_ports rosc_sample_clk_i]

# Internal shared ring oscillator sample clock (entropy_sampler_clocks).
# Single shared RO (length 109) distributed to all 12 generators.
# Approximate clock frequency is 435 MHz (109 stages)
create_clock -name clk_sample_shared -period 2.3 \
    [get_pins u_generator_complex/u_sampler_clocks/u_shared_ro/u_fbf/y_o]

# Sampler lanes: 12 dividers x 5 stages. Debug monitor: 7 stages. Stage n
# divides its source by 2^(n+1). Q is not a clock cell, so each tap is a
# generated clock. Both sampler sources are stamped.
set entropy_ref_cells [get_cells -hierarchical -quiet -filter "ref_name =~ prim_flop*"]
set entropy_div_flops {}
if {[sizeof_collection $entropy_ref_cells] > 0} {
    set entropy_div_flops [get_object_name $entropy_ref_cells]
}
set entropy_sampler_flops [lsearch -all -inline -glob $entropy_div_flops \
    {*u_sampler_clocks*u_sample_clk_divider*u_div_ff}]
if {[llength $entropy_sampler_flops] == 0} {
    set entropy_sampler_cells [get_cells -hierarchical -quiet \
        *u_sampler_clocks*u_sample_clk_divider*u_div_ff]
    if {[sizeof_collection $entropy_sampler_cells] > 0} {
        set entropy_sampler_flops [get_object_name $entropy_sampler_cells]
    }
}
set entropy_sampler_flops [lsort -dictionary $entropy_sampler_flops]
set entropy_tap_idx 0
foreach entropy_tap_cell $entropy_sampler_flops {
    if {![regexp {gen_div_stage\[([0-9]+)\]|gen_div_stage_([0-9]+)} \
            $entropy_tap_cell -> entropy_stage_b entropy_stage_u]} {
        error "entropy divider flop has no stage index: $entropy_tap_cell"
    }
    set entropy_stage $entropy_stage_b
    if {$entropy_stage eq ""} {
        set entropy_stage $entropy_stage_u
    }
    set entropy_divide_by [expr {1 << ($entropy_stage + 1)}]
    set entropy_tap_pin [get_pins "${entropy_tap_cell}/q_o"]
    create_generated_clock -add -name clk_sample_ext_div_${entropy_tap_idx} \
        -master_clock clk_sample_ext -divide_by $entropy_divide_by \
        -source [get_ports rosc_sample_clk_i] $entropy_tap_pin
    create_generated_clock -add -name clk_sample_shared_div_${entropy_tap_idx} \
        -master_clock clk_sample_shared -divide_by $entropy_divide_by \
        -source [get_pins u_generator_complex/u_sampler_clocks/u_shared_ro/u_fbf/y_o] \
        $entropy_tap_pin
    incr entropy_tap_idx
}
if {$entropy_tap_idx != 60} {
    error "entropy sampler divider taps: expected 60, found $entropy_tap_idx"
}

set entropy_dbg_flops [lsearch -all -inline -glob $entropy_div_flops \
    {*u_debug_monitor*u_ripple_divider*u_div_ff}]
if {[llength $entropy_dbg_flops] == 0} {
    set entropy_dbg_cells [get_cells -hierarchical -quiet \
        *u_debug_monitor*u_ripple_divider*u_div_ff]
    if {[sizeof_collection $entropy_dbg_cells] > 0} {
        set entropy_dbg_flops [get_object_name $entropy_dbg_cells]
    }
}
set entropy_dbg_flops [lsort -dictionary $entropy_dbg_flops]
set entropy_dbg_tap_idx 0
foreach entropy_dbg_cell $entropy_dbg_flops {
    create_clock -add -name clk_sample_dbg_${entropy_dbg_tap_idx} -period 2.5 \
        [get_pins "${entropy_dbg_cell}/q_o"]
    incr entropy_dbg_tap_idx
}
if {$entropy_dbg_tap_idx != 7} {
    error "entropy debug divider taps: expected 7, found $entropy_dbg_tap_idx"
}

#------------------------------------------------------------------------------
# CLOCK GROUPS - ASYNCHRONOUS DOMAINS
#------------------------------------------------------------------------------

# System clock is asynchronous to both sample-clock families and to the debug
# divider. Each family includes its ripple-divider taps. The two sample
# families are logically exclusive at the source mux, so they are not also
# asynchronous to each other.
set_clock_groups -asynchronous \
    -group [get_object_name [get_clocks clk_sys]] \
    -group [concat [get_object_name [get_clocks clk_sample_ext]] \
        [get_object_name [get_clocks clk_sample_ext_div_*]]] \
    -group [concat [get_object_name [get_clocks clk_sample_shared]] \
        [get_object_name [get_clocks clk_sample_shared_div_*]]] \
    -group [get_object_name [get_clocks clk_sample_dbg_*]]

set_clock_groups -logically_exclusive \
    -group [concat [get_object_name [get_clocks clk_sample_ext]] \
        [get_object_name [get_clocks clk_sample_ext_div_*]]] \
    -group [concat [get_object_name [get_clocks clk_sample_shared]] \
        [get_object_name [get_clocks clk_sample_shared_div_*]]]

#------------------------------------------------------------------------------
# RING OSCILLATOR CONSTRAINTS - *** may need adjustment for tech mapping ***
#------------------------------------------------------------------------------
# Ring oscillators must not be optimized by synthesis or place & route
# Set size_only to prevent buffering/optimization while allowing technology mapping
set_dont_touch [get_cells -hierarchical -filter "ref_name =~ entropy_ring_oscillator"]

# Prevent optimization of individual ring oscillator cells
# These must maintain their structure for proper oscillation
set_dont_touch [get_cells -hierarchical -filter "ref_name =~ prim_clock_nand2"]
set_dont_touch [get_cells -hierarchical -filter "ref_name =~ prim_buf*"]
set_dont_touch [get_cells -hierarchical -filter "ref_name =~ prim_stdmux2"]

# Break timing paths on ring oscillator feedback loops
# The feedback path is a combinational loop and is not a timed path
set_false_path -through [get_pins -hierarchical -filter "name =~ */ro/feedback"]

# Break timing on all ring oscillator internal paths
# These are asynchronous self-timed circuits
set_false_path -through [get_cells -hierarchical -filter "ref_name =~ entropy_ring_oscillator"]

# Shared ring oscillator fanout constraint.
# The shared RO has 12-way fanout to generator muxes.
set_max_fanout 12 [get_nets -hierarchical -filter \
    "name =~ *u_sampler_clocks/shared_ring_osc_clk"]

#------------------------------------------------------------------------------
# RIPPLE DIVIDER CONSTRAINTS
#------------------------------------------------------------------------------
# Sampler clocks: u_sampler_clocks/gen_sampler_clk[*]/u_sample_clk_divider
# (12 instances, 5 stages). Debug monitor: u_debug_monitor/u_ripple_divider
# (7 stages). Their Q pins are generated clocks, declared above. The Q-to-D
# toggle feedback is a same-stage synchronous data path and remains timed.

set_dont_touch [get_cells -hierarchical -filter "ref_name =~ entropy_ripple_divider"]

#------------------------------------------------------------------------------
# METASTABLE SAMPLING CONSTRAINTS
#------------------------------------------------------------------------------

# The sampling flip-flop (u_smpl) captures metastable events from the
# asynchronous ring oscillator; those events are the entropy source
# Disable timing checks on the data input to the sampling flip-flop
set_false_path -to [get_pins -hierarchical -filter "name =~ *u_noise_source*/u_smpl/d_i"]

# First stage of synchronizer (u_sync0) receives potentially metastable data
# Break input timing path to allow metastability to settle
set_false_path -to [get_pins -hierarchical -filter "name =~ *u_noise_source*/u_sync0/d_i"]

# Note: sync1 (second synchronizer stage) has normal timing constraints
# This allows checking that the synchronized output meets timing

#------------------------------------------------------------------------------
# DECORRELATOR SHIFT REGISTER
#------------------------------------------------------------------------------

# Optional multi-cycle relaxation for the decorrelator shift register;
# enable if single-cycle timing closure fails:
# set_multicycle_path -setup 2 -through [get_cells -hierarchical -filter "ref_name =~ entropy_decorrelator"]
# set_multicycle_path -hold 1 -through [get_cells -hierarchical -filter "ref_name =~ entropy_decorrelator"]

#------------------------------------------------------------------------------
# HEALTH TEST CONSTRAINTS
#------------------------------------------------------------------------------

# Health tests process data serially and may benefit from multi-cycle paths
# The tests operate on 32-bit words and iterate through bits
# Uncomment if timing closure is difficult on health test logic:
# set_multicycle_path -setup 2 -through [get_cells -hierarchical -filter "ref_name =~ entropy_health_test*"]
# set_multicycle_path -hold 1 -through [get_cells -hierarchical -filter "ref_name =~ entropy_health_test*"]

#------------------------------------------------------------------------------
# FIFO CONSTRAINTS
#------------------------------------------------------------------------------

# FIFO gray code pointer domain crossing paths are handled by the design
# with proper synchronization - treat as normal timing paths
# If timing issues arise, consider multi-cycle:
# set_multicycle_path -setup 2 -from [get_cells -hierarchical -filter "name =~ */entropy_fifo/wptr_q*"] \
#                                -to [get_cells -hierarchical -filter "name =~ */entropy_fifo/rptr_q*"]

#------------------------------------------------------------------------------
# APB INTERFACE CONSTRAINTS
#------------------------------------------------------------------------------

# APB interface input delays (relative to clk_sys)
# Assume APB signals arrive 30% of clock period after clock edge
set INPUT_DELAY [expr $PERIOD * $INPUT_DELAY_PERCENT]

set_input_delay -clock clk_sys $INPUT_DELAY [get_ports paddr_i*]
set_input_delay -clock clk_sys $INPUT_DELAY [get_ports pprot_i*]
set_input_delay -clock clk_sys $INPUT_DELAY [get_ports psel_i]
set_input_delay -clock clk_sys $INPUT_DELAY [get_ports penable_i]
set_input_delay -clock clk_sys $INPUT_DELAY [get_ports pwrite_i]
set_input_delay -clock clk_sys $INPUT_DELAY [get_ports pwdata_i*]
set_input_delay -clock clk_sys $INPUT_DELAY [get_ports pstrb_i*]

# APB interface output delays (relative to clk_sys)
# Outputs must be stable 30% of clock period before next clock edge
set OUTPUT_DELAY [expr $PERIOD * $OUTPUT_DELAY_PERCENT]

set_output_delay -clock clk_sys $OUTPUT_DELAY [get_ports pready_o]
set_output_delay -clock clk_sys $OUTPUT_DELAY [get_ports prdata_o*]
set_output_delay -clock clk_sys $OUTPUT_DELAY [get_ports pslverr_o]

# Interrupt output
set_output_delay -clock clk_sys $OUTPUT_DELAY [get_ports irq_o]

# Entropy stream outputs (synchronous to clk_sys)
set_output_delay -clock clk_sys $OUTPUT_DELAY [get_ports entropy_stream_data_o*]
set_output_delay -clock clk_sys $OUTPUT_DELAY [get_ports entropy_stream_vld_o*]

# Debug monitor output (asynchronous, driven by selected internal signal)
# No timing constraint needed - false path
set_false_path -to [get_ports signal_monitor_o]

#------------------------------------------------------------------------------
# RESET CONSTRAINTS
#------------------------------------------------------------------------------

# Asynchronous active-low reset
# Set as false path since it's asynchronous
set_false_path -from [get_ports rst_ni]

# If using synchronous reset internally, uncomment:
# set_input_delay -clock clk_sys 0.0 [get_ports rst_ni]

#------------------------------------------------------------------------------
# CASE ANALYSIS (CONSTANT PROPAGATION)
#------------------------------------------------------------------------------

# If certain configuration bits are known at synthesis time,
# they can be set as constants for optimization
# Example: If decorrelator is never bypassed:
# set_case_analysis 0 [get_pins -hierarchical -filter "name =~ */decorrelator_bypass_i*"]

#------------------------------------------------------------------------------
# DESIGN RULE CONSTRAINTS
#------------------------------------------------------------------------------

# Maximum transition time for signals (technology dependent)
# set_max_transition 0.5 [current_design]

# Maximum fanout for high fanout nets (clock, reset)
# set_max_fanout 64 [current_design]

# Maximum capacitance (technology dependent)
# set_max_capacitance 0.5 [current_design]

#------------------------------------------------------------------------------
# AREA CONSTRAINTS
#------------------------------------------------------------------------------

# Optimize for area after meeting timing
# set_max_area 0

#------------------------------------------------------------------------------
# VERIFICATION
#------------------------------------------------------------------------------

# Report timing on all clocks
# report_timing -from [all_registers] -to [all_registers]
# report_timing -from [all_inputs] -to [all_registers]
# report_timing -from [all_registers] -to [all_outputs]

# Report clock networks
# report_clocks
# report_clock_networks

#------------------------------------------------------------------------------
# END OF FILE
#------------------------------------------------------------------------------
