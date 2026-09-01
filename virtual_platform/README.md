# OCAH Virtual Platform

The integrated SEP virtual platform: the [`tt-oca-harness-model`](https://github.com/tenstorrent/tt-oca-harness-model)
SystemC simulator as a submodule, a Makefile that builds its `sep-vp` executable (and the
SystemC/Boost/OpenSSL/CCI dependencies it needs), and the `sepvp` Python runner + pytest
harness for running SEP firmware — including the production boot ROM from
`hw/sys/sep/bootrom/prod` — on the functional model.

## Layout

```
virtual_platform/
  Makefile          VP + dependency build, firmware-harness targets (make help)
  vp.mk             ocah.mk fragment: repo-root ocah-vp-* targets
  tt-oca-harness-model/
                    the simulator (git submodule)
  sepvp/            importable runner library (see sepvp/README.md)
  tests/            pytest suites
    test_fuses.py   sepvp.fuses unit tests (no VP build needed)
    fuse_maps/      YAML fuse-map fixtures
    bootcode/       SEP boot ROM tests (positive + OT-SPI negative)
    sim/            OT SPI mux/DMA tests (firmware from tt-oca-harness-model/sw/sep-vp-tests)
    fw/             DV-engine firmware tests run on the VP
```

## Quick start

From the repo root (targets provided by `vp.mk` via `ocah.mk`):

```bash
make ocah-vp-init      # init the tt-oca-harness-model submodule (recursive)
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

Requirements:

- **A C++20-capable compiler on PATH** (g++ ≥ 10; `make check-cxx` verifies, `CXX=...`
  overrides; g++ 11–14 verified). Activate it yourself — e.g. on RHEL via
  `scl enable gcc-toolset-<N> bash`.
- **Boost ≥ 1.74** (`iostreams`, `program_options`) and **OpenSSL ≥ 3.0**: used from
  the system when adequate, otherwise downloaded and built into `local/` automatically.
  `make deps-info` shows what was chosen and why; `VP_SYS_DEPS=0` forces hermetic
  local builds. SystemC and CCI are always built into `local/` (rarely system-installed).
- **A RISC-V cross toolchain** for the firmware builds: on PATH, or point
  `RISCV_TOOLCHAIN=<prefix>` at an install (its `bin/` is prepended). Optional — the
  ROM/DV builds fall back to the container (below), and firmware-dependent tests skip
  cleanly without it.
- `uv` for the Python environment, and network access (or a pre-seeded `downloads/`)
  for the dependency tarballs.

No internal tool mounts are required anywhere in the flow.

The boot ROM and DV-engine firmware compile against picolibc, which bare
riscv-gnu-toolchain installs typically lack; those builds fall back automatically to
the `ocah-toolchain` container via `scripts/docker-run.sh run-here` (build it once
with `./scripts/docker-run.sh build`; see `tools/docker/README.md`). That is the
same image the containerized flow below uses. On hosts where rootless podman's
`--userns=keep-id` fails, extract the image rootfs once and set
`OCAH_TOOLCHAIN_ROOTFS=<dir>` to use the engine-less bubblewrap backend instead.

## Containerized build & run

For hosts with no usable native toolchain at all, the whole VP can be built AND run
in the `ocah-toolchain` container — one image carries the native C++20 toolchain,
apt Boost/OpenSSL, the RISC-V firmware toolchain and the runner's Python (see
`tools/docker/Dockerfile`):

```bash
./scripts/docker-run.sh build         # build the image once (vp-build is an alias)
make -C virtual_platform vp VP_CONTAINER=1        # deps (SystemC/CCI) + sep-vp
make -C virtual_platform vp-test VP_CONTAINER=1   # pytest suites, in-container
make -C virtual_platform boot-run VP_CONTAINER=1 BOOT_ARGS="--boot primary"
./scripts/docker-run.sh vp-shell      # interactive shell, repo bound 1:1
```

A container-built `sep-vp` links the container's glibc and cannot run on older
hosts, so `VP_CONTAINER=1` routes the run/test targets into the container too.
Artifacts are partitioned per environment (`local-ctr/`, `tt-oca-harness-model/vp/build-ctr`)
and never mix with a native build. Where rootless podman's `--userns=keep-id`
fails, extract the image rootfs and set `OCAH_TOOLCHAIN_ROOTFS=<dir>` for the
engine-less bubblewrap backend; on a host with both engines installed,
`OCAH_ENGINE=docker` (or `podman`) pins which one is used.

`.github/workflows/vp.yml` runs both flows — a native build on the runner and a
`VP_CONTAINER=1` build in this image — on every PR that touches the VP, plus
nightly. It is the reference for the exact commands and dependencies each path
needs.

The `sepvp` runner's design — status channels, overlay `.ini` generation, fuse maps —
is documented in [`sepvp/README.md`](sepvp/README.md).
