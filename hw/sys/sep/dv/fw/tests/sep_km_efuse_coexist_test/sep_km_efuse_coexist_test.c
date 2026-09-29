/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * SEP eFuse KM/EL2 mux coexistence firmware (eFuse Suite 10.3).
 *
 * The REAL SEP EL2 CPU (host) and the REAL KM CPU both drive the eFuse through
 * efuse_interface_controller.u_km_efuse_axi_lite_mux at the same time:
 *   - This EL2 firmware handshakes with the KM over the KM<->SEP mailbox
 *     (receive KM READY, send GO), then loops issuing host eFuse reads and
 *     self-checks that CHIPLET_UID stays correct under KM contention.
 *   - The KM (test_efuse_km_coexist) free-runs eFuse writes once it gets GO.
 * Scratch-cold registers give the UVM a lightweight progress/handshake view.
 ******************************************************************************/

#include <stdint.h>
#include <stdio.h>

#include "efuse_fw_test_common.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define SYNC_CPU_READY_REG SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0) /* EL2 -> UVM : ready  */
#define SYNC_UVM_DONE_REG SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(1)  /* UVM -> EL2 : done   */
#define SYNC_CPU_COUNT_REG SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(2) /* host loop count     */
/* Measured-evidence summary (read + checked directly by the UVM): */
#define SYNC_BAD_UID_REG \
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(3) /* CHIPLET_UID corrupt count */
#define SYNC_MMR_CHANGES_REG \
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(4) /* KM counter changes seen   */
#define SYNC_MMR_BACK_REG \
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(5) /* KM counter went backward  */
#define SYNC_MMR_BADTAG_REG \
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6) /* tag/attribution failures  */

/* KM-owned MMR pattern (must match test_efuse_km_coexist.c). */
#define MMR0_ADDR SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0)
#define MMR1_ADDR SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(1)
#define KM_TAG0 0xA5000000u
#define KM_TAG1 0x5A000000u
#define KM_TAG_MASK 0xFF000000u
#define KM_PAYLOAD_MASK 0x00FFFFFFu

#define CPU_READY_MARKER 0xE9050001u
#define UVM_DONE_MARKER 0xE90500D0u

/* Mailbox handshake tokens (must match test_efuse_km_coexist.c). */
#define KM_READY_TOKEN 0xA11FE5EEu /* KM -> EL2 : KM up and ready  */
#define EL2_GO_TOKEN 0x60600060u   /* EL2 -> KM : start write loop */

/* SEP Reset Controller: release the KM CPU from warm/software reset. */
#define SW_RESET_N_ADDR SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR
#define SW_RESET_N_KM_MASK 0x1u /* bit0 = km_sw_rst_n */

#define KNOWN_UID 0xDEADBEEFu /* CHIPLET_UID word0 (default_efuse preload) */

#define MIN_CPU_EFUSE_LOOPS 256u
#define MAX_CPU_EFUSE_LOOPS 200000u
#define MBOX_WAIT_LIMIT 500000u

/* Receive one word from the KM (outbound FIFO), bounded. */
static int km_mbox_get(uint32_t *word) {
    uint32_t guard = MBOX_WAIT_LIMIT;
    while (guard != 0u) {
        if ((READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_STATUS_BASE_ADDR) &
             KM_MAILBOX_SEP__STATUS_REG__OUTBOUND_EMPTY_bm) == 0u) {
            *word = READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_READ_DATA_BASE_ADDR);
            return 0;
        }
        guard--;
    }
    return -1;
}

/* Send one word to the KM (inbound FIFO), separator-terminated. */
static void km_mbox_send(uint32_t word) {
    WRITE_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_WRITE_SEPARATOR_BASE_ADDR, 1u);
    WRITE_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_WRITE_DATA_BASE_ADDR, word);
}

int main(void) {
    uint32_t loop_count = 0u;
    uint32_t km_ready = 0u;
    uint32_t bad_uid = 0u;      /* host MAP read corrupted under contention   */
    uint32_t mmr_changes = 0u;  /* KM counter advanced (KM reached the mux)   */
    uint32_t mmr_backward = 0u; /* KM counter went backward (torn/stale)      */
    uint32_t mmr_bad_tag = 0u;  /* wrong owner tag or m1<m0 (cross-attribution)*/
    uint32_t last_p0 = 0u;
    uint32_t started = 0u; /* set once both KM owner tags are first seen */

    sep_outbound_filter_init();
    printf("SEP eFuse KM/EL2 mux coexistence FW test\n");

    if (efuse_wait_sense_done() != 0) {
        printf("ERROR: fuse sense did not complete\n");
        goto fail;
    }

    WRITE_REG(SYNC_UVM_DONE_REG, 0u);
    WRITE_REG(SYNC_CPU_COUNT_REG, 0u);

    /* Release the KM CPU from warm/software reset (the SEP host brings the KM
     * up). Without this the KM never boots and the handshake below times out. */
    {
        uint32_t rv = READ_REG(SW_RESET_N_ADDR);
        WRITE_REG(SW_RESET_N_ADDR, rv | SW_RESET_N_KM_MASK);
    }

    /* --- Mailbox handshake with the KM CPU: wait READY, then send GO. --- */
    if ((km_mbox_get(&km_ready) != 0) || (km_ready != KM_READY_TOKEN)) {
        printf("ERROR: KM READY not received (got 0x%08x)\n", km_ready);
        goto fail;
    }
    km_mbox_send(EL2_GO_TOKEN);
    printf("KM handshake complete (READY rx / GO tx); starting concurrent loop\n");

    WRITE_REG(SYNC_CPU_READY_REG, CPU_READY_MARKER);

    /* --- Concurrent host eFuse loop: sample + validate KM evidence each pass. --- */
    while (loop_count < MAX_CPU_EFUSE_LOOPS) {
        uint32_t m0, m1, p0, p1;

        /* (a) Stable host MAP read must not be corrupted by KM MMR writes. */
        if (READ_REG(SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR) != KNOWN_UID) {
            bad_uid++;
        }

        /* (b) Sample the two KM-owned MMR registers. */
        m0 = READ_REG(MMR0_ADDR);
        m1 = READ_REG(MMR1_ADDR);
        p0 = m0 & KM_PAYLOAD_MASK;
        p1 = m1 & KM_PAYLOAD_MASK;

        /* Warm-up: don't validate until both owner tags are first observed, so
         * pre-first-write reset/default MMR values are not counted as errors. */
        if (started == 0u) {
            if (((m0 & KM_TAG_MASK) == KM_TAG0) && ((m1 & KM_TAG_MASK) == KM_TAG1)) {
                started = 1u;
                last_p0 = p0;
            }
        } else {
            if ((m0 & KM_TAG_MASK) != KM_TAG0) mmr_bad_tag++; /* MMR0 must carry tag A5 */
            if ((m1 & KM_TAG_MASK) != KM_TAG1) mmr_bad_tag++; /* MMR1 must carry tag 5A */
            if (p1 < p0) mmr_bad_tag++;                       /* MMR1 leads -> p1>=p0   */
            if (p0 != last_p0) mmr_changes++;
            if (p0 < last_p0) mmr_backward++; /* KM only increments (no wrap in-window) */
            last_p0 = p0;
        }

        loop_count++;
        WRITE_REG(SYNC_CPU_COUNT_REG, loop_count);
        WRITE_REG(SYNC_BAD_UID_REG, bad_uid);
        WRITE_REG(SYNC_MMR_CHANGES_REG, mmr_changes);
        WRITE_REG(SYNC_MMR_BACK_REG, mmr_backward);
        WRITE_REG(SYNC_MMR_BADTAG_REG, mmr_bad_tag);

        if ((READ_REG(SYNC_UVM_DONE_REG) == UVM_DONE_MARKER) &&
            (loop_count >= MIN_CPU_EFUSE_LOOPS)) {
            break;
        }
    }

    printf("EL2 coexist summary: loops=%u bad_uid=%u mmr_changes=%u backward=%u bad_tag=%u\n",
           loop_count, bad_uid, mmr_changes, mmr_backward, mmr_bad_tag);

    if (loop_count >= MAX_CPU_EFUSE_LOOPS) {
        printf("ERROR: UVM did not signal DONE (loop_count=%u)\n", loop_count);
        goto fail;
    }
    /* Measured verdict: KM must have made progress, with zero integrity errors. */
    if ((mmr_changes == 0u) || (bad_uid != 0u) || (mmr_backward != 0u) || (mmr_bad_tag != 0u)) {
        printf("ERROR: mux coexistence integrity failure\n");
        goto fail;
    }

    printf("*** mux coexistence PASSED ***\n");
    test_pass(0);
    while (1) {
        __asm__("wfi");
    }

fail:
    /* Single failure path: report once and never fall through to test_pass(). */
    test_fail(1);
    while (1) {
        __asm__("wfi");
    }
}
