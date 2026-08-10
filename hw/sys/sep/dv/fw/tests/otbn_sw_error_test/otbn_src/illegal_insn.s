/* OTBN software error testcase: ILLEGAL_INSN */

.section .text.start
.globl _start
.globl start

_start:
start:
  .word   0xffffffff
  ecall
