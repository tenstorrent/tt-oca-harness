/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP inbound-filter block/DECERR test firmware.
 *
 * Purpose:
 *   1. Move the lifecycle from TEST_DEV -> PROD so feat_ctrl.sep_debug=0. The
 *      inbound filter's skip input is inbound_filter_skip_i = feat_ctrl.sep_debug
 *      (sep.sv), so the DEFAULT boot (sep_debug=1) BYPASSES the inbound filter and
 *      any block/allow check would be vacuous. PROD is required to make it ACTIVE.
 *   2. Program the SEP inbound traffic filter's allow-list from the (trusted) CPU,
 *      which bypasses the inbound filter, then signal the TB that configuration is
 *      done. The UVM sequence then drives EXTERNAL AXI traffic through the ACTIVE
 *      inbound filter and checks that in-window addresses return OKAY while
 *      everything else (block-by-default) returns DECERR.
 *
 *   This is the firmware half of sep_inbound_filter_block_decerr_test. The
 *   filter is NEVER skipped (no +SEP_SKIP_CPU_RUN); PROD makes sep_debug=0.
 */

#include <stdint.h>
#include <stddef.h>

#include "och_sep_common.h"
#include "sep.h"

/* Inbound filter entry register layout (per-entry stride 0x20). */
#define FILTER_CONFIG_OFFSET 0x0u
#define FILTER_START_OFFSET 0x8u
#define FILTER_END_OFFSET 0x10u

/*
 * Allow-window = SEP Local SRAM [0x1000_0000, 0x1003_FFFF].
 * FILTER_CONFIG enable bits: read_allowed(0) | write_allowed(1) | entry_enabled(4) |
 *                            allow_ns(8) | allow_burst(24) = 0x0100_0113.
 */
#define ALLOW_START_ADDR 0x0000000010000000ULL
#define ALLOW_END_ADDR 0x000000001003FFFFULL
#define ALLOW_FILTER_CONFIG 0x0000000001000113ULL

/*
 * Firmware -> TB handshake: after the allow-list is programmed, write a done
 * magic to an SRAM word INSIDE the allow-window. The external VIP master polls
 * this address (allowed) and only proceeds once it reads the magic, which also
 * proves the filter transitioned from block-by-default to allow.
 */
#define SYNC_ADDR 0x10003000u
#define CONFIG_DONE_MAGIC 0x6000D01Eu

/*
 * PROD lifecycle state, differentially encoded. LC_STATE stores {~raw[3:0],
 * raw[3:0]}; PROD raw=0x1 -> 0xE1 (hw re-derives [7:4]). With the default DIS
 * vectors PROD gives feat_ctrl.sep_debug=0 -> inbound filter ACTIVE.
 */
#define PROD_LC_STATE_DIFF_ENCODED 0xE1u

static inline void enter_prod_lifecycle(void) {
    WRITE_REG(SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR, PROD_LC_STATE_DIFF_ENCODED);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    /* Let LC_STATE -> feat_ctrl.sep_debug -> inbound_filter_skip_i settle before
     * the allow-list is programmed and the TB starts driving external traffic. */
    for (volatile int i = 0; i < 500; i++) {
        __asm__ volatile("nop");
    }
}

static inline void program_inbound_allow_entry0(void) {
    uintptr_t base = (uintptr_t)SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0);

    WRITE_REG64(base + FILTER_START_OFFSET, ALLOW_START_ADDR);
    WRITE_REG64(base + FILTER_END_OFFSET, ALLOW_END_ADDR);
    WRITE_REG64(base + FILTER_CONFIG_OFFSET, ALLOW_FILTER_CONFIG);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

__attribute__((noinline, used)) void sep_inbound_filter_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    /* 1. Enter PROD so sep_debug=0 and the inbound filter is ACTIVE (not skipped). */
    enter_prod_lifecycle();

    /* 2. Program the inbound filter allow-list (CPU master bypasses the filter). */
    program_inbound_allow_entry0();

    /* 3. Signal the TB that the filter is configured. */
    WRITE_REG(SYNC_ADDR, CONFIG_DONE_MAGIC);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    /* 4. Park; the UVM sequence drives inbound traffic through the active filter. */
    sep_inbound_filter_pass_loop();
    return 0;
}
