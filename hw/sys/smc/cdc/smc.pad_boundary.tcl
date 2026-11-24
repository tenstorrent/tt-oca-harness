# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# smc.pad_boundary.tcl - SMC pad-boundary CDC constraints
#
# CDC annotations on SMC's pad ports: the core2pad_o output ignore paths. They
# model core2pad_o as the chip boundary, which holds only where it is a top port. A
# parent whose pads sit between its ports and SMC (a padring, a bidirectional pad
# that feeds core2pad_o back into pad2core_i) constrains that boundary itself, so
# these apply at block top only. SMU states the same boundary for its own ports
# in hw/sys/smu/cdc/smu.pad_boundary.tcl.
################################################################################

if { [info procs cdc_is_block_top] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/hier_reuse_procs.tcl
}

if { ![cdc_is_block_top] } {
    puts "INFO: smc.pad_boundary: skipped under prefix '$::cdc_hier_prefix'; the parent\
          constrains the pad boundary"
    return
}

################################################################################
# GPIO core2pad OUTPUT IGNORE
################################################################################
# core2pad_o[*] outputs are constrained to ck_feedthru (async virtual clock).
# These are GPIO pad outputs driven from SMCCLK register fields; the crossing
# to ck_feedthru is expected and does not require synchronization since the
# destination is a primary output going to pads with no clock relationship.
set_cdc_ignore_path \
    -to [get_ports {core2pad_o*}] \
    -type cdc_crossing \
    -comments "GPIO core2pad outputs: SMCCLK register to async pad, no sync needed"

# The pads also reconverge at the padring mux, where per-pad DATA_CTRL fields
# (interface_enable, lsio_select, lsio_disable) choose between the core2pad
# register and a protocol source. No in-block flop receives the result, so the
# glitch checks on every output stop at the port. The exported SPI clock
# (core2pad_o[9]) and AVS clock (core2pad_o[49]) keep the clock-path glitch
# check: a select change while one of those clocks runs glitches the clock the
# external device samples on.
set core2pad_clock_pads [get_ports {core2pad_o[9] core2pad_o[49]}]
set_cdc_ignore_path \
    -to [get_ports {core2pad_o*}] \
    -type glitch \
    -comments "GPIO core2pad: padring mux reconvergence at a terminal output with no in-block receiver."
set_cdc_ignore_path \
    -to [remove_from_collection [get_ports {core2pad_o*}] $core2pad_clock_pads] \
    -type clock_path_glitch \
    -comments "GPIO core2pad: padring mux reconvergence at a terminal output; the exported SPI and AVS clock pads stay checked."
