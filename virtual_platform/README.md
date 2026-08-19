# OCAH Virtual Platform

The integrated SEP virtual platform: the [`tt-oca-sim`](https://github.com/tenstorrent/tt-oca-sim)
SystemC simulator as a submodule, a Makefile that builds its `sep-vp` executable (and the
SystemC/Boost/OpenSSL/CCI dependencies it needs), and the `sepvp` Python runner + pytest
harness for running SEP firmware — including the production boot ROM from
`hw/sys/sep/bootrom/prod` — on the functional model.

## Layout

```
virtual_platform/
  Makefile          VP + dependency build, firmware-harness targets (make help)
  vp.mk             ocah.mk fragment: repo-root ocah-vp-* targets
  tt-oca-sim/       the simulator (git submodule)
  sepvp/            importable runner library (see sepvp/README.md)
  tests/            pytest suites
    test_fuses.py   sepvp.fuses unit tests (no VP build needed)
    fuse_maps/      YAML fuse-map fixtures
    bootcode/       SEP boot ROM tests (positive + OT-SPI negative)
    sim/            OT SPI mux/DMA tests (firmware from tt-oca-sim/sw/sep-vp-tests)
    fw/             DV-engine firmware tests run on the VP
```

## Quick start

From the repo root (targets provided by `vp.mk` via `ocah.mk`):

```bash
make ocah-vp-init      # init the tt-oca-sim submodule (recursive)
make ocah-vp-deps      # one-time: build SystemC/Boost/OpenSSL/CCI into local/ (~1-2 h)
make ocah-vp-build     # build sep-vp (incremental)
make ocah-vp-test      # run the pytest suites
make ocah-vp-boot-run BOOT_ARGS="--boot primary"
```

Or work in this directory directly — `make help` lists everything:

```bash
cd virtual_platform
make vp-py-deps                              # uv sync --inexact --group vp
make boot-run BOOT_ARGS="--boot primary --until SEP_MSG_PRIMARY_CHIPLET"
make fw-run FW_TEST=hello_world              # a hw/sys/sep/dv/fw test on the VP
make vp-test PYTEST_ARGS="--no-build -k bootcode"
```

Requirements: `gcc-toolset-11` (VeeR-ISS does not compile under gcc-13/14), a RISC-V
cross toolchain for the firmware builds (`RISCV_TOOLCHAIN=...`), `uv` for the Python
environment, and network access (or pre-seeded `downloads/`) for the dependency tarballs.

The boot ROM and DV-engine firmware compile against picolibc, which bare
riscv-gnu-toolchain installs typically lack; those builds fall back automatically to
the `ocah-toolchain` container via `scripts/docker-run.sh run-here` (build it once
with `./scripts/docker-run.sh build`; see `tools/docker/README.md`). On hosts where
rootless podman's `--userns=keep-id` fails, extract the image rootfs once and set
`OCAH_TOOLCHAIN_ROOTFS=<dir>` to use the engine-less bubblewrap backend instead.

The `sepvp` runner's design — status channels, overlay `.ini` generation, fuse maps —
is documented in [`sepvp/README.md`](sepvp/README.md).
