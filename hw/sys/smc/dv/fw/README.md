<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->
# SMC OSS DV firmware

C images the SMC CPU cluster runs under DV. Tests supply `main()` and link
against `libsmc.a` (the Freedom-Metal drivers plus the OCCP master BFM in
`common/occp/`). `fw.mk` drives the shared DV firmware engine
(`hw/common/dv/fw/compile.mk`), which emits the gitignored images under
`fw/build/tests/<name>/`: `<name>.ecc.hex` (the simulator preload), and the
`.sram.bin` / `.sram.sym` or `.rom.hex` sidecars of the image's link mode.

```
fw/
  fw.mk          dispatcher: make -f ocah.mk ocah-dv-fw-tests TARGET=smc [TEST=<name>]
  toolchain.mk   RISC-V prefix / ISA
  postprocess.mk ECC hex and preload-address conversion (shared with bootrom/dummy)
  common/occp/   OCCP master BFM library (rom-mode images)
  drivers/       Freedom-Metal device drivers and the OpenTitan I2C driver
  include/       firmware-visible headers (metal/, smc_*.h, smc_stackless_test.h)
  link/modes/    linker scripts: sram.ld (default), rom.ld
  scripts/       bin_to_verilog.py, update_smc_hex_to_preload_addr.py
  startup/       entry.S, crt0.S, trap/vector, exit_stub.c
  tests/         one directory per image
  build/         generated images (gitignored)
```

The production boot ROM lives outside this tree, at `hw/sys/smc/bootrom/prod/`;
`[c_build.bootrom]` in `smc_sim_cfg.toml` builds it, not a `tests/` image.

## Build

The images need a RISC-V GCC with picolibc (`--specs=picolibc.specs`). From the
repository root, with the container toolchain:

```bash
./scripts/docker-run.sh run-here make -f ocah.mk ocah-dv-fw-tests TARGET=smc
./scripts/docker-run.sh run-here make -f ocah.mk ocah-dv-fw-tests TARGET=smc TEST=hello_world
```

Clean with `ocah-dv-fw-clean TARGET=smc` after a toolchain or container change;
Make compares timestamps only.

Under the runner, a testlist entry with `firmware = "<name>"` inserts the
`c_compile` stage, builds `<name>` through `[c_build.default]` and stages the
declared outputs into the per-test simulator directory by basename
(`testlists/fw.toml` states the contract). Run recipes are in
`hw/sys/smc/dv/README.md`.

## Adding a test

A new `tests/<name>/` is added in the same change as its consumer and its row.
Nothing in the build enforces this: `compile.mk` discovers and builds every
`tests/<name>/` directory whether or not a testlist names it, so a clean
`ocah-dv-fw-tests` run says nothing about consumers; most directories have no
consumer in this tree, and the record says which. The check is the record,
applied at review: every directory under `tests/` has exactly one row that is
not `superseded`, and every such row has a directory.

The change that adds an image carries:

1. Its consumer: a `[[tests]]` entry with `firmware = "<name>"` (or
   `firmware = { name, mode }` for a rom-mode OCCP image) in a testlist, and
   the cocotb leaf it drives -- `cocotb/tests/smc_fw_<name>_test.py` on the
   `smc_fw_hello_world_test` pattern (fire-and-forget verdict on
   `CPU_CTRL SCRATCH_0`) or the `smc_fw_plic_claim_test` pattern
   (`arm_value` plus an `on_armed` stimulus). A rom-mode image also needs a
   `[c_build.*]` block that builds it; a generic one is added with the first
   image that consumes it.
2. Its row in `docs/SMC_VPLAN.adoc` (Known Limitations, "SMC firmware image disposition"), the disposition of
   record for every image name. An image whose consumer is not yet in the tree
   is a `deferred` row with the blocker and the condition that closes it.
3. Its VPLAN card (`docs/SMC_VPLAN.adoc`, FIRMWARE table).

The image itself: `tests/<name>/<name>.c` with `int main(void)` that ends in
`test_pass(0)` / `test_fail(0)` (never by returning); progress words the cocotb
half waits for go on other scratch registers. `compile.mk` discovers the
directory; `fw.mk` needs a line only for `FW_TEST_MODE_<name> := rom`.

A new image with no consumer in the tree is added only as a `deferred` row
that names the blocker and the consumer that closes it; an image with neither a
consumer nor such a row is not added. An image whose consumer goes away is
superseded: its directory leaves the tree and its row in the disposition record
names what proves the property now. An image whose only consumer is a
regression outside this repository stays as an `external-consumer` row that
names that consumer; the same holds for a shared header under `tests/` or
`include/` that such a regression's firmware includes.
