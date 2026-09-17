// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP real-entropy bring-up (ESRC -> DRBG -> CSRNG -> EDN) firmware driver.
// Header-only. Programs the OpenTitan-style entropy stack over the EL2 LSU bus so
// the Key Manager (and crypto engines) receive real EDN genbits from the
// programmed stack, with no testbench force. Order matters: EDN commands are
// staged first and EDN is enabled last:
//   1. sep_entropy_configure()       -- PHASE-A: mux, ESRC config (gens OFF),
//                                        CSRNG enable, stage EDN commands.
//   2. sep_entropy_start_generators()-- enable the ring-osc generators.
//   3. (allow time for the first seed to accumulate)
//   4. sep_entropy_enable_edn()      -- PHASE-B: lock ESRC config, enable EDN last.
// Under Verilator the ESRC ring oscillators do not self-oscillate, so the tb-side
// +esrc_noise_force supplies the raw noise; the DRBG/CSRNG/EDN math below is real.
// CSRNG/EDN sit behind a 64-bit lane adapter; an aligned 32-bit store at the
// register byte address lands on the correct lane.
// Addresses and field masks come from generated sep_addr.h / entropy_source.h /
// csrng.h / edn.h (via sep.h). MuBi4 encodings (TRUE=0x6, FALSE=0x9) and CSRNG
// command words are prim_mubi / cmd encodings, not PeakRDL enums.

#ifndef SEP_ENTROPY_H
#define SEP_ENTROPY_H

#include <stdint.h>
#include "sep.h"
#include "sep_reset.h"

#define SEP_CLOCK_GATE_CTRL OCH_SEP_TOP_SEP_CPU_CTRL_CLOCK_GATE_CTRL_BASE_ADDR
#define SEP_CLOCK_GATE_ENTROPY SEP_CPU_CTRL__CLOCK_GATE_CTRL_reset
#define SEP_EXT_TRNG_SRC_SEL OCH_SEP_TOP_SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_BASE_ADDR
#define SEP_ESRC_CTRL OCH_SEP_TOP_ENTROPY_SOURCE_CTRL_BASE_ADDR
#define SEP_ESRC_FIFO_CTRL OCH_SEP_TOP_ENTROPY_SOURCE_FIFO_CTRL_BASE_ADDR
#define SEP_ESRC_HEALTH_TEST_CTRL OCH_SEP_TOP_ENTROPY_SOURCE_HEALTH_TEST_CTRL_BASE_ADDR
#define SEP_ESRC_RING_OSC_ENABLE OCH_SEP_TOP_ENTROPY_SOURCE_RING_OSC_ENABLE_BASE_ADDR
#define SEP_ESRC_DECORRELATOR_CTRL OCH_SEP_TOP_ENTROPY_SOURCE_DECORRELATOR_CTRL_BASE_ADDR
#define SEP_ESRC_MAIN_SM_STATUS OCH_SEP_TOP_ENTROPY_SOURCE_MAIN_SM_STATUS_BASE_ADDR
#define SEP_ESRC_FIPS_LOCK OCH_SEP_TOP_ENTROPY_SOURCE_FIPS_LOCK_BASE_ADDR
#define SEP_CSRNG_CTRL OCH_SEP_TOP_CSRNG_CTRL_BASE_ADDR
#define SEP_EDN_CTRL OCH_SEP_TOP_EDN_CTRL_BASE_ADDR
#define SEP_EDN_BOOT_INS_CMD OCH_SEP_TOP_EDN_BOOT_INS_CMD_BASE_ADDR
#define SEP_EDN_RESEED_CMD OCH_SEP_TOP_EDN_RESEED_CMD_BASE_ADDR
#define SEP_EDN_GENERATE_CMD OCH_SEP_TOP_EDN_GENERATE_CMD_BASE_ADDR
#define SEP_EDN_MAX_REQS OCH_SEP_TOP_EDN_MAX_NUM_REQS_BETWEEN_RESEEDS_BASE_ADDR

#define SEP_RING_OSC_SAMPLECLK_ONLY ENTROPY_SOURCE__RING_OSC_ENABLE__SAMPLE_CLK_ENABLE_bm
#define SEP_RING_OSC_ALL_ON \
    (ENTROPY_SOURCE__RING_OSC_ENABLE__ENABLE_bm | \
     ENTROPY_SOURCE__RING_OSC_ENABLE__SAMPLE_CLK_ENABLE_bm)

#define SEP_CSRNG_CTRL_ENABLE \
    ((MULTIBITBOOL4__TRUE << CSRNG__CTRL__ENABLE_bp) | \
     (MULTIBITBOOL4__TRUE << CSRNG__CTRL__SW_APP_ENABLE_bp) | \
     (MULTIBITBOOL4__TRUE << CSRNG__CTRL__READ_INT_STATE_bp) | \
     (MULTIBITBOOL4__FALSE << CSRNG__CTRL__FIPS_FORCE_ENABLE_bp))
#define SEP_EDN_CTRL_AUTO \
    ((MULTIBITBOOL4__TRUE << EDN__CTRL__EDN_ENABLE_bp) | \
     (MULTIBITBOOL4__TRUE << EDN__CTRL__BOOT_REQ_MODE_bp) | \
     (MULTIBITBOOL4__TRUE << EDN__CTRL__AUTO_REQ_MODE_bp) | \
     (MULTIBITBOOL4__FALSE << EDN__CTRL__CMD_FIFO_RST_bp))

#define SEP_ESRC_CTRL_BRINGUP \
    (ENTROPY_SOURCE__CTRL__MODULE_ENABLE_bm | ENTROPY_SOURCE__CTRL__SHA256_WHITENING_ENABLE_bm)
#define SEP_ESRC_HEALTH_TEST_BRINGUP \
    (ENTROPY_SOURCE__HEALTH_TEST_CTRL__ENABLE_bm | \
     (50u << ENTROPY_SOURCE__HEALTH_TEST_CTRL__REPETITION_LIMIT_bp))

#define SEP_CMD_INSTANTIATE 0x00000901u
#define SEP_CMD_RESEED 0x00000902u
#define SEP_CMD_GENERATE_GLEN32 0x00020903u

// DECORRELATOR_CTRL.SAMPLE_CLK_DIV is bits [31:12] and division = field+1, so
// div64 is 63<<12. 63 in the low bits lands 0x3F0 in the field instead --
// divide-by-1009, 16x slower than the register's own reset value, which pushes
// one 2048-sample health window past any reasonable simulation budget.
#define SEP_DECOR_CTRL_DIV64 \
    (63u << ENTROPY_SOURCE__DECORRELATOR_CTRL__SAMPLE_CLK_DIV_bp) // 0x0003F000

// MAIN_SM_STATUS, the entropy_src_main_sm boot gate. BOOT_PHASE_DONE gates
// entropy_stream_valid, so enabling EDN before it issues an Instantiate against
// a source that cannot answer. ALERT/ERR mean the FSM escalated and no further
// entropy will come out -- a different verdict from "not yet".
#define SEP_MAIN_SM_BOOT_PHASE_DONE ENTROPY_SOURCE__MAIN_SM_STATUS__BOOT_PHASE_DONE_bm
#define SEP_MAIN_SM_ERR ENTROPY_SOURCE__MAIN_SM_STATUS__ERR_bm
#define SEP_MAIN_SM_ALERT ENTROPY_SOURCE__MAIN_SM_STATUS__ALERT_bm

// One boot health-test window is 2048 samples at the div64 rate, ~131k core
// cycles; each poll here is an uncached AXI read, so a few thousand covers it.
#define SEP_BOOT_PHASE_POLL_ITERS 20000u

#define SEP_ENTROPY_OK 0
#define SEP_ENTROPY_ERR_ALERT (-1)   // main_sm escalated; source is dead
#define SEP_ENTROPY_ERR_TIMEOUT (-2) // boot gate never opened

static inline void sep_entropy_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// Program a freshly reset entropy complex without touching SW_RESET_N: alarm
// recovery must keep consumers quiesced while reinitializing.
static inline void sep_entropy_program_after_reset(void) {
    sep_entropy_wr(SEP_CLOCK_GATE_CTRL, SEP_CLOCK_GATE_ENTROPY);
    sep_entropy_wr(SEP_EXT_TRNG_SRC_SEL, 0x0);
    sep_entropy_wr(SEP_ESRC_RING_OSC_ENABLE, SEP_RING_OSC_SAMPLECLK_ONLY);
    sep_entropy_wr(SEP_ESRC_DECORRELATOR_CTRL, SEP_DECOR_CTRL_DIV64);
    sep_entropy_wr(SEP_ESRC_FIFO_CTRL, ENTROPY_SOURCE__FIFO_CTRL__ENABLE_bm);
    sep_entropy_wr(SEP_ESRC_HEALTH_TEST_CTRL, SEP_ESRC_HEALTH_TEST_BRINGUP);
    sep_entropy_wr(SEP_ESRC_CTRL, SEP_ESRC_CTRL_BRINGUP);
    sep_entropy_wr(SEP_CSRNG_CTRL, SEP_CSRNG_CTRL_ENABLE);
    sep_entropy_wr(SEP_EDN_BOOT_INS_CMD, SEP_CMD_INSTANTIATE);
    sep_entropy_wr(SEP_EDN_RESEED_CMD, SEP_CMD_RESEED);
    sep_entropy_wr(SEP_EDN_GENERATE_CMD, SEP_CMD_GENERATE_GLEN32);
    sep_entropy_wr(SEP_EDN_MAX_REQS, 8);
}

// Initial PHASE-A bring-up: no entropy consumers are enabled yet, so reset the
// complete ESRC+CSRNG+EDN domain and then program it. Alarm recovery instead
// uses sep_reset_begin_trng_recovery(), releases TRNG for reinitialization,
// calls sep_entropy_program_after_reset(), starts generators/enables EDN, waits
// for fresh progress, and only then restores consumers.
static inline void sep_entropy_configure(void) {
    sep_reset_assert_trng();
    sep_reset_release_trng();
    sep_entropy_program_after_reset();
}

// Enable the ring-osc generators (the tb +esrc_noise_force already drives noise).
static inline void sep_entropy_start_generators(void) {
    sep_entropy_wr(SEP_ESRC_RING_OSC_ENABLE, SEP_RING_OSC_ALL_ON);
}

static inline uint32_t sep_entropy_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline int sep_entropy_boot_phase_done(void) {
    return (sep_entropy_rd(SEP_ESRC_MAIN_SM_STATUS) & SEP_MAIN_SM_BOOT_PHASE_DONE) != 0;
}

// Wait on the entropy source's own boot gate rather than on a fixed delay, so a
// run that stalls says why.
static inline int sep_entropy_wait_boot_phase(void) {
    for (uint32_t i = 0; i < SEP_BOOT_PHASE_POLL_ITERS; i++) {
        uint32_t sm = sep_entropy_rd(SEP_ESRC_MAIN_SM_STATUS);
        if (sm & (SEP_MAIN_SM_ALERT | SEP_MAIN_SM_ERR)) {
            return SEP_ENTROPY_ERR_ALERT;
        }
        if (sm & SEP_MAIN_SM_BOOT_PHASE_DONE) {
            return SEP_ENTROPY_OK;
        }
    }
    return SEP_ENTROPY_ERR_TIMEOUT;
}

// PHASE-B: enable EDN last (auto+boot). Call after a seed has accumulated; EDN
// then auto-issues Instantiate+Generate and streams genbits to the KM. Lock the
// now-proven ESRC configuration before exposing entropy to consumers.
static inline void sep_entropy_enable_edn(void) {
    sep_entropy_wr(SEP_ESRC_FIPS_LOCK, ENTROPY_SOURCE__FIPS_LOCK__LOCK_bm);
    sep_entropy_wr(SEP_EDN_CTRL, SEP_EDN_CTRL_AUTO);
}

// Full bring-up, for a test that needs entropy to exist rather than one that is
// testing the bring-up itself. Idempotent by inspection: if the boot gate is
// already open the stack is running, and re-running PHASE-A would pulse
// CTRL.RESET and tear down a source a consumer may already be drawing from.
static inline int sep_entropy_bringup(void) {
    if (sep_entropy_boot_phase_done()) {
        sep_entropy_enable_edn();
        return SEP_ENTROPY_OK;
    }
    sep_entropy_configure();
    sep_entropy_start_generators();
    int rc = sep_entropy_wait_boot_phase();
    if (rc != SEP_ENTROPY_OK) {
        return rc;
    }
    sep_entropy_enable_edn();
    return SEP_ENTROPY_OK;
}

#endif // SEP_ENTROPY_H
