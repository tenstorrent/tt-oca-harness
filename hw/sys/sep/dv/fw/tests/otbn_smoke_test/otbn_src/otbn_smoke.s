/* Copyright lowRISC contributors (OpenTitan project). */
/* Licensed under the Apache License, Version 2.0, see LICENSE for details. */
/* SPDX-License-Identifier: Apache-2.0 */

  /*
   * OTBN smoke program for SEP integration testing.
   *
   * The host preloads three DMEM inputs:
   *   - input_outer_inc
   *   - input_inner_count
   *   - input_inner_inc
   *
   * The program computes:
   *   result = 4 * (input_outer_inc + input_inner_count * input_inner_inc)
   *
   * For the default smoke vectors (10, 3, 1), the expected result is 52.
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
