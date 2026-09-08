/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OROM BL1 handoff: find image, copy to ICCM, jump.
//
// BL1 handoff sequence:
//   1. find_toc_entry(SEP_BL1) — scan TOC for BL1 image
//   2. sep_dma_copy()          — DMA BL1 from SRAM to its ICCM load address
//   3. jump_to_bl1()           — transfer control to BL1 entry point
//
// OROM BL1 handoff: find image, copy to SRAM, jump.
//
//   1. locate BL1 in the payload TOC via oca_toc_image_at()
//   2. sep_dma_copy() BL1 to the TOC entry's load address
//   3. jump_to_bl1()  -- transfer control
//
// BL1 executes from ICCM: the IFU fetches it there, and vector.S's warm-reset
// handler check only accepts an ICCM address.  Nothing BL1 loads or stores can
// be in ICCM, though, so the blob copied here is BL1's .text plus the load image
// of its .rodata/.data, and BL1's own _start copies that second part into DCCM --
// reading it from SRAM via bl0_state.bl1_image_src_addr, since the ICCM copy is
// not readable to it either.
//
// BL1 is a single flat binary linked to its load address. The payload is already
// staged and verified in SEP SRAM; this copies BL1 out of it so PC-relative and
// absolute references inside the binary resolve.

#include <stdint.h>

#include "bl0_state.h"
#include "errors.h"
#include "oca_boot.h"
#include "oca_validator.h"
#include "rom_virt_console.h"
#include "sep.h"
#include "sep_dma.h"
#include "sep_helpers.h"
#include "status_values.h"

// The image type BL1 is published under. 16 ASCII bytes: bytes[15:8] are a
// vendor string, bytes[7:0] the spec's recommended label (boot-manifest.adoc,
// "Payload TOC entry"). Matched in full rather than on the label alone so an
// image another vendor published as BLSTAGE1 cannot be booted here.
#define SEP_BL1_IMAGE_TYPE "TT_SEP  BLSTAGE1"

// Bytes zeroed past BL1's image so the IFU cannot fetch a word that was never
// written. The 64-bit fetch granule is the documented part; the rest is margin
// for sequential prefetch, whose depth is not specified. Unused when
// ROM_ICCM_CLEAR_FULL scrubs the whole region at [C9b].
#define ICCM_ECC_PAD_BYTES 256u

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// oca_image_info_t::type is a NUL-terminated 17-byte buffer holding the 16
// on-disk bytes, so a plain fixed-length compare is enough; no libc.
static bool type_matches(const char *type, const char *want) {
    for (uint32_t i = 0; i < 16u; ++i) {
        if (type[i] != want[i]) return false;
        if (want[i] == '\0') break;
    }
    return true;
}

// Scan the TOC for the first image of the wanted type.
static bool find_bl1(oca_image_info_t *out) {
    const uint8_t *payload = rom_oca_payload();
    size_t payload_len = rom_oca_payload_len();
    oca_toc_info_t toc;

    if (payload == NULL || oca_toc_info(payload, payload_len, &toc) != OCA_OK) {
        return false;
    }
    for (uint64_t i = 0; i < toc.image_count; ++i) {
        if (oca_toc_image_at(payload, payload_len, i, out) != OCA_OK) {
            return false;
        }
        if (type_matches(out->type, SEP_BL1_IMAGE_TYPE)) {
            return true;
        }
    }
    return false;
}

// The copy must go through the DMA, not a CPU memcpy. ICCM and DCCM share VeeR
// region 0xC, so el2_lsu_addrcheck treats any 0xCxxxxxxx address as DCCM's and
// faults the ones outside DCCM's offset range: a store to ICCM raises an
// unmapped access fault and never reaches the bus. The DMA engine is a separate
// crossbar master and does reach the ICCM window.

// Jump to BL1 entry point.  Does not return.
__attribute__((noreturn)) static void jump_to_bl1(uint32_t entry_addr) {
    // fence.i flushes IFU pipeline so freshly written ICCM code is visible.
    // fence completes pending stores.
    simputs("PRE_JUMP\n");
    __asm__ volatile("csrw mepc, %0\n"
                     "fence.i\n"
                     "fence\n"
                     "mret\n"
                     :
                     : "r"(entry_addr)
                     : "memory");
    __builtin_unreachable();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

uint32_t rom_handoff_bl1(void) {
    oca_image_info_t bl1;

    report_status(STATUS_TYPE_INFO, SEP_MSG_COPY_AND_EXEC_IMAGE);

    // -- Step 1: find BL1 --
    if (!find_bl1(&bl1)) {
        simputs("NO_BL1_IMAGE\n");
        report_status(STATUS_TYPE_ERROR, SEP_MSG_SEP_BL1_MISSING);
        return OCA_BOOT_ERR_NO_BL1;
    }

    uint32_t load_addr = (uint32_t)bl1.load_addr;
    uint32_t img_length = (uint32_t)bl1.length;
    uint32_t entry_off = (uint32_t)bl1.entry_point;

    report_status(STATUS_TYPE_INFO, SEP_MSG_BL1_FOUND);
    simputshex32("LOAD=", load_addr);
    simputshex32("LEN=", img_length);
    simputshex32("ENTRY=", entry_off);

    // The TOC entry's load_addr/entry_point are authenticated but arbitrary:
    // the library checks them for internal consistency, never against this
    // device's memory map. Confining the copy to a region BL1 may legally
    // occupy is the ROM's job.
    //
    // BOTH SEP SRAM and ICCM are legal (SEP-ROM-MAN-060). Placement is a
    // property of the image the manifest describes, not a ROM build option, so
    // the ROM honours whichever region the TOC entry names and refuses anything
    // outside both -- load_addr lives in the signed manifest but is still
    // attacker-chosen among valid images, so "in one of the two" is the check
    // that matters, not "equal to a constant this build was compiled for".
    //
    // The copy goes through the DMA either way: the LSU cannot store to ICCM at
    // all (it shares VeeR region 0xC with DCCM, so el2_lsu_addrcheck faults any
    // ICCM address), and the DMA engine reaches both. Bounds come from the
    // generated register map, so an RDL change moves them here too.
    // contains_range() rejects a length that would overflow, so no separate
    // size guard is needed.
    // ICCM is the secure execution space and is always permitted. SRAM is
    // permitted only when BL1_SRAM_EXEC_ENABLE is set -- it exists for debug and
    // special applications, and an adopter can compile it out to lock the ROM
    // down to ICCM-only execution. Default is enabled (see the Makefile knob).
    const bool sram_span =
        contains_range(OCH_SEP_TOP_SEP_SRAM_BASE_ADDR, OCH_SEP_TOP_SEP_SRAM_SIZE,
                       (size_t)bl1.load_addr, (size_t)bl1.length);
    const bool bl1_in_iccm =
        contains_range(OCH_SEP_TOP_SEP_ICCM_BASE_ADDR, OCH_SEP_TOP_SEP_ICCM_SIZE,
                       (size_t)bl1.load_addr, (size_t)bl1.length);
    const bool bl1_in_sram = (BL1_SRAM_EXEC_ENABLE != 0) && sram_span;

    if (!bl1_in_sram && !bl1_in_iccm) {
        // Distinguish "nowhere legal" from "would have been legal, but this
        // build forbids SRAM execution" -- otherwise an adopter who locks the
        // ROM down and then boots a debug image gets an unattributable range
        // error and no hint that a build flag caused it.
        if (sram_span) {
            simputs("BL1_SRAM_EXEC_DISABLED\n");
        }
        simputs("BL1_ADDR_RANGE\n");
        report_status(STATUS_TYPE_ERROR, SEP_MSG_BL1_BAD_ADDR);
        return OCA_BOOT_ERR_BL1_BAD_ADDR;
    }
    simputs(bl1_in_iccm ? "BL1_DST=ICCM\n" : "BL1_DST=SRAM\n");
    if (bl1.entry_point >= bl1.length) {
        simputs("BL1_ENTRY_RANGE\n");
        report_status(STATUS_TYPE_ERROR, SEP_MSG_BL1_ENTRY_INVALID);
        return OCA_BOOT_ERR_BL1_BAD_ADDR;
    }
    if (img_length == 0u) {
        simputs("BL1_SIZE\n");
        report_status(STATUS_TYPE_ERROR, SEP_MSG_BL1_SIZE_INVALID);
        return OCA_BOOT_ERR_BL1_TOO_LARGE;
    }

    img_length = (img_length + 3u) & ~3u;

#if ROM_ICCM_CLEAR_ENABLE && !ROM_ICCM_CLEAR_FULL
    // The copy below writes BL1's own words with valid ECC; this covers the
    // words past its end that the IFU may still fetch. pad_start rounds down to
    // the 64-bit ECC granule, so a granule holding both image and past-the-end
    // bytes is covered; the copy runs after the pad and restores the image
    // bytes in it. Clamped to ICCM so a BL1 sized near the top of the region
    // cannot push the pad out of bounds.
    if (bl1_in_iccm) {
        const uint32_t iccm_end = OCH_SEP_TOP_SEP_ICCM_BASE_ADDR + OCH_SEP_TOP_SEP_ICCM_SIZE;
        const uint32_t pad_start = (load_addr + img_length) & ~7u;
        if (pad_start < iccm_end) {
            uint32_t pad_len = iccm_end - pad_start;
            if (pad_len > ICCM_ECC_PAD_BYTES) {
                pad_len = ICCM_ECC_PAD_BYTES;
            }
            uint32_t pad_err = sep_dma_zero(pad_start, pad_len);
            if (pad_err) {
                simputs("ICCM_PAD_FAIL\n");
                return OCA_BOOT_ERR_BL1_BAD_ADDR;
            }
            simputshex32("ICCM_PAD=", pad_start);
        }
    }
#endif

    // ── Step 2: Copy BL1 to its ICCM load address ──
    report_status(STATUS_TYPE_INFO, SEP_MSG_BL1_COPY);
    simputshex32("COPY_SRC=", (uint32_t)(uintptr_t)bl1.bytes);
    simputshex32("COPY_DST=", load_addr);
    simputshex32("COPY_LEN=", img_length);

    uint32_t dma_err = sep_dma_copy(load_addr, (uint32_t)(uintptr_t)bl1.bytes, img_length);
    if (dma_err) {
        simputs("BL1_COPY_FAIL\n");
        report_status(STATUS_TYPE_ERROR, SEP_MSG_BL1_BAD_ADDR);
        return OCA_BOOT_ERR_BL1_BAD_ADDR;
    }
    simputs("BL1_COPIED\n");

    // BL1 needs the SRAM source, not the ICCM copy, to reach the load image of
    // its own .rodata/.data: it executes from ICCM but cannot read ICCM.
    get_bl0_state()->bl1_image_src_addr = (uint32_t)(uintptr_t)bl1.bytes;

    // ── Step 3: Jump to BL1 ──
    uint32_t entry_addr = load_addr + entry_off;

    report_status(STATUS_TYPE_INFO, SEP_MSG_EXEC_IMAGE);
    report_status(STATUS_TYPE_INFO, SEP_MSG_STARTING_BL1);
    report_status(STATUS_TYPE_INFO_EXT, (uint16_t)(entry_addr >> 16));
    report_status(STATUS_TYPE_INFO_EXT, (uint16_t)(entry_addr & 0xFFFF));
    simputshex32("BL1_JUMP=", entry_addr);

    jump_to_bl1(entry_addr);

    return OCA_BOOT_ERR_NO_BL1; // unreachable
}
