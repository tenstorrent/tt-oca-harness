/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OROM manifest loading and validation.
//
// Manifest format uses manifest_t (1184 bytes), TOC header
// + toc_entry[]).  See manifest.h for structure definitions.
//
// Manifest load flow:
//   1. Determine manifest source (SPI flash vs SMC SRAM)
//   2. Try primary slot; on failure, try backup (SPI only)
//   3. For each attempt: load header -> validate -> integrity check ->
//      load payload (contains TOC + images) -> validate payload
//   4. On success, update BL0 state with manifest address
//
// Manifest hash verification uses the HMAC SHA-256 hardware driver.
// Secure boot follows the ROM policy: PROD/PROD_END always enforce.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "manifest.h"
#include "boot_straps.h"
#include "hmac_sha256.h"
#include "lifecycle.h"
#include "sep_dma.h"
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

// Terminal failure for an unusable SMC staging window. Not a slot error: the
// window comes from the SMC, so the backup manifest would read the same
// scratch registers and fail identically, and reporting MANIFEST_ALL_FAILED
// would blame the images for an environment fault.
#define ROM_ERR_SMC_STAGING 0x0000A003u

__attribute__((noreturn)) extern void rom_err_fail_ext(uint32_t error_code);

// AES-CBC block size. Used only as the upper bound on how far an encrypted
// payload's manifest length may exceed the plaintext length its TOC reports:
// the packer PKCS#7-pads before encrypting, and PKCS#7 appends between 1 and a
// full block.
#define AES_CBC_BLOCK_BYTES 16u

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

// Whether the SHA-256 verification checks run at all.
//
// The escape hatch exists for a non-functional HMAC IP, which would otherwise
// block every boot. Two gates keep it out of a fielded part: secure boot wins
// outright, and outside TEST_DEV the manifest bit is ignored. flag_args sits
// outside the signed TBS region, so the bit is unauthenticated and the gates are
// what make it safe.
//
// This governs verification only. It must never gate the payload decryption KDF:
// skipping a check is a decision, skipping a derivation just produces the wrong
// key. So an encrypted payload cannot boot with a dead HMAC IP either way.
static bool sha256_checks_enabled(const manifest_t *m, bool secure_boot, uint32_t lc_state) {
    if (secure_boot) {
        return true;
    }
    if (lc_state != LC_STATE_TEST_DEV) {
        return true;
    }
    if (m->boot_arguments.flag_args & (1u << FLAG_ARGS_BIT_SKIP_SHA256)) {
        report_status(STATUS_TYPE_INFO, SEP_MSG_MANIFEST_SHA256_CHECKS_DISABLED);
        simputs("SHA256_CHECKS_DISABLED\n");
        return false;
    }
    return true;
}

// ── Verify the manifest hash (SHA-256 of the TBS region) ──
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

// Read manifest data into SRAM. Flash is not memory-mapped, so on the SPI path
// `src` is a flash byte-offset read through the SPI host; otherwise it is an
// absolute SMC SRAM address copied by the secure DMA. Returns 0 on success.
static uint32_t manifest_src_read(uint32_t dst, uint32_t src, uint32_t len, bool from_spi) {
    if (from_spi) {
        return boot_flash_read(dst, src, len);
    }
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
// ── Secure boot decision ──
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

// ── Validate payload structure (TOC header + entries) ──
static uint32_t validate_manifest_payload(const manifest_t *m, bool sha_checks) {
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
    uint32_t toc_bytes = (uint32_t)sizeof(struct toc_header) + n * (uint32_t)sizeof(struct toc_entry);
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
    // PKCS#7 makes the padded length a single value, so require exactly that
    // rather than a slack window: a window also admits zero padding, which the
    // scheme never emits.
    const uint64_t toc_p_len = (uint64_t)toc->payload_length;
    const bool encrypted = (m->usage_constraints.flags &
                            (1u << USAGE_CONSTRAINTS_FLAGS_BIT_ENCRYPTED_PAYLOAD)) != 0u;
    const uint64_t expect_p_len = encrypted
        ? ((toc_p_len & ~(uint64_t)(AES_CBC_BLOCK_BYTES - 1u)) + AES_CBC_BLOCK_BYTES)
        : toc_p_len;
    const bool plen_bad = (m->payload_length != expect_p_len);
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
        // The body address reaches sep_dma_copy() as the DMA source unchecked,
        // so refuse it here rather than at the transfer. Checked before the
        // arithmetic arms so a misaligned offset is never reported as a bound
        // or ordering failure.
        if ((off & 7u) != 0u) {
            simputshex32("IMAGE_OFF_ALIGN idx=", i);
            return MANIFEST_ERR_IMAGE_ALIGN;
        }
        // Four arms return MANIFEST_ERR_IMAGE_OOB, so the status word alone
        // cannot say which one refused the image. These two name themselves.
        if (end < off) { // overflow
            simputshex32("IMAGE_END_OVERFLOW idx=", i);
            return MANIFEST_ERR_IMAGE_OOB;
        }
        if (end > p_len) {
            simputshex32("IMAGE_OOB_BOUND idx=", i);
            return MANIFEST_ERR_IMAGE_OOB;
        }

        // Image bodies must start after the TOC region and run in strictly
        // ascending order. Ascending order is what makes prev_end a sufficient
        // bound: it turns overlap detection into a single comparison and, with
        // the gap zeroization below, means every byte of the payload is either
        // inside a validated image or has been cleared.
        //
        // Comparing against the previous image's end refuses both a body that
        // starts before its predecessor's and one that starts inside it, so a
        // port carrying two separate ordering rules across collapses to this
        // one arm. No case is lost; the two are not told apart.
        if (off < prev_end) {
            simputshex32("IMAGE_ORDER_BAD idx=", i);
            return MANIFEST_ERR_IMAGE_OVERLAP;
        }
        // Test the truncated width every other arm and every consumer uses, or
        // a length of 0x1_0000_0000 passes as non-zero and reaches them as 0.
        if (len == 0u) {
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
        if (sha_checks) {
            uint8_t img_digest[32];
            if (sha256((const uint8_t *)toc + off, len, img_digest) != 0) {
                simputs("IMAGE_HASH_TIMEOUT\n");
                return MANIFEST_ERR_IMAGE_HASH_MISMATCH;
            }
            if (!const_time_eq(img_digest, e->hash, 32)) {
                simputshex32("IMAGE_HASH_MISMATCH idx=", i);
                return MANIFEST_ERR_IMAGE_HASH_MISMATCH;
            }
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
//
// staged_addr/staged_size report where the payload was staged, so a failed
// attempt can be wiped before the next slot is tried. The destination
// is no longer always inside the SEP SRAM region the caller clears wholesale.
static uint32_t try_manifest_slot(manifest_t *dest, uint32_t src_addr, bool from_spi,
                                 uint32_t lc_state, bool sboot_dis,
                                 uint32_t *staged_addr, uint32_t *staged_size) {
    uint32_t err;

    // Validate the header read is in bounds before issuing it (redundant,
    // default-reject bounds gate). Applies to the SPI path only.
    if (from_spi && !boot_flash_bounds_ok(src_addr, (uint32_t)sizeof(manifest_t), (uint32_t)dest,
                                          (uint32_t)sizeof(manifest_t))) {
        report_status(STATUS_TYPE_ERROR, SEP_MSG_SPI_OT_BOUNDS_ERROR);
        return MANIFEST_ERR_PAYLOAD_BAD_LOC;
    }

    // Load the manifest header (1184 bytes).
    err = load_manifest_header(dest, src_addr, from_spi);
    if (err) return err;

    // Validate manifest fields.
    err = validate_manifest_header(dest);
    if (err) return err;

    // payload_offset is a cursor, not a constant. As authored it is the distance
    // from the manifest to the payload in flash; both bases are still available
    // here, so the source read below uses src_addr + offset while the staging
    // destination is chosen independently. After staging, the offset is rebased
    // onto the staged address so every later manifest_payload_address() caller
    // -- validate_manifest_payload(), rom_handoff_bl1() -- resolves to the copy
    // rather than to flash. The field sits outside the signed TBS region, so
    // rewriting it invalidates no completed integrity check.

    // Determine secure boot state. Computed here rather than after the
    // integrity check because the hash gate below needs it; the verdict takes
    // lc_state and sboot_dis by value, so it does not depend on call ordering.
    const bool sb = secure_boot_enabled(dest, lc_state, sboot_dis);
    const bool sha_ok = sha256_checks_enabled(dest, sb, lc_state);

    // Verify the manifest hash.
    if (sha_ok) {
        err = manifest_check_integrity(dest);
        if (err) return err;
    }

    get_bl0_state()->secure_boot = sb;

    // An encrypted payload without secure boot is rejected outright. The
    // decryption key is derived from a fuse, so with secure boot off nothing
    // authenticates the manifest that selects it -- and the ciphertext would
    // reach the TOC check undecrypted anyway, failing as a malformed TOC and
    // hiding the real reason.
    if (!sb && (dest->usage_constraints.flags &
                (1u << USAGE_CONSTRAINTS_FLAGS_BIT_ENCRYPTED_PAYLOAD))) {
        simputs("ENC_WITHOUT_SBOOT\n");
        return MANIFEST_ERR_LC_USAGE_CONSTRAINT;
    }

    // Validate usage constraints.
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

        // Life cycle state check.
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

        // chiplet_id check (selector_bits[0..7]).
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

        // package_id check (selector_bits[8..15]).
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
    // Verify the payload source falls within a valid region (a flash boot slot
    // or SMC SRAM) to prevent a read from an unexpected address.
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

        // Classify by the `from_spi` flag that selected src_addr in the caller,
        // not by the address value: on the SPI path src_addr is a flash
        // byte-offset, so no value test can tell it from an absolute address.
        if (from_spi) {
            // Static slot-region + SRAM-destination bounds (hardened,
            // default-reject). payload_src is a flash byte-offset here.
            uint32_t payload_dest = (uint32_t)dest + p_off;
            if (!boot_flash_bounds_ok(payload_src, p_len, payload_dest, p_len)) {
                simputs("PAYLOAD_LOC_OT_OOB\n");
                report_status(STATUS_TYPE_ERROR, SEP_MSG_SPI_OT_BOUNDS_ERROR);
                return MANIFEST_ERR_PAYLOAD_BAD_LOC;
            }
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

    // Load payload (TOC header + entries + image data).
    {
        uint32_t p_len = (uint32_t)dest->payload_length;
        int32_t p_off = (int32_t)dest->boot_arguments.payload_offset;
        if (p_len > 0u && p_off > 0) {
            // Choose the staging destination.
            //
            // Only the SPI path chooses. On the non-SPI path the payload already
            // lives in SMC SRAM, so honouring use_ext_sram=0 there would stage
            // SMC SRAM into itself.
            uint32_t payload_dest = (uint32_t)dest + (uint32_t)p_off;
            uint32_t payload_max = SRAM_BASE + SRAM_SIZE - payload_dest;

            if (from_spi &&
                !(dest->boot_arguments.flag_args & (1u << FLAG_ARGS_BIT_USE_EXT_SRAM))) {
                // Unbounded: the specification states that this recovery-path
                // wait loops forever.
                //
                // Known exposure, deliberately not handled here: bit 29 sits
                // outside the signed TBS region, so flipping it in a fielded
                // image reaches this loop and an SMC that never initialises
                // hangs the boot. Bounding the loop would diverge from the
                // specification, so it needs a spec decision rather than a local
                // one.
                report_status(STATUS_TYPE_INFO, SEP_MSG_EXT_SRAM_INIT_WAIT);
                // Also on the console: the status ring is not scraped by DV, so
                // without this the fact that the ROM waited at all is
                // unobservable in simulation.
                simputs("EXT_SRAM_INIT_WAIT\n");
                for (;;) {
                    uint32_t st = smc_scratch_read(SMC_SCRATCH_STATUS_TO_SEP_IDX);
                    if (st & SMC_SEP_STATUS_SRAM_INIT) {
                        break;
                    }
                }

                uint32_t win_off = smc_scratch_read(SMC_SCRATCH_SEP_SAFE_SRAM_START_IDX);
                uint32_t win_len = smc_scratch_read(SMC_SCRATCH_SEP_SAFE_SRAM_SIZE_IDX);
                report_status(STATUS_TYPE_INFO, SEP_MSG_SMC_PAYLOAD_OFFSET);
                report_status(STATUS_TYPE_INFO, SEP_MSG_SMC_PAYLOAD_MAX_SIZE);
                simputshex32("SMC_WIN_OFF=", win_off);
                simputshex32("SMC_WIN_LEN=", win_len);

                // The window is SMC-supplied and therefore untrusted. Both
                // refusals are terminal, not slot errors -- see ROM_ERR_SMC_STAGING.
                if (!contains_range(0u, SMC_SRAM_SIZE_BYTES, win_off, win_len)) {
                    simputs("SMC_WIN_OOB\n");
                    report_status(STATUS_TYPE_ERROR, SEP_MSG_PAYLOAD_INVALID_LOCATION_SRAM);
                    rom_err_fail_ext(ROM_ERR_SMC_STAGING);
                }
                if (win_off & 0x7u) {
                    simputs("SMC_WIN_MISALIGNED\n");
                    report_status(STATUS_TYPE_ERROR, SEP_MSG_INVALID_PAYLOAD_ALIGNMENT_SRAM);
                    rom_err_fail_ext(ROM_ERR_SMC_STAGING);
                }

                payload_dest = sep_get_smc_sram_base() + win_off;
                payload_max = win_len;
                report_status(STATUS_TYPE_INFO, SEP_MSG_USING_SMC_SRAM);
                simputs("USING_SMC_SRAM\n");
            } else {
                report_status(STATUS_TYPE_INFO, SEP_MSG_USING_SEP_SRAM);
                simputs("USING_SEP_SRAM\n");
            }

            // The destination has a capacity; nothing checked it before. The DMA
            // range check would catch an overrun, but as a backstop rather than
            // as a decision the ROM made.
            if (p_len > payload_max) {
                simputshex32("PAYLOAD_NO_ROOM=", payload_max);
                report_status(STATUS_TYPE_ERROR, SEP_MSG_INVALID_PAYLOAD_LENGTH);
                return MANIFEST_ERR_PAYLOAD_NO_ROOM;
            }

            uint32_t payload_src = src_addr + (uint32_t)p_off;

            // The bounds gate above ran before the destination was chosen, so it
            // validated the EXT SRAM address rather than the one about to be
            // written. Re-run it on the real destination: the driver's own gate
            // would refuse an undeclared region anyway, but this keeps the
            // hardened caller-side check covering what actually happens.
            if (from_spi && !boot_flash_bounds_ok(payload_src, p_len, payload_dest, p_len)) {
                simputs("PAYLOAD_DST_OT_OOB\n");
                report_status(STATUS_TYPE_ERROR, SEP_MSG_SPI_OT_BOUNDS_ERROR);
                return MANIFEST_ERR_PAYLOAD_BAD_LOC;
            }

            err = manifest_src_read(payload_dest, payload_src, p_len, from_spi);
            if (err) return MANIFEST_ERR_DMA_FAILED;

            simputshex32("PAYLOAD_DST=", payload_dest);

            // Rebase the cursor onto the staged copy so every later
            // manifest_payload_address() resolves there.
            dest->boot_arguments.payload_offset =
                (int64_t)(int32_t)(payload_dest - (uint32_t)dest);

            if (staged_addr) *staged_addr = payload_dest;
            if (staged_size) *staged_size = p_len;
        }
    }

    // Crypto chain, then the payload structure.
    //
    // THE ORDER IS REQUIRED: security version -> signature -> payload hash (over
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
        if (sha_ok) {
            err = verify_payload_hash(dest);
            if (err) {
                simputshex32("PLD_HASH_FAIL=", err);
                return err;
            }
        }
    }

    // Validate payload structure (TOC header + entries).
    err = validate_manifest_payload(dest, sha_ok);
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

uint32_t rom_manifest_boot(const struct boot_straps *straps, uint32_t spi_status,
                          uint32_t lc_state, bool sboot_dis) {
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

    // Declared outside the loop so a failed attempt's staging area can be wiped
    // before the next slot is tried, wherever it landed.
    uint32_t staged_addr = 0u;
    uint32_t staged_size = 0u;

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

        // Source of the manifest. Flash is not memory-mapped, so the SPI path
        // passes the raw flash byte-offset; the SMC SRAM path passes an
        // absolute address.
        uint32_t manifest_src;
        if (from_spi) {
            manifest_src = offset;
        } else {
            manifest_src = sep_get_smc_sram_base() + offset;
        }

        report_status(STATUS_TYPE_INFO, SEP_MSG_MANIFEST_LOAD_START);
        simputs(retry == 0 ? "MANIFEST_PRIMARY\n" : "MANIFEST_BACKUP\n");
        simputshex32("MANIFEST_SRC=", manifest_src);

        // Attempt load + validate.
        staged_addr = 0u;
        staged_size = 0u;
        uint32_t err = try_manifest_slot(p_manifest, manifest_src, from_spi,
                                        lc_state, sboot_dis,
                                        &staged_addr, &staged_size);
        if (err != 0u) {
            simputshex32("MANIFEST_ERR=", err);
            last_err = err;

            // Clean up SRAM before retrying.
            if (from_spi && retry < num_retries) {
                // A payload staged outside SEP SRAM is not reached by the region
                // clear below, so wipe it where it actually landed. Otherwise the
                // failed attempt's payload survives into the backup attempt.
                if (staged_size != 0u &&
                    !contains_range(SRAM_BASE, SRAM_SIZE, staged_addr, staged_size)) {
                    simputshex32("STAGED_WIPE=", staged_addr);
                    (void)sep_dma_zero(staged_addr, staged_size);
                }
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
