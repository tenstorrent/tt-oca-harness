// Status reporting interface.
//
// Provides STATUS_ENCODE(), STATUS_OUT(), and report_status() with the ROM
// status encoding. Status values (SEP_MSG_*) are
// generated from meta/status/status_values.tsv.

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
#include "och_sep_top_reg.h"
#include "rom_virt_console.h"
#include "status_ring.h"

#define STATUS_OUT(code) mmio_write32(SEP_SCRATCH_COLD_SCRATCH_1__REG_ADDR, (code))

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
