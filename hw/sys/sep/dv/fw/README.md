<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS firmware

Self-contained boot firmware for the SEP OSS DV environment. No libc and no
internal headers — only the OSS drivers here and a handful of SEP hardware
addresses, so this tree migrates with the DV env.

```
fw/
  build/      shared startup + linker + make rules
    start.S        minimal VeeR EL2 crt0 (PMA, bss, sp, call main, PASS/FAIL magic)
    sep_tcm.ld     ICCM (0xC0000000) / DCCM (0xC0040000) layout
    common.mk      build rules: ELF -> .itcm.hex / .dtcm.hex (objcopy -O verilog)
  drivers/    reusable SEP device drivers
    sep_mailbox.h          STDOUT mailbox (0x80000000) console
    sep_outbound_filter.h  open the outbound filter window
  tests/
    hello_world/   prints a banner + returns PASS
```

## Build

A RISC-V bare-metal GCC must be on `PATH` (rv32imc / ilp32; no picolibc needed):

```bash
cd fw/tests/hello_world
make                                  # default GCC_PREFIX=riscv64-unknown-elf
# or: make CC=/path/to/riscv64-unknown-elf-gcc
```

This produces `hello_world.itcm.hex` and `hello_world.dtcm.hex`, which the DV
boot test (`tests/sep_hello_world_test.py`) backdoor-loads into the TCM
responder.

> The OSS `run_dv.py` flow has no `cgen` stage — firmware is built here, then
> `run_dv.py --dut sep --items sep_hello_world_test --stage sim` boots it.

## Adding a test

1. `fw/tests/<name>/<name>.c` with `int main(void)` (return 0 = PASS).
2. `fw/tests/<name>/Makefile`: `TEST := <name>` then `include ../../build/common.mk`.
3. Point the DV test at `<name>.itcm.hex` / `.dtcm.hex`.
