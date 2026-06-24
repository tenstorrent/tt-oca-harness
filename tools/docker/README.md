# OCAH firmware toolchain container

Cross-compiles RISC-V DV firmware (SEP, KM, SMC). Host OS does not matter;
only Docker or Podman is required.

There is no separate toolchain build step: `docker build` runs `apt install`
inside the image, pulling pre-built Debian packages (`gcc-riscv64-unknown-elf`,
`picolibc-riscv64-unknown-elf`, and `python3` for artifact postprocessing).
Image build typically takes 1–2 minutes.

## Prerequisites

- Docker or Podman (on RHEL, `docker` is often an alias for Podman)

## Quick start (helper script)

From `tt-oca/` (or anywhere — the script resolves the repo root):

```bash
./scripts/fw-toolchain-docker.sh build
./scripts/fw-toolchain-docker.sh verify
./scripts/fw-toolchain-docker.sh run make ocah-dv-fw TARGET=sep
```

Build all subsystems:

```bash
./scripts/fw-toolchain-docker.sh run make ocah-dv-fw
```

Interactive shell for debugging:

```bash
./scripts/fw-toolchain-docker.sh shell
```

Override the image tag with `OCAH_FW_DOCKER_IMAGE=my-tag`.

## Manual docker commands

Equivalent commands without the helper (run from `tt-oca/`):

```bash
docker build -t ocah-fw-toolchain tools/docker

docker run --rm ocah-fw-toolchain riscv64-unknown-elf-gcc --version
docker run --rm ocah-fw-toolchain riscv64-unknown-elf-gcc -print-multi-lib

docker run --rm -v "$PWD":/work:Z -w /work ocah-fw-toolchain \
    make ocah-dv-fw TARGET=sep
```

On hosts without SELinux (typical Docker Desktop), omit `:Z` from the volume
mount.

## How it works

- The container runs on x86_64 or arm64 Linux; the compiler produces RISC-V
  object code (cross-compilation).
- `riscv64-unknown-elf-gcc` is on `PATH`; leave `RISCV_TOOLCHAIN` empty.
- SEP uses picolibc via `--specs=picolibc.specs` (from
  `picolibc-riscv64-unknown-elf`).
- Users with a compatible host toolchain can skip Docker and run
  `make ocah-dv-fw TARGET=sep` directly.

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
| `scripts/fw-toolchain-docker.sh` | Helper script |
| `hw/common/dv/fw/compile.mk` | Firmware build engine (toolchain contract) |
