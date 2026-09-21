/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Fabric Mailbox ISS Lock Reset Test
 *
 * Uses the CSR-visible ISS mailbox policy:
 * mailbox data/IRQ status plus inbound-filter src_id and locked behavior.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define TEST_FILTER_IDX 15u

#define MAILBOX_0_APERTURE_SIZE SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_SIZE

static int check_eq32(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);

    printf("%s: 0x%08x expected 0x%08x - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

static int check_bit(const char *name, uint32_t value) {
    printf("%s: %u - %s\n", name, value, value ? "PASS" : "FAIL");
    return value ? 1 : 0;
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
    uint32_t cfg_addr = inbound_addr(SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0));
    uint32_t start_addr = inbound_addr(SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(0));
    uint32_t end_addr = inbound_addr(SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(0));
    uint32_t cfg_src3;
    uint32_t cfg_rb;
    uint32_t cfg_hi;
    axil_mailbox__STATUS_t status;
    axil_mailbox__IRQS_t irqs;
    axil_mailbox__CTRL_t ctrl = {.f.wflush = 1, .f.rflush = 1};

    sep_outbound_filter_init();

    printf("\n==========================================\n");
    printf("Fabric Mailbox ISS Lock Reset Test\n");
    printf("==========================================\n\n");

    /* CLOCK_GATE_CTRL is a reserved placeholder;
     * mailbox/filter clocks are always on, so no ungate step is required. */

    WRITE_REG(SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_BASE_ADDR, (uint32_t)ctrl.w);
    WRITE_REG(SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR, 0x7);

    WRITE_REG(SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR, 0xA5A50053);
    WRITE_REG(SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR + 4, 0x5A5A0053);

    status.w = READ_REG(SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR);
    if (!check_bit("Mailbox write-level-above-threshold", status.f.write_level_above_thresh)) {
        pass = 0;
    }

    irqs.w = READ_REG(SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR);
    if (!check_bit("Mailbox wtirq", irqs.f.wtirq)) {
        pass = 0;
    }

    write64_split(start_addr, SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR);
    write64_split(end_addr, SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR +
                                MAILBOX_0_APERTURE_SIZE - 1u);

    cfg_src3 =
        FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm |
        FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm | FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm |
        FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm | (3u << FILTER_CTRL__FILTER_CONFIG__SRC_ID_bp);
    write64_split(cfg_addr, cfg_src3);
    cfg_rb = READ_REG(cfg_addr);
    if (!check_eq32("Inbound filter src_id=3 cfg", cfg_rb,
                    cfg_src3 | FILTER_CTRL__FILTER_CONFIG_reset)) {
        pass = 0;
    }

    WRITE_REG(cfg_addr + 4, (uint32_t)(FILTER_CTRL__FILTER_CONFIG__LOCKED_bm >> 32));
    cfg_hi = READ_REG(cfg_addr + 4);
    if (!check_bit("Inbound filter locked", (cfg_hi >> 31) & 1u)) {
        pass = 0;
    }

    cfg_rb = READ_REG(cfg_addr);
    if (!check_eq32("Locked filter preserves src_id config", cfg_rb,
                    cfg_src3 | FILTER_CTRL__FILTER_CONFIG_reset)) {
        pass = 0;
    }

    WRITE_REG(SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR, 0x7);
    WRITE_REG(SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_BASE_ADDR, (uint32_t)ctrl.w);

    if (pass) {
        printf("=== FABRIC MAILBOX ISS LOCK RESET TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== FABRIC MAILBOX ISS LOCK RESET TEST FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
