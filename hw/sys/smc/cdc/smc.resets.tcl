# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
##########
# RESETS
##########

# Refer to markdowns/reset_relationships.md for the reset hierarchy and assertion sequences.
#
# Hierarchy-reusable: anchored paths go through cdc_inst; port resets go through
# cdc_create_port_reset (skipped at the parent when
# ::cdc_reset_alias maps the name onto a parent reset, created on the instance pin when
# the reset is genuinely internal there, e.g. JTAG_RESET from DTP). Assertion-sequence
# name lists map through cdc_rst / cdc_clk.

if { [info procs cdc_conv_apply] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/hier_reuse_procs.tcl
}

set reset_unit_hier u_smc_peripherals/u_smc_reset_unit
set cpu_ctrl_wrap_hier u_smc_cpu_wrapper/u_smc_cpu_ctrl_wrap

# top level reset ports for smc.sv
cdc_create_port_reset POWERGOOD_RESET_N "powergood_i" -async -type reset -value low -disable_assertions_db
cdc_create_port_reset COLD_RESET_PAD_N "rst_cold_ni" -async -type reset -value low -disable_assertions_db
cdc_create_port_reset COOL_RESET_FROM_PIN_N "rst_cool_n_from_pin_i" -async -type reset -value low -disable_assertions_db

cdc_create_port_reset TELEMETRY_RESET_N "rst_telemetry_ni" -both -type reset -value low -disable_assertions_db
cdc_create_port_reset SCAN_RESET_N "scan_rst_ni" -both -type reset -value low -disable_assertions_db
cdc_create_port_reset JTAG_RESET "smc_cpu_jtag_reset_i" -both -type reset -value high -disable_assertions_db


# POWERGOOD_STABLE_N is the 32-stage async-assert / sync-deassert stretched version of POWERGOOD_RESET_N
# produced by u_powergood_stretcher_n0_scan inside smc_reset_ctrl.

create_reset -name POWERGOOD_STABLE_N [cdc_inst "${reset_unit_hier}/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/gen_rst_sync_stage\[31\].u_sync_dffr/q_d/Q"] -async -type reset -value low -disable_assertions_db

set_reset_groups \
    -name POWERGOOD_RESET_GROUP \
    -group {POWERGOOD_RESET_N POWERGOOD_STABLE_N}

# Pad cold reset after the 32-cycle REFCLK deglitch. Through the rstbypass mux it is the
# async reset of the cold-reset extend counter and gates stable_cold_rst_no.
create_reset -name COLD_RESET_DEGLITCH_N [cdc_inst "${reset_unit_hier}/u_smc_reset_ctrl/cold_rst_deglitch_to_rstbypass/Q"] -async -type reset -value low -disable_assertions_db

# COLD RESET GROUP
create_reset -name COLD_RESET_N [cdc_inst "${reset_unit_hier}/u_smc_reset_ctrl/stable_cold_rst_no"] -async -type reset -value low -disable_assertions_db
create_reset -name COLD_RESET_N_REF_CLK [cdc_inst "${reset_unit_hier}/rst_cold_ref_n"] -both -type reset -value low -disable_assertions_db
create_reset -name COLD_RESET_N_SMC_CLK [cdc_inst "${reset_unit_hier}/rst_cold_smc_n"] -both -type reset -value low -disable_assertions_db

set_reset_groups \
    -name COLD_RESET_GROUP \
    -group {COLD_RESET_N COLD_RESET_N_REF_CLK COLD_RESET_N_SMC_CLK}


# PRIMARY_RESET_N is the wire that feeds the async reset pin of the syncs that create PRIMARY_RESET_N_REF_CLK, PRIMARY_RESET_N_SMC_CLK, and PRIMARY_RESET_N_PERIPH_CLK
create_reset -name PRIMARY_RESET_N [cdc_inst "${reset_unit_hier}/u_smc_reset_ctrl/rst_primary_no"] -both -type reset -value low -disable_assertions_db
create_reset -name PRIMARY_RESET_N_REF_CLK [cdc_inst "${reset_unit_hier}/rst_primary_ref_clk_no"] -both -type reset -value low -disable_assertions_db
create_reset -name PRIMARY_RESET_N_SMC_CLK [cdc_inst "${reset_unit_hier}/rst_primary_smc_clk_no"] -both -type reset -value low -disable_assertions_db
create_reset -name PRIMARY_RESET_N_PERIPH_CLK [cdc_inst "${reset_unit_hier}/rst_primary_periph_clk_no"] -both -type reset -value low -disable_assertions_db

set_reset_groups \
    -name PRIMARY_RESET_GROUP \
    -group {PRIMARY_RESET_N PRIMARY_RESET_N_REF_CLK PRIMARY_RESET_N_SMC_CLK PRIMARY_RESET_N_PERIPH_CLK}


# COOL RESET FROM FLR UNIT - Primary Chiplet Only
create_reset -name COOL_RESET_FROM_FLR_N [cdc_inst "${reset_unit_hier}/u_smc_cool_reset_wrap/rst_cool_no"] -both -type reset -value low -disable_assertions_db

# assign fuse_reset_stalled_n = fuse_reset_n & ~boot_stall_sticky;
# Final efuse-released reset after boot-stall processing inside u_smc_peripherals
create_reset -name FUSE_RESET_N [cdc_inst "u_smc_peripherals/fuse_reset_n_o"] -both -type reset -value low -disable_assertions_db

# assign rst_warm_no = wdt_reset_n && rst_primary_no && fuse_reset_ni;
create_reset -name WARM_RESET_N [cdc_inst "${reset_unit_hier}/u_smc_reset_ctrl/rst_warm_no"] -async -type reset -value low -disable_assertions_db
create_reset -name WARM_RESET_N_SMC_CLK [cdc_inst "${reset_unit_hier}/rst_warm_smc_clk_no"] -both -type reset -value low -disable_assertions_db

create_reset -name CORE_RESET_0_N [cdc_inst "${cpu_ctrl_wrap_hier}/core_reset_n_n0_scan_o[0]"] -async -type reset -value low -disable_assertions_db
create_reset -name CORE_RESET_1_N [cdc_inst "${cpu_ctrl_wrap_hier}/core_reset_n_n0_scan_o[1]"] -async -type reset -value low -disable_assertions_db
create_reset -name CORE_RESET_2_N [cdc_inst "${cpu_ctrl_wrap_hier}/core_reset_n_n0_scan_o[2]"] -async -type reset -value low -disable_assertions_db
create_reset -name CORE_RESET_3_N [cdc_inst "${cpu_ctrl_wrap_hier}/core_reset_n_n0_scan_o[3]"] -async -type reset -value low -disable_assertions_db

create_reset -name CLUSTER_UNCORE_RESET_N [cdc_inst "${cpu_ctrl_wrap_hier}/cluster_uncore_reset_n_n0_scan_o"] -async -type reset -value low -disable_assertions_db

set_reset_groups \
    -name WARM_RESET_GROUP \
    -group {WARM_RESET_N WARM_RESET_N_SMC_CLK}

# SW written
create_reset -name DEBUG_RESET_N [cdc_inst "${cpu_ctrl_wrap_hier}/debug_reset_n_o"] -async -type reset -value low -disable_assertions_db

# Debug-module per-hart reset: hartResetReg_<n> (set by the debugger via dmcontrol.hartreset,
# async-cleared by chip reset) drives io_hartResetReq_<n>, an active-high reset to hart <n>.
create_reset -name DM_HART_RESET_0 [cdc_inst "u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/dmOuter/dmOuter/hartResetReg_0/Q"] -async -type reset -value high -disable_assertions_db
create_reset -name DM_HART_RESET_1 [cdc_inst "u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/dmOuter/dmOuter/hartResetReg_1/Q"] -async -type reset -value high -disable_assertions_db
create_reset -name DM_HART_RESET_2 [cdc_inst "u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/dmOuter/dmOuter/hartResetReg_2/Q"] -async -type reset -value high -disable_assertions_db
create_reset -name DM_HART_RESET_3 [cdc_inst "u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/dmOuter/dmOuter/hartResetReg_3/Q"] -async -type reset -value high -disable_assertions_db

# Mem Init Done
create_reset -name MEM_INIT_DONE_N [cdc_inst "u_smc_cpu_wrapper/u_smc_cpu/init_mem_complete/Q"] -async -type reset -value low -disable_assertions_db

create_reset -name WDT_RESET_N [cdc_inst "${reset_unit_hier}/u_smc_reset_ctrl/rst_wdt_no"] -both -type reset -value low -disable_assertions_db
create_reset -name WDT_RESET_N_SMC_CLK [cdc_inst "${reset_unit_hier}/rst_wdt_smc_clk_no"] -both -type reset -value low -disable_assertions_db

set_reset_groups \
    -name WDT_RESET_GROUP \
    -group {WDT_RESET_N WDT_RESET_N_SMC_CLK}

# BOOT_STALL_N: GPIO 60 drives the raw boot stall signal which is captured by 'boot_stall_sticky'.
# This is intended to halt the regular boot process by holding fuse reset asserted until gpio 60 is deasserted.
create_reset -name BOOT_STALL_N [cdc_inst "u_smc_peripherals/boot_stall_sticky/Q"] -async -type reset -value high

############################################################
# SYNC-CHAIN TAIL RESETS (async-assert, sync-deassert)
############################################################
# Each prim_sync_reset instance is a WIDTH-deep chain of prim_metastab_hardened_dffr
# flops with i_RN tied to the external async reset. Assertion is async (all stages
# flush to 0 on the same cycle); deassertion is clocked (1'b1 walks through the
# chain over WIDTH destination-clock cycles). The chain output is its own reset
# domain: same root as the parent but a later deassertion edge. Downstream flops
# whose async-reset pin is driven by the chain output live in THIS domain, not
# the parent's, so VC-RDC needs them declared as explicit reset boundaries.
#
# Without these declarations the tool emits SETUP_RESET_INFERRED_SOFT on the
# last-stage Q, and RDC analyses downstream of each chain waste effort tracing
# back through the sync chain to the raw parent. Declaring the tail as a named
# reset + an assertion sequence from the parent gives a clean boundary.
#
# Stamps are placed on gen_rst_sync_stage[WIDTH-1].u_sync_dffr/q_d/Q (the last
# stage flop Q).

# u_refclk_counter (inside u_smc_cpu_ctrl_wrap): prim_refclk_count_w_cdc syncs the
# primary reset into the SMCCLK (write) and REFCLK (read) domains using two WIDTH=16
# prim_sync_reset chains. Source: hw/common/ocah_prim/rtl/prim_refclk_count_w_cdc.sv.
create_reset -name PRIMARY_RESET_N_REFCNT_SMC_CLK [cdc_inst "${cpu_ctrl_wrap_hier}/u_refclk_counter/u_prst_wr_clk_domain_sync/gen_rst_sync_stage\[15\].u_sync_dffr/q_d/Q"] -both -type reset -value low -disable_assertions_db
create_reset -name PRIMARY_RESET_N_REFCNT_REF_CLK [cdc_inst "${cpu_ctrl_wrap_hier}/u_refclk_counter/u_prst_rd_clk_domain_sync/gen_rst_sync_stage\[15\].u_sync_dffr/q_d/Q"] -both -type reset -value low -disable_assertions_db

# AVS-bus controller internal reset syncs (hw/ip/avsbus_controller/rtl/avsbus_controller.sv).
# ResetSyncStages = 6 for all four chains.
#   u_clk_div/u_reset_sync : sync of rst_clk_div_ni = powergood_stable into pre_div_clk.
#   apb_clk_reset_sync   : sync of rst_ni = rst_primary_periph_clk_n into clk_reg_i  (PERIPHCLK).
#   avs_clk_reset_sync   : sync of rst_ni = rst_primary_periph_clk_n into avs_clk    (divided from REFCLK).
#   pre_div_clk_reset_sync : sync of rst_ni = rst_primary_periph_clk_n into apb_ref_muxed_clk.
create_reset -name AVS_CLK_DIV_RESET_N [cdc_inst "u_smc_peripherals/u_avsbus_controller/u_clk_div/u_reset_sync/gen_rst_sync_stage\[5\].u_sync_dffr/q_d/Q"] -both -type reset -value low -disable_assertions_db
create_reset -name AVS_APB_CLK_RESET_N [cdc_inst "u_smc_peripherals/u_avsbus_controller/u_apb_clk_reset_sync/gen_rst_sync_stage\[5\].u_sync_dffr/q_d/Q"] -both -type reset -value low -disable_assertions_db
create_reset -name AVS_CLK_RESET_N [cdc_inst "u_smc_peripherals/u_avsbus_controller/u_avs_clk_reset_sync/gen_rst_sync_stage\[5\].u_sync_dffr/q_d/Q"] -both -type reset -value low -disable_assertions_db
create_reset -name AVS_PRE_DIV_CLK_RESET_N [cdc_inst "u_smc_peripherals/u_avsbus_controller/u_pre_div_clk_reset_sync/gen_rst_sync_stage\[5\].u_sync_dffr/q_d/Q"] -both -type reset -value low -disable_assertions_db

##############################
# RESET ASSERTION SEQUENCES #
##############################

# POWERGOOD_STABLE_N low ==> all chip clocks are absent.
#
# Design knowledge: POWERGOOD_STABLE_N asserting (low) means the chip power
# rail is not yet stable / has dropped, which means every clock generator
# feeding the SMC is also unavailable. This includes clocks sourced from
# dedicated top-level input ports (REFCLK, SMCCLK, PERIPHERALCLK,
# TELEMETRYCLK, SPICLK, ck_feedthru) and
# the JTAG TCK — no external agent can drive clocks into an
# unpowered die, and JTAG in this design shares the chip power rail.
#
# Declaring this to VC-RDC lets the tool prune RDC crossings whose capture
# clock is gated by POWERGOOD_STABLE: when the reset asserts the clock has
# no edges, so there is nothing to meta-stabilise.
# Clock names map through cdc_clk (SMCCLK -> SMUCLK at the parent); reset names are the
# SMC-internal ones and keep their names at every level.
set_rdc_define_assertion_sequence \
    -from_reset {POWERGOOD_STABLE_N} \
    -to_clock [cdc_clk {REFCLK SMCCLK PERIPHERALCLK TELEMETRYCLK JTAG_TCK SPICLK ck_feedthru}]

# For active-low AND gates, any input asserting (going low) forces the output
# to assert (go low). Therefore child resets always assert when parent resets
# assert, making RDC paths from parent domain to child domain safe.
#
# -to_reset asserts before (or simultaneously with) -from_reset.

# POWERGOOD => COLD: when powergood deasserts there is no power and no clocks in
# the system, so cold reset is guaranteed to also be asserted.
set_rdc_define_assertion_sequence \
    -from_reset {POWERGOOD_RESET_N POWERGOOD_STABLE_N} \
    -to_reset {COLD_RESET_DEGLITCH_N COLD_RESET_N COLD_RESET_N_REF_CLK COLD_RESET_N_SMC_CLK}

# COLD_DEGLITCH => COLD: outside scan mode, the deglitched reset asserting forces
# stable_cold_rst_no low at once; the extend counter only delays release.
set_rdc_define_assertion_sequence \
    -from_reset {COLD_RESET_DEGLITCH_N} \
    -to_reset {COLD_RESET_N COLD_RESET_N_REF_CLK COLD_RESET_N_SMC_CLK}

# COLD/COOL_FLR => PRIMARY: when cold or cool-from-FLR asserts, primary asserts
# simultaneously via the AND gate (rst_primary_no = stable_cold_rst_n && ... && rst_cool_from_flr_ni).
# COOL_RESET_FROM_PIN_N is excluded because it goes through a 32-cycle deglitch
# before reaching the AND gate, so PRIMARY does not assert simultaneously.
set_rdc_define_assertion_sequence \
    -from_reset {COLD_RESET_N COLD_RESET_N_REF_CLK COLD_RESET_N_SMC_CLK COOL_RESET_FROM_FLR_N} \
    -to_reset {PRIMARY_RESET_N PRIMARY_RESET_N_REF_CLK PRIMARY_RESET_N_SMC_CLK PRIMARY_RESET_N_PERIPH_CLK}

# PRIMARY => FUSE:
set_rdc_define_assertion_sequence \
    -from_reset {PRIMARY_RESET_N PRIMARY_RESET_N_REF_CLK PRIMARY_RESET_N_SMC_CLK PRIMARY_RESET_N_PERIPH_CLK} \
    -to_reset {FUSE_RESET_N}

# PRIMARY/WDT/FUSE => WARM: when primary, wdt, or fuse asserts, warm asserts.
set_rdc_define_assertion_sequence \
    -from_reset {PRIMARY_RESET_N PRIMARY_RESET_N_REF_CLK PRIMARY_RESET_N_SMC_CLK PRIMARY_RESET_N_PERIPH_CLK WDT_RESET_N WDT_RESET_N_SMC_CLK FUSE_RESET_N} \
    -to_reset {WARM_RESET_N WARM_RESET_N_SMC_CLK}

# WARM_SMC_CLK => per-core and cluster-uncore resets.
set_rdc_define_assertion_sequence \
    -from_reset {WARM_RESET_N_SMC_CLK} \
    -to_reset {CORE_RESET_0_N CORE_RESET_1_N CORE_RESET_2_N CORE_RESET_3_N CLUSTER_UNCORE_RESET_N}

# POWERGOOD => AVS clock-divider internal u_reset_sync.
# u_clk_div.rst_ni = rst_clk_div_ni = powergood_stable (POWERGOOD_STABLE_N).
# POWERGOOD_RESET_N listed too so the raw pad is accepted as an equivalent root.
set_rdc_define_assertion_sequence \
    -from_reset {POWERGOOD_RESET_N POWERGOOD_STABLE_N} \
    -to_reset {AVS_CLK_DIV_RESET_N}

############################################################
# SYNC-CHAIN TAIL ASSERTION SEQUENCES
############################################################
# For each prim_sync_reset instance the async-reset input (i_RN) is tied to the
# parent reset, and the i_RN pin drives every flop in the chain. Therefore the
# parent asserting forces every chain-stage Q to 0 on the same cycle, including
# the last-stage Q we stamped above. Declare the sequence explicitly so VC-RDC
# does not have to infer it across the sync chain.

# PRIMARY_RESET_N_SMC_CLK => u_refclk_counter prstb syncs (both clock domains).
set_rdc_define_assertion_sequence \
    -from_reset {PRIMARY_RESET_N_SMC_CLK} \
    -to_reset {PRIMARY_RESET_N_REFCNT_SMC_CLK PRIMARY_RESET_N_REFCNT_REF_CLK}

# PRIMARY_PERIPH_CLK => AVS APB/AVS/PRE_DIV clock reset syncs.
# u_avsbus_controller.rst_ni = rst_primary_periph_clk_n (PRIMARY_RESET_N_PERIPH_CLK)
# is the async input to all three chains. Any upstream reset that asserts
# PRIMARY_RESET_N_PERIPH_CLK (see COLD/COOL_FLR=>PRIMARY sequence above) will
# transitively assert these three via this sequence.
set_rdc_define_assertion_sequence \
    -from_reset {PRIMARY_RESET_N_PERIPH_CLK} \
    -to_reset {AVS_APB_CLK_RESET_N AVS_CLK_RESET_N AVS_PRE_DIV_CLK_RESET_N}

# Telemetry reset pairing. rst_telemetry_ni is a chip-level input that passes through smu.sv
# and smc.sv untouched. The integrator guide requires the adopter to assert it whenever
# PRIMARY asserts and never on its own (doc/integrator/src/smu-smc.adoc, Telemetry and Debug
# Integration). This command declares PRIMARY -> TELEMETRY, which the ATB FIFOs also get from
# their rst_ni & rst_telemetry_ni reset and the afvalid synchronizers rely on the adopter for.
# The TELEMETRY -> PRIMARY direction is an asyncrst_assert_sequence below.
set_rdc_define_assertion_sequence \
    -from_reset {PRIMARY_RESET_N PRIMARY_RESET_N_SMC_CLK PRIMARY_RESET_N_REF_CLK PRIMARY_RESET_N_PERIPH_CLK} \
    -to_reset {TELEMETRY_RESET_N}


# asyncrst_assert_sequence needs this app var (default off); set before first use.
set_app_var rdc_new_asyncrst_commands true

# WARM / FUSE => PRIMARY
# Both are only asserted when the SMU is going into reset, as WARM is asserted by
# WDT (WDT trigger indicates system will go into reset) and FUSE is asserted during boot,
# so system is in reset
asyncrst_assert_sequence \
    -from_reset {WARM_RESET_N WARM_RESET_N_SMC_CLK FUSE_RESET_N} \
    -to_reset {PRIMARY_RESET_N PRIMARY_RESET_N_SMC_CLK}

# TELEMETRY => PRIMARY: rst_telemetry_ni never asserts without PRIMARY (see the telemetry
# pairing above), so the telemetry receivers are in reset whenever their ATB FIFO is.
asyncrst_assert_sequence \
    -from_reset {TELEMETRY_RESET_N} \
    -to_reset {PRIMARY_RESET_N PRIMARY_RESET_N_SMC_CLK}

# AVS_APB_CLK_RESET_N => PRIMARY: AVS_APB is the prim_sync_reset tail of primary_periph,
# so it co-asserts with primary (cannot assert without it).
asyncrst_assert_sequence \
    -from_reset {AVS_APB_CLK_RESET_N} \
    -to_reset {PRIMARY_RESET_N PRIMARY_RESET_N_PERIPH_CLK}
