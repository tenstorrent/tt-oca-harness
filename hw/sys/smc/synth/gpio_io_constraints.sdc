# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
# GPIO Interface
#
# Hierarchy-reusable: every port referenced here (core2pad_o*, pad2core_i*, *_en_o*,
# lsio_interface_select_o*) keeps the same name at the SMU top, so the file applies at
# both levels; only the SMCCLK references map through cdc_clk (SMCCLK -> SMUCLK).
if {[info procs cdc_is_block_top] eq ""} {
    source $::env(GIT_ROOT)/flows/synth/constraints/cdc_hier_procs.tcl
}
#
# These ports connect to an adopter-defined GPIO/padring implementation and
# should not be modeled as a single `SMCCLK`-synchronous interface.
# - `lsio_interface_select_o` is mode-control / pad ownership information.
# - `core2pad_o` can carry mixed-domain protocol traffic, including clocks.
# - `pad2core_en_o` / `core2pad_en_o` are pad enable / ownership controls.
# Use a generic feedthrough model at the block boundary, then add bit-specific
# clock intent separately where we know a GPIO is carrying a real protocol
# clock or other special signal.
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {lsio_interface_select_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {core2pad_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {core2pad_en_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {pad2core_en_o*}] -add_delay

# UART TX outputs — launched by PERIPHERALCLK-domain UART IP (combinational pass-through)
# GPIO indices: 12 = UART[0].TX, 16 = UART[1].TX, 20 = UART[2].TX, 24 = UART[3].TX
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o[12]"] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o[16]"] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o[20]"] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o[24]"] -add_delay

# UART RTS outputs — launched by PERIPHERALCLK-domain UART IP (combinational pass-through)
# GPIO indices: 13 = UART[0].RTS, 17 = UART[1].RTS, 21 = UART[2].RTS, 25 = UART[3].RTS
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o[13]"] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o[17]"] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o[21]"] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports "core2pad_o[25]"] -add_delay

# UART RX pads — output is constant 0, pad output driver disabled (input-only pads)
# GPIO indices: 11 = UART[0].RX, 15 = UART[1].RX, 19 = UART[2].RX, 23 = UART[3].RX
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[11]"] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[15]"] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[19]"] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[23]"] -add_delay

# UART CTS pads — output is constant 0, pad output driver disabled (input-only pads)
# GPIO indices: 14 = UART[0].CTS, 18 = UART[1].CTS, 22 = UART[2].CTS, 26 = UART[3].CTS
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[14]"] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[18]"] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[22]"] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[26]"] -add_delay


# Reserved
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[56]"] -add_delay

# System timer / OCTS — outputs driven from SMCCLK-domain timer (GPIO table).
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[58]"] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock [cdc_clk SMCCLK]] [get_ports "core2pad_o[59]"] -add_delay


# `pad2core_i` is a mixed-domain GPIO boundary. Apply the generic `ck_feedthru`
# feedthrough model only to bits whose source clock is not known at this level,
# and override bits that carry a real protocol clock or are source-synchronous
# to one so CDC/STA analyze them in their actual domain.
#
# Pinout reference (authoritative): doc/integrator/meta/ocah_gpio_table.adoc
# Padring connectivity (authoritative for RTL): hw/sys/smc/rtl/smc_peripherals/rtl/smc_padring.sv
#
# SPI clock-domain `pad2core_i` bits, per the adoc pinout and confirmed in the
# padring RTL:
#
#   Bit | Pinout function            | Padring net (smc_padring.sv)
#   ----+----------------------------+------------------------------------------
#   [0] | SPI.DATA[0]                | pad2core_i[0]  -> spi_rxd_o[0]
#   [1] | SPI.DATA[1]                | pad2core_i[1]  -> spi_rxd_o[1]
#   [2] | SPI.DATA[2]                | pad2core_i[2]  -> spi_rxd_o[2]
#   [3] | SPI.DATA[3]                | pad2core_i[3]  -> spi_rxd_o[3]
#   [4] | SPI.DATA[4]                | pad2core_i[4]  -> spi_rxd_o[4]
#   [5] | SPI.DATA[5]                | pad2core_i[5]  -> spi_rxd_o[5]
#   [6] | SPI.DATA[6]                | pad2core_i[6]  -> spi_rxd_o[6]
#   [7] | SPI.DATA[7]                | pad2core_i[7]  -> spi_rxd_o[7]
#   [9] | SPI.CLK                    | (generated clock SPICLK_IN_GPIO, stamped in
#       |                            |  hw/sys/smc/synth/constraints.sdc; excluded here to
#       |                            |  avoid re-adding an input delay)
#   [10]| SPI.DQS                    | pad2core_i[10] -> spi_rxds_o
#   [54]| SPI DQS Loopback           | pad2core_i[54] -> spi_mem_rebar_ipad_o
#
# SMC (via SEP cdns_spi) is the SPI master and emits the SPI clock on
# core2pad_o[9]; the external flash launches DATA[7:0] and DQS back source-
# synchronous to that clock. The data/DQS/loopback pads feed `spi_rxd_o[*]` /
# `spi_rxds_o` / `spi_mem_rebar_ipad_o` combinationally through `smc_padring`.
# Those outputs are already stamped on `SPICLK` in `hw/sys/smc/synth/constraints.sdc`, and
# `SPICLK`, `SPICLK_IN_GPIO` and `SPICLK_OUT_GPIO` share one async clock group, so the pad-to-pad
# feedthrough is an intra-group synchronous path rather than a CDC crossing.
set spi_pad2core_bits [get_ports {pad2core_i[0] pad2core_i[1] pad2core_i[2] pad2core_i[3] \
                                  pad2core_i[4] pad2core_i[5] pad2core_i[6] pad2core_i[7] \
                                  pad2core_i[10] pad2core_i[54]}]

# I2C pad inputs (GPIO 37–48): three controllers × {SCL, SDA, SMBus Alert, SMBus Suspend}.
# Padring: `smc_padring.sv` `gen_i2c_connections`; pinout: `doc/integrator/meta/ocah_gpio_table.adoc`.
# Open-drain bus lines are sampled by `i2c_core` synchronizers clocked from PERIPHERALCLK;
# modeling launch on PERIPHERALCLK aligns CDC/STA with the capture clock (same pattern as
# SPI pad2core bits on SPICLK_OUT_GPIO vs generic ck_feedthru).
set i2c_pad2core_bits [get_ports {pad2core_i[37] pad2core_i[38] pad2core_i[39] pad2core_i[40] \
                                  pad2core_i[41] pad2core_i[42] pad2core_i[43] pad2core_i[44] \
                                  pad2core_i[45] pad2core_i[46] pad2core_i[47] pad2core_i[48]}]

# System timer / OCTS pad inputs (GPIO 58–59): sampled by `system_timer_octs` on SMCCLK.
set system_timer_pad2core_bits [get_ports {pad2core_i[58] pad2core_i[59]}]

# SPI chip select input pad (GPIO 8) — SPI controller domain (SMCCLK register plane).
set gpio_spi_cs_pad [get_ports pad2core_i[8]]

# UART straps GPIO 11–26 (RX/TX/RTS/CTS): consumed by PERIPHERALCLK UART IP / padring.
set gpio_uart_pad2core [get_ports {pad2core_i[11] pad2core_i[12] pad2core_i[13] pad2core_i[14] \
    pad2core_i[15] pad2core_i[16] pad2core_i[17] pad2core_i[18] pad2core_i[19] pad2core_i[20] \
    pad2core_i[21] pad2core_i[22] pad2core_i[23] pad2core_i[24] pad2core_i[25] pad2core_i[26]}]

# AVS CLOCK + MDATA observe inputs (GPIO 49–50) — dual launch vs divider clocks (same pattern as SDATA [51]).
set gpio_avs_clk_mdata [get_ports {pad2core_i[49] pad2core_i[50]}]

# Thermal / isolate (52–53); PLL obs / PVT / straps (55–57); reserved / unbonded (61–64; NUM_GPIO_WRAPS = 65).
set gpio_misc_a [get_ports {pad2core_i[52] pad2core_i[53]}]
set gpio_misc_b [get_ports {pad2core_i[55] pad2core_i[56] pad2core_i[57]}]
set gpio_misc_c [get_ports {pad2core_i[61] pad2core_i[62] pad2core_i[63] pad2core_i[64]}]

# Bits excluded from generic ck_feedthru: SPI data/DQS/CS, SPICLK_IN_GPIO [9], I2C [37:48], AVS SDATA [51],
# system timer [58:59], UART block [11:26], I3C [27:36], AVS clk/mdata [49:50], misc [8] [52:53] [55:57] [61:64].
set pad2core_excluded $spi_pad2core_bits
set pad2core_excluded [add_to_collection $pad2core_excluded $i2c_pad2core_bits]
set pad2core_excluded [add_to_collection $pad2core_excluded [get_ports {pad2core_i[9] pad2core_i[51]}]]
set pad2core_excluded [add_to_collection $pad2core_excluded $system_timer_pad2core_bits]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_spi_cs_pad]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_uart_pad2core]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_avs_clk_mdata]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_misc_a]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_misc_b]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_misc_c]
set pad2core_generic [remove_from_collection [get_ports {pad2core_i*}] $pad2core_excluded]

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] $pad2core_generic -add_delay

# SPI data / DQS / DQS-loopback inputs: launched by the external flash synchronous to
# the SPI clock SMC emits on core2pad_o[9], SPICLK_OUT_GPIO (hw/sys/smc/synth/constraints.sdc).
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK_OUT_GPIO] $spi_pad2core_bits -add_delay

# SPI CS pad input (GPIO 8).
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]        -clock [get_clock [cdc_clk SMCCLK]] $gpio_spi_cs_pad -add_delay

# I2C pads — consumed by PERIPHERALCLK-domain synchronizers and receivers.
set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i2c_pad2core_bits -add_delay

# UART GPIO 11–26 — PERIPHERALCLK UART slice / padring.
set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $gpio_uart_pad2core -add_delay

# GPIO [51] AVS.SDATA — flops in AVS divider clock domain (`avs_sdata_capture`, interrupt detect).
# Legal mux modes match AVS GPIO clock intent on core2pad_o[49].
set avs_sdata_pad [get_ports pad2core_i[51]]
set_input_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_REFCLK] $avs_sdata_pad -add_delay
set_input_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK] $avs_sdata_pad -add_delay

# AVS CLOCK + MDATA observe (GPIO 49–50) — same legal AVS clock roots as SDATA.
set_input_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_REFCLK] $gpio_avs_clk_mdata -add_delay
set_input_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK] $gpio_avs_clk_mdata -add_delay

set_input_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock [cdc_clk SMCCLK]] $system_timer_pad2core_bits -add_delay

# Misc GPIO inputs — thermal/isolate and observability (SMCCLK); reserved/unbonded (generic feedthru).
set_input_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock [cdc_clk SMCCLK]] [add_to_collection $gpio_misc_a $gpio_misc_b] -add_delay
set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] $gpio_misc_c -add_delay
