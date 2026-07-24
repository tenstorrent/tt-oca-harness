// SPDX-License-Identifier: Apache-2.0
//
// SEP HMAC + KMAC CPU crypto smoke firmware test (OSS port combining the OCAH
// hmac_test and kmac_test). Exercises the two OpenTitan crypto engines over the
// real CPU->fabric path on bare `sep` (both internal, CSR clocks always on).
//
// HMAC (SHA-256 mode, 0x1091_1000): hash three messages -- empty, "abc",
// "Hello OTBN." -- and compare each HW digest against an INDEPENDENT software
// SHA-256 (fw/drivers/sha256.c) computed over the same bytes. Also requires no
// done-timeout and HMAC ERR_CODE == 0. (OCAH hard-codes the three NIST vectors;
// computing them in firmware is an equivalent, self-contained golden.)
//
// KMAC (KMAC128/cSHAKE, 0x1091_3000): run a masked hash of "test" with a zero
// key using SOFTWARE entropy (no EDN), then check it reached done, ERR_CODE == 0,
// and the unmasked digest (share0 ^ share1) is non-zero.
//   Scope delta (documented, matches OCAH + the OSS VPLAN allowance): the KMAC
//   result is checked for completion / no-error / non-degenerate masking, NOT
//   against an exact KMAC/Keccak software reference (no bare-metal Keccak model
//   is ported). The HMAC side carries the exact-digest rigor. This is a "smoke".
//   The OSS port also FIXES the OCAH kmac entropy bug by using SW entropy mode
//   (see sep_kmac.h) so it cannot hang on an unseeded EDN.
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

// Compare one HMAC SHA-256 against an independent software SHA-256 golden.
static int hmac_check(const char *name, const uint8_t *msg, uint32_t len) {
    uint32_t hw[8];
    int rc = sep_hmac_sha256(msg, len, hw);
    if (rc != 0) {
        sep_mbx_puts("[FAIL] ");
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
        sep_mbx_puts(name);
        sep_mbx_puts(" HMAC digest != SW SHA-256 (hw[0]=");
        sep_mbx_puthex(hw[0]);
        sep_mbx_putc('\n');
        return 1;
    }
    sep_mbx_puts("[PASS] ");
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
    errors += hmac_check("empty", msg_empty, 0);
    errors += hmac_check("abc", msg_abc, 3);
    errors += hmac_check("Hello OTBN.", msg_hello, 11);

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
            sep_mbx_puts("[PASS] KMAC done, ERR_CODE=0, digest nonzero kdig[0]=");
            sep_mbx_puthex(kdig[0]);
            sep_mbx_putc('\n');
        }
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: HMAC 3/3 == SW SHA-256 + KMAC SW-entropy smoke; "
                     "both done-IRQ RW1C cleared\n");
    }
    return errors;
}
