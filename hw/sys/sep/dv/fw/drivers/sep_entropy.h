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
// register byte address lands on the correct lane. MuBi4: TRUE=0x6, FALSE=0x9.
// csrng cmd word = {8'h0, glen[11:0], flag0=0x9(use-entropy), clen=0, acmd}.

#ifndef SEP_ENTROPY_H
#define SEP_ENTROPY_H

#include <stdint.h>
#include "sep_reset.h"

// sep_cpu_ctrl
#define SEP_CLOCK_GATE_CTRL 0x10A30008u
#define SEP_CLOCK_GATE_ENTROPY 0x001F0421u // reset 0x001F0021 | entropy_fifo_cg (bit 10)
#define SEP_EXT_TRNG_SRC_SEL 0x10A30190u   // 0 = internal DRBG (reset 0x7 = ext_trng)
// entropy_source (flat 32-bit map @ 0x1091_6000)
#define SEP_ESRC_CTRL 0x10916004u
#define SEP_ESRC_FIFO_CTRL 0x10916020u
#define SEP_ESRC_HEALTH_TEST_CTRL 0x10916030u
#define SEP_ESRC_RING_OSC_ENABLE 0x10916090u
#define SEP_ESRC_DECORRELATOR_CTRL 0x109160A0u
#define SEP_ESRC_MAIN_SM_STATUS 0x109160B4u
#define SEP_ESRC_FIPS_LOCK 0x10916154u
// CSRNG @ 0x1091_5000, EDN @ 0x1091_5800 (lane adapter)
#define SEP_CSRNG_CTRL 0x10915014u
#define SEP_EDN_CTRL 0x10915814u
#define SEP_EDN_BOOT_INS_CMD 0x10915818u
#define SEP_EDN_RESEED_CMD 0x1091582Cu
#define SEP_EDN_GENERATE_CMD 0x10915830u
#define SEP_EDN_MAX_REQS 0x10915834u

#define SEP_RING_OSC_SAMPLECLK_ONLY 0x00FFF000u // SAMPLE_CLK_ENABLE on, generators off
#define SEP_RING_OSC_ALL_ON 0x00FFFFFFu         // generators + sample-clk on
#define SEP_CSRNG_CTRL_ENABLE 0x00009666u // {FIPS_FORCE=F, READ_INT_STATE=T, SW_APP=T, ENABLE=T}
#define SEP_EDN_CTRL_AUTO 0x00009666u     // {CMD_FIFO_RST=F, AUTO_REQ=T, BOOT_REQ=T, EDN_ENABLE=T}
#define SEP_CMD_INSTANTIATE 0x00000901u
#define SEP_CMD_RESEED 0x00000902u
#define SEP_CMD_GENERATE_GLEN32 0x00020903u // glen=32

// DECORRELATOR_CTRL.SAMPLE_CLK_DIV is bits [31:12] and division = field+1, so
// div64 is 63<<12. 63 in the low bits lands 0x3F0 in the field instead --
// divide-by-1009, 16x slower than the register's own reset value, which pushes
// one 2048-sample health window past any reasonable simulation budget.
#define SEP_DECOR_CTRL_DIV64 (63u << 12) // 0x0003F000

// MAIN_SM_STATUS, the entropy_src_main_sm boot gate. BOOT_PHASE_DONE gates
// entropy_stream_valid, so enabling EDN before it issues an Instantiate against
// a source that cannot answer. ALERT/ERR mean the FSM escalated and no further
// entropy will come out -- a different verdict from "not yet".
#define SEP_MAIN_SM_BOOT_PHASE_DONE (1u << 12)
#define SEP_MAIN_SM_ERR (1u << 11)
#define SEP_MAIN_SM_ALERT (1u << 10)

// One boot health-test window is 2048 samples at the div64 rate, ~131k core
// cycles; each poll here is an uncached AXI read, so a few thousand covers it.
#define SEP_BOOT_PHASE_POLL_ITERS 20000u

#define SEP_ENTROPY_OK 0
#define SEP_ENTROPY_ERR_ALERT (-1)   // main_sm escalated; source is dead
#define SEP_ENTROPY_ERR_TIMEOUT (-2) // boot gate never opened

static inline void sep_entropy_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// Program a freshly reset entropy complex. This intentionally does not touch
// SW_RESET_N: alarm recovery must keep consumers quiesced while reinitializing.
static inline void sep_entropy_program_after_reset(void) {
    sep_entropy_wr(SEP_CLOCK_GATE_CTRL, SEP_CLOCK_GATE_ENTROPY);
    sep_entropy_wr(SEP_EXT_TRNG_SRC_SEL, 0x0);
    sep_entropy_wr(SEP_ESRC_RING_OSC_ENABLE, SEP_RING_OSC_SAMPLECLK_ONLY);
    sep_entropy_wr(SEP_ESRC_DECORRELATOR_CTRL, SEP_DECOR_CTRL_DIV64);
    sep_entropy_wr(SEP_ESRC_FIFO_CTRL, 0x1);
    sep_entropy_wr(SEP_ESRC_HEALTH_TEST_CTRL, 0x00003207u); // rep_limit=50, rep/apt/markov en
    sep_entropy_wr(SEP_ESRC_CTRL, 0x10000002u);             // MODULE_ENABLE + SHA256 whitening
    sep_entropy_wr(SEP_CSRNG_CTRL, SEP_CSRNG_CTRL_ENABLE);
    sep_entropy_wr(SEP_EDN_BOOT_INS_CMD, SEP_CMD_INSTANTIATE);
    sep_entropy_wr(SEP_EDN_RESEED_CMD, SEP_CMD_RESEED);
    sep_entropy_wr(SEP_EDN_GENERATE_CMD, SEP_CMD_GENERATE_GLEN32); // glen=32
    sep_entropy_wr(SEP_EDN_MAX_REQS, 8);                           // reseed interval=8
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
    sep_entropy_wr(SEP_ESRC_FIPS_LOCK, 0x1u);
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
