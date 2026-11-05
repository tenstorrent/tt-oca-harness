/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OCAH SEP ROM - DMA copy implementation (secure_dma)
//
// References:
// - bootcode DMA API and behavior
// - `fw/sep/tests/dma_test/dma_test.c` (secure_dma programming sequence)
//
// This file is freestanding and uses absolute register addresses from
// `sep.h`.

#include <stddef.h>
#include <stdint.h>

#include "rom_mmio.h"

// Generated absolute register map for OCAH SEP.
#include "sep.h"

#include "sep_dma.h"
#include "errors.h"
#include "harden.h"
#include "rom_virt_console.h"

// SMC interface (for dynamic SMC SRAM range checks).
#include "sep_smc_interface.h"

// XIP window for direct (memory-mapped) flash access (OCAH address map):
//   0x3000_0000 - 0x3FFF_FFFF (256 MiB).
#ifndef SEP_SPI_BASE
#define SEP_SPI_BASE ((uint32_t)SEP_TOP_SEP_EXTERNAL_XIP_REGION_BASE_ADDR)
#endif
#ifndef SEP_SPI_MAX_SIZE
#define SEP_SPI_MAX_SIZE ((uint32_t)SEP_TOP_SEP_EXTERNAL_XIP_REGION_SIZE)
#endif

// For OCAH, the "SEP EXT SRAM" equivalent is `sep_sram` in the address map.
#define SEP_EXT_SRAM_BASE ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR)
#define SEP_SRAM_SIZE ((uint32_t)SEP_TOP_SEP_SRAM_SIZE)

// ABORT forces the engine idle and is not gated by cfg_regwen.
#define DMA_CTRL_ABORT SECURE_DMA__CONTROL__ABORT_bm
#define DMA_STATUS_BUSY SECURE_DMA__STATUS__BUSY_bm
#define DMA_STATUS_DONE SECURE_DMA__STATUS__DONE_bm
#define DMA_STATUS_ERROR SECURE_DMA__STATUS__ERROR_bm
#define DMA_STATUS_W1C \
    (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ABORTED_bm | DMA_STATUS_ERROR | \
     SECURE_DMA__STATUS__CHUNK_DONE_bm)

// CONTROL.OPCODE for a zero fill. The register description names no opcode
// values, so the generated headers carry none.
#define SEP_DMA_OPCODE_ZERO 0x4u

// Completion-poll budget for one transfer, counted in STATUS reads.
//
// The largest transfer sep_dma_copy() or sep_dma_zero() accepts is SMC SRAM's 1 MiB, 256 Ki beats
// of 4 bytes. A STATUS read is at least one bus round trip, taken here as no
// less than 4 core cycles, so DMA_POLLS_PER_BEAT allows over 1000 core cycles
// per beat, far slower than a copy between on-chip memories. The budget assumes
// an on-chip source; it is not sized for a serial-flash XIP source, which can
// take longer than that per beat. DMA_POLLS_SETUP covers the engine starting
// and the last write response, a few bus transactions each, with at least 40000
// core cycles. The largest budget, ~67 M reads, fits uint32_t.
#define DMA_POLLS_SETUP 10000u
#define DMA_POLLS_PER_BEAT 256u

static inline uint32_t dma_read(uint32_t addr) {
    return mmio_read32(addr);
}
static inline void dma_write(uint32_t addr, uint32_t v) {
    mmio_write32(addr, v);
}

static inline int contains_range_u32(uint32_t base, uint32_t size, uint32_t addr, uint32_t len) {
    // Reject wraparound.
    if (len == 0u) {
        return 1;
    }
    const uint32_t end = addr + len - 1u;
    if (end < addr) {
        return 0;
    }
    const uint32_t limit = base + size - 1u;
    if (limit < base) {
        return 0;
    }
    return (addr >= base) && (end <= limit);
}

void sep_dma_init(void) {
    // Secure DMA requires an enabled memory range before operation.
    dma_write(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x00000000u);
    dma_write(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    dma_write(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, SECURE_DMA__RANGE_VALID__RANGE_VALID_bm);
}

// Check if destination is in the ICCM region.
static inline int dest_is_iccm(uint32_t dest, uint32_t n) {
    return contains_range_u32(SEP_TOP_SEP_ICCM_BASE_ADDR, SEP_TOP_SEP_ICCM_SIZE, dest, n);
}

// Claims the engine for one transfer. It must be idle, and DONE and ERROR left by
// an earlier transfer are cleared and seen clear, so they cannot be read as the
// outcome of this one. The engine drops configuration writes while it is busy.
static uint32_t dma_claim(void) {
    dma_write(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, DMA_STATUS_W1C);
    const uint32_t status = dma_read(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    const uint32_t held = DMA_STATUS_BUSY | DMA_STATUS_DONE | DMA_STATUS_ERROR;
    if ((status & held) != 0u || (harden_u32(status) & held) != 0u) {
        report_status(STATUS_TYPE_WARN, SEP_MSG_DMA_ERROR);
        simputshex32("DMA_STS=", status);
        return SEP_DMA_ERR_TRANSFER;
    }
    return 0u;
}

// One chunk of n bytes, 4-byte beats, OT internal address space at both ends.
static void dma_program(uint32_t dest, uint32_t src, uint32_t n, uint32_t src_config) {
    dma_write(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    dma_write(SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0u);
    dma_write(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dest);
    dma_write(SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0u);
    dma_write(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR,
              (0x7u << SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_bp) |
                  (0x7u << SECURE_DMA__ADDR_SPACE_ID__DST_ASID_bp));
    dma_write(SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, 0x2u);
    dma_write(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, src_config);
    dma_write(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, SECURE_DMA__DST_CONFIG__INCREMENT_bm);
    dma_write(SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, n);
    dma_write(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, n);
}

static int dma_completed(uint32_t status, uint32_t ecode) {
    return ((status & (DMA_STATUS_BUSY | DMA_STATUS_DONE | DMA_STATUS_ERROR)) == DMA_STATUS_DONE) &&
           (ecode == 0u);
}

// Starts the programmed transfer and waits for it, bounded so that an engine which
// neither finishes nor errors becomes a DMA error rather than a hang. n has been
// range-checked by the caller, so the budget cannot overflow.
static uint32_t dma_go_and_wait(uint32_t opcode, uint32_t dest, uint32_t src, uint32_t n) {
    (void)dest;
    (void)src;
    dma_write(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, SECURE_DMA__CONTROL__GO_bm |
                                                        SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm |
                                                        (opcode << SECURE_DMA__CONTROL__OPCODE_bp));

    const uint32_t poll_max = DMA_POLLS_SETUP + (n / 4u) * DMA_POLLS_PER_BEAT;
    uint32_t status = 0u;
    uint32_t polls = 0u;
    for (; polls < poll_max; ++polls) {
        status = dma_read(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (status & (DMA_STATUS_DONE | DMA_STATUS_ERROR)) {
            break;
        }
    }
    if (polls == poll_max) {
        // A WARN, since the caller decides whether the failure is terminal: a
        // manifest read can still fail over to the backup slot.
        report_status(STATUS_TYPE_WARN, SEP_MSG_DMA_TIMEOUT);
        simputshex32("DMA_TIMEOUT_STS=", status);
        simputshex32("DMA_DST=", dest);
        simputshex32("DMA_LEN=", n);
        // Stop the engine before returning, so it issues no further beats into
        // memory the caller goes on to reuse -- the next manifest slot, for one.
        dma_write(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, DMA_CTRL_ABORT);
        for (uint32_t i = 0u; i < DMA_POLLS_SETUP; ++i) {
            if (!(dma_read(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR) & DMA_STATUS_BUSY)) {
                break;
            }
        }
        return SEP_DMA_ERR_TRANSFER;
    }

    // Success needs two separate reads of STATUS and ERROR_CODE to agree, each
    // evaluated on its own, so one corrupted read or skipped check cannot pass a
    // failed transfer.
    status = dma_read(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    const uint32_t ecode = dma_read(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    const uint32_t status2 = dma_read(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    const uint32_t ecode2 = dma_read(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    const int ok = dma_completed(status, ecode);
    const int ok2 = dma_completed(harden_u32(status2), harden_u32(ecode2));
    if (!ok || !ok2) {
        report_status(STATUS_TYPE_WARN, SEP_MSG_DMA_ERROR);
        simputshex32("DMA_STS=", status);
        simputshex32("DMA_EC=", ecode);
        simputshex32("DMA_DST=", dest);
        simputshex32("DMA_SRC=", src);
        simputshex32("DMA_LEN=", n);
        return SEP_DMA_ERR_TRANSFER;
    }
    return 0u;
}

uint32_t sep_dma_copy(uint32_t dest, uint32_t src, size_t len) {
    const uint32_t n = (uint32_t)len;

    // Destination can be in SEP SRAM, SMC SRAM, or ICCM (for BL1 handoff).
    const uint32_t smc_sram = sep_get_smc_sram_base();
    if (!contains_range_u32(SEP_EXT_SRAM_BASE, SEP_SRAM_SIZE, dest, n) &&
        !contains_range_u32(smc_sram, SMC_SRAM_SIZE_BYTES, dest, n) && !dest_is_iccm(dest, n)) {
        report_status(STATUS_TYPE_WARN, SEP_MSG_DMA_OUT_OF_RANGE);
        return SEP_DMA_ERR_OUT_OF_RANGE;
    }

    // Source can be in SPI window, SMC SRAM, or SEP SRAM.
    if (!contains_range_u32(SEP_SPI_BASE, SEP_SPI_MAX_SIZE, src, n) &&
        !contains_range_u32(smc_sram, SMC_SRAM_SIZE_BYTES, src, n) &&
        !contains_range_u32(SEP_EXT_SRAM_BASE, SEP_SRAM_SIZE, src, n)) {
        report_status(STATUS_TYPE_WARN, SEP_MSG_DMA_OUT_OF_RANGE);
        return SEP_DMA_ERR_OUT_OF_RANGE;
    }

    const uint32_t err = dma_claim();
    if (err != 0u || harden_u32(err) != 0u) {
        return err != 0u ? err : SEP_DMA_ERR_TRANSFER;
    }
    dma_program(dest, src, n, SECURE_DMA__SRC_CONFIG__INCREMENT_bm);
    return dma_go_and_wait(0u, dest, src, n);
}

// A zero fill may target one of these regions, and the engine's enabled range is
// set to the whole of that region. The window comes from this table, not from the
// request, so a request corrupted after it was checked cannot widen it.
static int fill_region(uint32_t dest, uint32_t n, uint32_t *base, uint32_t *limit) {
    const uint32_t regions[3][2] = {
        {SEP_EXT_SRAM_BASE, SEP_SRAM_SIZE},
        {sep_get_smc_sram_base(), SMC_SRAM_SIZE_BYTES},
        {SEP_TOP_SEP_ICCM_BASE_ADDR, SEP_TOP_SEP_ICCM_SIZE},
    };
    for (uint32_t i = 0u; i < 3u; ++i) {
        if (contains_range_u32(regions[i][0], regions[i][1], dest, n)) {
            *base = regions[i][0];
            *limit = regions[i][0] + regions[i][1] - 1u;
            return 1;
        }
    }
    return 0;
}

// The registers a zero fill depends on, read back before the engine starts.
enum {
    FILL_RB_DST,
    FILL_RB_TOTAL,
    FILL_RB_CHUNK,
    FILL_RB_WIDTH,
    FILL_RB_DST_CONFIG,
    FILL_RB_BASE,
    FILL_RB_LIMIT,
    FILL_RB_COUNT
};

static const uint32_t fill_rb_addr[FILL_RB_COUNT] = {
    SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR,
    SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR,
    SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR,
    SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR,
    SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR,
    SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR,
    SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR,
};

static int fill_registers_match(const uint32_t *got, const uint32_t *want) {
    uint32_t diff = 0u;
    for (uint32_t i = 0u; i < FILL_RB_COUNT; ++i) {
        diff |= got[i] ^ want[i];
    }
    return (diff == 0u) &&
           contains_range_u32(got[FILL_RB_BASE], got[FILL_RB_LIMIT] - got[FILL_RB_BASE] + 1u,
                              got[FILL_RB_DST], got[FILL_RB_TOTAL]);
}

uint32_t sep_dma_zero(uint32_t dest, size_t len) {
    const uint32_t n = (uint32_t)len;
    uint32_t base = 0u;
    uint32_t limit = 0u;

    // ICCM and DCCM take only aligned word writes; the engine reports a narrow or
    // misaligned one as a bus error, so every fill is whole aligned words.
    if (n == 0u || (size_t)n != len || ((dest | n) & 3u) != 0u ||
        !fill_region(dest, n, &base, &limit)) {
        report_status(STATUS_TYPE_WARN, SEP_MSG_DMA_OUT_OF_RANGE);
        simputshex32("DMA_DST=", dest);
        simputshex32("DMA_LEN=", n);
        return SEP_DMA_ERR_OUT_OF_RANGE;
    }

    const uint32_t err = dma_claim();
    if (err != 0u || harden_u32(err) != 0u) {
        return err != 0u ? err : SEP_DMA_ERR_TRANSFER;
    }

    // Every write of a zero fill is checked against the enabled range.
    dma_write(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, base);
    dma_write(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, limit);
    dma_write(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, SECURE_DMA__RANGE_VALID__RANGE_VALID_bm);
    // The engine validates the source address and space but never reads it.
    dma_program(dest, 0u, n, 0u);

    const uint32_t want[FILL_RB_COUNT] = {
        dest, n, n, 0x2u, SECURE_DMA__DST_CONFIG__INCREMENT_bm, base, limit,
    };
    uint32_t got[FILL_RB_COUNT];
    uint32_t got2[FILL_RB_COUNT];
    uint32_t want2[FILL_RB_COUNT];
    for (uint32_t i = 0u; i < FILL_RB_COUNT; ++i) {
        got[i] = dma_read(fill_rb_addr[i]);
        got2[i] = harden_u32(got[i]);
        want2[i] = harden_u32(want[i]);
    }
    const int match = fill_registers_match(got, want);
    const int match2 = fill_registers_match(got2, want2);
    if (!match || !match2) {
        report_status(STATUS_TYPE_WARN, SEP_MSG_DMA_OUT_OF_RANGE);
        simputshex32("DMA_DST=", got[FILL_RB_DST]);
        simputshex32("DMA_LEN=", got[FILL_RB_TOTAL]);
        return SEP_DMA_ERR_OUT_OF_RANGE;
    }

    return dma_go_and_wait(SEP_DMA_OPCODE_ZERO, dest, 0u, n);
}
