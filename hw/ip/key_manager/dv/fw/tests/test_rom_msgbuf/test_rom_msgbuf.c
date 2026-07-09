/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_msgbuf.c
 * @brief T021 - Circular message buffer unit test (single-frame)
 *
 * Exercises rom_msgbuf: write/peek/pop, single-frame semantics, full/flush,
 * partial detection, wrap-around, frame_slots_available, and reject when
 * frame already present.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_msgbuf
 */

#include "test_common.h"
#include "rom_msgbuf.h"

static rom_km_msgbuf_t buf;

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(300000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    /* 1. Write single word and pop back */
    TEST_SUBTEST_START("Write single word, pop back");
    rom_msgbuf_init(&buf);
    {
        int rc = rom_msgbuf_write_word(&buf, 0xDEADBEEFu, 1);
        if (rc != 0) {
            TEST_FAIL("write_word returned %d", rc);
        }
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "frame_available");
        uint32_t word;
        rc = rom_msgbuf_peek_word(&buf, &word);
        if (rc != 0) {
            TEST_FAIL("peek_word returned %d", rc);
        }
        TEST_ASSERT_EQ(word, 0xDEADBEEFu, "peek value");
        rc = rom_msgbuf_pop_word(&buf, &word);
        if (rc != 0) {
            TEST_FAIL("pop_word returned %d", rc);
        }
        TEST_ASSERT_EQ(word, 0xDEADBEEFu, "readback value");
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "frame still requires consume");
        TEST_ASSERT_EQ(buf.tail, 1u, "tail advanced after pop");
        rom_msgbuf_consume_frame(&buf);
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 0u, "frame consumed");
    }
    TEST_SUBTEST_PASS();

    /* 2. Write multi-word frame */
    TEST_SUBTEST_START("Write multi-word frame (3 words)");
    rom_msgbuf_init(&buf);
    {
        rom_msgbuf_write_word(&buf, 0x11111111u, 0);
        rom_msgbuf_write_word(&buf, 0x22222222u, 0);
        rom_msgbuf_write_word(&buf, 0x33333333u, 1);
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "frame_available");

        uint16_t start, length;
        int rc = rom_msgbuf_peek_frame(&buf, &start, &length);
        if (rc != 0) {
            TEST_FAIL("peek_frame returned %d", rc);
        }
        TEST_ASSERT_EQ(length, 3u, "frame length");

        uint32_t w;
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0x11111111u, "word 0");
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0x22222222u, "word 1");
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0x33333333u, "word 2");
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "frame remains until consume");
        rom_msgbuf_consume_frame(&buf);
    }
    TEST_SUBTEST_PASS();

    /* 3. Single-frame: consume first frame then write second */
    TEST_SUBTEST_START("Two frames in sequence (consume then write)");
    rom_msgbuf_init(&buf);
    {
        rom_msgbuf_write_word(&buf, 0xAAAAAAAAu, 0);
        rom_msgbuf_write_word(&buf, 0xBBBBBBBBu, 1);
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "frame_available");

        uint32_t w;
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xAAAAAAAAu, "frame 0 word 0");
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xBBBBBBBBu, "frame 0 word 1");

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "frame remains after final pop");
        rom_msgbuf_consume_frame(&buf);
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 0u, "no frame after consume");

        rom_msgbuf_write_word(&buf, 0xCCCCCCCCu, 0);
        rom_msgbuf_write_word(&buf, 0xDDDDDDDDu, 1);
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "frame_available");

        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xCCCCCCCCu, "frame 1 word 0");
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xDDDDDDDDu, "frame 1 word 1");
        rom_msgbuf_consume_frame(&buf);
    }
    TEST_SUBTEST_PASS();

    /* 4. Buffer full */
    TEST_SUBTEST_START("Buffer full");
    rom_msgbuf_init(&buf);
    {
        uint16_t i;
        int rc;
        for (i = 0; i < ROM_KM_MSGBUF_SIZE - 1; i++) {
            rc = rom_msgbuf_write_word(&buf, 0x12340000u | i, 0);
            if (rc != 0) {
                TEST_FAIL("write_word[%u] returned %d before full", (unsigned)i, rc);
            }
        }
        rc = rom_msgbuf_write_word(&buf, 0xFFFFFFFFu, 1);
        if (rc != 0) {
            TEST_FAIL("write_word (last) returned %d", rc);
        }
        TEST_ASSERT_EQ(rom_msgbuf_is_full(&buf), 1u, "is_full");

        rc = rom_msgbuf_write_word(&buf, 0x99999999u, 0);
        if (rc != -1) {
            TEST_FAIL("write_word when full should return -1, got %d", rc);
        }
    }
    TEST_SUBTEST_PASS();

    /* 5. Flush */
    TEST_SUBTEST_START("Flush");
    rom_msgbuf_init(&buf);
    {
        rom_msgbuf_write_word(&buf, 0x11u, 1);
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "pre-flush one frame");

        rom_msgbuf_flush(&buf);
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 0u, "post-flush frames");
        TEST_ASSERT_EQ(buf.count, 0u, "post-flush count");
        TEST_ASSERT_EQ(buf.tail, 0u, "post-flush tail");
    }
    TEST_SUBTEST_PASS();

    /* 6. has_only_partial */
    TEST_SUBTEST_START("has_only_partial");
    rom_msgbuf_init(&buf);
    {
        uint16_t i;
        for (i = 0; i < ROM_KM_MSGBUF_SIZE; i++) {
            int rc = rom_msgbuf_write_word(&buf, i, 0);
            if (rc != 0) {
                TEST_FAIL("write_word[%u] returned %d filling partial", (unsigned)i, rc);
            }
        }
        TEST_ASSERT_EQ(rom_msgbuf_is_full(&buf), 1u, "is_full for partial");
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 0u, "no complete frames");
        TEST_ASSERT_EQ(rom_msgbuf_has_only_partial(&buf), 1u, "has_only_partial");
    }
    TEST_SUBTEST_PASS();

    /* 7. frame_slots_available (single frame: 0 or 1 slot) */
    TEST_SUBTEST_START("frame_slots_available");
    rom_msgbuf_init(&buf);
    {
        TEST_ASSERT_EQ(rom_msgbuf_can_accept_frame(&buf), 1u, "slots when empty");

        int rc = rom_msgbuf_write_word(&buf, 0u, 1);
        if (rc != 0) {
            TEST_FAIL("write_word frame returned %d", rc);
        }
        TEST_ASSERT_EQ(rom_msgbuf_can_accept_frame(&buf), 0u, "slots when frame present");
    }
    TEST_SUBTEST_PASS();

    /* 8. Reject second frame when one already present */
    TEST_SUBTEST_START("Reject write when frame present");
    rom_msgbuf_init(&buf);
    {
        int rc = rom_msgbuf_write_word(&buf, 0x11u, 1);
        if (rc != 0) {
            TEST_FAIL("write_word first frame failed");
        }
        rc = rom_msgbuf_write_word(&buf, 0x99u, 1);
        if (rc != -1) {
            TEST_FAIL("write_word (second frame) should return -1, got %d", rc);
        }
    }
    TEST_SUBTEST_PASS();

    /* 9. pop_word partial descriptor update (peek reflects remaining slice) */
    TEST_SUBTEST_START("pop_word partial descriptor update");
    rom_msgbuf_init(&buf);
    {
        rom_msgbuf_write_word(&buf, 0xA1u, 0);
        rom_msgbuf_write_word(&buf, 0xA2u, 0);
        rom_msgbuf_write_word(&buf, 0xA3u, 0);
        rom_msgbuf_write_word(&buf, 0xA4u, 0);
        rom_msgbuf_write_word(&buf, 0xA5u, 1);
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "one frame");

        uint16_t start0, len0;
        int rc = rom_msgbuf_peek_frame(&buf, &start0, &len0);
        if (rc != 0) TEST_FAIL("peek_frame failed");
        TEST_ASSERT_EQ(len0, 5u, "initial frame length");

        uint32_t w;
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xA1u, "partial read word 0");
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xA2u, "partial read word 1");

        uint16_t start1, len1;
        rc = rom_msgbuf_peek_frame(&buf, &start1, &len1);
        if (rc != 0) TEST_FAIL("peek after partial read failed");
        TEST_ASSERT_EQ(len1, 3u, "remaining frame length after 2 reads");

        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xA3u, "remaining word 0");
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xA4u, "remaining word 1");
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xA5u, "remaining word 2 (last)");

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "frame remains after last pop");
        TEST_ASSERT_EQ(buf.tail, 5u, "tail reaches frame length");
        TEST_ASSERT_EQ(rom_msgbuf_peek_word(&buf, &w), -1, "peek past end fails");
        rom_msgbuf_consume_frame(&buf);
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 0u, "frame consumed after explicit drop");
    }
    TEST_SUBTEST_PASS();

    /* 10. peek_word is non-destructive */
    TEST_SUBTEST_START("peek_word is non-destructive");
    rom_msgbuf_init(&buf);
    {
        uint32_t w = 0u;

        rom_msgbuf_write_word(&buf, 0x11111111u, 0);
        rom_msgbuf_write_word(&buf, 0x22222222u, 0);
        rom_msgbuf_write_word(&buf, 0x33333333u, 1);

        TEST_ASSERT_EQ(rom_msgbuf_peek_word(&buf, &w), 0, "first peek succeeds");
        TEST_ASSERT_EQ(w, 0x11111111u, "first peek sees word 0");
        TEST_ASSERT_EQ(buf.tail, 0u, "peek does not advance tail");

        TEST_ASSERT_EQ(rom_msgbuf_peek_word(&buf, &w), 0, "second peek succeeds");
        TEST_ASSERT_EQ(w, 0x11111111u, "second peek still sees word 0");
        TEST_ASSERT_EQ(buf.tail, 0u, "repeated peek still does not advance tail");

        TEST_ASSERT_EQ(rom_msgbuf_pop_word(&buf, &w), 0, "pop after peek succeeds");
        TEST_ASSERT_EQ(w, 0x11111111u, "pop returns word 0");
        TEST_ASSERT_EQ(buf.tail, 1u, "pop advances tail");

        TEST_ASSERT_EQ(rom_msgbuf_peek_word(&buf, &w), 0, "peek after pop succeeds");
        TEST_ASSERT_EQ(w, 0x22222222u, "peek follows advanced tail");
        TEST_ASSERT_EQ(buf.tail, 1u, "peek after pop does not advance tail");
        rom_msgbuf_consume_frame(&buf);
    }
    TEST_SUBTEST_PASS();

    /* 11. consume_frame resets partially popped frames */
    TEST_SUBTEST_START("consume_frame resets partially popped frame");
    rom_msgbuf_init(&buf);
    {
        uint32_t w = 0u;
        uint16_t start = 0u;
        uint16_t length = 0u;

        rom_msgbuf_write_word(&buf, 0xABC00001u, 0);
        rom_msgbuf_write_word(&buf, 0xABC00002u, 0);
        rom_msgbuf_write_word(&buf, 0xABC00003u, 1);

        TEST_ASSERT_EQ(rom_msgbuf_pop_word(&buf, &w), 0, "partial pop succeeds");
        TEST_ASSERT_EQ(w, 0xABC00001u, "partial pop returns first word");
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "frame still available");
        TEST_ASSERT_EQ(rom_msgbuf_frame_empty(&buf), 0u, "frame not empty before final pop");
        TEST_ASSERT_EQ(rom_msgbuf_peek_frame(&buf, &start, &length), 0, "peek frame succeeds");
        TEST_ASSERT_EQ(start, 1u, "start follows partial pop");
        TEST_ASSERT_EQ(length, 2u, "remaining words tracked after partial pop");

        rom_msgbuf_consume_frame(&buf);

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 0u, "frame removed");
        TEST_ASSERT_EQ(rom_msgbuf_frame_empty(&buf), 0u, "no empty frame remains");
        TEST_ASSERT_EQ(buf.count, 0u, "count reset");
        TEST_ASSERT_EQ(buf.tail, 0u, "tail reset");
        TEST_ASSERT_EQ(buf.frame_len, 0u, "frame_len reset");
        TEST_ASSERT_EQ(rom_msgbuf_can_accept_frame(&buf), 1u, "new frame can be accepted");
        TEST_ASSERT_EQ(rom_msgbuf_peek_word(&buf, &w), -1, "peek fails after consume");
    }
    TEST_SUBTEST_PASS();

    /* 12. peek_word fails on empty and exhausted frames */
    TEST_SUBTEST_START("peek_word fails on empty and exhausted frames");
    rom_msgbuf_init(&buf);
    {
        uint32_t w = 0u;

        TEST_ASSERT_EQ(rom_msgbuf_peek_word(&buf, &w), -1, "peek fails on empty buffer");

        rom_msgbuf_write_word(&buf, 0x55555555u, 1);
        TEST_ASSERT_EQ(rom_msgbuf_pop_word(&buf, &w), 0, "pop single-word frame");
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "exhausted frame still present");
        TEST_ASSERT_EQ(rom_msgbuf_frame_empty(&buf), 1u, "frame_empty after final pop");
        TEST_ASSERT_EQ(rom_msgbuf_peek_word(&buf, &w), -1, "peek fails on exhausted frame");
        rom_msgbuf_consume_frame(&buf);
    }
    TEST_SUBTEST_PASS();

    /* 13. Wrap-around */
    TEST_SUBTEST_START("Wrap-around");
    rom_msgbuf_init(&buf);
    {
        uint16_t i;
        uint32_t w;
        for (i = 0; i < ROM_KM_MSGBUF_SIZE - 2; i++) {
            rom_msgbuf_write_word(&buf, 0xAA000000u | i, 0);
        }
        rom_msgbuf_write_word(&buf, 0xAA00FFFFu, 1);
        rom_msgbuf_consume_frame(&buf);

        rom_msgbuf_write_word(&buf, 0xBB000001u, 0);
        rom_msgbuf_write_word(&buf, 0xBB000002u, 0);
        rom_msgbuf_write_word(&buf, 0xBB000003u, 1);

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&buf), 1u, "wrap frame_available");
        uint16_t start, length;
        rom_msgbuf_peek_frame(&buf, &start, &length);
        TEST_ASSERT_EQ(length, 3u, "wrap frame length");

        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xBB000001u, "wrap word 0");
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xBB000002u, "wrap word 1");
        rom_msgbuf_pop_word(&buf, &w);
        TEST_ASSERT_EQ(w, 0xBB000003u, "wrap word 2");
        rom_msgbuf_consume_frame(&buf);
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
