/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Host tests for the Adams Bridge ML-DSA-87 verify driver against fake_abr.c.

#include <stdint.h>
#include <string.h>

#include "abr_driver.h"
#include "abr_driver_internal.h"
#include "fake_abr.h"
#include "unit_helpers.h"

int g_unit_total;
int g_unit_failed;
int g_unit_case_failed;

#define TOKEN 0x5A17C0DEu
#define MSG_LEN 5903u

static uint8_t s_pk[ABR_MLDSA87_PK_BYTES];
static uint8_t s_sig[ABR_MLDSA87_SIG_BYTES];
static uint8_t s_msg[ABR_MLDSA87_MAX_MSG_BYTES + 4u];
static uint32_t s_verdict;
static abr_drv_diag_t s_diag;

void test_fixture_reset(void) {
    fake_abr_reset();
    for (uint32_t i = 0; i < sizeof(s_pk); ++i) s_pk[i] = (uint8_t)(i * 7u + 1u);
    for (uint32_t i = 0; i < sizeof(s_sig); ++i) s_sig[i] = (uint8_t)(i * 13u + 5u);
    for (uint32_t i = 0; i < sizeof(s_msg); ++i) s_msg[i] = (uint8_t)(i * 3u + 9u);
    s_verdict = 0u;
    memset(&s_diag, 0xA5, sizeof(s_diag));
}

static int verify(uint32_t len) {
    return abr_mldsa87_verify(s_pk, s_sig, s_msg, len, TOKEN, &s_verdict, &s_diag);
}

// The strobe of the final MSG write, or ~0 if nothing was streamed.
static uint32_t last_strobe(void) {
    return g_fake.strobe_count != 0u ? g_fake.strobes[g_fake.strobe_count - 1u] : 0xFFFFFFFFu;
}

// Every failure must also leave a rejecting verdict and a zeroized accelerator.
static void expect_reject(int rc, int want) {
    ASSERT_EQ_INT(rc, want);
    ASSERT_EQ_INT(s_verdict, ~TOKEN);
    ASSERT_TRUE(g_fake.zeroize_count >= 1);
    ASSERT_EQ_INT(g_fake.bad_width_accesses, 0);
    ASSERT_EQ_INT(g_fake.out_of_window_accesses, 0);
}

TEST(valid_signature_verifies) {
    ASSERT_EQ_INT(verify(MSG_LEN), ABR_DRV_OK);
    ASSERT_EQ_INT(s_verdict, TOKEN);
    ASSERT_EQ_INT(s_diag.bytes_written, MSG_LEN);
    ASSERT_EQ_INT(s_diag.early_valid, 0);
    ASSERT_EQ_INT(s_diag.res_inverse, 0);
    ASSERT_EQ_INT(s_diag.res_nonzero, 1);
    ASSERT_EQ_INT(s_diag.done_count, 1);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_DONE);
    ASSERT_EQ_INT(g_fake.verify_commands, 1);
    ASSERT_EQ_INT(g_fake.zeroize_count, 2);
    ASSERT_TRUE(g_fake.fence_count >= 2);
    ASSERT_EQ_INT(g_fake.stream_len, MSG_LEN);
    ASSERT_MEM_EQ(g_fake.stream, s_msg, MSG_LEN);
    ASSERT_EQ_INT(last_strobe(), 0x7u);
    ASSERT_EQ_INT(g_fake.msg_outside_stream, 0);
    ASSERT_EQ_INT(g_fake.strobe_outside_stream, 0);
    ASSERT_EQ_INT(g_fake.bad_width_accesses, 0);
    ASSERT_EQ_INT(g_fake.out_of_window_accesses, 0);
}

TEST(diag_may_be_null) {
    ASSERT_EQ_INT(abr_mldsa87_verify(s_pk, s_sig, s_msg, MSG_LEN, TOKEN, &s_verdict, NULL),
                  ABR_DRV_OK);
    ASSERT_EQ_INT(s_verdict, TOKEN);
}

TEST(mismatch_in_each_ctilde_word_rejects) {
    for (int w = 0; w < 16; ++w) {
        test_fixture_reset();
        g_fake.result = FAKE_RES_MISMATCH;
        g_fake.mismatch_word = w;
        expect_reject(verify(MSG_LEN), ABR_DRV_ERR_SIG_INVALID);
        ASSERT_EQ_INT(s_diag.res_inverse, 0);
        ASSERT_EQ_INT(s_diag.res_nonzero, 1);
    }
}

TEST(inverse_result_rejects_and_is_reported) {
    g_fake.result = FAKE_RES_INVERSE;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_SIG_INVALID);
    ASSERT_EQ_INT(s_diag.res_inverse, 1);
}

TEST(zero_result_rejects_and_is_reported) {
    g_fake.result = FAKE_RES_ZERO;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_SIG_INVALID);
    ASSERT_EQ_INT(s_diag.res_nonzero, 0);
}

TEST(all_zero_ctilde_never_starts_the_accelerator) {
    memset(s_sig, 0, ABR_MLDSA87_CTILDE_BYTES);
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_SIG_INVALID);
    ASSERT_EQ_INT(g_fake.verify_commands, 0);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_ARGS);
    ASSERT_EQ_INT(s_diag.done_count, 0);
}

TEST(early_valid_rejects) {
    g_fake.early_valid = 1;
    g_fake.result = FAKE_RES_INVERSE;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_SIG_INVALID);
    ASSERT_EQ_INT(s_diag.early_valid, 1);
    ASSERT_EQ_INT(s_diag.bytes_written, 0);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_STREAM_WAIT);
    ASSERT_EQ_INT(s_diag.res_inverse, 1);
    ASSERT_EQ_INT(s_diag.done_count, 1);
}

TEST(early_valid_with_matching_result_still_rejects) {
    g_fake.early_valid = 1;
    g_fake.result = FAKE_RES_MATCH;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_SIG_INVALID);
    ASSERT_EQ_INT(s_diag.early_valid, 1);
}

TEST(error_while_waiting_for_stream_ready) {
    g_fake.error_in_stream_wait = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_HW);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_STREAM_WAIT);
}

TEST(error_while_waiting_for_valid) {
    g_fake.error_in_complete_wait = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_HW);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_COMPLETE);
}

TEST(zeroize_never_ready) {
    g_fake.zeroize_never_ready = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_STATE);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_ZEROIZE);
    ASSERT_EQ_INT(g_fake.verify_commands, 0);
}

TEST(zeroize_not_clean_ready) {
    g_fake.zeroize_status = 0x3u; // READY | VALID, though the registers accept writes
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_STATE);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_ZEROIZE);
    ASSERT_EQ_INT(g_fake.verify_commands, 0);
}

TEST(stream_ready_timeout) {
    g_fake.never_stream_ready = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_TIMEOUT);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_STREAM_WAIT);
}

TEST(valid_timeout) {
    g_fake.never_valid = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_TIMEOUT);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_COMPLETE);
}

TEST(preload_never_observed) {
    g_fake.no_preload = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_STATE);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_PRELOAD);
    ASSERT_EQ_INT(g_fake.msg_outside_stream, 0);
}

TEST(pubkey_readback_mismatch) {
    g_fake.pk_readback_corrupt = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_FAULT);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_READBACK);
}

TEST(signature_ctilde_readback_mismatch) {
    g_fake.sig_readback_corrupt = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_FAULT);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_READBACK);
}

TEST(second_evaluation_differs) {
    g_fake.second_res_differs = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_FAULT);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_VERDICT);
}

TEST(done_event_arm_not_confirmed) {
    g_fake.done_count_sticks = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_STATE);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_ARM);
    ASSERT_EQ_INT(g_fake.verify_commands, 0);
}

TEST(stale_done_status_not_cleared) {
    g_fake.done_sts_sticks = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_STATE);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_ARM);
    ASSERT_EQ_INT(g_fake.verify_commands, 0);
}

TEST(valid_without_a_done_event_is_a_stale_result) {
    g_fake.done_events = 0; // VERIFY_RES == c~, as a result left over would be
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_STATE);
    ASSERT_EQ_INT(s_diag.done_count, 0);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_COMPLETE);
}

TEST(two_done_events_reject) {
    g_fake.done_events = 2;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_STATE);
    ASSERT_EQ_INT(s_diag.done_count, 2);
}

TEST(done_status_clear_rejects) {
    g_fake.done_sts_cleared = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_STATE);
}

TEST(error_event_at_valid_rejects) {
    g_fake.error_event = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_HW);
}

TEST(error_status_alone_rejects) {
    g_fake.error_sts_only = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_HW);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_COMPLETE);
}

TEST(error_count_alone_rejects) {
    g_fake.error_count_only = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_HW);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_COMPLETE);
}

TEST(trailing_zeroize_failure_after_a_pass_fails_closed) {
    g_fake.trailing_zeroize_fails = 1;
    expect_reject(verify(MSG_LEN), ABR_DRV_ERR_STATE);
    ASSERT_EQ_INT(s_diag.stage, ABR_DRV_STAGE_ZEROIZE);
}

TEST(strobe_sequence_for_each_length) {
    static const uint32_t lens[] = {0u, 1u, 2u, 3u, 4u, 5u, 5900u, 5903u};
    for (uint32_t k = 0; k < sizeof(lens) / sizeof(lens[0]); ++k) {
        const uint32_t len = lens[k];
        test_fixture_reset();
        ASSERT_EQ_INT(verify(len), ABR_DRV_OK);
        ASSERT_EQ_INT(g_fake.stream_len, len);
        ASSERT_MEM_EQ(g_fake.stream, s_msg, len);
        ASSERT_EQ_INT(g_fake.strobe_count, len / 4u + 1u);
        for (uint32_t i = 0; i + 1u < g_fake.strobe_count; ++i) {
            ASSERT_EQ_INT(g_fake.strobes[i], 0xFu);
        }
        ASSERT_EQ_INT(last_strobe(), (1u << (len % 4u)) - 1u);
    }
}

TEST(caller_ctilde_change_after_load_is_not_used) {
    abr_drv_ctx_t ctx;
    abr_drv_ctx_init(&ctx);
    ASSERT_EQ_INT(abr_drv_load(&ctx, s_pk, s_sig), ABR_DRV_OK);
    s_sig[0] ^= 0xFFu;
    ASSERT_EQ_INT(abr_drv_start(&ctx), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_stream_range(&ctx, s_msg, MSG_LEN, 1), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_finish(&ctx, s_pk, MSG_LEN, TOKEN, &s_verdict), ABR_DRV_OK);
    ASSERT_EQ_INT(s_verdict, TOKEN);
}

TEST(short_stream_rejects) {
    abr_drv_ctx_t ctx;
    abr_drv_ctx_init(&ctx);
    ASSERT_EQ_INT(abr_drv_load(&ctx, s_pk, s_sig), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_start(&ctx), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_stream_range(&ctx, s_msg, MSG_LEN - 4u, 1), ABR_DRV_OK);
    expect_reject(abr_drv_finish(&ctx, s_pk, MSG_LEN, TOKEN, &s_verdict), ABR_DRV_ERR_SIG_INVALID);
}

// Each byte count is checked on its own: either one disagreeing rejects.
static void expect_count_reject(int which) {
    abr_drv_ctx_t ctx;
    abr_drv_ctx_init(&ctx);
    ASSERT_EQ_INT(abr_drv_load(&ctx, s_pk, s_sig), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_start(&ctx), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_stream_range(&ctx, s_msg, MSG_LEN, 1), ABR_DRV_OK);
    if (which == 0) {
        ctx.written -= 4u;
    } else {
        ctx.written_dup -= 4u;
    }
    expect_reject(abr_drv_finish(&ctx, s_pk, MSG_LEN, TOKEN, &s_verdict), ABR_DRV_ERR_SIG_INVALID);
    ASSERT_EQ_INT(ctx.diag.stage, ABR_DRV_STAGE_VERDICT);
}

TEST(byte_count_disagrees_rejects) {
    expect_count_reject(0);
}

TEST(duplicate_byte_count_disagrees_rejects) {
    expect_count_reject(1);
}

TEST(non_final_range_must_be_whole_words) {
    abr_drv_ctx_t ctx;
    abr_drv_ctx_init(&ctx);
    ASSERT_EQ_INT(abr_drv_load(&ctx, s_pk, s_sig), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_start(&ctx), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_stream_range(&ctx, s_msg, 6u, 0), ABR_DRV_ERR_PARAM);
}

TEST(zeroize_mid_stream_then_verify) {
    abr_drv_ctx_t ctx;
    abr_drv_ctx_init(&ctx);
    ASSERT_EQ_INT(abr_drv_load(&ctx, s_pk, s_sig), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_start(&ctx), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_stream_range(&ctx, s_msg, 2948u, 0), ABR_DRV_OK);
    ASSERT_EQ_INT(abr_drv_zeroize(), ABR_DRV_OK);
    ASSERT_EQ_INT(verify(MSG_LEN), ABR_DRV_OK);
    ASSERT_EQ_INT(s_verdict, TOKEN);
}

TEST(bad_arguments) {
    ASSERT_EQ_INT(abr_mldsa87_verify(NULL, s_sig, s_msg, MSG_LEN, TOKEN, &s_verdict, NULL),
                  ABR_DRV_ERR_PARAM);
    ASSERT_EQ_INT(s_verdict, ~TOKEN);
    ASSERT_EQ_INT(abr_mldsa87_verify(s_pk, NULL, s_msg, MSG_LEN, TOKEN, &s_verdict, NULL),
                  ABR_DRV_ERR_PARAM);
    ASSERT_EQ_INT(abr_mldsa87_verify(s_pk, s_sig, NULL, MSG_LEN, TOKEN, &s_verdict, NULL),
                  ABR_DRV_ERR_PARAM);
    ASSERT_EQ_INT(abr_mldsa87_verify(s_pk, s_sig, s_msg, MSG_LEN, TOKEN, NULL, NULL),
                  ABR_DRV_ERR_PARAM);
    ASSERT_EQ_INT(abr_mldsa87_verify(s_pk, s_sig, s_msg, ABR_MLDSA87_MAX_MSG_BYTES + 1u, TOKEN,
                                     &s_verdict, NULL),
                  ABR_DRV_ERR_PARAM);
    ASSERT_EQ_INT(abr_mldsa87_verify(s_pk, s_sig, s_msg, MSG_LEN, 0u, &s_verdict, NULL),
                  ABR_DRV_ERR_PARAM);
    ASSERT_EQ_INT(abr_mldsa87_verify(s_pk, s_sig, s_msg, MSG_LEN, 0xFFFFFFFFu, &s_verdict, NULL),
                  ABR_DRV_ERR_PARAM);
    // The verdict key: with it as the token, the first evaluation would cancel out.
    ASSERT_EQ_INT(abr_mldsa87_verify(s_pk, s_sig, s_msg, MSG_LEN, 0xC3A5965Au, &s_verdict, NULL),
                  ABR_DRV_ERR_PARAM);
    ASSERT_EQ_INT(g_fake.verify_commands, 0);
}

TEST(maximum_length_is_accepted) {
    ASSERT_EQ_INT(verify(ABR_MLDSA87_MAX_MSG_BYTES), ABR_DRV_OK);
    ASSERT_EQ_INT(s_diag.bytes_written, ABR_MLDSA87_MAX_MSG_BYTES);
}

TEST(identity_matches) {
    ASSERT_EQ_INT(abr_drv_check_identity(), ABR_DRV_OK);
}

TEST(identity_mismatch) {
    g_fake.identity_bad = 1;
    ASSERT_EQ_INT(abr_drv_check_identity(), ABR_DRV_ERR_IDENTITY);
}

int main(void) {
    RUN_TEST(valid_signature_verifies);
    RUN_TEST(diag_may_be_null);
    RUN_TEST(mismatch_in_each_ctilde_word_rejects);
    RUN_TEST(inverse_result_rejects_and_is_reported);
    RUN_TEST(zero_result_rejects_and_is_reported);
    RUN_TEST(all_zero_ctilde_never_starts_the_accelerator);
    RUN_TEST(early_valid_rejects);
    RUN_TEST(early_valid_with_matching_result_still_rejects);
    RUN_TEST(error_while_waiting_for_stream_ready);
    RUN_TEST(error_while_waiting_for_valid);
    RUN_TEST(zeroize_never_ready);
    RUN_TEST(zeroize_not_clean_ready);
    RUN_TEST(stream_ready_timeout);
    RUN_TEST(valid_timeout);
    RUN_TEST(preload_never_observed);
    RUN_TEST(pubkey_readback_mismatch);
    RUN_TEST(signature_ctilde_readback_mismatch);
    RUN_TEST(second_evaluation_differs);
    RUN_TEST(done_event_arm_not_confirmed);
    RUN_TEST(stale_done_status_not_cleared);
    RUN_TEST(valid_without_a_done_event_is_a_stale_result);
    RUN_TEST(two_done_events_reject);
    RUN_TEST(done_status_clear_rejects);
    RUN_TEST(error_event_at_valid_rejects);
    RUN_TEST(error_status_alone_rejects);
    RUN_TEST(error_count_alone_rejects);
    RUN_TEST(trailing_zeroize_failure_after_a_pass_fails_closed);
    RUN_TEST(strobe_sequence_for_each_length);
    RUN_TEST(caller_ctilde_change_after_load_is_not_used);
    RUN_TEST(short_stream_rejects);
    RUN_TEST(byte_count_disagrees_rejects);
    RUN_TEST(duplicate_byte_count_disagrees_rejects);
    RUN_TEST(non_final_range_must_be_whole_words);
    RUN_TEST(zeroize_mid_stream_then_verify);
    RUN_TEST(bad_arguments);
    RUN_TEST(maximum_length_is_accepted);
    RUN_TEST(identity_matches);
    RUN_TEST(identity_mismatch);
    return unit_report();
}
