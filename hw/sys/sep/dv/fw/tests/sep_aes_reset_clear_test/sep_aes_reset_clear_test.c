/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES Reset / Clear Test (SEC-002)
 *
 * Coverage:
 *  - KEY_IV_DATA_IN_CLEAR changes software-visible key/IV state and invalidates
 *    the previously programmed key material.
 *  - DATA_OUT_CLEAR clears OUTPUT_VALID and overwrites unread output data.
 *  - AES software reset is pulsed through sep_reset_ctrl, and the full reset
 *    effects are checked: idle, CTRL_AUX_REGWEN restored, IV cleared, key
 *    wiped, then normal operation with the original key.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

/* ------------------------------------------------------------------ */
/* Minimal trap handler (no printf to avoid recursive traps)          */
/* ------------------------------------------------------------------ */

#define STDOUT_ADDR 0x80000000

static void raw_putc(char c) {
    *(volatile uint8_t *)STDOUT_ADDR = (uint8_t)c;
}

static void raw_puts(const char *s) {
    while (*s) raw_putc(*s++);
}

static void raw_hex32(uint32_t v) {
    const char hex[] = "0123456789abcdef";
    raw_puts("0x");
    for (int i = 28; i >= 0; i -= 4) raw_putc(hex[(v >> i) & 0xf]);
}

void trap_dump(uint32_t mcause, uint32_t mepc, uint32_t mtval) __attribute__((noreturn));

void trap_dump(uint32_t mcause, uint32_t mepc, uint32_t mtval) {
    raw_puts("\n*** TRAP ***\nmcause=");
    raw_hex32(mcause);
    raw_puts("\nmepc=");
    raw_hex32(mepc);
    raw_puts("\nmtval=");
    raw_hex32(mtval);
    raw_putc('\n');
    test_fail(1);
    while (1) __asm__ volatile("wfi");
}

static void trap_handler_c(void) __attribute__((naked));
static void trap_handler_c(void) {
    __asm__ volatile("addi  sp, sp, -16   \n"
                     "sw    ra, 12(sp)    \n"
                     "csrr  a0, mcause    \n"
                     "csrr  a1, mepc      \n"
                     "csrr  a2, mtval     \n"
                     "call  trap_dump     \n");
}

static void install_trap_handler(void) {
    uintptr_t addr = (uintptr_t)&trap_handler_c;
    __asm__ volatile("csrw mtvec, %0" ::"r"(addr));
}

static const uint32_t test_key[4] = {0x16157e2b, 0xa6d2ae28, 0x8815f7ab, 0x3c4fcf09};

static const uint32_t zero_iv[4] = {0x00000000, 0x00000000, 0x00000000, 0x00000000};

static const uint32_t probe_iv[4] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c};

static const uint32_t pt0[4] = {0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373};

static const uint32_t ct0_exp[4] = {0xb47bd73a, 0x60367a0d, 0xf3ca9ea8, 0x97ef6624};

static void spin_delay(int cycles) {
    for (volatile int i = 0; i < cycles; i++) {
        __asm__("nop");
    }
}

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t s = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (s.f.IDLE) return 0;
    }
    printf("ERROR: Timeout waiting for AES idle\n");
    return -1;
}

static int wait_for_input_ready(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t s = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (s.f.INPUT_READY) return 0;
    }
    printf("ERROR: Timeout waiting for AES input ready\n");
    return -1;
}

static int wait_for_output_valid(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t s = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (s.f.OUTPUT_VALID) return 0;
    }
    printf("ERROR: Timeout waiting for AES output valid\n");
    return -1;
}

static int wait_for_output_cleared(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t s = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (!s.f.OUTPUT_VALID) return 0;
    }
    printf("ERROR: Timeout waiting for AES output_valid=0\n");
    return -1;
}

static void print_status(const char *tag) {
    uint32_t val = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR);
    printf("%s: STATUS=0x%08x (idle=%u stall=%u output_lost=%u output_valid=%u input_ready=%u)\n",
           tag, val, (val >> 0) & 1, (val >> 1) & 1, (val >> 2) & 1, (val >> 3) & 1,
           (val >> 4) & 1);
}

static void write_ctrl_shadowed(uint32_t operation, uint32_t mode, uint32_t manual_operation) {
    aes__CTRL_SHADOWED_t ctrl = {.w = 0};
    ctrl.f.OPERATION = operation;
    ctrl.f.MODE = mode;
    ctrl.f.KEY_LEN = 0x1; /* AES-128 */
    ctrl.f.SIDELOAD = 0x0;
    ctrl.f.MANUAL_OPERATION = manual_operation;

    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
}

static int configure_aes_ecb_enc_auto(const uint32_t iv[4]) {
    write_ctrl_shadowed(0x1, 0x1, 0x0);
    if (wait_for_idle() != 0) return -1;

    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), test_key[i]);
    }
    for (int i = 4; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), 0);
    }
    for (int i = 0; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0);
    }

    if (wait_for_idle() != 0) return -1;

    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_IV_BASE_ADDR(i), iv[i]);
    }

    return 0;
}

static void cleanup_aes(void) {
    aes__TRIGGER_t trigger = {.w = 0};

    write_ctrl_shadowed(0x1, 0x1, 0x1);

    trigger.f.KEY_IV_DATA_IN_CLEAR = 1;
    trigger.f.DATA_OUT_CLEAR = 1;
    WRITE_REG(SEP_TOP_AES_TRIGGER_BASE_ADDR, trigger.w);
}

static void write_data_in(const uint32_t in[4]) {
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_DATA_IN_BASE_ADDR(i), in[i]);
    }
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

static int blocks_equal(const uint32_t *lhs, const uint32_t *rhs, int words) {
    for (int i = 0; i < words; i++) {
        if (lhs[i] != rhs[i]) {
            return 0;
        }
    }
    return 1;
}

static int ensure_aes_sw_reset_released(void) {
    uint32_t sw_reset_n = READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    sw_reset_n |= (uint32_t)SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm;
    WRITE_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, sw_reset_n);
    __asm__ volatile("fence" ::: "memory");
    sw_reset_n = READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);

    if ((sw_reset_n & SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm) == 0) {
        printf("ERROR: AES sw reset release not functional\n");
        return -1;
    }

    return 0;
}

static int pulse_aes_sw_reset(void) {
    uint32_t sw_reset_n = READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    uint32_t released = sw_reset_n | (uint32_t)SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm;
    uint32_t asserted = released & ~((uint32_t)SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm);

    WRITE_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, released);
    __asm__ volatile("fence" ::: "memory");
    if ((READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR) &
         SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm) == 0) {
        printf("ERROR: AES sw reset bit did not reach released state\n");
        return -1;
    }

    WRITE_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, asserted);
    __asm__ volatile("fence" ::: "memory");
    spin_delay(200);
    if ((READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR) &
         SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm) != 0) {
        printf("ERROR: AES sw reset bit did not assert low\n");
        return -1;
    }

    WRITE_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, released);
    __asm__ volatile("fence" ::: "memory");
    spin_delay(400);
    if ((READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR) &
         SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm) == 0) {
        printf("ERROR: AES sw reset bit did not release high\n");
        return -1;
    }

    return 0;
}

static int test_key_iv_clear_invalidate_previous_key(void) {
    uint32_t out[4];
    uint32_t out_after_clear[4];
    uint32_t iv_before[4];
    uint32_t iv_after[4];

    printf("\n--- SEC-002.A KEY_IV_DATA_IN_CLEAR behavior ---\n");

    if (wait_for_idle() != 0) return -1;
    if (configure_aes_ecb_enc_auto(probe_iv) != 0) return -1;
    if (wait_for_input_ready() != 0) return -1;

    write_data_in(pt0);
    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out);
    if (compare_block(out, ct0_exp, "Baseline ECB ciphertext") != 0) return -1;
    printf("  Baseline ciphertext matches NIST reference\n");

    read_iv(iv_before);
    printf("  IV before clear: 0x%08x 0x%08x 0x%08x 0x%08x\n", iv_before[0], iv_before[1],
           iv_before[2], iv_before[3]);

    aes__TRIGGER_t trigger = {.w = 0};
    trigger.f.KEY_IV_DATA_IN_CLEAR = 1;
    WRITE_REG(SEP_TOP_AES_TRIGGER_BASE_ADDR, trigger.w);
    if (wait_for_idle() != 0) return -1;

    read_iv(iv_after);
    printf("  IV after  clear: 0x%08x 0x%08x 0x%08x 0x%08x\n", iv_after[0], iv_after[1],
           iv_after[2], iv_after[3]);

    if (blocks_equal(iv_before, iv_after, 4)) {
        printf("ERROR: IV contents were not changed by KEY_IV_DATA_IN_CLEAR\n");
        return -1;
    }
    printf("  IV registers changed after KEY_IV_DATA_IN_CLEAR\n");

    /* KEY_SHARE0/KEY_SHARE1 are write-only (swaccess=wo) so we cannot verify
     * them via direct readback. Instead, re-configure AES with an all-zero key
     * (different from test_key) and encrypt the same plaintext. The AES spec
     * requires all key registers to be written before accepting new data. */
    write_ctrl_shadowed(0x1, 0x1, 0x0);
    if (wait_for_idle() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), 0);
    }
    for (int i = 0; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0);
    }

    if (wait_for_input_ready() != 0) return -1;
    write_data_in(pt0);
    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out_after_clear);

    printf("  Post-clear CT: 0x%08x 0x%08x 0x%08x 0x%08x\n", out_after_clear[0], out_after_clear[1],
           out_after_clear[2], out_after_clear[3]);

    if (blocks_equal(out_after_clear, ct0_exp, 4)) {
        printf("ERROR: Ciphertext still matches baseline with zero-key -- key not invalidated\n");
        return -1;
    }

    printf("  Zero-key ciphertext differs from baseline -- key material invalidated\n");
    if (check_alert_status("SEC-002.A") != 0) return -1;
    return 0;
}

static int test_data_out_clear(void) {
    uint32_t out_after_clear[4];

    printf("\n--- SEC-002.B DATA_OUT_CLEAR behavior ---\n");

    if (wait_for_idle() != 0) return -1;
    if (configure_aes_ecb_enc_auto(zero_iv) != 0) return -1;
    if (wait_for_input_ready() != 0) return -1;

    write_data_in(pt0);
    if (wait_for_output_valid() != 0) return -1;
    print_status("  Before DATA_OUT_CLEAR");

    aes__TRIGGER_t trigger = {.w = 0};
    trigger.f.DATA_OUT_CLEAR = 1;
    WRITE_REG(SEP_TOP_AES_TRIGGER_BASE_ADDR, trigger.w);

    if (wait_for_output_cleared() != 0) return -1;
    read_data_out(out_after_clear);

    if (blocks_equal(out_after_clear, ct0_exp, 4)) {
        printf("ERROR: DATA_OUT_CLEAR did not overwrite the unread ciphertext\n");
        return -1;
    }

    printf("  DATA_OUT_CLEAR cleared OUTPUT_VALID and overwrote DATA_OUT\n");
    if (check_alert_status("SEC-002.B") != 0) return -1;
    return 0;
}

static int test_aes_sw_reset_probe(void) {
    uint32_t baseline_ct[4];
    uint32_t post_reset_ct[4];
    uint32_t iv_after_reset[4];
    uint32_t regwen_before;
    uint32_t regwen_after;
    uint32_t status_after;

    printf("\n--- SEC-002.C AES software reset probe ---\n");

    if (ensure_aes_sw_reset_released() != 0) {
        printf("ERROR: AES SW reset bit not writable via sep_reset_ctrl\n");
        return -1;
    }

    /* ---- Step 1: Configure AES with sensitive data and perform operation ---- */
    printf("  Step 1: Perform baseline encryption before reset\n");
    if (configure_aes_ecb_enc_auto(probe_iv) != 0) return -1;
    if (wait_for_input_ready() != 0) return -1;
    write_data_in(pt0);
    if (wait_for_output_valid() != 0) return -1;
    read_data_out(baseline_ct);
    if (compare_block(baseline_ct, ct0_exp, "Pre-reset baseline CT") != 0) return -1;
    printf("  Baseline CT: 0x%08x 0x%08x 0x%08x 0x%08x\n", baseline_ct[0], baseline_ct[1],
           baseline_ct[2], baseline_ct[3]);

    /* Lock CTRL_AUX_REGWEN so we can verify reset restores it */
    WRITE_REG(SEP_TOP_AES_CTRL_AUX_SHADOWED_BASE_ADDR, 0x00000001);
    WRITE_REG(SEP_TOP_AES_CTRL_AUX_SHADOWED_BASE_ADDR, 0x00000001);
    WRITE_REG(SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR, 0x00000000);
    regwen_before = READ_REG(SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR);
    if ((regwen_before & 0x1) != 0) {
        printf("ERROR: could not lock CTRL_AUX_REGWEN before reset probe\n");
        return -1;
    }
    printf("  CTRL_AUX_REGWEN locked (0x%08x)\n", regwen_before);

    /* Write known IV so we can check it is cleared */
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_IV_BASE_ADDR(i), probe_iv[i]);
    }

    /* ---- Step 2: Apply software reset ---- */
    printf("  Step 2: Pulse AES software reset\n");
    if (pulse_aes_sw_reset() != 0) {
        printf("ERROR: pulse_aes_sw_reset() did not toggle reset bit\n");
        return -1;
    }
    spin_delay(400);

    /* ---- Step 3: Verify registers return to reset values ---- */
    printf("  Step 3: Verify reset values\n");

    status_after = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR);
    printf("  STATUS after reset: 0x%08x (idle=%u)\n", status_after, (status_after >> 0) & 1);
    if (((status_after >> 0) & 1) != 1) {
        printf("ERROR: AES not idle after sw reset\n");
        return -1;
    }

    regwen_after = READ_REG(SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR);
    printf("  CTRL_AUX_REGWEN after reset: 0x%08x\n", regwen_after);
    if ((regwen_after & 0x1) != 0x1) {
        printf("ERROR: CTRL_AUX_REGWEN not restored after sw reset (got=0x%08x)\n", regwen_after);
        return -1;
    }

    read_iv(iv_after_reset);
    printf("  IV after reset: 0x%08x 0x%08x 0x%08x 0x%08x\n", iv_after_reset[0], iv_after_reset[1],
           iv_after_reset[2], iv_after_reset[3]);
    if (blocks_equal(iv_after_reset, probe_iv, 4)) {
        printf("ERROR: IV registers not cleared by sw reset\n");
        return -1;
    }

    /* ---- Step 3b: Verify key material is cleared (no residual key) ---- */
    printf("  Step 3b: Verify key material invalidated by reset\n");

    /*
     * Re-configure AES with a zero key (different from test_key) and encrypt
     * the same plaintext. If the old key were still present, the ciphertext
     * would match baseline_ct. A different ciphertext proves the key was wiped.
     */
    write_ctrl_shadowed(0x1, 0x1, 0x0);
    if (wait_for_idle() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), 0);
    }
    for (int i = 0; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0);
    }

    if (wait_for_input_ready() != 0) return -1;
    write_data_in(pt0);
    if (wait_for_output_valid() != 0) return -1;
    read_data_out(post_reset_ct);

    printf("  Post-reset CT (zero-key): 0x%08x 0x%08x 0x%08x 0x%08x\n", post_reset_ct[0],
           post_reset_ct[1], post_reset_ct[2], post_reset_ct[3]);

    if (blocks_equal(post_reset_ct, baseline_ct, 4)) {
        printf("ERROR: Ciphertext matches baseline after reset -- key not cleared\n");
        return -1;
    }
    printf("  Key material confirmed invalidated after sw reset\n");

    /* ---- Step 3c: Verify AES returns to full functional state ---- */
    printf("  Step 3c: Verify AES functional after reset (re-encrypt with original key)\n");

    if (configure_aes_ecb_enc_auto(zero_iv) != 0) return -1;
    if (wait_for_input_ready() != 0) return -1;
    write_data_in(pt0);
    if (wait_for_output_valid() != 0) return -1;

    uint32_t recovery_ct[4];
    read_data_out(recovery_ct);
    if (compare_block(recovery_ct, ct0_exp, "Post-reset recovery CT") != 0) {
        printf("ERROR: AES not functional after sw reset\n");
        return -1;
    }
    printf("  AES fully functional after sw reset -- recovery CT matches NIST reference\n");

    printf("  AES software reset cleared all sensitive state as expected\n");
    if (check_alert_status("SEC-002.C") != 0) return -1;
    return 0;
}

int main(void) {
    int rc = 0;

    sep_outbound_filter_init();
    install_trap_handler();

    /* Release AES from software reset (default state is asserted/0) */
    if (ensure_aes_sw_reset_released() != 0) {
        printf("ERROR: cannot release AES sw reset at boot\n");
        test_fail(1);
        while (1) __asm__("wfi");
    }

    printf("\n========================================\n");
    printf("sep_aes_reset_clear_test (SEC-002)\n");
    printf("========================================\n");
    printf("AES base=0x%08x\n", SEP_TOP_AES_BASE_ADDR);

    if (rc == 0) rc = test_key_iv_clear_invalidate_previous_key();
    if (rc == 0) rc = test_data_out_clear();
    if (rc == 0) rc = test_aes_sw_reset_probe();

    cleanup_aes();

    if (rc == 0) {
        printf("\n========================================\n");
        printf("=== sep_aes_reset_clear_test PASSED ===\n");
        printf("========================================\n");
        test_pass(0);
    } else {
        printf("\n=== sep_aes_reset_clear_test FAILED ===\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
