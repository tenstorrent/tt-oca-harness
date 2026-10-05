/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OCA boot-manifest load and validation for the SEP boot ROM.
//
// Structural parsing, integrity, usage constraints, anti-rollback, signature and
// payload verification all live in the vendored OCA library; this module owns
// only what the library deliberately does not: getting bytes out of storage,
// slot selection, and reporting.

#pragma once

#include <stddef.h>
#include <stdint.h>

#include "boot_straps.h"

// Error codes reported through rom_err_fail() and the MANIFEST_ERR= marker.
// 0x0003 is the manifest subsystem nibble that DV and log tooling match on.
//
// A library verdict is carried through verbatim in the low byte: an
// oca_result_t is 0..34, so 0x000300xx is always "the library said xx" and
// 0x000301xx is always "this module failed before or after it". That beats
// collapsing distinct verdicts onto a handful of ROM-local codes.
#define OCA_BOOT_ERR_BASE 0x00030000u
#define OCA_BOOT_ERR_RESULT(r) (OCA_BOOT_ERR_BASE | (uint32_t)(r))

#define OCA_BOOT_ERR_DMA 0x00030100u            // secure-DMA storage copy failed
#define OCA_BOOT_ERR_STAGE_OVERFLOW 0x00030101u // body+payload exceed SEP SRAM
#define OCA_BOOT_ERR_NO_BL1 0x00030102u         // no BL1 image in the TOC
#define OCA_BOOT_ERR_BL1_BAD_ADDR 0x00030103u   // BL1 load/entry outside SRAM
#define OCA_BOOT_ERR_BL1_TOO_LARGE 0x00030104u  // BL1 length implausible
#define OCA_BOOT_ERR_KEY_UNTRUSTED 0x00030105u  // signing key is not a device root key
#define OCA_BOOT_ERR_READ_OUT_OF_BOUNDS \
    0x00030106u                             // storage read refused by boot_flash_bounds_ok()
#define OCA_BOOT_ERR_FLASH_READ 0x00030107u // flash transport reported a failed read

// Load, authenticate and stage a manifest + payload into SEP SRAM.
//
// Tries the primary then the backup slot on the SPI path (order swapped by the
// rotate_update strap); waits for the SMC to publish one on the recovery /
// secondary path. spi_status non-zero skips the primary attempt.
//
// Returns 0 on success, in which case the authenticated body and its verified
// payload are staged in SEP SRAM and reachable via the accessors below.
uint32_t rom_manifest_boot(const struct boot_straps *straps, uint32_t spi_status);

// The staged, authenticated manifest body. NULL before a successful
// rom_manifest_boot(). Valid until the next call.
const uint8_t *rom_oca_body(void);

// The staged, verified payload (TOC header + images), and its length.
// Plaintext: if the payload was encrypted it has already been decrypted in
// place by the time rom_manifest_boot() returns.
const uint8_t *rom_oca_payload(void);
size_t rom_oca_payload_len(void);

// The manifest_hash field of the staged manifest: 32 bytes, NULL before a
// successful rom_manifest_boot(). The validator checked this field against the
// body it covers (oca_check_manifest_hash) during validation, so it is the
// digest of what was actually authenticated -- which is what a boot measurement
// has to commit to, as opposed to a digest recomputed over bytes nothing
// vouched for.
const uint8_t *rom_oca_manifest_hash(void);

// demotion_control (manifest offset 172, u16). Bits, vendor-defined:
//   0 BL1_DEMOTION_VALID   1 BL1_DEMOTION_ENABLE
//   2 BL2_DEMOTION_VALID   3 BL2_DEMOTION_ENABLE
// Reads the staged body, so it is only meaningful after a successful boot.
#define OCA_DEMOTE_BL1_VALID (1u << 0)
#define OCA_DEMOTE_BL1_ENABLE (1u << 1)
#define OCA_DEMOTE_BL2_VALID (1u << 2)
#define OCA_DEMOTE_BL2_ENABLE (1u << 3)
uint32_t rom_oca_demotion_control(void);

// Check that the staged payload carries a BL1 this device can load: present,
// correctly typed, placed in a permitted region, with entry_point inside it.
// Called per slot by rom_manifest_boot(), before the fuse-secret lock, so a
// slot whose BL1 cannot be loaded fails over to the backup.
uint32_t rom_bl1_check(void);

// Find BL1 in the staged payload TOC, copy it to its load address and jump.
// Does not return on success.
uint32_t rom_handoff_bl1(void);

// Zero SEP EXT SRAM before any manifest is staged into it (src/rom_mem_clear.c).
// Declared here because this header owns the SRAM staging area.
void rom_clear_ext_sram(void);
