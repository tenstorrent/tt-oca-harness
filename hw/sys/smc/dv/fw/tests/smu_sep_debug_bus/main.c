/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "sep_smu_debug_bus_protocol.h"
#include "sep_debug_bus_symbols.h"

/*
 * smu_sep_debug_bus -- SMC DFD-arm (CONSUMER) firmware.
 *
 * Card S3: clear scratch2/3, publish PH_CLEARED, then wait for SEP_WAIT.
 * Programs DFX L3/L2 DBM + DFD CDbgMuxSel + CLA mask/match (bogus negative,
 * then exact marker PC), then writes GO.
 * Closure values are read back here; the cocotb checker also observes the
 * CLA CSRs passively. Stackless: no function calls in main().
 *
 * DFX DBM uses generated 0xC000B810 (card text 0xC000F810 is map drift).
 */
SMC_STACKLESS_ENTRY(smu_sep_debug_bus_entry)

#define DEBUG_BUS_MATCH_BOGUS ((uint64_t)DEBUG_BUS_BOGUS_TRACE16 << 48)
#define DEBUG_BUS_MATCH_EXACT ((uint64_t)DEBUG_BUS_MARKER_TRACE16 << 48)

#define DFX_DBM SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR
/* Generated map splits the 64-bit CLA mux/mask/match/snapshot words. */
#define DFD_MUX_LO SMC_TOP_SMC_CLA_CLA_CDBGMUXSELLO_BASE_ADDR(0)
#define DFD_MUX_HI SMC_TOP_SMC_CLA_CLA_CDBGMUXSELHI_BASE_ADDR(0)
#define CLA_MASK0_LO SMC_TOP_SMC_CLA_CLA_CDBGSIGNALMASK0LO_BASE_ADDR(0)
#define CLA_MASK0_HI SMC_TOP_SMC_CLA_CLA_CDBGSIGNALMASK0HI_BASE_ADDR(0)
#define CLA_MATCH0_LO SMC_TOP_SMC_CLA_CLA_CDBGSIGNALMATCH0LO_BASE_ADDR(0)
#define CLA_MATCH0_HI SMC_TOP_SMC_CLA_CLA_CDBGSIGNALMATCH0HI_BASE_ADDR(0)
#define CLA_SNAP_LO SMC_TOP_SMC_CLA_CLA_CDBGSIGNALSNAPSHOTNODE0EAP0LO_BASE_ADDR(0)
#define CLA_SNAP_HI SMC_TOP_SMC_CLA_CLA_CDBGSIGNALSNAPSHOTNODE0EAP0HI_BASE_ADDR(0)
#define CLA_EAP0 SMC_TOP_SMC_CLA_CLA_CDBGNODE0EAP0_BASE_ADDR(0)
#define CLA_STATUS SMC_TOP_SMC_CLA_CLA_CDBGEAPSTATUS_BASE_ADDR(0)
#define CLA_CTRL SMC_TOP_SMC_CLA_CLA_CDBGCLACTRLSTATUS_BASE_ADDR(0)

#define SMC_WR64_LOHI(lo, hi, v) \
    do { \
        SMC_WR32((lo), (uint32_t)(v)); \
        SMC_WR32((hi), (uint32_t)((uint64_t)(v) >> 32)); \
    } while (0)
#define SMC_RD64_LOHI(lo, hi) ((uint64_t)SMC_RD32(lo) | ((uint64_t)SMC_RD32(hi) << 32))

/* W2C is rise-edge only. Drop bit32 first so a later write of bit32 pulses. */
#define DEBUG_BUS_W2C_PULSE() \
    do { \
        SMC_WR64(CLA_STATUS, 0ULL); \
        SMC_FENCE(); \
        SMC_WR64(CLA_STATUS, DEBUG_BUS_CLA_W2C); \
        SMC_FENCE(); \
    } while (0)

__attribute__((naked, section(".text"), used)) void smu_sep_debug_bus_smc_pass_loop(void) {
    __asm__ volatile("1:\n wfi\n j 1b\n");
}
__attribute__((naked, section(".text"), used)) void smu_sep_debug_bus_smc_fail_loop(void) {
    __asm__ volatile("1:\n wfi\n j 1b\n");
}

int main(void) {
    uint32_t ok;
    uint64_t st = 0;
    uint64_t snap = 0;

    /* CPU_CTRL scratch is 64-bit; 32-bit sw/lw can read X in the unused
     * half right after the SEP reset pulse. */
    SMC_DELAY_ITERS(1024);
    SMC_WR64(DEBUG_BUS_SMC_SCRATCH2, 0ULL);
    SMC_WR64(DEBUG_BUS_SMC_SCRATCH3, 0ULL);
    SMC_WR64(DEBUG_BUS_SMC_SCRATCH4, 0ULL);
    SMC_WR64(DEBUG_BUS_SMC_SCRATCH9, 0ULL);
    SMC_WR64(DEBUG_BUS_SMC_SCRATCH10, 0ULL);
    SMC_WR64(DEBUG_BUS_SMC_SCRATCH14, 0ULL);
    SMC_WR64(DEBUG_BUS_SMC_SCRATCH15, 0ULL);
    SMC_FENCE();
    st = SMC_RD64(DEBUG_BUS_SMC_SCRATCH2);
    if (st != 0ULL) {
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH9, (uint32_t)st);
        goto fail;
    }
    st = SMC_RD64(DEBUG_BUS_SMC_SCRATCH3);
    if (st != 0ULL) {
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH9, (uint32_t)st);
        goto fail;
    }
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH4, DEBUG_BUS_PH_CLEARED);
    SMC_FENCE();

    SMC_WAIT_EQ(DEBUG_BUS_SMC_SCRATCH3, DEBUG_BUS_SEP_WAIT, DEBUG_BUS_HANDSHAKE_POLL_LIMIT, ok);
    if (!ok) goto fail;

    /* CLA powers up enabled; CDBGCLACTRLSTATUS is the remaining gate. */
    SMC_WR64(DFX_DBM, (uint64_t)DEBUG_BUS_DFX_DBM_ID13);
    SMC_FENCE();
    if (SMC_RD64(DFX_DBM) != (uint64_t)DEBUG_BUS_DFX_DBM_ID13) goto fail;
    SMC_WR64(DFX_DBM, (uint64_t)DEBUG_BUS_DFX_DBM_ID6);
    SMC_FENCE();
    if (SMC_RD64(DFX_DBM) != (uint64_t)DEBUG_BUS_DFX_DBM_ID6) goto fail;

    SMC_WR64_LOHI(DFD_MUX_LO, DFD_MUX_HI, DEBUG_BUS_DFD_DBM_ID1);
    SMC_FENCE();
    if (SMC_RD64_LOHI(DFD_MUX_LO, DFD_MUX_HI) != DEBUG_BUS_DFD_DBM_ID1) goto fail;
    SMC_WR64_LOHI(DFD_MUX_LO, DFD_MUX_HI, DEBUG_BUS_DFD_DBM_ID2);
    SMC_FENCE();
    if (SMC_RD64_LOHI(DFD_MUX_LO, DFD_MUX_HI) != DEBUG_BUS_DFD_DBM_ID2) goto fail;

    SMC_WR64_LOHI(CLA_MASK0_LO, CLA_MASK0_HI, DEBUG_BUS_CLA_MASK0);
    SMC_FENCE();
    if (SMC_RD64_LOHI(CLA_MASK0_LO, CLA_MASK0_HI) != DEBUG_BUS_CLA_MASK0) goto fail;

    SMC_WR64_LOHI(CLA_MATCH0_LO, CLA_MATCH0_HI, DEBUG_BUS_MATCH_BOGUS);
    SMC_FENCE();
    if (SMC_RD64_LOHI(CLA_MATCH0_LO, CLA_MATCH0_HI) != DEBUG_BUS_MATCH_BOGUS) goto fail;
    SMC_WR64(CLA_EAP0, DEBUG_BUS_CLA_EAP0);
    DEBUG_BUS_W2C_PULSE();
    if ((SMC_RD64(CLA_STATUS) & 1ULL) != 0ULL) goto fail;
    SMC_WR64(CLA_CTRL, (uint64_t)DEBUG_BUS_CLA_CTRL);
    SMC_FENCE();
    if (SMC_RD64(CLA_CTRL) != (uint64_t)DEBUG_BUS_CLA_CTRL) goto fail;
    DEBUG_BUS_W2C_PULSE();
    if ((SMC_RD64(CLA_STATUS) & 1ULL) != 0ULL) goto fail;
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH4, DEBUG_BUS_PH_NEG_ARMED);
    SMC_FENCE();

    SMC_DELAY_ITERS(DEBUG_BUS_NEG_HOLD_ITERS);
    st = SMC_RD64(CLA_STATUS);
    snap = SMC_RD64_LOHI(CLA_SNAP_LO, CLA_SNAP_HI);
    if ((st & 1ULL) != 0ULL) {
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH9, (uint32_t)((snap >> 48) & 0xFFFFULL));
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH11, (uint32_t)st);
        goto fail;
    }
    if (SMC_RD32(DEBUG_BUS_SMC_SCRATCH2) != 0u) goto fail;
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH4, DEBUG_BUS_PH_NEG_OK);
    SMC_FENCE();

    SMC_WR64(CLA_CTRL, (uint64_t)DEBUG_BUS_CLA_CTRL_CLK);
    SMC_FENCE();
    SMC_WR64_LOHI(CLA_MATCH0_LO, CLA_MATCH0_HI, DEBUG_BUS_MATCH_EXACT);
    SMC_FENCE();
    if (SMC_RD64_LOHI(CLA_MATCH0_LO, CLA_MATCH0_HI) != DEBUG_BUS_MATCH_EXACT) goto fail;
    DEBUG_BUS_W2C_PULSE();
    if ((SMC_RD64(CLA_STATUS) & 1ULL) != 0ULL) goto fail;
    SMC_WR64(CLA_CTRL, (uint64_t)DEBUG_BUS_CLA_CTRL);
    SMC_FENCE();
    /* Let gated CLA clocks run with the exact match before GO. */
    SMC_DELAY_ITERS(256);
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH4, DEBUG_BUS_PH_EXACT_ARMED);
    SMC_FENCE();

    SMC_WR32(DEBUG_BUS_SMC_SCRATCH2, DEBUG_BUS_GO);
    SMC_FENCE();
    if (SMC_RD32(DEBUG_BUS_SMC_SCRATCH2) != DEBUG_BUS_GO) goto fail;
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH4, DEBUG_BUS_PH_GO);
    SMC_FENCE();

    SMC_WAIT_EQ(DEBUG_BUS_SMC_SCRATCH3, DEBUG_BUS_GO_SEEN, DEBUG_BUS_HANDSHAKE_POLL_LIMIT, ok);
    if (!ok) goto fail;
    /* Marker PC crosses a 3FF CDC + DFX/DFD mux before CLA. A 512-poll
     * loop finishes before the match flop sees the marker; hold, then
     * sample. */
    SMC_DELAY_ITERS(DEBUG_BUS_EXACT_HOLD_ITERS);
    st = 0;
    snap = 0;
    for (uint32_t i = 0; i < 16; ++i) {
        st = SMC_RD64(CLA_STATUS);
        snap = SMC_RD64_LOHI(CLA_SNAP_LO, CLA_SNAP_HI);
        if (((st & 1ULL) != 0ULL) &&
            (((snap >> 48) & 0xFFFFULL) == (uint64_t)DEBUG_BUS_MARKER_TRACE16)) {
            break;
        }
        SMC_DELAY_ITERS(256);
    }
    if ((st & 1ULL) == 0ULL || (((snap >> 48) & 0xFFFFULL) != (uint64_t)DEBUG_BUS_MARKER_TRACE16)) {
        /* Exact match missed after CDC hold. Dump live CLA + MATCH/MASK; do
         * not re-arm always-on (that is not CHK-BUS-UPDATE). */
        uint64_t match_rb = SMC_RD64_LOHI(CLA_MATCH0_LO, CLA_MATCH0_HI);
        uint64_t mask_rb = SMC_RD64_LOHI(CLA_MASK0_LO, CLA_MASK0_HI);
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH9, (uint32_t)((snap >> 48) & 0xFFFFULL));
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH11, (uint32_t)st);
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH12, (uint32_t)snap);
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH13, (uint32_t)(snap >> 32));
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH14, (uint32_t)match_rb);
        SMC_WR32(DEBUG_BUS_SMC_SCRATCH15,
                 (uint32_t)(match_rb >> 32) | (((uint32_t)(mask_rb >> 32) & 0xFFFFu) << 16));
        SMC_FENCE();
        goto fail;
    }
    /* Publish CLA results on wrap-visible GPI scratch before W2C. After the
     * marker self-loop, hierarchical CLA/XMR probes stall VCS. */
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH9, (uint32_t)((snap >> 48) & 0xFFFFULL));
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH11, (uint32_t)st);
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH12, (uint32_t)snap);
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH13, (uint32_t)(snap >> 32));
    SMC_FENCE();
    if ((st & 1ULL) == 0ULL) goto fail;
    if (((snap >> 48) & 0xFFFFULL) != (uint64_t)DEBUG_BUS_MARKER_TRACE16) goto fail;

    SMC_WR64(CLA_CTRL, (uint64_t)DEBUG_BUS_CLA_CTRL_CLK);
    SMC_FENCE();
    DEBUG_BUS_W2C_PULSE();
    if ((SMC_RD64(CLA_STATUS) & 1ULL) != 0ULL) goto fail;
    SMC_DELAY_ITERS(DEBUG_BUS_QUIET_HOLD_ITERS);
    if ((SMC_RD64(CLA_STATUS) & 1ULL) != 0ULL) goto fail;
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH4, DEBUG_BUS_PH_CLEARED_EAP);
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH10, DEBUG_BUS_SMC_PASS);
    SMC_FENCE();
    __asm__ volatile("j smu_sep_debug_bus_smc_pass_loop");

fail:
    SMC_WR32(DEBUG_BUS_SMC_SCRATCH10, DEBUG_BUS_SMC_FAIL);
    SMC_FENCE();
    __asm__ volatile("j smu_sep_debug_bus_smc_fail_loop");
    return 0;
}
