/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <string.h>

#include "bl1_handoff.h"
#include "oca_validator.h"
#include "sep_bl1_status.h"
#include "unit.h"

// The fixture bundle is laid out as the SEP ROM stages it: the manifest body at the SEP SRAM
// base, the payload immediately after it.
static uint8_t sram[64 * 1024];
static size_t sram_len;
static uint32_t payload_off;
static uint32_t payload_len;
static uint32_t sep_image_off;

static int load(void) {
    char path[512];
    snprintf(path, sizeof path, "%s/one.bin", UNIT_FIXTURE_DIR);
    sram_len = unit_read_file(path, sram, sizeof sram);
    oca_manifest_peek_t pk;
    oca_toc_info_t toc;
    oca_image_info_t img;
    if (sram_len == 0 || oca_peek_manifest(sram, sram_len, &pk) != OCA_OK) return 0;
    payload_off = (uint32_t)((pk.body_size + 7u) & ~(size_t)7u);
    if (oca_toc_info(sram + payload_off, sram_len - payload_off, &toc) != OCA_OK) return 0;
    if (oca_toc_image_at(sram + payload_off, sram_len - payload_off, 0, &img) != OCA_OK) return 0;
    payload_len = (uint32_t)toc.payload_length;
    sep_image_off = (uint32_t)(img.bytes - (sram + payload_off));
    return 1;
}

static struct bl0_state good_state(void) {
    struct bl0_state s;
    memset(&s, 0, sizeof s);
    s.start_magic = BL0_STATE_MAGIC;
    s.end_magic = BL0_STATE_MAGIC;
    s.size = sizeof s;
    s.boot_mode = BOOT_MODE_SECONDARY;
    s.sep_sram_manifest_addr = BL1_SEP_SRAM_MANIFEST_ADDR;
    s.bl1_image_src_addr = BL1_SEP_SRAM_MANIFEST_ADDR + payload_off + sep_image_off;
    return s;
}

static bl1_result_t check(const struct bl0_state *s, uint32_t avail, uint32_t *detail) {
    struct bl1_handoff out;
    *detail = 0;
    return bl1_check_handoff(s, sram, avail, &out, detail);
}

#define EXPECT_DETAIL(state, avail, want) \
    do { \
        uint32_t d_; \
        CHECK_EQ(check(&(state), (avail), &d_), SEP_BL1_ERR_HANDOFF); \
        CHECK_EQ(d_, (want)); \
    } while (0)

void test_handoff(void) {
    if (!load()) {
        printf("FAIL handoff fixture one.bin did not load\n");
        unit_failures++;
        return;
    }
    const uint32_t avail = (uint32_t)sram_len;
    struct bl0_state s;
    struct bl1_handoff out;
    uint32_t detail = 0;

    s = good_state();
    CHECK_EQ(bl1_check_handoff(&s, sram, avail, &out, &detail), BL1_OK);
    CHECK_EQ(out.manifest_addr, BL1_SEP_SRAM_MANIFEST_ADDR);
    CHECK_EQ(out.payload_addr, BL1_SEP_SRAM_MANIFEST_ADDR + payload_off);
    CHECK_EQ(out.payload_len, payload_len);
    CHECK(out.payload == sram + payload_off);

    s = good_state();
    s.start_magic ^= 1u;
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_MAGIC);
    s = good_state();
    s.end_magic = 0;
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_MAGIC);
    s = good_state();
    s.size = sizeof s - 4u;
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_SIZE);
    s = good_state();
    s.error_code = 1;
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_BL0_ERROR);
    s = good_state();
    s.boot_mode = BOOT_MODE_UNKNOWN;
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_BOOT_MODE);
    s = good_state();
    s.boot_mode = 9;
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_BOOT_MODE);
    s = good_state();
    s.sep_sram_manifest_addr += 0x1000u;
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_MANIFEST_ADDR);

    s = good_state();
    EXPECT_DETAIL(s, payload_off + 8u, BL1_HANDOFF_DETAIL_PAYLOAD);

    s = good_state();
    s.bl1_image_src_addr = BL1_SEP_SRAM_MANIFEST_ADDR + payload_off - 4u;
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_BL1_SOURCE);
    s = good_state();
    s.bl1_image_src_addr = BL1_SEP_SRAM_MANIFEST_ADDR + payload_off + payload_len;
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_BL1_SOURCE);

    uint8_t saved = sram[0];
    sram[0] ^= 0xFFu;
    s = good_state();
    EXPECT_DETAIL(s, avail, BL1_HANDOFF_DETAIL_MANIFEST);
    sram[0] = saved;
}
