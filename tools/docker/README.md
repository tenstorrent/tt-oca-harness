# OCAH containers

`tools/docker/Dockerfile` builds the one locally-built image, `ocah-toolchain`,
which carries **both** the RISC-V DV firmware toolchain and everything the OCAH
virtual platform needs to build and run all three of its executables — `sep-vp`,
`smc-vp` and `smu-vp`. Docs and EDA use **pulled**
public images. `scripts/docker-run.sh` is the shared front door: each
subcommand picks an image.

| Need | Image | How you get it | `docker-run.sh` |
|------|--------|----------------|-----------------|
| DV firmware (`riscv64-unknown-elf-gcc`, picolibc) | `ocah-toolchain` | **Build** from `tools/docker/Dockerfile` | `build`, `run`, `shell`, `verify` |
| OCAH virtual platform (`g++`, cmake, Boost/OpenSSL, runner Python) | `ocah-toolchain` (same image) | **Build** from `tools/docker/Dockerfile` | `vp-build`, `vp-run`, `vp-shell`, `vp-verify` |
| Docs HTML | `docker.io/antora/antora:3.1.10` | Pull | `doc-html` |
| Docs PDF | digest-pinned `docker.io/asciidoctor/docker-asciidoctor` | Pull (see [Pinned image digests](#pinned-image-digests)) | `doc-pdf` |
| EDA (yosys + PDKs; also slang/verible in-container) | [`hpretl/iic-osic-tools`](https://github.com/hpretl/iic-osic-tools) | Pull | `eda-run`, `eda-shell` |

Host OS does not matter; only Docker or Podman is required. Partners building
PDF/HTML docs do not need to build `ocah-toolchain` or install the firmware
toolchain. Lint/format Make targets prefer tools on `PATH`; use `eda-run` when
you want the container instead. Synth Make targets still call `eda-run` by
default — see `flows/synth/yosys/README.md`.

## Prerequisites

- Docker or Podman (on RHEL, `docker` is often an alias for Podman)

## Quick start (`docker-run.sh`)

From the `tt-oca-harness` repo root (or anywhere — the script resolves the repo root). Build the
firmware image once before `run` / `shell` / `verify`:

```bash
# Docs (pulled images; no local build)
./scripts/docker-run.sh doc-html trm
./scripts/docker-run.sh doc-pdf trm
./scripts/docker-run.sh doc-html integrator
./scripts/docker-run.sh doc-pdf integrator

# Firmware (build ocah-toolchain once, then run)
./scripts/docker-run.sh build
./scripts/docker-run.sh verify
./scripts/docker-run.sh run make ocah-dv-fw-libs TARGET=sep
```

Build all subsystems:

```bash
./scripts/docker-run.sh run make ocah-dv-fw-libs
```

Build both documentation products:

```bash
./scripts/docker-run.sh doc-html trm
./scripts/docker-run.sh doc-html integrator
./scripts/docker-run.sh doc-pdf trm
./scripts/docker-run.sh doc-pdf integrator
```

Interactive shell for debugging:

```bash
./scripts/docker-run.sh shell
```

Override the image tag with `OCAH_DOCKER_IMAGE=my-tag`. On a host that has both
podman and docker installed, pin the engine with `OCAH_ENGINE=docker` (or
`podman`) instead of taking whichever is found first.

## Virtual platform (`sep-vp`, `smc-vp`, `smu-vp`)

The same image also builds and runs the OCAH virtual platform, for hosts with no
usable native C++20 toolchain. On top of the firmware packages it carries `g++`,
`cmake`, autotools, Boost (`iostreams`, `program_options`, `log`) and OpenSSL
dev libraries, `zlib1g-dev`, and the runner's Python (`pexpect`, `pytest`,
`yaml`, `toml`, `pyelftools`, plus the `tt-boot-manifest` packer's
`cryptography`, `ruamel.yaml`, `tomlkit`, `bitarray`). Boost and OpenSSL from
apt clear the VP's floors, so `virtual_platform/Makefile` resolves both to
`/usr` and only builds SystemC and CCI from source.

That set covers all three executables: `smc-vp` and `smu-vp` need **no extra
packages** beyond it. Their one additional dependency, the Whisper ISS, is
source that `virtual_platform/Makefile` clones and builds into `local-ctr/`
like SystemC and CCI, rather than something baked into the image. They also
reuse this image's `riscv64-unknown-elf-` for their firmware suites, so there
is no second cross toolchain either.

```bash
./scripts/docker-run.sh vp-verify                  # g++ and cmake versions
make -C virtual_platform vp      VP_CONTAINER=1    # deps (SystemC/CCI) + sep-vp
make -C virtual_platform vp-test VP_CONTAINER=1    # pytest suites, in-container
make -C virtual_platform smc-vp smu-vp VP_CONTAINER=1   # + Whisper, then both
make -C virtual_platform smc-test VP_CONTAINER=1   # the model's SMC suite
make -C virtual_platform smu-test VP_CONTAINER=1   # the model's SMU suite
./scripts/docker-run.sh vp-shell                   # interactive, repo bound 1:1
```

`vp-build` and `vp-run` are aliases for `build` and `run-here`, one image
serving both toolchains. A container-built VP links the container's glibc and
**must also run in the container**, which is why the VP path uses the 1:1
host-path mount rather than `/work`: `VP_CONTAINER=1` forwards the run/test
targets into the container too, and partitions artifacts into `local-ctr/`,
`vp/build-ctr` and `vp/build_smc-ctr` so they never mix with a native build —
the Whisper archives and `smu-vp`'s companion `libsmc_cluster_smu.so` included.
See `virtual_platform/README.md`.

## Container user (UID/GID mapping)

The goal is that files written back into the bind-mounted repo - build output,
generated docs, etc. - are owned by the calling user rather than some other
UID, whichever engine is in use. How that is achieved differs by engine:

- **Rootless podman** already maps the container's root to the caller's UID, so
  bind-mounted output comes out caller-owned with no flag at all. No `--user` is
  passed (it trips a runc `setgroups: invalid argument` failure on some RHEL 8
  hosts). `--userns=keep-id`, which additionally makes the container *see* the
  caller's own UID, is passed only when the account's `/etc/subuid` allocation
  is wide enough to map that UID: podman maps container UIDs `0..uid-1` onto
  that range first, so a large LDAP/AD-assigned UID with the customary
  65536-wide range does not fit, and podman fails before the container starts
  (`chowning container workdir ...: invalid argument`). Force the decision
  either way with `OCAH_PODMAN_KEEP_ID=1` / `=0`.
- **Rootful docker** maps container root to real root, so `--user
  "$(id -u):$(id -g)"` is passed (with `HOME` pointed at `/tmp`).

Override the UID/GID with `OCAH_DOCKER_UIDGID=<uid>:<gid>`, or set it to an
empty string to run every container as its image's own default user instead:

```bash
OCAH_DOCKER_UIDGID= ./scripts/docker-run.sh shell
```

SystemVerilog lint and format Make targets (`make lint-slang-all`,
`make lint-verilator-all`, `make format-sv[-check]`, and
`make lint-sv-verible`) require the corresponding native tool on `PATH`. If a
tool is missing, Make prints an install hint and the matching container
command, e.g. `./scripts/docker-run.sh eda-run make lint-slang`. Synthesis
(`make synth-all`) still runs through Docker by default via
`./scripts/docker-run.sh eda-run` internally. The subcommand is also available
directly, e.g. for ad-hoc debugging:

```bash
./scripts/docker-run.sh eda-run yosys --version
./scripts/docker-run.sh eda-shell
```

Unlike `run`/`shell` (which mount the repo at `/work`), `eda-run`/`eda-shell`
mount the repo at its own host-absolute path, because the `.f` filelists these
flows feed to the container are generated natively by `bender` beforehand and
already contain host-absolute paths. Override the image tag with
`OCAH_EDA_IMAGE=my-tag`.

`run-here` is the firmware-image counterpart to `eda-run`: it runs in
`ocah-toolchain` but mounts the repo at its host-absolute path (instead of
`/work`) so commands that reference absolute host paths resolve inside the
container. The DV `cgen` flow uses it to build firmware, e.g.
`./scripts/docker-run.sh run-here make -C "$OCH_ROOT" -f ocah.mk ocah-dv-fw-tests TARGET=smc`.

## Manual docker commands

Equivalent commands without the helper (run from the `tt-oca-harness` repo root):

```bash
PDF_IMAGE=docker.io/asciidoctor/docker-asciidoctor:1.106.0@sha256:6266e05784c2d8ece9d9fe5e593b12c3beebebbc467135fd6f4a56269c93cea3

docker build -t ocah-toolchain tools/docker

docker run --rm --user "$(id -u):$(id -g)" docker.io/antora/antora:3.1.10 --version
docker run --rm --user "$(id -u):$(id -g)" "$PDF_IMAGE" asciidoctor-pdf --version
docker run --rm --user "$(id -u):$(id -g)" ocah-toolchain riscv64-unknown-elf-gcc --version
docker run --rm --user "$(id -u):$(id -g)" ocah-toolchain riscv64-unknown-elf-gcc -print-multi-lib

docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work:Z -w /work ocah-toolchain \
    make ocah-dv-fw-libs TARGET=sep

docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work:Z -w /work \
    "$PDF_IMAGE" \
    env OCAH_DOC_REGEN_REGS=0 make ocah-doc-trm-setup
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work:Z -w /work \
    docker.io/antora/antora:3.1.10 \
    --attribute basedir=doc/trm antora-trm-playbook.yml
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work:Z -w /work \
    "$PDF_IMAGE" \
    env OCAH_DOC_REGEN_REGS=0 make ocah-doc-trm-pdf

docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":"$PWD":Z -w "$PWD" \
    hpretl/iic-osic-tools:2025.12 \
    slang --version
```

`$PDF_IMAGE` is kept as a variable above only for brevity; see
[Pinned image digests](#pinned-image-digests) for why it is pinned by digest.
On hosts without SELinux (typical Docker Desktop), omit `:Z` from the volume
mount; drop `--user "$(id -u):$(id -g)" -e HOME=/tmp` to run as each image's
own default user instead.

## How it works

- The firmware container runs on x86_64 or arm64 Linux; the compiler produces
  RISC-V object code (cross-compilation).
- In `ocah-toolchain`, `riscv64-unknown-elf-gcc` is on `PATH`; leave
  `RISCV_TOOLCHAIN` empty.
- SEP uses picolibc via `--specs=picolibc.specs` (from
  `picolibc-riscv64-unknown-elf`).
- Documentation helpers set `OCAH_DOC_REGEN_REGS=0` because generated register
  docs are checked in. Regenerate register docs before building the doc products
  when the RDL changes.
- Users with a compatible host toolchain can skip Docker and run
  the same `make` targets directly.

## Verification (`ocah-toolchain`)

| Target | `ocah-dv-fw-libs` in container | Notes |
|--------|---------------------------|-------|
| SEP | **Pass** | `--specs=picolibc.specs` in `toolchain.mk` |
| KM | **Pass** | Same specs on compile; `-nostdlib` at link (headers only) |
| SMC | **Pass** | Same specs on compile |
| `sep-vp` | **Pass** | `vp-verify` (g++/cmake), then `make -C virtual_platform vp VP_CONTAINER=1` |
| `smc-vp` | **Pass** | `make -C virtual_platform smc-vp VP_CONTAINER=1`; `smc-test` runs 15/15 green with this image's `riscv64-unknown-elf-` |
| `smu-vp` | **Pass** | `make -C virtual_platform smu-vp VP_CONTAINER=1`; `smu-test` runs 5/5 green, each requiring both the SMC and SEP halves to report PASS |

All three firmware subsystems use `--specs=picolibc.specs` for compile-time
headers. The `vp` workflow (`.github/workflows/vp.yml`) exercises the VP rows on
every relevant PR and nightly.

## Pinned image digests

Images that are pulled rather than built locally are pinned by digest (in
addition to a human-readable tag) so a rebuild months later resolves to the
exact same image instead of whatever a floating tag - `latest` especially -
happens to point to that day:

- `tools/docker/Dockerfile`'s `debian:trixie-slim` base.
- `scripts/docker-run.sh`'s default `OCAH_DOC_PDF_IMAGE` (previously
  `docker-asciidoctor:latest`, which tracks that project's main branch rather
  than a release; now a pinned release tag instead).

`docker.io/antora/antora:3.1.10` and `hpretl/iic-osic-tools:2025.12` are left
tag-only: both are release tags from projects that do not rewrite them after
publishing, so the tag alone is already reproducible in practice.

To refresh a pin, resolve the new digest for the desired tag (e.g. `docker
manifest inspect <image>:<tag>`, or an equivalent registry API query) and
update the reference in place; re-verify the affected build before landing
the change.

## Caveats

- **KM** targets `rv32emc` / `ilp32e` (RV32E). Stock Debian multilib does not
  include an `ilp32e` libc variant. KM builds `-nostdlib -ffreestanding` into an
  **archive** (`libkey_manager.a`), so compilation does not need that multilib.
- The base image is pinned (see [Pinned image digests](#pinned-image-digests)),
  but the `apt-get install` package versions inside it still float with
  whatever is current in Debian trixie at build time. Pin specific package
  versions too if that level of reproducibility becomes important.
- Carrying both toolchains makes the image substantially larger than a
  firmware-only one (roughly 2.4 GB installed versus 1.7 GB), which everyone
  building DV firmware now pays. Adding `smc-vp`/`smu-vp` did **not** grow it
  further: they need no new packages, and Whisper is built into
  `virtual_platform/local-ctr/` rather than baked in. That is the accepted cost of a single image:
  a separate VP image would have to duplicate the RISC-V toolchain anyway, and
  two images meant two Dockerfile hashes, two tarball caches and two rootfs
  extractions to keep in sync.

## Files

| Path | Role |
|------|------|
| `tools/docker/Dockerfile` | Builds `ocah-toolchain` (firmware **and** virtual platform) |
| `scripts/docker-run.sh` | Multi-image helper (`build`/`run`/`vp-*`/`doc-*`/`eda-*`) |
| `.github/workflows/vp.yml` | CI: builds and tests all three VPs, each both natively and in this image |
| `hw/common/dv/fw/compile.mk` | Firmware build engine (native or `run`) |
| `flows/common.mk` | Lint/synth helpers (`eda-run` for synth; native-or-fail for slang/verible) |
