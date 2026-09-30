# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# =============================================================================
# OCAH Virtual Platform build
#
# Resolves or builds the SystemC, Boost, OpenSSL and CCI dependencies (system
# installs where adequate, otherwise from source into ./local), then configures
# and builds the VP executables via tt-oca-harness-model/vp/configure_vp.sh.
# The dependency recipes follow the model's own
# .github/workflows/ci-rhel8.yml.
#
# Three executables, all available here:
#   sep-vp  the SEP subsystem          -> vp/build       ('make vp')
#   smc-vp  the SMC subsystem          -> vp/build_smc   ('make smc-vp')
#   smu-vp  SMC + SEP, one process     -> vp/build_smc   ('make smu-vp')
#
# smc-vp and smu-vp are opt-in: both need the Whisper ISS, built here as a
# managed dependency, and both live in a second build tree (see
# SMC_BUILD_DIR). 'make vp' neither downloads nor builds Whisper.
#
# A C++20-capable compiler (g++ >= 10) must be on PATH, or set CXX=...;
# 'make check-cxx' verifies it. 'make help' lists the targets, README.md the
# variables. The repo-level entry points are the ocah-vp-* targets in vp.mk.
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

# The ROM's elf-to-vmem needs pyelftools, which only the uv-bundled image carries;
# the bare image points uv at the host .venv and strips the vp group from it.
export OCAH_IMAGE_WITH_UV ?= true

# Container-built and host-built artifacts must never mix: they carry
# different glibc/libstdc++ ABIs, and CMake caches pin compiler paths. Every
# build tree is therefore partitioned by an environment tag - empty natively,
# "ctr" in a container, detected from the podman/docker markers or the
# OCAH_IN_CONTAINER the bwrap backend sets.
VP_ENV_TAG ?= $(if $(or $(wildcard /run/.containerenv /.dockerenv),$(OCAH_IN_CONTAINER)),ctr,)
VP_TAG_SUFFIX := $(if $(VP_ENV_TAG),-$(VP_ENV_TAG),)

# VP_CONTAINER=1 runs the requested goals inside the ocah-toolchain image via
# scripts/docker-run.sh run-here, for hosts with no usable native toolchain. A
# container-built VP links the container's glibc and must also RUN there, so
# the forwarding covers the run targets (vp-test, boot-run, fw-run, smoke) as
# well as the builds.
VP_CONTAINER ?=
ifeq ($(VP_CONTAINER),1)
  ifeq ($(VP_ENV_TAG),)
    VP_FORWARD := 1
  endif
endif

ifeq ($(VP_FORWARD),1)
# =============================================================================
# Container forwarding mode: one rule that re-invokes make inside the
# container, replacing everything below the else. podman forwards no
# environment, so every relevant variable travels as a command-line argument.
# =============================================================================
_FWD_GOALS := $(or $(MAKECMDGOALS),help)
_FWD_FIRST := $(firstword $(_FWD_GOALS))
.PHONY: $(_FWD_GOALS)
$(_FWD_FIRST):
	@echo "[VP] VP_CONTAINER=1: running '$(_FWD_GOALS)' in the OCAH container..."
	"$(DOCKER_RUN)" run-here make -C "$(VP_DIR)" $(_FWD_GOALS) \
	  VP_ENV_TAG=ctr VP_CONTAINER=0 \
	  $(if $(PYTEST_ARGS),PYTEST_ARGS="$(PYTEST_ARGS)") \
	  $(if $(BOOT_ARGS),BOOT_ARGS="$(BOOT_ARGS)") \
	  $(if $(FW_ARGS),FW_ARGS="$(FW_ARGS)") \
	  $(if $(FW_TEST),FW_TEST=$(FW_TEST)) \
	  $(if $(SW_TEST),SW_TEST=$(SW_TEST)) \
	  $(if $(WHISPER_HOME),WHISPER_HOME="$(WHISPER_HOME)") \
	  $(if $(WHISPER_REV),WHISPER_REV=$(WHISPER_REV)) \
	  $(if $(SMC_ARGS),SMC_ARGS="$(SMC_ARGS)") \
	  $(if $(SMU_ARGS),SMU_ARGS="$(SMU_ARGS)") \
	  $(if $(SMC_INI),SMC_INI="$(SMC_INI)") \
	  $(if $(SEP_INI),SEP_INI="$(SEP_INI)") \
	  $(if $(SIM_TIME_MS),SIM_TIME_MS=$(SIM_TIME_MS)) \
	  $(if $(RISCV_PREFIX),RISCV_PREFIX=$(RISCV_PREFIX)) \
	  $(if $(NPROC),NPROC=$(NPROC))
$(filter-out $(_FWD_FIRST),$(_FWD_GOALS)):
	@:

else  # ---- native / in-container execution ----------------------------------

# ---- Overridable configuration ---------------------------------------------
# Compiler: whatever $(CXX) resolves to on PATH. C++20 needs g++ >= 10; 11
# through 14 are verified.
CXX_STD         ?= 20
SYSTEMC_VERSION ?= 3.0.2
BOOST_VERSION   ?= 1.84.0
OPENSSL_VERSION ?= 3.3.2
CCI_VERSION     ?= 1.0.2
# Whisper ISS revision for smc-vp/smu-vp. Read from the model's own CI workflow
# rather than pinned here: that file records the commit its SMC VP was validated
# against, so a submodule uprev carries the new revision with it and the two
# cannot drift. Empty when the submodule is not checked out, which the whisper
# target below reports rather than building an unpinned tree.
# Deferred: SIM_DIR is derived further down.
WHISPER_REV_SOURCE = $(SIM_DIR)/.github/workflows/ci-rhel8.yml
WHISPER_REV     ?= $(shell sed -n 's/^[[:space:]]*WHISPER_REV:[[:space:]]*"\{0,1\}\([0-9a-f]\{7,\}\)"\{0,1\}.*/\1/p' $(WHISPER_REV_SOURCE) 2>/dev/null)
NPROC           ?= $(shell nproc)
# SW_TEST: used by the optional `smoke` target
SW_TEST         ?= sep-gpio-test
# RISCV_TOOLCHAIN: optional RISC-V cross-toolchain prefix; its bin/ is
# prepended to PATH for the firmware builds when set. Leave unset when
# riscv64-unknown-elf-gcc is already on PATH — ROM/DV builds fall back to the
# ocah-toolchain container regardless (see fw_make below).
RISCV_TOOLCHAIN ?=
# RISCV_PREFIX: optional cross-toolchain prefix for the SMC/SMU firmware
# suites. Left empty, the model's runners auto-detect, and both find the
# ocah-toolchain image's riscv64-unknown-elf- (which is first in
# run_smc_vp_tests.sh's candidate list and run_smu_vp_tests.sh's fallback).
RISCV_PREFIX    ?=
# SMOKE_TIMEOUT: seconds to let the VP run (it does not self-terminate)
SMOKE_TIMEOUT   ?= 20
# Pass-through args and knobs for the SMC/SMU firmware suites (see smc-test /
# smu-test below): `make smc-test SMC_ARGS=smc-uart-test`, and the SMU
# runner's own ini/sim-window overrides.
SMC_ARGS        ?=
SMU_ARGS        ?=
SMC_INI         ?=
SEP_INI         ?=
SIM_TIME_MS     ?=

# ---- Derived paths ----------------------------------------------------------
# LOCAL_DIR / VP_BUILD_DIR carry the environment tag (local-ctr, build-ctr in
# a container); DOWNLOAD_DIR is shared, since tarballs are host-independent.
# Being shared, the trees extracted into it must stay removable from either
# environment - hence --no-same-owner on every `tar` below.
LOCAL_DIR    := $(VP_DIR)/local$(VP_TAG_SUFFIX)
DOWNLOAD_DIR := $(VP_DIR)/downloads
SIM_DIR      := $(VP_DIR)/tt-oca-harness-model
VP_SRC_DIR   := $(SIM_DIR)/vp
VP_BUILD_DIR := $(VP_SRC_DIR)/build$(VP_TAG_SUFFIX)
SEP_VP_BIN   := $(VP_BUILD_DIR)/bin/sep-vp
# smc-vp and smu-vp share ONE tree, separate from the SEP one. WHISPER_HOME is
# read at configure time and decides whether the smc/smu targets are generated
# at all (vp/platform/CMakeLists.txt), so no single tree can serve both the
# Whisper-less SEP build and these; both platforms hang off that one switch, so
# they always come together. The shared SEP peripheral tree is compiled twice
# as a result.
SMC_BUILD_DIR := $(VP_SRC_DIR)/build_smc$(VP_TAG_SUFFIX)
SMC_VP_BIN    := $(SMC_BUILD_DIR)/bin/smc-vp
SMU_VP_BIN    := $(SMC_BUILD_DIR)/bin/smu-vp
# smu-vp repackages the SMC CPU cluster as a shared library so Whisper's
# WdRiscv symbols stay local to it and the SEP side can statically link its own
# VeeR-ISS fork (vp/platform/smu/CMakeLists.txt). CMake builds it beside the
# target, NOT in bin/, so anything that copies, uploads or caches smu-vp must
# carry it too.
SMU_CLUSTER_LIB := $(SMC_BUILD_DIR)/platform/smu/libsmc_cluster_smu.so

# ---- Firmware test harness (sepvp/ + tests/) --------------------------------
# Python from the repo's uv-managed venv (`make vp-py-deps` creates/populates it
# via `uv sync --inexact --group vp`).
UV            ?= uv
PYTHON        ?= $(OCAH_ROOT)/.venv/bin/python
# Interpreter for the harness itself. uv resolves the vp group from the repo
# root, so this works against the repo venv, the container's own UV environment
# or a bare checkout without assuming where the interpreter lives -- PYTHON
# above stays a plain path because FW_ENV puts its directory on PATH for the
# bootrom's OTBN codegen, which calls a bare python3.
# --project, not --directory: --directory would chdir to the repo root, and the
# harness targets below run from virtual_platform/ so pytest finds tests/.
VP_PYTHON     ?= $(UV) --project "$(OCAH_ROOT)" run --group vp --locked python3
BOOTCODE_DIR  := $(OCAH_ROOT)/hw/sys/sep/bootrom/prod
# SEP_MSG_* status-name table baked into sep-vp's sep_scratch_cold decoder;
# tt-oca-harness-model takes it as a CMake cache variable (TSV rows or a C
# header of #defines). Without it the VP falls back to a vendored snapshot that
# lags this repo's table and decodes newer codes as SEP_MSG_UNKNOWN. The
# checked-in bootrom header is the table the boot ROM itself compiles against.
# Changing this value triggers a clean reconfigure (see the config stamp below).
STATUS_VALUES_PATH ?= $(BOOTCODE_DIR)/include/status_values.h
# The SEP VP models the OpenTitan SPI host only: the Cadence xSPI controller is
# closed-source IP, absent from the open SEP and not modeled. VP boot therefore
# always builds the OpenTitan controller variant (the bootrom's
# ot-toolchain-images target -> build_ot/), never the default Cadence build.
BOOT_OT_BUILD_DIR := build_ot
BOOT_ELF          := $(BOOTCODE_DIR)/$(BOOT_OT_BUILD_DIR)/boot_rom.elf
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
#      pairing intact)
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

# --- Whisper (smc-vp / smu-vp only; never resolved or built for sep-vp) ---
# One Whisper, built -fPIC, serves both targets: smu-vp's cluster DSO requires
# PIC, and PIC archives link into smc-vp's executable just as well. The -pic
# suffix is part of the prefix name so a non-PIC variant stays expressible
# without two indistinguishable trees at one path.
WHISPER_LOCAL := $(LOCAL_DIR)/whisper-$(WHISPER_REV)-pic
WHISPER_HOME  ?= $(WHISPER_LOCAL)
WHISPER_WHY   := $(if $(filter $(WHISPER_HOME),$(WHISPER_LOCAL)),local (default),explicit ($(origin WHISPER_HOME)))
# Whisper's GNUmakefile names its build dir after `uname -s`; the model's
# import shim resolves the same value from CMAKE_HOST_SYSTEM_NAME.
WHISPER_BUILD_SUBDIR := build-$(shell uname -s)
# Four archives, not one: smc/cpu_cluster/external/whisper-cmake imports
# librvcore.a plus the softfloat/pci/virtual_memory sub-libs, and Whisper's
# makefile wires those three as prerequisites of its `whisper` executable only.
# Asking for librvcore.a alone silently skips them, and the configure step then
# fails with "Whisper artifact not found".
WHISPER_ARCHIVES := \
  $(WHISPER_HOME)/$(WHISPER_BUILD_SUBDIR)/librvcore.a \
  $(WHISPER_HOME)/virtual_memory/libvirtual_memory.a \
  $(WHISPER_HOME)/pci/libpci.a \
  $(WHISPER_HOME)/third_party/softfloat/build/RISCV-GCC/softfloat.a

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
# Whisper is the one dependency whose usability cannot be represented by a
# single file: all four archives must be present, and a restored cache is no
# proof of that. For our own tree the sentinel is therefore a stamp written
# only AFTER all four verify. It lives outside WHISPER_HOME so an external
# prefix is never written to; for that case the sentinel is librvcore.a and the
# recipe only verifies and reports.
ifeq ($(WHISPER_HOME),$(WHISPER_LOCAL))
  WHISPER_SENTINEL := $(LOCAL_DIR)/.whisper-$(WHISPER_REV)-pic-complete
else
  WHISPER_SENTINEL := $(firstword $(WHISPER_ARCHIVES))
endif

# Verify all four archives; on failure name the missing ones and say what to
# do, rather than leaving it to a cmake backtrace much later.
define WHISPER_VERIFY
missing=
for lib in $(WHISPER_ARCHIVES); do
  [ -f "$$lib" ] || missing="$$missing $$lib"
done
if [ -n "$$missing" ]; then
  echo "[VP] ERROR: Whisper tree at $(WHISPER_HOME) is missing archives:" >&2
  for lib in $$missing; do echo "[VP]   $$lib" >&2; done
  echo "[VP]   Whisper resolution: $(WHISPER_WHY)" >&2
  if [ "$(WHISPER_HOME)" = "$(WHISPER_LOCAL)" ]; then
    echo "[VP]   Fix: make whisper   (builds it into local$(VP_TAG_SUFFIX)/)" >&2
  else
    echo "[VP]   Fix: build the four archives in that tree with" >&2
    echo "[VP]        MEM_CALLBACKS=1 CXX_STD=c++$(CXX_STD) EXTRA_CXXFLAGS=-fPIC," >&2
    echo "[VP]        or unset WHISPER_HOME to use our own managed build." >&2
  fi
  exit 1
fi
endef

define DEPS_INFO
echo "[VP] Dependency prefixes (VP_SYS_DEPS=$(VP_SYS_DEPS)):"
echo "[VP]   SYSTEMC_HOME = $(SYSTEMC_HOME)   [$(SYSTEMC_WHY)]"
echo "[VP]   CCI_HOME     = $(CCI_HOME)   [$(CCI_WHY)]"
echo "[VP]   BOOST_ROOT   = $(BOOST_ROOT)   [$(BOOST_WHY)]"
echo "[VP]   OPENSSL_ROOT = $(OPENSSL_ROOT)   [$(OPENSSL_WHY)]"
echo "[VP]   WHISPER_HOME = $(WHISPER_HOME)   [$(WHISPER_WHY); smc-vp/smu-vp only, $(if $(wildcard $(firstword $(WHISPER_ARCHIVES))),built,not built)]"
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
# Fingerprint the status table's CONTENTS, not just its path. The path alone
# never changes, so adding a SEP_MSG_* code left the configure-baked decoder
# stale and the new code decoded as SEP_MSG_UNKNOWN -- which is precisely the
# "configure-baked status table change" this signature says it covers.
STATUS_VALUES_SIG := $(shell cksum '$(STATUS_VALUES_PATH)' 2>/dev/null | cut -d' ' -f1)
VP_CONFIG_SIG := $(SYSTEMC_HOME)|$(CCI_HOME)|$(BOOST_ROOT)|$(OPENSSL_ROOT)|c++$(CXX_STD)|$(CXX_ID)|$(STATUS_VALUES_PATH)@$(STATUS_VALUES_SIG)
DEP_STAMP     := $(VP_DIR)/.vp-config-stamp$(VP_TAG_SUFFIX)
# The SMC/SMU tree needs its own stamp: a different signature (Whisper, plus
# the BOOST_DIR the SMC cluster requires) and a different build dir, so one
# shared stamp would make each tree's reconfigure wipe the other's. The name
# keeps the .vp-config-stamp* gitignore pattern.
# WHISPER_HOME is part of the signature because it decides the generated TARGET
# SET, not just a link path: setting Whisper up after a first build has to
# reconfigure, or the stale cache has no smc/smu targets and make reports only
# "No rule to make target".
SMC_CONFIG_SIG := $(VP_CONFIG_SIG)|$(WHISPER_HOME)|pic
SMC_DEP_STAMP  := $(VP_DIR)/.vp-config-stamp-smc$(VP_TAG_SUFFIX)

.PHONY: scratch-build scratch-build-smc download deps deps-info vp vp-clean clean env enable_vp \
        systemc boost openssl cci whisper submodule-init check-tt-oca-harness-model check-cxx smoke \
        smc-vp smu-vp smc-test smu-test smc-clean \
        boot-build boot-run fw-run vp-test vp-test-host vp-py-deps FORCE

# =============================================================================
# Help
#
# Generated from the ## docblocks on the targets below by the repo-wide flow in
# help.mk; README.md documents the variables.
# =============================================================================
HELP_TITLE       = "OCAH Virtual Platform"
HELP_DESCRIPTION = "Build and run sep-vp, smc-vp and smu-vp, and the SEP firmware test harness"
include $(OCAH_ROOT)/help.mk

# =============================================================================
# Aggregate phases
# =============================================================================
## @section Virtual platform (sep-vp)

## Clean, then build every dependency and sep-vp from scratch.
scratch-build:
	@echo "[VP] === Scratch build: clean -> deps -> vp ==="
	$(MAKE) clean
	$(MAKE) deps
	$(MAKE) vp
	$(MAKE) env
	echo "[VP] === Scratch build complete: $(SEP_VP_BIN) ==="
	echo "[VP]     Run sep-vp standalone with:  source $(ENV_SCRIPT)"

## Build/rebuild sep-vp (incremental; dependencies assumed built).
vp: vp-build

## Wipe vp/build, then reconfigure and rebuild sep-vp.
vp-clean:
	@echo "[VP] Clean reconfigure of vp/build..."
	rm -rf $(VP_BUILD_DIR)
	$(MAKE) vp

# =============================================================================
# Dependency, toolchain and source phases
# =============================================================================
## @section Dependencies, toolchain and sources

## Fetch the dependency source tarballs into downloads/.
download: $(SYSTEMC_TARBALL) $(BOOST_TARBALL) $(OPENSSL_TARBALL) $(CCI_TARBALL)

## Resolve or build SystemC, Boost, OpenSSL and CCI.
deps: $(SYSTEMC_SENTINEL) $(BOOST_SENTINEL) $(OPENSSL_SENTINEL) $(CCI_SENTINEL)
	@$(DEPS_INFO)

## Report where each dependency resolves to and why.
deps-info:
	@$(DEPS_INFO)

## Resolve or build SystemC alone.
systemc: $(SYSTEMC_SENTINEL)
## Resolve or build Boost alone.
boost:   $(BOOST_SENTINEL)
## Resolve or build OpenSSL alone.
openssl: $(OPENSSL_SENTINEL)
## Resolve or build CCI alone.
cci:     $(CCI_SENTINEL)
## Resolve or build the Whisper ISS alone (smc-vp/smu-vp only).
whisper: check-whisper-rev $(WHISPER_SENTINEL)

# WHISPER_REV comes from the model's CI workflow, so an uninitialised submodule
# yields an empty revision and a whisper-*-pic prefix that pins nothing.
.PHONY: check-whisper-rev
check-whisper-rev:
	@[ -n "$(WHISPER_REV)" ] || { \
	  echo "error: WHISPER_REV is empty; no revision found in $(WHISPER_REV_SOURCE)." >&2; \
	  echo "       Initialise the submodule first: make submodule-init" >&2; \
	  exit 1; }

# =============================================================================
# Compiler capability check (order-only prereq of every compile step)
# =============================================================================
## Print one variable's resolved value, for scripts that would otherwise parse
## this file: `make -s print-WHISPER_REV`. Resolved, so a value computed at
## expansion time reads the same here as it does in a build.
print-%:
	@echo "$($*)"

## Verify the compiler on PATH can build the C++ standard the VP requires.
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
# Dependency builds (commands follow ci-rhel8.yml Job 1)
#
# Sentinel prereqs are ORDER-ONLY: the sentinels carry pure existence
# semantics, and an explicit or system prefix must never look "out of date"
# against a freshly downloaded tarball and trigger an install into it. Each
# recipe also refuses to install outside ./local.
#
# Every extraction passes --no-same-owner: in a container make runs as root,
# and root-run tar restores the uid recorded in the archive. CCI's release
# records uid 1000, which rootless podman maps into the caller's subuid range,
# leaving a tree in the SHARED downloads/ that the host user cannot re-extract:
#   rm: cannot remove '.../downloads/cci_v1.0.2/NOTICE': Permission denied
# It is already tar's default for non-root, so native extraction is unaffected.
# =============================================================================
define REFUSE_NON_LOCAL
case "$(1)" in $(LOCAL_DIR)/*) ;; *) echo "[VP] refusing to build into non-local prefix $(1)" >&2; exit 1;; esac
endef

ifeq ($(SYSTEMC_HOME),$(SYSTEMC_LOCAL))
$(SYSTEMC_SENTINEL): | $(SYSTEMC_TARBALL) $(LOCAL_DIR) check-cxx
	@echo "[VP] Building SystemC $(SYSTEMC_VERSION)..."
	$(call REFUSE_NON_LOCAL,$(SYSTEMC_HOME))
	rm -rf $(DOWNLOAD_DIR)/systemc-$(SYSTEMC_VERSION)
	tar --no-same-owner -zxf $(SYSTEMC_TARBALL) -C $(DOWNLOAD_DIR)
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
	echo "[VP] Using External SystemC: $(SYSTEMC_HOME)"
endif

ifeq ($(BOOST_ROOT),$(BOOST_LOCAL))
$(BOOST_SENTINEL): | $(BOOST_TARBALL) $(LOCAL_DIR) check-cxx
	@echo "[VP] Building Boost $(BOOST_VERSION)..."
	$(call REFUSE_NON_LOCAL,$(BOOST_ROOT))
	rm -rf $(DOWNLOAD_DIR)/$(BOOST_USCORE)
	tar --no-same-owner -zxf $(BOOST_TARBALL) -C $(DOWNLOAD_DIR)
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
	echo "[VP] Using External Boost: $(BOOST_ROOT)"
endif

ifeq ($(OPENSSL_ROOT),$(OPENSSL_LOCAL))
$(OPENSSL_SENTINEL): | $(OPENSSL_TARBALL) $(LOCAL_DIR) check-cxx
	@echo "[VP] Building OpenSSL $(OPENSSL_VERSION)..."
	$(call REFUSE_NON_LOCAL,$(OPENSSL_ROOT))
	rm -rf $(DOWNLOAD_DIR)/openssl-$(OPENSSL_VERSION)
	tar --no-same-owner -zxf $(OPENSSL_TARBALL) -C $(DOWNLOAD_DIR)
	cd $(DOWNLOAD_DIR)/openssl-$(OPENSSL_VERSION)
	./Configure --prefix=$(OPENSSL_ROOT) --openssldir=$(OPENSSL_ROOT)/ssl no-shared linux-x86_64
	make -j$(NPROC)
	make install_sw
else
$(OPENSSL_SENTINEL):
	@test -e "$@" || {\
	    echo "[VP] ERROR: external OpenSSL at $(OPENSSL_ROOT) has no \`include/openssl/ssl.h\`" >&2; \
		exit 1; }
	echo "[VP] Using External OpenSSL: $(OPENSSL_ROOT)"
endif

ifeq ($(CCI_HOME),$(CCI_LOCAL))
# CCI links against SystemC and Boost, so both must be resolved first (order-only:
# their timestamps are irrelevant, their existence is the contract).
$(CCI_SENTINEL): | $(CCI_TARBALL) $(SYSTEMC_SENTINEL) $(BOOST_SENTINEL) $(LOCAL_DIR) check-cxx
	@echo "[VP] Building CCI $(CCI_VERSION)..."
	$(call REFUSE_NON_LOCAL,$(CCI_HOME))
	rm -rf $(DOWNLOAD_DIR)/cci_v$(CCI_VERSION)
	tar --no-same-owner -zxf $(CCI_TARBALL) -C $(DOWNLOAD_DIR)
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
	echo "[VP] Using External CCI: $(CCI_HOME)"
endif

# ---- Whisper ISS (smc-vp / smu-vp) -----------------------------------------
# Cloned rather than downloaded: DOWNLOAD_DIR holds release tarballs only.
ifeq ($(WHISPER_HOME),$(WHISPER_LOCAL))
# Boost must be resolved first: Whisper's makefile compiles against its
# headers (order-only -- existence is the contract, not timestamps).
$(WHISPER_SENTINEL): | $(BOOST_SENTINEL) $(LOCAL_DIR) check-cxx
	@echo "[VP] Building Whisper $(WHISPER_REV) (PIC, four archives)..."
	$(call REFUSE_NON_LOCAL,$(WHISPER_HOME))
	# This recipe also runs when a previous attempt left a tree with only some
	# archives built, so reuse an existing checkout rather than failing on
	# "destination path already exists". No fetch is needed: the path pins
	# WHISPER_REV, so an existing checkout is already at that revision.
	if [ -d "$(WHISPER_HOME)/.git" ]; then
	  echo "[VP] Reusing the existing Whisper checkout; building missing archives."
	else
	  rm -rf "$(WHISPER_HOME)"
	  git clone --quiet https://github.com/tenstorrent/whisper.git "$(WHISPER_HOME)"
	  git -C "$(WHISPER_HOME)" checkout --quiet $(WHISPER_REV)
	fi
	# Headers-only Boost root: Whisper's makefile -isystems the whole prefix,
	# which shadows libc headers whenever that prefix is /usr.
	rm -rf "$(LOCAL_DIR)/whisper-boost-headers"
	mkdir -p "$(LOCAL_DIR)/whisper-boost-headers/include"
	ln -s "$(BOOST_ROOT)/include/boost" "$(LOCAL_DIR)/whisper-boost-headers/include/boost"
	# One aggregate goal, expressed in Whisper's OWN variables: the three
	# sub-libs cannot be named as relative goals, because its makefile defines
	# them by absolute path - one of them with a double slash
	# ($$PWD/virtual_memory//libvirtual_memory.a).
	printf 'smc_vp_whisper_libs: $$(BUILD_DIR)/librvcore.a $$(soft_float_lib) $$(pci_lib) $$(virtual_memory_lib)\n' \
	  > "$(LOCAL_DIR)/whisper-smc-libs.mk"
	# `make`, not $(MAKE): our command-line overrides would reach a sub-make
	# through MAKEFLAGS/MAKEOVERRIDES, and Whisper reuses two of those names
	# with different meanings - CXX_STD is "c++20" there but "20" here, and
	# BOOST_ROOT must be the headers-only shim above, not a prefix a developer
	# passed us. Clearing them keeps the two namespaces apart.
	env -u MAKEFLAGS -u MAKEOVERRIDES -u MFLAGS -u MAKELEVEL \
	  make -C "$(WHISPER_HOME)" -f GNUmakefile -f "$(LOCAL_DIR)/whisper-smc-libs.mk" \
	  MEM_CALLBACKS=1 CXX_STD=c++$(CXX_STD) EXTRA_CXXFLAGS=-fPIC \
	  BOOST_ROOT="$(LOCAL_DIR)/whisper-boost-headers" \
	  smc_vp_whisper_libs -j$(NPROC)
	$(WHISPER_VERIFY)
	printf '%s' '$(WHISPER_REV)' > "$@"
	echo "[VP] Built Whisper: $(WHISPER_HOME)"
else
$(WHISPER_SENTINEL):
	@$(WHISPER_VERIFY)
	echo "[VP] Using External Whisper: $(WHISPER_HOME)"
endif

# =============================================================================
# Source preparation (submodules)
# =============================================================================
## Initialize the tt-oca-harness-model submodule, recursively.
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
	    # A configured tree with no stamp is adopted as-is rather than
	    # reconfigured; its signature is assumed to match.
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
	# WHISPER_HOME is forced EMPTY, not merely left unset: vp/platform's gate
	# is `if(DEFINED ENV{WHISPER_HOME} AND NOT "..." STREQUAL "")`, so an
	# exported WHISPER_HOME in the developer's shell would otherwise add the smc
	# and smu platforms to this SEP-only tree. Empty keeps it SEP-only always.
	SYSTEMC_HOME=$(SYSTEMC_HOME) CCI_HOME=$(CCI_HOME) \
	BOOST_ROOT=$(BOOST_ROOT) OPENSSL_ROOT=$(OPENSSL_ROOT) \
	WHISPER_HOME= \
	VP_BOOST_MIN=$(BOOST_MIN) BUILD_DIR=$(VP_BUILD_DIR) \
	CMAKE_BUILD_TYPE=Release CMAKE_CXX_STANDARD=$(CXX_STD) \
	  ./configure_vp.sh -- -DSEP_SCRATCH_COLD_STATUS_VALUES_PATH=$(STATUS_VALUES_PATH)

# PHONY, not a file target keyed on the binary: CMake owns the source/header
# dependency graph, and an unchanged sep-vp binary would shadow its
# finer-grained tracking, so a pulled tt-oca-harness-model change would be
# silently skipped. The configure sentinel is an order-only prereq so configure
# still runs exactly once.
vp-build: | $(VP_BUILD_DIR)/Makefile check-cxx
	@echo "[VP] Building sep-vp (incremental, via CMake)..."
	$(MAKE) -C $(VP_BUILD_DIR) -j$(NPROC) sep-vp
	echo "[VP] Built: $(SEP_VP_BIN)"

# File-target alias so other targets can depend on the binary existing without
# forcing a rebuild themselves; the real build path is `vp` / `vp-build`.
$(SEP_VP_BIN): | vp-build

# =============================================================================
# SMC / SMU configure + build (opt-in; the Whisper-enabled tree)
# =============================================================================
## @section SMC / SMU (opt-in; these build the Whisper ISS first)

# This environment must be present for the BUILD steps too, not just the
# configure: WHISPER_HOME decides whether the smc/smu targets are generated at
# all, and CMake re-runs its own configure during a build whenever any
# CMakeLists.txt changes - a model uprev, or an edit to any of the SEP/SMC
# peripherals this tree pulls in. That re-configure inherits the build step's
# environment, and without these the targets vanish mid-build:
#     make[1]: *** No rule to make target 'smc-vp'.  Stop.
# BOOST_DIR is here for the same reason (smc/cpu_cluster requires it).
SMC_CMAKE_ENV = \
  SYSTEMC_HOME=$(SYSTEMC_HOME) CCI_HOME=$(CCI_HOME) \
  BOOST_ROOT=$(BOOST_ROOT) BOOST_DIR=$(BOOST_ROOT) OPENSSL_ROOT=$(OPENSSL_ROOT) \
  WHISPER_HOME=$(WHISPER_HOME)

# Build one target in the SMC/SMU tree. A tree reconfigured without
# WHISPER_HOME simply has no such target, and make reports only "No rule to
# make target 'smc-vp'", which reads like a typo here rather than a stale build
# tree - so name the real cause and the fix.
define SMC_BUILD_TARGET
if ! $(SMC_CMAKE_ENV) $(MAKE) -C $(SMC_BUILD_DIR) -j$(NPROC) $(1); then
  if ! $(SMC_CMAKE_ENV) $(MAKE) -C $(SMC_BUILD_DIR) help 2>/dev/null | grep -qx "\.\.\. $(1)"; then
    echo "[VP] ERROR: $(SMC_BUILD_DIR) has no '$(1)' target." >&2
    echo "[VP]   Its CMake cache was regenerated without WHISPER_HOME, so the" >&2
    echo "[VP]   smc and smu platforms were skipped (vp/platform/CMakeLists.txt)." >&2
    echo "[VP]   Fix: make smc-clean   (wipes the tree and reconfigures)" >&2
  fi
  exit 1
fi
endef
$(SMC_DEP_STAMP): FORCE
	@if [ "$$(cat '$@' 2>/dev/null)" != '$(SMC_CONFIG_SIG)' ]; then
	  printf '%s' '$(SMC_CONFIG_SIG)' > '$@'
	fi

# Same contract as the SEP configure above, plus three settings:
#   WHISPER_HOME     -- read at CONFIGURE time; what makes the smc and smu
#                       targets exist at all (vp/platform/CMakeLists.txt).
#   BOOST_DIR        -- smc/cpu_cluster/CMakeLists.txt requires it, and
#                       configure_vp.sh sets only BOOST_ROOT/Boost_ROOT, so
#                       without it the configure dies at the SMC cluster even
#                       with every other prefix correct.
#   SMC_CXX_STANDARD -- the cluster's own standard knob.
$(SMC_BUILD_DIR)/Makefile: $(SMC_DEP_STAMP) $(SYSTEMC_SENTINEL) $(BOOST_SENTINEL) $(OPENSSL_SENTINEL) $(CCI_SENTINEL) $(WHISPER_SENTINEL) | check-tt-oca-harness-model check-cxx
	@echo "[VP] Preparing source (submodules)..."
	if [ -f "$(SMC_BUILD_DIR)/CMakeCache.txt" ]; then
	  echo "[VP] Build configuration changed — wiping $(SMC_BUILD_DIR) for a clean reconfigure."
	  rm -rf "$(SMC_BUILD_DIR)"
	fi
	# A sentinel that exists is not proof the tree is usable, so re-check all
	# four archives here as well: an interrupted build or a restored cache can
	# leave the stamp beside an incomplete tree.
	$(WHISPER_VERIFY)
	cd $(SIM_DIR)
	git submodule update --init --recursive
	echo "[VP] Configuring smc-vp/smu-vp via configure_vp.sh..."
	$(DEPS_INFO)
	cd $(VP_SRC_DIR)
	$(SMC_CMAKE_ENV) \
	VP_BOOST_MIN=$(BOOST_MIN) BUILD_DIR=$(SMC_BUILD_DIR) \
	CMAKE_BUILD_TYPE=Release CMAKE_CXX_STANDARD=$(CXX_STD) \
	  ./configure_vp.sh -- -DSMC_CXX_STANDARD=$(CXX_STD) -DBOOST_DIR=$(BOOST_ROOT) \
	                       -DSEP_SCRATCH_COLD_STATUS_VALUES_PATH=$(STATUS_VALUES_PATH)
	# The gate is silent when it declines, so assert rather than trust: a tree
	# without these targets fails much later with "No rule to make target".
	for t in smc-vp smu-vp; do
	  if ! $(SMC_CMAKE_ENV) $(MAKE) -C $(SMC_BUILD_DIR) help 2>/dev/null | grep -qx "\.\.\. $$t"; then
	    echo "[VP] ERROR: configure produced no '$$t' target in $(SMC_BUILD_DIR)." >&2
	    echo "[VP]   WHISPER_HOME=$(WHISPER_HOME) was not accepted by vp/platform/CMakeLists.txt." >&2
	    exit 1
	  fi
	done

## Clean, then build every dependency, Whisper, smc-vp and smu-vp.
scratch-build-smc:
	@echo "[VP] === Scratch build (SMC/SMU): clean -> deps -> whisper -> smc-vp + smu-vp ==="
	$(MAKE) clean
	$(MAKE) deps
	$(MAKE) whisper
	$(MAKE) smc-vp
	$(MAKE) smu-vp
	$(MAKE) env
	echo "[VP] === Scratch build complete: $(SMC_VP_BIN)"
	echo "[VP]                             $(SMU_VP_BIN)"
	echo "[VP]                             $(SMU_CLUSTER_LIB)"

# PHONY for the same reason vp-build is: CMake owns the source/header
# dependency graph, and keying on the binary would shadow its finer-grained
# tracking.
## Build/rebuild smc-vp into vp/build_smc (incremental).
smc-vp: | $(SMC_BUILD_DIR)/Makefile check-cxx
	@echo "[VP] Building smc-vp (incremental, via CMake)..."
	$(call SMC_BUILD_TARGET,smc-vp)
	echo "[VP] Built: $(SMC_VP_BIN)"

# Two artifacts: the executable and the cluster DSO it loads at run time. They
# must travel together (see SMU_CLUSTER_LIB above).
## Build/rebuild smu-vp and its companion libsmc_cluster_smu.so (same tree).
smu-vp: | $(SMC_BUILD_DIR)/Makefile check-cxx
	@echo "[VP] Building smu-vp + libsmc_cluster_smu.so (incremental, via CMake)..."
	$(call SMC_BUILD_TARGET,smu-vp)
	echo "[VP] Built: $(SMU_VP_BIN)"
	echo "[VP]        $(SMU_CLUSTER_LIB)   (companion; copy/upload it alongside)"

# File-target aliases, matching $(SEP_VP_BIN)'s role.
$(SMC_VP_BIN): | smc-vp
$(SMU_VP_BIN) $(SMU_CLUSTER_LIB): | smu-vp

## Wipe vp/build_smc, then reconfigure and rebuild smc-vp and smu-vp.
smc-clean:
	@echo "[VP] Clean reconfigure of vp/build_smc..."
	rm -rf $(SMC_BUILD_DIR)
	$(MAKE) smc-vp smu-vp

# =============================================================================
# Clean (build artifacts only; tt-oca-harness-model source is left intact)
# =============================================================================
## @section Cleaning and environment

## Remove downloads/, local/ and both vp/build trees.
clean:
	@echo "[VP] Removing downloads/, local/, and tt-oca-harness-model/vp/build{,_smc}..."
	rm -rf $(DOWNLOAD_DIR) $(LOCAL_DIR) $(VP_BUILD_DIR) $(SMC_BUILD_DIR) \
	       $(DEP_STAMP) $(SMC_DEP_STAMP)
	echo "[VP] Clean complete (tt-oca-harness-model source untouched)."

# =============================================================================
# Environment script (run sep-vp outside the Make environment)
# =============================================================================
# The script lands at the path the model's sw/sep-vp-tests run.sh scripts
# already source. Written with $(file >...) so $$ becomes a literal '$' and
# $(...) make variables are interpolated, without shell heredoc escaping.
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

# Runtime library search path. sep-vp loads libsystemc as a shared lib;
# Boost/CCI/OpenSSL are static and listed for re-running
# cmake/configure_vp.sh against these prefixes. The last entry is smu-vp's
# companion libsmc_cluster_smu.so: smu-vp's RUNPATH is an absolute path into
# the build tree, so this entry is what keeps a moved or copied smu-vp working.
export LD_LIBRARY_PATH="$(SYSTEMC_LIBDIR):$(CCI_LIBDIR):$(BOOST_LIBDIR):$(OPENSSL_LIBDIR):$(dir $(SMU_CLUSTER_LIB))$${LD_LIBRARY_PATH:+:$$LD_LIBRARY_PATH}"

# Put sep-vp on PATH, and smc-vp/smu-vp too when their tree has been built.
export PATH="$(VP_BUILD_DIR)/bin:$$PATH"
if [ -d "$(SMC_BUILD_DIR)/bin" ]; then
    export PATH="$(SMC_BUILD_DIR)/bin:$$PATH"
fi
# WHISPER_HOME is exported for re-running configure_vp.sh against the SMC/SMU
# tree. With it set, a configure of the SEP tree would also pull in the smc and
# smu platforms, which is why `make vp` forces it empty.
export WHISPER_HOME="$(WHISPER_HOME)"

# RISC-V cross toolchain for building/running SEP firmware (added if set).
if [ -n "$(RISCV_TOOLCHAIN)" ] && [ -d "$(RISCV_TOOLCHAIN)/bin" ]; then
    export PATH="$(RISCV_TOOLCHAIN)/bin:$$PATH"
fi

echo "OCAH VP environment ready:"
echo "  sep-vp      : $$(command -v sep-vp 2>/dev/null || echo '$(SEP_VP_BIN)')"
echo "  smc-vp      : $$(command -v smc-vp 2>/dev/null || echo '(not built; make smc-vp)')"
echo "  smu-vp      : $$(command -v smu-vp 2>/dev/null || echo '(not built; make smu-vp)')"
echo "  SYSTEMC_HOME: $$SYSTEMC_HOME"
endef

## Write setup_environment.sh: source it to run a built VP standalone.
env:
	@echo "[VP] Generating environment script: $(ENV_SCRIPT)"
	$(file >$(ENV_SCRIPT),$(ENV_SCRIPT_BODY))
	if [ ! -x "$(SEP_VP_BIN)" ]; then \
	  echo "[VP] NOTE: $(SEP_VP_BIN) not built yet — run 'make vp' (paths in the script are still valid)." ; \
	fi
	echo "[VP] Wrote $(ENV_SCRIPT). Use it with:"
	echo "        source $(ENV_SCRIPT)"

## Alias for env.
enable_vp: env

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
## @section SEP firmware test harness

## Build and run one sw/sep-vp-tests test in sep-vp; skips if it cannot.
## @param SW_TEST=sep-gpio-test Which test to build and run
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
# --inexact so a previously synced dv group is not stripped from the venv.
## Sync the harness Python dependencies into the repo's uv venv.
vp-py-deps:
	@echo "[VP] Syncing harness Python deps (uv sync --inexact --group vp)..."
	cd $(OCAH_ROOT) && $(UV) sync --inexact --group vp

# The bootrom's named ot-toolchain-images target owns the BUILD_DIR/flag
# mapping; it does NOT run oca-images (which needs uv + the tt-oca-manifest
# submodule — the ELF the VP boots does not).
#
# It is not wrapped in fw_make. The bootrom runs key-digests on the host and
# dispatches only the compile into the toolchain sandbox itself, and a sandbox
# has no engine to dispatch to again. The bootrom builds natively only when
# RISCV_TOOLCHAIN names a bin dir, so a picolibc toolchain found on PATH is
# passed that way; otherwise RISCV_TOOLCHAIN is cleared so that a prefix given
# to this Makefile does not reach the bootrom, which reads it as a bin dir.
## Build the SEP boot ROM, OpenTitan SPI variant (-> build_ot/boot_rom.elf).
boot-build:
	@echo "[VP] Building the SEP boot ROM, OpenTitan SPI variant..."
	$(FW_ENV)
	if echo 'int main(void){return 0;}' | riscv64-unknown-elf-gcc --specs=picolibc.specs -x c -c - -o /dev/null 2>/dev/null; then \
	  $(MAKE) -C $(BOOTCODE_DIR) ot-toolchain-images RISCV_TOOLCHAIN="$$(dirname "$$(command -v riscv64-unknown-elf-gcc)")"; \
	else \
	  $(MAKE) -C $(BOOTCODE_DIR) ot-toolchain-images RISCV_TOOLCHAIN=; \
	fi
	echo "[VP] Built: $(BOOT_ELF)"

# Build + run the boot ROM on sep-vp. Control via BOOT_ARGS, e.g.:
#   make boot-run BOOT_ARGS="--boot primary --until SEP_MSG_PRIMARY_CHIPLET"
#   make boot-run BOOT_ARGS="--boot secondary --timeout 30"
## Build the boot ROM and run it on sep-vp; BOOT_ARGS reaches the sepvp CLI.
boot-run: boot-build $(SEP_VP_BIN)
	@echo "[VP] Running boot_rom.elf on sep-vp ($(BOOT_ARGS))..."
	export SEP_VP_BIN="$(SEP_VP_BIN)"
	cd $(VP_DIR) && $(VP_PYTHON) -m sepvp.cli --bin $(BOOT_ELF) $(BOOT_ARGS)

# Tests live in hw/sys/sep/dv/fw/tests/ and are built by the shared DV firmware
# engine (default link mode tcm -> build/tests/<t>/<t>.tcm.elf).
## Build a hw/sys/sep/dv/fw test and run it on sep-vp; FW_ARGS reaches the CLI.
## @param FW_TEST=hello_world Which DV firmware test to build and run
fw-run: $(SEP_VP_BIN)
	@if [ -z "$(FW_TEST)" ]; then \
	  echo "[VP] ERROR: set FW_TEST=<name>, e.g. make fw-run FW_TEST=hello_world" >&2; exit 1; \
	fi
	$(FW_ENV)
	echo "[VP] Building hw/sys/sep/dv/fw/tests/$(FW_TEST)..."
	$(call fw_make,-C $(OCAH_ROOT) ocah-dv-fw-tests TARGET=sep TEST=$(FW_TEST))
	echo "[VP] Running $(FW_TEST) on sep-vp ($(FW_ARGS))..."
	export SEP_VP_BIN="$(SEP_VP_BIN)"
	cd $(VP_DIR) && $(VP_PYTHON) -m sepvp.cli --bin $(OCAH_ROOT)/hw/sys/sep/dv/fw/build/tests/$(FW_TEST)/$(FW_TEST).tcm.elf $(FW_ARGS)

# One invocation: every suite lives under virtual_platform/tests, whose rootdir
# is virtual_platform.
## Run the pytest harness suite; builds firmware unless told not to.
## @param PYTEST_ARGS=--no-build Extra pytest arguments, e.g. "--no-build -k bootcode"
vp-test: $(SEP_VP_BIN)
	@$(VP_PYTHON) -c "import pexpect, yaml, pytest, toml, elftools" 2>/dev/null || $(MAKE) vp-py-deps
	$(FW_ENV)
	export SEP_VP_BIN="$(SEP_VP_BIN)"
	cd $(VP_DIR) && $(VP_PYTHON) -m pytest tests $(PYTEST_ARGS)

# No $(SEP_VP_BIN) prerequisite and no firmware: the hostonly marker covers the
# suites that only read checked-in data, so this runs on a bare checkout.
## Run only the suites needing no sep-vp binary, firmware or RISC-V toolchain.
vp-test-host:
	@$(VP_PYTHON) -c "import pexpect, yaml, pytest, toml" 2>/dev/null || $(MAKE) vp-py-deps
	cd $(VP_DIR) && $(VP_PYTHON) -m pytest tests -m hostonly $(PYTEST_ARGS)

# =============================================================================
# SMC / SMU firmware suites
#
# Thin wrappers around the model's own sw/{smc,smu}-vp-tests runners; the sepvp
# package drives the SEP VP only.
#
# VP and VP_BUILD_DIR are always passed explicitly, or the runners configure a
# tree of their own: run_smc_vp_tests.sh's find_vp_binary() probes
# vp/build/bin/smc-vp -- the SEP tree -- before it looks at VP_BUILD_DIR.
# =============================================================================
## @section SMC / SMU firmware suites

# Shared environment for both runners. RISCV_TOOLCHAIN is our knob; the runners
# take RISCV_TOOLCHAIN_PATH, a base dir containing bin/<prefix>gcc.
# RISCV_PREFIX is passed only when set: unset, both runners auto-detect and
# find the image's riscv64-unknown-elf-.
define SMC_TEST_ENV
export SYSTEMC_HOME="$(SYSTEMC_HOME)" CCI_HOME="$(CCI_HOME)" WHISPER_HOME="$(WHISPER_HOME)"
export BOOST_DIR="$(BOOST_ROOT)" BOOST_ROOT="$(BOOST_ROOT)"
export OPENSSL_ROOT="$(OPENSSL_ROOT)" OPENSSL_ROOT_DIR="$(OPENSSL_ROOT)"
if [ -n "$(RISCV_TOOLCHAIN)" ] && [ -d "$(RISCV_TOOLCHAIN)/bin" ]; then
  export RISCV_TOOLCHAIN_PATH="$(RISCV_TOOLCHAIN)"
fi
if [ -n "$(RISCV_PREFIX)" ]; then export RISCV_PREFIX="$(RISCV_PREFIX)"; fi
endef

## Run the model's SMC firmware suite on smc-vp.
## @param SMC_ARGS=smc-uart-test One test instead of the whole suite
smc-test: $(SMC_VP_BIN)
	@echo "[VP] Running the SMC VP firmware suite ($(if $(SMC_ARGS),$(SMC_ARGS),all tests))..."
	$(SMC_TEST_ENV)
	export VP="$(SMC_VP_BIN)" VP_BUILD_DIR="$(SMC_BUILD_DIR)"
	cd $(SIM_DIR)/sw/smc-vp-tests && ./run_smc_vp_tests.sh $(SMC_ARGS)

# A test passes only when BOTH the SMC and SEP halves print PASS.
## Run the model's SMU firmware suite on smu-vp (both subsystems at once).
## @param SMU_ARGS=smu-link-test One test instead of the whole suite
smu-test: $(SMU_VP_BIN)
	@echo "[VP] Running the SMU VP firmware suite ($(if $(SMU_ARGS),$(SMU_ARGS),all tests))..."
	$(SMC_TEST_ENV)
	export VP="$(SMU_VP_BIN)"
	if [ -n "$(SMC_INI)" ]; then export SMC_INI="$(SMC_INI)"; fi
	if [ -n "$(SEP_INI)" ]; then export SEP_INI="$(SEP_INI)"; fi
	if [ -n "$(SIM_TIME_MS)" ]; then export SIM_TIME_MS="$(SIM_TIME_MS)"; fi
	cd $(SIM_DIR)/sw/smu-vp-tests && ./run_smu_vp_tests.sh $(SMU_ARGS)

endif  # VP_FORWARD
