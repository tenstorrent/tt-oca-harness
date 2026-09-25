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
/* read/write allowed, entry_enabled, allow_ns, allow_burst; bit 31 clear. */
#define FILTER_LOWER_LANES \
    ((uint32_t)(FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | \
                FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm | \
                FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm | \
                FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm | \
                FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm))
/* Bit 31 only: locked's lane in the upper half. */
#define FILTER_LOCKED_LANE ((uint32_t)(FILTER_CTRL__FILTER_CONFIG__LOCKED_bm >> 32))

static uint32_t held;

static inline void io_fence(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

/* Store value to store_half; field_half must read what it read before. */
static void hold_other_half_with(const char *name, uint64_t field_half, uint64_t store_half,
                                 uint32_t value) {
    uint32_t before = read_reg(field_half);
    write_reg(store_half, value);
    io_fence();
    uint32_t after = read_reg(field_half);
    if (after != before) {
        info_msg_s(0, name);
        raise_fatal_hex32_s(0, "field half changed under an unstrobed store, now ", after);
    }
    held++;
}

/* Store all ones to store_half; field_half must read what it read before. */
static void hold_other_half(const char *name, uint64_t field_half, uint64_t store_half) {
    hold_other_half_with(name, field_half, store_half, ALL_ONES);
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
        /*
         * WDT_TIMEOUT_RESET is 32 bits wide at 0x58 and nothing is declared at
         * 0x5C, so a store there writes no field; its singlepulse core-reset
         * fields carry the replicated ones with their strobes clear.
         */
        hold_beside_empty_half("WDT_TIMEOUT_RESET",
                               SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_RESET_BASE_ADDR,
                               SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_RESET_BASE_ADDR + 4);

        /*
         * Outbound filter 14's FILTER_CONFIG keeps only locked (bit 63) in its
         * upper half. An upper-half store with bit 31 clear writes 0 there,
         * which woset ignores, while the lower lanes carry read/write allowed,
         * entry_enabled, allow_ns and allow_burst with their strobes clear. A
         * lower-half store with only bit 31 set puts a one on locked's lane with
         * its strobe clear and writes the lower fields, entry_enabled included,
         * to 0; the reset lower half is then written back.
         */
        uint64_t filter = SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(14);
        uint32_t filter_lower = read_reg(filter);
        hold_other_half_with("FILTER_CONFIG lower lanes", filter, filter + 4, FILTER_LOWER_LANES);
        hold_other_half_with("FILTER_CONFIG locked lane", filter + 4, filter, FILTER_LOCKED_LANE);
        write_reg(filter, filter_lower);
        io_fence();
        if (read_reg(filter) != filter_lower || read_reg(filter + 4) != 0) {
            raise_fatal_hex32_s(0, "FILTER_CONFIG not restored: ", read_reg(filter));
        }

        /*
         * The zeroer starts on a CTRL_STATUS write only while SIZE is non-zero,
         * so an upper-half store with SIZE 0 starts nothing; INT_EN's lane
         * carries a one with its strobe clear, and the zeroer stays idle.
         */
        if (read_reg(SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR) != 0) {
            raise_fatal_s(0, "zeroer SIZE not 0");
        }
        hold_other_half_with("ZEROER CTRL_STATUS", SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR,
                             SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR + 4, 1u);
        if (read_reg(SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR + 4) != 0) {
            raise_fatal_s(0, "zeroer busy after an upper-half store with SIZE 0");
        }
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
