# =============================================================================
# SEP Virtual Platform build (CI-aligned)
#
# Mirrors tt-oca-harness-model/.github/workflows/ci-rhel8.yml: resolves or builds the
# SystemC, Boost, OpenSSL, and CCI dependencies (system installs are used when
# adequate; otherwise they are built from source into ./local), then
# configures the VP via tt-oca-harness-model/vp/configure_vp.sh and builds the sep-vp
# executable.
#
# Quick start:
#   make scratch-build   # clean rebuild of everything (deps + sep-vp)
#   make vp              # rebuild just sep-vp (deps assumed built; incremental)
#   make deps-info       # show where each dependency resolves and why
#   make clean           # wipe downloads/, local/, and tt-oca-harness-model/vp/build
#
# A C++20-capable compiler (g++ >= 10) must be on PATH (or set CXX=...);
# `make check-cxx` verifies it. Run "make help" for the full target/variable
# list. The repo-level entry points are the ocah-vp-* targets in vp.mk
# (included by ocah.mk).
# =============================================================================

SHELL       := /usr/bin/env
.SHELLFLAGS := bash -ec
.ONESHELL:
.DELETE_ON_ERROR:
.DEFAULT_GOAL := help

# ---- Execution environment (native vs container) ----------------------------
VP_DIR     := $(CURDIR)
OCAH_ROOT  := $(abspath $(VP_DIR)/..)
DOCKER_RUN := $(OCAH_ROOT)/scripts/docker-run.sh

# Container-built and host-built artifacts must never mix (different
# glibc/libstdc++ ABIs; CMake caches pin compiler paths), so every build tree
# is partitioned by an environment tag: empty natively (paths unchanged),
# "ctr" inside a container (auto-detected via the podman/docker markers or the
# OCAH_IN_CONTAINER env the bwrap backend sets; the VP_CONTAINER forwarding
# below also passes it explicitly).
VP_ENV_TAG ?= $(if $(or $(wildcard /run/.containerenv /.dockerenv),$(OCAH_IN_CONTAINER)),ctr,)
VP_TAG_SUFFIX := $(if $(VP_ENV_TAG),-$(VP_ENV_TAG),)

# VP_CONTAINER=1 (opt-in; native stays the default): run the requested goals
# inside the ocah-toolchain image via scripts/docker-run.sh vp-run — for
# hosts whose only capability is running containers. The container-built
# sep-vp links the container's glibc and must also RUN in the container, which
# this forwarding covers for vp-test/boot-run/fw-run/smoke too.
VP_CONTAINER ?=
ifeq ($(VP_CONTAINER),1)
  ifeq ($(VP_ENV_TAG),)
    VP_FORWARD := 1
  endif
endif

ifeq ($(VP_FORWARD),1)
# =============================================================================
# Container forwarding mode: everything below the else is replaced by a single
# rule that re-invokes make inside the container (1:1 repo bind; podman
# forwards no environment, so the relevant variables travel as command-line
# arguments).
# =============================================================================
_FWD_GOALS := $(or $(MAKECMDGOALS),help)
_FWD_FIRST := $(firstword $(_FWD_GOALS))
.PHONY: $(_FWD_GOALS)
$(_FWD_FIRST):
	@echo "[VP] VP_CONTAINER=1: running '$(_FWD_GOALS)' in the ocah-toolchain container..."
	"$(DOCKER_RUN)" vp-run make -C "$(VP_DIR)" $(_FWD_GOALS) \
	  VP_ENV_TAG=ctr VP_CONTAINER=0 PYTHON=/usr/bin/python3 \
	  $(if $(PYTEST_ARGS),PYTEST_ARGS="$(PYTEST_ARGS)") \
	  $(if $(BOOT_ARGS),BOOT_ARGS="$(BOOT_ARGS)") \
	  $(if $(FW_ARGS),FW_ARGS="$(FW_ARGS)") \
	  $(if $(FW_TEST),FW_TEST=$(FW_TEST)) \
	  $(if $(SW_TEST),SW_TEST=$(SW_TEST)) \
	  $(if $(NPROC),NPROC=$(NPROC))
$(filter-out $(_FWD_FIRST),$(_FWD_GOALS)):
	@:

else  # ---- native / in-container execution ----------------------------------

# ---- Overridable configuration ---------------------------------------------
# Compiler: whatever $(CXX) resolves to on PATH (make's default is g++).
# C++20 needs g++ >= 10; 11 through 14 are verified (a historic VeeR-ISS
# header-ordering failure under g++ 13/14 was fixed at the source in
# tt-oca-harness-model — Memory.hpp now includes <string>).
CXX_STD         ?= 20
SYSTEMC_VERSION ?= 3.0.2
BOOST_VERSION   ?= 1.84.0
OPENSSL_VERSION ?= 3.3.2
CCI_VERSION     ?= 1.0.2
NPROC           ?= $(shell nproc)
# SW_TEST: used by the optional `smoke` target
SW_TEST         ?= sep-gpio-test
# RISCV_TOOLCHAIN: optional RISC-V cross-toolchain prefix; its bin/ is
# prepended to PATH for the firmware builds when set. Leave unset when
# riscv64-unknown-elf-gcc is already on PATH — ROM/DV builds fall back to the
# ocah-toolchain container regardless (see fw_make below).
RISCV_TOOLCHAIN ?=
# SMOKE_TIMEOUT: seconds to let the VP run (it does not self-terminate)
SMOKE_TIMEOUT   ?= 20

# ---- Derived paths ----------------------------------------------------------
# LOCAL_DIR / VP_BUILD_DIR carry the environment tag (local-ctr, build-ctr in
# a container); DOWNLOAD_DIR is shared — tarballs are host-independent.
LOCAL_DIR    := $(VP_DIR)/local$(VP_TAG_SUFFIX)
DOWNLOAD_DIR := $(VP_DIR)/downloads
SIM_DIR      := $(VP_DIR)/tt-oca-harness-model
VP_SRC_DIR   := $(SIM_DIR)/vp
VP_BUILD_DIR := $(VP_SRC_DIR)/build$(VP_TAG_SUFFIX)
SEP_VP_BIN   := $(VP_BUILD_DIR)/bin/sep-vp

# ---- Firmware test harness (sepvp/ + tests/) --------------------------------
# Python from the repo's uv-managed venv (`make vp-py-deps` creates/populates it
# via `uv sync --inexact --group vp`).
UV            ?= uv
PYTHON        ?= $(OCAH_ROOT)/.venv/bin/python
BOOTCODE_DIR  := $(OCAH_ROOT)/hw/sys/sep/bootrom/prod
# SEP_MSG_* status-name table baked into sep-vp's sep_scratch_cold decoder. tt-oca-harness-model
# exposes this as a CMake cache variable (accepts TSV rows or a C header of #defines);
# without it the VP falls back to its vendored snapshot, which lags this repo's table
# and decodes newer codes as SEP_MSG_UNKNOWN. The checked-in bootrom header is the
# exact table the boot ROM compiles against, so decoder and firmware cannot drift.
# Changing this value triggers a clean reconfigure (see the config stamp below).
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
         if [ -n "$(RISCV_TOOLCHAIN)" ] && [ -d "$(RISCV_TOOLCHAIN)/bin" ]; then export PATH="$(RISCV_TOOLCHAIN)/bin:$$PATH"; fi

# ROM/DV-engine firmware builds need the RISC-V + picolibc toolchain from the
# ocah-toolchain container (tools/docker/README.md). Run natively when the
# toolchain on PATH can compile against picolibc; otherwise route through
# scripts/docker-run.sh run-here (set OCAH_TOOLCHAIN_ROOTFS to an extracted
# image rootfs for the engine-less bwrap path). The pack targets (uv) stay
# native — the container does not carry uv.
define fw_make
if echo 'int main(void){return 0;}' | riscv64-unknown-elf-gcc --specs=picolibc.specs -x c -c - -o /dev/null 2>/dev/null; then \
  $(MAKE) $(1); \
else \
  echo "[VP] native toolchain lacks picolibc; building via $(DOCKER_RUN) run-here"; \
  "$(DOCKER_RUN)" run-here make $(1); \
fi
endef

# ---- Dependency install prefixes ---------------------------------------------
# Resolution order for Boost/OpenSSL (SystemC/CCI: always ./local unless
# explicitly overridden — rarely system-installed):
#   1. explicit BOOST_ROOT/OPENSSL_ROOT (environment or command line; set the
#      variable EMPTY, e.g. `make vp BOOST_ROOT=`, to re-enable auto-resolution)
#   2. a complete, already-built ./local install (keeps the CCI<->Boost ODR
#      pairing and existing checkouts' behavior stable)
#   3. an adequate system install under /usr (only with VP_SYS_DEPS=auto)
#   4. otherwise: built from source into ./local by the recipes below.
VP_SYS_DEPS ?= auto
# Minimum acceptable system Boost, as BOOST_VERSION from boost/version.hpp
# (107400 = 1.74.0, the oldest C++20-clean Boost we accept; e.g. RHEL 8's 1.66
# fails: std::allocator::allocate(n, hint) was removed in C++20).
BOOST_MIN   ?= 107400

SYSTEMC_LOCAL := $(LOCAL_DIR)/systemc-$(SYSTEMC_VERSION)
BOOST_LOCAL   := $(LOCAL_DIR)/boost-$(BOOST_VERSION)
OPENSSL_LOCAL := $(LOCAL_DIR)/openssl-$(OPENSSL_VERSION)
CCI_LOCAL     := $(LOCAL_DIR)/cci-$(CCI_VERSION)

SYSTEMC_HOME ?= $(SYSTEMC_LOCAL)
CCI_HOME     ?= $(CCI_LOCAL)
SYSTEMC_WHY  := $(if $(filter $(SYSTEMC_HOME),$(SYSTEMC_LOCAL)),local (default),explicit ($(origin SYSTEMC_HOME)))
CCI_WHY      := $(if $(filter $(CCI_HOME),$(CCI_LOCAL)),local (default),explicit ($(origin CCI_HOME)))

# --- Boost ---
ifeq ($(strip $(BOOST_ROOT)),)
  # "Complete" local install = headers AND the static libs sep-vp links.
  ifneq ($(and $(wildcard $(BOOST_LOCAL)/include/boost/version.hpp),$(wildcard $(BOOST_LOCAL)/lib/libboost_program_options.a)),)
    override BOOST_ROOT := $(BOOST_LOCAL)
    BOOST_WHY := already built in local/
  else
    ifeq ($(VP_SYS_DEPS),auto)
      # Adequate system Boost = version floor met AND the compiled components
      # sep-vp needs (iostreams, program_options) actually link.
      BOOST_SYS_OK := $(shell \
        v=$$(sed -n 's/^\#define BOOST_VERSION \([0-9][0-9]*\)$$/\1/p' /usr/include/boost/version.hpp 2>/dev/null); \
        [ -n "$$v" ] && [ "$$v" -ge $(BOOST_MIN) ] \
        && echo 'int main(){return 0;}' | $(CXX) -x c++ - -lboost_iostreams -lboost_program_options -o /dev/null 2>/dev/null \
        && echo yes)
    endif
    ifeq ($(BOOST_SYS_OK),yes)
      override BOOST_ROOT := /usr
      BOOST_WHY := system install (BOOST_VERSION >= $(BOOST_MIN); iostreams+program_options linkable)
    else
      override BOOST_ROOT := $(BOOST_LOCAL)
      BOOST_WHY := will build from source $(if $(filter auto,$(VP_SYS_DEPS)),(no adequate system Boost),(VP_SYS_DEPS=$(VP_SYS_DEPS)))
    endif
  endif
else
  BOOST_WHY := explicit ($(origin BOOST_ROOT))
endif

# --- OpenSSL ---
ifeq ($(strip $(OPENSSL_ROOT)),)
  ifneq ($(and $(wildcard $(OPENSSL_LOCAL)/include/openssl/ssl.h),$(wildcard $(OPENSSL_LOCAL)/lib64/libssl.a)),)
    override OPENSSL_ROOT := $(OPENSSL_LOCAL)
    OPENSSL_WHY := already built in local/
  else
    ifeq ($(VP_SYS_DEPS),auto)
      # core_names.h is the actual >= 3.0 requirement (EVP_MAC API for the
      # hmac/kmac peripherals) — no version parsing needed. Dev headers imply
      # the dev libs on mainstream distros.
      OPENSSL_SYS_OK := $(if $(and $(wildcard /usr/include/openssl/ssl.h),$(wildcard /usr/include/openssl/core_names.h)),yes)
    endif
    ifeq ($(OPENSSL_SYS_OK),yes)
      override OPENSSL_ROOT := /usr
      OPENSSL_WHY := system install (OpenSSL >= 3.0: core_names.h present)
    else
      override OPENSSL_ROOT := $(OPENSSL_LOCAL)
      OPENSSL_WHY := will build from source $(if $(filter auto,$(VP_SYS_DEPS)),(system OpenSSL missing or < 3.0),(VP_SYS_DEPS=$(VP_SYS_DEPS)))
    endif
  endif
else
  OPENSSL_WHY := explicit ($(origin OPENSSL_ROOT))
endif

# Sentinels that mark a dependency as usable. Local installs use the
# last-installed artifact (robust against an interrupted install); explicit or
# system prefixes use the probe file their layout is guaranteed to have (their
# recipes must never fire — hence the order-only tarball prereqs below).
SYSTEMC_SENTINEL := $(SYSTEMC_HOME)/include/systemc.h
CCI_SENTINEL     := $(CCI_HOME)/lib/libcci.a
ifeq ($(BOOST_ROOT),$(BOOST_LOCAL))
  BOOST_SENTINEL := $(BOOST_ROOT)/lib/libboost_program_options.a
else
  BOOST_SENTINEL := $(BOOST_ROOT)/include/boost/version.hpp
endif
ifeq ($(OPENSSL_ROOT),$(OPENSSL_LOCAL))
  # The recipe pins the linux-x86_64 Configure target, whose libdir is lib64.
  OPENSSL_SENTINEL := $(OPENSSL_ROOT)/lib64/libssl.a
else
  OPENSSL_SENTINEL := $(OPENSSL_ROOT)/include/openssl/ssl.h
endif

define DEPS_INFO
echo "[VP] Dependency prefixes (VP_SYS_DEPS=$(VP_SYS_DEPS)):"
echo "[VP]   SYSTEMC_HOME = $(SYSTEMC_HOME)   [$(SYSTEMC_WHY)]"
echo "[VP]   CCI_HOME     = $(CCI_HOME)   [$(CCI_WHY)]"
echo "[VP]   BOOST_ROOT   = $(BOOST_ROOT)   [$(BOOST_WHY)]"
echo "[VP]   OPENSSL_ROOT = $(OPENSSL_ROOT)   [$(OPENSSL_WHY)]"
endef

# ---- Runtime env script (generated by `make env`) ---------------------------
# Resolve each dependency's library subdir robustly (lib-linux64 / lib64 / lib),
# falling back to the canonical default when the dep is not built yet. This is
# also where an overridden prefix gets its layout right.
ENV_SCRIPT      := $(VP_DIR)/setup_environment$(VP_TAG_SUFFIX).sh
SYSTEMC_LIBDIR  := $(or $(firstword $(wildcard $(SYSTEMC_HOME)/lib-linux64 $(SYSTEMC_HOME)/lib64 $(SYSTEMC_HOME)/lib)),$(SYSTEMC_HOME)/lib-linux64)
CCI_LIBDIR      := $(or $(firstword $(wildcard $(CCI_HOME)/lib $(CCI_HOME)/lib64 $(CCI_HOME)/lib-linux64)),$(CCI_HOME)/lib)
BOOST_LIBDIR    := $(or $(firstword $(wildcard $(BOOST_ROOT)/lib $(BOOST_ROOT)/lib64 $(BOOST_ROOT)/lib/x86_64-linux-gnu)),$(BOOST_ROOT)/lib)
OPENSSL_LIBDIR  := $(or $(firstword $(wildcard $(OPENSSL_ROOT)/lib64 $(OPENSSL_ROOT)/lib $(OPENSSL_ROOT)/lib/x86_64-linux-gnu)),$(OPENSSL_ROOT)/lib64)

# ---- Download artifacts -----------------------------------------------------
BOOST_USCORE    := boost_$(subst .,_,$(BOOST_VERSION))
SYSTEMC_TARBALL := $(DOWNLOAD_DIR)/systemc-$(SYSTEMC_VERSION).tar.gz
BOOST_TARBALL   := $(DOWNLOAD_DIR)/$(BOOST_USCORE).tar.gz
OPENSSL_TARBALL := $(DOWNLOAD_DIR)/openssl-$(OPENSSL_VERSION).tar.gz
CCI_TARBALL     := $(DOWNLOAD_DIR)/cci_v$(CCI_VERSION).tar.gz

# ---- Configure stamp ---------------------------------------------------------
# Reconfigure (with a clean build dir) whenever the dep prefixes, C++ standard,
# effective compiler, or the configure-baked status table change. Content-stamp
# pattern: the stamp is only rewritten when the signature differs, so its mtime
# is stable across no-op runs.
# Fingerprint by target+version (not the $(CXX) spelling) so `CXX=/path/to/g++`
# and an activated-PATH `g++` of the same compiler don't ping-pong reconfigures.
CXX_ID        := $(shell $(CXX) -dumpmachine 2>/dev/null)-$(shell $(CXX) -dumpversion 2>/dev/null)
VP_CONFIG_SIG := $(SYSTEMC_HOME)|$(CCI_HOME)|$(BOOST_ROOT)|$(OPENSSL_ROOT)|c++$(CXX_STD)|$(CXX_ID)|$(STATUS_VALUES_PATH)
DEP_STAMP     := $(VP_DIR)/.vp-config-stamp$(VP_TAG_SUFFIX)

.PHONY: help scratch-build download deps deps-info vp vp-clean clean env enable_vp \
        systemc boost openssl cci submodule-init check-tt-oca-harness-model check-cxx smoke \
        boot-build boot-secure-image boot-run fw-run vp-test vp-py-deps FORCE

# =============================================================================
# Help
# =============================================================================
help:
	@echo "SEP Virtual Platform build (mirrors tt-oca-harness-model CI)"
	@echo ""
	@echo "Primary targets:"
	@echo "  scratch-build  - clean, then build all deps and sep-vp from scratch"
	@echo "  vp             - build/rebuild sep-vp (incremental; deps assumed built)"
	@echo "  vp-clean       - wipe vp/build and reconfigure + rebuild sep-vp"
	@echo "  clean          - remove downloads/, local/, and tt-oca-harness-model/vp/build"
	@echo "  deps-info      - show where each dependency resolves and why"
	@echo "  check-cxx      - verify the compiler on PATH can build C++$(CXX_STD)"
	@echo "  env/enable_vp  - write setup_environment.sh to source for running sep-vp standalone"
	@echo ""
	@echo "Phase targets:"
	@echo "  download       - fetch the dependency source tarballs into downloads/"
	@echo "  deps           - resolve or build SystemC, Boost, OpenSSL, CCI"
	@echo "  systemc boost openssl cci - resolve/build a single dependency"
	@echo "  submodule-init - init the tt-oca-harness-model submodule (recursive)"
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
	@echo "  CXX=$(CXX)   CXX_STD=$(CXX_STD)   NPROC=$(NPROC)"
	@echo "  VP_CONTAINER=1 (build AND run in the ocah-toolchain container — no native"
	@echo "    toolchain needed; artifacts land in local-ctr/ and vp/build-ctr)"
	@echo "  VP_SYS_DEPS=$(VP_SYS_DEPS) (auto: use adequate system Boost/OpenSSL; 0: hermetic local builds)"
	@echo "  BOOST_MIN=$(BOOST_MIN) (minimum acceptable system BOOST_VERSION)"
	@echo "  SYSTEMC_VERSION=$(SYSTEMC_VERSION)  BOOST_VERSION=$(BOOST_VERSION)  OPENSSL_VERSION=$(OPENSSL_VERSION)  CCI_VERSION=$(CCI_VERSION)"
	@echo "  SYSTEMC_HOME / BOOST_ROOT / OPENSSL_ROOT / CCI_HOME  (point at an existing install;"
	@echo "    set one EMPTY, e.g. 'make vp BOOST_ROOT=', to re-enable auto-resolution)"
	@echo ""
	@echo "Examples:"
	@echo "  make scratch-build"
	@echo "  make vp"
	@echo "  make env && source setup_environment.sh   # then run sep-vp directly"
	@echo "  make deps BOOST_ROOT=/path/to/boost OPENSSL_ROOT=/path/to/openssl-3"

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
	@$(DEPS_INFO)

deps-info:
	@$(DEPS_INFO)

systemc: $(SYSTEMC_SENTINEL)
boost:   $(BOOST_SENTINEL)
openssl: $(OPENSSL_SENTINEL)
cci:     $(CCI_SENTINEL)

vp: vp-build

# =============================================================================
# Compiler capability check (order-only prereq of every compile step)
# =============================================================================
check-cxx:
	@if ! echo 'int main(){return 0;}' | $(CXX) -std=c++$(CXX_STD) -x c++ - -o /dev/null 2>/dev/null; then
	  echo "[VP] ERROR: '$(CXX)' cannot compile C++$(CXX_STD)." >&2
	  echo "[VP]   Effective compiler: $$(command -v $(CXX) 2>/dev/null || echo '<not found>') ($$($(CXX) --version 2>/dev/null | head -1))" >&2
	  echo "[VP]   Fix: install g++ >= 10 (e.g. apt install g++; on RHEL install a" >&2
	  echo "[VP]        gcc-toolset and activate it in your shell, e.g. 'scl enable gcc-toolset-12 bash')," >&2
	  echo "[VP]        or point CXX=/path/to/modern/g++." >&2
	  exit 1
	fi

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
#
# Sentinel prereqs are ORDER-ONLY: the sentinels have pure existence semantics
# (an explicit/system prefix must never look "out of date" against a freshly
# downloaded tarball and trigger an install into it). Each recipe also refuses
# to install outside ./local as defense in depth.
# =============================================================================
define REFUSE_NON_LOCAL
case "$(1)" in $(LOCAL_DIR)/*) ;; *) echo "[VP] refusing to build into non-local prefix $(1)" >&2; exit 1;; esac
endef

ifeq ($(SYSTEMC_HOME),$(SYSTEMC_LOCAL))
$(SYSTEMC_SENTINEL): | $(SYSTEMC_TARBALL) $(LOCAL_DIR) check-cxx
	@echo "[VP] Building SystemC $(SYSTEMC_VERSION)..."
	$(call REFUSE_NON_LOCAL,$(SYSTEMC_HOME))
	rm -rf $(DOWNLOAD_DIR)/systemc-$(SYSTEMC_VERSION)
	tar zxf $(SYSTEMC_TARBALL) -C $(DOWNLOAD_DIR)
	cd $(DOWNLOAD_DIR)/systemc-$(SYSTEMC_VERSION)
	touch docs/DEVELOPMENT.md
	mkdir -p objdir
	cd objdir
	../configure --prefix=$(SYSTEMC_HOME) CXXFLAGS="-std=c++$(CXX_STD)"
	make -j$(NPROC)
	make install
else
$(SYSTEMC_SENTINEL):
	@test -e "$@" 2>/dev/null || {\
		echo "[VP] ERROR: external SystemC at $(SYSTEMC_HOME) has no \`include/systemc.h\`" >&2; \
		exit 1; }
	@echo "[VP] Using External SystemC: $(SYSTEMC_HOME)"
endif

ifeq ($(BOOST_ROOT),$(BOOST_LOCAL))
$(BOOST_SENTINEL): | $(BOOST_TARBALL) $(LOCAL_DIR) check-cxx
	@echo "[VP] Building Boost $(BOOST_VERSION)..."
	$(call REFUSE_NON_LOCAL,$(BOOST_ROOT))
	rm -rf $(DOWNLOAD_DIR)/$(BOOST_USCORE)
	tar zxf $(BOOST_TARBALL) -C $(DOWNLOAD_DIR)
	cd $(DOWNLOAD_DIR)/$(BOOST_USCORE)
	./bootstrap.sh --prefix=$(BOOST_ROOT)
	./b2 install \
	  --with-atomic --with-chrono --with-date_time --with-filesystem \
	  --with-iostreams --with-log --with-program_options --with-regex \
	  --with-system --with-thread \
	  cxxflags=-fPIC cflags=-fPIC \
	  link=static threading=multi variant=release cxxstd=17 -j$(NPROC)
else
$(BOOST_SENTINEL):
	@test -e "$@" || {\
	    echo "[VP] ERROR: external Boost at $(BOOST_ROOT) has no \`include/boost/version.hpp\`" >&2; \
		exit 1; }
	@echo "[VP] Using External Boost: $(BOOST_ROOT)"
endif

ifeq ($(OPENSSL_ROOT),$(OPENSSL_LOCAL))
$(OPENSSL_SENTINEL): | $(OPENSSL_TARBALL) $(LOCAL_DIR) check-cxx
	@echo "[VP] Building OpenSSL $(OPENSSL_VERSION)..."
	$(call REFUSE_NON_LOCAL,$(OPENSSL_ROOT))
	rm -rf $(DOWNLOAD_DIR)/openssl-$(OPENSSL_VERSION)
	tar zxf $(OPENSSL_TARBALL) -C $(DOWNLOAD_DIR)
	cd $(DOWNLOAD_DIR)/openssl-$(OPENSSL_VERSION)
	./Configure --prefix=$(OPENSSL_ROOT) --openssldir=$(OPENSSL_ROOT)/ssl no-shared linux-x86_64
	make -j$(NPROC)
	make install_sw
else
$(OPENSSL_SENTINEL):
	@test -e "$@" || {\
	    echo "[VP] ERROR: external OpenSSL at $(OPENSSL_ROOT) has no \`include/openssl/ssl.h\`" >&2; \
		exit 1; }
	@echo "[VP] Using External OpenSSL: $(OPENSSL_ROOT)"
endif

ifeq ($(CCI_HOME),$(CCI_LOCAL))
# CCI links against SystemC and Boost, so both must be resolved first (order-only:
# their timestamps are irrelevant, their existence is the contract).
$(CCI_SENTINEL): | $(CCI_TARBALL) $(SYSTEMC_SENTINEL) $(BOOST_SENTINEL) $(LOCAL_DIR) check-cxx
	@echo "[VP] Building CCI $(CCI_VERSION)..."
	$(call REFUSE_NON_LOCAL,$(CCI_HOME))
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
else
$(CCI_SENTINEL): $(SYSTEMC_SENTINEL) $(BOOST_SENTINEL)
	@test -e "$@" || {\
	    echo "[VP] ERROR: external CCI at $(CCI_HOME) has no \`lib/libcci.a\`" >&2; \
		exit 1; }
	@echo "[VP] Using External CCI: $(CCI_HOME)"
endif

# =============================================================================
# Source preparation (submodules)
#
# The CSML C++20 fixes (csml_report.h overloads, csml_reg_vector/2D flat storage)
# are now merged into the CSML submodule upstream, so no source patch is applied.
# =============================================================================
submodule-init:
	@echo "[VP] Initializing the tt-oca-harness-model submodule (recursive)..."
	git -C $(OCAH_ROOT) submodule update --init --recursive virtual_platform/tt-oca-harness-model

# =============================================================================
# VP configure + build (delegates to configure_vp.sh, deps passed via env)
# =============================================================================
FORCE:

$(DEP_STAMP): FORCE
	@if [ "$$(cat '$@' 2>/dev/null)" != '$(VP_CONFIG_SIG)' ]; then
	  if [ ! -e '$@' ] && [ -f '$(VP_BUILD_DIR)/Makefile' ]; then
	    # Migration: adopt a build configured before this stamp existed
	    # (assumed consistent) without retriggering a reconfigure.
	    printf '%s' '$(VP_CONFIG_SIG)' > '$@'
	    touch -r '$(VP_BUILD_DIR)/Makefile' '$@'
	  else
	    printf '%s' '$(VP_CONFIG_SIG)' > '$@'
	  fi
	fi

# Configure runs once per configuration; the generated vp/build/Makefile is the
# sentinel, and the config stamp forces a CLEAN reconfigure when the dep
# prefixes / compiler / status table change (a stale CMakeCache pinning old
# paths is worse than a rebuild).
$(VP_BUILD_DIR)/Makefile: $(DEP_STAMP) $(SYSTEMC_SENTINEL) $(BOOST_SENTINEL) $(OPENSSL_SENTINEL) $(CCI_SENTINEL) | check-tt-oca-harness-model check-cxx
	@echo "[VP] Preparing source (submodules)..."
	if [ -f "$(VP_BUILD_DIR)/CMakeCache.txt" ]; then
	  echo "[VP] Build configuration changed — wiping $(VP_BUILD_DIR) for a clean reconfigure."
	  rm -rf "$(VP_BUILD_DIR)"
	fi
	cd $(SIM_DIR)
	git submodule update --init --recursive
	echo "[VP] Configuring sep-vp via configure_vp.sh..."
	$(DEPS_INFO)
	cd $(VP_SRC_DIR)
	SYSTEMC_HOME=$(SYSTEMC_HOME) CCI_HOME=$(CCI_HOME) \
	BOOST_ROOT=$(BOOST_ROOT) OPENSSL_ROOT=$(OPENSSL_ROOT) \
	VP_BOOST_MIN=$(BOOST_MIN) BUILD_DIR=$(VP_BUILD_DIR) \
	CMAKE_BUILD_TYPE=Release CMAKE_CXX_STANDARD=$(CXX_STD) \
	  ./configure_vp.sh -- -DSEP_SCRATCH_COLD_STATUS_VALUES_PATH=$(STATUS_VALUES_PATH)

# Always delegate to the CMake-generated build (the authority on source/header
# dependencies). This is intentionally PHONY and NOT a file target keyed on the
# binary: if it were, an unchanged sep-vp binary would shadow CMake's finer-grained
# tracking, so a pulled tt-oca-harness-model source/header change (e.g. the boot-ROM LMA fix)
# would be silently skipped. The configure sentinel is an order-only prereq so
# configure still runs exactly once.
vp-build: | $(VP_BUILD_DIR)/Makefile check-cxx
	@echo "[VP] Building sep-vp (incremental, via CMake)..."
	$(MAKE) -C $(VP_BUILD_DIR) -j$(NPROC) sep-vp
	echo "[VP] Built: $(SEP_VP_BIN)"

# File-target alias so other targets can depend on the binary existing without
# forcing a rebuild themselves; the real build path is `vp` / `vp-build`.
$(SEP_VP_BIN): | vp-build

vp-clean:
	@echo "[VP] Clean reconfigure of vp/build..."
	rm -rf $(VP_BUILD_DIR)
	$(MAKE) vp

# =============================================================================
# Clean (build artifacts only; tt-oca-harness-model source is left intact)
# =============================================================================
clean:
	@echo "[VP] Removing downloads/, local/, and tt-oca-harness-model/vp/build..."
	rm -rf $(DOWNLOAD_DIR) $(LOCAL_DIR) $(VP_BUILD_DIR) $(DEP_STAMP)
	echo "[VP] Clean complete (tt-oca-harness-model source untouched)."

# =============================================================================
# Environment script (run sep-vp outside the Make environment)
# =============================================================================
# `make env` (alias `make enable_vp`) writes setup_environment.sh; source it to
# get SYSTEMC_HOME/CCI_HOME/BOOST_ROOT/OPENSSL_ROOT, sep-vp on PATH, and the
# dep library paths. It lands at the same path the sw/sep-vp-tests run.sh
# scripts already source.
# Built with $(file >...) so $$ -> literal '$' in the generated script and
# $(...) make-vars are interpolated (no shell heredoc / $-escaping pitfalls).
define ENV_SCRIPT_BODY
#!/usr/bin/env bash
# Generated by virtual_platform/Makefile ('make env'). Do not edit by hand.
# Source this to run sep-vp outside the build environment:
#     source $(ENV_SCRIPT)
# Regenerate after a (re)build or when changing deps:  make env
#
# NOTE: activate the C++ toolchain sep-vp was built with (if its runtime is
# newer than the system one) before sourcing this script.

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

# RISC-V cross toolchain for building/running SEP firmware (added if set).
if [ -n "$(RISCV_TOOLCHAIN)" ] && [ -d "$(RISCV_TOOLCHAIN)/bin" ]; then
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
check-tt-oca-harness-model:
	@if [ ! -f "$(SIM_DIR)/vp/configure_vp.sh" ]; then
	  echo "[VP] ERROR: the tt-oca-harness-model submodule is not checked out at $(SIM_DIR)" >&2
	  echo "[VP] Initialize it with:  make ocah-vp-init   (from the repo root)" >&2
	  echo "[VP]   or:  git -C $(OCAH_ROOT) submodule update --init --recursive virtual_platform/tt-oca-harness-model" >&2
	  exit 1
	fi

# =============================================================================
# Optional smoke test (best-effort; not part of scratch-build/vp)
# =============================================================================
smoke: vp
	@echo "[VP] Smoke: build + run sw/sep-vp-tests/$(SW_TEST) in sep-vp"
	TESTDIR="$(SIM_DIR)/sw/sep-vp-tests/$(SW_TEST)"
	if [ ! -d "$$TESTDIR" ]; then
	  echo "[VP] WARNING: test '$(SW_TEST)' not found under sw/sep-vp-tests; skipping." >&2
	  exit 0
	fi
	# Make the RISC-V cross toolchain available for the firmware build.
	if [ -n "$(RISCV_TOOLCHAIN)" ] && [ -x "$(RISCV_TOOLCHAIN)/bin/riscv64-unknown-elf-gcc" ]; then
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
	$(call fw_make,-C $(BOOTCODE_DIR) ot-toolchain-images)
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
	export SEP_VP_BIN="$(SEP_VP_BIN)"
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
	$(call fw_make,-C $(OCAH_ROOT) ocah-dv-fw-tests TARGET=sep TEST=$(FW_TEST))
	echo "[VP] Running $(FW_TEST) on sep-vp ($(FW_ARGS))..."
	export SEP_VP_BIN="$(SEP_VP_BIN)"
	cd $(VP_DIR) && $(PYTHON) -m sepvp.cli --bin $(OCAH_ROOT)/hw/sys/sep/dv/fw/build/tests/$(FW_TEST)/$(FW_TEST).tcm.elf $(FW_ARGS)

# Run the pytest harness suite. Builds firmware by default (RISC-V toolchain on PATH);
# pass PYTEST_ARGS="--no-build -k bootcode" etc. to refine. Single invocation: all
# suites live under virtual_platform/tests (rootdir = virtual_platform).
vp-test: $(SEP_VP_BIN)
	@$(PYTHON) -c "import pexpect, yaml, pytest, toml, elftools" 2>/dev/null || $(MAKE) vp-py-deps
	$(FW_ENV)
	export SEP_VP_BIN="$(SEP_VP_BIN)"
	cd $(VP_DIR) && $(PYTHON) -m pytest tests $(PYTEST_ARGS)

endif  # VP_FORWARD
