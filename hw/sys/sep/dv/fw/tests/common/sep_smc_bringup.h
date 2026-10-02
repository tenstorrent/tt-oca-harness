/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*******************************************************************************
 * SEP-driven SMC bring-up over the SEP->SMC port (sep_axi_in) -- common helper.
 *
 * The SEP->SMC port maps the SEP-view region 0x4000_0000 to the SMC-local 0xC000_0000
 * space and is NOT behind the SMC sys-inbound BLOCK_BY_DEFAULT filter, so the real SEP
 * firmware can reach SMC CPU_CTRL (reset CSRs, scratch) and SMC SRAM directly. The SEP's
 * OWN outbound egress filter must first be opened over this region (sep_smc_open_window()).
 *
 * This simulation bring-up path lets SEP release SMC. It does not verify the
 * secure-boot, OCCP, manifest, or BL1-handoff flow.
 *
 * Typical use (SEP test firmware):
 *   #include "sep_smc_bringup.h"
 *   sep_smc_open_window();                                    // outbound egress filter
 *   if (sep_smc_bringup_from_sram(SMC_ENTRY, SMC_COOKIE, LIM) != 0) { ...fail... }
 *   // ...then SEP<->SMC scratch handshake via sep_smc_scratch_write/_wait...
 ******************************************************************************/
#ifndef SEP_SMC_BRINGUP_H
#define SEP_SMC_BRINGUP_H

#include <stdint.h>
#include "och_sep_common.h"
#include "sep_outbound_filter.h"

//==============================================================================
// SEP->SMC alias map (SEP-view 0x4000_0000 region -> SMC-local 0xC000_0000)
//==============================================================================
#define SEP_SMC_REGION_START 0x0000000040000000ULL /* SEP-view base of SMC region */
#define SEP_SMC_REGION_END 0x00000000800000FFULL   /* covers SMC region + TB mailbox */
#define SEP_SMC_RESET_VECTOR_ALIAS 0x40039000u     /* SMC CPU_CTRL RESET_VECTOR_0 (+0/8/10/18) */
#define SEP_SMC_RESET_CTRL_ALIAS 0x40039020u       /* SMC CPU_CTRL RESET_CTRL */
#define SEP_SMC_SCRATCH0_ALIAS 0x40039080u         /* SMC CPU_CTRL SCRATCH_0 (8-byte stride) */
#define SEP_SMC_SRAM_BASE_ALIAS 0x40060000u        /* SMC SRAM base */
/* RESET_CTRL pulse: default 0x10F | core0..3 reset_pulse_start[7:4] -> re-fetch all cores. */
#define SEP_SMC_RESET_CTRL_PULSE 0x00000000000001FFULL

/* SEP-view alias of an SMC CPU_CTRL scratch index (0..15). */
#define SEP_SMC_SCRATCH_ALIAS(n) (SEP_SMC_SCRATCH0_ALIAS + ((uint32_t)(n)*8u))

//==============================================================================
// Bring-up
//==============================================================================

/* Open the SEP outbound egress filter over the whole SEP->SMC region (+ TB mailbox) so the
 * SEP can reach SMC CPU_CTRL / SRAM as well as STDOUT. Call before any SEP->SMC access. */
static inline void sep_smc_open_window(void) {
    sep_outbound_filter_init_range(SEP_SMC_REGION_START, SEP_SMC_REGION_END);
}

/* Frontdoor SMC bring-up: wait (bounded) for the TB to preload the SMC image into SRAM by
 * polling the SMC SRAM base word for the EXACT image cookie, then re-vector all four SMC
 * cores to `entry` and pulse their reset -- releasing them to run the image. Returns 0 on
 * success, -1 if the cookie never appeared within poll_limit (caller should signal + stop,
 * never proceed on an absent preload). Requires sep_smc_open_window() first. */
static inline int sep_smc_bringup_from_sram(uint32_t entry, uint32_t cookie, uint32_t poll_limit) {
    int ready = 0;
    for (uint32_t i = 0; i < poll_limit; ++i) {
        if (READ_REG(SEP_SMC_SRAM_BASE_ALIAS) == cookie) {
            ready = 1;
            break;
        }
    }
    if (!ready) {
        return -1;
    }
    WRITE_REG64(SEP_SMC_RESET_VECTOR_ALIAS + 0x00, (uint64_t)entry);
    WRITE_REG64(SEP_SMC_RESET_VECTOR_ALIAS + 0x08, (uint64_t)entry);
    WRITE_REG64(SEP_SMC_RESET_VECTOR_ALIAS + 0x10, (uint64_t)entry);
    WRITE_REG64(SEP_SMC_RESET_VECTOR_ALIAS + 0x18, (uint64_t)entry);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    WRITE_REG64(SEP_SMC_RESET_CTRL_ALIAS, SEP_SMC_RESET_CTRL_PULSE);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    return 0;
}

//==============================================================================
// SEP<->SMC scratch handshake (over the alias; no ECC -- plain register accesses)
//==============================================================================

/* Publish a value to an SMC scratch alias (with a fence). */
static inline void sep_smc_scratch_write(uint32_t alias_addr, uint32_t value) {
    WRITE_REG(alias_addr, value);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

/* Bounded-wait for an SMC scratch alias to equal `expected`. Returns 0 on match, -1 on
 * timeout (never hangs). */
static inline int sep_smc_scratch_wait(uint32_t alias_addr, uint32_t expected,
                                       uint32_t poll_limit) {
    for (uint32_t i = 0; i < poll_limit; ++i) {
        if (READ_REG(alias_addr) == expected) {
            return 0;
        }
    }
    return -1;
}

#endif // SEP_SMC_BRINGUP_H
