# OCAH Virtual Platform

The integrated OCAH virtual platform: the [`tt-oca-harness-model`](https://github.com/tenstorrent/tt-oca-harness-model)
SystemC simulator as a submodule, a Makefile that builds its three VP executables (and the
dependencies they need), and the `sepvp` Python runner + pytest harness for running SEP
firmware — including the production boot ROM from `hw/sys/sep/bootrom/prod` — on the
functional model.

## The three executables

| Target | Builds | Tree | Extra dependency |
|---|---|---|---|
| `make vp` | `sep-vp` — the SEP subsystem | `tt-oca-harness-model/vp/build` | — |
| `make smc-vp` | `smc-vp` — the SMC subsystem | `.../vp/build_smc` | Whisper ISS |
| `make smu-vp` | `smu-vp` + `libsmc_cluster_smu.so` — SMC and SEP together in one process | `.../vp/build_smc` | Whisper ISS |

`sep-vp` is the default and needs nothing new. **`smc-vp` and `smu-vp` are opt-in**:
asking for either builds the [Whisper ISS](https://github.com/tenstorrent/whisper)
(pinned at `WHISPER_REV`) into `local/` first, which `make vp` never does. They live
in a second build tree because `WHISPER_HOME` is read at *configure* time and decides
whether the SMC and SMU platforms are generated at all, so one tree cannot serve both
cases. Both are gated on that single switch upstream, so they always come together and
share the tree.

`smu-vp` is the only configuration that runs the SMC and SEP subsystems concurrently,
and its tests pass only when *both* halves report PASS — so it is where cross-subsystem
regressions show up.

```bash
make smc-vp                       # builds Whisper on first use, then smc-vp
make smu-vp                       # same tree, adds smu-vp + its companion .so
make smc-test                     # the model's SMC firmware suite  (16 tests)
make smu-test                     # the model's SMU firmware suite  (5 tests)
make smc-test SMC_ARGS=smc-wdt-test        # one test
make smu-test SMU_ARGS=smu-link-test       # one test
make deps-info                    # where every prefix resolves, Whisper included
```

SMC/SMU testing goes through the model's own `sw/{smc,smu}-vp-tests` runners, which
these targets wrap with our resolved prefixes; the `sepvp` package is SEP-specific and
does not drive them.

> **`smu-vp` has a companion artifact.** `libsmc_cluster_smu.so` (the SMC CPU cluster,
> repackaged so Whisper's symbols stay local to it and the SEP side can link its own
> VeeR-ISS fork) is built beside the target, *not* into `bin/`. `smu-vp` bakes that
> build-tree path into its RUNPATH, so it runs in place with no `LD_LIBRARY_PATH` — but
> anything that copies, uploads or caches `smu-vp` must carry the `.so` too, or the copy
> will silently bind to the build tree and then fail once that tree is gone.
> `make env` puts its directory on `LD_LIBRARY_PATH` for exactly this reason.

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
    bootcode/       SEP boot ROM tests and the declarative ROM testlist (see its README.md)
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

Or work in this directory directly — `make help` lists every target:

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
  cleanly without it. The SMC/SMU suites auto-detect a prefix and are happy with
  `riscv64-unknown-elf-`; override with `RISCV_PREFIX=` if yours is named differently.
- **For `smc-vp`/`smu-vp` only**: `git` and network access for the Whisper checkout.
  No extra system packages, and no second RISC-V toolchain.
- `uv` for the Python environment, and network access (or a pre-seeded `downloads/`)
  for the dependency tarballs.

No internal tool mounts are required anywhere in the flow.

The boot ROM and DV-engine firmware compile against picolibc, which bare
riscv-gnu-toolchain installs typically lack; those builds fall back automatically to
the OCAH container via `scripts/docker-run.sh run-here` (build it once
with `./scripts/docker-run.sh build`; the image is defined by `flake.nix` and
`ocah_deps.nix`). That is the
same image the containerized flow below uses. If a container will not start on your
host at all, extract the image rootfs once and set `OCAH_TOOLCHAIN_ROOTFS=<dir>` to
use the engine-less bubblewrap backend instead.

## Containerized build & run

For hosts with no usable native toolchain at all, the whole VP can be built AND run
in the OCAH container. One nix-built image carries the native C++20 toolchain, the
RISC-V firmware toolchain, the runner's Python, and the VP's own dependencies --
SystemC, CCI, Boost, OpenSSL and Whisper -- whose prefixes it exports, so nothing is
built from source in there (see `ocah_deps.nix`):

```bash
./scripts/docker-run.sh build         # build the image once
make -C virtual_platform vp VP_CONTAINER=1        # sep-vp; deps come from the image
make -C virtual_platform vp-test VP_CONTAINER=1   # pytest suites, in-container
make -C virtual_platform boot-run VP_CONTAINER=1 BOOT_ARGS="--boot primary"
make -C virtual_platform smc-vp smu-vp VP_CONTAINER=1   # the SMC/SMU pair
make -C virtual_platform smc-test VP_CONTAINER=1        # and their suites
make -C virtual_platform smu-test VP_CONTAINER=1
./scripts/docker-run.sh shell-here    # interactive shell, repo bound 1:1
```

The same image carries everything `smc-vp` and `smu-vp` need — no extra packages —
and builds the Whisper archives too.

A container-built VP links the container's glibc and cannot run on older
hosts, so `VP_CONTAINER=1` routes the run/test targets into the container too.
Artifacts are partitioned per environment (`local-ctr/`,
`tt-oca-harness-model/vp/build-ctr`, `.../vp/build_smc-ctr`) and never mix with a
native build — which matters for `libsmc_cluster_smu.so` and the Whisper archives
as much as for the binaries. If no container will start on your host, extract the
image rootfs and set `OCAH_TOOLCHAIN_ROOTFS=<dir>` for the engine-less bubblewrap
backend; on a host with both engines installed, `OCAH_ENGINE=docker` (or `podman`)
pins which one is used.

`.github/workflows/vp.yml` runs two jobs, each both ways — a native build on
the runner and a `VP_CONTAINER=1` build in this image — one for `sep-vp` and
one for the `smc-vp`/`smu-vp` pair. The native legs run on every pull request
that is not documentation-only and must pass to merge. The container legs run
after merge: on a push to `main` that touches the VP, nightly, and on manual
dispatch. The `sep-vp` legs run the tests marked `smoke`, one clean boot per ROM
path; the full suite is an offline regression. The workflow is the reference
for the exact commands and dependencies each path needs.

Both paths are supported for all three executables. On a host whose system
compiler is too old (RHEL 8's g++ 8.5 has no C++20), activate a newer one
first — e.g. `source /opt/rh/gcc-toolset-<N>/enable`, or
`scl enable gcc-toolset-<N> bash` — and the Makefile picks it up; there, the
system Boost and OpenSSL are also too old (the floors are Boost >= 1.74 and
OpenSSL >= 3.0, the latter for the `EVP_MAC` API the hmac/kmac peripherals
use), so both get built from source into `local/` and the whole flow is
hermetic.

If the site provides newer ones outside `/usr`, point at them instead and the
two source builds drop out, leaving only SystemC and CCI to compile:

```bash
export BOOST_ROOT=/path/to/boost-1.8x  OPENSSL_ROOT=/path/to/openssl-3.x
make deps-info      # both should read "explicit (environment)"
```

`ldd` on the built `sep-vp` is the check that they were the ones linked.

Building on your own host rather than in the container — what the host must
provide, pointing the build at existing Boost/OpenSSL, and which suites run
without a RISC-V toolchain — is in
[`BUILDING_NATIVELY.md`](BUILDING_NATIVELY.md).

The `sepvp` runner's design — status channels, overlay `.ini` generation, fuse maps —
is documented in [`sepvp/README.md`](sepvp/README.md).

Running the SMC production boot ROM on `smc-vp` needs a different setup from the
firmware suites (the ROM image is preloaded into the modeled ROM rather than
loaded as an ELF, and its console is a scratch register rather than a UART):
see [`RUNNING_THE_SMC_BOOT_ROM.md`](RUNNING_THE_SMC_BOOT_ROM.md).
