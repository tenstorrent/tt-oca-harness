# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMC GPIO/padring input and output delays.
#
# Every GPIO index is claimed by exactly one section: an interface owns a bit,
# or the bit falls through to the generic feedthrough model built by
# subtraction below. Nothing here re-stamps a port another section already
# constrained, so no section has to undo an earlier one.
#
# Two things are constrained per interface:
#
#   the I/O delay    fixes where the interface sits in the cycle. The
#                    *_ext_max values are the budget reserved outside the
#                    block; they absorb clock latency as well as board flight,
#                    so 0.6 of the period failed at ss on the equivalent SMU
#                    paths. This is the contract an adopter reads, and it is
#                    what scales if a clock period changes.
#   the *_bal window fixes how far the bits of one interface may separate from
#                    each other, by holding every bit of a bus to one arrival
#                    window: bits sharing a window cannot differ by more than
#                    its width. Each group carries its own, so no group's is
#                    derived from another's.
#
# Where a bus has both, the window is an exception and overrides the I/O
# delay's check on that path -- the window is what the tool enforces there.
# The I/O delay still stands: it is the published external budget, and on an
# input it is the only thing covering the pad's other fanout, the GPIO CSR
# capture in the SMCCLK domain, which no window here targets.
#
# All times are picoseconds.
#
# Pinout reference (authoritative): doc/integrator/meta/ocah_gpio_table.adoc.
# Padring connectivity is adopter-defined and lives outside this repo; the bit
# assignments below are cross-checked against the pinout table only.
# `pad2core_i` is NUM_GPIO_WRAPS wide (61 bonded + 4 unbonded = 65), so 64 is
# the last bit; pinout rows 65+ are dedicated JTAG/REFCLK pads, not GPIO bits.
#
# NOTE:
# THE NUMBERS BELOW ARE STARTING POINTS, NOT A SPECIFICATION. Every budget,
# window and skew here is a fraction of a clock period or a round figure; none
# came from a device datasheet, a board, or a measured path. Replace them with
# values that match your own system before using this for anything but a smoke
# run:
#
#   *_ext_max        how much of the period the external device and board may
#                    consume -- from the device datasheet plus board flight
#   *_skew           how far the bits of one interface may separate -- from the
#                    protocol's own timing requirement
#   *_bal_min/max    the arrival window each bus is held to on the way in; the
#                    width is the balance place-and-route is asked to deliver
#   i3c_tsco         target clock-to-data-out limit -- from your I3C revision
#   i3c_tsco_cycles  cycles the target FSM spends between sampling SCL and
#                    launching SDA -- read it off the RTL; it is not a timing
#                    property and no constraint can change it
#-----------------------------------------------------------------------------

if {![array exists ::clock_periods]} {
    error "smc_gpio_io_delays.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}

# Block-top only: these delays anchor the block's own ports. Replayed under a parent
# they are internal nets whose launch and capture domains come from the real fabric.
if {[cdc_is_block_top]} {

# Budget reserved outside the block, per interface.
set spi_ext_max        [expr $clock_periods(SPICLK_PERIOD)        * 0.4]
set uart_ext_max       [expr $clock_periods(PERIPHERALCLK_PERIOD) * 0.4]
set i3c_ext_max        [expr $clock_periods(PERIPHERALCLK_PERIOD) * 0.4]
set i2c_ext_max        [expr $clock_periods(PERIPHERALCLK_PERIOD) * 0.4]
set avs_refclk_ext_max [expr $clock_periods(REFCLK_PERIOD)        * 0.4]
set avs_periph_ext_max [expr $clock_periods(PERIPHERALCLK_PERIOD) * 0.4]

# Arrival spread each group of pads may cover. Every one stands alone; to give
# a single controller a window of its own, put a literal on its line in place
# of the variable.
set spi_out_bal_min     0
set spi_out_bal_max   200
set spi_in_bal_min      0
set spi_in_bal_max    200
set i3c_bal_min         0
set i3c_bal_max      2000
set i2c_bal_min         0
set i2c_bal_max      2000


# I3C tSCO -- the interval from the controller driving SCL to this target
# driving SDA. Held at 8 ns against a 12 ns spec maximum; the rest is margin
# for the pad and board delay outside this block. The response is registered,
# so the interval is
#
#   tSCO  =  t(SCL pad -> sampling flop)
#          + I3C_TSCO_CYCLES x T(i3c core clock, a gated PERIPHERALCLK)
#          + t(SDA launch flop -> pad)
#
# Only the two hops are STA's to enforce; the cycle count is a property of the
# target FSM and is set here so the hop budget follows from it. Measuring the
# real turnaround needs a gate-level simulation, not a constraint.
set i3c_tsco        8000
set i3c_tsco_cycles    1
set i3c_tsco_hop_min   0
set i3c_tsco_io [expr { $i3c_tsco - $i3c_tsco_cycles * $clock_periods(PERIPHERALCLK_PERIOD) }]

if { $i3c_tsco_io > 0 } {
    # Split what is left evenly between the inbound and outbound hop.
    set i3c_tsco_hop_max [expr { $i3c_tsco_io / 2 }]
    # The inbound hop is the same path the balance window already bounds, so
    # keep one exception per path and let whichever is tighter set it.
    if { $i3c_tsco_hop_max < $i3c_bal_max } { set i3c_bal_max $i3c_tsco_hop_max }
} else {
    set i3c_tsco_hop_max 0
    puts "WARNING: i3c tSCO: $i3c_tsco_cycles cycles of\
          $clock_periods(PERIPHERALCLK_PERIOD) ps leave nothing of the $i3c_tsco ps budget\
          for the pad hops; no I/O constraint can recover it, so none is applied"
}

########################################################
# Bit ownership
########################################################
# Indices are GPIO bit numbers. A bit listed here is stamped by its interface
# section below and is excluded from the generic model; anything unlisted
# takes the generic feedthrough stamp.

# SPI (GPIO 0-10, 54). SMC is the master and emits SPI.CLK on core2pad_o[9];
# the external flash launches DATA[7:0] and DQS back source-synchronous to it,
# arriving on pad2core_i and captured against SPICLK_IN_GPIO.
set spi_out_bits  {0 1 2 3 4 5 6 7 8 54}
set spi_in_bits   {0 1 2 3 4 5 6 7 10 54}
set spi_cs_in_bit 8

# UART (GPIO 11-26), four channels at 11+4u: RX, TX, RTS, CTS.
set uart_tx_rts_bits {12 13 16 17 20 21 24 25}
set uart_rx_cts_bits {11 14 15 18 19 22 23 26}

# I3C (GPIO 27-36 for I3C[0] and I3C[2:5], 63-64 for the unbonded I3C[1]).
set i3c_bits {27 28 29 30 31 32 33 34 35 36 63 64}

# I2C (GPIO 37-48), three controllers at 37+4i x {SCL, SDA, SMB_A, SMB_D}.
set i2c_bits {37 38 39 40 41 42 43 44 45 46 47 48}

# AVS (GPIO 49-51): CLK out on 49, MDATA out on 50, SDATA in on 51.
set avs_obs_in_bits {49 50 51}

# Ports that carry a generated clock and must not also carry an I/O delay.
# - the below contains SPI_CLK (9) and AVS_CLK (49)
set clk_source_out_bits {9 49}

# Bits with a fixed launch/capture domain that no protocol section above owns.
set sys_timer_bits {58 59}
set reserved_out_bit 56
set misc_smc_in_bits {52 53 55 56 57}
set misc_feedthru_in_bits {61 62}

proc smc_gpio_ports {sig bits} {
    set names {}
    foreach b $bits { lappend names "${sig}\[$b\]" }
    return [get_ports $names]
}

########################################################
# Generic feedthrough model
########################################################
# These ports connect to an adopter-defined GPIO/padring implementation and
# should not be modeled as a single `SMCCLK`-synchronous interface:
# - `lsio_interface_select_o` is mode-control / pad ownership information.
# - `core2pad_o` can carry mixed-domain protocol traffic, including clocks.
# - `pad2core_en_o` / `core2pad_en_o` are pad enable / ownership controls.
# Bits whose source clock is not known at this level take the generic model;
# the interface sections below own the rest.

set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] [get_ports {lsio_interface_select_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] [get_ports {pad2core_en_o*}] -add_delay

set core2pad_claimed [concat $spi_out_bits $uart_tx_rts_bits $uart_rx_cts_bits \
                             $i3c_bits $i2c_bits {50} $sys_timer_bits \
                             [list $reserved_out_bit] $clk_source_out_bits]
set core2pad_generic [remove_from_collection [get_ports {core2pad_o*}] \
                                             [smc_gpio_ports core2pad_o $core2pad_claimed]]
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] $core2pad_generic -add_delay

set core2pad_en_generic [remove_from_collection [get_ports {core2pad_en_o*}] \
                                                [smc_gpio_ports core2pad_en_o $i2c_bits]]
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] $core2pad_en_generic -add_delay

set pad2core_claimed [concat $spi_in_bits [list $spi_cs_in_bit] {9} \
                             $uart_tx_rts_bits $uart_rx_cts_bits $i3c_bits $i2c_bits \
                             $avs_obs_in_bits $sys_timer_bits \
                             $misc_smc_in_bits $misc_feedthru_in_bits]
set pad2core_generic [remove_from_collection [get_ports {pad2core_i*}] \
                                             [smc_gpio_ports pad2core_i $pad2core_claimed]]
set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] $pad2core_generic -add_delay

########################################################
# SPI -- GPIO 0-10, 54
########################################################
# DATA[7:0] = spi_txd_i, CS = spi_cs_n_i, DQS loopback = spi_mem_rebar_opad_i,
# all launched on SPICLK. core2pad_o[9] carries SPICLK_OUT_GPIO and takes no
# output delay, so it is absent from spi_out_bits.
foreach bit $spi_out_bits {
    set_output_delay -max $spi_ext_max -clock [get_clock SPICLK] [get_ports "core2pad_o\[$bit\]"] -add_delay
    set_output_delay -min 0            -clock [get_clock SPICLK] [get_ports "core2pad_o\[$bit\]"] -add_delay
}

# DATA[7:0], DQS and the DQS loopback return source-synchronous to the clock
# SMC emitted on core2pad_o[9]; SMC declares SPICLK_IN_GPIO on pad2core_i[9].
foreach bit $spi_in_bits {
    set_input_delay -max $spi_ext_max -clock [get_clock SPICLK_IN_GPIO] [get_ports "pad2core_i\[$bit\]"] -add_delay
    set_input_delay -min 0            -clock [get_clock SPICLK_IN_GPIO] [get_ports "pad2core_i\[$bit\]"] -add_delay
}

# The read bus only passes through this block: the pads land on `spi_rxd_o`,
# `spi_rxds_o` and `spi_mem_rebar_ipad_o`, and the controller that captures
# them lives in SEP. There is no endpoint here to time against, so the balance
# window bounds the padring hop port to port. SPICLK_IN_GPIO is not usable as a
# destination -- pad2core_i[9] drives nothing, so that clock has no fanout.
foreach bit $spi_in_bits {
    switch -- $bit {
        10      { set spi_bal_dst spi_rxds_o }
        54      { set spi_bal_dst spi_mem_rebar_ipad_o }
        default { set spi_bal_dst "spi_rxd_o\[$bit\]" }
    }
    set_max_delay $spi_in_bal_max -from [get_ports "pad2core_i\[$bit\]"] -to [get_ports $spi_bal_dst]
    set_min_delay $spi_in_bal_min -from [get_ports "pad2core_i\[$bit\]"] -to [get_ports $spi_bal_dst]
}

# Hold the write bus together: every bit is held to one launch window, so no
# two can separate by more than its width. This overrides the output delay's
# check on these pads; the output delay above remains the external budget.
foreach bit $spi_out_bits {
    set_max_delay $spi_out_bal_max -from [get_clocks SPICLK] -to [get_ports "core2pad_o\[$bit\]"]
    set_min_delay $spi_out_bal_min -from [get_clocks SPICLK] -to [get_ports "core2pad_o\[$bit\]"]
}

# CS in (GPIO 8) is sampled in the SPI controller's SMCCLK register plane.
set_input_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [smc_gpio_ports pad2core_i [list $spi_cs_in_bit]] -add_delay

########################################################
# UART -- GPIO 11-26, four channels at 11+4u
########################################################
# TX = uart_tx_i[u], RTS = uart_rts_n_i[u], both launched by the PERIPHERALCLK
# UART IP.
foreach bit $uart_tx_rts_bits {
    set_output_delay -max $uart_ext_max -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o\[$bit\]"] -add_delay
    set_output_delay -min 0             -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o\[$bit\]"] -add_delay
}

# RX -> uart_rx_o[u], CTS -> uart_cts_n_o[u], captured by the same IP.
foreach bit $uart_rx_cts_bits {
    set_input_delay -max $uart_ext_max -clock [get_clock PERIPHERALCLK] [get_ports "pad2core_i\[$bit\]"] -add_delay
    set_input_delay -min 0             -clock [get_clock PERIPHERALCLK] [get_ports "pad2core_i\[$bit\]"] -add_delay
}

# TX and RTS carry no skew requirement of their own -- UART is asynchronous

# core2pad_o on the RX and CTS bits is tied to 1'b0 with the output driver
# disabled; the pad still belongs to the UART slice, so it is stamped on
# SMCCLK rather than left in the ck_feedthru group.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [smc_gpio_ports core2pad_o $uart_rx_cts_bits] -add_delay

# The TX and RTS pads are outputs, so their pad2core_i side carries no traffic;
# it stays on PERIPHERALCLK with the rest of the slice.
set_input_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [smc_gpio_ports pad2core_i $uart_tx_rts_bits] -add_delay

########################################################
# I3C -- GPIO 27-36, 63-64
########################################################
# Bidirectional open-drain/push-pull SCL and SDA. The controller builds SCL
# from a PERIPHERALCLK counter and never uses the pad SCL as a clock, so both
# directions stay on PERIPHERALCLK.
foreach bit $i3c_bits {
    set_output_delay -max $i3c_ext_max -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o\[$bit\]"] -add_delay
    set_output_delay -min 0            -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o\[$bit\]"] -add_delay

    set_input_delay -max $i3c_ext_max -clock [get_clock PERIPHERALCLK] [get_ports "pad2core_i\[$bit\]"] -add_delay
    set_input_delay -min 0            -clock [get_clock PERIPHERALCLK] [get_ports "pad2core_i\[$bit\]"] -add_delay
}

# Hold SCL and SDA together on the way out. This window also carries the
# outbound half of tSCO: the budget above tightens $i3c_bal_max when the cycle
# count leaves less room than the skew figure does. It overrides the output
# delay's check on these pads; the output delay remains the external budget.
foreach bit $i3c_bits {
    set_max_delay $i3c_bal_max -from [get_clocks PERIPHERALCLK] -to [get_ports "core2pad_o\[$bit\]"]
    set_min_delay $i3c_bal_min -from [get_clocks PERIPHERALCLK] -to [get_ports "core2pad_o\[$bit\]"]
    set_max_delay $i3c_bal_max -from [get_clocks PERIPHERALCLK] -to [get_ports "core2pad_en_o\[$bit\]"]
    set_min_delay $i3c_bal_min -from [get_clocks PERIPHERALCLK] -to [get_ports "core2pad_en_o\[$bit\]"]
}

# And hold them together on the way in.
foreach bit $i3c_bits {
    set_max_delay $i3c_bal_max -from [get_ports "pad2core_i\[$bit\]"] -to [get_clocks PERIPHERALCLK]
    set_min_delay $i3c_bal_min -from [get_ports "pad2core_i\[$bit\]"] -to [get_clocks PERIPHERALCLK]
}

########################################################
# I2C -- GPIO 37-48, three controllers at 37+4i x {SCL, SDA, SMB_A, SMB_D}
########################################################
# core2pad_o is tied to 1'b0 across all twelve bits and the pad is pulled up on
# the board, so the launched edge leaves on core2pad_en_o. Both buses are
# stamped: the data bit to keep the constant port out of the ck_feedthru group,
# the enable because it is the one carrying I2C timing.
foreach bit $i2c_bits {
    set_output_delay -max $i2c_ext_max -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o\[$bit\]"] -add_delay
    set_output_delay -min 0            -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o\[$bit\]"] -add_delay

    set_output_delay -max $i2c_ext_max -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_en_o\[$bit\]"] -add_delay
    set_output_delay -min 0            -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_en_o\[$bit\]"] -add_delay

    set_input_delay -max $i2c_ext_max -clock [get_clock PERIPHERALCLK] [get_ports "pad2core_i\[$bit\]"] -add_delay
    set_input_delay -min 0            -clock [get_clock PERIPHERALCLK] [get_ports "pad2core_i\[$bit\]"] -add_delay
}

# Hold the four bus lines of a controller together on the way out. The launched
# edge leaves on the enable, so that is the bus bounded here. This overrides
# the output delay's check on the enables; the output delay stays the external
# budget, and the data bits keep theirs unshadowed.
foreach bit $i2c_bits {
    set_max_delay $i2c_bal_max -from [get_clocks PERIPHERALCLK] -to [get_ports "core2pad_en_o\[$bit\]"]
    set_min_delay $i2c_bal_min -from [get_clocks PERIPHERALCLK] -to [get_ports "core2pad_en_o\[$bit\]"]
}

# And on the way in.
foreach bit $i2c_bits {
    set_max_delay $i2c_bal_max -from [get_ports "pad2core_i\[$bit\]"] -to [get_clocks PERIPHERALCLK]
    set_min_delay $i2c_bal_min -from [get_ports "pad2core_i\[$bit\]"] -to [get_clocks PERIPHERALCLK]
}

########################################################
# AVS -- GPIO 49-51
########################################################
# MDATA = avs_mdata_i, launched source-synchronous to the AVS clock on GPIO 49.
# The two source modes are logically exclusive, so both are stamped and the
# tool picks the active one. MDATA is the only data bit of the interface, so it
# has nothing to skew against and carries no data check. core2pad_o[49] is the
# emitted AVS clock and takes no output delay.
set_output_delay -max $avs_refclk_ext_max -clock [get_clock AVS_CLK_FROM_REFCLK_GPIO]        [get_ports {core2pad_o[50]}] -add_delay
set_output_delay -min 0                   -clock [get_clock AVS_CLK_FROM_REFCLK_GPIO]        [get_ports {core2pad_o[50]}] -add_delay
set_output_delay -max $avs_periph_ext_max -clock [get_clock AVS_CLK_FROM_PERIPHERALCLK_GPIO] [get_ports {core2pad_o[50]}] -add_delay
set_output_delay -min 0                   -clock [get_clock AVS_CLK_FROM_PERIPHERALCLK_GPIO] [get_ports {core2pad_o[50]}] -add_delay

# CLOCK and MDATA observe inputs (49-50) and SDATA (51) flop in the AVS divider
# clock domain; the legal mux modes give each two possible roots.
set_input_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]        -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_REFCLK]        [smc_gpio_ports pad2core_i $avs_obs_in_bits] -add_delay
set_input_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK] [smc_gpio_ports pad2core_i $avs_obs_in_bits] -add_delay

########################################################
# Fixed-domain pads with no protocol section
########################################################
# Reserved (56) and system timer / OCTS (58-59) outputs are driven from the
# SMCCLK-domain timer; the matching inputs are sampled by `system_timer_octs`.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [smc_gpio_ports core2pad_o [list $reserved_out_bit]] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [smc_gpio_ports core2pad_o $sys_timer_bits] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [smc_gpio_ports pad2core_i $sys_timer_bits] -add_delay

# Thermal / isolate (52-53) and PLL obs / PVT / straps (55-57) are sampled in
# the SMCCLK plane; the unbonded pads (61-62) have no known source clock.
set_input_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK]     [smc_gpio_ports pad2core_i $misc_smc_in_bits] -add_delay
set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] [smc_gpio_ports pad2core_i $misc_feedthru_in_bits] -add_delay

}
# end of block-top-only smc_gpio_io_delays
