/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_key_load_err.c
 * @brief CMD_KEY_LOAD argument-error path test
 *
 * Covers every documented rejection path:
 *   - KEY_SIZE reserved bit [7] set            → invalid_arg, arg=0
 *   - Payload-length/KEY_SIZE mismatch         → invalid_arg, arg=0
 *   - DEST_VALID reserved bits [31:8] set      → invalid_arg, arg=1
 *   - DEST_VALID == 0                          → invalid_arg, arg=1
 *   - DEST_VALID[31:8] != 0 (bit 8)            → invalid_arg, arg=1
 *   - KPV full (no eligible slots)             → failure, no arg
 *   - Handle-pool exhausted                    → failure, no arg, no KPV mutation
 *
 * After every rejection the KPV CTRL snapshot is compared to confirm no
 * slot was mutated.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_key_load_err
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"
#include "rom_boot.h"
#include "rom_kpv.h"
#include "rom_keyreg.h"
#include "rom_state.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

/*===========================================================================
 * Helpers
 *===========================================================================*/

static uint8_t cmd_seq;

static void send_cmd_with_payload(uint8_t cmd_id, const uint32_t *payload, uint8_t payload_len) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq;
    hdr.id = cmd_id;
    hdr.payload_len = payload_len;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");

    for (uint8_t i = 0; i < payload_len; i++) {
        if (!tb_sep_mbox_write(payload[i], 5000)) TEST_FAIL("payload write %u failed", (unsigned)i);
    }

    uint32_t crc = rom_crc32c((const uint8_t *)payload, (uint32_t)payload_len * 4u);
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(crc, 5000)) TEST_FAIL("CRC write failed");
}

static void process_and_drain(void) {
    test_delay(1000);
    rom_msg_rx_process();
    rom_isr_mailbox();
}

static void read_resp_cmd(rom_km_msg_header_t *rhdr, uint32_t *seq_echo, uint32_t *cmd_echo,
                          int8_t *rc, uint32_t *arg) {
    uint32_t payload_words[4] = {0};
    uint32_t word;
    if (!tb_sep_mbox_read(&word, 5000)) TEST_FAIL("Failed to read response header");
    rhdr->raw = word;

    uint8_t exp_crc = rom_crc8_rohc((const uint8_t *)&word, 3);
    TEST_ASSERT_EQ(rhdr->header_crc8, exp_crc, "resp header CRC");
    TEST_ASSERT_EQ(rhdr->id, (uint32_t)ROM_KM_RESP_CMD, "resp ID");

    if (!tb_sep_mbox_read(seq_echo, 5000)) TEST_FAIL("Failed to read seq echo");
    payload_words[0] = *seq_echo;
    if (!tb_sep_mbox_read(cmd_echo, 5000)) TEST_FAIL("Failed to read cmd echo");
    payload_words[1] = *cmd_echo;

    uint32_t rc_word;
    if (!tb_sep_mbox_read(&rc_word, 5000)) TEST_FAIL("Failed to read return code");
    *rc = (int8_t)(rc_word & 0xFFu);
    payload_words[2] = rc_word;

    if (rhdr->payload_len >= 4u) {
        if (!tb_sep_mbox_read(arg, 5000)) TEST_FAIL("Failed to read return arg");
        payload_words[3] = *arg;
    } else {
        *arg = 0;
    }

    uint32_t crc_word;
    if (!tb_sep_mbox_read(&crc_word, 5000)) TEST_FAIL("Failed to read payload CRC");
    TEST_ASSERT(rhdr->payload_len == 3u || rhdr->payload_len == 4u, "resp payload_len=%u",
                (unsigned)rhdr->payload_len);
    TEST_ASSERT_EQ(crc_word,
                   rom_crc32c((const uint8_t *)payload_words, (uint32_t)rhdr->payload_len * 4u),
                   "resp payload CRC");
}

/**
 * Snapshot all 32 KPV_CTRL registers.
 * Used to confirm no slot was mutated after a rejected command.
 */
static void snapshot_kpv_ctrl(uint32_t out[ROM_KM_KPV_NUM_SLOTS]) {
    for (uint8_t s = 0u; s < ROM_KM_KPV_NUM_SLOTS; s++) {
        km_kpv__ctrl_reg_t ctrl;
        ctrl.w = KPV_CTRL(s).w;
        out[s] = ctrl.w;
    }
}

/** Assert two snapshots match. */
static void assert_kpv_unchanged(const uint32_t before[ROM_KM_KPV_NUM_SLOTS],
                                 const uint32_t after[ROM_KM_KPV_NUM_SLOTS]) {
    for (uint8_t s = 0u; s < ROM_KM_KPV_NUM_SLOTS; s++) {
        if (before[s] != after[s])
            TEST_FAIL("KPV slot %u changed: 0x%08X → 0x%08X", (unsigned)s, (unsigned)before[s],
                      (unsigned)after[s]);
    }
}

/**
 * Issue a CMD_KEY_LOAD and return rc and arg.
 * Asserts seq/cmd echoes.
 */
static void do_key_load_raw(const uint32_t *payload, uint8_t payload_len, int8_t *rc_out,
                            uint32_t *arg_out) {
    send_cmd_with_payload(ROM_KM_CMD_KEY_LOAD, payload, payload_len);
    process_and_drain();

    rom_km_msg_header_t rhdr;
    uint32_t seq_e, cmd_e;
    read_resp_cmd(&rhdr, &seq_e, &cmd_e, rc_out, arg_out);
    TEST_ASSERT_EQ(seq_e & 0xFFu, (uint32_t)cmd_seq, "seq echo");
    TEST_ASSERT_EQ(cmd_e & 0xFFu, (uint32_t)ROM_KM_CMD_KEY_LOAD, "cmd echo");
    cmd_seq++;
}

/**
 * Issue CMD_KEY_GENERATE for a 1-word key (KEY_SIZE=0) to AES.
 * Returns the allocated handle. Used to fill KPV slots.
 */
static uint8_t fill_one_kpv_slot(void) {
    /* CMD_KEY_GENERATE: word0=REQ_SIZE=0 (1 word), word1=dest=AES */
    uint32_t payload[2] = {0u, (rom_km_dest_bits_t){.aes = 1}.raw};
    send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, payload, 2u);
    process_and_drain();

    rom_km_msg_header_t rhdr;
    uint32_t seq_e, cmd_e, arg;
    int8_t rc;
    read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);
    cmd_seq++;

    if (rc != (int8_t)ROM_KM_RC_SUCCESS) return 0u; /* KPV or handles full */

    rom_km_key_generate_ret_t ret = {.raw = arg};
    return ret.key_handle;
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(3000000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xE826u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

    rom_boot_init();

    /* Discard RESP_KM_READY */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY");
        rom_km_msg_header_t rdy;
        rdy.raw = ready;
        TEST_ASSERT_EQ(rdy.id, (uint32_t)ROM_KM_RESP_KM_READY, "boot response id");
    }

    cmd_seq = 0;

    uint32_t snap_before[ROM_KM_KPV_NUM_SLOTS];
    uint32_t snap_after[ROM_KM_KPV_NUM_SLOTS];

    /*=================================================================
     * KEY_SIZE reserved bit [7] set → invalid_arg, arg=0
     *=================================================================*/
    TEST_SUBTEST_START("KEY_SIZE rsvd bit → invalid_arg");
    {
        uint32_t payload[3] = {0x00000080u, /* KEY_SIZE with bit 7 set (reserved) */
                               (rom_km_dest_bits_t){.aes = 1}.raw, 0xDEADBEEFu};
        snapshot_kpv_ctrl(snap_before);
        int8_t rc;
        uint32_t arg;
        do_key_load_raw(payload, 3u, &rc, &arg);
        snapshot_kpv_ctrl(snap_after);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "rsvd KEY_SIZE → invalid_arg");
        TEST_ASSERT_EQ(arg & 0xFFu, 0u, "return arg = word 0 (KEY_SIZE)");
        assert_kpv_unchanged(snap_before, snap_after);
        TEST_LOG("  KEY_SIZE rsvd-bit rejected correctly");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * payload_len inconsistent with KEY_SIZE
     * KEY_SIZE=3 declares 4 key words → expected payload_len=6.
     * Send only 5 words → mismatch.
     *=================================================================*/
    TEST_SUBTEST_START("payload_len/KEY_SIZE mismatch → invalid_arg");
    {
        uint32_t payload[5] = {
            3u, /* KEY_SIZE=3: expects payload_len=3+3=6 */
            (rom_km_dest_bits_t){.aes = 1}.raw, 0x11u, 0x22u,
            0x33u /* only 3 KEY_DATA words; should be 4 */
        };
        snapshot_kpv_ctrl(snap_before);
        int8_t rc;
        uint32_t arg;
        do_key_load_raw(payload, 5u, &rc, &arg); /* 5 != 6 */
        snapshot_kpv_ctrl(snap_after);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "len mismatch → invalid_arg");
        TEST_ASSERT_EQ(arg & 0xFFu, 0u, "return arg = word 0 (KEY_SIZE)");
        assert_kpv_unchanged(snap_before, snap_after);
        TEST_LOG("  payload_len mismatch rejected correctly");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * DEST_VALID reserved bits [31:8] set → invalid_arg, arg=1
     *=================================================================*/
    TEST_SUBTEST_START("DEST_VALID rsvd[31:8] → invalid_arg");
    {
        uint32_t payload[6] = {3u,          /* KEY_SIZE=3 */
                               0x00000100u, /* DEST_VALID: bit 8 set (reserved[31:8]) */
                               0x11u,       0x22u, 0x33u, 0x44u};
        snapshot_kpv_ctrl(snap_before);
        int8_t rc;
        uint32_t arg;
        do_key_load_raw(payload, 6u, &rc, &arg);
        snapshot_kpv_ctrl(snap_after);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "DEST rsvd[31:8] → invalid_arg");
        TEST_ASSERT_EQ(arg & 0xFFu, 1u, "return arg = word 1 (DEST_VALID)");
        assert_kpv_unchanged(snap_before, snap_after);
        TEST_LOG("  DEST_VALID rsvd[31:8] rejected correctly");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * DEST_VALID == 0 → invalid_arg, arg=1
     *=================================================================*/
    TEST_SUBTEST_START("DEST_VALID=0 → invalid_arg");
    {
        uint32_t payload[6] = {3u,    0u, /* DEST_VALID=0 → zero destinations */
                               0x11u, 0x22u, 0x33u, 0x44u};
        snapshot_kpv_ctrl(snap_before);
        int8_t rc;
        uint32_t arg;
        do_key_load_raw(payload, 6u, &rc, &arg);
        snapshot_kpv_ctrl(snap_after);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "DEST=0 → invalid_arg");
        TEST_ASSERT_EQ(arg & 0xFFu, 1u, "return arg = word 1 (DEST_VALID)");
        assert_kpv_unchanged(snap_before, snap_after);
        TEST_LOG("  DEST_VALID=0 rejected correctly");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * DEST_VALID[31:8] != 0 → invalid_arg, arg=1
     * (Bits 4-7 are now valid for ABR seeds; bit 8 and above remain reserved.)
     *=================================================================*/
    TEST_SUBTEST_START("DEST_VALID rsvd[31:8] set (bit 8) → invalid_arg");
    {
        uint32_t payload[6] = {3u,    0x00000100u, /* DEST_VALID: bit 8 set (truly reserved) */
                               0x11u, 0x22u,       0x33u, 0x44u};
        snapshot_kpv_ctrl(snap_before);
        int8_t rc;
        uint32_t arg;
        do_key_load_raw(payload, 6u, &rc, &arg);
        snapshot_kpv_ctrl(snap_after);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "DEST rsvd[31:8] → invalid_arg");
        TEST_ASSERT_EQ(arg & 0xFFu, 1u, "return arg = word 1 (DEST_VALID)");
        assert_kpv_unchanged(snap_before, snap_after);
        TEST_LOG("  DEST_VALID rsvd[31:8] rejected correctly");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * KPV slot-fit failure → failure, no arg
     *
     * Fill all 32 KPV slots with 1-word keys (KEY_SIZE=0 via CMD_KEY_GENERATE,
     * 1 slot each), then attempt CMD_KEY_LOAD.  The load must fail because
     * no consecutive slots remain.  KPV must be unchanged after rejection.
     *=================================================================*/
    TEST_SUBTEST_START("KPV full → failure");
    {
        /* Fill KPV: 32 slots × 1-word-key = 32 CMD_KEY_GENERATE calls. */
        uint8_t filled = 0u;
        for (uint8_t i = 0u; i < ROM_KM_KPV_NUM_SLOTS; i++) {
            uint8_t h = fill_one_kpv_slot();
            if (h != 0u) {
                filled++;
            } else {
                break; /* slots or handles exhausted */
            }
        }
        TEST_LOG("  filled %u KPV slots", (unsigned)filled);

        /* Attempt a 1-word CMD_KEY_LOAD — no eligible slot should be available. */
        uint32_t payload[3] = {0u, /* KEY_SIZE=0 → 1 word */
                               (rom_km_dest_bits_t){.aes = 1}.raw, 0xCAFEu};
        snapshot_kpv_ctrl(snap_before);
        int8_t rc;
        uint32_t arg;
        do_key_load_raw(payload, 3u, &rc, &arg);
        snapshot_kpv_ctrl(snap_after);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "KPV full → failure");
        assert_kpv_unchanged(snap_before, snap_after);
        TEST_LOG("  KPV-full rejection correct, no KPV mutation");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Handle-pool exhaustion → failure, no arg, no KPV mutation
     *
     * Directly set rom_keyreg_state.next_handle = 0 to simulate wrap-around
     * (handle pool exhausted). Some KPV slots are free at this point (after
     * the KPV-full test revokes are not done, but the pre-check must catch
     * it before any slot is consumed).
     *
     * Use a fresh boot-state approach: reset next_handle to 0 and confirm
     * CMD_KEY_LOAD detects exhaustion before mutating KPV.
     *=================================================================*/
    TEST_SUBTEST_START("handle exhaustion (next_handle=0) → failure, no KPV mutation");
    {
        /* Save the current next_handle and force it to 0 to simulate exhaustion.
         * next_handle == 0 is the sentinel used by rom_keyreg_generate to signal
         * exhaustion (wrap from 255 to 0 after 255 allocations). */
        uint8_t saved_next_handle = rom_keyreg_state.next_handle;
        rom_keyreg_state.next_handle = 0u;

        /* With KPV full from the previous test, there are no free slots either.
         * Reset rom_keyreg_state slot map for at least 1 slot to make the slot-fit
         * succeed so we can verify the handle pre-check fires BEFORE KPV mutation.
         *
         * Alternative: just verify the handle pre-check fires.  Since all KPV
         * slots are filled, find_consecutive_slots() will fail first.  To test
         * the handle-exhaustion path specifically, revoke one key to free a slot. */

        /* Restore next_handle so we can do a revoke (revoke doesn't touch next_handle). */
        rom_keyreg_state.next_handle = saved_next_handle;

        /* Revoke handle 1 to free its KPV slot (if it was generated). */
        if (saved_next_handle > 1u) {
            uint32_t rev_payload[1] = {1u};
            send_cmd_with_payload(ROM_KM_CMD_KEY_REVOKE, rev_payload, 1u);
            process_and_drain();

            rom_km_msg_header_t rhdr;
            uint32_t seq_e, cmd_e, arg;
            int8_t rc;
            read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);
            cmd_seq++;
            /* Revoke may fail if handle 1 is already freed - that is OK. */
        }

        /* Now force next_handle = 0 so handle pre-check fires. */
        rom_keyreg_state.next_handle = 0u;

        snapshot_kpv_ctrl(snap_before);

        /* Send a valid-format CMD_KEY_LOAD - should fail at handle pre-check. */
        uint32_t payload[3] = {0u, (rom_km_dest_bits_t){.aes = 1}.raw, 0xFEu};
        int8_t rc;
        uint32_t arg;
        do_key_load_raw(payload, 3u, &rc, &arg);
        snapshot_kpv_ctrl(snap_after);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "handle exhaustion → failure");
        assert_kpv_unchanged(snap_before, snap_after);
        TEST_LOG("  handle exhaustion: no KPV mutation confirmed");

        /* Restore next_handle to a sane value before test ends. */
        rom_keyreg_state.next_handle = saved_next_handle;
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
