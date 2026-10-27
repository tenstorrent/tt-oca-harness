/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SMC BL1 status values (firmware ID 4) and its POST word. The POST word keeps the SMC ROM's
// structured layout in scratch 1; boot phase 8 marks SMC BL1, since the ROM uses phases 0-7.
// Keep this file to plain #define lines: decoders parse it as text.

#pragma once

#define SMC_BL1_FW_ID 0x04

#define SMC_BL1_STARTED 0x0101
#define SMC_BL1_PATH_OK 0x0102
#define SMC_BL1_CHALLENGE_OK 0x0103
#define SMC_BL1_CONFIRM_SENT 0x0104
#define SMC_BL1_DONE 0x011F
#define SMC_BL1_ERR_NO_CHALLENGE 0x0180
#define SMC_BL1_ERR_BAD_TAG 0x0181
#define SMC_BL1_ERR_TRAP 0x0182

#define SMC_BL1_POST_PHASE 0x8
#define SMC_BL1_POST_PHASE_SHIFT 28
#define SMC_BL1_POST_VALUE_MASK 0xFFFF
#define SMC_BL1_POST_WORD(value) \
    ((SMC_BL1_POST_PHASE << SMC_BL1_POST_PHASE_SHIFT) | ((value)&SMC_BL1_POST_VALUE_MASK))
