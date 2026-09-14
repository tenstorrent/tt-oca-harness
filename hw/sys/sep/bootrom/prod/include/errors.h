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

#define STATUS_OUT(code) mmio_write32(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(1), (code))

// ── Final verdict channel: cold_scratch[0] ──
// Only the terminal outcome goes here, so one read gives one answer. It is
// SEP-internal and writable from the first instruction, unlike the mailbox at
// 0x80000000 behind the outbound AXI filter. The error code is on cold_scratch[1].
#define TEST_PASS_CODE 0xACAFACA1u
#define TEST_FAIL_CODE 0xDEADBEEFu

#define VERDICT_OUT(code) mmio_write32(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0), (code))

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
