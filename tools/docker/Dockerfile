# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# =============================================================================
# ocah-toolchain: the one OCAH build/run image. It carries two toolchains:
#
#   1. RISC-V bare-metal (picolibc) for the DV firmware and the SEP boot ROM.
#   2. A native C++20 toolchain plus the SEP virtual platform's dependencies,
#      so virtual_platform/ can BUILD and RUN sep-vp in here on hosts with no
#      usable native compiler.
#
# Build the image (from tt-oca/):
#   docker build -t ocah-toolchain tools/docker
#   ./scripts/docker-run.sh build
#
# Build firmware (from tt-oca/):
#   docker run --rm -v "$PWD":/work:Z -w /work ocah-toolchain \
#       make ocah-dv-fw-libs TARGET=sep
#   ./scripts/docker-run.sh run make ocah-dv-fw-libs TARGET=sep
#
# Build and run the SEP virtual platform (from tt-oca/):
#   make -C virtual_platform vp      VP_CONTAINER=1
#   make -C virtual_platform vp-test VP_CONTAINER=1
#   ./scripts/docker-run.sh vp-shell
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

# One layer, grouped by what each group is for:
#
# - Base build tools. wget/ca-certificates fetch the VP's SystemC and CCI
#   tarballs; git initializes the model's own nested submodules.
# - RISC-V firmware toolchain: the DV firmware and boot ROM compile against
#   picolibc via --specs=picolibc.specs.
# - Native C++20 toolchain and CMake/autotools for the SystemC/CCI/sep-vp
#   builds. Boost and OpenSSL come from apt and clear the VP's floors
#   (Boost >= 1.74 with iostreams+program_options, OpenSSL >= 3.0 for
#   core_names.h / the EVP_MAC API), so virtual_platform/Makefile's system-deps
#   probes resolve both to /usr and only SystemC + CCI get built from source.
# - Runner Python from apt: the host's uv-managed .venv is not usable in here,
#   so vp-test's import guard (pexpect/yaml/pytest/toml/pyelftools) has to be
#   satisfied by distro packages or it falls into vp-py-deps, which needs uv.
#   cryptography/ruamel.yaml/tomlkit/bitarray serve the tt-boot-manifest
#   packer's uv-less fallback (see hw/sys/sep/bootrom/prod/Makefile).
#
# NOTE: a sep-vp built in here links this image's glibc/libstdc++ and must also
# RUN in here (scripts/docker-run.sh vp-run / vp-shell). Build artifacts land
# in ctr-tagged trees (local-ctr/, vp/build-ctr) so they never mix with a
# native build.
RUN apt-get update && apt-get install -y --no-install-recommends \
        make \
        wget \
        ca-certificates \
        git \
        gcc-riscv64-unknown-elf \
        picolibc-riscv64-unknown-elf \
        g++ \
        cmake \
        autoconf \
        automake \
        libboost-iostreams-dev \
        libboost-program-options-dev \
        libboost-log-dev \
        libssl-dev \
        zlib1g-dev \
        python3 \
        python3-pyelftools \
        python3-yaml \
        python3-pexpect \
        python3-pytest \
        python3-toml \
        python3-cryptography \
        python3-ruamel.yaml \
        python3-tomlkit \
        python3-bitarray \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
