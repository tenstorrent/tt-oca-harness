// SPDX-License-Identifier: Apache-2.0
//
// OSS RSA-verify stub for the SEP boot ROM (non-secure ROM boot test).
//
// The production rsa_verify.c runs an RSA-3072 signature check on the OTBN
// coprocessor. Non-secure boot (secure_boot=0) NEVER calls rsa_3072_verify()
// (rom_main gates it behind get_bl0_state()->secure_boot), so for the OSS
// non-secure subset we stub it out. This drops the entire OTBN app / OTBN
// assembler toolchain dependency from the OSS build. Restore the real driver
// when secure boot is brought up on the OSS flow.

#include <stdint.h>

#include "rsa_verify.h"

int rsa_3072_verify(const uint8_t *digest, const uint8_t *signature, const uint8_t *modulus) {
    (void)digest;
    (void)signature;
    (void)modulus;
    // Never reached in non-secure boot; fail closed if a secure path calls it.
    return 1;
}
