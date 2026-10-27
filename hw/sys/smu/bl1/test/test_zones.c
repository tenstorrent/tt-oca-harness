/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <string.h>

#include "bl1_zones.h"
#include "oca_validator.h"
#include "sep_bl1_status.h"
#include "smu_bl1_contract.h"
#include "unit.h"

static uint8_t fixture[64 * 1024];

static bl1_result_t image(uint64_t load, uint64_t len, uint64_t entry) {
    struct bl1_image_desc d = {.load_addr = load, .length = len, .entry_point = entry};
    return bl1_check_smc_image(&d);
}

static void image_checks(void) {
    const uint64_t win = SMU_BL1_IMAGE_WINDOW_START;
    const uint64_t win_end = SMU_BL1_IMAGE_WINDOW_END;

    CHECK_EQ(image(win, 1024, 0x40), BL1_OK);
    CHECK_EQ(image(win_end - 8, 8, 4), BL1_OK);
    CHECK_EQ(image(win, win_end - win, 0), BL1_OK);

    // Range: length, alignment, 4 GiB and wrap, checked before the entry point.
    CHECK_EQ(image(win, 0, 0), SEP_BL1_ERR_SMC_IMAGE_RANGE);
    CHECK_EQ(image(win, 6, 0), SEP_BL1_ERR_SMC_IMAGE_RANGE);
    CHECK_EQ(image(win + 4, 1024, 0), SEP_BL1_ERR_SMC_IMAGE_RANGE);
    CHECK_EQ(image(0x1C0080000ull, 1024, 0), SEP_BL1_ERR_SMC_IMAGE_RANGE);
    CHECK_EQ(image(UINT64_MAX - 7u, 16, 0), SEP_BL1_ERR_SMC_IMAGE_RANGE);
    CHECK_EQ(image(win, UINT64_MAX - 3u, 0), SEP_BL1_ERR_SMC_IMAGE_RANGE);
    CHECK_EQ(image(win, 0, 0x99), SEP_BL1_ERR_SMC_IMAGE_RANGE);

    // Entry point.
    CHECK_EQ(image(win, 1024, 1024), SEP_BL1_ERR_SMC_IMAGE_ENTRY);
    CHECK_EQ(image(win, 1024, 2), SEP_BL1_ERR_SMC_IMAGE_ENTRY);
    CHECK_EQ(image(win, 1024, UINT64_MAX), SEP_BL1_ERR_SMC_IMAGE_ENTRY);

    // Image window.
    CHECK_EQ(image(win - 8, 16, 0), SEP_BL1_ERR_SMC_IMAGE_ZONE);
    CHECK_EQ(image(win_end - 8, 16, 0), SEP_BL1_ERR_SMC_IMAGE_ZONE);
    CHECK_EQ(image(0xC0160000ull, 1024, 0), SEP_BL1_ERR_SMC_IMAGE_ZONE);
    CHECK_EQ(image(SMU_BL1_RW_WINDOW_START, 1024, 0), SEP_BL1_ERR_SMC_IMAGE_ZONE);
}

static bl1_result_t find_in(const char *name, struct bl1_image_desc *d) {
    char path[512];
    snprintf(path, sizeof path, "%s/%s", UNIT_FIXTURE_DIR, name);
    size_t n = unit_read_file(path, fixture, sizeof fixture);
    oca_manifest_peek_t pk;
    if (n == 0 || oca_peek_manifest(fixture, n, &pk) != OCA_OK || pk.body_size >= n) {
        printf("FAIL fixture %s is not a manifest bundle\n", name);
        unit_failures++;
        return 0;
    }
    return bl1_find_smc_image(fixture + pk.body_size, n - pk.body_size, d);
}

static void toc_checks(void) {
    struct bl1_image_desc d;
    memset(&d, 0, sizeof d);
    CHECK_EQ(find_in("one.bin", &d), BL1_OK);
    CHECK_EQ(d.load_addr, 0xC0080000u);
    CHECK_EQ(d.length, 1024u);
    CHECK_EQ(d.entry_point, 0x40u);
    CHECK(d.bytes != NULL && d.hash != NULL);
    if (d.bytes != NULL) CHECK_EQ(d.bytes[7], (7u * 7u) & 0xFFu);

    CHECK_EQ(find_in("none.bin", &d), SEP_BL1_ERR_SMC_IMAGE_MISSING);
    CHECK_EQ(find_in("two.bin", &d), SEP_BL1_ERR_SMC_IMAGE_DUPLICATE);
}

static bl1_result_t zone(uint32_t status, uint32_t start, uint32_t start_hi, uint32_t size,
                         uint32_t size_hi, uint32_t *warn) {
    struct bl1_smc_zone_regs r = {.status_lo = status,
                                  .start_off_lo = start,
                                  .start_off_hi = start_hi,
                                  .size_lo = size,
                                  .size_hi = size_hi};
    *warn = 0;
    return bl1_check_smc_zone(&r, warn);
}

static void zone_checks(void) {
    const uint32_t ready = SMU_BL1_STATUS_SRAM_INIT | SMU_BL1_STATUS_BUFFER_READY;
    const uint32_t start = SMU_BL1_SEP_ZONE_START - SMU_BL1_SMC_SRAM_BASE;
    const uint32_t size = SMU_BL1_SEP_ZONE_END - SMU_BL1_SEP_ZONE_START;
    uint32_t w;

    CHECK_EQ(zone(ready, start, 0, size, 0, &w), BL1_OK);
    CHECK_EQ(w, 0u);

    CHECK_EQ(zone(SMU_BL1_STATUS_BUFFER_READY, start, 0, size, 0, &w),
             SEP_BL1_ERR_SMC_ZONE_UNPUBLISHED);

    CHECK_EQ(zone(ready, start, 1, size, 0, &w), SEP_BL1_ERR_SMC_ZONE_INVALID);
    CHECK_EQ(zone(ready, start, 0, size, 1, &w), SEP_BL1_ERR_SMC_ZONE_INVALID);
    CHECK_EQ(zone(ready, 0xFFFFFFF0u, 0, 0x20, 0, &w), SEP_BL1_ERR_SMC_ZONE_INVALID);
    CHECK_EQ(zone(ready, start, 0, SMU_BL1_SMC_SRAM_SIZE, 0, &w), SEP_BL1_ERR_SMC_ZONE_INVALID);
    CHECK_EQ(zone(ready, SMU_BL1_SMC_SRAM_SIZE, 0, 8, 0, &w), SEP_BL1_ERR_SMC_ZONE_INVALID);

    CHECK_EQ(zone(ready, start, 0, size - 8, 0, &w), SEP_BL1_ERR_SMC_ZONE_TOO_SMALL);
    CHECK_EQ(zone(ready, start + 8, 0, size - 8, 0, &w), SEP_BL1_ERR_SMC_ZONE_TOO_SMALL);

    CHECK_EQ(zone(ready, start - 0x400, 0, size + 0x800, 0, &w), BL1_OK);
    CHECK_EQ(w, BL1_WARN_ZONE_MISMATCH);
}

void test_zones(void) {
    image_checks();
    toc_checks();
    zone_checks();
}
