# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_flow_common_mk
ocah_flow_common_mk := 1

# Shared plumbing for the lint/synth/format flows. Included by ocah.mk
# (top-level ocah-lint-slang-all/ocah-synth-all/... dispatch) and by each
# hw/sys/<block>/flow.mk (per-block ocah-lint-slang/ocah-synth worker).
include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/preamble.mk

OCAH_BENDER ?= bender
OCAH_FLOW_COMMON_BENDER_TARGETS ?= -t axi_rtl -t apb_rtl -t common_cells_rtl \
	-t common_cell_sync_shim -t register_interface_l1

# Defines shared by lint and synth so both see the same design.
OCAH_FLOW_COMMON_DEFINES ?= -D SYNTHESIS=1

# Default timescale for files that don't declare their own. Shared by
# flows/lint/slang.mk and flows/synth/yosys/scripts/elab.tcl.
OCAH_FLOW_TIMESCALE ?= 1ns/1ps

# Discover per-block flow descriptors, including vendored IP overlays (e.g.
# vendor/tenstorrent/aou/overlay/flow.mk).
OCAH_FLOW_MKS := $(wildcard $(OCAH_ROOT)/hw/sys/*/flow.mk $(OCAH_ROOT)/hw/ip/*/flow.mk $(OCAH_ROOT)/hw/ip/*/*/flow.mk $(OCAH_ROOT)/vendor/*/*/overlay/flow.mk)

# Directory containing a given flow.mk.
ocah_flow_mkdir = $(patsubst %/flow.mk,%,$(1))

# Block name from a flow.mk path (vendor overlays are named after the
# package directory, not `overlay`).
ocah_flow_name = $(if $(filter overlay,$(notdir $(call ocah_flow_mkdir,$(1)))),$(notdir $(patsubst %/,%,$(dir $(call ocah_flow_mkdir,$(1))))),$(notdir $(call ocah_flow_mkdir,$(1))))

# Sorted unique block names.
OCAH_FLOW_TARGETS := $(sort $(foreach m,$(OCAH_FLOW_MKS),$(call ocah_flow_name,$(m))))

# Block dir for a block name.
ocah_flow_dir_for = $(call ocah_flow_mkdir,$(strip $(foreach m,$(OCAH_FLOW_MKS),$(if $(filter $(1),$(call ocah_flow_name,$(m))),$(m)))))

# Run a command inside the EDA image via the shared docker helper.
# $(1) = command to run inside the EDA image.
ocah_eda_docker_run = $(OCAH_ROOT)/scripts/docker-run.sh eda-run $(1)

# Require a host tool for native-or-fail Make targets. $(1) = binary name.
# $(2) = docker-run.sh example command printed on failure.
ocah_require_host_tool = @command -v "$(1)" >/dev/null 2>&1 || { \
	echo "error: $(1) not found on PATH." >&2; \
	echo "install $(1), or run via the project container:" >&2; \
	echo "  $(2)" >&2; \
	exit 1; \
}

# Native bender flist wrapper; bender always runs on the host, auto-discovering
# Bender.yml from whichever directory it's invoked in.
# $(1) = block-specific bender targets (FLOW_BENDER_TARGETS)
# $(2) = output .f path (relative to the recipe's own CWD)
ocah_eda_flist = $(OCAH_BENDER) script flist-plus $(OCAH_FLOW_COMMON_DEFINES) \
	$(OCAH_FLOW_COMMON_BENDER_TARGETS) $(1) > $(2)

# Fan a goal out to selected blocks as an isolated sub-make (BLOCK=<block>
# picks one, else all discovered blocks). Not named TARGET= to avoid
# colliding with hw/common/regs/classify.mk's register-block namespace check.
# $(1) = goal   $(2) = extra make-var assignments forwarded to each sub-make
ocah_flow_run = @$(foreach b,$(if $(strip $(BLOCK)),$(strip $(BLOCK)),$(OCAH_FLOW_TARGETS)), \
	{ dir="$(call ocah_flow_dir_for,$(b))"; \
	  [ -n "$$dir" ] || { echo "error: unknown flow target '$(b)' (known: $(OCAH_FLOW_TARGETS))" >&2; exit 1; }; \
	  echo "==> $(b): $(1)"; \
	  $(MAKE) -C "$$dir" -f flow.mk OCAH_ROOT="$(OCAH_ROOT)" $(2) $(1); } &&) true

OCAH_UV_RUN := $(UV) --directory "$(OCAH_ROOT)" run --locked

endif
