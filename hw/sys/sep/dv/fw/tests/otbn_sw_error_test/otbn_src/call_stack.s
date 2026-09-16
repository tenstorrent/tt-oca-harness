/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/* OTBN software error testcase: CALL_STACK overflow */

.section .text.start
.globl _start
.globl start

_start:
start:
  jal     x1, level1
  ecall

level1:
  jal     x1, level2

level2:
  jal     x1, level3

level3:
  jal     x1, level4

level4:
  jal     x1, level5

level5:
  jal     x1, level6

level6:
  jal     x1, level7

level7:
  jal     x1, level8

level8:
  jal     x1, level9

level9:
  ecall
