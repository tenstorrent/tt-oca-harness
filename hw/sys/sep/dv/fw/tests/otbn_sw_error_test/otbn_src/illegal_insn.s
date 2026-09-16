/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/* OTBN software error testcase: ILLEGAL_INSN */

.section .text.start
.globl _start
.globl start

_start:
start:
  .word   0xffffffff
  ecall
