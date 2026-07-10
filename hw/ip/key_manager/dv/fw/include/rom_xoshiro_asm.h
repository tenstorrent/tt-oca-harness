/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/*
 * @file rom_xoshiro_asm.h
 * @brief Shared GNU-assembler macro for the xoshiro128++ generator step.
 *
 * Assembler-only include (`.S` sources only): defines the `.macro` used by the
 * stack-less SRAM routines.
 */

#ifndef ROM_XOSHIRO_ASM_H
#define ROM_XOSHIRO_ASM_H

#ifdef __ASSEMBLER__

/*
 * XOSHIRO128PP_STEP s0, s1, s2, s3, res, tmp
 *
 * Emits one xoshiro128++ iteration entirely in registers:
 *   res = rotl32(s0 + s3, 7) + s0      ; output word (preserved on exit)
 *   t   = s1 << 9
 *   s2 ^= s0;  s3 ^= s1;  s1 ^= s2;  s0 ^= s3;  s2 ^= t
 *   s3  = rotl32(s3, 11)               ; state advanced in place
 *
 * Operands must be six distinct registers.  On exit s0-s3 hold the next state,
 * res holds the output word to store, and tmp is clobbered.
 */
.macro XOSHIRO128PP_STEP s0, s1, s2, s3, res, tmp
    /* res = rotl32(s0 + s3, 7) + s0 */
    add  \res, \s0, \s3
    slli \tmp, \res, 7
    srli \res, \res, 25             /* 32 - 7 */
    or   \res, \res, \tmp
    add  \res, \res, \s0

    /* state update; tmp = t = s1 << 9 (kept live until s2 ^= t) */
    slli \tmp, \s1, 9
    xor  \s2, \s2, \s0
    xor  \s3, \s3, \s1
    xor  \s1, \s1, \s2
    xor  \s0, \s0, \s3
    xor  \s2, \s2, \tmp

    /* s3 = rotl32(s3, 11) */
    slli \tmp, \s3, 11
    srli \s3, \s3, 21               /* 32 - 11 */
    or   \s3, \s3, \tmp
.endm

#endif /* __ASSEMBLER__ */

#endif /* ROM_XOSHIRO_ASM_H */
