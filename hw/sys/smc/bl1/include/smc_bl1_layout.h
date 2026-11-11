/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Contract values that start.S and the linker script need, as plain integers: the contract
// header's constants carry C suffixes that neither the assembler nor the linker accepts.
// post.c asserts that each equals its contract value.

#pragma once

#define SMC_BL1_IMAGE_START 0xC0080000
#define SMC_BL1_IMAGE_END 0xC00C0000
#define SMC_BL1_RW_START 0xC00C0000
#define SMC_BL1_RW_END 0xC015B000
#define SMC_BL1_STACK_SIZE 0x2000

#define SMC_BL1_SCRATCH_POST 1
#define SMC_BL1_SCRATCH_STATUS_TO_SEP 9
#define SMC_BL1_HART0_PARKED_BIT 4
