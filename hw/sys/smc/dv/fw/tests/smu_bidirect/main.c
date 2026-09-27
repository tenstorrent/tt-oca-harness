/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdbool.h>
#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"

#define SEP_SHARED_ADDR 0x0000000010802000ULL
#define SEP_SHARED_START_ADDR 0x0000000010802000ULL
#define SEP_SHARED_END_ADDR 0x000000001080203FULL
#define SMC_TO_SEP_PATTERN 0xC001CAFEu
#define SMC_TO_SEP_DONE_PATTERN 0xD0E0F00Du
#define SEP_READY_PATTERN 0x51EAD001u
#define SEP_TO_SMC_ACK_PATTERN 0x5E9ACCE5u
#define SEP_ACK_SCRATCH_NUM 12u
#define SEP_ACK_TIMEOUT_ITERS 1000000u
#define SMC_OUTBOUND_FILTER_BASE 0x00000000C0016000ULL
#define FILTER_CONFIG_OFFSET 0x0ULL
#define FILTER_START_OFFSET 0x8ULL
#define FILTER_END_OFFSET 0x10ULL
#define SMC_FILTER_CONFIG 0x0000000101030013ULL

static inline void write32(uint64_t addr, uint32_t value) {
    volatile uint32_t *p = (volatile uint32_t *)(uintptr_t)addr;
    *p = value;
}

static inline uint32_t read32(uint64_t addr) {
    volatile uint32_t *p = (volatile uint32_t *)(uintptr_t)addr;
    return *p;
}

static inline void write64(uint64_t addr, uint64_t value) {
    volatile uint64_t *p = (volatile uint64_t *)(uintptr_t)addr;
    *p = value;
}

static void open_smc_outbound_sep_shared_window(void) {
    write64(SMC_OUTBOUND_FILTER_BASE + FILTER_START_OFFSET, SEP_SHARED_START_ADDR);
    write64(SMC_OUTBOUND_FILTER_BASE + FILTER_END_OFFSET, SEP_SHARED_END_ADDR);
    write64(SMC_OUTBOUND_FILTER_BASE + FILTER_CONFIG_OFFSET, SMC_FILTER_CONFIG);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static bool wait_for_shared(uint32_t expected) {
    for (uint32_t i = 0; i < SEP_ACK_TIMEOUT_ITERS; ++i) {
        if (read32(SEP_SHARED_ADDR) == expected) {
            return true;
        }
    }
    return false;
}

int main(void) {
    smu_sep_dv_test_bringup();
    open_smc_outbound_sep_shared_window();

    /*
     * No SEP_READY rendezvous here: the harness releases the SMC only after
     * the SEP has finished its CSR/filter setup and is polling the shared
     * address.
     */
    write32(SEP_SHARED_ADDR, SMC_TO_SEP_PATTERN);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    if (!wait_for_shared(SMC_TO_SEP_PATTERN)) {
        test_fail(0);
        while (true) {
            __asm__ volatile("wfi");
        }
    }

    for (uint32_t i = 0; i < SEP_ACK_TIMEOUT_ITERS; ++i) {
        if (read_scratch(SEP_ACK_SCRATCH_NUM) == SEP_TO_SMC_ACK_PATTERN) {
            write32(SEP_SHARED_ADDR, SMC_TO_SEP_DONE_PATTERN);
            __asm__ volatile("fence iorw, iorw" ::: "memory");

            if (wait_for_shared(SMC_TO_SEP_DONE_PATTERN)) {
                test_pass(0);
            } else {
                test_fail(0);
            }

            while (true) {
                __asm__ volatile("wfi");
            }
        }
    }

    test_fail(0);
    while (true) {
        __asm__ volatile("wfi");
    }

    return 0;
}

int secondary_main(void) {
    return main();
}
