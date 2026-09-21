/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Fabric Alias Remap Cacheable Default Test
 *
 * Verifies cpu_ctrl alias defaults and a local alias remap entry's cacheable
 * attribute through the normal SEP firmware MMIO path.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

static int check_eq32(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);

    printf("%s: 0x%08x expected 0x%08x - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

static uint64_t read64_split(uint32_t addr) {
    uint64_t lo = READ_REG(addr);
    uint64_t hi = READ_REG(addr + 4);

    return lo | (hi << 32);
}

static void write64_split(uint32_t addr, uint64_t value) {
    WRITE_REG(addr, (uint32_t)value);
    WRITE_REG(addr + 4, (uint32_t)(value >> 32));
}

int main(void) {
    int pass = 1;
    uint64_t saved_start;
    uint64_t saved_end;
    uint64_t saved_attrs;
    uint64_t attrs;

    sep_outbound_filter_init();

    printf("\n====================================================\n");
    printf("Fabric Alias Remap Cacheable Default Test\n");
    printf("====================================================\n\n");

    if (!check_eq32("SEP_LOCAL_BASE_ADDR",
                    READ_REG(SEP_TOP_SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_BASE_ADDR),
                    SEP_CPU_CTRL__SEP_LOCAL_BASE_ADDR_reset)) {
        pass = 0;
    }
    if (!check_eq32("SEP_REGION_SIZE", READ_REG(SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR),
                    SEP_CPU_CTRL__SEP_REGION_SIZE_reset)) {
        pass = 0;
    }
    if (!check_eq32("SMU_GLOBAL_BASE_ADDR",
                    READ_REG(SEP_TOP_SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_BASE_ADDR),
                    SEP_CPU_CTRL__SMU_GLOBAL_BASE_ADDR_reset)) {
        pass = 0;
    }
    if (!check_eq32("SMU_REGION_SIZE", READ_REG(SEP_TOP_SEP_CPU_CTRL_SMU_REGION_SIZE_BASE_ADDR),
                    SEP_CPU_CTRL__SMU_REGION_SIZE_reset)) {
        pass = 0;
    }

    saved_start =
        read64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_START_BASE_ADDR(15));
    saved_end =
        read64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_END_BASE_ADDR(15));
    saved_attrs =
        read64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(15));

    printf("Alias entry 15 saved START=0x%016llx END=0x%016llx ATTRS=0x%016llx\n",
           (unsigned long long)saved_start, (unsigned long long)saved_end,
           (unsigned long long)saved_attrs);

    write64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_START_BASE_ADDR(15),
                  0x00000000C1F00000ULL);
    write64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_END_BASE_ADDR(15),
                  0x00000000C1F00FFFULL);

    attrs = (1ULL << 63);
    write64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(15),
                  attrs);
    if (!check_eq32(
            "Alias cacheable=0 attrs hi",
            READ_REG(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(15) +
                     4),
            (uint32_t)(attrs >> 32))) {
        pass = 0;
    }

    attrs = (1ULL << 63) | (1ULL << 62);
    write64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(15),
                  attrs);
    if (!check_eq32(
            "Alias cacheable=1 attrs hi",
            READ_REG(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(15) +
                     4),
            (uint32_t)(attrs >> 32))) {
        pass = 0;
    }

    write64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(15),
                  saved_attrs);
    write64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_END_BASE_ADDR(15),
                  saved_end);
    write64_split(SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_REGION_START_BASE_ADDR(15),
                  saved_start);

    if (pass) {
        printf("=== FABRIC ALIAS REMAP CACHEABLE DEFAULT TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== FABRIC ALIAS REMAP CACHEABLE DEFAULT TEST FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
