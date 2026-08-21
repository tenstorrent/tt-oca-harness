// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
/* OTBN software error testcase: LOOP branch-at-end violation */

.section .text.start
.globl _start
.globl start

_start:
start:
  addi    x2, x0, 0
  loopi   2, 2
    addi  x2, x2, 1
    beq   x0, x0, loop_target

loop_target:
  ecall
