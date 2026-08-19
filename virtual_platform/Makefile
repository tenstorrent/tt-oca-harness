# =============================================================================
# SEP Virtual Platform build (CI-aligned)
#
# Mirrors tt-oca-sim/.github/workflows/ci-rhel8.yml: builds SystemC, Boost,
# OpenSSL, and CCI from source into ./local, then
# configures the VP via tt-oca-sim/vp/configure_vp.sh and builds the sep-vp
# executable.
#
# Quick start:
#   make scratch-build   # clean rebuild of everything (deps + sep-vp)
#   make vp              # rebuild just sep-vp (deps assumed built; incremental)
#   make clean           # wipe downloads/, local/, and tt-oca-sim/vp/build
#
# Run "make help" for the full target/variable list. The repo-level entry
# points are the ocah-vp-* targets in vp.mk (included by ocah.mk).
# =============================================================================

SHELL       := /bin/bash
.SHELLFLAGS := -ec
.ONESHELL:
.DELETE_ON_ERROR:
.DEFAULT_GOAL := help

# ---- Overridable configuration ---------------------------------------------
# GCC_TOOLSET: CI builds with gcc-toolset-12, which is NOT installed here
# (this box has 9/11/13/14). gcc-toolset-13/14 fail to compile VeeR-ISS
# (sep/cpu/VeeR-ISS/Tlb.cpp: "partial specialization of std::hash<basic_string>
# after instantiation" — a GCC-13 libstdc++ header-ordering strictness). GCC 11
# compiles the full C++20 tree cleanly, so it is the default here. Override if
# gcc-toolset-12 becomes available: make vp GCC_TOOLSET=gcc-toolset-12
# (Keep comments on their own lines: an inline comment bakes trailing
#  whitespace into the variable value, which breaks `source .../enable`.)
GCC_TOOLSET     ?= gcc-toolset-11
CXX_STD         ?= 20
SYSTEMC_VERSION ?= 3.0.2
BOOST_VERSION   ?= 1.84.0
OPENSSL_VERSION ?= 3.3.2
CCI_VERSION     ?= 1.0.2
NPROC           ?= $(shell nproc)
# SW_TEST: used by the optional `smoke` target
SW_TEST         ?= sep-gpio-test
# RISCV_TOOLCHAIN: prepended to PATH for the firmware builds
RISCV_TOOLCHAIN ?= /tools_soc/opensrc/riscv-gnu-toolchain/2025.01.20-rhel-8.10
# SMOKE_TIMEOUT: seconds to let the VP run (it does not self-terminate)
SMOKE_TIMEOUT   ?= 20

# ---- Derived paths ----------------------------------------------------------
VP_DIR       := $(CURDIR)
LOCAL_DIR    := $(VP_DIR)/local
DOWNLOAD_DIR := $(VP_DIR)/downloads
OCAH_ROOT    := $(abspath $(VP_DIR)/..)
SIM_DIR      := $(VP_DIR)/tt-oca-sim
VP_SRC_DIR   := $(SIM_DIR)/vp
VP_BUILD_DIR := $(VP_SRC_DIR)/build
SEP_VP_BIN   := $(VP_BUILD_DIR)/bin/sep-vp

# ---- Firmware test harness (sepvp/ + tests/) --------------------------------
# Python from the repo's uv-managed venv (`make vp-py-deps` creates/populates it
# via `uv sync --inexact --group vp`).
UV            ?= uv
PYTHON        ?= $(OCAH_ROOT)/.venv/bin/python
BOOTCODE_DIR  := $(OCAH_ROOT)/hw/sys/sep/bootrom/prod
# SEP_MSG_* status-name table baked into sep-vp's sep_scratch_cold decoder. tt-oca-sim
# exposes this as a CMake cache variable (accepts TSV rows or a C header of #defines);
# without it the VP falls back to its vendored snapshot, which lags this repo's table
# and decodes newer codes as SEP_MSG_UNKNOWN. The checked-in bootrom header is the
# exact table the boot ROM compiles against, so decoder and firmware cannot drift.
# Changing this value requires a reconfigure: `make vp-clean` (baked in at configure time).
STATUS_VALUES_PATH ?= $(BOOTCODE_DIR)/include/status_values.h
# The SEP VP models the OpenTitan SPI host only. The Cadence xSPI controller is
# closed-source IP that was removed from the open SEP; it is not (and will not be)
# modeled in the VP. VP boot therefore always builds the OpenTitan controller
# variant (the bootrom's ot-toolchain-images target -> build_ot/) — never the
# default Cadence build.
BOOT_OT_BUILD_DIR := build_ot
BOOT_ELF          := $(BOOTCODE_DIR)/$(BOOT_OT_BUILD_DIR)/boot_rom.elf
# Signed SPI image for the OT-negative pytest suite (generated, not prebuilt).
SECURE_BOOT_PRELOAD := $(BOOTCODE_DIR)/build/secure_boot.spi_preload
# Pass-through args: `make boot-run BOOT_ARGS="--boot primary --until SEP_MSG_PRIMARY_CHIPLET"`
BOOT_ARGS     ?=
FW_ARGS       ?=
PYTEST_ARGS   ?=
# Prepend the venv (python3 with pyelftools for the OTBN codegen) and the RISC-V
# toolchain (if present) for the firmware builds.
FW_ENV = export PATH="$(dir $(PYTHON)):$$PATH"; \
         if [ -d "$(RISCV_TOOLCHAIN)/bin" ]; then export PATH="$(RISCV_TOOLCHAIN)/bin:$$PATH"; fi

# ---- Dependency install prefixes (override to use an existing install) ------
SYSTEMC_HOME ?= $(LOCAL_DIR)/systemc-$(SYSTEMC_VERSION)
BOOST_ROOT   ?= $(LOCAL_DIR)/boost-$(BOOST_VERSION)
OPENSSL_ROOT ?= $(LOCAL_DIR)/openssl-$(OPENSSL_VERSION)
CCI_HOME     ?= $(LOCAL_DIR)/cci-$(CCI_VERSION)

# Sentinel files that mark a dependency as installed (an existing install that
# already has these will be detected, so its build step is skipped).
SYSTEMC_SENTINEL := $(SYSTEMC_HOME)/include/systemc.h
BOOST_SENTINEL   := $(BOOST_ROOT)/include/boost/version.hpp
OPENSSL_SENTINEL := $(OPENSSL_ROOT)/include/openssl/ssl.h
CCI_SENTINEL     := $(CCI_HOME)/lib/libcci.a

# ---- Runtime env script (generated by `make env`) ---------------------------
# Resolve each dependency's library subdir robustly (lib-linux64 / lib64 / lib),
# falling back to the canonical default when the dep is not built yet. This is
# also where an overridden prefix (e.g. a /tools_soc install) gets its layout right.
ENV_SCRIPT      := $(VP_DIR)/setup_environment.sh
SYSTEMC_LIBDIR  := $(or $(firstword $(wildcard $(SYSTEMC_HOME)/lib-linux64 $(SYSTEMC_HOME)/lib64 $(SYSTEMC_HOME)/lib)),$(SYSTEMC_HOME)/lib-linux64)
CCI_LIBDIR      := $(or $(firstword $(wildcard $(CCI_HOME)/lib $(CCI_HOME)/lib64 $(CCI_HOME)/lib-linux64)),$(CCI_HOME)/lib)
BOOST_LIBDIR    := $(or $(firstword $(wildcard $(BOOST_ROOT)/lib $(BOOST_ROOT)/lib64)),$(BOOST_ROOT)/lib)
OPENSSL_LIBDIR  := $(or $(firstword $(wildcard $(OPENSSL_ROOT)/lib64 $(OPENSSL_ROOT)/lib)),$(OPENSSL_ROOT)/lib64)

# ---- Download artifacts -----------------------------------------------------
BOOST_USCORE    := boost_$(subst .,_,$(BOOST_VERSION))
SYSTEMC_TARBALL := $(DOWNLOAD_DIR)/systemc-$(SYSTEMC_VERSION).tar.gz
BOOST_TARBALL   := $(DOWNLOAD_DIR)/$(BOOST_USCORE).tar.gz
OPENSSL_TARBALL := $(DOWNLOAD_DIR)/openssl-$(OPENSSL_VERSION).tar.gz
CCI_TARBALL     := $(DOWNLOAD_DIR)/cci_v$(CCI_VERSION).tar.gz

# Activate the C++20 toolchain at the top of each build recipe.
ACTIVATE := source /opt/rh/$(GCC_TOOLSET)/enable

.PHONY: help scratch-build download deps vp vp-clean clean env enable_vp \
        systemc boost openssl cci submodule-init check-tt-oca-sim smoke \
        boot-build boot-secure-image boot-run fw-run vp-test vp-py-deps

# =============================================================================
# Help
# =============================================================================
help:
	@echo "SEP Virtual Platform build (mirrors tt-oca-sim CI)"
	@echo ""
	@echo "Primary targets:"
	@echo "  scratch-build  - clean, then build all deps and sep-vp from scratch"
	@echo "  vp             - build/rebuild sep-vp (incremental; deps assumed built)"
	@echo "  vp-clean       - wipe vp/build and reconfigure + rebuild sep-vp"
	@echo "  clean          - remove downloads/, local/, and tt-oca-sim/vp/build"
	@echo "  env/enable_vp  - write setup_environment.sh to source for running sep-vp standalone"
	@echo ""
	@echo "Phase targets:"
	@echo "  download       - fetch the 4 dependency source tarballs into downloads/"
	@echo "  deps           - build+install SystemC, Boost, OpenSSL, CCI into local/"
	@echo "  systemc boost openssl cci - build a single dependency"
	@echo "  submodule-init - init the tt-oca-sim submodule (recursive)"
	@echo "  smoke          - (optional) build+run a sw/sep-vp-tests test in sep-vp"
	@echo ""
	@echo "Firmware test harness (sepvp/ + tests/):"
	@echo "  boot-build       - build the SEP boot ROM, OpenTitan SPI variant (-> build_ot/boot_rom.elf)"
	@echo "  boot-secure-image- generate the signed SPI image (-> build/secure_boot.spi_preload)"
	@echo "  boot-run         - build + run boot_rom.elf on sep-vp (BOOT_ARGS=\"--boot primary ...\")"
	@echo "  fw-run           - build + run a hw/sys/sep/dv/fw test (FW_TEST=<name>, FW_ARGS=...)"
	@echo "  vp-test          - run the pytest harness suite (PYTEST_ARGS=...)"
	@echo "  vp-py-deps       - sync harness Python deps into the uv venv (uv sync --group vp)"
	@echo ""
	@echo "Key variables (override on the command line):"
	@echo "  GCC_TOOLSET=$(GCC_TOOLSET)   CXX_STD=$(CXX_STD)   NPROC=$(NPROC)"
	@echo "  SYSTEMC_VERSION=$(SYSTEMC_VERSION)  BOOST_VERSION=$(BOOST_VERSION)  OPENSSL_VERSION=$(OPENSSL_VERSION)  CCI_VERSION=$(CCI_VERSION)"
	@echo "  SYSTEMC_HOME / BOOST_ROOT / OPENSSL_ROOT / CCI_HOME  (point at an existing install to skip its build)"
	@echo ""
	@echo "Examples:"
	@echo "  make scratch-build"
	@echo "  make vp"
	@echo "  make env && source setup_environment.sh   # then run sep-vp directly"
	@echo "  make deps BOOST_ROOT=/tools_soc/opensrc/boost/1.87.0 OPENSSL_ROOT=/tools_soc/opensrc/openssl/3.5.4"

# =============================================================================
# Aggregate phases
# =============================================================================
scratch-build:
	@echo "[VP] === Scratch build: clean -> deps -> vp ==="
	$(MAKE) clean
	$(MAKE) deps
	$(MAKE) vp
	$(MAKE) env
	echo "[VP] === Scratch build complete: $(SEP_VP_BIN) ==="
	echo "[VP]     Run sep-vp standalone with:  source $(ENV_SCRIPT)"

download: $(SYSTEMC_TARBALL) $(BOOST_TARBALL) $(OPENSSL_TARBALL) $(CCI_TARBALL)

deps: $(SYSTEMC_SENTINEL) $(BOOST_SENTINEL) $(OPENSSL_SENTINEL) $(CCI_SENTINEL)

systemc: $(SYSTEMC_SENTINEL)
boost:   $(BOOST_SENTINEL)
openssl: $(OPENSSL_SENTINEL)
cci:     $(CCI_SENTINEL)

vp: vp-build

# =============================================================================
# Directories
# =============================================================================
$(LOCAL_DIR) $(DOWNLOAD_DIR):
	mkdir -p $@

# =============================================================================
# Downloads (deterministic filenames via wget -O)
# =============================================================================
$(SYSTEMC_TARBALL): | $(DOWNLOAD_DIR)
	@echo "[VP] Downloading SystemC $(SYSTEMC_VERSION)..."
	wget -q -O $@ https://github.com/accellera-official/systemc/archive/refs/tags/$(SYSTEMC_VERSION).tar.gz

$(BOOST_TARBALL): | $(DOWNLOAD_DIR)
	@echo "[VP] Downloading Boost $(BOOST_VERSION)..."
	wget -q -O $@ https://archives.boost.io/release/$(BOOST_VERSION)/source/$(BOOST_USCORE).tar.gz

$(OPENSSL_TARBALL): | $(DOWNLOAD_DIR)
	@echo "[VP] Downloading OpenSSL $(OPENSSL_VERSION)..."
	wget -q -O $@ https://github.com/openssl/openssl/releases/download/openssl-$(OPENSSL_VERSION)/openssl-$(OPENSSL_VERSION).tar.gz

$(CCI_TARBALL): | $(DOWNLOAD_DIR)
	@echo "[VP] Downloading CCI $(CCI_VERSION)..."
	wget -q -O $@ https://github.com/accellera-official/cci/releases/download/v$(CCI_VERSION)/cci_v$(CCI_VERSION).tar.gz

# =============================================================================
# Dependency builds (commands lifted from ci-rhel8.yml Job 1)
# =============================================================================
$(SYSTEMC_SENTINEL): $(SYSTEMC_TARBALL) | $(LOCAL_DIR)
	@echo "[VP] Building SystemC $(SYSTEMC_VERSION)..."
	$(ACTIVATE)
	rm -rf $(DOWNLOAD_DIR)/systemc-$(SYSTEMC_VERSION)
	tar zxf $(SYSTEMC_TARBALL) -C $(DOWNLOAD_DIR)
	cd $(DOWNLOAD_DIR)/systemc-$(SYSTEMC_VERSION)
	touch docs/DEVELOPMENT.md
	mkdir -p objdir
	cd objdir
	../configure --prefix=$(SYSTEMC_HOME) CXXFLAGS="-std=c++$(CXX_STD)"
	make -j$(NPROC)
	make install

$(BOOST_SENTINEL): $(BOOST_TARBALL) | $(LOCAL_DIR)
	@echo "[VP] Building Boost $(BOOST_VERSION)..."
	$(ACTIVATE)
	rm -rf $(DOWNLOAD_DIR)/$(BOOST_USCORE)
	tar zxf $(BOOST_TARBALL) -C $(DOWNLOAD_DIR)
	cd $(DOWNLOAD_DIR)/$(BOOST_USCORE)
	./bootstrap.sh --prefix=$(BOOST_ROOT)
	./b2 install \
	  --with-atomic --with-chrono --with-date_time --with-filesystem \
	  --with-iostreams --with-log --with-program_options --with-regex \
	  --with-system --with-thread \
	  link=static threading=multi variant=release cxxstd=17 -j$(NPROC)

$(OPENSSL_SENTINEL): $(OPENSSL_TARBALL) | $(LOCAL_DIR)
	@echo "[VP] Building OpenSSL $(OPENSSL_VERSION)..."
	$(ACTIVATE)
	rm -rf $(DOWNLOAD_DIR)/openssl-$(OPENSSL_VERSION)
	tar zxf $(OPENSSL_TARBALL) -C $(DOWNLOAD_DIR)
	cd $(DOWNLOAD_DIR)/openssl-$(OPENSSL_VERSION)
	./Configure --prefix=$(OPENSSL_ROOT) --openssldir=$(OPENSSL_ROOT)/ssl no-shared linux-x86_64
	make -j$(NPROC)
	make install_sw

# CCI links against SystemC and Boost, so both must be built first.
$(CCI_SENTINEL): $(CCI_TARBALL) $(SYSTEMC_SENTINEL) $(BOOST_SENTINEL) | $(LOCAL_DIR)
	@echo "[VP] Building CCI $(CCI_VERSION)..."
	$(ACTIVATE)
	rm -rf $(DOWNLOAD_DIR)/cci_v$(CCI_VERSION)
	tar zxf $(CCI_TARBALL) -C $(DOWNLOAD_DIR)
	cd $(DOWNLOAD_DIR)/cci_v$(CCI_VERSION)
	export SYSTEMC_HOME=$(SYSTEMC_HOME)
	cmake -S . -B build \
	  -DCMAKE_CXX_STANDARD=$(CXX_STD) -DCMAKE_CXX_STANDARD_REQUIRED=ON \
	  -DCMAKE_BUILD_TYPE=Release \
	  -DCMAKE_INSTALL_PREFIX=$(CCI_HOME) -DCMAKE_INSTALL_LIBDIR=lib \
	  -DBOOST_ROOT=$(BOOST_ROOT) -DBoost_NO_SYSTEM_PATHS=ON \
	  -DSYSTEMCCCI_BUILD_TESTS=OFF -DBUILD_SHARED_LIBS=OFF
	cmake --build build -j$(NPROC)
	cmake --install build

# =============================================================================
# Source preparation (submodules)
#
# The CSML C++20 fixes (csml_report.h overloads, csml_reg_vector/2D flat storage)
# are now merged into the CSML submodule upstream, so no source patch is applied.
# =============================================================================
submodule-init:
	@echo "[VP] Initializing the tt-oca-sim submodule (recursive)..."
	git -C $(OCAH_ROOT) submodule update --init --recursive virtual_platform/tt-oca-sim

# =============================================================================
# VP configure + build (delegates to configure_vp.sh, deps passed via env)
# =============================================================================
# Configure runs once; the generated vp/build/Makefile is the sentinel.
$(VP_BUILD_DIR)/Makefile: $(SYSTEMC_SENTINEL) $(BOOST_SENTINEL) $(OPENSSL_SENTINEL) $(CCI_SENTINEL) | check-tt-oca-sim
	@echo "[VP] Preparing source (submodules)..."
	$(ACTIVATE)
	cd $(SIM_DIR)
	git submodule update --init --recursive
	echo "[VP] Configuring sep-vp via configure_vp.sh..."
	cd $(VP_SRC_DIR)
	SYSTEMC_HOME=$(SYSTEMC_HOME) CCI_HOME=$(CCI_HOME) \
	BOOST_ROOT=$(BOOST_ROOT) OPENSSL_ROOT=$(OPENSSL_ROOT) \
	CMAKE_BUILD_TYPE=Release CMAKE_CXX_STANDARD=$(CXX_STD) \
	  ./configure_vp.sh -- -DSEP_SCRATCH_COLD_STATUS_VALUES_PATH=$(STATUS_VALUES_PATH)

# Always delegate to the CMake-generated build (the authority on source/header
# dependencies). This is intentionally PHONY and NOT a file target keyed on the
# binary: if it were, an unchanged sep-vp binary would shadow CMake's finer-grained
# tracking, so a pulled tt-oca-sim source/header change (e.g. the boot-ROM LMA fix)
# would be silently skipped. The configure sentinel is an order-only prereq so
# configure still runs exactly once.
vp-build: | $(VP_BUILD_DIR)/Makefile
	@echo "[VP] Building sep-vp (incremental, via CMake)..."
	$(ACTIVATE)
	$(MAKE) -C $(VP_BUILD_DIR) -j$(NPROC) sep-vp
	@echo "[VP] Built: $(SEP_VP_BIN)"

# File-target alias so other targets can depend on the binary existing without
# forcing a rebuild themselves; the real build path is `vp` / `vp-build`.
$(SEP_VP_BIN): | vp-build

vp-clean:
	@echo "[VP] Clean reconfigure of vp/build..."
	rm -rf $(VP_BUILD_DIR)
	$(MAKE) vp

# =============================================================================
# Clean (build artifacts only; tt-oca-sim source is left intact)
# =============================================================================
clean:
	@echo "[VP] Removing downloads/, local/, and tt-oca-sim/vp/build..."
	rm -rf $(DOWNLOAD_DIR) $(LOCAL_DIR) $(VP_BUILD_DIR)
	echo "[VP] Clean complete (tt-oca-sim source untouched)."

# =============================================================================
# Environment script (run sep-vp outside the Make environment)
# =============================================================================
# `make env` (alias `make enable_vp`) writes setup_environment.sh; source it to
# get SYSTEMC_HOME/CCI_HOME/BOOST_ROOT/OPENSSL_ROOT, the C++ runtime, sep-vp on
# PATH, and the dep library paths. It lands at the same path the
# sw/sep-vp-tests run.sh scripts already source.
# Built with $(file >...) so $$ -> literal '$' in the generated script and
# $(...) make-vars are interpolated (no shell heredoc / $-escaping pitfalls).
define ENV_SCRIPT_BODY
#!/bin/bash
# Generated by virtual_platform/Makefile ('make env'). Do not edit by hand.
# Source this to run sep-vp outside the build environment:
#     source $(ENV_SCRIPT)
# Regenerate after a (re)build or when changing deps/toolset:  make env

# C++ runtime + toolchain used to build sep-vp (libstdc++, PATH).
if [ -f /opt/rh/$(GCC_TOOLSET)/enable ]; then
    source /opt/rh/$(GCC_TOOLSET)/enable
fi

# Dependency install prefixes.
export SYSTEMC_HOME="$(SYSTEMC_HOME)"
export CCI_HOME="$(CCI_HOME)"
export BOOST_ROOT="$(BOOST_ROOT)"
export OPENSSL_ROOT="$(OPENSSL_ROOT)"
export CMAKE_PREFIX_PATH="$$SYSTEMC_HOME:$$CCI_HOME:$$BOOST_ROOT:$$OPENSSL_ROOT$${CMAKE_PREFIX_PATH:+:$$CMAKE_PREFIX_PATH}"

# Runtime library search path. sep-vp loads libsystemc as a shared lib (resolved
# via RPATH too); Boost/CCI/OpenSSL are static, included here for robustness and
# for re-running cmake/configure_vp.sh against these prefixes.
export LD_LIBRARY_PATH="$(SYSTEMC_LIBDIR):$(CCI_LIBDIR):$(BOOST_LIBDIR):$(OPENSSL_LIBDIR)$${LD_LIBRARY_PATH:+:$$LD_LIBRARY_PATH}"

# Put sep-vp on PATH.
export PATH="$(VP_BUILD_DIR)/bin:$$PATH"

# RISC-V cross toolchain for building/running SEP firmware (added if present).
if [ -d "$(RISCV_TOOLCHAIN)/bin" ]; then
    export PATH="$(RISCV_TOOLCHAIN)/bin:$$PATH"
fi

echo "SEP VP environment ready:"
echo "  sep-vp      : $$(command -v sep-vp 2>/dev/null || echo '$(SEP_VP_BIN)')"
echo "  SYSTEMC_HOME: $$SYSTEMC_HOME"
endef

env enable_vp:
	@echo "[VP] Generating environment script: $(ENV_SCRIPT)"
	$(file >$(ENV_SCRIPT),$(ENV_SCRIPT_BODY))
	@if [ ! -x "$(SEP_VP_BIN)" ]; then \
	  echo "[VP] NOTE: $(SEP_VP_BIN) not built yet — run 'make vp' (paths in the script are still valid)." ; \
	fi
	@echo "[VP] Wrote $(ENV_SCRIPT). Use it with:"
	@echo "        source $(ENV_SCRIPT)"

# =============================================================================
# Guards
# =============================================================================
# A registered-but-uninitialized submodule dir exists but is empty, so test for
# a file inside it rather than the directory itself.
check-tt-oca-sim:
	@if [ ! -f "$(SIM_DIR)/vp/configure_vp.sh" ]; then
	  echo "[VP] ERROR: the tt-oca-sim submodule is not checked out at $(SIM_DIR)" >&2
	  echo "[VP] Initialize it with:  make ocah-vp-init   (from the repo root)" >&2
	  echo "[VP]   or:  git -C $(OCAH_ROOT) submodule update --init --recursive virtual_platform/tt-oca-sim" >&2
	  exit 1
	fi

# =============================================================================
# Optional smoke test (best-effort; not part of scratch-build/vp)
# =============================================================================
smoke: vp
	@echo "[VP] Smoke: build + run sw/sep-vp-tests/$(SW_TEST) in sep-vp"
	$(ACTIVATE)
	TESTDIR="$(SIM_DIR)/sw/sep-vp-tests/$(SW_TEST)"
	if [ ! -d "$$TESTDIR" ]; then
	  echo "[VP] WARNING: test '$(SW_TEST)' not found under sw/sep-vp-tests; skipping." >&2
	  exit 0
	fi
	# Make the RISC-V cross toolchain available for the firmware build.
	if [ -x "$(RISCV_TOOLCHAIN)/bin/riscv64-unknown-elf-gcc" ]; then
	  export PATH="$(RISCV_TOOLCHAIN)/bin:$$PATH"
	fi
	if ! command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then
	  echo "[VP] WARNING: riscv64-unknown-elf-gcc not found (set RISCV_TOOLCHAIN=...); skipping smoke." >&2
	  exit 0
	fi
	echo "[VP] Building test firmware ($(SW_TEST))..."
	$(MAKE) -C "$$TESTDIR"
	# The ELF name is the test Makefile's TARGET (e.g. sep-gpio-test -> sep_gpio_test).
	TARGET=$$(sed -n 's/^[[:space:]]*TARGET[[:space:]]*=[[:space:]]*//p' "$$TESTDIR/Makefile" | head -1)
	if [ -z "$$TARGET" ] || [ ! -f "$$TESTDIR/$$TARGET" ]; then
	  echo "[VP] WARNING: could not locate built ELF for $(SW_TEST); skipping run." >&2
	  exit 0
	fi
	LOG="$(VP_DIR)/smoke-$(SW_TEST).log"
	echo "[VP] Running $$TARGET in sep-vp for up to $(SMOKE_TIMEOUT)s (the VP does not self-terminate; timeout is expected)..."
	cd "$$TESTDIR"
	timeout -k 5 $(SMOKE_TIMEOUT) $(SEP_VP_BIN) $(VP_SRC_DIR)/platform/sep/config/accellera_config.ini "$$TARGET" 2>&1 | tee "$$LOG" || true
	echo "[VP] Smoke run finished (full output: $$LOG)."

# =============================================================================
# Firmware test harness (sepvp/ runner + tests/ pytest suite)
# =============================================================================
# Python deps for the harness, via the repo's uv-managed environment. --inexact
# so a previously synced dv group is not stripped from the venv.
vp-py-deps:
	@echo "[VP] Syncing harness Python deps (uv sync --inexact --group vp)..."
	cd $(OCAH_ROOT) && $(UV) sync --inexact --group vp

# Build the SEP boot ROM, OpenTitan SPI variant (-> build_ot/boot_rom.elf).
# The named ot-toolchain-images target owns the BUILD_DIR/flag mapping; it does
# NOT run pack-images (which needs uv + the tt-boot-manifest submodule — the
# ELF the VP boots does not).
boot-build:
	@echo "[VP] Building the SEP boot ROM, OpenTitan SPI variant..."
	$(FW_ENV)
	$(MAKE) -C $(BOOTCODE_DIR) ot-toolchain-images
	@echo "[VP] Built: $(BOOT_ELF)"

# Generate the signed SPI image used by the OT-negative pytest suite.
# Needs uv on PATH and the tt-boot-manifest submodule initialized
# (git submodule update --init hw/sys/sep/bootrom/prod/tools/tt-boot-manifest).
boot-secure-image:
	@echo "[VP] Generating the signed SPI image (secure_boot.spi_preload)..."
	$(FW_ENV)
	$(MAKE) -C $(BOOTCODE_DIR) secure_boot_spi
	@echo "[VP] Built: $(SECURE_BOOT_PRELOAD)"

# Build + run the boot ROM on sep-vp. Control via BOOT_ARGS, e.g.:
#   make boot-run BOOT_ARGS="--boot primary --until SEP_MSG_PRIMARY_CHIPLET"
#   make boot-run BOOT_ARGS="--boot secondary --timeout 30"
boot-run: boot-build $(SEP_VP_BIN)
	@echo "[VP] Running boot_rom.elf on sep-vp ($(BOOT_ARGS))..."
	cd $(VP_DIR) && $(PYTHON) -m sepvp.cli --bin $(BOOT_ELF) $(BOOT_ARGS)

# Build + run a SEP DV firmware test on sep-vp:  make fw-run FW_TEST=hello_world
# Tests live in hw/sys/sep/dv/fw/tests/ and are built by the shared DV firmware
# engine (default link mode tcm -> build/tests/<t>/<t>.tcm.elf).
fw-run: $(SEP_VP_BIN)
	@if [ -z "$(FW_TEST)" ]; then \
	  echo "[VP] ERROR: set FW_TEST=<name>, e.g. make fw-run FW_TEST=hello_world" >&2; exit 1; \
	fi
	$(FW_ENV)
	echo "[VP] Building hw/sys/sep/dv/fw/tests/$(FW_TEST)..."
	$(MAKE) -C $(OCAH_ROOT) ocah-dv-fw-tests TARGET=sep TEST=$(FW_TEST)
	echo "[VP] Running $(FW_TEST) on sep-vp ($(FW_ARGS))..."
	cd $(VP_DIR) && $(PYTHON) -m sepvp.cli --bin $(OCAH_ROOT)/hw/sys/sep/dv/fw/build/tests/$(FW_TEST)/$(FW_TEST).tcm.elf $(FW_ARGS)

# Run the pytest harness suite. Builds firmware by default (RISC-V toolchain on PATH);
# pass PYTEST_ARGS="--no-build -k bootcode" etc. to refine. Single invocation: all
# suites live under virtual_platform/tests (rootdir = virtual_platform).
vp-test: $(SEP_VP_BIN)
	@$(PYTHON) -c "import pexpect, yaml, pytest, toml, elftools" 2>/dev/null || $(MAKE) vp-py-deps
	$(FW_ENV)
	cd $(VP_DIR) && $(PYTHON) -m pytest tests $(PYTEST_ARGS)
