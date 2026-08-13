// SPDX-License-Identifier: Apache-2.0
//
// SEP Secure-DMA firmware driver for the OSS tests. Header-only.
// Register addresses and STATUS/CONTROL field masks come from generated
// sep_addr.h / secure_dma.h (via sep.h) — do not keep a parallel hand-copied map.

#ifndef SEP_DMA_H
#define SEP_DMA_H

#include <stdint.h>

#include "sep.h"

// Secure DMA CSR block (generated sep_addr.h aperture).
#define SEP_DMA_BASE OCH_SEP_TOP_SECURE_DMA_BASE_ADDR
#define SEP_DMA_INTR_ENABLE OCH_SEP_TOP_SECURE_DMA_INTR_ENABLE_BASE_ADDR
#define SEP_DMA_SRC_ADDR_LO OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR
#define SEP_DMA_SRC_ADDR_HI OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR
#define SEP_DMA_DST_ADDR_LO OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR
#define SEP_DMA_DST_ADDR_HI OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR
#define SEP_DMA_ADDR_SPACE_ID OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR
#define SEP_DMA_ENABLED_RANGE_BASE \
    OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR
#define SEP_DMA_ENABLED_RANGE_LIMIT \
    OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR
#define SEP_DMA_RANGE_VALID OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR
#define SEP_DMA_RANGE_REGWEN OCH_SEP_TOP_SECURE_DMA_RANGE_REGWEN_BASE_ADDR
#define SEP_DMA_CFG_REGWEN OCH_SEP_TOP_SECURE_DMA_CFG_REGWEN_BASE_ADDR
#define SEP_DMA_TOTAL_DATA_SIZE OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR
#define SEP_DMA_CHUNK_DATA_SIZE OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR
#define SEP_DMA_TRANSFER_WIDTH OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR
#define SEP_DMA_CONTROL OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR
#define SEP_DMA_SRC_CONFIG OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR
#define SEP_DMA_DST_CONFIG OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR
#define SEP_DMA_STATUS OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR
#define SEP_DMA_ERROR_CODE OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR
#define SEP_DMA_SHA2_DIGEST_0 OCH_SEP_TOP_SECURE_DMA_SHA2_DIGEST_0_BASE_ADDR
#define SEP_DMA_HANDSHAKE_INTR_ENABLE \
    OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR

// CFG_REGWEN / RANGE_REGWEN multi-bit-bool: 0x6 unlocked, 0x9 locked.
#define SEP_DMA_REGWEN_UNLOCKED 0x6u
#define SEP_DMA_REGWEN_LOCKED 0x9u

// CONTROL fields (generated masks / opcode encodings).
#define SEP_DMA_CTRL_GO SECURE_DMA__CONTROL__GO_bm
#define SEP_DMA_CTRL_ABORT SECURE_DMA__CONTROL__ABORT_bm
#define SEP_DMA_CTRL_INITIAL SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm
#define SEP_DMA_CTRL_DIGEST_SWAP SECURE_DMA__CONTROL__DIGEST_SWAP_bm
#define SEP_DMA_CTRL_HW_HANDSHAKE SECURE_DMA__CONTROL__HARDWARE_HANDSHAKE_ENABLE_bm
#define SEP_DMA_OPCODE_COPY 0x0u
#define SEP_DMA_OPCODE_SHA256 0x1u
// OPCODE[3:0] valid range is 0x0..0x3; 0x4..0xF are reserved -> opcode_error.
#define SEP_DMA_OPCODE_INVALID 0xFu

// SRC/DST_CONFIG fields: INCREMENT[0], WRAP[1].
#define SEP_DMA_ADDR_INCR SECURE_DMA__SRC_CONFIG__INCREMENT_bm
#define SEP_DMA_ADDR_WRAP SECURE_DMA__SRC_CONFIG__WRAP_bm
#define SEP_DMA_CFG_FIXED SECURE_DMA__SRC_CONFIG__WRAP_bm
#define SEP_DMA_CFG_INCR SECURE_DMA__SRC_CONFIG__INCREMENT_bm
#define SEP_DMA_CFG_WRAP_CHUNK \
    (SECURE_DMA__SRC_CONFIG__INCREMENT_bm | SECURE_DMA__SRC_CONFIG__WRAP_bm)

// STATUS bits: BUSY/SHA2_DIGEST_VALID are RO; DONE/ABORTED/ERROR/CHUNK_DONE RW1C.
#define SEP_DMA_STATUS_BUSY SECURE_DMA__STATUS__BUSY_bm
#define SEP_DMA_STATUS_DONE SECURE_DMA__STATUS__DONE_bm
#define SEP_DMA_STATUS_ERROR SECURE_DMA__STATUS__ERROR_bm
#define SEP_DMA_STATUS_CHUNK_DONE SECURE_DMA__STATUS__CHUNK_DONE_bm

// ERROR_CODE bits (RO; HW-written per transfer).
#define SEP_DMA_ERR_SRC_ADDR SECURE_DMA__ERROR_CODE__SRC_ADDR_ERROR_bm
#define SEP_DMA_ERR_DST_ADDR SECURE_DMA__ERROR_CODE__DST_ADDR_ERROR_bm
#define SEP_DMA_ERR_OPCODE SECURE_DMA__ERROR_CODE__OPCODE_ERROR_bm
#define SEP_DMA_ERR_SIZE SECURE_DMA__ERROR_CODE__SIZE_ERROR_bm
#define SEP_DMA_ERR_BUS SECURE_DMA__ERROR_CODE__BUS_ERROR_bm
#define SEP_DMA_ERR_BASE_LIMIT SECURE_DMA__ERROR_CODE__BASE_LIMIT_ERROR_bm
#define SEP_DMA_ERR_RANGE_VALID SECURE_DMA__ERROR_CODE__RANGE_VALID_ERROR_bm
#define SEP_DMA_ERR_ASID SECURE_DMA__ERROR_CODE__ASID_ERROR_bm

// INTR_ENABLE bits.
#define SEP_DMA_INTR_DONE SECURE_DMA__INTR_ENABLE__DMA_DONE_bm
#define SEP_DMA_INTR_CHUNK_DONE SECURE_DMA__INTR_ENABLE__DMA_CHUNK_DONE_bm
#define SEP_DMA_INTR_ERROR SECURE_DMA__INTR_ENABLE__DMA_ERROR_bm

// Address-space IDs (asid_e): only the OpenTitan 32-bit internal bus is wired
// in bare sep; SYS/SOC are tied off (would raise ASID_ERROR).
#define SEP_DMA_ASID_OT SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset

// Transfer widths (transfer_width_e): 0x3 is invalid -> ERROR_CODE.size_error.
#define SEP_DMA_WIDTH_1B 0x0u
#define SEP_DMA_WIDTH_2B 0x1u
#define SEP_DMA_WIDTH_4B 0x2u

static inline uint32_t sep_dma_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void sep_dma_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// Program and start a single-chunk copy + inline SHA-256 transfer. Both src and
// dst are OT-internal (ASID 0x7), 4-byte width, incrementing. The DIGEST_SWAP
// bit makes the hardware digest big-endian to match the software SHA-256.
static inline void sep_dma_sha256_start(uint32_t src, uint32_t dst, uint32_t len) {
    sep_dma_wr(SEP_DMA_ENABLED_RANGE_BASE, 0x0);
    sep_dma_wr(SEP_DMA_ENABLED_RANGE_LIMIT, 0xFFFFFFFFu);
    sep_dma_wr(SEP_DMA_RANGE_VALID, 0x1);

    sep_dma_wr(SEP_DMA_SRC_ADDR_LO, src);
    sep_dma_wr(SEP_DMA_SRC_ADDR_HI, 0x0);
    sep_dma_wr(SEP_DMA_DST_ADDR_LO, dst);
    sep_dma_wr(SEP_DMA_DST_ADDR_HI, 0x0);
    sep_dma_wr(SEP_DMA_ADDR_SPACE_ID, SEP_DMA_ASID_OT | (SEP_DMA_ASID_OT << 4));
    sep_dma_wr(SEP_DMA_TRANSFER_WIDTH, SEP_DMA_WIDTH_4B);
    sep_dma_wr(SEP_DMA_CHUNK_DATA_SIZE, len);
    sep_dma_wr(SEP_DMA_TOTAL_DATA_SIZE, len);
    sep_dma_wr(SEP_DMA_SRC_CONFIG, 0x1); // increment, no wrap
    sep_dma_wr(SEP_DMA_DST_CONFIG, 0x1);
    sep_dma_wr(SEP_DMA_INTR_ENABLE, SEP_DMA_INTR_DONE | SEP_DMA_INTR_ERROR);

    sep_dma_wr(SEP_DMA_CONTROL, SEP_DMA_CTRL_GO | SEP_DMA_CTRL_INITIAL | SEP_DMA_CTRL_DIGEST_SWAP |
                                    SEP_DMA_OPCODE_SHA256);
}

// Program and start a single-chunk plain memory copy (opcode COPY, no inline
// hash). Both src and dst are OT-internal (ASID 0x7), 4-byte width,
// incrementing. Non-blocking and interrupt-free: CONTROL.GO returns immediately
// and the caller polls STATUS (BUSY/DONE/ERROR) -- used by the DMA/CPU
// contention test, which must observe the transfer mid-flight.
static inline void sep_dma_copy_start(uint32_t src, uint32_t dst, uint32_t len) {
    sep_dma_wr(SEP_DMA_ENABLED_RANGE_BASE, 0x0);
    sep_dma_wr(SEP_DMA_ENABLED_RANGE_LIMIT, 0xFFFFFFFFu);
    sep_dma_wr(SEP_DMA_RANGE_VALID, 0x1);

    sep_dma_wr(SEP_DMA_SRC_ADDR_LO, src);
    sep_dma_wr(SEP_DMA_SRC_ADDR_HI, 0x0);
    sep_dma_wr(SEP_DMA_DST_ADDR_LO, dst);
    sep_dma_wr(SEP_DMA_DST_ADDR_HI, 0x0);
    sep_dma_wr(SEP_DMA_ADDR_SPACE_ID, SEP_DMA_ASID_OT | (SEP_DMA_ASID_OT << 4));
    sep_dma_wr(SEP_DMA_TRANSFER_WIDTH, SEP_DMA_WIDTH_4B);
    sep_dma_wr(SEP_DMA_CHUNK_DATA_SIZE, len);
    sep_dma_wr(SEP_DMA_TOTAL_DATA_SIZE, len);
    sep_dma_wr(SEP_DMA_SRC_CONFIG, SEP_DMA_ADDR_INCR);
    sep_dma_wr(SEP_DMA_DST_CONFIG, SEP_DMA_ADDR_INCR);

    sep_dma_wr(SEP_DMA_CONTROL, SEP_DMA_CTRL_GO | SEP_DMA_CTRL_INITIAL | SEP_DMA_OPCODE_COPY);
}

#endif // SEP_DMA_H
