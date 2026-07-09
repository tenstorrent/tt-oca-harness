/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_sram_exec.c
 * @brief CMD_SRAM_EXEC warm-reset restart test.
 *
 * Verifies that CMD_SRAM_EXEC restarts previously-loaded mutable firmware
 * after a warm reset, using sram_fw_size (stored in rom_persist) as the
 * phase indicator.
 *
 * Phase 0 (cold boot, sram_fw_size == 0):
 *   1. Copy mutable_fw_blob_small (14 words, 56 bytes) to SRAM at 0x4000
 *      using memcpy.  The blob is in the mutable-firmware load area (below
 *      the ROM stack / .data / .bss).
 *   2. Record sram_fw_size = MUTABLE_FW_BLOB_SMALL_WORDS * 4 in rom_persist
 *      so the value survives a warm reset.
 *   3. Issue a warm reset via TB_CMD_KM_WARM_RESET.  The SRAM blob and the
 *      persisted sram_fw_size survive because warm reset does not clear SRAM.
 *
 * Phase 1 (warm reset, sram_fw_size != 0):
 *   1. rom_boot_init() runs (warm-boot path; does not re-zero sram_fw_size).
 *   2. Drain RESP_KM_READY.
 *   3. Send CMD_SRAM_EXEC (0-payload command).
 *   4. rom_msg_rx_process() dispatches to rom_cmd_sram_exec →
 *      rom_handover_exec_existing → rom_handover_finish.
 *   5. rom_handover_finish: lock OTP, lock rom_persist, apply SRAM write-lock
 *      for region 0 (covering the blob at 0x4000..0x41FF), disable all IRQs,
 *      call rom_handover_jump.S.
 *   6. rom_handover_jump.S: scrambles unlocked SRAM (write-locked region 0 is
 *      unaffected), clears GPRs, jumps to 0x4000.
 *   7. Mutable blob runs and writes TEST_PASS_SIGNATURE → test passes.
 *
 * Phase detection uses rom_persist_get_sram_fw_size():
 *   sram_fw_size == 0  → Phase 0 (cold boot, no firmware loaded)
 *   sram_fw_size != 0  → Phase 1 (warm reset, firmware copied in Phase 0)
 *
 * The sram_fw_size lives in the rom_persist region (0x7E00), which is outside
 * the BSS section cleared by crt0 on warm restart; it therefore survives the
 * warm reset, making it a reliable phase indicator.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_sram_exec
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"
#include "rom_boot.h"
#include "rom_persist.h"
#include "test_mutable_fw_blob.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

int main(void) {
    TEST_INIT();

    rom_boot_init();

    /*=====================================================================
     * Phase detection: use sram_fw_size from rom_persist.
     * Phase 0: cold boot → sram_fw_size == 0 (zeroed by cold-only init).
     * Phase 1: warm reset → sram_fw_size == MUTABLE_FW_BLOB_SMALL_WORDS * 4.
     *=====================================================================*/
    uint32_t fw_size = rom_persist_get_sram_fw_size();

    if (fw_size == 0u) {
        /*=================================================================
         * Phase 0: cold boot — set up SRAM and warm reset.
         *=================================================================*/
        if (!tb_set_timeout(2000000)) TEST_FAIL("timeout set failed");

        if (!tb_drbg_set_seed(0xE030u, 5000)) TEST_FAIL("drbg set seed failed");

        TEST_SUBTEST_START("Phase 0: copy blob to SRAM 0x4000");
        {
            void *sram_base = (void *)SRAM_BASE; /* 0x4000 */
            memcpy(sram_base, mutable_fw_blob_small, MUTABLE_FW_BLOB_SMALL_WORDS * 4u);
            __asm__ volatile("fence" ::: "memory");

            /* Quick readback sanity check (first word only). */
            volatile uint32_t *sram_ptr = (volatile uint32_t *)SRAM_BASE;
            if (*sram_ptr != mutable_fw_blob_small[0]) {
                TEST_FAIL("Phase 0: blob readback mismatch at 0x4000 "
                          "(got 0x%08X, expected 0x%08X)",
                          (unsigned)*sram_ptr, (unsigned)mutable_fw_blob_small[0]);
            }
        }
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: set sram_fw_size in rom_persist");
        {
            uint32_t size_bytes = MUTABLE_FW_BLOB_SMALL_WORDS * 4u; /* 56 */
            rom_persist_set_sram_fw_size(size_bytes);
            __asm__ volatile("fence" ::: "memory");

            uint32_t readback = rom_persist_get_sram_fw_size();
            if (readback != size_bytes) {
                TEST_FAIL("Phase 0: sram_fw_size readback mismatch "
                          "(got 0x%08X, expected 0x%08X)",
                          (unsigned)readback, (unsigned)size_bytes);
            }
        }
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: trigger warm reset");
        {
            if (!tb_km_warm_reset(5000u)) TEST_FAIL("TB_CMD_KM_WARM_RESET not acknowledged");
            /* Should not reach here. */
            TEST_FAIL("execution continued after warm reset");
        }

    } else {
        /*=================================================================
         * Phase 1: warm reset — send CMD_SRAM_EXEC and jump to mutable fw.
         *=================================================================*/
        if (!tb_set_timeout(2000000)) TEST_FAIL("Phase 1: timeout set failed");

        if (!tb_drbg_set_seed(0xE031u, 5000)) TEST_FAIL("Phase 1: drbg set seed failed");

        TEST_SUBTEST_START("Phase 1: sram_fw_size survived warm reset");
        {
            uint32_t expected = MUTABLE_FW_BLOB_SMALL_WORDS * 4u; /* 56 */
            if (fw_size != expected) {
                TEST_FAIL("Phase 1: sram_fw_size mismatch "
                          "(got 0x%08X, expected 0x%08X)",
                          (unsigned)fw_size, (unsigned)expected);
            }
        }
        TEST_SUBTEST_PASS();

        /* Drain RESP_KM_READY sent by rom_boot_init() on this warm boot. */
        {
            uint32_t ready;
            if (!tb_sep_mbox_read(&ready, 5000))
                TEST_FAIL("Phase 1: No RESP_KM_READY after warm reset");
        }

        /*
         * Send CMD_SRAM_EXEC (0-payload, single header word with separator).
         * The ISR processes the 1-word frame and places it in rom_rx_msgbuf.
         * rom_msg_rx_process() dispatches to rom_cmd_sram_exec, which calls
         * rom_handover_exec_existing, which calls rom_handover_finish.
         *
         * rom_handover_finish:
         *   - Locks OTP, rom_persist.
         *   - Sets SRAM write-lock for region 0 (firmware blob at 0x4000..0x41FF).
         *   - Disables all IRQs.
         *   - Calls rom_handover_jump.S: scrambles unlocked SRAM, clears GPRs,
         *     jumps to 0x4000.
         *
         * The mutable blob writes TEST_PASS_SIGNATURE to KMCSR → test passes.
         * This dispatch never returns.
         */
        TEST_SUBTEST_START("Phase 1: CMD_SRAM_EXEC dispatches to mutable firmware");
        {
            uint8_t seq = 0;
            rom_km_msg_header_t hdr;
            hdr.seq_num = seq;
            hdr.id = ROM_KM_CMD_SRAM_EXEC;
            hdr.payload_len = 0;
            hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

            /* Write the single-word (with sep) frame to the inbound FIFO. */
            if (!tb_sep_mbox_write_separator_write(1, 5000))
                TEST_FAIL("Phase 1: separator write failed");
            if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("Phase 1: header write failed");

            /* Let the ISR drain the 1-word frame into rom_rx_msgbuf. */
            test_delay(1000);
            rom_isr_mailbox();

            /* Arm the TB's autonomous outbound drainer so the SEP-side reads
             * the RESP_CMD the handover sends.  rom_handover_finish() spins
             * until the outbound FIFO is empty before flushing it, and this
             * CPU cannot drain it itself once inside the handover. */
            if (!tb_sep_mbox_drain_enable(1, 5000))
                TEST_FAIL("Phase 1: failed to arm outbound drainer");

            /* Dispatch — never returns on success. */
            rom_msg_rx_process();

            /* Should never reach here. */
            TEST_FAIL("Phase 1: CMD_SRAM_EXEC should have jumped to 0x4000");
        }
    }

    return 0;
}
