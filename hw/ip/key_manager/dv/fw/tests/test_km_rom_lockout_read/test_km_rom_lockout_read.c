/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_rom_lockout_read.c
 * @brief ROM lockout: mutable firmware cannot read the ROM as data.
 *
 * Blocking data reads is what stops a mutable image extracting ROM constants,
 * so it is verified from the far side of a real handover rather than from ROM
 * itself.  A blocked read returns zero instead of trapping, which is exactly
 * what makes it observable: the blob survives to report what it read.
 *
 * Phase 0 (cold boot, sram_fw_size == 0):
 *   1. Read the ROM word the blob will later read, and require it to be
 *      non-zero.  Without this the blob's comparison would also be satisfied by
 *      a ROM that happens to contain zero there.
 *   2. Copy mutable_fw_blob_rom_read to the SRAM base and record sram_fw_size.
 *   3. Warm reset, so the blob and sram_fw_size survive into phase 1.
 *
 * Phase 1 (warm reset, sram_fw_size != 0):
 *   1. Send CMD_SRAM_EXEC, which write-locks the image region, masks all IRQs
 *      and jumps to 0x8000, engaging the ROM lockout on that fetch.
 *   2. The blob reads the ROM and writes TEST_RESULT from the comparison, so a
 *      still-readable ROM reports failure rather than hanging.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_rom_lockout_read
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"
#include "rom_boot.h"
#include "rom_persist.h"
#include "test_mutable_fw_blob.h"

/* The word the blob loads.  The IRQ vector at 0x10 is in physical ROM in every
 * link mode, so it holds real code with valid parity; most of the ROM is
 * uninitialized in the default execute-from-VROM build. */
#define ROM_LIVE_WORD_ADDR (ROM_KM_ROM_BASE + 0x10u)

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

int main(void) {
    TEST_INIT();

    rom_boot_init();

    uint32_t fw_size = rom_persist_get_sram_fw_size();

    if (fw_size == 0u) {
        if (!tb_set_timeout(2000000)) TEST_FAIL("timeout set failed");
        if (!tb_drbg_set_seed(0xE040u, 5000)) TEST_FAIL("drbg set seed failed");

        TEST_SUBTEST_START("Phase 0: ROM is readable before handover");
        {
            volatile uint32_t *rom_word = (volatile uint32_t *)(uintptr_t)ROM_LIVE_WORD_ADDR;
            if (*rom_word == 0u) {
                TEST_FAIL("Phase 0: ROM word at 0x%08X reads zero while ROM is live",
                          (unsigned)ROM_LIVE_WORD_ADDR);
            }
        }
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: copy ROM-reading blob to SRAM base");
        {
            void *sram_base = (void *)SRAM_BASE;
            memcpy(sram_base, mutable_fw_blob_rom_read, MUTABLE_FW_BLOB_ROM_READ_WORDS * 4u);
            __asm__ volatile("fence" ::: "memory");

            volatile uint32_t *sram_ptr = (volatile uint32_t *)SRAM_BASE;
            if (*sram_ptr != mutable_fw_blob_rom_read[0]) {
                TEST_FAIL("Phase 0: blob readback mismatch at the SRAM base "
                          "(got 0x%08X, expected 0x%08X)",
                          (unsigned)*sram_ptr, (unsigned)mutable_fw_blob_rom_read[0]);
            }
        }
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: set sram_fw_size in rom_persist");
        {
            uint32_t size_bytes = MUTABLE_FW_BLOB_ROM_READ_WORDS * 4u;
            rom_persist_set_sram_fw_size(size_bytes);
            __asm__ volatile("fence" ::: "memory");

            if (rom_persist_get_sram_fw_size() != size_bytes) {
                TEST_FAIL("Phase 0: sram_fw_size readback mismatch");
            }
        }
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: trigger warm reset");
        {
            if (!tb_km_warm_reset(5000u)) TEST_FAIL("TB_CMD_KM_WARM_RESET not acknowledged");
            TEST_FAIL("execution continued after warm reset");
        }

    } else {
        if (!tb_set_timeout(2000000)) TEST_FAIL("Phase 1: timeout set failed");
        if (!tb_drbg_set_seed(0xE041u, 5000)) TEST_FAIL("Phase 1: drbg set seed failed");

        {
            uint32_t ready;
            if (!tb_sep_mbox_read(&ready, 5000))
                TEST_FAIL("Phase 1: No RESP_KM_READY after warm reset");
        }

        TEST_SUBTEST_START("Phase 1: hand over to the ROM-reading blob");
        {
            rom_km_msg_header_t hdr;
            hdr.seq_num = 0;
            hdr.id = ROM_KM_CMD_SRAM_EXEC;
            hdr.payload_len = 0;
            hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

            if (!tb_sep_mbox_write_separator_write(1, 5000))
                TEST_FAIL("Phase 1: separator write failed");
            if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("Phase 1: header write failed");

            test_delay(1000);
            rom_isr_mailbox();

            if (!tb_sep_mbox_drain_enable(1, 5000))
                TEST_FAIL("Phase 1: failed to arm outbound drainer");

            /* Never returns; the blob reports the result. */
            rom_msg_rx_process();

            TEST_FAIL("Phase 1: CMD_SRAM_EXEC should have jumped to the SRAM base");
        }
    }

    return 0;
}
