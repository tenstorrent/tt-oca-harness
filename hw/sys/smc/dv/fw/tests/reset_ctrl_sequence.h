/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef RESET_CTRL_SEQUENCE_H
#define RESET_CTRL_SEQUENCE_H

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

reset_unit__SS_CONFIG_t _SAVED_EXP_SS_CONFIG = {.w = 0};
reset_unit__SS_CONFIG_LOCK_t _SAVED_EXP_SS_CONFIG_LOCK = {.w = 0};
reset_unit__SS_COLD_RESET_N_t _SAVED_EXP_SS_COLD_RESET = {.w = 0};
reset_unit__SS_COLD_RESET_LOCK_t _SAVED_EXP_SS_COLD_RESET_LOCK = {.w = 0};

uint32_t get_exp_val_lockable_reg_write(uint32_t curr_val, uint32_t write_val, uint32_t lock_val) {
    uint32_t exp_val = curr_val;
    for (uint32_t bit = 0; bit < 32; bit++) {
        if ((lock_val & ((uint32_t)(0x1 << bit))) == 0) {
            exp_val &= ~((uint32_t)(0x1 << bit));
            exp_val |= (write_val & ((uint32_t)(0x1 << bit)));
        }
    }
    return exp_val;
}

int reset_ctrl_sequence(int hartid) {
    info_msg_s(hartid, "reset_ctrl_sequence Starting");

    // Bit bang all the registers in the reset unit
    reset_unit__SS_CONFIG_t reset_unit_ss_config = {.w = get_random_int()};
    reset_unit__SS_CONFIG_LOCK_t reset_unit_ss_config_lock = {.w = get_random_int()};
    reset_unit__SS_COLD_RESET_N_t reset_unit_ss_cold_reset_n = {.w = get_random_int()};
    reset_unit__SS_WARM_RESET_N_t reset_unit_ss_warm_reset_n = {.w = get_random_int()};
    reset_unit__SS_CONFIG_HOLD_t reset_unit_ss_config_hold = {.w = get_random_int()};
    reset_unit__SS_SRAM_HOLD_t reset_unit_ss_sram_hold = {.w = get_random_int()};
    reset_unit__SS_CRITICAL_HOLD_t reset_unit_ss_critical_hold = {.w = get_random_int()};
    reset_unit__SS_DEBUG_HOLD_t reset_unit_ss_debug_hold = {.w = get_random_int()};
    reset_unit__SS_FORCE_TO_REF_CLK_t reset_unit_ss_force_to_ref_clk = {.w = get_random_int()};
    reset_unit__SS_COLD_RESET_LOCK_t reset_unit_ss_cold_reset_lock = {.w = get_random_int()};

    // The expected values to later check against
    reset_unit__SS_WARM_RESET_N_t exp_reset_unit_ss_warm_reset_n = reset_unit_ss_warm_reset_n;
    reset_unit__SS_CONFIG_HOLD_t exp_reset_unit_ss_config_hold = reset_unit_ss_config_hold;
    reset_unit__SS_SRAM_HOLD_t exp_reset_unit_ss_sram_hold = reset_unit_ss_sram_hold;
    reset_unit__SS_CRITICAL_HOLD_t exp_reset_unit_ss_critical_hold = reset_unit_ss_critical_hold;
    reset_unit__SS_DEBUG_HOLD_t exp_reset_unit_ss_debug_hold = reset_unit_ss_debug_hold;
    reset_unit__SS_FORCE_TO_REF_CLK_t exp_reset_unit_ss_force_to_ref_clk =
        reset_unit_ss_force_to_ref_clk;

    // SS Config and SS Config Lock are special cases.
    reset_unit__SS_CONFIG_t exp_reset_unit_ss_config = {.w = 0};
    reset_unit__SS_CONFIG_LOCK_t exp_reset_unit_ss_config_lock = {.w = 0};

    exp_reset_unit_ss_config.w = get_exp_val_lockable_reg_write(
        _SAVED_EXP_SS_CONFIG.w, reset_unit_ss_config.w, _SAVED_EXP_SS_CONFIG_LOCK.w);
    // The Lock bits can only be set.  They can't be cleared.  So the expected cold_reset_lock bits
    // should be what was originally saved with the new bits that were set
    exp_reset_unit_ss_config_lock.w = _SAVED_EXP_SS_CONFIG_LOCK.w | reset_unit_ss_config_lock.w;

    // Cold Reset and Cold Reset Lock are special cases.
    reset_unit__SS_COLD_RESET_N_t exp_reset_unit_ss_cold_reset_n = {.w = 0};
    reset_unit__SS_COLD_RESET_LOCK_t exp_reset_unit_ss_cold_reset_lock = {.w = 0};

    exp_reset_unit_ss_cold_reset_n.w = get_exp_val_lockable_reg_write(
        _SAVED_EXP_SS_COLD_RESET.w, reset_unit_ss_cold_reset_n.w, _SAVED_EXP_SS_COLD_RESET_LOCK.w);
    // The Lock bits can only be set.  They can't be cleared.  So the expected cold_reset_lock bits
    // should be what was originally saved with the new bits that were set
    exp_reset_unit_ss_cold_reset_lock.w =
        _SAVED_EXP_SS_COLD_RESET_LOCK.w | reset_unit_ss_cold_reset_lock.w;

    // Save off the expectations for the next time this sequence gets called
    _SAVED_EXP_SS_CONFIG.w = exp_reset_unit_ss_config.w;
    _SAVED_EXP_SS_CONFIG_LOCK.w = exp_reset_unit_ss_config_lock.w;
    _SAVED_EXP_SS_COLD_RESET.w = exp_reset_unit_ss_cold_reset_n.w;
    _SAVED_EXP_SS_COLD_RESET_LOCK.w = exp_reset_unit_ss_cold_reset_lock.w;

    // Write to the scratch registers.  These can be used to check
    // against the top-level signals in the testbench
    write_scratch(7, exp_reset_unit_ss_config.w);
    write_scratch(9, exp_reset_unit_ss_cold_reset_n.w);
    write_scratch(10, exp_reset_unit_ss_warm_reset_n.w);
    write_scratch(11, exp_reset_unit_ss_config_hold.w);
    write_scratch(12, exp_reset_unit_ss_sram_hold.w);
    write_scratch(13, exp_reset_unit_ss_critical_hold.w);
    write_scratch(14, exp_reset_unit_ss_debug_hold.w);
    write_scratch(15, exp_reset_unit_ss_force_to_ref_clk.w);

    // Drive the signals at the top-level
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR, reset_unit_ss_config.w);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR, reset_unit_ss_config_lock.w);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR, reset_unit_ss_cold_reset_n.w);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR, reset_unit_ss_warm_reset_n.w);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_HOLD_BASE_ADDR, reset_unit_ss_config_hold.w);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_SRAM_HOLD_BASE_ADDR, reset_unit_ss_sram_hold.w);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_CRITICAL_HOLD_BASE_ADDR, reset_unit_ss_critical_hold.w);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_DEBUG_HOLD_BASE_ADDR, reset_unit_ss_debug_hold.w);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_FORCE_TO_REF_CLK_BASE_ADDR,
              reset_unit_ss_force_to_ref_clk.w);
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR, reset_unit_ss_cold_reset_lock.w);

    reset_unit__SS_CONFIG_t read_back_reset_unit_ss_config = {.w = 0};
    reset_unit__SS_CONFIG_LOCK_t read_back_reset_unit_ss_config_lock = {.w = 0};
    reset_unit__SS_COLD_RESET_N_t read_back_reset_unit_ss_cold_reset_n = {.w = 0};
    reset_unit__SS_WARM_RESET_N_t read_back_reset_unit_ss_warm_reset_n = {.w = 0};
    reset_unit__SS_CONFIG_HOLD_t read_back_reset_unit_ss_config_hold = {.w = 0};
    reset_unit__SS_SRAM_HOLD_t read_back_reset_unit_ss_sram_hold = {.w = 0};
    reset_unit__SS_CRITICAL_HOLD_t read_back_reset_unit_ss_critical_hold = {.w = 0};
    reset_unit__SS_DEBUG_HOLD_t read_back_reset_unit_ss_debug_hold = {.w = 0};
    reset_unit__SS_FORCE_TO_REF_CLK_t read_back_reset_unit_ss_force_to_ref_clk = {.w = 0};
    reset_unit__SS_COLD_RESET_LOCK_t read_back_reset_unit_ss_cold_reset_lock = {.w = 0};

    read_back_reset_unit_ss_config.w = read_reg(SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR);
    if (read_back_reset_unit_ss_config.w != exp_reset_unit_ss_config.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_config.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_config.w);
    }

    read_back_reset_unit_ss_config_lock.w =
        read_reg(SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR);
    if (read_back_reset_unit_ss_config_lock.w != exp_reset_unit_ss_config_lock.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_config_lock.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_config_lock.w);
    }

    read_back_reset_unit_ss_cold_reset_n.w =
        read_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR);
    if (read_back_reset_unit_ss_cold_reset_n.w != exp_reset_unit_ss_cold_reset_n.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_cold_reset_n.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_cold_reset_n.w);
    }

    read_back_reset_unit_ss_warm_reset_n.w =
        read_reg(SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR);
    if (read_back_reset_unit_ss_warm_reset_n.w != exp_reset_unit_ss_warm_reset_n.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_warm_reset_n.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_warm_reset_n.w);
    }

    read_back_reset_unit_ss_config_hold.w =
        read_reg(SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_HOLD_BASE_ADDR);
    if (read_back_reset_unit_ss_config_hold.w != exp_reset_unit_ss_config_hold.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_HOLD_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_config_hold.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_config_hold.w);
    }

    read_back_reset_unit_ss_sram_hold.w = read_reg(SMC_TOP_SMC_RESET_UNIT_SS_SRAM_HOLD_BASE_ADDR);
    if (read_back_reset_unit_ss_sram_hold.w != exp_reset_unit_ss_sram_hold.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_SRAM_HOLD_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_sram_hold.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_sram_hold.w);
    }

    read_back_reset_unit_ss_critical_hold.w =
        read_reg(SMC_TOP_SMC_RESET_UNIT_SS_CRITICAL_HOLD_BASE_ADDR);
    if (read_back_reset_unit_ss_critical_hold.w != exp_reset_unit_ss_critical_hold.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_CRITICAL_HOLD_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_critical_hold.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_critical_hold.w);
    }

    read_back_reset_unit_ss_debug_hold.w = read_reg(SMC_TOP_SMC_RESET_UNIT_SS_DEBUG_HOLD_BASE_ADDR);
    if (read_back_reset_unit_ss_debug_hold.w != exp_reset_unit_ss_debug_hold.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_DEBUG_HOLD_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_debug_hold.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_debug_hold.w);
    }

    read_back_reset_unit_ss_force_to_ref_clk.w =
        read_reg(SMC_TOP_SMC_RESET_UNIT_SS_FORCE_TO_REF_CLK_BASE_ADDR);
    if (read_back_reset_unit_ss_force_to_ref_clk.w != exp_reset_unit_ss_force_to_ref_clk.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_FORCE_TO_REF_CLK_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_force_to_ref_clk.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_force_to_ref_clk.w);
    }

    read_back_reset_unit_ss_cold_reset_lock.w =
        read_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR);
    if (read_back_reset_unit_ss_cold_reset_lock.w != exp_reset_unit_ss_cold_reset_lock.w) {
        raise_error_s(hartid, "Mismatch in SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR");
        raise_error_hex32_s(hartid, "Expected: ", exp_reset_unit_ss_cold_reset_lock.w);
        raise_error_hex32_s(hartid, "Actual: ", read_back_reset_unit_ss_cold_reset_lock.w);
    }

    info_msg_s(hartid, "reset_ctrl_sequence Ending");

    return 0;
}

#endif
