/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Pre-hand-off gate ledger and self-check (rom.adoc, SEP-ROM-HOFF-040/-050).
//
// The ledger is ROM-private DCCM state, never part of bl0_state. Every word is
// volatile so each stamp and each check is a real load or store that a fault
// has to defeat, rather than a value the compiler carried in a register.

#include "gate_ledger.h"

#include <stdbool.h>
#include <stdint.h>

#include "bl0_state.h"
#include "errors.h"
#include "fuse_lock.h"
#include "harden.h"
#include "rom_mmio.h"
#include "sep.h"

#define SRAM_BASE ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR)
#define SRAM_END (SRAM_BASE + (uint32_t)SEP_TOP_SEP_SRAM_SIZE)
#define LOCKS_ADDR ((uint32_t)SEP_TOP_SEP_EFUSE_MAP_LOCKS_BASE_ADDR)

static volatile uint32_t g_gate_ok;
static volatile uint32_t g_gate_inv;
static volatile uint32_t g_gate_manifest_len;
static volatile uint32_t g_selfcheck_seen;

void gate_ledger_reset(void) {
    g_gate_ok = 0u;
    g_gate_inv = 0xFFFFFFFFu;
    g_gate_manifest_len = 0u;
}

__attribute__((always_inline)) static inline void gate_stamp(uint32_t gate) {
    g_gate_ok = g_gate_ok | gate;
    g_gate_inv = g_gate_inv & ~gate;
}

void gate_stamp_manifest(void) {
    gate_stamp(BOOT_GATE_MANIFEST);
}

void gate_stamp_crypto(void) {
    gate_stamp(BOOT_GATE_CRYPTO);
}

void gate_stamp_hash(void) {
    gate_stamp(BOOT_GATE_HASH);
}

void gate_stamp_fuselock(void) {
    gate_stamp(BOOT_GATE_FUSELOCK);
}

void gate_ledger_record_manifest_len(uint32_t len) {
    g_gate_manifest_len = len;
}

// Each check is its own function so the two evaluations of one invariant stay
// two separate pieces of code; the second launders every operand.

__attribute__((noinline)) static bool check_ledger(void) {
    return g_gate_ok == BOOT_GATE_EXPECT && g_gate_inv == (uint32_t)~BOOT_GATE_EXPECT;
}

static inline bool locus_holds(uint32_t addr, uint32_t len, uint32_t base, uint32_t end) {
    return addr == base && len <= end - addr;
}

__attribute__((noinline)) static bool check_locus_first(void) {
    return locus_holds(get_bl0_state()->sep_sram_manifest_addr, g_gate_manifest_len, SRAM_BASE,
                       SRAM_END);
}

__attribute__((noinline)) static bool check_locus_second(void) {
    return locus_holds(harden_u32(get_bl0_state()->sep_sram_manifest_addr),
                       harden_u32(g_gate_manifest_len), harden_u32(SRAM_BASE),
                       harden_u32(SRAM_END));
}

static inline bool locks_hold(uint32_t locks, uint32_t mask) {
    return (locks & mask) == mask;
}

__attribute__((noinline)) static bool check_locks_first(void) {
    return locks_hold(mmio_read32(LOCKS_ADDR), FUSE_SECRET_READ_LOCK_MASK);
}

__attribute__((noinline)) static bool check_locks_second(void) {
    return locks_hold(harden_u32(mmio_read32(harden_u32(LOCKS_ADDR))),
                      harden_u32(FUSE_SECRET_READ_LOCK_MASK));
}

typedef bool (*selfcheck_fn)(void);

static const selfcheck_fn k_selfchecks[] = {
    check_ledger, check_locus_first, check_locus_second, check_locks_first, check_locks_second,
};

#define SELFCHECK_COUNT ((uint32_t)(sizeof(k_selfchecks) / sizeof(k_selfchecks[0])))

__attribute__((noreturn, noinline)) static void selfcheck_fail(void) {
    rom_err_fail_ext(ROM_ERR_HANDOFF_SELFCHECK_FAILED);
}

void rom_handoff_selfcheck(void) {
    g_selfcheck_seen = 0u;
    // i advances through a laundered copy, so the compiler can neither derive it from
    // g_selfcheck_seen nor replace it with the trip count after the loop.
    uint32_t i = 0u;
    while (i < SELFCHECK_COUNT) {
        if (!k_selfchecks[i]()) {
            selfcheck_fail();
        }
        g_selfcheck_seen = g_selfcheck_seen + 1u;
        if (g_selfcheck_seen != harden_u32(i) + 1u) {
            selfcheck_fail();
        }
        i = harden_u32(i) + 1u;
    }
    // The tally catches a loop left early, which every per-iteration compare missed.
    const uint32_t count = harden_u32(SELFCHECK_COUNT);
    if (i != count || g_selfcheck_seen != count) {
        selfcheck_fail();
    }
}
