/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * CPU SRAM-AES-SRAM integration test.
 *
 * The real SEP CPU provisions a known AES-128 key through production Key
 * Manager mailbox commands, selects the AES sideload key, and copies a
 * runtime-sized payload from one SEP SRAM region to another through AES.
 *
 * AES has no completion interrupt in the SEP integration, so the test uses
 * bounded OUTPUT_VALID polling and claims no IRQ coverage.
 */

#include <stdint.h>
#include <stdio.h>

#include "aes_test_util.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_aes_init.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define FW_READY_MAGIC 0xA1E50565u
#define CONFIG_TIMEOUT 2000000u
#define KM_TIMEOUT 2000000u
#define MAX_PAYLOAD_BLOCKS 4096u

#define OP_ENCRYPT 1u
#define OP_DECRYPT 2u
#define OP_BOTH 3u

#define KM_CMD_KEY_TRANSFER 0x24u
#define KM_CMD_ENGINE_SHRED 0x25u
#define KM_CMD_KEY_LOAD 0x26u
#define KM_RESP_CMD 0x00u
#define KM_RESP_READY 0x55u
#define KM_DEST_AES 0x04u

#define KM_STATUS_IN_FULL KM_MAILBOX_SEP__STATUS_REG__INBOUND_FULL_bm
#define KM_STATUS_OUT_EMPTY KM_MAILBOX_SEP__STATUS_REG__OUTBOUND_EMPTY_bm
#define KM_STATUS_OUT_SEP KM_MAILBOX_SEP__STATUS_REG__OUTBOUND_SEPARATOR_bm

/*
 * Leave room for immediate guard words at the maximum payload size. The
 * destination sits at +0x20010 rather than +0x20000 so a 64-KiB source payload
 * and its trailing guard cannot overlap it.
 */
#define SRAM_SRC_BASE (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x00010000u)
#define SRAM_DST_BASE (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x00020010u)
#define SRC_GUARD_BEFORE 0x51A0B001u
#define SRC_GUARD_AFTER 0x51A0A001u
#define DST_GUARD_BEFORE 0xD57AB001u
#define DST_GUARD_AFTER 0xD57AA001u
#define DST_SENTINEL 0xDEADBEEFu

static const uint32_t aes_key[4] = {0x16157e2b, 0xa6d2ae28, 0x8815f7ab, 0x3c4fcf09};

static const uint32_t plaintext[4][4] = {{0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373},
                                         {0x578a2dae, 0x9cac031e, 0xac6fb79e, 0x518eaf45},
                                         {0x461cc830, 0x11e45ca3, 0x19c1fbe5, 0xef520a1a},
                                         {0x45249ff6, 0x179b4fdf, 0x7b412bad, 0x10376ce6}};

static const uint32_t ciphertext[4][4] = {{0xb47bd73a, 0x60367a0d, 0xf3ca9ea8, 0x97ef6624},
                                          {0x85d5d3f5, 0x9d69b903, 0x5a8985e7, 0xafbafd96},
                                          {0x7fcdb143, 0x23ce8e59, 0xe3001b88, 0x880603ed},
                                          {0x5e780c7b, 0x3fade827, 0x71202382, 0xd45d7204}};

static uint8_t km_cmd_seq;
static uint8_t km_resp_seq;
static uint8_t negative_disable_sideload;
static uint8_t vector_start;

static uint8_t crc8_rohc_bytes(const uint8_t *data, uint32_t len) {
    uint8_t crc = 0xffu;

    for (uint32_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint32_t bit = 0; bit < 8; bit++)
            crc = (crc & 1u) ? (uint8_t)((crc >> 1) ^ 0xe0u) : (uint8_t)(crc >> 1);
    }
    return crc;
}

static uint32_t crc32c_words(const uint32_t *words, uint32_t count) {
    uint32_t crc = 0xffffffffu;

    for (uint32_t i = 0; i < count; i++) {
        uint32_t word = words[i];
        for (uint32_t byte = 0; byte < 4; byte++) {
            crc ^= (word >> (byte * 8u)) & 0xffu;
            for (uint32_t bit = 0; bit < 8; bit++)
                crc = (crc & 1u) ? (crc >> 1) ^ 0x82f63b78u : crc >> 1;
        }
    }
    return crc ^ 0xffffffffu;
}

static uint32_t km_header(uint8_t seq, uint8_t id, uint8_t payload_len) {
    uint8_t bytes[3] = {seq, id, payload_len};
    uint32_t crc = crc8_rohc_bytes(bytes, 3);

    return (crc << 24) | ((uint32_t)payload_len << 16) | ((uint32_t)id << 8) | seq;
}

static int km_wait_inbound_space(void) {
    uint32_t timeout = KM_TIMEOUT;

    while (timeout-- != 0u) {
        if ((READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_STATUS_BASE_ADDR) & KM_STATUS_IN_FULL) == 0u)
            return 0;
    }
    return -1;
}

static int km_send_frame(uint8_t id, const uint32_t *payload, uint8_t payload_len) {
    uint32_t words[16];
    uint32_t total = 1u;

    if (payload_len > 12u) return -1;

    words[0] = km_header(km_cmd_seq, id, payload_len);
    for (uint32_t i = 0; i < payload_len; i++) words[total++] = payload[i];
    if (payload_len != 0u) words[total++] = crc32c_words(payload, payload_len);

    for (uint32_t i = 0; i < total; i++) {
        if (km_wait_inbound_space() != 0) return -1;
        if (i == total - 1u) WRITE_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_WRITE_SEPARATOR_BASE_ADDR, 1u);
        WRITE_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_WRITE_DATA_BASE_ADDR, words[i]);
    }
    km_cmd_seq++;
    return 0;
}

static int km_recv_frame(uint32_t *words, uint32_t capacity, uint32_t *count) {
    uint32_t timeout = KM_TIMEOUT;
    uint32_t n = 0u;

    while (timeout-- != 0u) {
        uint32_t status = READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_STATUS_BASE_ADDR);

        if ((status & KM_STATUS_OUT_EMPTY) != 0u) continue;
        if (n >= capacity) return -1;

        words[n++] = READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_READ_DATA_BASE_ADDR);
        status = READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_STATUS_BASE_ADDR);
        if ((status & KM_STATUS_OUT_SEP) != 0u) {
            *count = n;
            return 0;
        }
    }
    return -1;
}

static int km_validate_frame(const uint32_t *words, uint32_t count, uint8_t expected_id,
                             const uint32_t **payload, uint8_t *payload_len) {
    uint32_t header;
    uint8_t bytes[3];
    uint8_t len;

    if (count == 0u) return -1;

    header = words[0];
    bytes[0] = (uint8_t)header;
    bytes[1] = (uint8_t)(header >> 8);
    bytes[2] = (uint8_t)(header >> 16);
    len = bytes[2];

    if ((uint8_t)(header >> 24) != crc8_rohc_bytes(bytes, 3)) return -1;
    if (bytes[0] != km_resp_seq || bytes[1] != expected_id) return -1;
    if (count != 1u + len + ((len != 0u) ? 1u : 0u)) return -1;
    if (len != 0u && words[1u + len] != crc32c_words(&words[1], len)) return -1;

    km_resp_seq++;
    *payload = &words[1];
    *payload_len = len;
    return 0;
}

static int km_wait_ready(void) {
    uint32_t words[8];
    uint32_t count;
    const uint32_t *payload;
    uint8_t payload_len;

    if (km_recv_frame(words, 8, &count) != 0) return -1;
    if (km_validate_frame(words, count, KM_RESP_READY, &payload, &payload_len) != 0) return -1;
    return (payload_len == 0u) ? 0 : -1;
}

static int km_command(uint8_t id, const uint32_t *payload, uint8_t payload_len,
                      uint32_t *return_arg) {
    uint32_t words[12];
    uint32_t count;
    const uint32_t *response;
    uint8_t response_len;
    uint8_t sent_seq = km_cmd_seq;

    if (km_send_frame(id, payload, payload_len) != 0) return -1;
    if (km_recv_frame(words, 12, &count) != 0) return -1;
    if (km_validate_frame(words, count, KM_RESP_CMD, &response, &response_len) != 0) return -1;
    if (response_len < 3u || (uint8_t)response[0] != sent_seq || (uint8_t)response[1] != id ||
        (int8_t)response[2] != 0)
        return -1;

    *return_arg = (response_len >= 4u) ? response[3] : 0u;
    return 0;
}

static int release_km_reset(void) {
    uint32_t reset_n = READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);

    reset_n |= SEP_RESET_CTRL__SW_RESET_N__KM_SW_RST_N_bm;
    WRITE_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, reset_n);
    __asm__ volatile("fence" ::: "memory");
    return (READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR) &
            SEP_RESET_CTRL__SW_RESET_N__KM_SW_RST_N_bm)
               ? 0
               : -1;
}

static int provision_aes_key(uint8_t *handle) {
    uint32_t load_payload[6] = {3u, KM_DEST_AES, aes_key[0], aes_key[1], aes_key[2], aes_key[3]};
    uint32_t transfer_payload[2];
    uint32_t result;

    if (km_command(KM_CMD_KEY_LOAD, load_payload, 6, &result) != 0) return -1;

    *handle = (uint8_t)result;
    transfer_payload[0] = *handle;
    transfer_payload[1] = KM_DEST_AES;
    return km_command(KM_CMD_KEY_TRANSFER, transfer_payload, 2, &result);
}

static int configure_sideload_aes(uint32_t operation) {
    aes__CTRL_SHADOWED_t ctrl = {.w = 0};

    ctrl.f.OPERATION = operation;
    ctrl.f.MODE = 0x1u;
    ctrl.f.KEY_LEN = 0x1u;
    ctrl.f.SIDELOAD = negative_disable_sideload ? 0u : 1u;
    ctrl.f.MANUAL_OPERATION = 0u;
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
    if (negative_disable_sideload) {
        printf("EXPECTED NEGATIVE: AES sideload disabled; rejecting operation\n");
        return -1;
    }
    return wait_for_idle();
}

static int check_guards(volatile uint32_t *src, volatile uint32_t *dst, uint32_t words) {
    if (src[-1] != SRC_GUARD_BEFORE || src[words] != SRC_GUARD_AFTER) return -1;
    if (dst[-1] != DST_GUARD_BEFORE || dst[words] != DST_GUARD_AFTER) return -1;
    return 0;
}

static int prepare_sram(uint32_t operation, uint32_t blocks) {
    volatile uint32_t *src = (volatile uint32_t *)(uintptr_t)SRAM_SRC_BASE;
    volatile uint32_t *dst = (volatile uint32_t *)(uintptr_t)SRAM_DST_BASE;
    const uint32_t(*input)[4] = (operation == OP_ENCRYPT) ? plaintext : ciphertext;
    uint32_t words = blocks * 4u;

    src[-1] = SRC_GUARD_BEFORE;
    src[words] = SRC_GUARD_AFTER;
    dst[-1] = DST_GUARD_BEFORE;
    dst[words] = DST_GUARD_AFTER;

    for (uint32_t block = 0; block < blocks; block++) {
        for (uint32_t word = 0; word < 4; word++) {
            src[block * 4u + word] = input[(block + vector_start) & 3u][word];
            dst[block * 4u + word] = DST_SENTINEL;
        }
    }
    return check_guards(src, dst, words);
}

static int process_payload(uint32_t operation, uint32_t blocks) {
    volatile uint32_t *src = (volatile uint32_t *)(uintptr_t)SRAM_SRC_BASE;
    volatile uint32_t *dst = (volatile uint32_t *)(uintptr_t)SRAM_DST_BASE;
    uint32_t input[4];
    uint32_t output[4];

    if (configure_sideload_aes(operation) != 0) return -1;

    for (uint32_t block = 0; block < blocks; block++) {
        for (uint32_t word = 0; word < 4; word++) input[word] = src[block * 4u + word];

        if (wait_for_input_ready() != 0) return -1;
        write_data_in(input);
        if (wait_for_output_valid() != 0) return -1;

        aes__STATUS_t status = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.OUTPUT_LOST || status.f.STALL || check_no_alert("SRAM-AES") != 0) return -1;

        read_data_out(output);
        for (uint32_t word = 0; word < 4; word++) dst[block * 4u + word] = output[word];
    }
    return 0;
}

static int verify_sram(uint32_t operation, uint32_t blocks) {
    volatile uint32_t *src = (volatile uint32_t *)(uintptr_t)SRAM_SRC_BASE;
    volatile uint32_t *dst = (volatile uint32_t *)(uintptr_t)SRAM_DST_BASE;
    const uint32_t(*input)[4] = (operation == OP_ENCRYPT) ? plaintext : ciphertext;
    const uint32_t(*expected)[4] = (operation == OP_ENCRYPT) ? ciphertext : plaintext;
    uint32_t words = blocks * 4u;

    if (check_guards(src, dst, words) != 0) return -1;

    for (uint32_t block = 0; block < blocks; block++) {
        for (uint32_t word = 0; word < 4; word++) {
            uint32_t index = block * 4u + word;

            if (src[index] != input[(block + vector_start) & 3u][word]) return -1;
            if (dst[index] == DST_SENTINEL ||
                dst[index] != expected[(block + vector_start) & 3u][word])
                return -1;
        }
    }
    return 0;
}

static int run_direction(uint32_t operation, uint32_t blocks) {
    const char *name = (operation == OP_ENCRYPT) ? "encrypt" : "decrypt";

    printf("Running %s: %u blocks, SRAM 0x%08x -> AES -> SRAM 0x%08x\n", name, blocks,
           SRAM_SRC_BASE, SRAM_DST_BASE);
    if (prepare_sram(operation, blocks) != 0) return -1;
    if (process_payload(operation, blocks) != 0) return -1;
    if (verify_sram(operation, blocks) != 0) return -1;
    printf("%s SRAM-AES-SRAM pass\n", name);
    return 0;
}

static int get_config(uint32_t *operation, uint32_t *blocks) {
    uint32_t timeout = CONFIG_TIMEOUT;
    uint32_t config = 0u;

    WRITE_REG(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7), 0u);
    WRITE_REG(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6), FW_READY_MAGIC);
    while (timeout-- != 0u) {
        config = READ_REG(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7));
        if (config != 0u) break;
    }
    if (config == 0u) return -1;

    *operation = config & 0x3u;
    negative_disable_sideload = (uint8_t)((config >> 8) & 0x1u);
    vector_start = (uint8_t)((config >> 9) & 0x7fu);
    *blocks = (config >> 16) & 0xffffu;
    if (*operation < OP_ENCRYPT || *operation > OP_BOTH) return -1;
    if (*blocks == 0u) *blocks = 16u;
    if (*blocks > MAX_PAYLOAD_BLOCKS) *blocks = MAX_PAYLOAD_BLOCKS;
    return 0;
}

static void clear_and_shred_aes(void) {
    uint32_t payload = KM_DEST_AES;
    uint32_t result;

    cleanup_aes();
    if (km_command(KM_CMD_ENGINE_SHRED, &payload, 1, &result) != 0)
        printf("ERROR: KM AES engine shred failed\n");
}

int main(void) {
    uint32_t operation;
    uint32_t blocks;
    uint8_t key_handle;
    int rc = 0;

    sep_outbound_filter_init();
    printf("\n=== CPU SRAM-AES-SRAM integration test ===\n");

    if (get_config(&operation, &blocks) != 0) rc = -1;
    if (rc == 0 && sep_aes_sw_reset_release() != 0) rc = -1;
    if (rc == 0 && release_km_reset() != 0) rc = -1;
    if (rc == 0 && km_wait_ready() != 0) {
        printf("ERROR: KM RESP_KM_READY timeout or validation failure\n");
        rc = -1;
    }
    if (rc == 0 && provision_aes_key(&key_handle) != 0) {
        printf("ERROR: KM key load/transfer failed\n");
        rc = -1;
    }

    if (rc == 0) printf("KM provisioned AES key handle 0x%02x over private bus\n", key_handle);
    if (rc == 0 && (operation == OP_ENCRYPT || operation == OP_BOTH))
        rc = run_direction(OP_ENCRYPT, blocks);
    if (rc == 0 && (operation == OP_DECRYPT || operation == OP_BOTH))
        rc = run_direction(OP_DECRYPT, blocks);

    if (rc == 0) clear_and_shred_aes();

    if (rc == 0) {
        printf("=== CPU SRAM-AES-SRAM TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== CPU SRAM-AES-SRAM TEST FAILED ===\n");
        test_fail(1);
    }

    while (1) __asm__ volatile("wfi");
}
