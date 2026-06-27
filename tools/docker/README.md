# OCAH toolchain container

Provides containerized open tools used by OCAH:

- The local Dockerfile builds only the RISC-V DV firmware image
  (`ocah-toolchain`) from Debian's prebuilt `gcc-riscv64-unknown-elf` and
  `picolibc-riscv64-unknown-elf` packages.
- Documentation uses pulled public images directly:
  `docker.io/antora/antora:3.1.10` for HTML and
  `docker.io/asciidoctor/docker-asciidoctor:latest` for PDF.

Host OS does not matter; only Docker or Podman is required. Partners building
PDF/HTML docs do not need to build an OCAH image or install the firmware
toolchain.

## Prerequisites

- Docker or Podman (on RHEL, `docker` is often an alias for Podman)

## Quick start (helper script)

From `tt-oca/` (or anywhere — the script resolves the repo root):

```bash
./scripts/docker-run.sh doc-html trm
./scripts/docker-run.sh doc-pdf trm
./scripts/docker-run.sh doc-html integrator
./scripts/docker-run.sh doc-pdf integrator

./scripts/docker-run.sh build
./scripts/docker-run.sh verify
./scripts/docker-run.sh run make ocah-dv-fw TARGET=sep
```

Build all subsystems:

```bash
./scripts/docker-run.sh run make ocah-dv-fw
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

Override the image tag with `OCAH_DOCKER_IMAGE=my-tag`.

## Manual docker commands

Equivalent commands without the helper (run from `tt-oca/`):

```bash
docker build -t ocah-toolchain tools/docker

docker run --rm docker.io/antora/antora:3.1.10 --version
docker run --rm docker.io/asciidoctor/docker-asciidoctor:latest asciidoctor-pdf --version
docker run --rm ocah-toolchain riscv64-unknown-elf-gcc --version
docker run --rm ocah-toolchain riscv64-unknown-elf-gcc -print-multi-lib

docker run --rm -v "$PWD":/work:Z -w /work ocah-toolchain \
    make ocah-dv-fw TARGET=sep

docker run --rm -v "$PWD":/work:Z -w /work \
    docker.io/asciidoctor/docker-asciidoctor:latest \
    env OCAH_DOC_REGEN_REGS=0 make ocah-doc-trm-setup
docker run --rm -v "$PWD":/work:Z -w /work \
    docker.io/antora/antora:3.1.10 \
    --attribute basedir=doc/trm antora-trm-playbook.yml
docker run --rm -v "$PWD":/work:Z -w /work \
    docker.io/asciidoctor/docker-asciidoctor:latest \
    env OCAH_DOC_REGEN_REGS=0 make ocah-doc-trm-pdf
```

On hosts without SELinux (typical Docker Desktop), omit `:Z` from the volume
mount.

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

## Verification (Debian trixie image)

| Target | `ocah-dv-fw` in container | Notes |
|--------|---------------------------|-------|
| SEP | **Pass** | `--specs=picolibc.specs` in `toolchain.mk` |
| KM | **Pass** | Same specs on compile; `-nostdlib` at link (headers only) |
| SMC | **Pass** | Same specs on compile; libgloss link flags deferred to DV-test milestone |

All three subsystems use `--specs=picolibc.specs` for compile-time headers. One
container covers the full driver-archive milestone.

## Caveats

- **KM** targets `rv32emc` / `ilp32e` (RV32E). Stock Debian multilib does not
  include an `ilp32e` libc variant. KM builds `-nostdlib -ffreestanding` into an
  **archive** (`libkm.a`), so compilation does not need that multilib. A future
  link stage would require a custom multilib build.
- **SMC final link (later).** Archive compile uses picolibc headers via
  `--specs=picolibc.specs`. Final ELF link still references legacy libgloss
  crt0/`-lgloss` from tt-oca-hw; migrate to picolibc crt0 at the DV-test milestone.
- Package versions float with the base image tag. Pin the base image and/or apt
  versions if reproducibility becomes important.

## Files

| Path | Role |
|------|------|
| `tools/docker/Dockerfile` | Image definition |
| `scripts/docker-run.sh` | Helper script for running repo commands in the image |
| `hw/common/dv/fw/compile.mk` | Firmware build engine (toolchain contract) |
