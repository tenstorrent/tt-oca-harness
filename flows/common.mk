# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_flow_common_mk
ocah_flow_common_mk := 1

# Shared plumbing for the open-source lint/synth/format flows. Included both by
# ocah.mk (top-level dispatch context: exposes ocah-lint/ocah-synth/...) and by
# each hw/sys/<block>/flow.mk (per-block worker context: exposes
# ocah-lint-one/ocah-synth-one, using that block's FLOW_DESIGN/
# FLOW_BENDER_TARGETS). Mirrors hw/common/dv/fw/dispatch.mk's split between
# shared fan-out logic and literal per-tree target lists.
include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/preamble.mk

OCAH_BENDER ?= bender

# Defines shared by every flow.mk block, applied to both lint and synth so
# "lint passed" stays a reliable predictor of "synth will elaborate cleanly"
# (see flows/lint/slang.mk). SYNTHESIS=1 strips simulation-only code guarded by
# `ifndef SYNTHESIS` (assertions, etc.) - the same convention already used
# throughout the vendored RTL (common_cells, hw/common/assert).
OCAH_FLOW_COMMON_DEFINES ?= -D SYNTHESIS=1

# Default time scale for design elements that don't declare their own -
# slang (and yosys-slang, which wraps the same frontend) errors out rather
# than guessing when some files in a filelist have a `timescale` directive
# and others don't, which is unavoidable across a filelist this wide (some
# vendored packages never set one). 1ns/1ps matches the convention already
# used by the large majority of `timescale`-carrying files in this repo.
# Shared by flows/lint/slang.mk and flows/synth/yosys/scripts/elab.tcl so
# lint/synth never disagree on this.
OCAH_FLOW_TIMESCALE ?= 1ns/1ps

# Discover per-block flow descriptors. Breadth matches dispatch.mk's fw
# discovery for the hw/{sys,ip}/* blocks; vendor/*/*/overlay/flow.mk covers
# vendored IP (e.g. vendor/tenstorrent/aou-rtl), which keeps its flow.mk in
# the same `overlay/` subdirectory used repo-wide for TT-specific collateral
# layered onto a vendored package (generated regs, waivers, ...) instead of
# forking the vendored tree - see e.g. vendor/lowRISC/opentitan/overlay/ and
# vendor/pulp-platform/axi/overlay/.
OCAH_FLOW_MKS := $(wildcard $(OCAH_ROOT)/hw/sys/*/flow.mk $(OCAH_ROOT)/hw/ip/*/flow.mk $(OCAH_ROOT)/hw/ip/*/*/flow.mk $(OCAH_ROOT)/vendor/*/*/overlay/flow.mk)

# Directory containing a given flow.mk.
ocah_flow_mkdir = $(patsubst %/flow.mk,%,$(1))

# Block name from a flow.mk path. hw/{sys,ip}/<block>/flow.mk names the block
# after its own directory; vendor/<org>/<pkg>/overlay/flow.mk instead names it
# after <pkg> (the directory containing `overlay/`), since `overlay` itself
# is never the block name.
ocah_flow_name = $(if $(filter overlay,$(notdir $(call ocah_flow_mkdir,$(1)))),$(notdir $(patsubst %/,%,$(dir $(call ocah_flow_mkdir,$(1))))),$(notdir $(call ocah_flow_mkdir,$(1))))

# Sorted unique block names.
OCAH_FLOW_TARGETS := $(sort $(foreach m,$(OCAH_FLOW_MKS),$(call ocah_flow_name,$(m))))

# Block dir for a block name: scan OCAH_FLOW_MKS for the entry whose computed
# name matches (can't just pattern-match "%/$(1)/flow.mk" any more now that
# vendored blocks live under ".../$(1)/overlay/flow.mk").
ocah_flow_dir_for = $(call ocah_flow_mkdir,$(strip $(foreach m,$(OCAH_FLOW_MKS),$(if $(filter $(1),$(call ocah_flow_name,$(m))),$(m)))))

# One-line delegation to the single Docker entry point - all engine detection
# (docker vs. podman), volume flags, and image resolution live in
# scripts/docker-run.sh, the same place they already live for the firmware/doc
# images. $(1) = command to run inside the EDA image.
ocah_eda_docker_run = $(OCAH_ROOT)/scripts/docker-run.sh eda-run $(1)

# Native bender flist wrapper - bender always runs on the host (never inside
# the EDA container) so it resolves against tt-oca's pinned fork, not whatever
# version the image happens to bundle; it also auto-discovers Bender.yml from
# any CWD, so this works whether invoked from OCAH_ROOT or a block dir.
# $(1) = extra block-specific bender targets (FLOW_BENDER_TARGETS)
# $(2) = output .f path (relative to the recipe's own CWD)
ocah_eda_flist = $(OCAH_BENDER) script flist-plus $(OCAH_FLOW_COMMON_DEFINES) $(1) > $(2)

# Fan a goal out to selected blocks as an isolated sub-make (BLOCK=<block>
# picks one, else all discovered blocks; unknown BLOCK errors at run time).
# Deliberately not named TARGET=: hw/common/regs/classify.mk already
# validates a top-level TARGET= against the (disjoint) register-block
# namespace, unconditionally, for every goal - reusing it here would make
# `make lint BLOCK=smu` fail with "Unknown OCAH register block 'smu'" since
# smu/dtp have no registers.
# $(1) = goal   $(2) = extra make-var assignments forwarded to each sub-make
ocah_flow_run = @$(foreach b,$(if $(strip $(BLOCK)),$(strip $(BLOCK)),$(OCAH_FLOW_TARGETS)), \
	{ dir="$(call ocah_flow_dir_for,$(b))"; \
	  [ -n "$$dir" ] || { echo "error: unknown flow target '$(b)' (known: $(OCAH_FLOW_TARGETS))" >&2; exit 1; }; \
	  echo "==> $(b): $(1)"; \
	  $(MAKE) -C "$$dir" -f flow.mk OCAH_ROOT="$(OCAH_ROOT)" $(2) $(1); } &&) true

endif
