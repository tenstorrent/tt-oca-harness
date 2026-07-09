# OCAH toolchain container

Provides containerized open tools used by OCAH:

- The local Dockerfile builds only the RISC-V DV firmware image
  (`ocah-toolchain`) from Debian's prebuilt `gcc-riscv64-unknown-elf` and
  `picolibc-riscv64-unknown-elf` packages.
- Documentation uses pulled public images directly:
  `docker.io/antora/antora:3.1.10` for HTML and a digest-pinned
  `docker.io/asciidoctor/docker-asciidoctor` release for PDF (see
  [Pinned image digests](#pinned-image-digests)).
- The open-source lint/synth/format flows (`flows/`) use a third pulled image,
  [`hpretl/iic-osic-tools`](https://github.com/hpretl/iic-osic-tools):
  `slang`, `yosys` (with the `yosys-slang` plugin), `verible`, and several open
  PDKs (IHP SG13G2, Sky130A, GF180mcuD, ...) baked in - see
  `flows/synth/yosys/README.md` for flow-specific usage.

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

## Container user (UID/GID mapping)

Every container the helper script runs is started with `--user "$(id -u):$(id -g)"`
(`HOME` pointed at `/tmp`) instead of each image's baked-in default (root, or
a fixed non-root UID), so files written back into the bind-mounted repo -
build output, generated docs, etc. - are owned by the calling user, not some
other UID, regardless of container engine. Override with
`OCAH_DOCKER_UIDGID=<uid>:<gid>`, or set it to an empty string to run every
container as its image's own default user instead:

```bash
OCAH_DOCKER_UIDGID= ./scripts/docker-run.sh shell
```

Lint/synth/format (`make lint-slang-all`/`make synth-all`/`make format-sv[-check]`) run through
Docker automatically and need no separate invocation - they call
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

## Manual docker commands

Equivalent commands without the helper (run from `tt-oca/`):

```bash
PDF_IMAGE=docker.io/asciidoctor/docker-asciidoctor:1.106.0@sha256:6266e05784c2d8ece9d9fe5e593b12c3beebebbc467135fd6f4a56269c93cea3

docker build -t ocah-toolchain tools/docker

docker run --rm --user "$(id -u):$(id -g)" docker.io/antora/antora:3.1.10 --version
docker run --rm --user "$(id -u):$(id -g)" "$PDF_IMAGE" asciidoctor-pdf --version
docker run --rm --user "$(id -u):$(id -g)" ocah-toolchain riscv64-unknown-elf-gcc --version
docker run --rm --user "$(id -u):$(id -g)" ocah-toolchain riscv64-unknown-elf-gcc -print-multi-lib

docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work:Z -w /work ocah-toolchain \
    make ocah-dv-fw TARGET=sep

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

## Verification (Debian trixie image)

| Target | `ocah-dv-fw` in container | Notes |
|--------|---------------------------|-------|
| SEP | **Pass** | `--specs=picolibc.specs` in `toolchain.mk` |
| KM | **Pass** | Same specs on compile; `-nostdlib` at link (headers only) |
| SMC | **Pass** | Same specs on compile; libgloss link flags deferred to DV-test milestone |

All three subsystems use `--specs=picolibc.specs` for compile-time headers. One
container covers the full driver-archive milestone.

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
  **archive** (`libkm.a`), so compilation does not need that multilib. A future
  link stage would require a custom multilib build.
- **SMC final link (later).** Archive compile uses picolibc headers via
  `--specs=picolibc.specs`. Final ELF link still references legacy libgloss
  crt0/`-lgloss` from tt-oca-hw; migrate to picolibc crt0 at the DV-test milestone.
- The base image is pinned (see [Pinned image digests](#pinned-image-digests)),
  but the `apt-get install` package versions inside it still float with
  whatever is current in Debian trixie at build time. Pin specific package
  versions too if that level of reproducibility becomes important.

## Files

| Path | Role |
|------|------|
| `tools/docker/Dockerfile` | Image definition |
| `scripts/docker-run.sh` | Helper script for running repo commands in the image |
| `hw/common/dv/fw/compile.mk` | Firmware build engine (toolchain contract) |
| `flows/common.mk` | Lint/synth/format build engine (EDA container contract) |
