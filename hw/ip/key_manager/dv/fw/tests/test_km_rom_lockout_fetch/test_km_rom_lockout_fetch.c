/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_rom_lockout_fetch.c
 * @brief ROM lockout: mutable firmware cannot jump back into the ROM.
 *
 * This is the code-reuse case the lockout exists to stop.  Unlike a blocked
 * data read, a blocked fetch is fatal: the zeros returned in place of ROM
 * content decode as an illegal instruction, and because handover has masked
 * every interrupt the core takes the trap state directly rather than vectoring.
 * The KM halts and unrecoverable_err asserts.
 *
 * No fault code reaches the SEP, because the ISR that would send one is in the
 * ROM that has just been revoked.  The test asserts exactly that: a restart on
 * unrecoverable_err with no captured fault code.  Expect the testbench to log a
 * "RESP_UNRECOVERABLE_FAULT not observed" warning; that absence is the point.
 * The -18 decode itself is covered by test_km_unrec_hw_rom_access.
 *
 * Phase 0 (cold boot, sram_fw_size == 0): copy mutable_fw_blob_rom_fetch to the
 * SRAM base, record sram_fw_size, warm reset.
 *
 * Phase 1 (warm reset, sram_fw_size != 0): arm the unrecoverable watcher, then
 * send CMD_SRAM_EXEC.  The blob jumps to the ROM reset vector and the KM halts.
 *
 * Phase 2 (after the testbench reset): report the result.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_rom_lockout_fetch
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

    if (tb_check_unrecoverable_restart(1000)) {
        uint32_t fault_code;
        if (!tb_get_unrecoverable_fault_code(1000, &fault_code)) {
            TEST_FAIL("Failed to query the unrecoverable fault code");
        }
        if (fault_code != 0u) {
            TEST_FAIL("Unexpected fault code 0x%08X: the ROM ISR must be unreachable "
                      "once the lockout has engaged",
                      (unsigned)fault_code);
        }
        TEST_PASS();
        return 0;
    }

    rom_boot_init();

    uint32_t fw_size = rom_persist_get_sram_fw_size();

    if (fw_size == 0u) {
        if (!tb_set_timeout(2000000)) TEST_FAIL("timeout set failed");
        if (!tb_drbg_set_seed(0xE050u, 5000)) TEST_FAIL("drbg set seed failed");

        TEST_SUBTEST_START("Phase 0: copy ROM-jumping blob to SRAM base");
        {
            void *sram_base = (void *)SRAM_BASE;
            memcpy(sram_base, mutable_fw_blob_rom_fetch, MUTABLE_FW_BLOB_ROM_FETCH_WORDS * 4u);
            __asm__ volatile("fence" ::: "memory");

            volatile uint32_t *sram_ptr = (volatile uint32_t *)SRAM_BASE;
            if (*sram_ptr != mutable_fw_blob_rom_fetch[0]) {
                TEST_FAIL("Phase 0: blob readback mismatch at the SRAM base "
                          "(got 0x%08X, expected 0x%08X)",
                          (unsigned)*sram_ptr, (unsigned)mutable_fw_blob_rom_fetch[0]);
            }
        }
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: set sram_fw_size in rom_persist");
        {
            uint32_t size_bytes = MUTABLE_FW_BLOB_ROM_FETCH_WORDS * 4u;
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
        if (!tb_drbg_set_seed(0xE051u, 5000)) TEST_FAIL("Phase 1: drbg set seed failed");

        {
            uint32_t ready;
            if (!tb_sep_mbox_read(&ready, 5000))
                TEST_FAIL("Phase 1: No RESP_KM_READY after warm reset");
        }

        /* Armed here rather than in phase 0 so that the warm reset above is not
         * mistaken for the fault we are looking for. */
        if (!tb_set_unrecoverable_watch(1, 1000u)) {
            TEST_FAIL("Phase 1: failed to arm the unrecoverable watcher");
        }

        TEST_SUBTEST_START("Phase 1: hand over to the ROM-jumping blob");
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

            /* Never returns; the blob halts the KM on the blocked ROM fetch. */
            rom_msg_rx_process();

            TEST_FAIL("Phase 1: CMD_SRAM_EXEC should have jumped to the SRAM base");
        }
    }

    return 0;
}
