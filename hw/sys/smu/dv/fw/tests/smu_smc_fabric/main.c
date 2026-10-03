// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// SMC ROM image for smu_smc_fabric_test: every hart writes and reads back
// words in SEP SRAM over smc_out and at an address that leaves on ext_out, and
// reports through the SMC scratch words, which hart 0 collects into a verdict.

#include <stdint.h>

#include "smu_smc_fabric_protocol.h"

#define SCRATCH(idx) \
    ((volatile uint32_t *)(uintptr_t)(SMCFAB_SCRATCH_BASE + (idx)*SMCFAB_SCRATCH_STRIDE))

static inline void fence(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

// Stores every word before the first load, so each hart has several
// transfers in flight on the path, then reads each back.
static uint32_t round_trip(uintptr_t base, uint64_t tag) {
    volatile uint64_t *word = (volatile uint64_t *)base;
    uint32_t bad = 0;
    for (uint32_t i = 0; i < SMCFAB_WORDS; i++) {
        word[i] = tag | i;
    }
    fence();
    for (uint32_t i = 0; i < SMCFAB_WORDS; i++) {
        if (word[i] != (tag | i)) {
            bad |= 1u << i;
        }
    }
    return bad;
}

int main(uint64_t hart) {
    if (hart == 0) {
        *SCRATCH(SMCFAB_STATUS_IDX) = SMCFAB_READY;
        fence();
    }
    while (*SCRATCH(SMCFAB_GO_IDX) != SMCFAB_GO) {
    }

    uint64_t tag = (uint64_t)SMCFAB_PATTERN | (hart << 16);
    uintptr_t offset = (uintptr_t)(hart * SMCFAB_HART_STRIDE);
    uint32_t bad = round_trip((uintptr_t)SMCFAB_SEP_TARGET + offset, tag);
    bad |= round_trip((uintptr_t)SMCFAB_EXT_TARGET + offset, tag | 0x100u) << 8;
    if (*SCRATCH(SMCFAB_GO_IDX) != SMCFAB_GO) {
        bad |= 1u << 16;
    }
    *SCRATCH(SMCFAB_HART_IDX + hart) =
        bad ? (SMCFAB_HART_FAIL | bad) : (SMCFAB_HART_PASS | (uint32_t)hart);
    fence();

    if (hart == 0) {
        uint32_t status = SMCFAB_TEST_PASS;
        for (uint32_t h = 0; h < SMCFAB_NUM_HARTS; h++) {
            uint32_t result;
            do {
                result = *SCRATCH(SMCFAB_HART_IDX + h);
            } while ((result & 0xFFFF0000u) != SMCFAB_HART_PASS &&
                     (result & 0xFFFF0000u) != SMCFAB_HART_FAIL);
            if (result != (SMCFAB_HART_PASS | h)) {
                status = SMCFAB_TEST_FAIL;
            }
        }
        *SCRATCH(SMCFAB_STATUS_IDX) = status;
        fence();
    }
    for (;;) {
        __asm__ volatile("wfi");
    }
}
