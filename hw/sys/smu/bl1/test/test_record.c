/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <string.h>

#include "bl1_measure.h"
#include "host_sha256.h"
#include "unit.h"

#include "record_vectors.h"

static int failing_sha(const uint8_t *data, uint32_t len, uint8_t *digest) {
    (void)data;
    (void)len;
    (void)digest;
    return -1;
}

void test_record(void) {
    uint8_t raw[BL1_RECORD_BYTES];

    memset(raw, 0xEE, sizeof raw);
    bl1_record_serialize(&vec_staged, raw);
    CHECK(memcmp(raw, vec_staged_bytes, sizeof raw) == 0);

    memset(raw, 0xEE, sizeof raw);
    bl1_record_serialize(&vec_failure, raw);
    CHECK(memcmp(raw, vec_failure_bytes, sizeof raw) == 0);

    // The slot starts at zero and extends with the staged record, then the failure record.
    uint8_t pcr[BL1_DIGEST_BYTES] = {0};
    CHECK_EQ(bl1_pcr_extend(pcr, vec_staged_bytes, BL1_RECORD_BYTES, host_sha256), BL1_OK);
    CHECK(memcmp(pcr, vec_pcr_after_staged, sizeof pcr) == 0);
    CHECK_EQ(bl1_pcr_extend(pcr, vec_failure_bytes, BL1_RECORD_BYTES, host_sha256), BL1_OK);
    CHECK(memcmp(pcr, vec_pcr_after_failure, sizeof pcr) == 0);

    // A hash failure leaves the slot unchanged.
    uint8_t before[BL1_DIGEST_BYTES];
    memcpy(before, pcr, sizeof pcr);
    CHECK(bl1_pcr_extend(pcr, vec_staged_bytes, BL1_RECORD_BYTES, failing_sha) != BL1_OK);
    CHECK(memcmp(pcr, before, sizeof pcr) == 0);
}
