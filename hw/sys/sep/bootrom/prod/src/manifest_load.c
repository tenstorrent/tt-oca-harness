/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OROM manifest loading and validation.
//
// Manifest format uses manifest_t (1184 bytes), TOC header
// + toc_entry[]).  See manifest.h for structure definitions.
//
// Flow for BL0 tasks C12-C14:
//   1. Determine manifest source (SPI flash vs SMC SRAM)
//   2. Try primary slot; on failure, try backup (SPI only)
//   3. For each attempt: load header -> validate -> integrity check ->
//      load payload (contains TOC + images) -> validate payload
//   4. On success, update BL0 state with manifest address
//
// Manifest hash verification (C13.6) uses the HMAC SHA-256 hardware driver.
// Secure boot (C13.5) follows the ROM policy: PROD/PROD_END always enforce.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "manifest.h"
#include "boot_straps.h"
#include "hmac_sha256.h"
#include "lifecycle.h"
#include "sep_dma.h"
#include "sep_spi.h"
#include "boot_flash.h"
#include "errors.h"
#include "rom_smc.h"
#include "bl0_state.h"
#include "manifest_crypto.h"
#include "sep_helpers.h"

// Generated register map for OCAH SEP.
#include "sep.h"
#include "sep_smc_interface.h"

// SEP EXT SRAM: staging area for manifest and payload.
#define SRAM_BASE ((uint32_t)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR) // 0x10000000
#define SRAM_SIZE ((uint32_t)OCH_SEP_TOP_SEP_SRAM_SIZE)      // 0x00040000 (256 KiB)

// AES-CBC block size. Used only as the upper bound on how far an encrypted
// payload's manifest length may exceed the plaintext length its TOC reports:
// the packer PKCS#7-pads before encrypting, and PKCS#7 appends between 1 and a
// full block.
#define AES_CBC_BLOCK_BYTES 16u

// SPI XIP region size (for payload location check).
#ifndef SEP_SPI_MAX_SIZE
#define SEP_SPI_MAX_SIZE ((uint32_t)OCH_SEP_TOP_SEP_EXTERNAL_XIP_REGION_SIZE)
#endif

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// Constant-time byte comparison (prevents timing side-channel).
static bool const_time_eq(const uint8_t *a, const uint8_t *b, uint32_t len) {
    volatile uint8_t diff = 0;
    for (uint32_t i = 0; i < len; ++i) {
        diff |= a[i] ^ b[i];
    }
    return diff == 0;
}

static bool is_known_image_type(uint64_t type) {
    static const uint64_t known_image_types[] = {
        IMAGE_TYPE_SEP_BL1,
        IMAGE_TYPE_SEP_BL2,
        IMAGE_TYPE_SMC_BL1,
        IMAGE_TYPE_SMC_BL2,
    };

    for (uint32_t i = 0; i < sizeof(known_image_types) / sizeof(known_image_types[0]); ++i) {
        if (known_image_types[i] == type) {
            return true;
        }
    }

    return false;
}

// ── C13.6 (integrity): Verify manifest hash (SHA-256 of TBS region) ──
// TBS = all fields from offset 0 up to (but not including) the signature
// field.  This is always checked regardless of secure boot state.
static uint32_t manifest_check_integrity(const manifest_t *m) {
    report_status(STATUS_TYPE_INFO, SEP_MSG_CHECK_MANIFEST_HASH);

    // TBS region: from start of manifest to the signature field.
    const uint8_t *tbs = (const uint8_t *)m;
    uint32_t tbs_len = (uint32_t)((const uint8_t *)&m->signature - tbs);
    uint8_t digest[32];

    if (sha256(tbs, tbs_len, digest) != 0) {
        simputs("MANIFEST_HASH_TIMEOUT\n");
        return MANIFEST_ERR_HASH_MISMATCH;
    }

    if (!const_time_eq(digest, m->manifest_hash, 32)) {
        simputs("MANIFEST_HASH_MISMATCH\n");
        report_status(STATUS_TYPE_ERROR, SEP_MSG_INVALID_MANIFEST_HASH);
        return MANIFEST_ERR_HASH_MISMATCH;
    }

    simputs("MANIFEST_HASH_OK\n");
    return MANIFEST_OK;
}

// Read manifest data into SRAM. For the OpenTitan controller the flash is not
// memory-mapped, so `src` is a flash byte-offset read through the SPI host;
// otherwise `src` is an absolute address (Cadence XIP window or SMC SRAM) copied
// by the secure DMA. Returns 0 on success.
static uint32_t manifest_src_read(uint32_t dst, uint32_t src, uint32_t len, bool from_spi) {
#if BOOT_SPI_CONTROLLER_OT
    if (from_spi) {
        return boot_flash_read(dst, src, len);
    }
#else
    (void)from_spi;
#endif
    return sep_dma_copy(dst, src, len);
}

// Load the manifest header (1184 bytes) from source.
static uint32_t load_manifest_header(manifest_t *dest, uint32_t src_addr, bool from_spi) {
    uint32_t err =
        manifest_src_read((uint32_t)dest, src_addr, (uint32_t)sizeof(manifest_t), from_spi);
    return err ? MANIFEST_ERR_DMA_FAILED : MANIFEST_OK;
}

// Validate manifest header fields (no crypto).
// Applies the ROM's manifest sanity checks.
static uint32_t validate_manifest_header(const manifest_t *m) {
    // Check manifest identifier ("TBL1").
    if (m->manifest_identifier != MANIFEST_ID_TBL1) {
        return MANIFEST_ERR_BAD_MAGIC;
    }

    // Check manifest version.
    if (m->manifest_version_major != MANIFEST_MAJOR_VERSION) {
        return MANIFEST_ERR_BAD_VERSION;
    }

    // Check manifest length.
    if (m->manifest_version_minor == 0) {
        // v1.0: exact match required.
        if (m->manifest_length != (uint32_t)sizeof(manifest_t)) {
            return MANIFEST_ERR_BAD_LENGTH;
        }
    } else {
        // v1.x: must be >= sizeof(manifest_t) and <= MANIFEST_MAX_SIZE.
        if (m->manifest_length < (uint32_t)sizeof(manifest_t) ||
            m->manifest_length > MANIFEST_MAX_SIZE) {
            return MANIFEST_ERR_BAD_LENGTH;
        }
    }

    // Alignment check.
    if (m->manifest_length % 4u != 0u) {
        return MANIFEST_ERR_BAD_LENGTH;
    }

    // payload_offset and payload_length are 64-bit in the manifest but every
    // consumer below truncates them to 32 bits. Range-check the full width
    // first, or a value above 4 GiB silently becomes a small in-range one and
    // every later bound is computed against the wrong number.
    if (m->boot_arguments.payload_offset > (int64_t)0x7FFFFFFF ||
        m->boot_arguments.payload_offset < -(int64_t)0x7FFFFFFF) {
        simputs("PAYLOAD_OFF_RANGE\n");
        return MANIFEST_ERR_BAD_LENGTH;
    }
    if (m->payload_length > (uint64_t)0xFFFFFFFFu) {
        simputs("PAYLOAD_LEN_RANGE\n");
        return MANIFEST_ERR_PAYLOAD_TOO_LARGE;
    }

    // payload_offset (int64_t in boot_arguments) must be positive and sane.
    int32_t p_off = (int32_t)m->boot_arguments.payload_offset;
    if (p_off <= 0) {
        return MANIFEST_ERR_BAD_LENGTH;
    }

    // The payload is DMA'd and then read as a TOC of 64-bit fields, so the
    // whole region has to start 8-byte aligned.
    if (((uint32_t)p_off & 7u) != 0u) {
        simputs("PAYLOAD_OFF_ALIGN\n");
        return MANIFEST_ERR_BAD_LENGTH;
    }

    // payload_length must be non-zero (must at least contain a TOC header).
    uint32_t p_len = (uint32_t)m->payload_length;
    if (p_len == 0u) {
        return MANIFEST_ERR_BAD_LENGTH;
    }

    // payload_hashed_length bounds. verify_payload_hash() returns OK when this
    // is 0, so leaving it unchecked lets a manifest opt out of its own payload
    // hash entirely -- the digest is simply never computed. Requiring a non-zero
    // value that cannot exceed the payload closes that, and for an encrypted
    // payload the hash must cover all of it: the packer hashes the whole
    // already-encrypted blob, so a shorter length would leave ciphertext
    // unauthenticated while still appearing to verify.
    uint64_t h_len = m->payload_hashed_length;
    if (h_len == 0u || h_len > (uint64_t)p_len) {
        simputshex32("PAYLOAD_HASHED_LEN_BAD=", (uint32_t)h_len);
        return MANIFEST_ERR_BAD_LENGTH;
    }
    if ((m->usage_constraints.flags & (1u << USAGE_CONSTRAINTS_FLAGS_BIT_ENCRYPTED_PAYLOAD)) &&
        h_len != (uint64_t)p_len) {
        simputs("ENC_HASHED_LEN_PARTIAL\n");
        return MANIFEST_ERR_BAD_LENGTH;
    }

    // Everything (manifest + payload) must fit in SRAM.
    uint32_t total = (uint32_t)p_off + p_len;
    if (total < (uint32_t)p_off) { // overflow
        return MANIFEST_ERR_PAYLOAD_TOO_LARGE;
    }
    if (total > SRAM_SIZE) {
        return MANIFEST_ERR_PAYLOAD_TOO_LARGE;
    }

    // Payload must not overlap with manifest header region.
    // payload_offset is relative to manifest start; if it's smaller than
    // manifest_length, the payload would overwrite part of the header.
    // This is the payload/header overlap check.
    if ((uint32_t)p_off < m->manifest_length) {
        simputs("PAYLOAD_OVERLAPS_MANIFEST\n");
        report_status(STATUS_TYPE_ERROR, SEP_MSG_PAYLOAD_OVERLAPS_MANIFEST);
        return MANIFEST_ERR_PAYLOAD_OVERLAP;
    }

    return MANIFEST_OK;
}

// If manifest_length > sizeof(manifest_t), load the extra bytes (v1.x extension).
static uint32_t load_manifest_extra(manifest_t *m, uint32_t src_addr, bool from_spi) {
    uint32_t hdr_size = (uint32_t)sizeof(manifest_t);
    if (m->manifest_length <= hdr_size) {
        return MANIFEST_OK;
    }
    uint32_t remaining = m->manifest_length - hdr_size;
    uint32_t err =
        manifest_src_read((uint32_t)m + hdr_size, src_addr + hdr_size, remaining, from_spi);
    return err ? MANIFEST_ERR_DMA_FAILED : MANIFEST_OK;
}

// Load payload data (TOC + image data) from source to SEP SRAM.
static uint32_t load_payload(const manifest_t *m, uint32_t src_addr) {
    uint32_t p_len = (uint32_t)m->payload_length;
    if (p_len == 0u) {
        return MANIFEST_OK;
    }
    // manifest_payload_address() uses the already-adjusted payload_offset
    // to compute the SRAM destination.
    uint32_t dest = (uint32_t)(uintptr_t)manifest_payload_address(m);
    // Source in flash/SMC SRAM: original source + payload_offset.
    // At this point boot_arguments.payload_offset has been adjusted to
    // point from the SRAM manifest location, but we need the original
    // flash offset.  We compute it from the known SRAM base.
    int32_t p_off_original = (int32_t)(dest - src_addr);
    uint32_t src = src_addr + (uint32_t)p_off_original;
    uint32_t err = sep_dma_copy(dest, src, p_len);
    return err ? MANIFEST_ERR_DMA_FAILED : MANIFEST_OK;
}

// ── C13.5: Secure boot decision framework ──
// Secure-boot decision:
//   - sboot_dis fuse → always disable (chicken bit)
//   - PROD/PROD_END → always enforce, regardless of manifest flag
//   - TEST_DEV/RMA → secure boot is enabled only if the manifest flag requests it
// lc_state and sboot_dis are ARGUMENTS, never re-read from bl0_state: that
// struct is zeroed wholesale by init_bl0_state(), so a decision that reads it
// back is only as correct as the call ordering. Taking them by value makes this
// verdict independent of any later reordering.
static bool secure_boot_enabled(const manifest_t *m, uint32_t lc_state, bool sboot_dis) {
    if (sboot_dis) return false;

    bool mfst_flag = (m->boot_arguments.flag_args & (1u << FLAG_ARGS_BIT_SECURE_BOOT)) != 0;

    // In TEST_DEV or RMA states, the manifest flag decides whether secure boot is enabled.
    // In PROD/PROD_END, secure boot is always enforced.
    if (!mfst_flag && (lc_state == LC_STATE_TEST_DEV || lc_state_is_rma(lc_state))) return false;

    return true;
}

// ── C13.11: Validate payload structure (TOC header + entries) ──
static uint32_t validate_manifest_payload(const manifest_t *m) {
    const struct toc_header *toc = (const struct toc_header *)manifest_payload_address(m);

    // Validate TOC header magic.
    if (toc->identifier != TOC_HEADER_MAGIC_WORD) {
        return MANIFEST_ERR_BAD_TOC_ID;
    }

    // Validate TOC version.
    if (toc->major_version != TOC_MAJOR_VERSION) {
        return MANIFEST_ERR_BAD_TOC_VERSION;
    }

    // Validate image count.
    uint32_t n = (uint32_t)toc->image_count;
    if (n == 0u || n > 256u) {
        return MANIFEST_ERR_TOC_COUNT;
    }

    uint32_t p_len = (uint32_t)m->payload_length;

    // The TOC header and its n entries were read before this point, so confirm
    // the payload was ever big enough to hold them. Without this, a small
    // payload with a large image_count reads entries from beyond the DMA'd
    // region -- whatever happens to follow it in SRAM -- and validates those.
    uint32_t toc_bytes =
        (uint32_t)sizeof(struct toc_header) + n * (uint32_t)sizeof(struct toc_entry);
    if (toc_bytes < n || toc_bytes > p_len) {
        simputshex32("TOC_REGION_OOB=", toc_bytes);
        return MANIFEST_ERR_PAYLOAD_TOO_LARGE;
    }

    // The TOC repeats the payload length, and the two must not contradict the
    // bounds every check below relies on.
    //
    // For a plaintext payload they describe the same bytes and must agree
    // exactly. For an encrypted one they do NOT: the manifest records the
    // ciphertext length the DMA transferred, while the TOC only becomes
    // readable after decryption and records the plaintext content length. The
    // packer pads with PKCS#7 before encrypting (tt-boot-manifest
    // aes128cbc.py), which appends a whole block when the plaintext is already
    // block-aligned, so the manifest length legitimately runs up to one AES
    // block ahead of the TOC's.
    //
    // The property worth enforcing in both cases is that the TOC cannot claim
    // more than was actually loaded; the padding bound keeps the slack from
    // being an arbitrary amount of unaccounted payload.
    const uint64_t toc_p_len = (uint64_t)toc->payload_length;
    const bool encrypted =
        (m->usage_constraints.flags & (1u << USAGE_CONSTRAINTS_FLAGS_BIT_ENCRYPTED_PAYLOAD)) != 0u;
    const bool plen_bad = encrypted ? (toc_p_len > m->payload_length ||
                                       m->payload_length - toc_p_len > AES_CBC_BLOCK_BYTES)
                                    : (toc_p_len != m->payload_length);
    if (plen_bad) {
        simputshex32("TOC_PLEN_MISMATCH=", (uint32_t)toc_p_len);
        return MANIFEST_ERR_BAD_LENGTH;
    }

    uint32_t prev_end = toc_bytes; // images start after the TOC region
    bool bl1_found = false;

    for (uint32_t i = 0; i < n; ++i) {
        const struct toc_entry *e = &toc->images[i];

        // Check image type is known.
        if (!is_known_image_type(e->type)) {
            return MANIFEST_ERR_BAD_IMAGE_TYPE;
        }

        // Check offset + length within payload bounds.
        uint32_t off = (uint32_t)e->offset;
        uint32_t len = (uint32_t)e->length;
        uint32_t end = off + len;
        if (end < off) { // overflow
            return MANIFEST_ERR_IMAGE_OOB;
        }
        if (end > p_len) {
            return MANIFEST_ERR_IMAGE_OOB;
        }

        // Image bodies must start after the TOC region and run in strictly
        // ascending order. Ascending order is what makes prev_end a sufficient
        // bound: it turns overlap detection into a single comparison and, with
        // the gap zeroization below, means every byte of the payload is either
        // inside a validated image or has been cleared.
        if (off < prev_end) {
            simputshex32("IMAGE_ORDER_BAD idx=", i);
            return MANIFEST_ERR_IMAGE_OVERLAP;
        }
        if (e->length == 0u) {
            simputshex32("IMAGE_LEN_ZERO idx=", i);
            return MANIFEST_ERR_IMAGE_OOB;
        }
        if ((len & 3u) != 0u) {
            simputshex32("IMAGE_LEN_ALIGN idx=", i);
            return MANIFEST_ERR_IMAGE_OOB;
        }

        // Clear the gap between the previous image and this one. Those bytes
        // were DMA'd in and are covered by no TOC entry, so nothing validates
        // them; leaving them means BL1 inherits attacker-chosen data sitting
        // between the images it does trust.
        if (off > prev_end) {
            explicit_memzero((uint8_t *)(uintptr_t)toc + prev_end, off - prev_end);
        }
        prev_end = end;

        // Check no overlap with any earlier entry.
        for (uint32_t j = 0; j < i; ++j) {
            uint32_t b_off = (uint32_t)toc->images[j].offset;
            uint32_t b_len = (uint32_t)toc->images[j].length;
            uint32_t b_end = b_off + b_len;
            if (off < b_end && b_off < end) {
                return MANIFEST_ERR_IMAGE_OVERLAP;
            }
        }

        // Per-image hash, over the image body, against the digest in its TOC
        // entry. This runs after the bounds check above so only bytes already
        // proven to lie inside the payload are hashed.
        //
        // This is a distinct guarantee from the manifest payload_hash: that one
        // covers a single contiguous blob and only for the payload_hashed_length
        // it spans, so it binds the images only transitively and only as far as
        // that length reaches. The per-entry digest binds each image body on its
        // own. Image offsets are relative to the TOC, which is the start of the
        // payload, so the same base is used here as for the bounds check.
        uint8_t img_digest[32];
        if (sha256((const uint8_t *)toc + off, len, img_digest) != 0) {
            simputs("IMAGE_HASH_TIMEOUT\n");
            return MANIFEST_ERR_IMAGE_HASH_MISMATCH;
        }
        if (!const_time_eq(img_digest, e->hash, 32)) {
            simputshex32("IMAGE_HASH_MISMATCH idx=", i);
            return MANIFEST_ERR_IMAGE_HASH_MISMATCH;
        }

        // BL1 must be present and loadable, and that is decided HERE rather than
        // at handoff. rom_handoff_bl1() repeats these checks, but by the time it
        // runs the slot has already been accepted, the crypto chain has passed
        // and the fuse secrets are locked -- so a manifest with no usable BL1
        // ended the boot outright instead of failing this slot and letting
        // rom_manifest_boot() try the backup.
        if (e->type == IMAGE_TYPE_SEP_BL1) {
            uint32_t chk = check_bl1_image(e);
            if (chk != 0u) {
                simputs(chk == 1u ? "BL1_ADDR_RANGE\n" : "BL1_ENTRY_RANGE\n");
                return MANIFEST_ERR_BL1_BAD_ADDR;
            }
            bl1_found = true;
        }
    }

    if (!bl1_found) {
        simputs("NO_BL1_IMAGE\n");
        return MANIFEST_ERR_NO_BL1_IMAGE;
    }

    // Same reasoning as the inter-image gaps, for the tail after the last one.
    if (p_len > prev_end) {
        explicit_memzero((uint8_t *)(uintptr_t)toc + prev_end, p_len - prev_end);
    }

    return MANIFEST_OK;
}

// Attempt one manifest slot: load -> validate -> integrity -> payload.
static uint32_t try_manifest_slot(manifest_t *dest, uint32_t src_addr, bool from_spi,
                                  uint32_t lc_state, bool sboot_dis) {
    uint32_t err;

#if BOOT_SPI_CONTROLLER_OT
    // OpenTitan controller: validate the header read is in bounds before issuing
    // it (redundant, default-reject bounds gate). Applies to the SPI path only.
    if (from_spi && !boot_flash_bounds_ok(src_addr, (uint32_t)sizeof(manifest_t), (uint32_t)dest,
                                          (uint32_t)sizeof(manifest_t))) {
        report_status(STATUS_TYPE_ERROR, SEP_MSG_SPI_OT_BOUNDS_ERROR);
        return MANIFEST_ERR_PAYLOAD_BAD_LOC;
    }
#endif

    // C13.4: Load the manifest header (1184 bytes).
    err = load_manifest_header(dest, src_addr, from_spi);
    if (err) return err;

    // C13.6 (structure): Validate manifest fields.
    err = validate_manifest_header(dest);
    if (err) return err;

    // Adjust payload_offset: after DMA to SRAM, the manifest sits at
    // a different address than in flash. payload_offset remains relative
    // to the copied manifest in SRAM so manifest_payload_address() points
    // at the staged payload correctly.
    // Original: payload_offset = distance from manifest in flash to payload in flash.
    // After DMA: manifest is at dest, but payload_offset still points to flash.
    // Adjustment: payload_offset += (src_addr - (uint32_t)dest)
    // so manifest_payload_address(dest) = dest + adjusted_offset
    //   = dest + original_offset + src_addr - dest = src_addr + original_offset
    // Then after payload DMA, it will point correctly.
    // Actually: We need payload_address to be in SRAM (where payload will be DMA'd).
    // We want: dest + payload_offset = SRAM location of payload
    // Original payload_offset says: flash_addr + payload_offset = flash payload location
    // So keep payload_offset as-is; it's relative to manifest start.
    // manifest_payload_address(dest) = dest + payload_offset = SRAM payload addr.
    // This is correct IF we DMA payload from (src_addr + payload_offset) to (dest +
    // payload_offset). No adjustment needed when payload_offset is stored relative to manifest
    // start.

    // C13.6 (integrity): Verify manifest hash.
    err = manifest_check_integrity(dest);
    if (err) return err;

    // C13.5: Determine secure boot state.
    const bool sb = secure_boot_enabled(dest, lc_state, sboot_dis);
    get_bl0_state()->secure_boot = sb;

    // An encrypted payload without secure boot is rejected outright. The
    // decryption key is derived from a fuse, so with secure boot off nothing
    // authenticates the manifest that selects it -- and the ciphertext would
    // reach the TOC check undecrypted anyway, failing as a malformed TOC and
    // hiding the real reason.
    if (!sb &&
        (dest->usage_constraints.flags & (1u << USAGE_CONSTRAINTS_FLAGS_BIT_ENCRYPTED_PAYLOAD))) {
        simputs("ENC_WITHOUT_SBOOT\n");
        return MANIFEST_ERR_LC_USAGE_CONSTRAINT;
    }

    // C13.7: Validate usage constraints.
    // Checks selector_bits to decide which constraints to enforce.
    {
        uint64_t sel = dest->usage_constraints.selector_bits;

        // Wait for SMC fuse sense to complete before reading SMC fuse map
        // (chiplet_id / package_id). In cold reset this is normally done
        // by the time we get here, but in warm/cool reset paths HW may
        // not enforce it. Wait unconditionally.
        {
            uint8_t sel_ids = (uint8_t)(sel & 0xFFu) | (uint8_t)((sel >> 8) & 0xFFu);
            if (sel_ids) {
                // Only wait if we actually need to read SMC fuse map.
                for (int i = 0; i < 1000000; ++i) {
                    uint32_t fss =
                        mmio_read32(OCH_SEP_TOP_SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_BASE_ADDR);
                    if (fss & 0x1u) break; // smc_fuse_sense_done
                }
            }
        }

        // C13.7a: Life cycle state check.
        if (sel & (1ull << SELECTOR_BIT_LIFE_CYCLE_STATES)) {
            report_status(STATUS_TYPE_INFO, SEP_MSG_CHECK_USAGE_CONSTRAINTS);
            int bit = lc_state_to_manifest_bit(lc_state);
            uint32_t allowed = dest->usage_constraints.life_cycle_states;
            if (bit < 0 || !(allowed & (1u << (uint32_t)bit))) {
                simputs("LC_USAGE_CONSTRAINT_FAIL\n");
                simputshex32("LC_ALLOWED=", allowed);
                simputshex32("LC_BIT=", (uint32_t)bit);
                return MANIFEST_ERR_LC_USAGE_CONSTRAINT;
            }
        }

        // C13.7b: chiplet_id check (selector_bits[0..7]).
        // Reference logic for chiplet_id checking.
        {
            uint32_t smc_base = sep_get_smc_base();
            uint8_t sel_lo = (uint8_t)(sel & 0xFFu); // bits [0..7]
            for (uint32_t i = 0; i < DEVICE_ID_NUM_WORDS; ++i) {
                if (!(sel_lo & (1u << i))) continue;
                uint32_t fuse_val = mmio_read32(smc_base + SMC_FUSE_MAP_CHIPLET_ID_OFFSET + i * 4u);
                if (dest->usage_constraints.chiplet_id[i] != fuse_val) {
                    simputs("CHIPLET_ID_MISMATCH\n");
                    simputshex32("CID_IDX=", i);
                    simputshex32("CID_FUSE=", fuse_val);
                    simputshex32("CID_MFST=", dest->usage_constraints.chiplet_id[i]);
                    return MANIFEST_ERR_LC_USAGE_CONSTRAINT;
                }
            }
        }

        // C13.7c: package_id check (selector_bits[8..15]).
        // Reference logic for package_id checking.
        {
            uint32_t smc_base = sep_get_smc_base();
            uint8_t sel_hi = (uint8_t)((sel >> 8) & 0xFFu); // bits [8..15]
            for (uint32_t i = 0; i < DEVICE_ID_NUM_WORDS; ++i) {
                if (!(sel_hi & (1u << i))) continue;
                uint32_t fuse_val = mmio_read32(smc_base + SMC_FUSE_MAP_PACKAGE_ID_OFFSET + i * 4u);
                if (dest->usage_constraints.package_id[i] != fuse_val) {
                    simputs("PACKAGE_ID_MISMATCH\n");
                    simputshex32("PID_IDX=", i);
                    simputshex32("PID_FUSE=", fuse_val);
                    simputshex32("PID_MFST=", dest->usage_constraints.package_id[i]);
                    return MANIFEST_ERR_LC_USAGE_CONSTRAINT;
                }
            }
        }
    }

    // Load extra manifest bytes if v1.x.
    err = load_manifest_extra(dest, src_addr, from_spi);
    if (err) return err;

    // Payload source location check.
    // Verify the payload source address falls within a valid memory region
    // (SPI XIP or SMC SRAM) to prevent DMA from accessing unexpected addresses.
    {
        uint32_t p_len = (uint32_t)dest->payload_length;
        uint32_t p_off = (uint32_t)dest->boot_arguments.payload_offset;
        uint32_t payload_src = src_addr + p_off;
        uint32_t payload_end = payload_src + p_len;

        // Overflow check.
        if (payload_end < payload_src) {
            simputs("PAYLOAD_LOC_OVERFLOW\n");
            return MANIFEST_ERR_PAYLOAD_BAD_LOC;
        }

        // Determine source type and check the payload stays within that region.
        // OSS FIX: classify by the authoritative `from_spi` flag (the same flag
        // that selected src_addr in the caller), NOT by re-deriving the type from
        // the address value. The original `src_addr >= SEP_SPI_BASE` misclassifies
        // any SMC-SRAM manifest (sep_get_smc_sram_base()=0x4006_0000, which is
        // ABOVE the XIP window [0x3000_0000, 0x4000_0000)) as SPI and then rejects
        // it as OOB -- so the non-SPI/secondary (SMC-SRAM) boot path could never
        // pass. Using from_spi keeps the bounds check consistent with the source
        // selection by construction.
        if (from_spi) {
#if BOOT_SPI_CONTROLLER_OT
            // OpenTitan: static slot-region + SRAM-destination bounds (hardened,
            // default-reject). payload_src is a flash byte-offset here.
            uint32_t payload_dest = (uint32_t)dest + p_off;
            if (!boot_flash_bounds_ok(payload_src, p_len, payload_dest, p_len)) {
                simputs("PAYLOAD_LOC_OT_OOB\n");
                report_status(STATUS_TYPE_ERROR, SEP_MSG_SPI_OT_BOUNDS_ERROR);
                return MANIFEST_ERR_PAYLOAD_BAD_LOC;
            }
#else
            // SPI flash path: payload must be within XIP region.
            uint32_t spi_end = SEP_SPI_BASE + SEP_SPI_MAX_SIZE;
            if (payload_src < SEP_SPI_BASE || payload_end > spi_end) {
                simputs("PAYLOAD_LOC_SPI_OOB\n");
                report_status(STATUS_TYPE_ERROR, SEP_MSG_PAYLOAD_INVALID_LOCATION_FLASH);
                return MANIFEST_ERR_PAYLOAD_BAD_LOC;
            }
#endif
        } else {
            // SMC SRAM path (recovery / secondary).
            uint32_t smc_sram = sep_get_smc_sram_base();
            uint32_t smc_end = smc_sram + SMC_SRAM_SIZE_BYTES;
            if (payload_src < smc_sram || payload_end > smc_end) {
                simputs("PAYLOAD_LOC_SMC_OOB\n");
                return MANIFEST_ERR_PAYLOAD_BAD_LOC;
            }
        }
    }

    // C13.9: Load payload (TOC header + entries + image data).
    {
        uint32_t p_len = (uint32_t)dest->payload_length;
        int32_t p_off = (int32_t)dest->boot_arguments.payload_offset;
        if (p_len > 0u && p_off > 0) {
            uint32_t payload_dest = (uint32_t)dest + (uint32_t)p_off;
            uint32_t payload_src = src_addr + (uint32_t)p_off;
            err = manifest_src_read(payload_dest, payload_src, p_len, from_spi);
            if (err) return MANIFEST_ERR_DMA_FAILED;
        }
    }

    // C13.10: Crypto chain, then C13.11 the payload structure.
    //
    // ORDER IS LOAD-BEARING: security version -> signature -> payload hash (over
    // ciphertext) -> decrypt -> TOC.
    //   * The TOC is read LAST because an encrypted payload's TOC is itself
    //     ciphertext; reading it earlier rejects every encrypted image as
    //     MANIFEST_ERR_BAD_TOC_ID.
    //   * The chain runs INSIDE the slot attempt so a crypto failure returns an
    //     error and lets rom_manifest_boot() fall over to the backup slot.
    if (sb) {
        err = manifest_crypto_validate(dest, lc_state);
        if (err) {
            simputshex32("CRYPTO_FAIL=", err);
            return err;
        }
    } else {
        simputs("SBOOT_OFF\n");
        // Payload hash is checked even with secure boot off: it still detects
        // payload corruption, it just is not authenticated by a signature.
        err = verify_payload_hash(dest);
        if (err) {
            simputshex32("PLD_HASH_FAIL=", err);
            return err;
        }
    }

    // C13.11: Validate payload structure (TOC header + entries).
    err = validate_manifest_payload(dest);
    if (err) return err;

    return MANIFEST_OK;
}

// Zero a region of SEP SRAM (for cleanup between retry attempts).
static void clear_sram_region(uint32_t addr, uint32_t size) {
    volatile uint32_t *p = (volatile uint32_t *)(uintptr_t)addr;
    uint32_t words = size / 4u;
    for (uint32_t i = 0; i < words; ++i) {
        p[i] = 0u;
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

uint32_t rom_manifest_boot(const struct boot_straps *straps, uint32_t spi_status, uint32_t lc_state,
                           bool sboot_dis) {
    manifest_t *p_manifest = (manifest_t *)(uintptr_t)SRAM_BASE;
    const bool from_spi = boot_from_spi(straps);

    uint32_t offsets[2];
    uint32_t num_retries;

    if (from_spi) {
        offsets[0] = PRIMARY_MANIFEST_OFFSET;
        offsets[1] = BACKUP_MANIFEST_OFFSET;
        num_retries = 1; // Try primary, then backup.
    } else {
        // Recovery or secondary: wait for SMC to place manifest.
        report_status(STATUS_TYPE_INFO, SEP_MSG_WAIT_FOR_SMC_MANIFEST_READY);
        simputs("WAIT_SMC_MANIFEST\n");
        for (;;) {
            uint32_t status = smc_scratch_read(SMC_SCRATCH_STATUS_TO_SEP_IDX);
            if (status & SMC_SEP_STATUS_MANIFEST_READY) break;
        }
        offsets[0] = smc_scratch_read(SMC_SCRATCH_MANIFEST_ADDR_IDX);
        offsets[1] = offsets[0]; // never selected; see the rotate_update guard
        num_retries = 0;         // Single attempt for SMC path.
    }

    uint32_t last_err = 0;

    for (uint32_t retry = 0; retry <= num_retries; ++retry) {
        // Select slot: rotate_update swaps primary/backup order. Only the SPI
        // path has two slots -- the SMC path fills offsets[0] alone and runs a
        // single attempt, so rotating there selected an offset that was never
        // assigned.
        uint32_t slot = retry;
        if (straps->rotate_update && from_spi) {
            slot ^= 1u;
        }
        uint32_t offset = offsets[slot];

        // Skip primary if SPI init failed entirely.
        if (from_spi && retry == 0 && spi_status) {
            simputs("SPI init failed, using backup manifest\n");
            continue;
        }

        // Source of the manifest. The OpenTitan controller has no memory-mapped
        // flash, so pass the raw flash byte-offset; the Cadence XIP path and the
        // SMC SRAM path pass an absolute address.
        uint32_t manifest_src;
        if (from_spi) {
#if BOOT_SPI_CONTROLLER_OT
            manifest_src = offset;
#else
            manifest_src = SEP_SPI_BASE + offset;
#endif
        } else {
            manifest_src = sep_get_smc_sram_base() + offset;
        }

        report_status(STATUS_TYPE_INFO, SEP_MSG_MANIFEST_LOAD_START);
        simputs(retry == 0 ? "MANIFEST_PRIMARY\n" : "MANIFEST_BACKUP\n");
        simputshex32("MANIFEST_SRC=", manifest_src);

        // Attempt load + validate.
        uint32_t err = try_manifest_slot(p_manifest, manifest_src, from_spi, lc_state, sboot_dis);
        if (err != 0u) {
            simputshex32("MANIFEST_ERR=", err);
            last_err = err;

            // Clean up SRAM before retrying.
            if (from_spi && retry < num_retries) {
                clear_sram_region(SRAM_BASE, SRAM_SIZE);
                uint32_t rerr = boot_flash_reinit();
                if (rerr) {
                    // Without a working controller the backup slot cannot be
                    // read at all. Discarding this made the next attempt read
                    // through a dead controller and report whatever it got as a
                    // manifest defect, blaming the image for a transport fault.
                    simputshex32("FLASH_REINIT_FAIL=", rerr);
                    return MANIFEST_ERR_DMA_FAILED;
                }
            }
            continue;
        }

        // Success — manifest and payload are in SEP SRAM.
        report_status(STATUS_TYPE_INFO, SEP_MSG_MANIFEST_VALIDATED);
        simputs("MANIFEST_OK\n");

        // Debug: report image count and payload length from TOC.
        const struct toc_header *toc =
            (const struct toc_header *)manifest_payload_address(p_manifest);
        simputshex32("IMAGES=", (uint32_t)toc->image_count);
        simputshex32("PAYLOAD=", (uint32_t)p_manifest->payload_length);

        // Update BL0 state.
        get_bl0_state()->sep_sram_manifest_addr = (uint32_t)p_manifest;

        return MANIFEST_OK;
    }

    // All retries exhausted.
    report_status(STATUS_TYPE_ERROR, SEP_MSG_MANIFEST_LOAD_FAILED);
    simputs("MANIFEST_ALL_FAILED\n");
    return last_err;
}
