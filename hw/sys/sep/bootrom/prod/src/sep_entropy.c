/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SEP entropy chain bring-up (ESRC -> DRBG/CSRNG -> EDN).
//
// Follows the documented OCAH TRNG bring-up (doc/programmer, "OCAH TRNG
// Bring-Up"), cross-checked against the DV environment's proven sequence in
// sep_drbg_real_sink_multi_km_aes_test (seq_lib/sep_esrc_bringup_seq.py).
// The order is load-bearing:
//
//   PHASE A  select the internal DRBG, configure ESRC with the ring-oscillator
//            generators OFF, enable CSRNG, and stage EDN's commands. EDN stays
//            DISABLED: its commands are configured here but it is not enabled
//            until phase C.
//   PHASE B  start the generators.
//            ...wait for the boot health-test window to pass...
//   PHASE C  enable EDN last. It then auto-issues Instantiate + Generate and
//            streams genbits to the crypto blocks.
//
// Register values are built from the generated field macros, not written as
// literals. That is not style: ESRC_CTRL.MODULE_ENABLE RESETS TO 1, so a
// hand-built "just set the whitening bit" literal clears it and disables the
// entire entropy source -- the decorrelator keeps sampling, the whitener never
// accepts a word, and no seed ever reaches CSRNG. It fails silently, as a
// downstream crypto timeout.

#include "sep_entropy.h"

#include <stdint.h>

#include "sep.h"
#include "rom_mmio.h"
#include "entropy_source.h"
#include "csrng.h"
#include "edn.h"
#include "sep_reset_ctrl.h"
#include "rom_virt_console.h"
#include "errors.h"
#include "status_ring.h"
#include "status_values.h"

// --- values ----------------------------------------------------------------
// Ring oscillators: sample clock on, generators off (PHASE A) then everything
// on (PHASE B). The generators must not run before the rest is configured.
#define ESRC_RING_OSC_SAMPLECLK_ONLY 0x00FFF000u
#define ESRC_RING_OSC_ALL_ON 0x00FFFFFFu

// DECORRELATOR_CTRL.SAMPLE_CLK_DIV in [31:12]; 0x3F => divide by 64. The DV
// default policy; the /8 variant exists for faster smoke runs.
#define ESRC_DECOR_CTRL_DIV64 0x0003F000u

// rep_limit=50, repetition/APT/Markov health tests enabled. HEALTH_TEST_WINDOW_SIZE
// is deliberately left at its 2048-sample reset.
#define ESRC_HEALTH_CTRL 0x00003207u

// MuBi4: true = 0x6, false = 0x9. Every control field below is MuBi4.
#define MUBI4_TRUE 0x6u
#define MUBI4_FALSE 0x9u

// CSRNG: ENABLE only. SW_APP_ENABLE, READ_INT_STATE and FIPS_FORCE_ENABLE are
// diagnostic interfaces and stay false unless security policy asks for them --
// the ROM consumes entropy through the hardware EDN path and needs none of them.
#define CSRNG_CTRL_CONFIGURED \
    ((uint32_t)((MUBI4_TRUE << CSRNG__CTRL__ENABLE_bp) | \
                (MUBI4_FALSE << CSRNG__CTRL__SW_APP_ENABLE_bp) | \
                (MUBI4_FALSE << CSRNG__CTRL__READ_INT_STATE_bp) | \
                (MUBI4_FALSE << CSRNG__CTRL__FIPS_FORCE_ENABLE_bp)))

// EDN continuous-operation mode. BOOT_REQ_MODE must be FALSE: boot-request mode
// takes precedence over auto-request and stays in its completed state until
// firmware clears it, so setting both does NOT give continuous operation.
#define EDN_CTRL_CONFIGURED \
    ((uint32_t)((MUBI4_TRUE << EDN__CTRL__EDN_ENABLE_bp) | \
                (MUBI4_TRUE << EDN__CTRL__AUTO_REQ_MODE_bp) | \
                (MUBI4_FALSE << EDN__CTRL__BOOT_REQ_MODE_bp) | \
                (MUBI4_FALSE << EDN__CTRL__CMD_FIFO_RST_bp)))

// csrng command words: {8'h0, glen[11:0], flag0=9 (use real entropy), clen=0, acmd}
#define CSRNG_CMD_INSTANTIATE 0x00000901u
#define CSRNG_CMD_RESEED 0x00000902u
#define CSRNG_CMD_GENERATE_GLEN32 0x00020903u
#define EDN_RESEED_INTERVAL 8u

#ifndef SEP_ENTROPY_CMD_TIMEOUT
#define SEP_ENTROPY_CMD_TIMEOUT 1000000u
#endif

// EXT_TRNG_SRC_SEL.sel[2:0] is PER STREAM: bit0 Key Manager, bit1 crypto blocks,
// bit2 entropy pool. 0 = internal DRBG, 1 = external TRNG (reset 0x7 = all
// external). The ROM drives OTBN and AES, so it clears bit 1 and leaves the
// other two streams alone -- BL0 does not use them and should not be choosing
// their source for stages that have not run yet.
#define EXT_TRNG_SEL_CRYPTO_BLOCKS_bm 0x2u

// Bounded wait for the boot health-test window. The chain is analog at the
// bottom, so this must be a timeout, not a spin.
#ifndef SEP_ENTROPY_SEED_TIMEOUT
#define SEP_ENTROPY_SEED_TIMEOUT 2000000u
#endif

// ESRC_CTRL with every field at its reset value. MODULE_ENABLE and
// SHA256_WHITENING_ENABLE both reset to 1, which is already what this ROM
// wants, so the write is an explicit statement of intent rather than a change.
#define ESRC_CTRL_CONFIGURED \
    ((uint32_t)(ENTROPY_SOURCE__CTRL__MODULE_ENABLE_bm | \
                ENTROPY_SOURCE__CTRL__SHA256_WHITENING_ENABLE_bm))

// Terminal-failure hook, defined in rom_main.c. Same idiom lifecycle.c uses for
// an invalid life-cycle state: a device-level condition no retry can fix.
__attribute__((noreturn)) extern void rom_err_fail_ext(uint32_t error_code);

// A failed entropy bring-up STOPS secure boot. It is a device failure, not a bad
// image: the backup manifest slot carries the same crypto requirement, so
// rotating to it cannot help, and letting the failure surface as a signature
// error would report the wrong cause. Policy lives here, once, rather than at
// each crypto init that depends on it.
__attribute__((noreturn)) static void entropy_fail(void) {
    report_status(STATUS_TYPE_ERROR, SEP_MSG_ENTROPY_INIT_FAILED);
    rom_err_fail_ext(SEP_MSG_ENTROPY_INIT_FAILED);
}

// Apply a write-one-to-set lock and confirm it took.
//
// These locks are one-way: once set, the field is read-only until SEP reset. The
// read-back is not ceremony -- a lock that silently failed leaves the ROM
// believing it froze a security-relevant configuration that later software can
// still change, which is worse than not locking at all because nothing would
// ever notice.
static int apply_lock(uint32_t addr, uint32_t bm, const char *what) {
    mmio_write32(addr, mmio_read32(addr) | bm);
    __asm__ volatile("fence" ::: "memory");
    if ((mmio_read32(addr) & bm) == 0u) {
        simputs(what);
        simputs("_LOCK_FAIL\n");
        return -1;
    }
    return 0;
}

static int g_entropy_state; // 0 = untried, 1 = up, -1 = failed

// Wait for the entropy source to finish its startup health-test window.
//
// BOOT_PHASE_DONE proves the startup health-test gate opened. It does NOT prove
// CSRNG accepted a complete seed -- that is what the EDN Instantiate
// acknowledgement establishes. This poll separates an ESRC startup failure from
// a downstream CSRNG/EDN one, which have different fixes.
static int wait_boot_phase_done(void) {
    for (uint32_t i = 0; i < SEP_ENTROPY_SEED_TIMEOUT; ++i) {
        uint32_t s = mmio_read32(SEP_TOP_ENTROPY_SOURCE_MAIN_SM_STATUS_BASE_ADDR);
        if (s & ENTROPY_SOURCE__MAIN_SM_STATUS__BOOT_PHASE_DONE_bm) {
            return 0;
        }
        // Do not spin out the full timeout on a failure the hardware has
        // already reported; alert/err latch, so one check per iteration turns a
        // 2M-iteration wait into an immediate verdict.
        if (s &
            (ENTROPY_SOURCE__MAIN_SM_STATUS__ALERT_bm | ENTROPY_SOURCE__MAIN_SM_STATUS__ERR_bm)) {
            simputs("ESRC_HEALTH_FAIL=");
            simputhex32(s);
            simputs("\n");
            return -1;
        }
    }
    simputs("ESRC_BOOT_PHASE_TIMEOUT=");
    simputhex32(mmio_read32(SEP_TOP_ENTROPY_SOURCE_MAIN_SM_STATUS_BASE_ADDR));
    simputs("\n");
    return -1;
}

// Issue the EDN Instantiate and wait for its acknowledgement.
//
// This is the software-visible readiness event for the whole chain: CSRNG
// cannot acknowledge Instantiate until it has accepted a complete ESRC seed.
// It is why the ROM needs neither a blind delay nor a hierarchical
// drbg_seed_valid probe -- the latter has no CSR behind it anyway.
static int edn_instantiate(void) {
    const uint32_t ready = EDN__SW_CMD_STS__CMD_RDY_bm | EDN__SW_CMD_STS__CMD_REG_RDY_bm;
    uint32_t i, sts = 0u;

    for (i = 0; i < SEP_ENTROPY_CMD_TIMEOUT; ++i) {
        sts = mmio_read32(SEP_TOP_EDN_SW_CMD_STS_BASE_ADDR);
        if ((sts & ready) == ready) break;
    }
    if (i == SEP_ENTROPY_CMD_TIMEOUT) {
        simputs("EDN_CMD_NOT_READY=");
        simputhex32(sts);
        simputs("\n");
        return -1;
    }

    mmio_write32(SEP_TOP_EDN_SW_CMD_REQ_BASE_ADDR, CSRNG_CMD_INSTANTIATE);

    for (i = 0; i < SEP_ENTROPY_CMD_TIMEOUT; ++i) {
        sts = mmio_read32(SEP_TOP_EDN_SW_CMD_STS_BASE_ADDR);
        if (sts & EDN__SW_CMD_STS__CMD_ACK_bm) break;
    }
    if (i == SEP_ENTROPY_CMD_TIMEOUT) {
        simputs("EDN_INSTANTIATE_TIMEOUT=");
        simputhex32(sts);
        simputs("\n");
        return -1;
    }
    // An acknowledgement is not a success: CMD_STS carries the verdict.
    if (sts & EDN__SW_CMD_STS__CMD_STS_bm) {
        simputs("EDN_INSTANTIATE_ERR=");
        simputhex32(sts);
        simputs("\n");
        return -1;
    }
    return 0;
}

// Freeze which source feeds the crypto-block entropy stream.
//
// Called on BOTH paths and only at the very end, because the guide's rule is to
// lock the selection once the chosen source is verified operational -- and the
// EDN Instantiate acknowledgement (internal) or the adopter's driver returning
// success (external) is exactly that verification. Locking a selection whose
// source had not been proven would freeze the device onto a dead stream.
//
// Unlike FIPS_LOCK this applies to the external path too: it locks the mux, not
// the ESRC configuration, so it is meaningful whichever source was selected.
static void lock_source_selection(void) {
#if !SEP_ENTROPY_DEFER_SRC_SEL_LOCK
    if (apply_lock(SEP_TOP_SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_LOCK_BASE_ADDR,
                   SEP_CPU_CTRL__EXT_TRNG_SRC_SEL_LOCK__LOCK_bm, "ENTROPY_SRC_SEL") != 0) {
        entropy_fail();
    }
#endif
}

int sep_entropy_init(void) {
    // Only success is cacheable: a failure does not return, so there is no
    // failed state for a later call to observe.
    if (g_entropy_state != 0) {
        return 0;
    }

    report_status(STATUS_TYPE_INFO, SEP_MSG_ENTROPY_INIT_START);

    // The one branch an adopter changes. On the external path the ROM programs
    // nothing in the internal chain and leaves EXT_TRNG_SRC_SEL at its reset
    // value, so the crypto-block stream keeps taking the external source; the
    // adopter's driver owns everything from there.
    if (!sep_entropy_use_internal_source()) {
        if (sep_entropy_bringup_external() != 0) {
            entropy_fail();
        }
        lock_source_selection();
        g_entropy_state = 1;
        return 0;
    }

    // Pulse the shared TRNG reset: CLEAR then SET, read-modify-write so the
    // other blocks' reset bits are preserved. A release alone is not enough --
    // if the chain is already out of reset the write is a no-op and any stale
    // state stays. The pulse covers ESRC, CSRNG, EDN, their control-plane
    // adapters, buffered entropy and the fabric entropy pool.
    uint32_t rst = mmio_read32(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    mmio_write32(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR,
                 rst & ~(uint32_t)SEP_RESET_CTRL__SW_RESET_N__TRNG_SW_RST_N_bm);
    __asm__ volatile("fence" ::: "memory");
    mmio_write32(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR,
                 rst | (uint32_t)SEP_RESET_CTRL__SW_RESET_N__TRNG_SW_RST_N_bm);
    __asm__ volatile("fence" ::: "memory");

    // --- PHASE A: configure, generators off, EDN staged but not enabled ----
    // Point the crypto-block entropy stream at the internal DRBG.
    uint32_t sel = mmio_read32(SEP_TOP_SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_BASE_ADDR);
    sel &= ~EXT_TRNG_SEL_CRYPTO_BLOCKS_bm;
    mmio_write32(SEP_TOP_SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_BASE_ADDR, sel);

    mmio_write32(SEP_TOP_ENTROPY_SOURCE_RING_OSC_ENABLE_BASE_ADDR, ESRC_RING_OSC_SAMPLECLK_ONLY);
    mmio_write32(SEP_TOP_ENTROPY_SOURCE_DECORRELATOR_CTRL_BASE_ADDR, ESRC_DECOR_CTRL_DIV64);
    mmio_write32(SEP_TOP_ENTROPY_SOURCE_FIFO_CTRL_BASE_ADDR, 0x1u);
    mmio_write32(SEP_TOP_ENTROPY_SOURCE_HEALTH_TEST_CTRL_BASE_ADDR, ESRC_HEALTH_CTRL);
    mmio_write32(SEP_TOP_ENTROPY_SOURCE_CTRL_BASE_ADDR, ESRC_CTRL_CONFIGURED);

    mmio_write32(SEP_TOP_CSRNG_CTRL_BASE_ADDR, CSRNG_CTRL_CONFIGURED);
    // BOOT_INS_CMD is deliberately not programmed: that is boot-request mode's
    // command, and this brings EDN up in auto-request mode with boot-request
    // false. Instantiate is issued through SW_CMD_REQ once EDN is enabled.
    mmio_write32(SEP_TOP_EDN_RESEED_CMD_BASE_ADDR, CSRNG_CMD_RESEED);
    mmio_write32(SEP_TOP_EDN_GENERATE_CMD_BASE_ADDR, CSRNG_CMD_GENERATE_GLEN32);
    mmio_write32(SEP_TOP_EDN_MAX_NUM_REQS_BETWEEN_RESEEDS_BASE_ADDR, EDN_RESEED_INTERVAL);

    // --- PHASE B: start the generators, then wait for a seed ---------------
    mmio_write32(SEP_TOP_ENTROPY_SOURCE_RING_OSC_ENABLE_BASE_ADDR, ESRC_RING_OSC_ALL_ON);
    __asm__ volatile("fence" ::: "memory");

    if (wait_boot_phase_done() != 0) {
        entropy_fail();
    }

#if !SEP_ENTROPY_DEFER_FIPS_LOCK
    // Freeze the ESRC configuration now: after the startup health test has
    // passed and BEFORE any entropy is exposed to a consumer, which is the
    // window the programmer guide specifies. Locking earlier would freeze a
    // configuration that had not yet proved itself; later would expose entropy
    // from a still-mutable source. DEBUG_CTRL stays outside this lock by design.
    if (apply_lock(SEP_TOP_ENTROPY_SOURCE_FIPS_LOCK_BASE_ADDR, ENTROPY_SOURCE__FIPS_LOCK__LOCK_bm,
                   "ESRC_FIPS") != 0) {
        entropy_fail();
    }
#endif

    // --- PHASE C: enable EDN, then Instantiate ------------------------------
    mmio_write32(SEP_TOP_EDN_CTRL_BASE_ADDR, EDN_CTRL_CONFIGURED);
    __asm__ volatile("fence" ::: "memory");

    if (edn_instantiate() != 0) {
        entropy_fail();
    }

    lock_source_selection();

    simputs("ENTROPY_OK\n");
    g_entropy_state = 1;
    return 0;
}

// --- adopter seam (weak; see sep_entropy.h) --------------------------------
__attribute__((weak)) bool sep_entropy_use_internal_source(void) {
    // This harness exists to exercise the internal chain.
    return true;
}

__attribute__((weak)) int sep_entropy_bringup_external(void) {
    // No external TRNG in this tree. Fail rather than report success on a
    // stream nothing has configured: a false success stalls the crypto blocks
    // later with no indication of why.
    simputs("ENTROPY_EXT_STUB\n");
    return -1;
}
