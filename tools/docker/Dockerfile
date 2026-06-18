# =============================================================================
# Minimal RISC-V bare-metal toolchain (picolibc) for OCAH DV firmware.
#
# Build the image (from tt-oca/):
#   docker build -t ocah-fw-toolchain tools/docker
#   ./scripts/fw-toolchain-docker.sh build
#
# Build firmware (from tt-oca/):
#   docker run --rm -v "$PWD":/work:Z -w /work ocah-fw-toolchain \
#       make ocah-dv-fw TARGET=sep
#   ./scripts/fw-toolchain-docker.sh run make ocah-dv-fw TARGET=sep
#
# See tools/docker/README.md for full documentation.
# =============================================================================

FROM debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        make \
        python3 \
        gcc-riscv64-unknown-elf \
        picolibc-riscv64-unknown-elf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
