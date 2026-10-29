/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Modules of the reference SMC BL1, shared with the test fixtures that replace its main().

#pragma once

#include <stdint.h>

#include "smc_bl1_status.h"
#include "smu_bl1_contract.h"

static inline uint32_t smc_bl1_rd32(uintptr_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void smc_bl1_wr32(uintptr_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

static inline uint64_t smc_bl1_rd64(uintptr_t addr) {
    return *(volatile uint64_t *)addr;
}

static inline void smc_bl1_wr64(uintptr_t addr, uint64_t value) {
    *(volatile uint64_t *)addr = value;
}

// Disables interrupts, writes back the L1 D-cache and loops on wfi.
__attribute__((noreturn)) void smc_bl1_park(void);

// Uses the SMC Boot ROM's status ring only if the ROM published it and its header is intact;
// otherwise every ring write is dropped.
void smc_bl1_ring_init(void);
void smc_bl1_ring_write(uint32_t word);

// Writes the POST word and appends the value to the ring, as an error from 0x0180 up.
void smc_bl1_post(uint32_t value);

#ifdef DEBUG
void smc_bl1_puts(const char *str);
#else
static inline void smc_bl1_puts(const char *str) {
    (void)str;
}
#endif

// Everything up to the confirmation: sets up the ring, opens the outbound path to SEP mailbox
// 0's inbound port and pops the challenge, posting each step. Returns 0 once the challenge is
// in hand, or the SMC_BL1_ERR_* value it posted.
uint32_t smc_bl1_receive_challenge(uint32_t challenge[2]);

void smc_bl1_send_confirmation(uint32_t tag, const uint32_t challenge[2]);
