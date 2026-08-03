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
#       make ocah-dv-fw-libs TARGET=sep
#   ./scripts/docker-run.sh run make ocah-dv-fw-libs TARGET=sep
#
# Build docs with pulled public images (from tt-oca/):
#   ./scripts/docker-run.sh doc-html trm
#   ./scripts/docker-run.sh doc-pdf trm
#
# See tools/docker/README.md for full documentation.
# =============================================================================

# Pinned by digest for reproducibility; re-resolve with
# `docker manifest inspect debian:trixie-slim` (or a registry API query) to
# refresh, then re-pin here after re-verifying the build.
FROM debian:trixie-slim@sha256:28de0877c2189802884ccd20f15ee41c203573bd87bb6b883f5f46362d24c5c2

RUN apt-get update && apt-get install -y --no-install-recommends \
        make \
        python3 \
        python3-pyelftools \
        gcc-riscv64-unknown-elf \
        picolibc-riscv64-unknown-elf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
