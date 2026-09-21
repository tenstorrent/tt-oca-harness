// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP Secure-DMA firmware helpers for the OSS tests. Header-only.
// Addresses and field masks come from generated sep_addr.h / secure_dma.h
// (via sep.h). Do not alias those symbols — call them by their PeakRDL names.

#ifndef SEP_DMA_H
#define SEP_DMA_H

#include <stdint.h>

#include "sep.h"

// CFG_REGWEN / RANGE_REGWEN multi-bit-bool encodings from the generated
// MULTIBITBOOL4 pair. Unlocked is TRUE (the REGWEN reset); locked is FALSE
// (the value the engine writes when it auto-locks).
#define SEP_DMA_REGWEN_UNLOCKED MULTIBITBOOL4__TRUE
#define SEP_DMA_REGWEN_LOCKED MULTIBITBOOL4__FALSE

// CONTROL.OPCODE encodings. PeakRDL carries only the field, so the legal set
// is transcribed here from the IP register specification:
// vendor/lowRISC/opentitan/upstream/hw/ip/dma/data/dma.hjson enumerates
// opcode as COPY 0x0, SHA256 0x1, SHA384 0x2, SHA512 0x3. 0x4..0xF are
// reserved; the RDL describes OPCODE_ERROR as "Opcode is invalid."
#define SEP_DMA_OPCODE_COPY 0x0u
#define SEP_DMA_OPCODE_SHA256 0x1u
#define SEP_DMA_OPCODE_SHA384 0x2u
#define SEP_DMA_OPCODE_SHA512 0x3u
// OPCODE[3:0] valid range is 0x0..0x3; 0x4..0xF are reserved -> opcode_error.
#define SEP_DMA_OPCODE_INVALID 0xFu

// TRANSFER_WIDTH encodings (not named in PeakRDL). 0x3 is invalid -> size_error.
#define SEP_DMA_WIDTH_1B 0x0u
#define SEP_DMA_WIDTH_2B 0x1u
#define SEP_DMA_WIDTH_4B 0x2u
#define SEP_DMA_WIDTH_INVALID 0x3u

// ADDR_SPACE_ID SRC_ASID[3:0] / DST_ASID[7:4] encodings. PeakRDL carries only
// the reset value, so the legal set is transcribed here from the IP register
// specification: vendor/lowRISC/opentitan/upstream/hw/ip/dma/data/dma.hjson
// enumerates src_asid/dst_asid as OT_ADDR 0x7, SYS_ADDR 0x9, SOC_ADDR 0xa.
// Anything else is outside the enumeration; the RDL describes ASID_ERROR as
// "The source or destination ASID contains an invalid value."
#define SEP_DMA_ASID_OT 0x7u
#define SEP_DMA_ASID_SYS 0x9u
#define SEP_DMA_ASID_SOC 0xAu
// Not one of the three enumerated encodings.
#define SEP_DMA_ASID_INVALID 0x0u
// Field positions come from the generated header, so an RDL move follows here.
#define SEP_DMA_ASID_PAIR(src, dst) \
    ((((uint32_t)(src)) << SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_bp) | \
     (((uint32_t)(dst)) << SECURE_DMA__ADDR_SPACE_ID__DST_ASID_bp))

static inline uint32_t sep_dma_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void sep_dma_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// Program and start a single-chunk copy + inline SHA-256 transfer. Both src and
// dst are OT-internal, 4-byte width, incrementing. DIGEST_SWAP makes the
// hardware digest big-endian to match software SHA-256.
static inline void sep_dma_sha256_start(uint32_t src, uint32_t dst, uint32_t len) {
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    sep_dma_wr(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1);

    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst);
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0);
    uint32_t asid = SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset;
    sep_dma_wr(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, SEP_DMA_ASID_PAIR(asid, asid));
    sep_dma_wr(SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, SEP_DMA_WIDTH_4B);
    sep_dma_wr(SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, len);
    sep_dma_wr(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, len);
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, SECURE_DMA__SRC_CONFIG__INCREMENT_bm);
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, SECURE_DMA__DST_CONFIG__INCREMENT_bm);
    sep_dma_wr(SEP_TOP_SECURE_DMA_INTR_ENABLE_BASE_ADDR,
               SECURE_DMA__INTR_ENABLE__DMA_DONE_bm | SECURE_DMA__INTR_ENABLE__DMA_ERROR_bm);

    sep_dma_wr(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
               SECURE_DMA__CONTROL__GO_bm | SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm |
                   SECURE_DMA__CONTROL__DIGEST_SWAP_bm | SEP_DMA_OPCODE_SHA256);
}

// Program and start a single-chunk plain memory copy (opcode COPY, no inline
// hash). Non-blocking and interrupt-free: CONTROL.GO returns immediately and
// the caller polls STATUS.
static inline void sep_dma_copy_start(uint32_t src, uint32_t dst, uint32_t len) {
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    sep_dma_wr(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1);

    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst);
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0);
    uint32_t asid = SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset;
    sep_dma_wr(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, SEP_DMA_ASID_PAIR(asid, asid));
    sep_dma_wr(SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, SEP_DMA_WIDTH_4B);
    sep_dma_wr(SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, len);
    sep_dma_wr(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, len);
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, SECURE_DMA__SRC_CONFIG__INCREMENT_bm);
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, SECURE_DMA__DST_CONFIG__INCREMENT_bm);

    sep_dma_wr(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
               SECURE_DMA__CONTROL__GO_bm | SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm |
                   SEP_DMA_OPCODE_COPY);
}

#endif // SEP_DMA_H
