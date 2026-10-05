// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

.section .text.start
.global _start
.type _start, @function

_start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop

    csrr t0, mhartid
    bnez t0, .Lpark
    la sp, _stack_top
    andi sp, sp, -16
    call main

.Lpark:
    wfi
    j .Lpark
