/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "bl1_measure.h"

#include "sep_bl1_status.h"

static void put_le(uint8_t *out, uint64_t v, unsigned bytes) {
    for (unsigned i = 0; i < bytes; i++) out[i] = (uint8_t)(v >> (8u * i));
}

void bl1_record_serialize(const struct bl1_smc_record *rec, uint8_t out[BL1_RECORD_BYTES]) {
    for (unsigned i = 0; i < 16u; i++) out[i] = (uint8_t)rec->type[i];
    put_le(out + 0x10, rec->load_addr, 8);
    put_le(out + 0x18, rec->entry_point, 8);
    put_le(out + 0x20, rec->length, 4);
    put_le(out + 0x24, rec->kind, 4);
    for (unsigned i = 0; i < BL1_DIGEST_BYTES; i++) out[0x28 + i] = rec->digest[i];
    put_le(out + 0x48, rec->error, 4);
}

bl1_result_t bl1_pcr_extend(uint8_t pcr[BL1_DIGEST_BYTES], const uint8_t *record, uint32_t len,
                            bl1_sha256_fn sha256) {
    uint8_t buf[2u * BL1_DIGEST_BYTES];
    uint8_t next[BL1_DIGEST_BYTES];
    for (unsigned i = 0; i < BL1_DIGEST_BYTES; i++) buf[i] = pcr[i];
    if (sha256(record, len, buf + BL1_DIGEST_BYTES) != 0) return SEP_BL1_ERR_STAGE_VERIFY;
    if (sha256(buf, sizeof buf, next) != 0) return SEP_BL1_ERR_STAGE_VERIFY;
    for (unsigned i = 0; i < BL1_DIGEST_BYTES; i++) pcr[i] = next[i];
    return BL1_OK;
}
