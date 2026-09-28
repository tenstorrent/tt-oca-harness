/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES STATUS & Flow Control Test (STAT-001)
 *
 * Focus: STATUS transitions, STALL/OUTPUT_LOST behavior, and TRIGGER clear operations.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_aes_init.h"
#include "test_completion.h"

/* ------------------------------------------------------------------ */
/* Test Vectors (AES-128, NIST SP 800-38A)                             */
/* ------------------------------------------------------------------ */

static const uint32_t test_key[4] = {0x16157e2b, 0xa6d2ae28, 0x8815f7ab, 0x3c4fcf09};

static const uint32_t zero_iv[4] = {0x00000000, 0x00000000, 0x00000000, 0x00000000};

/* NIST F.1 ECB block #1 */
static const uint32_t pt0[4] = {0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373};
static const uint32_t ct0_exp[4] = {0xb47bd73a, 0x60367a0d, 0xf3ca9ea8, 0x97ef6624};

/* Distinct plaintext used for flow-control/error scenarios (no golden compare). */
static const uint32_t pt1[4] = {0x578a2dae, 0x9cac031e, 0xac6fb79e, 0x518eaf45};

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

static aes__STATUS_t get_status(void) {
    aes__STATUS_t s = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
    return s;
}

static void print_status(const char *tag) {
    aes__STATUS_t s = get_status();
    printf("%s: STATUS=0x%08x (idle=%u stall=%u output_lost=%u output_valid=%u input_ready=%u)\n",
           tag, s.w, s.f.IDLE, s.f.STALL, s.f.OUTPUT_LOST, s.f.OUTPUT_VALID, s.f.INPUT_READY);
}

static int wait_for_idle(int want_idle) {
    int timeout = 50000;
    while (timeout-- > 0) {
        aes__STATUS_t s = get_status();
        if ((int)s.f.IDLE == want_idle) return 0;
    }
    printf("ERROR: Timeout waiting for STATUS.IDLE=%d\n", want_idle);
    return -1;
}

static int wait_for_output_valid(int want_valid) {
    int timeout = 50000;
    while (timeout-- > 0) {
        aes__STATUS_t s = get_status();
        if ((int)s.f.OUTPUT_VALID == want_valid) return 0;
    }
    printf("ERROR: Timeout waiting for STATUS.OUTPUT_VALID=%d\n", want_valid);
    return -1;
}

static int wait_for_output_lost(int want_lost) {
    int timeout = 50000;
    while (timeout-- > 0) {
        aes__STATUS_t s = get_status();
        if ((int)s.f.OUTPUT_LOST == want_lost) return 0;
    }
    printf("ERROR: Timeout waiting for STATUS.OUTPUT_LOST=%d\n", want_lost);
    return -1;
}

static void write_data_in(const uint32_t in[4]) {
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_DATA_IN_BASE_ADDR(i), in[i]);
    }
}

static void read_data_out_word(int idx, uint32_t *out_word) {
    *out_word = READ_REG(SEP_TOP_AES_DATA_OUT_BASE_ADDR(idx));
}

static void read_data_out(uint32_t out[4]) {
    for (int i = 0; i < 4; i++) {
        out[i] = READ_REG(SEP_TOP_AES_DATA_OUT_BASE_ADDR(i));
    }
}

static void read_iv(uint32_t iv_out[4]) {
    for (int i = 0; i < 4; i++) {
        iv_out[i] = READ_REG(SEP_TOP_AES_IV_BASE_ADDR(i));
    }
}

static int wait_for_iv_not_equal(const uint32_t prev_iv[4]) {
    /* KEY_IV_DATA_IN_CLEAR may wipe IV to a non-zero pattern; require it to change. */
    for (int attempt = 0; attempt < 10; attempt++) {
        for (volatile int i = 0; i < 200; i++) {
            __asm__("nop");
        }

        uint32_t iv_out[4];
        read_iv(iv_out);
        if (iv_out[0] != prev_iv[0] || iv_out[1] != prev_iv[1] || iv_out[2] != prev_iv[2] ||
            iv_out[3] != prev_iv[3]) {
            return 0;
        }
    }

    uint32_t iv_out[4];
    read_iv(iv_out);
    printf("ERROR: IV was not wiped/changed by KEY_IV_DATA_IN_CLEAR (got %08x %08x %08x %08x)\n",
           iv_out[0], iv_out[1], iv_out[2], iv_out[3]);
    return -1;
}

static int compare_block(const uint32_t got[4], const uint32_t exp[4], const char *tag) {
    for (int i = 0; i < 4; i++) {
        if (got[i] != exp[i]) {
            printf("ERROR: %s mismatch at word %d: got=0x%08x exp=0x%08x\n", tag, i, got[i],
                   exp[i]);
            return -1;
        }
    }
    return 0;
}

static int check_alert_status(const char *tag) {
    uint32_t val = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR);
    if (val & (1u << 5)) {
        printf("ERROR: %s: ALERT_RECOV (STATUS=0x%08x)\n", tag, val);
        return -1;
    }
    if (val & (1u << 6)) {
        printf("ERROR: %s: ALERT_FATAL (STATUS=0x%08x)\n", tag, val);
        return -1;
    }
    return 0;
}

static void trigger_data_out_clear(void) {
    aes__TRIGGER_t t = {.w = 0};
    t.f.DATA_OUT_CLEAR = 1;
    WRITE_REG(SEP_TOP_AES_TRIGGER_BASE_ADDR, t.w);
}

static void trigger_key_iv_data_in_clear(void) {
    aes__TRIGGER_t t = {.w = 0};
    t.f.KEY_IV_DATA_IN_CLEAR = 1;
    WRITE_REG(SEP_TOP_AES_TRIGGER_BASE_ADDR, t.w);
}

static void trigger_start(void) {
    aes__TRIGGER_t t = {.w = 0};
    t.f.START = 1;
    WRITE_REG(SEP_TOP_AES_TRIGGER_BASE_ADDR, t.w);
}

static int configure_aes_ecb_enc_auto(void) {
    aes__CTRL_SHADOWED_t ctrl = {.w = 0};
    ctrl.f.OPERATION = 0x1; /* ENC */
    ctrl.f.MODE = 0x1;      /* ECB */
    ctrl.f.KEY_LEN = 0x1;   /* AES_128 */
    ctrl.f.SIDELOAD = 0x0;
    ctrl.f.MANUAL_OPERATION = 0x0; /* automatic */

    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);

    if (wait_for_idle(1) != 0) return -1;

    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), test_key[i]);
    }
    for (int i = 4; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), 0);
    }

    for (int i = 0; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0);
    }

    if (wait_for_idle(1) != 0) return -1;

    /* Always write IV for completeness (ECB ignores). */
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_IV_BASE_ADDR(i), zero_iv[i]);
    }

    return 0;
}

static int configure_aes_ecb_enc_manual(void) {
    aes__CTRL_SHADOWED_t ctrl = {.w = 0};
    ctrl.f.OPERATION = 0x1; /* ENC */
    ctrl.f.MODE = 0x1;      /* ECB */
    ctrl.f.KEY_LEN = 0x1;   /* AES_128 */
    ctrl.f.SIDELOAD = 0x0;
    ctrl.f.MANUAL_OPERATION = 0x1; /* manual trigger */

    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);

    if (wait_for_idle(1) != 0) return -1;

    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), test_key[i]);
    }
    for (int i = 4; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), 0);
    }

    for (int i = 0; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0);
    }

    if (wait_for_idle(1) != 0) return -1;

    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_IV_BASE_ADDR(i), zero_iv[i]);
    }

    return 0;
}

/* ------------------------------------------------------------------ */
/* Test Body                                                          */
/* ------------------------------------------------------------------ */

static int test_output_valid_clears_on_full_read(void) {
    uint32_t out[4];
    uint32_t w0;

    printf("\n--- STAT-001.A OUTPUT_VALID clear behavior ---\n");

    trigger_data_out_clear();
    if (wait_for_output_valid(0) != 0) return -1;

    if (wait_for_idle(1) != 0) return -1;
    if (configure_aes_ecb_enc_auto() != 0) return -1;

    print_status("  Before DATA_IN");
    write_data_in(pt0);

    /* OUTPUT_VALID should assert when result is available. */
    if (wait_for_output_valid(1) != 0) return -1;
    print_status("  After OUTPUT_VALID");

    /* Partial read should not clear OUTPUT_VALID. */
    read_data_out_word(0, &w0);
    (void)w0;

    aes__STATUS_t s_mid = get_status();
    if (!s_mid.f.OUTPUT_VALID) {
        printf("ERROR: OUTPUT_VALID cleared after partial DATA_OUT read\n");
        return -1;
    }

    /* Full read should clear OUTPUT_VALID. */
    read_data_out(out);
    if (compare_block(out, ct0_exp, "ECB ciphertext") != 0) return -1;

    if (wait_for_output_valid(0) != 0) return -1;
    print_status("  After full DATA_OUT read");

    return 0;
}

static int test_stall_auto_mode(void) {
    printf("\n--- STAT-001.B STALL behavior (auto mode) ---\n");

    /* Clear any prior output state. */
    trigger_data_out_clear();
    if (wait_for_output_valid(0) != 0) return -1;

    if (wait_for_idle(1) != 0) return -1;
    if (configure_aes_ecb_enc_auto() != 0) return -1;

    /* Operation 1: produce an output and do NOT read it. */
    printf("  Op1: generate output, do not read DATA_OUT\n");
    write_data_in(pt0);
    if (wait_for_output_valid(1) != 0) return -1;
    print_status("  After Op1 complete");

    /* Operation 2: start another operation without reading prior output -> expect STALL. */
    printf("  Op2: start new block without reading prior output (expect STALL)\n");
    write_data_in(pt1);

    int saw_stall = 0;
    for (int i = 0; i < 50000; i++) {
        aes__STATUS_t s = get_status();
        if (s.f.STALL) {
            saw_stall = 1;
            break;
        }
    }
    if (!saw_stall) {
        print_status("  ERROR: STALL not observed");
        return -1;
    }
    print_status("  STALL observed");

    /* Reading the pending output should clear STALL and allow Op2 to complete. */
    uint32_t out[4];
    read_data_out(out);

    /* Op2 may complete immediately after the final DATA_OUT read, leaving OUTPUT_VALID asserted.
     * Read DATA_OUT again if needed to clear the new output. */
    int timeout = 200000;
    while (timeout-- > 0) {
        aes__STATUS_t s = get_status();
        if (!s.f.STALL) break;
    }
    if (timeout <= 0) {
        print_status("  ERROR: STALL did not clear after reading DATA_OUT");
        return -1;
    }

    aes__STATUS_t s_after = get_status();
    if (s_after.f.OUTPUT_VALID) {
        read_data_out(out);
    }
    if (wait_for_output_valid(0) != 0) return -1;
    print_status("  After draining DATA_OUT (stall cleared, output_valid cleared)");

    return 0;
}

static int test_output_lost_manual_mode(void) {
    printf("\n--- STAT-001.C OUTPUT_LOST behavior (manual mode) ---\n");

    trigger_data_out_clear();
    if (wait_for_output_valid(0) != 0) return -1;

    if (wait_for_idle(1) != 0) return -1;
    if (configure_aes_ecb_enc_manual() != 0) return -1;
    if (wait_for_output_lost(0) != 0) return -1;

    printf("  Op1: START, do not read DATA_OUT\n");
    write_data_in(pt0);
    trigger_start();
    if (wait_for_output_valid(1) != 0) return -1;
    print_status("  After Op1 complete");

    printf("  Op2: START without reading prior DATA_OUT (expect OUTPUT_LOST)\n");
    write_data_in(pt1);
    trigger_start();
    if (wait_for_output_lost(1) != 0) return -1;
    print_status("  OUTPUT_LOST set");

    /* Clear OUTPUT_LOST by rewriting CTRL_SHADOWED (shadowed double-write). */
    if (configure_aes_ecb_enc_manual() != 0) return -1;
    if (wait_for_output_lost(0) != 0) return -1;
    print_status("  OUTPUT_LOST cleared by CTRL write");

    /* Cleanup: clear DATA_OUT so subsequent tests start clean. */
    trigger_data_out_clear();
    if (wait_for_output_valid(0) != 0) return -1;

    return 0;
}

static int test_trigger_clear_ops(void) {
    printf("\n--- STAT-001.D TRIGGER clear operations ---\n");

    /* KEY_IV_DATA_IN_CLEAR: write a non-zero IV then clear and verify IV reads back as zero. */
    if (wait_for_idle(1) != 0) return -1;
    if (configure_aes_ecb_enc_auto() != 0) return -1;

    static const uint32_t iv_set[4] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c};
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_IV_BASE_ADDR(i), iv_set[i]);
    }
    uint32_t iv_rd[4];
    read_iv(iv_rd);
    if (iv_rd[0] != iv_set[0] || iv_rd[1] != iv_set[1] || iv_rd[2] != iv_set[2] ||
        iv_rd[3] != iv_set[3]) {
        printf("ERROR: IV write/readback failed (got %08x %08x %08x %08x)\n", iv_rd[0], iv_rd[1],
               iv_rd[2], iv_rd[3]);
        return -1;
    }

    trigger_key_iv_data_in_clear();
    if (wait_for_iv_not_equal(iv_set) != 0) return -1;
    read_iv(iv_rd);
    printf("  After KEY_IV_DATA_IN_CLEAR: IV=%08x %08x %08x %08x\n", iv_rd[0], iv_rd[1], iv_rd[2],
           iv_rd[3]);

    /* KEY_IV_DATA_IN_CLEAR wipes key material; reconfigure before running DATA_OUT_CLEAR check. */
    if (configure_aes_ecb_enc_auto() != 0) return -1;

    /* DATA_OUT_CLEAR: generate output, clear output_valid, and ensure output data is overwritten.
     */
    write_data_in(pt0);
    if (wait_for_output_valid(1) != 0) return -1;
    print_status("  Before DATA_OUT_CLEAR");

    trigger_data_out_clear();
    if (wait_for_output_valid(0) != 0) return -1;

    uint32_t out[4];
    read_data_out(out);
    /* Some integrations may not guarantee a literal 0 readback here; require that the value
     * is no longer the previous ciphertext block. */
    if (out[0] == ct0_exp[0] && out[1] == ct0_exp[1] && out[2] == ct0_exp[2] &&
        out[3] == ct0_exp[3]) {
        printf("ERROR: DATA_OUT_CLEAR did not overwrite output data\n");
        return -1;
    }
    print_status("  After DATA_OUT_CLEAR");

    return 0;
}

int main(void) {
    int rc = 0;

    sep_outbound_filter_init();

    if (sep_aes_sw_reset_release() != 0) {
        test_fail(1);
        while (1) __asm__("wfi");
    }

    printf("\n========================================\n");
    printf("sep_aes_status_flow_test (STAT-001)\n");
    printf("========================================\n");
    printf("AES base=0x%08x\n", SEP_TOP_AES_BASE_ADDR);

    if (rc == 0) rc = test_output_valid_clears_on_full_read();
    if (rc == 0) rc = check_alert_status("STAT-001.A");
    if (rc == 0) rc = test_stall_auto_mode();
    if (rc == 0) rc = check_alert_status("STAT-001.B");
    if (rc == 0) rc = test_output_lost_manual_mode();
    if (rc == 0) rc = check_alert_status("STAT-001.C");
    if (rc == 0) rc = test_trigger_clear_ops();
    if (rc == 0) rc = check_alert_status("STAT-001.D");

    if (rc == 0) {
        printf("\n========================================\n");
        printf("=== sep_aes_status_flow_test PASSED ===\n");
        printf("========================================\n");
        test_pass(0);
    } else {
        printf("\n=== sep_aes_status_flow_test FAILED ===\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
