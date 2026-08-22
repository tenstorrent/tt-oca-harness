/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/* OTBN software error testcase: BAD_INSN_ADDR */

.section .text.start
.globl _start
.globl start

_start:
start:
  addi    x2, x0, 2
  jalr    x0, x2, 0
  ecall
