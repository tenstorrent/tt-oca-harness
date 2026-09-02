// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP real-entropy bring-up (ESRC -> DRBG -> CSRNG -> EDN) firmware driver.
// Header-only. Programs the OpenTitan-style entropy stack over the EL2 LSU bus so
// the Key Manager (and crypto engines) receive real EDN genbits -- the
// firmware-replicable equivalent of the reference UVM bring-up
// (sep_drbg_uvm_base_test_seq.sv configure_drbg_chain_from_cfg / enable_edn_mode),
// NOT a force. Order matters (mirrors the reference suite guard "configure EDN commands
// ONLY, do NOT enable EDN yet"):
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
#define SEP_ESRC_DECOR_DIV64 \
    (63u << ENTROPY_SOURCE__DECORRELATOR_CTRL__SAMPLE_CLK_DIV_bp)

#define SEP_CMD_INSTANTIATE 0x00000901u
#define SEP_CMD_RESEED 0x00000902u
#define SEP_CMD_GENERATE_GLEN32 0x00020903u

static inline void sep_entropy_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// Program a freshly reset entropy complex. This intentionally does not touch
// SW_RESET_N: alarm recovery must keep consumers quiesced while reinitializing.
static inline void sep_entropy_program_after_reset(void) {
    sep_entropy_wr(SEP_CLOCK_GATE_CTRL, SEP_CLOCK_GATE_ENTROPY);
    sep_entropy_wr(SEP_EXT_TRNG_SRC_SEL, 0x0);
    sep_entropy_wr(SEP_ESRC_RING_OSC_ENABLE, SEP_RING_OSC_SAMPLECLK_ONLY);
    sep_entropy_wr(SEP_ESRC_DECORRELATOR_CTRL, SEP_ESRC_DECOR_DIV64);
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

// PHASE-B: enable EDN last (auto+boot). Call after a seed has accumulated; EDN
// then auto-issues Instantiate+Generate and streams genbits to the KM. Lock the
// now-proven ESRC configuration before exposing entropy to consumers.
static inline void sep_entropy_enable_edn(void) {
    sep_entropy_wr(SEP_ESRC_FIPS_LOCK, ENTROPY_SOURCE__FIPS_LOCK__LOCK_bm);
    sep_entropy_wr(SEP_EDN_CTRL, SEP_EDN_CTRL_AUTO);
}

#endif // SEP_ENTROPY_H
