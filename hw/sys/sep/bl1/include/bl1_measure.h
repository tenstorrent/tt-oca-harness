/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// The SMC BL1 measurement record and the soft-PCR extend, which follows the SEP ROM's
// construction: pcr = SHA256(pcr || SHA256(record)).

#pragma once

#include <stdint.h>

#include "bl1_result.h"

#define BL1_DIGEST_BYTES 32u
#define BL1_RECORD_BYTES 76u

#define BL1_RECORD_KIND_STAGED 1u
#define BL1_RECORD_KIND_FAILURE 2u

struct bl1_smc_record {
    char type[16];
    uint64_t load_addr;
    uint64_t entry_point;
    uint32_t length;
    uint32_t kind;
    uint8_t digest[BL1_DIGEST_BYTES]; // the staged image's SHA-256; zero for a failure record
    uint32_t error;                   // the failure's SEP_BL1_ERR_* value; zero when staged
};

// Little-endian layout: type @0x00, load_addr @0x10, entry_point @0x18, length @0x20,
// kind @0x24, digest @0x28, error @0x48.
void bl1_record_serialize(const struct bl1_smc_record *rec, uint8_t out[BL1_RECORD_BYTES]);

// Returns 0 on success, as the SEP ROM's sha256() does.
typedef int (*bl1_sha256_fn)(const uint8_t *data, uint32_t len, uint8_t *digest);

bl1_result_t bl1_pcr_extend(uint8_t pcr[BL1_DIGEST_BYTES], const uint8_t *record, uint32_t len,
                            bl1_sha256_fn sha256);
