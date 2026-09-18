/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

printf("NIST Known Answer Test #1 - encrypt and then decrypt\n");

/*
KEY = 00000000000000000000000000000000
IV = 00000000000000000000000000000000
PLAINTEXT = 6a84867cd77e12ad07ea1be895c53fa3
CIPHERTEXT = 732281c0a0aab8f7a54a0c67a0c45ecf
*/
aes_pt[0] = swap_bytes_uint32(0x6a84867c);
aes_pt[1] = swap_bytes_uint32(0xd77e12ad);
aes_pt[2] = swap_bytes_uint32(0x07ea1be8);
aes_pt[3] = swap_bytes_uint32(0x95c53fa3);

aes_ct_expect[0] = 0x732281c0;
aes_ct_expect[1] = 0xa0aab8f7;
aes_ct_expect[2] = 0xa54a0c67;
aes_ct_expect[3] = 0xa0c45ecf;

memset(aes_iv, 0, sizeof(aes_iv));   // IV not used in ECB mode
memset(aes_key, 0, sizeof(aes_key)); // key = 0 in this test

printf("\n----------------------------------------------------------------\n");
printf("INFO: Encrypt plaintext to plaintext\n");

// Step 1: Wait for idle
printf("[Step 1] Waiting for AES idle\n");
if (wait_for_idle() != 0) return -1;
print_status("Ready. Go!\n");

// Step 2: Configure AES for AES-128 ECB encryption, automatic mode
printf("\n[Step 2] Configuring AES (AES-128 ECB Encryption, Automatic mode)\n");
printf("  AUTOMATIC MODE: AES will start automatically when DATA_IN is fully written\n");

aes_ctrl.w = 0;
aes_ctrl.f.OPERATION = AES_ENC;
aes_ctrl.f.MODE = AES_ECB;
aes_ctrl.f.KEY_LEN = AES_KEY_128;
aes_ctrl.f.SIDELOAD = 0; // Use SW key (deprecated, DV only)
aes_ctrl.f.MANUAL_OPERATION = AES_AUTO;

WRITE_REG(OCH_SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, aes_ctrl.w);
WRITE_REG(OCH_SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, aes_ctrl.w);

// Step 3: Wait for idle before writing key
if (wait_for_idle() != 0) return -1;

// Step 4: Write key shares (deprecated SW path for DV)
printf("\n[Step 3] Writing key (256-bit in two shares)\n");
printf("  Actual key = KEY_SHARE0 XOR KEY_SHARE1\n");
for (int i = 0; i < 8; i++) {
    WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), aes_key[i]);
    WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0x0);
}

// Step 5: Wait for idle and write IV (required for CBC mode)
if (wait_for_idle() != 0) return -1;

printf("\n[Step 4] Writing IV (not required for ECB mode)\n");
for (int i = 0; i < 4; i++) {
    WRITE_REG(OCH_SEP_TOP_AES_IV_BASE_ADDR(i), aes_iv[i]);
}

// Step 6: Wait for INPUT_READY
printf("\n[Step 5] Waiting for INPUT_READY before first block\n");
if (wait_for_input_ready() != 0) return -1;
print_status("  Ready for first block");

printf("[Block %d] Writing plaintext (4 x 32-bit registers)\n", 0);
printf("  As soon as all 4 DATA_IN registers written, AES starts automatically!\n");
for (int i = 0; i < 4; i++) {
    WRITE_REG(OCH_SEP_TOP_AES_DATA_IN_BASE_ADDR(i), aes_pt[i]);
}

printf("[Block %d] Waiting for OUTPUT_VALID (encryption completes automatically)\n", 0);
if (wait_for_output_valid() != 0) return -1;

for (int i = 0; i < 4; i++) {
    aes_ct[i] = swap_bytes_uint32(READ_REG(OCH_SEP_TOP_AES_DATA_OUT_BASE_ADDR(0) + 4 * i));
    printf("Endian converted ciphertext (bytes swapped) AES_DATA_OUT[%d]: 0x%08x\n", i, aes_ct[i]);
    if (aes_ct[i] != aes_ct_expect[i]) {
        error_mismatch++;
        printf("ERROR: encryption data out mismatch FAIL. Expected %08x\n", aes_ct_expect[i]);
    } else {
        printf("INFO: ECB encryption PASSED\n");
    }
}

printf("\n----------------------------------------------------------------\n");
printf("INFO: Decrypt ciphertext back to plaintext\n");

// Step 1: Wait for idle
printf("[Step 1] Waiting for AES idle\n");
if (wait_for_idle() != 0) return -1;
print_status("Ready. Go!");

// Step 2: Configure AES for AES-128 ECB encryption, automatic mode
printf("\n[Step 2] Configuring AES (AES-128 ECB Encryption, Automatic mode)\n");
printf("  AUTOMATIC MODE: AES will start automatically when DATA_IN is fully written\n");

aes_ctrl.f.OPERATION = AES_DEC;
WRITE_REG(OCH_SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, aes_ctrl.w);
WRITE_REG(OCH_SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, aes_ctrl.w);

// Step 3: Wait for idle before writing key
if (wait_for_idle() != 0) return -1;

/// NOTE: The OpenTitan AES expects the key to be reloaded whenever the control register is
/// updated; without the reload the following decryption hangs.

// Step 4: Write key shares (deprecated SW path for DV)
printf("\n[Step 3] Writing key (256-bit in two shares)\n");
printf("  Actual key = KEY_SHARE0 XOR KEY_SHARE1\n");
for (int i = 0; i < 8; i++) {
    WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), aes_key[i]);
    WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0x0);
}
printf("\n[Step 4] Skip writing IV\n");

// Step 6: Wait for INPUT_READY
printf("\n[Step 5] Waiting for INPUT_READY before first block\n");
if (wait_for_input_ready() != 0) return -1;
print_status("  Ready for first block");

printf("[Block %d] Writing ciphertext (4 x 32-bit registers)\n", 0);
printf("  As soon as all 4 DATA_IN registers written, AES starts automatically!\n");
for (int i = 0; i < 4; i++) {
    printf("DEBUG: data in %08x\n", aes_ct_expect[i]);
    WRITE_REG(OCH_SEP_TOP_AES_DATA_IN_BASE_ADDR(i), swap_bytes_uint32(aes_ct_expect[i]));
}

printf("[Block %d] Waiting for OUTPUT_VALID (decryption completes automatically)\n", 0);
if (wait_for_output_valid() != 0) return -1;

for (int i = 0; i < 4; i++) {
    regval = READ_REG(OCH_SEP_TOP_AES_DATA_OUT_BASE_ADDR(0) + 4 * i);
    printf("ciphertext AES_DATA_OUT[%d]: 0x%08x\n", i, regval);
    if (regval != aes_pt[i]) {
        error_mismatch++;
        printf("ERROR: decryption data out mismatch. Expected %08x\n", aes_pt[i]);
    } else {
        printf("INFO: ECB decryption passed\n");
    }
}
