/* Copyright lowRISC contributors (OpenTitan project). */
/* Licensed under the Apache License, Version 2.0, see LICENSE for details. */
/* SPDX-License-Identifier: Apache-2.0 */

  /*
   * OTBN SEP integration program.
   *
   * Same computation as the smoke program, but packaged as a dedicated image for
   * the SEP integration testcase.
   */

.section .text.start
.globl _start
.globl start
_start:
start:
  addi    x2, x0, 0

  la      x10, input_outer_inc
  lw      x10, 0(x10)

  la      x11, input_inner_count
  lw      x11, 0(x11)

  la      x12, input_inner_inc
  lw      x12, 0(x12)

  loopi   4, 4
    add   x2, x2, x10
    loop  x11, 1
      add x2, x2, x12
    nop

  la      x4, result
  sw      x2, 0(x4)

  ecall

.data
.globl input_outer_inc
input_outer_inc:
  .word 0

.globl input_inner_count
input_inner_count:
  .word 0

.globl input_inner_inc
input_inner_inc:
  .word 0

.globl result
result:
  .word 0
