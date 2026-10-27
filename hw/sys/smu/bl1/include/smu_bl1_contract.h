/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SEP BL1 to SMC BL1 stage contract: the SMC SRAM layout, the SMC hart 0 park interlock, the
// mailbox messages, and the timing limits. Both BL1 images include this header, and the BL1
// build checks it against the SMC ROM's own definitions. Macro-only, so assembly includes it.

#pragma once

#include "smc_addr.h"
#include "sep_addr.h"

// The SEP reaches SMC-local address a at SMU_BL1_SEP_VIEW(a): its SMC window starts at
// 0x4000_0000 and the SMC decodes it from LOCAL_BASE, which keeps its reset value.
#define SMU_BL1_SMC_LOCAL_BASE 0xC0000000u
#define SMU_BL1_SEP_SMC_WINDOW 0x40000000u
#define SMU_BL1_SEP_VIEW(smc_local_addr) \
    (SMU_BL1_SEP_SMC_WINDOW + ((smc_local_addr)-SMU_BL1_SMC_LOCAL_BASE))

// SMC-side base of the SEP global aperture. The integrator programs it; it is not in the
// generated SMC map.
#ifndef SMU_BL1_SEP_APERTURE
#define SMU_BL1_SEP_APERTURE 0x50000000u
#endif

// SMC SRAM layout, SMC-local, half-open. The SEP zone equals the SMC ROM's published SEP-safe
// range on the same tree; the image and writable windows are disjoint and lie inside it.
#define SMU_BL1_SMC_SRAM_BASE SMC_TOP_SPM_MEMORY_BASE_ADDR
#define SMU_BL1_SMC_SRAM_SIZE SMC_TOP_SPM_MEMORY_SIZE
#define SMU_BL1_SEP_ZONE_START 0xC0066400u
#define SMU_BL1_SEP_ZONE_END 0xC015B000u
#define SMU_BL1_IMAGE_WINDOW_START 0xC0080000u
#define SMU_BL1_IMAGE_WINDOW_END 0xC00C0000u
#define SMU_BL1_RW_WINDOW_START 0xC00C0000u
#define SMU_BL1_RW_WINDOW_END SMU_BL1_SEP_ZONE_END

// TOC image type of the SMC BL1: 16 ASCII bytes, vendor string then label.
#define SMU_BL1_SMC_IMAGE_TYPE "OCAHSMC BLSTAGE1"

// SMC CPU_CTRL registers, SMC-local.
#define SMU_BL1_SMC_RESET_VECTOR0 SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR(0)
#define SMU_BL1_SMC_RESET_CTRL SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR
#define SMU_BL1_SMC_CORE_PULSE_COUNT SMC_TOP_SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_BASE_ADDR
#define SMU_BL1_SMC_SCRATCH(idx) SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR((idx))
#define SMU_BL1_SMC_LC_STATE SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR

// RESET_CTRL low byte and uncore bit, written as whole constants: every core and the uncore
// out of reset; the same with a core 0 pulse; and core 0 held in reset.
#define SMU_BL1_RESET_CTRL_IDLE 0x10Fu
#define SMU_BL1_RESET_CTRL_PULSE_CORE0 0x11Fu
#define SMU_BL1_RESET_CTRL_HOLD_CORE0 0x10Eu
#define SMU_BL1_RESET_CTRL_UNCORE_BIT (1u << 8)
#define SMU_BL1_SMC_ROM_RESET_VECTOR 0xC0040000u

// Coordination scratch registers the interlock and the zone checks read.
#define SMU_BL1_SCRATCH_PARK_REQ 3u
#define SMU_BL1_SCRATCH_STATUS_TO_SEP 9u
#define SMU_BL1_SCRATCH_STATUS_BUFFER 11u
#define SMU_BL1_SCRATCH_SAFE_START 13u
#define SMU_BL1_SCRATCH_SAFE_SIZE 14u

// Park interlock. Only the SEP writes the request register; only the SMC ROM park routine
// sets HART0_PARKED, after writing back its data cache. The SMC ROM clears both on entry.
#define SMU_BL1_PARK_REQ_VALUE 0x50524B31u // "PRK1"
#define SMU_BL1_STATUS_SRAM_INIT (1u << 0)
#define SMU_BL1_STATUS_BUFFER_READY (1u << 2)
#define SMU_BL1_STATUS_HART0_PARKED (1u << 4)

// SEP host mailbox 0. The SEP pushes the challenge on the outbound port and pops the
// confirmation on the inbound port; the SMC uses the same ports through the SEP aperture.
#define SMU_BL1_MBOX_OUTBOUND SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR
#define SMU_BL1_MBOX_INBOUND SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR
#define SMU_BL1_MBOX_INBOUND_END (SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR + 0x800u)
#define SMU_BL1_TAG_SEP 0x53455031u // "SEP1"
#define SMU_BL1_TAG_SMC 0x534D4331u // "SMC1"

// SEP inbound filter entry that admits the SMC to the mailbox inbound port only.
#define SMU_BL1_FILTER_ENTRY 15u
#define SMU_BL1_FILTER_SMC_SRC_ID 3u
#define SMU_BL1_SEP_REGION_SIZE 0x20000000u

// Soft-PCR slot of the SMC BL1 measurement: slots 0 and 1 belong to BL0.
#define SMU_BL1_MEAS_SLOT_SMC_BL1 2u

// Time limits on the SEP cycle counter, which runs at the reference clock when the PLL strap
// is clear. Debug builds may shorten them for timeout tests; release builds may not.
#define SMU_BL1_SEP_CORE_HZ 100000000u
#define SMU_BL1_CONFIRM_TIMEOUT_US_DEFAULT 100000u
#define SMU_BL1_PARK_TIMEOUT_US_DEFAULT 10000u
#ifndef SMU_BL1_CONFIRM_TIMEOUT_US
#define SMU_BL1_CONFIRM_TIMEOUT_US SMU_BL1_CONFIRM_TIMEOUT_US_DEFAULT
#endif
#ifndef SMU_BL1_PARK_TIMEOUT_US
#define SMU_BL1_PARK_TIMEOUT_US SMU_BL1_PARK_TIMEOUT_US_DEFAULT
#endif
#ifdef SMU_BL1_RELEASE
#if SMU_BL1_CONFIRM_TIMEOUT_US != SMU_BL1_CONFIRM_TIMEOUT_US_DEFAULT
#error "release builds use the default confirmation timeout"
#endif
#if SMU_BL1_PARK_TIMEOUT_US != SMU_BL1_PARK_TIMEOUT_US_DEFAULT
#error "release builds use the default park timeout"
#endif
#endif

#if !defined(__ASSEMBLER__)
_Static_assert(SMU_BL1_SEP_ZONE_START < SMU_BL1_IMAGE_WINDOW_START &&
                   SMU_BL1_IMAGE_WINDOW_END <= SMU_BL1_RW_WINDOW_START &&
                   SMU_BL1_RW_WINDOW_START < SMU_BL1_RW_WINDOW_END &&
                   SMU_BL1_RW_WINDOW_END <= SMU_BL1_SEP_ZONE_END,
               "image and writable windows are disjoint and inside the SEP zone");
_Static_assert(SMU_BL1_SMC_SRAM_BASE <= SMU_BL1_SEP_ZONE_START &&
                   SMU_BL1_SEP_ZONE_END <= SMU_BL1_SMC_SRAM_BASE + SMU_BL1_SMC_SRAM_SIZE,
               "the SEP zone lies inside SMC SRAM");
_Static_assert(SMU_BL1_IMAGE_WINDOW_START % 8u == 0u, "image window is 8-byte aligned");
#endif
