/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_key_load_recov.c
 * @brief CMD_KEY_LOAD rejection during recoverable fault state
 *
 * Covers:
 *   - While RECOVERABLE_ERR is set, CMD_KEY_LOAD is rejected with RESP_CMD
 *     failure and no KPV mutation, identically to CMD_KEY_GENERATE and other
 *     key-management commands.
 *   - After CMD_RECOV_ACK, the same CMD_KEY_LOAD payload succeeds and returns
 *     a valid handle.
 *   - Code path: the rejection occurs via the recoverable-fault allow-list
 *     filter in rom_msg_rx_process before the handler runs, not via a partial
 *     argument-validation path.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_key_load_recov
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

static void send_header_only(uint8_t cmd_id) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq;
    hdr.id = cmd_id;
    hdr.payload_len = 0;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");
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

static void drain_fault_response(void) {
    test_delay(500);

    uint32_t fault_hdr;
    if (!tb_sep_mbox_read(&fault_hdr, 5000)) TEST_FAIL("No RESP_RECOVERABLE_FAULT in outbound");

    rom_km_msg_header_t fh;
    fh.raw = fault_hdr;
    TEST_ASSERT_EQ(fh.id, ROM_KM_RESP_RECOVERABLE_FAULT, "got fault response");

    if (fh.payload_len > 0u) {
        uint32_t fpl, fcrc;
        tb_sep_mbox_read(&fpl, 5000);
        tb_sep_mbox_read(&fcrc, 5000);
    }
}

/**
 * Snapshot all 32 KPV_CTRL registers.
 */
static void snapshot_kpv_ctrl(uint32_t out[ROM_KM_KPV_NUM_SLOTS]) {
    for (uint8_t s = 0u; s < ROM_KM_KPV_NUM_SLOTS; s++) {
        km_kpv__ctrl_reg_t ctrl;
        ctrl.w = KPV_CTRL(s).w;
        out[s] = ctrl.w;
    }
}

static void assert_kpv_unchanged(const uint32_t before[ROM_KM_KPV_NUM_SLOTS],
                                 const uint32_t after[ROM_KM_KPV_NUM_SLOTS]) {
    for (uint8_t s = 0u; s < ROM_KM_KPV_NUM_SLOTS; s++) {
        if (before[s] != after[s])
            TEST_FAIL("KPV slot %u changed: 0x%08X → 0x%08X", (unsigned)s, (unsigned)before[s],
                      (unsigned)after[s]);
    }
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(1500000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xF826u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

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

    /* The CMD_KEY_LOAD payload used for both the fault-state and post-ACK tests. */
    static const uint32_t key_load_payload[6] = {3u,           /* KEY_SIZE=3 → 4 key words */
                                                 (uint32_t)4u, /* DEST_VALID: AES=bit2=0x04 */
                                                 0xDEAD0001u,  0xDEAD0002u,
                                                 0xDEAD0003u,  0xDEAD0004u};

    uint32_t snap_before[ROM_KM_KPV_NUM_SLOTS];
    uint32_t snap_after[ROM_KM_KPV_NUM_SLOTS];

    /*=================================================================
     * Trigger a recoverable fault
     *=================================================================*/
    TEST_SUBTEST_START("Trigger recoverable fault");
    {
        rom_trigger_recoverable(ROM_KM_RFAULT_KEY_SLOT_CRC);
        drain_fault_response();
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Verify RECOVERABLE_ERR is set (via CMD_STAT)
     *=================================================================*/
    TEST_SUBTEST_START("CMD_STAT shows RECOVERABLE_ERR=1");
    {
        send_header_only(ROM_KM_CMD_STAT);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "CMD_STAT success");
        rom_km_stat_ret_t stat_ret = {.raw = arg};
        TEST_ASSERT_EQ(stat_ret.recoverable_err, 1u, "RECOVERABLE_ERR=1");
        TEST_LOG("  RECOVERABLE_ERR confirmed set");
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * CMD_KEY_LOAD while RECOVERABLE_ERR=1
     * Must return FAILURE, no return arg, no KPV mutation.
     *
     * Code path: the FAILURE comes from the allow-list filter in
     * rom_msg_rx_process, not from the command handler.  We verify
     * this indirectly: even an otherwise-valid payload returns FAILURE
     * with payload_len=3 (no return_arg), which matches the allow-list
     * filter's behavior (identical to CMD_KEY_GENERATE rejection pattern).
     *=================================================================*/
    TEST_SUBTEST_START("CMD_KEY_LOAD rejected during RECOVERABLE_ERR");
    {
        snapshot_kpv_ctrl(snap_before);
        send_cmd_with_payload(ROM_KM_CMD_KEY_LOAD, key_load_payload, 6u);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);
        snapshot_kpv_ctrl(snap_after);

        TEST_ASSERT_EQ(seq_e & 0xFFu, (uint32_t)cmd_seq, "fault-state seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFFu, (uint32_t)ROM_KM_CMD_KEY_LOAD, "fault-state cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "CMD_KEY_LOAD → FAILURE during fault");
        /* Allow-list filter returns payload_len=3 (no return arg). */
        TEST_ASSERT_EQ(rhdr.payload_len, 3u, "no return arg (allow-list filter path)");
        assert_kpv_unchanged(snap_before, snap_after);

        TEST_LOG("  CMD_KEY_LOAD rejected (FAILURE, no arg, no KPV mutation)");
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Clear the fault via CMD_RECOV_ACK
     *=================================================================*/
    TEST_SUBTEST_START("CMD_RECOV_ACK clears fault");
    {
        send_header_only(ROM_KM_CMD_RECOV_ACK);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "CMD_RECOV_ACK success");
        TEST_LOG("  recoverable fault cleared");
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * After CMD_RECOV_ACK, same CMD_KEY_LOAD payload must succeed and
     * return a non-zero handle.
     *=================================================================*/
    TEST_SUBTEST_START("CMD_KEY_LOAD succeeds after CMD_RECOV_ACK");
    {
        send_cmd_with_payload(ROM_KM_CMD_KEY_LOAD, key_load_payload, 6u);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFFu, (uint32_t)cmd_seq, "post-ack seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFFu, (uint32_t)ROM_KM_CMD_KEY_LOAD, "post-ack cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "CMD_KEY_LOAD succeeds after ACK");
        TEST_ASSERT_EQ(rhdr.payload_len, 4u, "has return arg");

        rom_km_key_generate_ret_t ret = {.raw = arg};
        TEST_ASSERT_NE(ret.key_handle, 0u, "handle non-zero after ACK");
        TEST_ASSERT_EQ(ret.req_size, 3u, "REQ_SIZE echoed correctly");
        TEST_ASSERT_EQ(ret.dest_valid, 4u, "DEST_VALID echoed correctly (AES)");

        TEST_LOG("  CMD_KEY_LOAD succeeded after fault cleared, handle=%u", ret.key_handle);
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
