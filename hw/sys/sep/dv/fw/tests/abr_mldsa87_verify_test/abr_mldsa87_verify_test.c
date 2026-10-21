/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Adams Bridge ML-DSA-87 verify of a blob signed at build time with the test key.
//
// Each case drives the boot ROM's ABR driver and prints one line with the driver's
// status and diagnostics, so a run on the virtual platform and a run in RTL
// simulation can be compared line by line by hand. abr_case_params[1] selects the cases
// (bit n runs case n); a testbench may overwrite it in the loaded image, found by
// the magic in abr_case_params[0], to split the set across runs of the same image.

#include <stdint.h>
#include <stdio.h>

#include "abr_driver.h"
#include "abr_driver_internal.h"
#include "mldsa87_vectors.h"
#include "sep_outbound_filter.h"

#define PASS_TOKEN 0x6A7B8C9Du
#define CASE_PARAM_MAGIC 0xAB2D5A87u
#define ALL_CASES 0x3FFFu

volatile uint32_t abr_case_params[2] = {CASE_PARAM_MAGIC, ALL_CASES};

static uint8_t s_blob[MLDSA87_BLOB_LEN];
static uint8_t s_sig[ABR_MLDSA87_SIG_BYTES];

typedef struct {
    int status;
    abr_drv_diag_t diag;
    uint32_t verdict;
} outcome_t;

// Fields set to -1, and a stage of ANY_STAGE, are not checked.
typedef struct {
    int status;
    uint32_t stage;
    int32_t written; // -1: not checked
    int32_t early;   // -1: not checked
    int32_t inv;     // -1: not checked
    int32_t nz;      // -1: not checked
    uint32_t done;
} expect_t;

#define ANY_STAGE (ABR_DRV_STAGE_DONE + 1u)

static void copy(uint8_t *dst, const uint8_t *src, uint32_t n) {
    for (uint32_t i = 0; i < n; ++i) dst[i] = src[i];
}

static outcome_t run(const uint8_t *pk, const uint8_t *sig, const uint8_t *msg, uint32_t len) {
    outcome_t o;
    o.status = abr_mldsa87_verify(pk, sig, msg, len, PASS_TOKEN, &o.verdict, &o.diag);
    return o;
}

static int report(unsigned id, const char *name, const outcome_t *o, const expect_t *e) {
    int ok = o->status == e->status;
    ok &= e->status != ABR_DRV_OK || o->verdict == PASS_TOKEN;
    ok &= e->status == ABR_DRV_OK || o->verdict == ~PASS_TOKEN;
    ok &= e->stage == ANY_STAGE || o->diag.stage == e->stage;
    ok &= e->written < 0 || o->diag.bytes_written == (uint32_t)e->written;
    ok &= e->early < 0 || o->diag.early_valid == (uint32_t)e->early;
    ok &= e->inv < 0 || o->diag.res_inverse == (uint32_t)e->inv;
    ok &= e->nz < 0 || o->diag.res_nonzero == (uint32_t)e->nz;
    ok &= o->diag.done_count == e->done;
    printf("case %u %s: %s status=%d stage=%lu written=%lu early=%lu inv=%lu nz=%lu done=%lu\n", id,
           name, ok ? "PASS" : "FAIL", o->status, (unsigned long)o->diag.stage,
           (unsigned long)o->diag.bytes_written, (unsigned long)o->diag.early_valid,
           (unsigned long)o->diag.res_inverse, (unsigned long)o->diag.res_nonzero,
           (unsigned long)o->diag.done_count);
    return ok;
}

// A signature the accelerator computed a non-matching c~' for.
static const expect_t REJECT_COMPUTED = {
    ABR_DRV_ERR_SIG_INVALID, ABR_DRV_STAGE_VERDICT, MLDSA87_BLOB_LEN, 0, 0, 1, 1u};

static int case_identity(void) {
    const int rc = abr_drv_check_identity();
    printf("case 0 identity: %s status=%d\n", rc == ABR_DRV_OK ? "PASS" : "FAIL", rc);
    return rc == ABR_DRV_OK;
}

static int case_genuine(unsigned id, const char *name) {
    const outcome_t o = run(mldsa87_test_pk, mldsa87_sig_genuine, mldsa87_blob, MLDSA87_BLOB_LEN);
    const expect_t e = {ABR_DRV_OK, ABR_DRV_STAGE_DONE, MLDSA87_BLOB_LEN, 0, 0, 1, 1u};
    return report(id, name, &o, &e);
}

static int case_whole_words(void) {
    const outcome_t o =
        run(mldsa87_test_pk, mldsa87_sig_genuine_5900, mldsa87_blob, MLDSA87_BLOB_LEN_WHOLE_WORDS);
    const expect_t e = {ABR_DRV_OK, ABR_DRV_STAGE_DONE, MLDSA87_BLOB_LEN_WHOLE_WORDS, 0, 0, 1, 1u};
    return report(2, "genuine_len_mod4_0", &o, &e);
}

static int case_tampered_blob(void) {
    copy(s_blob, mldsa87_blob, MLDSA87_BLOB_LEN);
    s_blob[MLDSA87_BLOB_LEN / 2u] ^= 0x01u;
    const outcome_t o = run(mldsa87_test_pk, mldsa87_sig_genuine, s_blob, MLDSA87_BLOB_LEN);
    return report(3, "tampered_blob", &o, &REJECT_COMPUTED);
}

static int case_tampered_z(void) {
    copy(s_sig, mldsa87_sig_genuine, ABR_MLDSA87_SIG_BYTES);
    s_sig[MLDSA87_TAMPERED_Z_OFFSET] ^= MLDSA87_TAMPERED_Z_MASK;
    const outcome_t o = run(mldsa87_test_pk, s_sig, mldsa87_blob, MLDSA87_BLOB_LEN);
    return report(4, "tampered_z", &o, &REJECT_COMPUTED);
}

static int case_tampered_ctilde(void) {
    copy(s_sig, mldsa87_sig_genuine, ABR_MLDSA87_SIG_BYTES);
    s_sig[0] ^= 0x01u;
    const outcome_t o = run(mldsa87_test_pk, s_sig, mldsa87_blob, MLDSA87_BLOB_LEN);
    return report(5, "tampered_ctilde", &o, &REJECT_COMPUTED);
}

static int case_rejected(unsigned id, const char *name, const uint8_t *pk, const uint8_t *sig) {
    const outcome_t o = run(pk, sig, mldsa87_blob, MLDSA87_BLOB_LEN);
    return report(id, name, &o, &REJECT_COMPUTED);
}

// Genuine c~ with a malformed body: the accelerator itself must leave ~c~, which
// separates its preload from a result of 0 or one left over.
static int case_ctilde_bad_z(void) {
    const outcome_t o =
        run(mldsa87_test_pk, mldsa87_sig_ctilde_bad_z, mldsa87_blob, MLDSA87_BLOB_LEN);
    const expect_t e = {ABR_DRV_ERR_SIG_INVALID, ABR_DRV_STAGE_STREAM_WAIT, 0, 1, 1, -1, 1u};
    return report(9, "genuine_ctilde_bad_z", &o, &e);
}

static int case_ctilde_bad_hint(void) {
    const outcome_t o =
        run(mldsa87_test_pk, mldsa87_sig_ctilde_bad_hint, mldsa87_blob, MLDSA87_BLOB_LEN);
    const expect_t e = {
        ABR_DRV_ERR_SIG_INVALID, ABR_DRV_STAGE_VERDICT, MLDSA87_BLOB_LEN, 0, 1, 1, 1u};
    return report(10, "genuine_ctilde_bad_hint", &o, &e);
}

static int case_forged_c0(void) {
    const outcome_t o =
        run(mldsa87_test_pk, mldsa87_sig_forged_c0_bad_z, mldsa87_blob, MLDSA87_BLOB_LEN);
    const expect_t e = {ABR_DRV_ERR_SIG_INVALID, ABR_DRV_STAGE_ARGS, 0, 0, 0, 0, 0u};
    return report(11, "forged_c0_bad_z", &o, &e);
}

// Zeroize half way through the stream; nothing may be published, and the next
// verify must pass.
static int case_zeroize_midstream(void) {
    abr_drv_ctx_t ctx;
    abr_drv_ctx_init(&ctx);

    int rc = abr_drv_load(&ctx, mldsa87_test_pk, mldsa87_sig_genuine);
    if (rc == ABR_DRV_OK) rc = abr_drv_start(&ctx);
    if (rc == ABR_DRV_OK) rc = abr_drv_stream_range(&ctx, mldsa87_blob, 2948u, 0);
    const int zrc = abr_drv_zeroize();
    const int ok_abort = rc == ABR_DRV_OK && zrc == ABR_DRV_OK;
    printf("case 12 zeroize_midstream_abort: %s status=%d zeroize=%d written=%lu\n",
           ok_abort ? "PASS" : "FAIL", rc, zrc, (unsigned long)ctx.written);
    return case_genuine(12, "zeroize_midstream") && ok_abort;
}

int main(void) {
    sep_outbound_filter_init();
    const uint32_t mask = abr_case_params[1];
    printf("abr_mldsa87_verify_test: case_mask=0x%04lx\n", (unsigned long)mask);
    // A mask that selects nothing would otherwise report PASS having run no case.
    if (mask == 0u || (mask & ~ALL_CASES) != 0u) {
        printf("abr_mldsa87_verify_test: FAIL (case mask selects no case or an unknown one)\n");
        return 1;
    }

    unsigned failed = 0u;
    unsigned run_count = 0u;
#define CASE(n, expr) \
    do { \
        if ((mask >> (n)) & 1u) { \
            ++run_count; \
            if (!(expr)) ++failed; \
        } \
    } while (0)

    CASE(0, case_identity());
    CASE(1, case_genuine(1, "genuine"));
    CASE(2, case_whole_words());
    CASE(3, case_tampered_blob());
    CASE(4, case_tampered_z());
    CASE(5, case_tampered_ctilde());
    CASE(6, case_rejected(6, "wrong_key", mldsa87_wrong_pk, mldsa87_sig_genuine));
    CASE(7, case_rejected(7, "context_oca", mldsa87_test_pk, mldsa87_sig_ctx_oca));
    CASE(8, case_rejected(8, "prehash", mldsa87_test_pk, mldsa87_sig_prehash));
    CASE(9, case_ctilde_bad_z());
    CASE(10, case_ctilde_bad_hint());
    CASE(11, case_forged_c0());
    CASE(12, case_zeroize_midstream());
    CASE(13, case_genuine(13, "genuine_repeat"));
#undef CASE

    printf("abr_mldsa87_verify_test: %s (%u failed, %u run)\n", failed == 0u ? "PASS" : "FAIL",
           failed, run_count);
    return failed == 0u ? 0 : 1;
}
