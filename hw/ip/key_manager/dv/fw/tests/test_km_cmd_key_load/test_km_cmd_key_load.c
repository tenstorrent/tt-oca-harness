/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_key_load.c
 * @brief CMD_KEY_LOAD happy-path test
 *
 * Covers:
 *   - Load a 4-word key (KEY_SIZE=3, DEST_VALID=AES=0x04), verify RESP_CMD
 *     success, non-zero handle, echoed REQ_SIZE and DEST_VALID.
 *   - CMD_KEY_TRANSFER of the loaded handle to AES succeeds.
 *   - CMD_KEY_REVOKE of the loaded handle succeeds; subsequent
 *     CMD_KEY_TRANSFER returns FAILURE.
 *   - Sweep KEY_SIZE in {0,1,3,15} — each load succeeds and the resulting
 *     handle is usable for CMD_KEY_TRANSFER.
 *   - After the 4-word load, verify KPV_CTRL for the allocated slot has
 *     lock_write=1, dest_valid matching request, extend and last_dword correct.
 *   - Sweep DEST_VALID in {0x01,0x02,0x04,0x08,0x0F} — each load succeeds and
 *     CMD_KEY_TRANSFER to each set bit succeeds; unset bits fail.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_key_load
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
 * Send CMD_KEY_LOAD and return the allocated handle on success.
 * Asserts RC_SUCCESS and echoed fields.
 */
static uint8_t do_key_load(uint8_t key_size_field, uint8_t dest_valid) {
    /* key_size_field = KEY_SIZE payload word (= number of key words - 1) */
    uint8_t num_key_words = (uint8_t)(key_size_field + 1u);
    uint8_t payload_len = (uint8_t)(num_key_words + 2u); /* +2 for KEY_SIZE+DEST_VALID */

    uint32_t payload[130]; /* max possible: 128 key words + 2 */
    payload[0] = (uint32_t)key_size_field;
    payload[1] = (uint32_t)dest_valid;
    for (uint8_t i = 0; i < num_key_words; i++) payload[2u + i] = 0xA5000000u | (uint32_t)i;

    send_cmd_with_payload(ROM_KM_CMD_KEY_LOAD, payload, payload_len);
    process_and_drain();

    rom_km_msg_header_t rhdr;
    uint32_t seq_e, cmd_e, arg;
    int8_t rc;
    read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

    TEST_ASSERT_EQ(seq_e & 0xFFu, (uint32_t)cmd_seq, "key_load seq echo");
    TEST_ASSERT_EQ(cmd_e & 0xFFu, (uint32_t)ROM_KM_CMD_KEY_LOAD, "key_load cmd echo");
    TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "key_load success");
    TEST_ASSERT_EQ(rhdr.payload_len, 4u, "key_load has return_arg");

    rom_km_key_generate_ret_t ret = {.raw = arg};
    TEST_ASSERT_NE(ret.key_handle, 0u, "key_load handle non-zero");
    TEST_ASSERT_EQ(ret.req_size, (uint32_t)key_size_field, "key_load REQ_SIZE echo");
    TEST_ASSERT_EQ(ret.dest_valid, (uint32_t)dest_valid, "key_load DEST_VALID echo");

    cmd_seq++;
    return ret.key_handle;
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(4000000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xC826u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

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

    /*=================================================================
     * Load a 4-word key (KEY_SIZE=3, AES)
     *=================================================================*/
    uint8_t handle_a;

    TEST_SUBTEST_START("CMD_KEY_LOAD 4-word key AES");
    {
        handle_a = do_key_load(3u, (rom_km_dest_bits_t){.aes = 1}.raw);
        TEST_LOG("  loaded handle=%u", handle_a);
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Verify KPV CTRL and registry fields for the 4-word loaded key
     *
     * For KEY_SIZE=3 (key_size=4 words), num_slots=1:
     *   extend    = 0  (only 1 slot)
     *   last_dword = (4-1) % 16 = 3
     *   lock_write = 1
     * dest_valid is tracked in the software key registry, not KPV CTRL.
     *=================================================================*/
    TEST_SUBTEST_START("KPV CTRL and registry fields correct after key_load");
    {
        uint8_t base_slot;
        if (rom_keyreg_get_slot(&rom_keyreg_state, handle_a, &base_slot) < 0)
            TEST_FAIL("rom_keyreg_get_slot failed for handle %u", handle_a);

        km_kpv__ctrl_reg_t ctrl;
        rom_km_dest_bits_t dest_valid;
        ctrl.w = KPV_CTRL(base_slot).w;

        TEST_ASSERT_EQ((uint32_t)ctrl.f.lock_write, 1u, "slot lock_write=1");
        TEST_ASSERT_EQ(rom_keyreg_get_dest_valid(&rom_keyreg_state, handle_a, &dest_valid), 0u,
                       "registry destination lookup");
        TEST_ASSERT_EQ((uint32_t)dest_valid.raw, (uint32_t)(rom_km_dest_bits_t){.aes = 1}.raw,
                       "registry dest_valid=AES");
        TEST_ASSERT_EQ((uint32_t)ctrl.f.extend, 0u, "extend=0 (1 slot)");
        TEST_ASSERT_EQ((uint32_t)ctrl.f.last_dword, 3u, "last_dword=(4-1)%%16=3");

        TEST_LOG("  base_slot=%u ctrl.w=0x%08X", base_slot, ctrl.w);
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * CMD_KEY_TRANSFER of loaded handle to AES
     *=================================================================*/
    TEST_SUBTEST_START("CMD_KEY_TRANSFER of loaded key");
    {
        uint32_t payload[2] = {(uint32_t)handle_a, (rom_km_dest_bits_t){.aes = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFFu, (uint32_t)cmd_seq, "xfer seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFFu, (uint32_t)ROM_KM_CMD_KEY_TRANSFER, "xfer cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "xfer success");
        TEST_LOG("  transfer of loaded key succeeded");
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * CMD_KEY_REVOKE the loaded handle
     *=================================================================*/
    TEST_SUBTEST_START("CMD_KEY_REVOKE of loaded key");
    {
        uint32_t payload[1] = {(uint32_t)handle_a};
        send_cmd_with_payload(ROM_KM_CMD_KEY_REVOKE, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "revoke success");
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CMD_KEY_TRANSFER after revoke → FAILURE");
    {
        uint32_t payload[2] = {(uint32_t)handle_a, (rom_km_dest_bits_t){.aes = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "xfer after revoke → FAILURE");
        TEST_LOG("  transfer of revoked handle correctly rejected");
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Sweep KEY_SIZE values 0, 1, 3, 15
     * Each load must succeed; result handle is usable for CMD_KEY_TRANSFER.
     *=================================================================*/
    TEST_SUBTEST_START("KEY_SIZE sweep (0,1,3,15)");
    {
        static const uint8_t key_sizes[] = {0u, 1u, 3u, 15u};
        uint8_t dest = (rom_km_dest_bits_t){.hmac_sha2 = 1}.raw;

        for (uint8_t i = 0u; i < 4u; i++) {
            uint8_t ks = key_sizes[i];
            uint8_t hdl = do_key_load(ks, dest);

            /* Verify handle is usable via CMD_KEY_TRANSFER (integrity check). */
            uint32_t xfer_payload[2] = {(uint32_t)hdl, (uint32_t)dest};
            send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, xfer_payload, 2);
            process_and_drain();

            rom_km_msg_header_t rhdr;
            uint32_t seq_e, cmd_e, arg;
            int8_t xrc;
            read_resp_cmd(&rhdr, &seq_e, &cmd_e, &xrc, &arg);
            TEST_ASSERT_EQ(xrc, (int8_t)ROM_KM_RC_SUCCESS, "xfer of loaded key OK");
            TEST_LOG("  KEY_SIZE=%u handle=%u transfer OK", (unsigned)ks, hdl);
            cmd_seq++;
        }
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Sweep DEST_VALID bits {0x01,0x02,0x04,0x08,0x0F}
     * For each value: load a key, then transfer to each set bit (expect
     * success) and to each unset bit (expect FAILURE).
     *=================================================================*/
    TEST_SUBTEST_START("DEST_VALID bit sweep");
    {
        static const uint8_t dest_masks[] = {0x01u, 0x02u, 0x04u, 0x08u, 0x0Fu};

        for (uint8_t m = 0u; m < 5u; m++) {
            uint8_t dv = dest_masks[m];
            uint8_t hdl = do_key_load(3u, dv); /* 4-word key */

            /* Transfer to each bit individually */
            for (uint8_t bit = 0u; bit < 4u; bit++) {
                uint8_t engine = (uint8_t)(1u << bit);
                uint32_t xfer_payload[2] = {(uint32_t)hdl, (uint32_t)engine};
                send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, xfer_payload, 2);
                process_and_drain();

                rom_km_msg_header_t rhdr;
                uint32_t seq_e, cmd_e, arg;
                int8_t xrc;
                read_resp_cmd(&rhdr, &seq_e, &cmd_e, &xrc, &arg);

                if (dv & engine) {
                    TEST_ASSERT_EQ(xrc, (int8_t)ROM_KM_RC_SUCCESS, "permitted engine → SUCCESS");
                } else {
                    TEST_ASSERT_EQ(xrc, (int8_t)ROM_KM_RC_FAILURE, "forbidden engine → FAILURE");
                }
                TEST_LOG("  DEST=0x%02X engine bit%u: %s", (unsigned)dv, (unsigned)bit,
                         (dv & engine) ? "SUCCESS" : "FAILURE");
                cmd_seq++;
            }

            TEST_LOG("  DEST=0x%02X handle=%u bit-sweep OK", (unsigned)dv, hdl);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
