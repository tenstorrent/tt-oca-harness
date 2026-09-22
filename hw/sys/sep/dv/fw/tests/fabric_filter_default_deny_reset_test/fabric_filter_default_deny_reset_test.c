/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Fabric Filter Default Deny Reset Test
 *
 * Verifies reset/default filter configuration and that a narrow programmed
 * window can be restored back to the disabled default state.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define TEST_FILTER_IDX 14u
#define TEST_OUT_FILTER_IDX 31u

#define MAILBOX_0_APERTURE_SIZE SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_SIZE

static int check_eq32(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);

    printf("%s: 0x%08x expected 0x%08x - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

static uint32_t inbound_addr(uint32_t base) {
    return base + (TEST_FILTER_IDX * SEP_TOP_INBOUND_FILTER_CTRL_STRIDE);
}

static void write64_split(uint32_t addr, uint64_t value) {
    WRITE_REG(addr, (uint32_t)value);
    WRITE_REG(addr + 4, (uint32_t)(value >> 32));
}

int main(void) {
    int pass = 1;
    uint32_t in_cfg_addr = inbound_addr(SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0));
    uint32_t in_start_addr = inbound_addr(SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(0));
    uint32_t in_end_addr = inbound_addr(SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(0));
    uint32_t out_cfg_addr = SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0) +
                            (TEST_OUT_FILTER_IDX * SEP_TOP_OUTBOUND_FILTER_CTRL_STRIDE);
    uint32_t cfg_lo;
    uint32_t cfg_hi;
    uint32_t programmed_cfg;

    sep_outbound_filter_init();

    printf("\n==============================================\n");
    printf("Fabric Filter Default Deny Reset Test\n");
    printf("==============================================\n\n");

    cfg_lo = READ_REG(in_cfg_addr);
    cfg_hi = READ_REG(in_cfg_addr + 4);
    printf("Inbound filter[%u] default cfg_lo=0x%08x cfg_hi=0x%08x\n", TEST_FILTER_IDX, cfg_lo,
           cfg_hi);
    if ((cfg_lo & FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm) != 0) {
        printf("Inbound filter default entry_enabled should be 0\n");
        pass = 0;
    }
    if (cfg_hi != 0) {
        printf("Inbound filter default high word should be 0\n");
        pass = 0;
    }

    cfg_lo = READ_REG(out_cfg_addr);
    cfg_hi = READ_REG(out_cfg_addr + 4);
    printf("Outbound filter[%u] default cfg_lo=0x%08x cfg_hi=0x%08x\n", TEST_OUT_FILTER_IDX, cfg_lo,
           cfg_hi);
    if ((cfg_lo & FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm) != 0) {
        printf("Outbound filter default entry_enabled should be 0\n");
        pass = 0;
    }
    if (cfg_hi != 0) {
        printf("Outbound filter default high word should be 0\n");
        pass = 0;
    }

    write64_split(in_start_addr, SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR);
    write64_split(in_end_addr,
                  SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR + MAILBOX_0_APERTURE_SIZE - 1u);

    programmed_cfg =
        FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm |
        FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm | FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm |
        FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm;
    write64_split(in_cfg_addr, programmed_cfg);
    if (!check_eq32("Inbound filter programmed cfg", READ_REG(in_cfg_addr),
                    programmed_cfg | FILTER_CTRL__FILTER_CONFIG_reset)) {
        pass = 0;
    }

    write64_split(in_cfg_addr, FILTER_CTRL__FILTER_CONFIG_reset);
    write64_split(in_start_addr, FILTER_CTRL__START_ADDR_reset);
    write64_split(in_end_addr, FILTER_CTRL__END_ADDR_reset);

    cfg_lo = READ_REG(in_cfg_addr);
    if ((cfg_lo & FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm) != 0) {
        printf("Inbound filter restore did not clear addr_mode, cfg=0x%08x\n", cfg_lo);
        pass = 0;
    } else {
        printf("Inbound filter restored to disabled/default-deny posture - PASS\n");
    }

    if (pass) {
        printf("=== FABRIC FILTER DEFAULT DENY RESET TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== FABRIC FILTER DEFAULT DENY RESET TEST FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
