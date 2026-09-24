/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * 32-bit stores into one half of a 64-bit register word.
 *
 * The core replicates a word store across both halves of its 64-bit data bus
 * and strobes only the addressed half, so a store of all ones to one half puts
 * ones on every byte lane of the other half with its strobe clear. Each target
 * below has its writable fields in the half the store does not address; they
 * must read back unchanged. The bench's SEP_IN master zero-fills unstrobed
 * lanes, so it cannot make this case.
 *
 * Every target is stored to while each of its fields differs from all ones, so
 * a store that leaked through a clear strobe would show on the read-back.
 */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define ALL_ONES 0xFFFFFFFFu

static uint32_t held;

static inline void io_fence(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

/* Store all ones to store_half; field_half must read what it read before. */
static void hold_other_half(const char *name, uint64_t field_half, uint64_t store_half) {
    uint32_t before = read_reg(field_half);
    write_reg(store_half, ALL_ONES);
    io_fence();
    uint32_t after = read_reg(field_half);
    if (after != before) {
        info_msg_s(0, name);
        raise_fatal_hex32_s(0, "field half changed under an unstrobed store, now ", after);
    }
    held++;
}

/* The same, where store_half has no field: it must also still read 0. */
static void hold_beside_empty_half(const char *name, uint64_t field_half, uint64_t store_half) {
    hold_other_half(name, field_half, store_half);
    uint32_t empty = read_reg(store_half);
    if (empty != 0) {
        info_msg_s(0, name);
        raise_fatal_hex32_s(0, "empty half reads ", empty);
    }
}

static void take_mutex(int idx, const char *why) {
    uint32_t got = read_reg(SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR(idx));
    if ((got & 1u) == 0) {
        info_msg_hex32_s(0, "MUTEX index ", (uint32_t)idx);
        raise_fatal_s(0, why);
    }
}

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        hold_beside_empty_half("CLOCK_GATE_CONTROL",
                               SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR,
                               SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR + 4);
        hold_beside_empty_half("HANG_DET_SYS_AXI_CTRL",
                               SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR,
                               SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR + 4);
        hold_beside_empty_half("HANG_DET_SEP_AXI_CTRL",
                               SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR,
                               SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR + 4);
        hold_beside_empty_half("HANG_DET_DATA_ACCEL_CTRL",
                               SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR,
                               SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR + 4);
        hold_beside_empty_half("DEBUG_CTRL", SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR,
                               SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR + 4);
        /*
         * The boot sequence leaves RESET_TIMEOUT with timeout_mode set, which an
         * all-ones leak would not change, so the store runs against the reset
         * value and the boot value goes back afterwards. No software reset is
         * requested meanwhile. The upper half is read-only live status.
         */
        uint32_t reset_timeout = read_reg(SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR);
        write_reg(SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR, 0);
        io_fence();
        hold_other_half("RESET_TIMEOUT", SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR,
                        SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR + 4);
        write_reg(SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR, reset_timeout);
        io_fence();
        info_msg_hex32_s(0, "held beside the stored half: ", held);

        /*
         * A MUTEX read takes the mutex and any write gives it back, whichever
         * half it selects (cpu_ctrl.rdl), so a store to the upper half cannot
         * leave it held: while free it must stay free, and while held it must
         * release it.
         */
        for (int i = 0; i < SMC_TOP_SMC_CPU_CTRL_MUTEX_NUM; i++) {
            uint64_t upper = SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR(i) + 4;
            write_reg(upper, ALL_ONES);
            io_fence();
            take_mutex(i, "not free after an upper-half store while free");
            write_reg(upper, ALL_ONES);
            io_fence();
            take_mutex(i, "not released by an upper-half store while held");
            write_reg(SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR(i), 0);
            io_fence();
        }
        info_msg_hex32_s(
            0, "mutexes free after upper-half stores: ", (uint32_t)SMC_TOP_SMC_CPU_CTRL_MUTEX_NUM);

        /*
         * region_attrs keeps cacheable and valid in the upper half. A store to
         * the lower half takes offset[31:12] and must leave the upper half 0;
         * the region stays invalid, so the new offset remaps nothing. The bench
         * reads the word back and restores it.
         */
        uint64_t attrs = SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR(0);
        uint32_t upper_before = read_reg(attrs + 4);
        write_reg(attrs, ALL_ONES);
        io_fence();
        uint32_t lower = read_reg(attrs);
        uint32_t upper = read_reg(attrs + 4);
        if (lower != 0xFFFFF000u) {
            raise_fatal_hex32_s(0, "region_attrs lower half did not take the store: ", lower);
        }
        if (upper != upper_before) {
            raise_fatal_hex32_s(0, "region_attrs upper half changed: ", upper);
        }
        info_msg_hex32_s(0, "region_attrs upper half held at ", upper);

        test_pass(0);
    }

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int secondary_main(void) {
    return main();
}
