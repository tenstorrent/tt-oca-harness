/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/* OTBN software error testcase: BAD_DATA_ADDR */

.section .text.start
.globl _start
.globl start

_start:
start:
  lui     x2, 0x8
  lw      x3, 0(x2)
  ecall
