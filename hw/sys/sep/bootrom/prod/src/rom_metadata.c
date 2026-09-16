/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// ROM metadata: version string and SHA-256 hash for self-reporting (C1).
//
// The build-time hash is inserted by tools/insert-rom-sha256.py after linking.
// It covers the ICCM content (code + metadata) and is stored here in .rodata
// (DCCM) because VeeR EL2's LSU cannot data-load from ICCM addresses.
// Since the hash covers ICCM and lives in DCCM, there is no circular dependency.

#include <stdint.h>
#include "bl0_version.h"

// ROM version string. The Makefile generates bl0_version.h with a fixed
// placeholder, which keeps the open build's ROM image -- and therefore the
// build-time hash above -- reproducible. A release image needs the adopter's
// own version policy here.
__attribute__((used, aligned(4))) const char g_rom_version[] = BL0_VERSION "\n";

// ROM SHA-256 hash string, patched at build time by insert-rom-sha256.py.
// Format: "sha256:<64-hex-chars>\0..." (80 bytes).
// Placeholder is all-zeros; the build script overwrites it.
__attribute__((used, aligned(4))) const char g_rom_sha256_str[80] = {0};
