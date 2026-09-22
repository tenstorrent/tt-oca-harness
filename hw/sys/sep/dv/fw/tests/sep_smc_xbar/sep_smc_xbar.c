/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <stddef.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_smc_bringup.h" /* common: sep_smc_open_window / _bringup_from_sram / _scratch_* */
#include "smc_sep_xbar_protocol.h"

/*
 * smc_sep_xbar  --  SEP (consumer/producer) firmware.
 *
 * Force-free SEP-DRIVEN bring-up (no ext_in traffic to CPU_CTRL): the real SEP CPU opens its
 * outbound egress window, polls SMC SRAM for the exact preload cookie, then re-vectors +
 * releases the four SMC cores
 * over the SEP->SMC alias (sep_smc_bringup helpers). It then runs the fixed-alias
 * bidirectional datapath: SEP->SMC store/load of the correlated word at the dedicated
 * scratch8 alias (proves both remap stages), and the SMC->SEP command/DONE channel via the
 * SMU xbar into SEP cold scratch0, with a two-sided acknowledged completion (READY -> data
 * -> SCRATCH8_OK -> CMD -> ACK -> DONE -> SEP_PASS -> TEST_PASS). No force/deposit anywhere.
 *
 * Ordering (CHK-SEP-HOLD-RELEASE): the SEP-driven boot is gated on the SMC SRAM cookie, which
 * the TB preloads only AFTER real fuse sense completes, so the SEP cannot drive the SMC
 * CPU_CTRL before SMC fuse-done.  The DV side proves this passively (first CPU_CTRL AW strictly
 * after the SMC fuse-done edge).  The SEP filter/aperture programming is verified by the DV
 * side with passive DUT reads + the functional bidirectional datapath (the filter block is a
 * write-only programming interface -- a CPU read of it would stall -- so firmware does not read
 * it back).
 */

/* SEP inbound filter range (SMC->SEP writes to the cold scratch at SEP-local 0x10802000). */
#define SEP_INBOUND_SHARED_START ((uint64_t)SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0))
#define SEP_INBOUND_SHARED_END ((uint64_t)SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7) + 7ULL)
/* allow_burst (bit24) CLEARED -> 8-byte granularity so the 64-byte window keeps its EXACT END
 * 0x1080203F (with allow_burst=1 axi_filter_wrap.sv:105-108 rounds a same-4KB-page window's END up
 * to 0x10802FFF). Single-beat SMC->SEP cmd/done still pass (allow_burst only gates bursts). */
#define SMC_TO_SEP_FILTER_CONFIG 0x0000000100030013ULL
#define SMC_TO_SEP_NS_FILTER_CONFIG 0x0000000100030113ULL
/* Local filter-register offsets (prefixed to avoid clashing with sep_outbound_filter.h). */
#define XBAR_FILT_CFG_OFF \
    (SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0) - \
     SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0))
#define XBAR_FILT_START_OFF \
    (SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(0) - SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0))
#define XBAR_FILT_END_OFF \
    (SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(0) - SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0))
#define XBAR_FILT_STRIDE SEP_TOP_INBOUND_FILTER_CTRL_STRIDE

static volatile int g_xbar_status;

static inline void program_sep_smu_aperture(void) {
    WRITE_REG(SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR, (uint32_t)XBAR_SEP_APERTURE_SIZE);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static inline void open_sep_inbound_sram_window(void) {
    uintptr_t base = (uintptr_t)SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0);

    WRITE_REG64(base + XBAR_FILT_START_OFF, SEP_INBOUND_SHARED_START);
    WRITE_REG64(base + XBAR_FILT_END_OFF, SEP_INBOUND_SHARED_END);
    WRITE_REG64(base + XBAR_FILT_CFG_OFF, SMC_TO_SEP_FILTER_CONFIG);

    base += XBAR_FILT_STRIDE;
    WRITE_REG64(base + XBAR_FILT_START_OFF, SEP_INBOUND_SHARED_START);
    WRITE_REG64(base + XBAR_FILT_END_OFF, SEP_INBOUND_SHARED_END);
    WRITE_REG64(base + XBAR_FILT_CFG_OFF, SMC_TO_SEP_NS_FILTER_CONFIG);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

/* CHK-SEP-HOLD-RELEASE fw gate: block until the SMC fuse-sense-done status CSR reads 1 (the same
 * SEP-local register the SEP bootcode polls in pll_init.c). This is the SEP FW reading the SMC
 * fuse-done CSR BEFORE its first CPU_CTRL write, so the SEP never drives the SMC before SMC fuse
 * sense completes. Bounded; -1 on timeout. */
static int wait_smc_fuse_sense_done(void) {
    for (uint32_t i = 0; i < XBAR_FW_POLL_LIMIT; ++i) {
        if (READ_REG(XBAR_SMC_FUSE_STATUS_ADDR) & XBAR_FUSE_SENSE_DONE_MASK) {
            return 0;
        }
    }
    return -1;
}

/* Bounded read-only wait for the SMC image cookie in SRAM (preloaded post-fuse). No CPU_CTRL AW. */
static int wait_smc_sram_cookie(void) {
    for (uint32_t i = 0; i < XBAR_FW_POLL_LIMIT; ++i) {
        if (READ_REG(XBAR_SMC_SRAM_BASE_ALIAS) == XBAR_SMC_IMAGE_FIRST_WORD) {
            return 0;
        }
    }
    return -1;
}

static int run_smc_sep_xbar_sequence(void) {
    /* Inbound setup FIRST so the later SMC->SEP CMD/DONE writes to 0x10802000 are routable. */
    program_sep_smu_aperture();
    open_sep_inbound_sram_window();

    /* Open the SEP outbound egress window (SEP->SMC region) before any SEP->SMC access. */
    sep_smc_open_window();

    /* CHK-SETUP: clear the SMC->SEP command channel (our own cold scratch0) and read it back == 0
     * before the SMC can drive it. */
    WRITE_REG(XBAR_SEP_SHARED_ADDR, 0u);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(XBAR_SEP_SHARED_ADDR) != 0u) {
        return -31;
    }

    /* CHK-SEP-HOLD-RELEASE: read the SMC fuse-sense-done status CSR == 1 BEFORE the first CPU_CTRL
     * write (a SEP-local read; no sep_axi_in traffic). Then wait (read-only) for the SMC image
     * cookie. Only after BOTH does bring-up issue the first CPU_CTRL AW. */
    if (wait_smc_fuse_sense_done() != 0) {
        return -13;
    }
    if (wait_smc_sram_cookie() != 0) {
        sep_smc_scratch_write(XBAR_SCRATCH12_SEP, XBAR_S0_FAIL); /* preload never landed */
        return -11;
    }

    /* SEP-driven SMC boot: bring-up re-checks the cookie (already present) then writes the reset
     * vectors + RESET_CTRL pulse -- the FIRST sep_axi_in CPU_CTRL AW. */
    if (sep_smc_bringup_from_sram((uint32_t)XBAR_SMC_ENTRY, XBAR_SMC_IMAGE_FIRST_WORD,
                                  XBAR_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(XBAR_SCRATCH12_SEP, XBAR_S0_FAIL);
        return -11;
    }

    /* Wait for the SMC to publish SMC_READY (read via the SEP->SMC alias of SMC scratch2). */
    if (sep_smc_scratch_wait(XBAR_SMC_READY_ALIAS, XBAR_SMC_READY, XBAR_FW_POLL_LIMIT) != 0) {
        return -1;
    }

    /* SEP->SMC dedicated fixed-alias datapath: store the correlated word to scratch8, read it
     * back (exercises SEP global -> SMU remap -> SMC local rebase and back). */
    WRITE_REG(XBAR_SEP_TO_SMC_SCRATCH8_SEP, XBAR_DATA_PATTERN);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(XBAR_SEP_TO_SMC_SCRATCH8_SEP) != XBAR_DATA_PATTERN) {
        return -2;
    }

    /* Publish READY (setup done + data published). */
    sep_smc_scratch_write(XBAR_SCRATCH12_SEP, XBAR_SEP_READY);

    /* Wait for the SMC->SEP command (SMU xbar -> our cold scratch0). */
    if (sep_smc_scratch_wait(XBAR_SEP_SHARED_ADDR, XBAR_SMC_TO_SEP_CMD, XBAR_FW_POLL_LIMIT) != 0) {
        return -3;
    }
    sep_smc_scratch_write(XBAR_SCRATCH12_SEP, XBAR_SEP_TO_SMC_ACK);

    /* Wait for the SMC->SEP DONE. */
    if (sep_smc_scratch_wait(XBAR_SEP_SHARED_ADDR, XBAR_SMC_TO_SEP_DONE, XBAR_FW_POLL_LIMIT) != 0) {
        return -4;
    }

    /* Datapath complete both ways: publish SEP_PASS. */
    sep_smc_scratch_write(XBAR_SCRATCH12_SEP, XBAR_SEP_PASS);
    return 0;
}

__attribute__((noinline, used)) void smc_sep_xbar_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((noinline, used)) void smc_sep_xbar_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    g_xbar_status = run_smc_sep_xbar_sequence();

    if (g_xbar_status == 0) {
        smc_sep_xbar_pass_loop();
    } else {
        smc_sep_xbar_fail_loop();
    }

    return g_xbar_status;
}
