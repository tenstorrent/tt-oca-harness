// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP HMAC, KMAC and AES CPU crypto smoke firmware test over the CPU-to-fabric
// path.
//
// HMAC (SHA-256 mode): hash three messages and compare each digest against an
// independent software SHA-256 (tests/common/sha256.c) over the same bytes.
// Each hash must finish without timeout or error and clear its done status.
//
// KMAC (KMAC128): run a masked hash with software entropy, so the engine does
// not wait on EDN, and check that it completes without error and that the
// unmasked digest is non-zero. There is no Keccak reference model, so the
// digest value itself is not checked.
//
// AES-128-ECB: encrypt the FIPS-197 C.1 block staged in SRAM, compare it with
// the published ciphertext, then decrypt it and compare with the plaintext read
// back from SRAM.
//
// main() returns the error count; crt0.s turns 0 into the PASS magic and any
// other value into the FAIL magic.

#include <stdint.h>
#include <string.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_hmac.h"
#include "sep_kmac.h"
#include "sha256.h"
#include "sep_aes_init.h"
#include "sep_entropy.h"
#include "aes_test_util.h"

// AES operation and mode encodings; the generated header has no enum for them.
#define AES_OP_ENC 0x1u
#define AES_OP_DEC 0x2u
#define AES_MODE_ECB 0x1u

// FIPS-197 C.1 AES-128 known answer, packed little-endian per 32-bit word.
static const uint32_t kAesKey128[4] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c};
static const uint32_t kAesPt[4] = {0x33221100, 0x77665544, 0xbbaa9988, 0xffeeddcc};
static const uint32_t kAesCtExp[4] = {0xd8e0c469, 0x30047b6a, 0x80b7cdd8, 0x5ac5b470};
static const uint32_t kAesZeroIv[4] = {0, 0, 0, 0};

// SRAM staging area for the AES round trip.
#define AES_SRAM_PT (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x400u)
#define AES_SRAM_CT (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x410u)
#define AES_SRAM_RT (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x420u)

static void sram_store_block(uint32_t addr, const uint32_t blk[4]) {
    volatile uint32_t *p = (volatile uint32_t *)addr;
    for (int i = 0; i < 4; i++) p[i] = blk[i];
    __asm__ volatile("fence" ::: "memory");
}

static void sram_load_block(uint32_t addr, uint32_t blk[4]) {
    volatile uint32_t *p = (volatile uint32_t *)addr;
    __asm__ volatile("fence" ::: "memory");
    for (int i = 0; i < 4; i++) blk[i] = p[i];
}

// One AES-128-ECB pass with SRAM on both the input and the output path, so a
// broken CPU load or store fails it.
static int aes_ecb_via_sram(uint32_t op, uint32_t src_addr, uint32_t dst_addr, uint32_t out[4]) {
    uint32_t in[4];
    sram_load_block(src_addr, in);

    if (wait_for_idle() != 0) return 1;
    if (configure_aes_full(op, AES_MODE_ECB, 0x1u, kAesKey128, 4, NULL, kAesZeroIv, 0x0) != 0)
        return 2;
    if (wait_for_input_ready() != 0) return 3;
    write_data_in(in);
    if (wait_for_output_valid() != 0) return 4;
    read_data_out(out);

    sram_store_block(dst_addr, out);
    return 0;
}

// Compare one HMAC SHA-256 against an independent software SHA-256 golden.
// ``chk`` is the VPLAN checker id printed on the [PASS] line.
static int hmac_check(const char *chk, const char *name, const uint8_t *msg, uint32_t len) {
    uint32_t hw[8];
    int rc = sep_hmac_sha256(msg, len, hw);
    if (rc != 0) {
        sep_mbx_puts("[FAIL] ");
        sep_mbx_puts(chk);
        sep_mbx_puts(" ");
        sep_mbx_puts(name);
        sep_mbx_puts(rc == 1   ? " HMAC timeout\n"
                     : rc == 2 ? " HMAC ERR_CODE!=0\n"
                               : " HMAC done RW1C did not clear\n");
        return 1;
    }

    uint8_t sw[32];
    SHA256_CTX ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, (const BYTE *)msg, len);
    sha256_final(&ctx, sw);

    if (memcmp(hw, sw, 32) != 0) {
        sep_mbx_puts("[FAIL] ");
        sep_mbx_puts(chk);
        sep_mbx_puts(" ");
        sep_mbx_puts(name);
        sep_mbx_puts(" HMAC digest != SW SHA-256 (hw[0]=");
        sep_mbx_puthex(hw[0]);
        sep_mbx_putc('\n');
        return 1;
    }
    sep_mbx_puts("[PASS] ");
    sep_mbx_puts(chk);
    sep_mbx_puts(": ");
    sep_mbx_puts(name);
    sep_mbx_puts(" HMAC == SW SHA-256\n");
    return 0;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the mailbox window
    sep_mbx_puts("SEP HMAC/KMAC crypto smoke test\n");

    // --- HMAC: three messages vs independent software SHA-256 goldens. ---
    static const uint8_t msg_empty[] = "";
    static const uint8_t msg_abc[] = "abc";
    static const uint8_t msg_hello[] = "Hello OTBN.";
    int hmac_errors = 0;
    hmac_errors += hmac_check("CHK-HMAC-EMPTY", "empty", msg_empty, 0);
    hmac_errors += hmac_check("CHK-HMAC-SHORT", "abc", msg_abc, 3);
    hmac_errors += hmac_check("CHK-HMAC-MULTI", "Hello OTBN.", msg_hello, 11);
    errors += hmac_errors;

    // --- KMAC: SW-entropy masked hash; completion + no-error + non-degenerate. ---
    uint32_t kdig[8];
    int krc = sep_kmac128_sw_smoke(kdig);
    if (krc != 0) {
        sep_mbx_puts("[FAIL] KMAC rc=");
        sep_mbx_puthex((uint32_t)krc);
        sep_mbx_puts(" (1=idle-to,2=done-to,3=err_code,4=rw1c)\n");
        errors++;
    } else {
        uint32_t acc = 0;
        for (int i = 0; i < 8; i++) {
            acc |= kdig[i];
        }
        if (acc == 0) {
            sep_mbx_puts("[FAIL] KMAC unmasked digest all-zero (degenerate)\n");
            errors++;
        } else {
            sep_mbx_puts("[PASS] CHK-KMAC-LIVE: KMAC done, ERR_CODE=0, digest "
                         "nonzero kdig[0]=");
            sep_mbx_puthex(kdig[0]);
            sep_mbx_putc('\n');
            if (hmac_errors == 0) {
                sep_mbx_puts("[PASS] CHK-RW1C: HMAC and KMAC done bits cleared\n");
            }
        }
    }

    // --- AES-128-ECB round trip through SRAM on the CPU-owned path. ---
    // AES masking reseeds its PRNG from EDN, so the engine never becomes idle
    // unless the entropy stack runs. Only this leg needs it. The bring-up is
    // idempotent: if the boot gate is already open it enables EDN and returns.
    int entropy_rc = sep_entropy_bringup();
    if (entropy_rc != SEP_ENTROPY_OK) {
        sep_mbx_puts("[FAIL] entropy bring-up rc=");
        sep_mbx_puthex((uint32_t)entropy_rc);
        sep_mbx_puts(" (-1=main_sm alert, -2=boot gate timeout); AES cannot run\n");
        errors++;
    } else if (sep_aes_sw_reset_release() != 0) {
        sep_mbx_puts("[FAIL] AES software reset did not release\n");
        errors++;
    } else {
        sram_store_block(AES_SRAM_PT, kAesPt);

        uint32_t ct[4];
        int rc = aes_ecb_via_sram(AES_OP_ENC, AES_SRAM_PT, AES_SRAM_CT, ct);
        if (rc != 0) {
            sep_mbx_puts("[FAIL] AES encrypt leg rc=");
            sep_mbx_puthex((uint32_t)rc);
            sep_mbx_puts(" (1=idle-to,2=cfg,3=in-rdy-to,4=out-vld-to)\n");
            errors++;
        } else if (compare_block(ct, kAesCtExp, "CHK-CPU-AES-ENC") != 0) {
            // compare_block prints the mismatching word.
            sep_mbx_puts("[FAIL] CHK-CPU-AES-ENC ciphertext != FIPS-197 C.1 vector\n");
            errors++;
        } else {
            sep_mbx_puts("[PASS] CHK-CPU-AES-ENC: SRAM-staged plaintext encrypted to the "
                         "FIPS-197 C.1 ciphertext\n");

            uint32_t rt[4];
            rc = aes_ecb_via_sram(AES_OP_DEC, AES_SRAM_CT, AES_SRAM_RT, rt);
            if (rc != 0) {
                sep_mbx_puts("[FAIL] AES decrypt leg rc=");
                sep_mbx_puthex((uint32_t)rc);
                sep_mbx_putc('\n');
                errors++;
            } else {
                // Compare against the plaintext re-read from SRAM, not the
                // firmware constant, so the CPU load stays on the checked path.
                uint32_t pt_back[4];
                sram_load_block(AES_SRAM_PT, pt_back);
                if (compare_block(rt, pt_back, "CHK-CPU-AES-RT") != 0) {
                    sep_mbx_puts("[FAIL] CHK-CPU-AES-RT recovered block != SRAM plaintext\n");
                    errors++;
                } else {
                    sep_mbx_puts("[PASS] CHK-CPU-AES-RT: decrypt of the SRAM ciphertext "
                                 "recovered the SRAM plaintext\n");
                }
            }
        }
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: HMAC 3/3 == SW SHA-256 + KMAC SW-entropy smoke + AES-128-ECB "
                     "SRAM round trip vs FIPS-197 C.1; both done-IRQ RW1C cleared\n");
    }
    return errors;
}
