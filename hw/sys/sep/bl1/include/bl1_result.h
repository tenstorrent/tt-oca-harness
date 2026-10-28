/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Result and warning encodings shared by the SEP BL1 checks.

#pragma once

#include <stdint.h>

// A check returns BL1_OK or one of the SEP_BL1_ERR_* values in sep_bl1_status.h. BL1_OK is a
// non-trivial pattern so that neither a cleared nor a flipped register reads as success.
typedef uint32_t bl1_result_t;
#define BL1_OK 0x3CA5C35Au

// Warnings accumulate in a bitmask; each maps to one SEP_BL1_WARN_* status value.
#define BL1_WARN_ZONE_MISMATCH (1u << 0)
#define BL1_WARN_NOT_SECURE (1u << 1)
#define BL1_WARN_LIFECYCLE (1u << 2)
#define BL1_WARN_DEMOTED (1u << 3)
#define BL1_WARN_STATUS_RING (1u << 4)
#define BL1_WARN_PARK_FORCED (1u << 5)
