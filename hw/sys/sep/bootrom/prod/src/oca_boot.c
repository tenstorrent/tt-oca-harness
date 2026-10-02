/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OCA boot-manifest load and validation.
//
// The division of labour with the vendored library is deliberate and is the
// whole reason this file is short: the library never touches storage. It takes
// pointers to memory the caller has already filled, so everything here is about
// getting the right bytes into SEP SRAM and reporting what the library decided.
//
// The staged sequence (INTEGRATION.md "The staged flow"; reference
// implementation validators/oca/test/main.c validate_from_storage()):
//
//   oca_peek_manifest()          20 bytes, in place, decides the variant/size
//   copy body -> SEP SRAM        authenticate the COPY, never storage
//   oca_validate_manifest()
//   oca_payload_encryption_info()
//   oca_locate_payload()         bounds-checks the untrusted payload_offset
//   copy payload -> SEP SRAM
//   oca_check_payload_at()       payload hash, hash chain, per-entry hashes
//
// oca_commit_security_state() is deliberately NOT called: the ROM has no OTP
// programming path, so revocation and anti-rollback are enforced against the
// fuses but never advanced. See oca_platform.c.

#include "oca_boot.h"

#include "oca_layout.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "bl0_state.h"
#include "boot_flash.h"
#include "errors.h"
#include "oca_platform.h"
#include "oca_validator.h"
#include "oca_variant.h"
#include "rom_virt_console.h"
#include "sep.h"
#include "sep_dma.h"
#include "sep_smc_interface.h"
#include "status_values.h"

// SEP EXT SRAM: staging area for the manifest body and its payload.
#define SRAM_BASE ((uint32_t)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR) // 0x10000000
#define SRAM_SIZE ((uint32_t)OCH_SEP_TOP_SEP_SRAM_SIZE)      // 0x00040000 (256 KiB)

// Staged state, valid only after a successful rom_manifest_boot().
static const uint8_t *g_body;
static const uint8_t *g_payload;
static size_t g_payload_len;

const uint8_t *rom_oca_body(void) {
    return g_body;
}
const uint8_t *rom_oca_payload(void) {
    return g_payload;
}
size_t rom_oca_payload_len(void) {
    return g_payload_len;
}

const uint8_t *rom_oca_manifest_hash(void) {
    if (g_body == NULL) {
        return NULL;
    }

    // Located through the library's own variant descriptor rather than a literal
    // offset: manifest_hash sits at a different place in an OCA-classic body than
    // in an OCA-PQC one, and both move with the format revision. Asking the
    // library keeps this correct across a submodule uprev instead of silently
    // measuring the wrong 32 bytes.
    oca_result_t st = OCA_OK;
    const oca_variant_t *v = oca_variant_for_body(g_body, &st);
    if (v == NULL) {
        return NULL;
    }
    return g_body + v->off_manifest_hash;
}

uint32_t rom_oca_demotion_control(void) {
    if (g_body == NULL) {
        return 0u;
    }
    // Little-endian u16 at OCA_OFF_DEMOTION_CONTROL (172). Read by hand rather
    // than through the library: it exposes no accessor for this field, and the
    // meaning of the bits is vendor-defined anyway.
    return (uint32_t)g_body[172] | ((uint32_t)g_body[173] << 8);
}

// ---------------------------------------------------------------------------
// Storage transport
// ---------------------------------------------------------------------------

// With the OpenTitan host, a flash `src` is a byte offset read through the host.
// Otherwise `src` is an absolute address (XIP window or SMC SRAM) copied by the
// secure DMA.
static uint32_t manifest_src_read(uint32_t dst, uint32_t src, uint32_t len, bool from_spi) {
    // Every storage read on the boot path goes through the transport shim's
    // bounds gate first (SEP-ROM-SPI-010). It is the only check that the SOURCE
    // stays inside the boot slot being tried: the library bounds the payload's
    // LOCATION against the slot region, and the OpenTitan driver bounds the
    // DESTINATION, but neither re-checks the offset a read is finally issued
    // with. The gate is fault-injection hardened (doubled, laundered evaluation)
    // and defaults to reject.
    //
    // The gate speaks flash byte offsets. Through the XIP window `src` is an
    // absolute address, so the window base is taken back off; a source below
    // the window has no offset and is refused rather than wrapped. Non-SPI
    // sources (a manifest the SMC staged in its SRAM) are not flash and are
    // bounded by their own region, so the gate does not apply.
    if (from_spi) {
#if BOOT_SPI_CONTROLLER_OT
        const uint32_t flash_off = src;
#else
        if (src < SEP_XIP_BASE) {
            simputs("FLASH_READ_OOB\n");
            return OCA_BOOT_ERR_READ_OUT_OF_BOUNDS;
        }
        const uint32_t flash_off = src - SEP_XIP_BASE;
#endif
        if (!boot_flash_bounds_ok(flash_off, len, dst, len)) {
            simputs("FLASH_READ_OOB\n");
            return OCA_BOOT_ERR_READ_OUT_OF_BOUNDS;
        }
    }

    uint32_t rc;
#if BOOT_SPI_CONTROLLER_OT
    if (from_spi) {
        rc = boot_flash_read(dst, src, len);
    } else {
        rc = sep_dma_copy(dst, src, len);
    }
#else
    rc = sep_dma_copy(dst, src, len);
#endif
    return (rc == 0u) ? 0u : OCA_BOOT_ERR_DMA;
}

// Zero SEP SRAM between retry attempts so a partially staged bad slot cannot be
// mistaken for the next one's bytes.
static void clear_sram_region(uint32_t addr, uint32_t size) {
    volatile uint32_t *p = (volatile uint32_t *)(uintptr_t)addr;
    uint32_t words = size / 4u;
    for (uint32_t i = 0; i < words; ++i) {
        p[i] = 0u;
    }
}

// ---------------------------------------------------------------------------
// Reporting
// ---------------------------------------------------------------------------

// Map a library verdict onto the ROM's production status stream, so the status
// word names which check refused the image rather than that one did.
static uint16_t status_for_result(oca_result_t r) {
    switch (r) {
    case OCA_FAIL_MAGIC:
        return SEP_MSG_INVALID_MANIFEST_ID;
    case OCA_FAIL_TRAILER:
        return SEP_MSG_INVALID_MANIFEST_ID;
    case OCA_FAIL_TRUNCATED:
        return SEP_MSG_INVALID_MANIFEST_LENGTH;
    case OCA_FAIL_MANIFEST_LENGTH:
        return SEP_MSG_INVALID_MANIFEST_LENGTH;
    case OCA_FAIL_FORMAT_VERSION_MISMATCH:
        return SEP_MSG_INVALID_MANIFEST_VERSION;
    case OCA_FAIL_UNSUPPORTED_VARIANT:
        return SEP_MSG_INVALID_MANIFEST_VERSION;
    case OCA_FAIL_MANIFEST_HASH:
        return SEP_MSG_INVALID_MANIFEST_HASH;
    case OCA_FAIL_SIGNATURE:
        return SEP_MSG_INVALID_SIGNATURE;
    case OCA_FAIL_CRYPTO_FIELD_SIZE:
        return SEP_MSG_INVALID_SIGNATURE_TYPE;
    case OCA_FAIL_ROOT_KEY_REVOKED:
        return SEP_MSG_REVOKED_KEY;
    case OCA_FAIL_ROOT_KEY_UNAUTHORIZED:
        return SEP_MSG_INVALID_KEY_HASH;
    case OCA_FAIL_SECURITY_VERSION:
        return SEP_MSG_INVALID_SECURITY_VERSION;
    case OCA_FAIL_CHIPLET_ID:
        return SEP_MSG_INVALID_CHIPLET_ID;
    case OCA_FAIL_PACKAGE_ID:
        return SEP_MSG_INVALID_PACKAGE_ID;
    case OCA_FAIL_SYSTEM_ID:
        return SEP_MSG_INVALID_PACKAGE_ID;
    case OCA_FAIL_LIFECYCLE:
        return SEP_MSG_LIFECYCLE_INVALID;
    case OCA_FAIL_VERSION_RANGE:
        return SEP_MSG_INVALID_SECURITY_VERSION;
    case OCA_FAIL_PAYLOAD_LOCATION:
        return SEP_MSG_PAYLOAD_INVALID_LOCATION_FLASH;
    case OCA_FAIL_PAYLOAD_HASH:
        return SEP_MSG_PAYLOAD_HASH_INVALID;
    case OCA_FAIL_PAYLOAD_HASH_CHAIN:
        return SEP_MSG_PAYLOAD_HASH_INVALID;
    case OCA_FAIL_PAYLOAD_ENTRY_HASH:
        return SEP_MSG_TOC_HASH_INVALID;
    case OCA_FAIL_PAYLOAD_TOC:
        return SEP_MSG_TOC_ID_INVALID;
    case OCA_FAIL_PAYLOAD_TOO_MANY_IMAGES:
        return SEP_MSG_PAYLOAD_IMAGE_COUNT_INVALID;
    case OCA_FAIL_DECRYPT:
        return SEP_MSG_DECRYPTION_FAILED;
    case OCA_FAIL_NO_PROVISIONED_SECRET:
        return SEP_MSG_INVALID_KEY_CONTENTS;
    case OCA_FAIL_ENCRYPTION_REQUIRES_SECURE_BOOT:
        return SEP_MSG_MANIFEST_INVALID_ENCRYPTION;
    case OCA_FAIL_SECURE_BOOT_INVARIANT:
        return SEP_MSG_MANIFEST_SECURE_BOOT;
    case OCA_FAIL_SECURE_BOOT_UNDETERMINED:
        return SEP_MSG_MANIFEST_SECURE_BOOT;
    case OCA_FAIL_SECURE_BOOT_STATE_CHANGED:
        return SEP_MSG_MANIFEST_SECURE_BOOT;
    case OCA_FAIL_SIGNATURE_CLASS_CONTROL:
        return SEP_MSG_MANIFEST_SECURE_BOOT;
    default:
        return SEP_MSG_MANIFEST_LOAD_FAILED;
    }
}

// ---------------------------------------------------------------------------
// One slot attempt
// ---------------------------------------------------------------------------

// Load, authenticate and stage the manifest at `src_addr`, whose storage-space
// bounds are [region_base, region_limit). Returns 0 on success.
static uint32_t try_manifest_slot(uint32_t src_addr, bool from_spi, int64_t region_base,
                                  int64_t region_limit) {
    uint8_t *const body = (uint8_t *)(uintptr_t)SRAM_BASE;

    // -- peek ---------------------------------------------------------------
    // The head has to be in RAM before the library sees it: on the OpenTitan
    // path storage is not memory-mapped at all, so "peek in place" in the
    // reference CLI becomes "read the first cache line, then peek".
    uint32_t peek_err =
        manifest_src_read((uint32_t)(uintptr_t)body, src_addr, OCA_MANIFEST_PEEK_MIN, from_spi);
    if (peek_err != 0u) {
        return peek_err;
    }

    oca_manifest_peek_t pk;
    oca_result_t r = oca_peek_manifest(body, OCA_MANIFEST_PEEK_MIN, &pk);
    if (r != OCA_OK) {
        report_status(STATUS_TYPE_WARN, status_for_result(r));
        return OCA_BOOT_ERR_RESULT(r);
    }
    simputshex32("OCA_BODY=", (uint32_t)pk.body_size);

    if (pk.body_size > SRAM_SIZE) {
        return OCA_BOOT_ERR_STAGE_OVERFLOW;
    }

    // -- body ---------------------------------------------------------------
    uint32_t body_err =
        manifest_src_read((uint32_t)(uintptr_t)body, src_addr, (uint32_t)pk.body_size, from_spi);
    if (body_err != 0u) {
        return body_err;
    }

    // The manifest's CLAIMED security-version flags, before anything has
    // authenticated them. Echoed here rather than beside the device's own value
    // because rom_oca_body() deliberately means "the accepted slot's body" and is
    // still NULL at this point; the pair is recoverable from the order, and every
    // slot that reaches the comparison prints both.
    simputshex32("MFST_VER=", (uint32_t)body[OCA_OFF_MANIFEST_SECURITY_VERSION] |
                                  ((uint32_t)body[OCA_OFF_MANIFEST_SECURITY_VERSION + 1] << 8) |
                                  ((uint32_t)body[OCA_OFF_MANIFEST_SECURITY_VERSION + 2] << 16) |
                                  ((uint32_t)body[OCA_OFF_MANIFEST_SECURITY_VERSION + 3] << 24));

    // One context spans the whole staged sequence: authentication happens here,
    // the payload check happens further down, and the second needs to know what
    // the first established about secure-boot state.
    oca_validation_context_t vctx;
    oca_validation_context_init(&vctx);

    report_status(STATUS_TYPE_INFO, SEP_MSG_CHECK_MANIFEST_HASH);
    r = oca_validate_manifest(body, pk.body_size, sep_oca_callbacks(), &vctx);
    if (r != OCA_OK) {
        report_status(STATUS_TYPE_WARN, status_for_result(r));
        return OCA_BOOT_ERR_RESULT(r);
    }
    // Record the determination for the rest of the ROM and for BL1. The library
    // keeps it in the validation context, which does not outlive this function,
    // so it has to be copied into bl0_state. This is the field's only writer,
    // and rom_main.c reads it to decide whether to print SBOOT_OFF.
    //
    // `enabled` rather than `authenticated`: the field means "verification is
    // enforced for this boot". A manifest that reached here with it set has
    // also been verified, since oca_validate_manifest() would have refused
    // otherwise.
    get_bl0_state()->secure_boot = (vctx.secure_boot_enabled == OCA_SECURE_TRUE);

    report_status(STATUS_TYPE_INFO, SEP_MSG_MANIFEST_VALIDATED);
    simputs("MANIFEST_OK\n");

    // -- payload ------------------------------------------------------------
    oca_payload_encryption_t enc;
    r = oca_payload_encryption_info(body, &enc);
    if (r != OCA_OK) {
        report_status(STATUS_TYPE_WARN, status_for_result(r));
        return OCA_BOOT_ERR_RESULT(r);
    }

    // payload_offset lives in the manifest's UNSIGNED tail, so it is attacker
    // controlled even on a perfectly valid signed manifest. Handing the library
    // the region this slot is allowed to reach is what stops one bank naming
    // another bank's payload; manifest_src_read() then re-checks the offset the
    // read is finally issued with.
    oca_storage_bounds_t bounds;
    bounds.manifest_addr = (int64_t)src_addr;
    bounds.region_base = region_base;
    bounds.region_limit = region_limit;

    int64_t payload_addr = 0;
    size_t payload_span = 0u;
    r = oca_locate_payload(body, &bounds, &payload_addr, &payload_span);
    if (r != OCA_OK) {
        report_status(STATUS_TYPE_WARN, status_for_result(r));
        simputs("PAYLOAD_LOC_FAIL\n");
        return OCA_BOOT_ERR_RESULT(r);
    }
    if (payload_span == 0u) {
        // A manifest with no payload cannot boot this device even though the
        // library considers it valid.
        return OCA_BOOT_ERR_NO_BL1;
    }

    // Stage the payload immediately after the body, 8-byte aligned.
    uint32_t payload_off = ((uint32_t)pk.body_size + 7u) & ~7u;
    if (payload_span > (size_t)(SRAM_SIZE - payload_off)) {
        simputs("PAYLOAD_TOO_LARGE\n");
        return OCA_BOOT_ERR_STAGE_OVERFLOW;
    }
    uint8_t *const payload = body + payload_off;

    uint32_t payload_err = manifest_src_read((uint32_t)(uintptr_t)payload,
                                              (uint32_t)payload_addr, (uint32_t)payload_span,
                                              from_spi);
    if (payload_err != 0u) {
        return payload_err;
    }

    report_status(STATUS_TYPE_DEBUG, SEP_MSG_START_PAYLOAD_VALIDATION);
    r = oca_check_payload_at(body, payload, payload_span, sep_oca_callbacks(), &vctx, NULL);
    if (r != OCA_OK) {
        report_status(STATUS_TYPE_WARN, status_for_result(r));
        return OCA_BOOT_ERR_RESULT(r);
    }
    report_status(STATUS_TYPE_INFO, SEP_MSG_PAYLOAD_VALIDATED);
    // Console evidence that the payload was verified, not just staged: the DV
    // suite asserts on these strings rather than on the SEP_STATUS stream.
    simputs("PAYLOAD_OK\n");

    g_body = body;
    g_payload = payload;
    g_payload_len = payload_span;

    // A slot is only usable if its BL1 can actually be loaded, so the check
    // belongs here, inside the retry, rather than at hand-off: a missing or
    // unplaceable BL1 in the primary then fails over to the backup instead of
    // ending the boot after [S25] has locked the fuse secrets. Needs the
    // globals above, which is why it follows them; they are cleared again on
    // rejection so a failed slot leaves nothing staged.
    uint32_t bl1_err = rom_bl1_check();
    if (bl1_err != 0u) {
        g_body = NULL;
        g_payload = NULL;
        g_payload_len = 0u;
        return bl1_err;
    }

    get_bl0_state()->sep_sram_manifest_addr = (uint32_t)(uintptr_t)body;
    return 0u;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

uint32_t rom_manifest_boot(const struct boot_straps *straps, uint32_t spi_status) {
    const bool from_spi = boot_from_spi(straps);

    uint32_t offsets[2];
    uint32_t num_retries;
    int64_t region_base;
    int64_t region_limit;

    g_body = NULL;
    g_payload = NULL;
    g_payload_len = 0u;

    if (from_spi) {
        offsets[0] = PRIMARY_MANIFEST_OFFSET;
        offsets[1] = BACKUP_MANIFEST_OFFSET;
        num_retries = 1; // primary, then backup
        // Set per slot in the retry loop.
        region_base = 0;
        region_limit = 0;
    } else {
        // Recovery or secondary: the SMC places a manifest in its SRAM and
        // publishes the offset. On a real part it got there over I3C; from the
        // ROM's side this is just another address space.
        report_status(STATUS_TYPE_INFO, SEP_MSG_WAIT_FOR_SMC_MANIFEST_READY);
        simputs("WAIT_SMC_MANIFEST\n");
        for (;;) {
            uint32_t status = smc_scratch_read(SMC_SCRATCH_STATUS_TO_SEP_IDX);
            if (status & SMC_SEP_STATUS_MANIFEST_READY) break;
        }
        offsets[0] = smc_scratch_read(SMC_SCRATCH_MANIFEST_ADDR_IDX);
        offsets[1] = offsets[0];
        num_retries = 0; // single attempt
        region_base = (int64_t)sep_get_smc_sram_base();
        region_limit = region_base + (int64_t)SMC_SRAM_SIZE_BYTES;
    }

    uint32_t last_err = 0u;

    for (uint32_t retry = 0; retry <= num_retries; ++retry) {
        // rotate_update swaps which slot is tried first.
        uint32_t slot = retry;
        if (straps->rotate_update) {
            slot ^= 1u;
        }
        uint32_t offset = offsets[slot];

        if (from_spi && retry == 0u && spi_status) {
            simputs("SPI init failed, using backup manifest\n");
            continue;
        }

        uint32_t manifest_src;
        if (from_spi) {
#if BOOT_SPI_CONTROLLER_OT
            manifest_src = offset;
#else
            manifest_src = SEP_XIP_BASE + offset;
#endif
            // The slot's own window, so its payload_offset cannot reach the other slot.
            region_base = (int64_t)manifest_src;
            region_limit =
                region_base + (int64_t)BOOT_SLOT_SIZE - (int64_t)BOOT_SLOT_MANIFEST_OFFSET;
        } else {
            manifest_src = sep_get_smc_sram_base() + offset;
        }

        report_status(STATUS_TYPE_INFO, SEP_MSG_MANIFEST_LOAD_START);
        // Keyed on the SLOT, not the retry counter. rotate_update swaps the
        // order, so retry 0 can be the backup slot -- labelling by retry made
        // the marker say PRIMARY while MANIFEST_SRC showed 0x41000.
        simputs(slot == 0u ? "MANIFEST_PRIMARY\n" : "MANIFEST_BACKUP\n");
        simputshex32("MANIFEST_SRC=", manifest_src);

        uint32_t err = try_manifest_slot(manifest_src, from_spi, region_base, region_limit);
        if (err != 0u) {
            simputshex32("MANIFEST_ERR=", err);
            last_err = err;
            if (from_spi && retry < num_retries) {
                clear_sram_region(SRAM_BASE, SRAM_SIZE);
                boot_flash_reinit();
            }
            continue;
        }
        return 0u;
    }

    // Every slot is gone, so now it IS a boot failure. Re-report the last slot's
    // verdict as an ERROR before the generic code: during the retry loop each
    // verdict was only a WARN, because a slot the backup recovers from must not
    // look like a failed boot to anything watching the production stream. The
    // low byte of an OCA_BOOT_ERR_RESULT carries the library's oca_result_t, so
    // the specific reason survives without being tracked separately.
    if ((last_err & 0xFFFFFF00u) == OCA_BOOT_ERR_BASE) {
        report_status(STATUS_TYPE_ERROR, status_for_result((oca_result_t)(last_err & 0xFFu)));
    }
    report_status(STATUS_TYPE_ERROR, SEP_MSG_MANIFEST_LOAD_FAILED);
    simputs("MANIFEST_ALL_FAILED\n");
    return last_err;
}
