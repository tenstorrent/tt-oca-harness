/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_aes_init.h"
#include "aes_util.c"

/*
NIST Known Answer Tests (subset)
-----------------------------------------------------
KEY = 00000000000000000000000000000000
IV = 00000000000000000000000000000000
PLAINTEXT = 6a84867cd77e12ad07ea1be895c53fa3
CIPHERTEXT = 732281c0a0aab8f7a54a0c67a0c45ecf
-----------------------------------------------------
KEY = 9dc2c84a37850c11699818605f47958c
IV = 256953b2feab2a04ae0180d8335bbed6
PLAINTEXT = 2e586692e647f5028ec6fa47a55a2aab
CIPHERTEXT = 1b1ebd1fc45ec43037fd4844241a437f
-----------------------------------------------------
*/

int main(void) {
    uint32_t error_mismatch = 0;
    uint32_t regval;

    sep_outbound_filter_init();

    if (sep_aes_sw_reset_release() != 0) {
        test_fail(1);
        while (1) __asm__("wfi");
    }

    uint32_t aes_key[8] = {[0 ... 7] = 0xABBAC001};
    uint32_t aes_pt[4] = {[0] = 0xCAFEBABE, [1] = 0xC001D00D, [2] = 0xC001D00D, [3] = 0xC001D00D};
    uint32_t aes_ct[4] = {[0 ... 3] = 0xFFFFFFFF};
    uint32_t aes_ct_expect[4] = {[0 ... 3] = 0xFFFFFFFF};
    uint32_t aes_iv[4] = {[0 ... 3] = 0xDEADBEEF};

    aes__CTRL_SHADOWED_t aes_ctrl = {.w = 0};

    printf("\n----------------------------------------------------------------\n");
    printf("AES CSR read/write - start\n");
    printf("----------------------------------------------------------------\n");
// AES_CTRL
// [1:0]   - AES_ENC: 2'b01 (default), AES_DEC: 2'b10
// [7:2]   - AES_ECB: 6'b000001, AES_CBC: 6'b000010, AES_CFB: 6'b000100,
//           AES_OFB: 6'b001000, AES_CTR: 6'b010000, AES_NONE: 6'b100000 (default),
// [10:8]  - 128: 3'b001, 192: 3'b010, 256: 3'b100 (default)
// [11]    - SIDELOAD: no: 0 (default), yes: 1
// [14:12] - PRNG_RESEED_RATE
// [15]    - MANUAL: no: 0 (default), yes: 1  (needs the trigger to be asserted)
#define AES_ENC 0x1
#define AES_DEC 0x2
#define AES_ECB 0x1
#define AES_KEY_128 0x1
#define AES_KEY_SDLD 0x1
#define AES_KEY_NOSDLD 0x0
#define AES_AUTO 0x0

    aes_ctrl.f.OPERATION = AES_ENC;
    aes_ctrl.f.MODE = AES_ECB;
    aes_ctrl.f.KEY_LEN = AES_KEY_128;
    aes_ctrl.f.SIDELOAD = AES_KEY_NOSDLD; // Use SW key (deprecated, DV only)
    aes_ctrl.f.MANUAL_OPERATION = AES_AUTO;

    printf("INFO: Wait for AES to go idle before proceeding with configuration...\n");
    if (wait_for_idle() != 0) return -1;
    printf("INFO: Idle state - let's write some CSRs");

    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, aes_ctrl.w);
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, aes_ctrl.w);

    // Write key via KEY_SHARE0/1 (deprecated SW path for DV)
    for (int i = 0; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), aes_key[i]);
        WRITE_REG(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0);
    }
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_DATA_IN_BASE_ADDR(i), aes_pt[i]);
        printf("DEBUG: write pt[%d]: %08x\n", i, aes_pt[i]);
    }
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_IV_BASE_ADDR(0) + 4 * i, aes_iv[i]);
        printf("DEBUG: write iv[%d]: %08x\n", i, aes_iv[i]);
    }

    print_registers();
    printf("AES CSR read/write test - done\n");

#include "aes_test1.h"

    printf("INFO: end of aes_sanity test\n");
    printf("\n----------------------------------------------------------------\n");

    // Require FW to explicitly signal PASS/FAIL to the testbench/cocotb.
    if (error_mismatch > 0) {
        printf("FAIL: aes_sanity data out mismatches: %d\n", error_mismatch);
        test_fail(1);
    } else {
        printf("PASS: aes_sanity\n");
        test_pass(0);
    }

    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
