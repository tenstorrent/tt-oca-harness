# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# =============================================================================
# Minimal RISC-V bare-metal toolchain (picolibc) for OCAH DV firmware.
#
# Build the firmware image (from tt-oca/):
#   docker build -t ocah-toolchain tools/docker
#   ./scripts/docker-run.sh build
#
# Build firmware (from tt-oca/):
#   docker run --rm -v "$PWD":/work:Z -w /work ocah-toolchain \
#       make ocah-dv-fw TARGET=sep
#   ./scripts/docker-run.sh run make ocah-dv-fw TARGET=sep
#
# Build docs with pulled public images (from tt-oca/):
#   ./scripts/docker-run.sh doc-html trm
#   ./scripts/docker-run.sh doc-pdf trm
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
