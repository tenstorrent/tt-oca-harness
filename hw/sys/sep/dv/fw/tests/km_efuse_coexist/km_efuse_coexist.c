// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP dual-CPU eFuse AXI-lite mux coexistence firmware (EL2 host side).
//
// The EL2 host and the Key Manager (KM) CPU, running km_rom_coexist.S, contend
// at the eFuse AXI-lite mux. The host waits for fuse sense, releases the KM from
// software reset, handshakes over the KM<->SEP mailbox, then runs a fixed window
// of CONTENDED_LOOPS iterations. Each iteration reads the host CHIPLET_UID, which
// must keep its preloaded value, and the two KM-owned MMRs. The host publishes a
// summary to the scratch-cold words for the cocotb observer and returns the error
// count; crt0.s turns 0 into the PASS magic and any other value into FAIL.
//
// The KM writes MMR1 (lead) then MMR0 (trail), each with its own owner tag and
// the same incrementing payload, so a correct mux always gives tag-correct,
// monotonic reads with MMR1 >= MMR0. A torn, stale or cross-attributed response,
// or a corrupted host UID, fails the test.
//
// The window is fixed because the observer is read-only. Non-starvation needs
// the host to finish all CONTENDED_LOOPS and the KM to make progress in the same
// window.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_km_mailbox.h"
#include "sep_reset.h"
#include "sep_efuse.h"
#include "sep_scratch_drv.h"

// --- Shared coexistence protocol (MUST match km_rom_coexist.S and the cocotb
//     observer sep_efuse_km_axil_cpu_mux_coexist_test.py). ---
#define KM_READY_TOKEN 0xA11FE5EEu // KM -> EL2: KM up
#define EL2_GO_TOKEN 0x60600060u   // EL2 -> KM: start contending
#define KM_TAG0 0xA5000000u        // owner tag on MMR0
#define KM_TAG1 0x5A000000u        // owner tag on MMR1
#define KM_TAG_MASK 0xFF000000u
#define KM_PAYLOAD_MASK 0x00FFFFFFu  // 24-bit counter payload
#define KNOWN_UID 0xDEADBEEFu        // golden CHIPLET_UID word0 (image preload)
#define CPU_READY_MARKER 0xE9050001u // EL2 -> observer: both CPUs up

// Scratch-cold word layout the cocotb observer reads back.
#define SCRATCH_READY 0u    // EL2 -> observer: CPU_READY_MARKER
#define SCRATCH_COUNT 2u    // host loop counter
#define SCRATCH_BAD_UID 3u  // host CHIPLET_UID corruption count
#define SCRATCH_CHANGES 4u  // KM counter changes witnessed
#define SCRATCH_BACKWARD 5u // KM counter went backward count
#define SCRATCH_BAD_TAG 6u  // KM tag/attribution/ordering failure count

// Fixed contended window, long enough that the free-running KM makes many MMR
// changes through the mux while the slower host completes.
#define CONTENDED_LOOPS 512u
#define SENSE_WAIT_LIMIT 1000000
#define MBOX_WAIT_LIMIT 500000

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the mailbox window
    sep_mbx_puts("SEP KM-eFuse mux coexist test\n");

    // Real fuse-sense must be complete before the host CHIPLET_UID read path is
    // meaningful. cocotb also gates the run on sense-done, so this returns fast.
    if (sep_efuse_wait_sense_done(SENSE_WAIT_LIMIT) != 0) {
        sep_mbx_puts("FAIL: fuse sense never completed\n");
        return 1;
    }

    // Clear the summary scratch words before publishing READY.
    sep_scratch_wr(SCRATCH_READY, 0);
    sep_scratch_wr(SCRATCH_COUNT, 0);
    sep_scratch_wr(SCRATCH_BAD_UID, 0);
    sep_scratch_wr(SCRATCH_CHANGES, 0);
    sep_scratch_wr(SCRATCH_BACKWARD, 0);
    sep_scratch_wr(SCRATCH_BAD_TAG, 0);

    // Release the KM, then handshake: receive READY, send GO. (Release BEFORE
    // waiting for READY, or the KM -- still in reset -- can never send it.)
    sep_reset_release_km();
    sep_mbx_puts("STEP Key Manager released from software reset\n");

    uint32_t km_ready = 0;
    if (sep_km_mbox_get(&km_ready, MBOX_WAIT_LIMIT) != 0) {
        sep_mbx_puts("FAIL: KM READY not received (mailbox timeout)\n");
        return 1;
    }
    if (km_ready != KM_READY_TOKEN) {
        sep_mbx_puts("FAIL: bad KM READY token\n");
        return 1;
    }
    sep_km_mbox_send(EL2_GO_TOKEN);
    sep_mbx_puts("KM READY received; EL2 GO sent\n");

    // Both cores are up and contending at the mux.
    sep_scratch_wr(SCRATCH_READY, CPU_READY_MARKER);

    uint32_t bad_uid = 0, changes = 0, backward = 0, bad_tag = 0;
    uint32_t last_p0 = 0;
    int started = 0;

    for (uint32_t loop = 0; loop < CONTENDED_LOOPS; loop++) {
        // Host data integrity: a concurrent KM MMR write through the shared mux
        // must never corrupt the host CHIPLET_UID read.
        uint32_t uid = sep_efuse_rd(SEP_EFUSE_CHIPLET_UID0);
        if (uid != KNOWN_UID) {
            bad_uid++;
        }

        // KM-owned MMRs: read MMR0 then MMR1 (KM writes MMR1 lead, MMR0 trail).
        uint32_t m0 = sep_efuse_rd(SEP_EFUSE_MMR0);
        uint32_t m1 = sep_efuse_rd(SEP_EFUSE_MMR1);
        uint32_t p0 = m0 & KM_PAYLOAD_MASK;
        uint32_t p1 = m1 & KM_PAYLOAD_MASK;

        if (!started) {
            // Warm-up: don't validate until the KM has written both MMRs once.
            if ((m0 & KM_TAG_MASK) == KM_TAG0 && (m1 & KM_TAG_MASK) == KM_TAG1) {
                started = 1;
                last_p0 = p0;
            }
        } else {
            if ((m0 & KM_TAG_MASK) != KM_TAG0) bad_tag++; // cross-attribution
            if ((m1 & KM_TAG_MASK) != KM_TAG1) bad_tag++;
            if (p1 < p0) bad_tag++;       // lead/trail ordering
            if (p0 != last_p0) changes++; // KM progress
            if (p0 < last_p0) backward++; // torn/stale response
            last_p0 = p0;
        }
        sep_scratch_wr(SCRATCH_COUNT, loop + 1);
    }

    // Publish the measured summary for the cocotb observer.
    sep_scratch_wr(SCRATCH_BAD_UID, bad_uid);
    sep_scratch_wr(SCRATCH_CHANGES, changes);
    sep_scratch_wr(SCRATCH_BACKWARD, backward);
    sep_scratch_wr(SCRATCH_BAD_TAG, bad_tag);

    if (changes == 0) {
        sep_mbx_puts("FAIL: KM made no progress through the mux\n");
        errors++;
    }
    if (bad_uid != 0) {
        sep_mbx_puts("FAIL: host CHIPLET_UID corrupted under KM contention\n");
        errors++;
    }
    if (backward != 0) {
        sep_mbx_puts("FAIL: KM counter went backward (torn/stale mux response)\n");
        errors++;
    }
    if (bad_tag != 0) {
        sep_mbx_puts("FAIL: KM MMR tag/ordering failure (cross-attribution)\n");
        errors++;
    }
    if (errors == 0) {
        sep_mbx_puts("PASS: KM+EL2 eFuse mux coexistence verified\n");
    }
    return errors;
}
