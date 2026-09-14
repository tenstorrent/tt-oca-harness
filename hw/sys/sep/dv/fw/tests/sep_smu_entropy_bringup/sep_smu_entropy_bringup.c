/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_entropy_bringup - SEP entropy stack brought up from firmware.
 *
 * Runs the ESRC -> CSRNG -> EDN bring-up that hw/sys/sep/dv/fw/drivers/
 * sep_entropy.h already provides, in the order that driver documents:
 *
 *   1. sep_entropy_configure()        PHASE-A: mux, ESRC config with the
 *                                     generators OFF, CSRNG enable, EDN
 *                                     commands staged but EDN still disabled.
 *   2. sep_entropy_start_generators() turn the ring-osc generators on.
 *   3. spin so a first seed can accumulate.
 *   4. sep_entropy_enable_edn()       PHASE-B: enable EDN last.
 *
 * The order is a hardware constraint (EDN commands are staged before EDN is
 * enabled), so each phase gets its own fail loop and the testbench can tell
 * which one did not take.
 *
 * The raw noise itself comes from the testbench: under Verilator the ESRC ring
 * oscillators do not self-oscillate, so +esrc_noise_force drives the 12
 * decorrelator lanes. Everything this firmware programs, and everything the
 * hardware then does with that noise, is real.
 *
 * Progress is published to SEP-local cold scratch so a stalled run says which
 * phase it reached without needing the outbound mailbox.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_entropy.h"
#include "sep_outbound_filter.h"

#define SCRATCH(n) OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(n)
#define SC_PHASE SCRATCH(1)

#define PH_ENTER 0x5EED0001u
#define PH_CONFIGURED 0x5EED0002u
#define PH_GENERATORS 0x5EED0003u
#define PH_BOOT_PHASE_DONE 0x5EED0004u
#define PH_EDN_ENABLED 0x5EED0005u

/* The boot-gate poll, its bound, and the MAIN_SM_STATUS bit names all live in
 * sep_entropy.h so this test and sep_entropy_bringup()'s callers agree on one
 * definition. This test still drives the four phases separately rather than
 * calling sep_entropy_bringup(), because the phase boundaries are its subject:
 * it marks each one in scratch and checks the readback in between. */

__attribute__((used, noinline, noreturn)) void sep_smu_entropy_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_entropy_fail_configure_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_entropy_fail_boot_phase_loop(void) {
    for (;;) {
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_entropy_fail_esrc_alert_loop(void) {
    for (;;) {
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_entropy_fail_generators_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

static inline void fence_io(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

int main(void) {
    sep_outbound_filter_init();
    WRITE_REG(SC_PHASE, PH_ENTER);
    fence_io();

    /* PHASE-A. Read back one register the phase programs: if the CSR path to
     * the entropy block is dead, everything after this is meaningless. */
    sep_entropy_configure();
    fence_io();
    if (READ_REG(SEP_ESRC_RING_OSC_ENABLE) != SEP_RING_OSC_SAMPLECLK_ONLY) {
        sep_smu_entropy_fail_configure_loop();
    }
    WRITE_REG(SC_PHASE, PH_CONFIGURED);
    fence_io();

    /* Generators on. */
    sep_entropy_start_generators();
    fence_io();
    if (READ_REG(SEP_ESRC_RING_OSC_ENABLE) != SEP_RING_OSC_ALL_ON) {
        sep_smu_entropy_fail_generators_loop();
    }
    WRITE_REG(SC_PHASE, PH_GENERATORS);
    fence_io();

    /* Wait for the entropy source's own boot gate rather than for a fixed
     * delay. Until BOOT_PHASE_DONE asserts, entropy_stream_valid is gated and
     * enabling EDN would issue an Instantiate against a source that cannot
     * answer it. */
    switch (sep_entropy_wait_boot_phase()) {
    case SEP_ENTROPY_OK:
        break;
    case SEP_ENTROPY_ERR_ALERT:
        sep_smu_entropy_fail_esrc_alert_loop();
    default:
        sep_smu_entropy_fail_boot_phase_loop();
    }
    WRITE_REG(SC_PHASE, PH_BOOT_PHASE_DONE);
    fence_io();

    /* PHASE-B. EDN has no software-visible readback of "streaming", so whether
     * this took is adjudicated by the testbench watching the EDN outputs. */
    sep_entropy_enable_edn();
    fence_io();
    WRITE_REG(SC_PHASE, PH_EDN_ENABLED);
    fence_io();

    sep_smu_entropy_pass_loop();
}
