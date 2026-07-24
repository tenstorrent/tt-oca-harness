// SPDX-License-Identifier: Apache-2.0
//
// OSS OTBN-driver stub for the SEP boot ROM (non-secure ROM boot test).
//
// The production otbn_driver.c loads and runs the RSA-3072 OTBN application used
// by secure-boot signature verification. Non-secure boot never uses OTBN, so the
// OSS non-secure subset stubs these entry points to avoid pulling in the OTBN
// app (which needs the OTBN assembler toolchain to generate). Restore the real
// driver when secure boot is brought up on the OSS flow.

#include <stdint.h>

#include "otbn_driver.h"

int otbn_init(void) {
    return 1;
}

int otbn_load_rsa_app(void) {
    return 1;
}

void otbn_dmem_write(uint32_t byte_offset, const uint32_t *data, uint32_t word_count) {
    (void)byte_offset;
    (void)data;
    (void)word_count;
}

void otbn_dmem_read(uint32_t byte_offset, uint32_t *data, uint32_t word_count) {
    (void)byte_offset;
    (void)data;
    (void)word_count;
}

int otbn_execute(void) {
    return 1;
}
