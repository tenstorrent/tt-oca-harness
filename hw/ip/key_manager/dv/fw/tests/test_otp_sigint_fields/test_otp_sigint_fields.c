/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_otp_sigint_fields.c
 * @brief Per-field attribution of the OTP dual-rail integrity check.
 *
 * IRQ_STATUS.otp_sigint is the OR of one decoder per 256-bit OTP field, so a
 * fault test can only ever prove that *some* decoder works.  This test walks
 * every field in turn, corrupting one dual rail at a time and confirming that
 * the status bit sets, that only the corrupted field's readback fails its
 * complement check, and that the status clears once the field is valid again.
 * A decoder fed from the wrong capture, or one left out of the aggregate, fails
 * here even though the readback path in test_otp_data still looks correct.
 *
 * The sigint IRQ enable is cleared up front so the corruption never reaches the
 * ROM ISR: the unrecoverable path it would take is covered by test_otp_sigint.
 *
 * Run: make run_fw FW_TEST=test_otp_sigint_fields
 */

#include "test_common.h"
#include "rom_otp.h"
#include "irq_common.h"
#include "rom_kmcsr.h"

/* Disable the SRAM wipe paths so they do not interfere with this test. */
int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

static const struct {
    const char *name;
    uint32_t selector;
    int (*reader)(uint32_t[ROM_KM_OTP_WORDS]);
} k_fields[] = {
    {"CHIPLET_UID", ROM_KM_OTP_DR_FIELD_CHIPLET_UID, rom_otp_read_chiplet_uid},
    {"SIP_UID", ROM_KM_OTP_DR_FIELD_SIP_UID, rom_otp_read_sip_uid},
    {"SYS_UID", ROM_KM_OTP_DR_FIELD_SYS_UID, rom_otp_read_sys_uid},
    {"CLASS_KEY", ROM_KM_OTP_DR_FIELD_CLASS_KEY, rom_otp_read_class_key},
    {"SEP_CHIPLET_ID", ROM_KM_OTP_DR_FIELD_SEP_CHIPLET_ID, rom_otp_read_sep_chiplet_id},
    {"SEP_SIP_ID", ROM_KM_OTP_DR_FIELD_SEP_SIP_ID, rom_otp_read_sep_sip_id},
    {"SEP_SYS_ID", ROM_KM_OTP_DR_FIELD_SEP_SYS_ID, rom_otp_read_sep_sys_id},
};

#define NUM_FIELDS (sizeof(k_fields) / sizeof(k_fields[0]))

static int sigint_status_set(void) {
    km_csr__irq_status_reg_t st;
    st.w = rom_kmcsr_irq_status_read();
    return (st.w & KM_CSR__IRQ_STATUS_REG__OTP_SIGINT_bm) != 0u;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(200000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    printf("OTP Signal Integrity Per-Field Test\n");
    printf("===================================\n\n");

    /* Keep the corruption off the ROM ISR: status only, no interrupt. */
    {
        km_csr__irq_enable_reg_t en;
        en.w = rom_kmcsr_irq_enable_read();
        en.w &= ~(uint32_t)KM_CSR__IRQ_ENABLE_REG__OTP_SIGINT_EN_bm;
        rom_kmcsr_irq_enable_write(en.w);
    }

    tb_otp_write();
    test_delay(200);
    rom_kmcsr_irq_status_clear(0xFFFFFFFFu);

    if (sigint_status_set()) {
        TEST_FAIL("otp_sigint set with a valid pattern driven on every field");
    }

    for (unsigned i = 0; i < NUM_FIELDS; i++) {
        TEST_SUBTEST_START(k_fields[i].name);

        tb_otp_write_sigint_field(k_fields[i].selector);
        test_delay(200);
        if (!sigint_status_set()) {
            TEST_FAIL("%s: corrupting the dual rail did not set otp_sigint", k_fields[i].name);
        }

        /* The status bit is an OR, so also confirm the corruption landed where
         * it was asked for: only this field's readback fails its complement
         * check, every other field still reads consistently. */
        for (unsigned j = 0; j < NUM_FIELDS; j++) {
            uint32_t buf[ROM_KM_OTP_WORDS];
            int rc = k_fields[j].reader(buf);
            if (j == i && rc == 0) {
                TEST_FAIL("%s: readback stayed complementary while corrupted", k_fields[j].name);
            }
            if (j != i && rc != 0) {
                TEST_FAIL("%s: readback broke while %s was the corrupted field", k_fields[j].name,
                          k_fields[i].name);
            }
        }

        /* Restore a valid encoding, then clear: the bit is sticky but hardware
         * re-sets it every cycle the corruption is still present. */
        tb_otp_write();
        test_delay(200);
        rom_kmcsr_irq_status_clear(KM_CSR__IRQ_STATUS_REG__OTP_SIGINT_bm);
        if (sigint_status_set()) {
            TEST_FAIL("%s: otp_sigint stayed set after the field was made valid again",
                      k_fields[i].name);
        }

        TEST_SUBTEST_PASS();
    }

    TEST_PASS();
    return 0;
}
