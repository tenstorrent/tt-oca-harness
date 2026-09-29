// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP HMAC + KMAC CPU crypto smoke firmware test (OSS port combining the reference suite
// hmac_test and kmac_test). Exercises the two OpenTitan crypto engines over the
// real CPU->fabric path on bare `sep` (both internal, CSR clocks always on).
//
// HMAC (SHA-256 mode, 0x1091_1000): hash three messages -- empty, "abc",
// "Hello OTBN." -- and compare each HW digest against an INDEPENDENT software
// SHA-256 (fw/tests/common/sha256.c) computed over the same bytes. Also requires no
// done-timeout and HMAC ERR_CODE == 0. (reference suite hard-codes the three NIST vectors;
// computing them in firmware is an equivalent, self-contained golden.)
//
// KMAC (KMAC128/cSHAKE, 0x1091_3000): run a masked hash of "test" with a zero
// key using SOFTWARE entropy (no EDN), then check it reached done, ERR_CODE == 0,
// and the unmasked digest (share0 ^ share1) is non-zero.
//   Scope delta (matches the reference suite and the OSS VPLAN allowance): the KMAC
//   result is checked for completion / no-error / non-degenerate masking, NOT
//   against an exact KMAC/Keccak software reference (no bare-metal Keccak model
//   is ported). The HMAC side carries the exact-digest rigor. This is a "smoke".
//   KMAC uses SOFTWARE entropy (see sep_kmac.h) so the engine does not wait on EDN.
//
// main() returns the error count; start.S turns 0 -> PASS magic / non-zero ->
// FAIL magic on the 0x8000_0000 mailbox, which the boot scoreboard gates on.

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

// CTRL_SHADOWED encodings from the IP register specification
// (vendor/lowRISC/opentitan/upstream/hw/ip/aes/data/aes.hjson: OPERATION enum
// AES_ENC = 1 / AES_DEC = 2, MODE enum AES_ECB = 6'b00_0001). The generated
// header carries only the field mask and position, not the enum.
#define AES_OP_ENC 0x1u
#define AES_OP_DEC 0x2u
#define AES_MODE_ECB 0x1u

// FIPS-197 C.1 AES-128 known answer, packed little-endian per 32-bit word,
// the same convention the other AES firmware uses for its NIST anchor. This is
// a published input/output pair, not a value read back from the engine.
static const uint32_t kAesKey128[4] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c};
static const uint32_t kAesPt[4] = {0x33221100, 0x77665544, 0xbbaa9988, 0xffeeddcc};
static const uint32_t kAesCtExp[4] = {0xd8e0c469, 0x30047b6a, 0x80b7cdd8, 0x5ac5b470};
static const uint32_t kAesZeroIv[4] = {0, 0, 0, 0};

// SRAM staging area for the round trip. Clear of the HMAC/KMAC legs, which do
// not touch SRAM at all.
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

// One AES-128-ECB pass: take the input block FROM SRAM, run the engine, store
// the result back TO SRAM. The point of the leg is that SRAM is on the path in
// both directions, so a broken CPU store or load fails it even though the
// register-resident AXI walk would pass.
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

    sep_outbound_filter_init(); // open the 0x8000_0000 mailbox window
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

    // --- AES-128-ECB round trip through SRAM -----------------------------
    // The AXI leaf already walks the AES mode/key matrix from the testbench
    // master. What it cannot show is the CPU-owned path: firmware staging the
    // block in SRAM, handing it to the engine, and recovering it from SRAM.
    //
    // AES masking reseeds its PRNG from crypto-EDN, so STATUS.IDLE never clears
    // unless the entropy stack is running. The HMAC and KMAC legs above do not
    // need it -- KMAC is driven with software entropy -- so the bring-up is
    // here, next to the only consumer that depends on it. It is idempotent: if
    // the boot gate is already open it enables EDN and returns.
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
                // Compare against the plaintext re-read from SRAM, not against
                // the firmware constant: that keeps the CPU load on the path
                // the checker depends on.
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
