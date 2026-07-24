// SPDX-License-Identifier: Apache-2.0
//
// SEP Secure-DMA firmware driver for the OSS tests. Header-only, self-contained
// (register addresses are SEP fabric facts, matching secure_dma.rdl /
// och_sep_top_reg). Supports the copy + inline-SHA-256 transfer path the
// dma_hash test exercises.

#ifndef SEP_DMA_H
#define SEP_DMA_H

#include <stdint.h>

// Secure DMA CSR block (SEP local fabric @ 0x1080_0000).
#define SEP_DMA_BASE                 0x10800000u
#define SEP_DMA_INTR_ENABLE          (SEP_DMA_BASE + 0x004)
#define SEP_DMA_SRC_ADDR_LO          (SEP_DMA_BASE + 0x010)
#define SEP_DMA_SRC_ADDR_HI          (SEP_DMA_BASE + 0x014)
#define SEP_DMA_DST_ADDR_LO          (SEP_DMA_BASE + 0x018)
#define SEP_DMA_DST_ADDR_HI          (SEP_DMA_BASE + 0x01C)
#define SEP_DMA_ADDR_SPACE_ID        (SEP_DMA_BASE + 0x020)
#define SEP_DMA_ENABLED_RANGE_BASE   (SEP_DMA_BASE + 0x024)
#define SEP_DMA_ENABLED_RANGE_LIMIT  (SEP_DMA_BASE + 0x028)
#define SEP_DMA_RANGE_VALID          (SEP_DMA_BASE + 0x02C)
#define SEP_DMA_RANGE_REGWEN         (SEP_DMA_BASE + 0x030)
#define SEP_DMA_CFG_REGWEN           (SEP_DMA_BASE + 0x034)
#define SEP_DMA_TOTAL_DATA_SIZE      (SEP_DMA_BASE + 0x038)
#define SEP_DMA_CHUNK_DATA_SIZE      (SEP_DMA_BASE + 0x03C)
#define SEP_DMA_TRANSFER_WIDTH       (SEP_DMA_BASE + 0x040)
#define SEP_DMA_CONTROL              (SEP_DMA_BASE + 0x044)
#define SEP_DMA_SRC_CONFIG           (SEP_DMA_BASE + 0x048)
#define SEP_DMA_DST_CONFIG           (SEP_DMA_BASE + 0x04C)
#define SEP_DMA_STATUS               (SEP_DMA_BASE + 0x050)
#define SEP_DMA_ERROR_CODE           (SEP_DMA_BASE + 0x054)
#define SEP_DMA_SHA2_DIGEST_0        (SEP_DMA_BASE + 0x058)
#define SEP_DMA_HANDSHAKE_INTR_ENABLE (SEP_DMA_BASE + 0x098)

// CFG_REGWEN / RANGE_REGWEN multi-bit-bool: 0x6 unlocked, 0x9 locked. CFG_REGWEN
// is HW-controlled (auto-locks while BUSY); RANGE_REGWEN is FW rw0c (write 0x9 to
// lock the ENABLED_MEMORY_RANGE_* / RANGE_VALID regs, one-way until reset).
#define SEP_DMA_REGWEN_UNLOCKED      0x6u
#define SEP_DMA_REGWEN_LOCKED        0x9u

// CONTROL fields.
#define SEP_DMA_CTRL_GO              (1u << 31)
#define SEP_DMA_CTRL_ABORT          (1u << 27)
#define SEP_DMA_CTRL_INITIAL        (1u << 8)
#define SEP_DMA_CTRL_DIGEST_SWAP    (1u << 5)
#define SEP_DMA_CTRL_HW_HANDSHAKE   (1u << 4)
#define SEP_DMA_OPCODE_COPY         0x0u
#define SEP_DMA_OPCODE_SHA256       0x1u
// OPCODE[3:0] valid range is 0x0..0x3 (COPY/SHA256/SHA384/SHA512); 0x4..0xF are
// reserved -> ERROR_CODE.opcode_error.
#define SEP_DMA_OPCODE_INVALID      0xFu

// SRC/DST_CONFIG fields: INCREMENT[0], WRAP[1]. Canonical address modes (per the
// secure_dma RDL + OCAH addr_fixed/wrap tests):
//   FIXED = INC0/WRAP1 (addr held: source replicates / destination overwrites in place),
//   INCR  = INC1/WRAP0 (linear, chunks contiguous),
//   WRAP  = INC1/WRAP1 (increment within a chunk, wrap to chunk start each chunk).
// (SEP_DMA_ADDR_INCR/_WRAP below are the legacy names: _INCR=INC1, _WRAP=0x2 is the
// INC0/WRAP1 fixed-in-place mode used by the FIFO-RX path -- kept for compatibility.)
#define SEP_DMA_ADDR_INCR           0x1u
#define SEP_DMA_ADDR_WRAP           0x2u
#define SEP_DMA_CFG_FIXED           0x2u  // INCREMENT=0, WRAP=1 (canonical fixed)
#define SEP_DMA_CFG_INCR            0x1u  // INCREMENT=1, WRAP=0 (linear)
#define SEP_DMA_CFG_WRAP_CHUNK      0x3u  // INCREMENT=1, WRAP=1 (wrap per chunk)

// STATUS bits: BUSY/SHA2_DIGEST_VALID are RO; DONE/ABORTED/ERROR/CHUNK_DONE RW1C.
#define SEP_DMA_STATUS_BUSY         (1u << 0)
#define SEP_DMA_STATUS_DONE         (1u << 1)
#define SEP_DMA_STATUS_ERROR        (1u << 3)
#define SEP_DMA_STATUS_CHUNK_DONE   (1u << 5)

// ERROR_CODE bits (RO; HW-written per transfer).
#define SEP_DMA_ERR_SRC_ADDR        (1u << 0)
#define SEP_DMA_ERR_DST_ADDR        (1u << 1)
#define SEP_DMA_ERR_OPCODE          (1u << 2)
#define SEP_DMA_ERR_SIZE            (1u << 3)
#define SEP_DMA_ERR_BUS             (1u << 4)
#define SEP_DMA_ERR_BASE_LIMIT      (1u << 5)
#define SEP_DMA_ERR_RANGE_VALID     (1u << 6)
#define SEP_DMA_ERR_ASID            (1u << 7)

// INTR_ENABLE bits.
#define SEP_DMA_INTR_DONE           (1u << 0)
#define SEP_DMA_INTR_CHUNK_DONE     (1u << 1)
#define SEP_DMA_INTR_ERROR          (1u << 2)

// Address-space IDs (asid_e): only the OpenTitan 32-bit internal bus is wired
// in bare sep; SYS/SOC are tied off (would raise ASID_ERROR).
#define SEP_DMA_ASID_OT             0x7u

// Transfer widths (transfer_width_e): 0x3 is invalid -> ERROR_CODE.size_error.
#define SEP_DMA_WIDTH_1B            0x0u
#define SEP_DMA_WIDTH_2B            0x1u
#define SEP_DMA_WIDTH_4B            0x2u

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
    sep_dma_wr(SEP_DMA_SRC_CONFIG, 0x1);  // increment, no wrap
    sep_dma_wr(SEP_DMA_DST_CONFIG, 0x1);
    sep_dma_wr(SEP_DMA_INTR_ENABLE, SEP_DMA_INTR_DONE | SEP_DMA_INTR_ERROR);

    sep_dma_wr(SEP_DMA_CONTROL, SEP_DMA_CTRL_GO | SEP_DMA_CTRL_INITIAL |
                                    SEP_DMA_CTRL_DIGEST_SWAP | SEP_DMA_OPCODE_SHA256);
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

    sep_dma_wr(SEP_DMA_CONTROL, SEP_DMA_CTRL_GO | SEP_DMA_CTRL_INITIAL |
                                    SEP_DMA_OPCODE_COPY);
}

#endif  // SEP_DMA_H
