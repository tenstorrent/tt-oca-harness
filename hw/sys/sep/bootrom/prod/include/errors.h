/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Status reporting interface.  Status values (SEP_MSG_*) are generated from
// meta/status/status_values.tsv.

#ifndef __ERRORS_H_DEFINED__
#define __ERRORS_H_DEFINED__

#define STATUS_ID_BL0 1
#define STATUS_ID_BL1 2

#ifdef SEP_BL0
#define SEP_STATUS_ID STATUS_ID_BL0
#else
#define SEP_STATUS_ID STATUS_ID_BL1
#endif

/*
 * Type values must conform to OCCP specification
 * 0x0-0x7F are defined by OCCP
 * 0x80-0xFF are implementation specific
 */
#define STATUS_TYPE_INFO 0x01
#define STATUS_TYPE_WARN 0x08
#define STATUS_TYPE_ERROR 0x0f
#define STATUS_TYPE_DEBUG 0x80
#define STATUS_TYPE_INFO_EXT 0x81

#define STATUS_ENCODE(type, value) \
    (((type & 0xFF) << 24) | ((SEP_STATUS_ID & 0xFF) << 16) | ((value & 0xFFFF)))

// Generated from meta/status/status_values.tsv
#include "status_values.h"

#ifdef __ASSEMBLER__
// Assembly cannot use inline functions — status writes are done with
// literal STATUS_ENCODE values in vector.S.
#else

#include <stdint.h>

#include "rom_mmio.h"
#include "sep.h"
#include "rom_virt_console.h"
#include "status_ring.h"

#define STATUS_OUT(code) mmio_write32(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(1), (code))

// ── Terminal error codes: rom_err_fail() ──
//
// The ROM core's terminal codes. They keep the upper half zero, which is
// what lets rom_err_fail() also post them to cold_scratch[1]. A subsystem's own
// codes carry its tag in the upper half instead: 0x0002xxxx for the DMA driver
// (SEP_DMA_ERR_*, sep_dma.c) and 0x0003xxxx for the manifest module
// (OCA_BOOT_ERR_*, oca_boot.h). The nibble at [15:12] names the
// area: A platform checks, B C runtime, C SMC coordination, D DFT gate, E SPI
// bring-up, F boot core.
enum {
    ROM_ERR_SMC_SANITY_FAILED = 0x0000A001u,
    ROM_ERR_LIFECYCLE_INVALID = 0x0000A002u,
    ROM_ERR_RUNTIME_INIT_FAILED = 0x0000B001u,
    ROM_ERR_SMC_COORD_NOT_READY = 0x0000C001u,
    // Reserved in the error-code space only; the MEM_REPAIR gate is in
    // vector.S and reports STATUS_ENCODE(ERROR, SEP_MSG_MBIST_FAIL) directly,
    // since rom_err_fail() needs a C stack that does not exist that early.
    ROM_ERR_DFT_GATE_BLOCKED = 0x0000D001u,
    ROM_ERR_SPI_INIT_FAILED = 0x0000E001u,
    ROM_ERR_STACK_OVERFLOW = 0x0000F001u,
    ROM_ERR_CRYPTO_SELFTEST_FAILED = 0x0000F002u,
    ROM_ERR_FUSE_SECRETS_NOT_LOCKED = 0x0000F003u,
    // 0x0000F004 is ROM_ERR_HANDOFF_SELFCHECK_FAILED in the spec's registry,
    // reserved for a pre-hand-off self-check this ROM does not implement.
    ROM_ERR_ROM_HASH_MISMATCH = 0x0000F005u,
    ROM_ERR_MEASUREMENT_FAILED = 0x0000F006u,
    ROM_ERR_BL0_STATE_OVERLAPS_STACK = 0x0000F007u,
    ROM_ERR_SBOOT_DIS_RSVD_SET = 0x0000F008u,
    ROM_ERR_ENTROPY_INIT_FAILED = 0x0000F009u,
};

// Records error_code and halts; defined in rom_main.c.
__attribute__((noreturn)) void rom_err_fail_ext(uint32_t error_code);

// ── Final verdict channel: cold_scratch[0] ──
// Only the terminal outcome goes here, so one read gives one answer. It is
// SEP-internal and writable from the first instruction, unlike the mailbox at
// 0x80000000 behind the outbound AXI filter. The error code is on cold_scratch[1].
#define TEST_PASS_CODE 0xACAFACA1u
#define TEST_FAIL_CODE 0xDEADBEEFu

#define VERDICT_OUT(code) mmio_write32(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0), (code))

// The ROM only ever reports FAIL. A successful boot ends in BL1, which reports
// PASS itself.
static inline void rom_test_fail(void) {
    VERDICT_OUT(TEST_FAIL_CODE);
}

#define LOG(msg, val) simputshex32(msg " ", (uint32_t)(val))

/**
 * Function to report status
 * @param type what kind of status (info | warning | error | debug)
 * @param value which error is this
 */
static inline void report_status(uint8_t type, uint16_t value) {
    uint32_t status;

    status = STATUS_ENCODE(type, value);

    STATUS_OUT(status);

    if (type == STATUS_TYPE_DEBUG) return;

    status_ring_buffer_insert(status);
}

#endif // __ASSEMBLER__

#endif // __ERRORS_H_DEFINED__
