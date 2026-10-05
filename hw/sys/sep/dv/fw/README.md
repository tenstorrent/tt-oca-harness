<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS firmware

Self-contained boot firmware for the SEP OSS DV environment. Tests supply
`main()` and link against `libsep.a`. The shared DV firmware engine
(`hw/common/dv/fw/compile.mk`, driven by `fw.mk`) emits the gitignored
`.itcm` / `.dtcm` hex images under `fw/build/tests/<name>/`.

```
fw/
  fw.mk             dispatcher: make -f fw.mk dv-fw-tests TEST=<name>
  fw_build_id.c     FW-BUILD-ID string compiled into every image
  fw_src_digest.py  digest of the firmware sources for FW-BUILD-ID
  toolchain.mk      RISC-V prefix / ISA
  drivers/          device drivers (mailbox, DMA, SPI, PIC, eFuse, …)
  include/          firmware-visible headers
  link/             TCM linker scripts (`link/modes/tcm.ld`)
  startup/          crt0
  tests/            per-test C sources (hello_world, DMA, SPI, …)
  build/            generated images (gitignored)
```

The production Boot ROM lives outside this tree, at `hw/sys/sep/bootrom/prod/`.

## Build

`--stage c_compile` is the canonical path. It needs a RISC-V GCC with picolibc
(`--specs=picolibc.specs`). Host installs without picolibc fall back to
`scripts/docker-run.sh`.

```bash
python3 tools/dv/run_dv.py --dut sep --items sep_hello_world_test \
  --stage c_compile --stage flist --stage hdl_compile --stage sim
```

To build one image by hand from the repository root:

```bash
make -C hw/sys/sep/dv/fw -f fw.mk dv-fw-tests TEST=hello_world OCAH_ROOT="$PWD"
```

That writes `fw/build/tests/hello_world/hello_world.{itcm,dtcm}.hex`. The DV
test `sep_hello_world_test` backdoor-loads those into the TCM macros.

`RISCV_TOOLCHAIN` + `RISCV_PREFIX` is the toolchain contract the shared engine
accepts. Leave them unset to use the stage's probe (site toolchain, local xPack,
then the container).

## Adding a test

1. `fw/tests/<name>/<name>.c` with `int main(void)` (return 0 = PASS).
2. Discover it through `fw.mk` / `compile.mk` (no per-test Makefile).
3. Point the testlist entry at `firmware = "<name>"` so `c_compile` builds it.
