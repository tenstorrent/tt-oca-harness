/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_drbg_tstrb_assembly.c
 * @brief DRBG Sampler partial-TSTRB byte-assembly test
 *
 * Exposes the RTL bug where the active DATA-read and prefetch FSMs discarded
 * partial-TSTRB beats instead of accumulating them into a 32-bit word.
 *
 * Pre-fix:  subtests "two-partials", "single-lane", "walking-lanes",
 *           "mixed-width", "prefetch-single-lane", "prefetch-two-partials",
 *           and "stbyteassembly-full-word" all fail at TEST_ASSERT_EQ because
 *           the RTL returns the next full-word beat instead of the assembled
 *           partial-beat value.
 * Post-fix: all subtests pass.
 *
 * Protocol:
 *   - Use TB_CMD_DRBG_SET_NEXT_VALUE to load the tdata for the next queued beat.
 *   - Use TB_CMD_DRBG_QUEUE_BEAT(tstrb) to enqueue that beat (value+tstrb pair).
 *   - Queue multiple beats before triggering the DATA read; the driver delivers
 *     them in order before resuming the default deterministic-random stream.
 *
 * Run with:
 *   make run_fw FW_TEST=test_drbg_tstrb_assembly
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#define DRBG_DATA_REG \
    (*(volatile km_drbg_sampler__data_reg_t *)KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR)
#define DRBG_CFG_REG \
    (*(volatile km_drbg_sampler__cfg_reg_t *)KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR)
#define DRBG_STATUS_REG \
    (*(volatile km_drbg_sampler__status_reg_t *)KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR)
#define DRBG_PREFETCH_DATA_REG \
    (*(volatile km_drbg_sampler__prefetch_data_reg_t *) \
         KEY_MANAGER_DRBG_SAMPLER_PREFETCH_DATA_BASE_ADDR)

#define PREFETCH_WAIT_MAX 5000u
#define SETTLE_CYCLES 16u

/* Queue one beat: set data then enqueue with given tstrb. */
static int queue_beat(uint32_t data, uint32_t tstrb_4b, uint32_t timeout) {
    if (!tb_drbg_set_next_value(data, timeout)) {
        return 0;
    }
    return tb_drbg_queue_beat(tstrb_4b, timeout);
}

/* Poll STATUS.PREFETCHED until set or timeout. */
static int wait_for_prefetched(void) {
    uint32_t i;
    for (i = 0; i < PREFETCH_WAIT_MAX; i++) {
        if (DRBG_STATUS_REG.f.prefetched != 0u) {
            return 1;
        }
    }
    return 0;
}

int main(void) {
    uint32_t read_val;
    uint32_t pf_val;

    TEST_INIT();

    /* Disable timeout so long queued sequences never time out. */
    DRBG_CFG_REG.w = 0;

    /*==========================================================================
     * Subtest 1: Active read - two non-overlapping TSTRB lanes
     * Beat 1: tdata=0xAABBCCDD, tstrb=0x3 -> packs bytes 0xDD,0xCC (lanes 0,1)
     * Beat 2: tdata=0xEEFF1122, tstrb=0xC -> packs bytes 0xFF,0xEE (lanes 2,3)
     * Expected assembled word: 0xEEFFCCDD
     * Fails on pre-fix RTL (returns the next default-random full-word beat).
     *==========================================================================*/
    TEST_SUBTEST_START("Active read - two non-overlapping partials");

    if (!queue_beat(0xAABBCCDDu, 0x3u, 1000u)) {
        TEST_FAIL("queue_beat 1 failed");
    }
    if (!queue_beat(0xEEFF1122u, 0xCu, 1000u)) {
        TEST_FAIL("queue_beat 2 failed");
    }

    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, 0xEEFFCCDDu, "assembled two-partial word");
    TEST_LOG("  DATA=0x%08X expected=0xEEFFCCDD", read_val);
    TEST_SUBTEST_PASS();

    /*==========================================================================
     * Subtest 2: Active read - single-lane-only stream (Policy B critical case)
     * Source always asserts tstrb=0x1 (only lane 0 valid per beat).
     * Policy A would deadlock until timeout; Policy B compaction produces a
     * full word from 4 successive single-lane beats.
     * Expected: bytes packed in arrival order -> 0xDDCCBBAA
     *==========================================================================*/
    TEST_SUBTEST_START("Active read - single-lane-only stream");

    if (!queue_beat(0x000000AAu, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 1 failed");
    }
    if (!queue_beat(0x000000BBu, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 2 failed");
    }
    if (!queue_beat(0x000000CCu, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 3 failed");
    }
    if (!queue_beat(0x000000DDu, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 4 failed");
    }

    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, 0xDDCCBBAAu, "single-lane-only assembled word");
    TEST_LOG("  DATA=0x%08X expected=0xDDCCBBAA", read_val);
    TEST_SUBTEST_PASS();

    /*==========================================================================
     * Subtest 3: Active read - four single-lane partials, each a different lane
     * Each beat contributes exactly one byte via its respective TSTRB lane.
     * Packer walks source lanes 0..3 in order; first valid bit wins each beat.
     * Expected: bytes packed in arrival order -> 0xDDCCBBAA
     *==========================================================================*/
    TEST_SUBTEST_START("Active read - four single-lane partials walking lanes");

    if (!queue_beat(0x000000AAu, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 1 failed");
    }
    if (!queue_beat(0x0000BB00u, 0x2u, 1000u)) {
        TEST_FAIL("queue_beat 2 failed");
    }
    if (!queue_beat(0x00CC0000u, 0x4u, 1000u)) {
        TEST_FAIL("queue_beat 3 failed");
    }
    if (!queue_beat(0xDD000000u, 0x8u, 1000u)) {
        TEST_FAIL("queue_beat 4 failed");
    }

    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, 0xDDCCBBAAu, "walking-lanes assembled word");
    TEST_LOG("  DATA=0x%08X expected=0xDDCCBBAA", read_val);
    TEST_SUBTEST_PASS();

    /*==========================================================================
     * Subtest 4: Active read - mixed-width compaction
     * Beat 1: tdata=0x44332211, tstrb=0x7 -> 3 valid bytes: 0x11,0x22,0x33
     * Beat 2: tdata=0xFFEEDDAA, tstrb=0x1 -> 1 valid byte: 0xAA
     * Expected: 0xAA332211
     *==========================================================================*/
    TEST_SUBTEST_START("Active read - mixed-width compaction");

    if (!queue_beat(0x44332211u, 0x7u, 1000u)) {
        TEST_FAIL("queue_beat 1 failed");
    }
    if (!queue_beat(0xFFEEDDAAu, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 2 failed");
    }

    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, 0xAA332211u, "mixed-width assembled word");
    TEST_LOG("  DATA=0x%08X expected=0xAA332211", read_val);
    TEST_SUBTEST_PASS();

    /*==========================================================================
     * Subtest 5: TSTRB=0xF in StByteAssembly fast-completes remaining lanes
     * Beat 1: tdata=0xAABBCCDD, tstrb=0x3 -> 2 bytes: 0xDD,0xCC -> bytes_collected=2
     * Beat 2: tdata=0xEEFF1122, tstrb=0xF -> 4 valid; only 2 needed; packer takes
     *         lanes 0,1 of beat 2 (0x22,0x11) -> word = 0x1122CCDD
     * This confirms that a full-word beat in StByteAssembly only fills remaining
     * lanes, not the already-collected ones.
     *==========================================================================*/
    TEST_SUBTEST_START("Full-word beat in StByteAssembly fills remaining lanes only");

    if (!queue_beat(0xAABBCCDDu, 0x3u, 1000u)) {
        TEST_FAIL("queue_beat 1 failed");
    }
    if (!queue_beat(0xEEFF1122u, 0xFu, 1000u)) {
        TEST_FAIL("queue_beat 2 failed");
    }

    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, 0x1122CCDDu, "partial+full assembled word");
    TEST_LOG("  DATA=0x%08X expected=0x1122CCDD", read_val);
    TEST_SUBTEST_PASS();

    /*==========================================================================
     * Subtest 6: COUNT_GOOD increments once per assembled word (not per beat)
     *==========================================================================*/
    TEST_SUBTEST_START("COUNT_GOOD increments once per assembled word");
    {
        uint32_t good_before = DRBG_STATUS_REG.f.count_good;

        /* Queue two partial beats that assemble into one word. */
        if (!queue_beat(0x11223344u, 0x3u, 1000u)) {
            TEST_FAIL("queue_beat 1 failed");
        }
        if (!queue_beat(0x55667788u, 0xCu, 1000u)) {
            TEST_FAIL("queue_beat 2 failed");
        }
        (void)DRBG_DATA_REG.f.data; /* consume */

        test_delay(SETTLE_CYCLES);
        if (DRBG_STATUS_REG.f.count_good != good_before + 1u) {
            TEST_FAIL("COUNT_GOOD did not increment exactly once");
        }
    }
    TEST_SUBTEST_PASS();

    /*==========================================================================
     * Subtest 7: COUNT_BAD does NOT increment for valid partial sequences
     *==========================================================================*/
    TEST_SUBTEST_START("COUNT_BAD unchanged after valid partial sequences");
    {
        uint32_t bad_before = DRBG_STATUS_REG.f.count_bad;

        if (!queue_beat(0xAAAAAAAAu, 0x3u, 1000u)) {
            TEST_FAIL("queue_beat 1 failed");
        }
        if (!queue_beat(0xBBBBBBBBu, 0xCu, 1000u)) {
            TEST_FAIL("queue_beat 2 failed");
        }
        (void)DRBG_DATA_REG.f.data;

        test_delay(SETTLE_CYCLES);
        if (DRBG_STATUS_REG.f.count_bad != bad_before) {
            TEST_FAIL("COUNT_BAD incremented on valid partial sequence");
        }
    }
    TEST_SUBTEST_PASS();

    /*==========================================================================
     * Subtest 8: Stream-error detection and state recovery
     *
     * (a) TVALID glitch (injected via TB command) causes STATUS.stream_err
     *     to be set and COUNT_BAD to increment.
     *
     * (b) After stream-error recovery, a fresh partial-byte assembly must
     *     produce the correct word.  This confirms that data_bytes_collected
     *     was properly reset on error and carries no stale state.
     *
     * Note: stream_err_pulse requires tvalid_q=1 AND tready_q=0 AND tvalid=0.
     * Because TREADY is always 1 in StRequest/StByteAssembly, stream errors
     * are only detectable when the sampler is idle (TREADY=0), which is
     * exactly the state during the glitch injection here.
     *==========================================================================*/
    TEST_SUBTEST_START("Stream-error detection and state recovery");
    {
        km_drbg_sampler__status_reg_t w1c = {0};
        uint32_t bad_before;

        w1c.f.stream_err = 1u;
        DRBG_STATUS_REG.w = w1c.w; /* clear any prior stream_err */
        bad_before = DRBG_STATUS_REG.f.count_bad;

        /* Arm one-shot TVALID glitch; the driver fires it while the sampler
         * is idle (TREADY=0), so tvalid drops while tready_q=0 → stream_err. */
        if (!tb_drbg_tvalid_glitch(1000u)) {
            TEST_FAIL("tvalid_glitch failed");
        }

        test_delay(SETTLE_CYCLES);

        if (DRBG_STATUS_REG.f.stream_err == 0u) TEST_FAIL("STATUS.STREAM_ERR not set after glitch");
        if (DRBG_STATUS_REG.f.count_bad <= bad_before)
            TEST_FAIL("COUNT_BAD not incremented after stream error");

        /* Clear error and resume the DRBG driver. */
        DRBG_STATUS_REG.w = w1c.w;
        if (!tb_drbg_start(1000u)) {
            TEST_FAIL("tb_drbg_start failed");
        }

        /* (b) Partial assembly after recovery must work correctly.
         *     Two non-overlapping partial beats → expected 0xEEFFCCDD.
         *     If data_bytes_collected carried stale state the result would
         *     be wrong (e.g. bytes packed at the wrong position). */
        if (!queue_beat(0xAABBCCDDu, 0x3u, 1000u)) {
            TEST_FAIL("queue_beat r1 failed");
        }
        if (!queue_beat(0xEEFF1122u, 0xCu, 1000u)) {
            TEST_FAIL("queue_beat r2 failed");
        }

        read_val = DRBG_DATA_REG.f.data;
        TEST_ASSERT_EQ(read_val, 0xEEFFCCDDu,
                       "partial assembly after stream-err recovery: no stale state");
        TEST_LOG("  DATA=0x%08X expected=0xEEFFCCDD", read_val);
    }
    TEST_SUBTEST_PASS();

    /*==========================================================================
     * Subtest 9: Prefetch - single-lane-only stream (Policy B critical case)
     * Enable prefetch, queue four tstrb=0x1 beats, wait for PREFETCHED,
     * read PREFETCH_DATA and DATA.  Expected: 0xD4C3B2A1.
     * Fails on pre-fix RTL (prefetch loads the next default full-word beat).
     *==========================================================================*/
    TEST_SUBTEST_START("Prefetch - single-lane-only stream");

    DRBG_CFG_REG.f.prefetch = 0u;
    test_delay(SETTLE_CYCLES);

    /* Queue the partial beats before enabling prefetch so they are waiting. */
    if (!queue_beat(0x000000A1u, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 1 failed");
    }
    if (!queue_beat(0x000000B2u, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 2 failed");
    }
    if (!queue_beat(0x000000C3u, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 3 failed");
    }
    if (!queue_beat(0x000000D4u, 0x1u, 1000u)) {
        TEST_FAIL("queue_beat 4 failed");
    }

    DRBG_CFG_REG.f.prefetch = 1u;

    if (!wait_for_prefetched()) {
        TEST_FAIL("PREFETCHED not set within timeout after single-lane stream");
    }

    pf_val = DRBG_PREFETCH_DATA_REG.f.data;
    TEST_ASSERT_EQ(pf_val, 0xD4C3B2A1u, "PREFETCH_DATA single-lane");
    TEST_LOG("  PREFETCH_DATA=0x%08X expected=0xD4C3B2A1", pf_val);

    /* Consume the prefetched word. */
    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, 0xD4C3B2A1u, "DATA matches prefetch single-lane");

    DRBG_CFG_REG.f.prefetch = 0u;
    test_delay(SETTLE_CYCLES);
    TEST_SUBTEST_PASS();

    /*==========================================================================
     * Subtest 10: Prefetch - two non-overlapping TSTRB partials
     * Beat 1: tdata=0xAABBCCDD, tstrb=0x3 -> 0xDD,0xCC (bytes_collected=2)
     * Beat 2: tdata=0xEEFF1122, tstrb=0xC -> 0xFF,0xEE (bytes_collected=4)
     * Expected PREFETCH_DATA: 0xEEFFCCDD
     * Fails on pre-fix RTL (prefetch discards partials, waits for full word).
     *==========================================================================*/
    TEST_SUBTEST_START("Prefetch - two non-overlapping partials");

    DRBG_CFG_REG.f.prefetch = 0u;
    test_delay(SETTLE_CYCLES);

    if (!queue_beat(0xAABBCCDDu, 0x3u, 1000u)) {
        TEST_FAIL("queue_beat 1 failed");
    }
    if (!queue_beat(0xEEFF1122u, 0xCu, 1000u)) {
        TEST_FAIL("queue_beat 2 failed");
    }

    DRBG_CFG_REG.f.prefetch = 1u;

    if (!wait_for_prefetched()) {
        TEST_FAIL("PREFETCHED not set within timeout after two non-overlapping partials");
    }

    pf_val = DRBG_PREFETCH_DATA_REG.f.data;
    TEST_ASSERT_EQ(pf_val, 0xEEFFCCDDu, "PREFETCH_DATA two-partial");
    TEST_LOG("  PREFETCH_DATA=0x%08X expected=0xEEFFCCDD", pf_val);

    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, 0xEEFFCCDDu, "DATA matches prefetch two-partial");

    DRBG_CFG_REG.f.prefetch = 0u;
    test_delay(SETTLE_CYCLES);
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
