# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMC GPIO/padring input and output delays.
#
# Shared with the closed block flow, which sources this file from both the SMC
# and the SMU timing setups rather than keeping its own copy. Reads
# $clock_periods(...); the sourcing flow populates that array first.
#
# Every GPIO index is claimed by exactly one section: an interface owns a bit,
# or the bit falls through to the generic feedthrough model built by
# subtraction below. Nothing here re-stamps a port another section already
# constrained, so no section has to undo an earlier one.
#
# Two things are constrained per interface, and they do not interact:
#
#   the I/O delay    fixes where the interface sits in the cycle. The
#                    *_ext_max values are the budget reserved outside the
#                    block; they absorb clock latency as well as board flight,
#                    so 0.6 of the period failed at ss on the equivalent SMU
#                    paths.
#   the data check   fixes how far the bits of one interface may separate from
#                    each other. Each group carries its own window, so no
#                    group's is derived from another's.
#
# All times are picoseconds, matching flows/synth/constraints/clock_periods.tcl.
#
# Pinout reference (authoritative): doc/integrator/meta/ocah_gpio_table.adoc.
# Padring connectivity is adopter-defined and lives outside this repo; the bit
# assignments below are cross-checked against the pinout table only.
# `pad2core_i` is NUM_GPIO_WRAPS wide (61 bonded + 4 unbonded = 65), so 64 is
# the last bit; pinout rows 65+ are dedicated JTAG/REFCLK pads, not GPIO bits.
#-----------------------------------------------------------------------------

if {![array exists ::clock_periods]} {
    error "smc_gpio_io_delays.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

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
set spi_out_skew   200
set spi_in_skew    200
set uart_skew     2000
set i3c_skew      2000
set i2c_bus_skew  2000
set i2c_smb_skew  2000

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

# CS in (GPIO 8) is sampled in the SPI controller's SMCCLK register plane.
set_input_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [smc_gpio_ports pad2core_i [list $spi_cs_in_bit]] -add_delay

# Hold the write data bus together. Every ordered pair is checked with a
# negative setup, so neither bit is declared the earlier one and the two
# opposing checks bound the separation both ways. There is no -hold anywhere
# in this file: set_data_check carries an implicit multicycle multiplier of 0,
# which measures its hold check against the following edge, so the reversed
# setup check stands in.
foreach a {0 1 2 3 4 5 6 7} {
    foreach b {0 1 2 3 4 5 6 7} {
        if {$a == $b} { continue }
        set_data_check -clock [get_clock SPICLK] -from [get_ports "core2pad_o\[$a\]"] -to [get_ports "core2pad_o\[$b\]"] -setup [expr -$spi_out_skew]
    }
}

# Read data plus DQS on GPIO 10 -- the capture edge comes from DQS, so its
# spread against the data bits is the one that matters.
foreach a {0 1 2 3 4 5 6 7 10} {
    foreach b {0 1 2 3 4 5 6 7 10} {
        if {$a == $b} { continue }
        set_data_check -clock [get_clock SPICLK_IN_GPIO] -from [get_ports "pad2core_i\[$a\]"] -to [get_ports "pad2core_i\[$b\]"] -setup [expr -$spi_in_skew]
    }
}

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

# core2pad_o on the RX and CTS bits is tied to 1'b0 with the output driver
# disabled; the pad still belongs to the UART slice, so it is stamped on
# SMCCLK rather than left in the ck_feedthru group.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [smc_gpio_ports core2pad_o $uart_rx_cts_bits] -add_delay

# The TX and RTS pads are outputs, so their pad2core_i side carries no traffic;
# it stays on PERIPHERALCLK with the rest of the slice.
set_input_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [smc_gpio_ports pad2core_i $uart_tx_rts_bits] -add_delay

# TX against RTS per channel. UART is asynchronous and has no real skew
# requirement, so these windows are loose enough not to bind; they exist so the
# knob is in the same place as the others.
#             {TX  RTS}
foreach pair {{12  13}
              {16  17}
              {20  21}
              {24  25}} {
    lassign $pair tx rts
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "core2pad_o\[$tx\]"]  -to [get_ports "core2pad_o\[$rts\]"] -setup [expr -$uart_skew]
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "core2pad_o\[$rts\]"] -to [get_ports "core2pad_o\[$tx\]"]  -setup [expr -$uart_skew]
}

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

# SCL against SDA, per controller, in both directions.
#             {SCL SDA}
foreach pair {{27  28}
              {29  30}
              {31  32}
              {33  34}
              {35  36}
              {63  64}} {
    lassign $pair scl sda
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "core2pad_o\[$scl\]"] -to [get_ports "core2pad_o\[$sda\]"] -setup [expr -$i3c_skew]
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "core2pad_o\[$sda\]"] -to [get_ports "core2pad_o\[$scl\]"] -setup [expr -$i3c_skew]
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "pad2core_i\[$scl\]"] -to [get_ports "pad2core_i\[$sda\]"] -setup [expr -$i3c_skew]
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "pad2core_i\[$sda\]"] -to [get_ports "pad2core_i\[$scl\]"] -setup [expr -$i3c_skew]
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

# SCL against SDA and SMB_A against SMB_D, per controller. The outbound checks
# are on the enables for the reason above; the inbound ones are on the data,
# which the pad does drive.
#             {SCL SDA  SMB_A SMB_D}
foreach quad {{37  38   39    40}
              {41  42   43    44}
              {45  46   47    48}} {
    lassign $quad scl sda smba smbd
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "core2pad_en_o\[$scl\]"]  -to [get_ports "core2pad_en_o\[$sda\]"]  -setup [expr -$i2c_bus_skew]
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "core2pad_en_o\[$sda\]"]  -to [get_ports "core2pad_en_o\[$scl\]"]  -setup [expr -$i2c_bus_skew]
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "core2pad_en_o\[$smba\]"] -to [get_ports "core2pad_en_o\[$smbd\]"] -setup [expr -$i2c_smb_skew]
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "core2pad_en_o\[$smbd\]"] -to [get_ports "core2pad_en_o\[$smba\]"] -setup [expr -$i2c_smb_skew]
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "pad2core_i\[$scl\]"]     -to [get_ports "pad2core_i\[$sda\]"]     -setup [expr -$i2c_bus_skew]
    set_data_check -clock [get_clock PERIPHERALCLK] -from [get_ports "pad2core_i\[$sda\]"]     -to [get_ports "pad2core_i\[$scl\]"]     -setup [expr -$i2c_bus_skew]
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
